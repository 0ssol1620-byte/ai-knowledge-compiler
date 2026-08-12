param(
    [Parameter(Mandatory = $true)] [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)] [string]$CredentialFile,
    [Parameter(Mandatory = $true)] [string]$HostName,
    [Parameter(Mandatory = $true)] [int]$Port,
    [Parameter(Mandatory = $true)] [string]$PodId,
    [Parameter(Mandatory = $true)] [string]$BootstrapTerminal,
    [Parameter(Mandatory = $true)] [string]$DeadlineUtc,
    [string]$RemoteBootstrapSlug = 'deepseek-operational-r2',
    [int]$PollSeconds = 60
)

$ErrorActionPreference = 'Stop'
if ($PollSeconds -lt 30 -or $PollSeconds -gt 300) { throw 'PollSeconds is invalid' }
$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$credential = [IO.Path]::GetFullPath($CredentialFile)
$bootstrapTerminalPath = [IO.Path]::GetFullPath($BootstrapTerminal)
$deadline = [DateTimeOffset]::Parse($DeadlineUtc).ToUniversalTime()
$python = Join-Path $repository '.venv\Scripts\python.exe'
$generated = Join-Path $repository 'benchmark\reports\generated'
$private = Join-Path $repository 'benchmark\datasets\private\runpod-2026-08-04'
$controllerRoot = Join-Path $generated 'folynta-preofficial-hybrid-deepseek-r1-2026-08-06'
$progressLog = Join-Path $controllerRoot 'progress.jsonl'
$terminalReceipt = Join-Path $controllerRoot 'terminal-receipt.json'
$null = New-Item -ItemType Directory -Path $controllerRoot -Force

function Write-Event {
    param([string]$Event, [hashtable]$Fields = @{})
    $value = [ordered]@{ event = $Event; observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o') }
    foreach ($key in $Fields.Keys) { $value[$key] = $Fields[$key] }
    Add-Content -LiteralPath $progressLog -Value ($value | ConvertTo-Json -Compress -Depth 10) -Encoding utf8
}
function Invoke-LoggedPython {
    param([string]$Event, [object[]]$Arguments)
    $savedPreference = $ErrorActionPreference; $exitCode = 0
    try {
        $ErrorActionPreference = 'Continue'
        & $python @Arguments 2>&1 | ForEach-Object { Write-Event -Event $Event -Fields @{ line = [string]$_ } }
        $exitCode = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $savedPreference }
    if ($exitCode -ne 0) { throw "$Event failed with exit $exitCode" }
}

while (-not (Test-Path -LiteralPath $bootstrapTerminalPath)) {
    if ([DateTimeOffset]::UtcNow -ge $deadline) { throw 'DeepSeek bootstrap deadline' }
    Write-Event -Event 'waiting-for-deepseek-bootstrap'; Start-Sleep -Seconds $PollSeconds
}
$bootstrap = Get-Content -Raw -LiteralPath $bootstrapTerminalPath | ConvertFrom-Json
if ($bootstrap.status -ne 'runtime_ready' -or [string]$bootstrap.pod_id -ne $PodId) { throw 'DeepSeek bootstrap identity is invalid' }

$collection = Join-Path $private 'preofficial-operational-deepseek-collection-r1'
$collectionReceipt = Join-Path $collection 'collection-receipt.json'
if (Test-Path -LiteralPath $collectionReceipt) {
    Write-Event -Event 'deepseek-collection-resume' -Fields @{ pod_id = $PodId }
}
else {
    $baseConfig = Get-Content -Raw -LiteralPath (Join-Path $private 'public-core-workers.json') | ConvertFrom-Json
    $key = [IO.Path]::GetFullPath((Join-Path $repository ([string]$baseConfig.key)))
    $knownHosts = Join-Path $private 'deepseek-recovery\known_hosts'
    $sshArgs = @('-i',$key,'-p',[string]$Port,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$knownHosts",'-o','KexAlgorithms=curve25519-sha256','-o','ConnectTimeout=15')
    & ssh @sshArgs "root@$HostName" (
        "test -f /workspace/folynta/bootstrap/$RemoteBootstrapSlug/runtime-identity.json && " +
        "ln -sfn /workspace/folynta/bootstrap/$RemoteBootstrapSlug /workspace/folynta/bootstrap/deepseek-r1"
    )
    if ($LASTEXITCODE -ne 0) { throw 'DeepSeek runtime identity alias failed' }
    Write-Event -Event 'deepseek-runtime-identity-bound' -Fields @{ pod_id = $PodId }

    $packages = Join-Path $private 'preofficial-operational-deepseek-packages-r1'
    $launchReceipt = Join-Path $controllerRoot 'launch-receipt.json'
    if (-not (Test-Path -LiteralPath $launchReceipt)) {
        Invoke-LoggedPython -Event 'deepseek-launch-output' -Arguments @(
            (Join-Path $repository 'benchmark\runpod_eval\launch_dedicated_recovery.py'),
            '--repository-root',$repository,'--model','deepseek-ocr-2','--host',$HostName,'--port',[string]$Port,'--pod-id',$PodId,
            '--key',$key,'--known-hosts',$knownHosts,'--package-receipt',(Join-Path $packages 'package-receipt.json'),'--package-root',$packages,
            '--model-runner',(Join-Path $repository 'benchmark\runpod_eval\deepseek_ocr2_stage2.py'),
            '--campaign-runner',(Join-Path $repository 'benchmark\runpod_eval\remote_run_dedicated_recovery.sh'),
            '--input-contract',(Join-Path $repository 'benchmark\runpod_eval\input_contract.py'),
            '--isolated-process',(Join-Path $repository 'benchmark\runpod_eval\isolated_case_process.py'),'--output-receipt',$launchReceipt
        )
    }
    $launch = Get-Content -Raw -LiteralPath $launchReceipt | ConvertFrom-Json
    $runnerPid = [int]$launch.runner_pid
    $remoteRoot = '/workspace/folynta/results/deepseek-r1'
    while ($true) {
        if ([DateTimeOffset]::UtcNow -ge $deadline) { throw 'DeepSeek campaign deadline' }
        $command = "if test -f '$remoteRoot/campaign-state.jsonl' && tail -1 '$remoteRoot/campaign-state.jsonl' | grep -F 'dedicated_recovery_completed' >/dev/null; then echo COMPLETE; elif kill -0 $runnerPid 2>/dev/null; then echo RUNNING; else echo FAILED; fi"
        $status = (& ssh @sshArgs "root@$HostName" $command).Trim()
        if ($LASTEXITCODE -ne 0) { Write-Event -Event 'deepseek-ssh-poll-failed'; Start-Sleep -Seconds $PollSeconds; continue }
        Write-Event -Event 'deepseek-campaign-poll' -Fields @{ status = $status }
        if ($status -eq 'COMPLETE') { break }
        if ($status -eq 'FAILED') {
            $tail = & ssh @sshArgs "root@$HostName" "tail -120 '$remoteRoot.launcher.stderr.log' 2>/dev/null || true"
            Write-Event -Event 'deepseek-campaign-failed' -Fields @{ stderr_tail = [string]($tail -join "`n") }
            throw 'DeepSeek dedicated campaign failed'
        }
        Start-Sleep -Seconds $PollSeconds
    }
    Invoke-LoggedPython -Event 'deepseek-collection-output' -Arguments @(
        (Join-Path $repository 'benchmark\runpod_eval\collect_dedicated_recovery.py'),'--model','deepseek-ocr-2','--host',$HostName,'--port',[string]$Port,
        '--key',$key,'--known-hosts',$knownHosts,'--launch-receipt',$launchReceipt,'--output-root',$collection
    )
}

$line = Get-Content -LiteralPath $credential | Where-Object { $_ -match '^\s*Runpod\s*:' } | Select-Object -First 1
if (-not $line) { throw 'RunPod credential label not found for cleanup' }
$apiKey = ($line -split ':',2)[1].Trim(); $headers = @{ Authorization = "Bearer $apiKey"; Accept = 'application/json' }
$uri = "https://rest.runpod.io/v1/pods/$PodId"
try { $null = Invoke-RestMethod -Method Delete -Uri $uri -Headers $headers -TimeoutSec 30 } catch { if ($_.Exception.Response.StatusCode.value__ -ne 404) { throw } }
for ($attempt=1;$attempt -le 20;$attempt++) {
    try { $null=Invoke-RestMethod -Method Get -Uri $uri -Headers $headers -TimeoutSec 30 } catch { if ($_.Exception.Response.StatusCode.value__ -eq 404) { break } }
    if ($attempt -eq 20) { throw 'DeepSeek Pod provider absence was not verified' }; Start-Sleep -Seconds 10
}
Write-Event -Event 'deepseek-pod-deleted' -Fields @{ pod_id = $PodId }

$baseline = Join-Path $generated 'folynta-composite-r3-paddle-op-2026-08-06'
$staging = Join-Path $private 'preofficial-operational-deepseek-staging-r1'
$candidate = Join-Path $generated 'folynta-composite-r4-hybrid-2026-08-06'
if (-not (Test-Path -LiteralPath $candidate)) {
    $arguments=@((Join-Path $repository 'benchmark\runpod_eval\apply_alternate_candidates.py'))
    for($index=0;$index -lt 4;$index++){ $arguments += @('--baseline',"$index=$(Join-Path $baseline ("worker-{0:d2}" -f $index))") }
    $arguments += @('--recovery-root',(Join-Path $collection 'evidence'),'--selective-plan',(Join-Path $staging 'selective-recovery-receipt.json'),'--recovery-model','deepseek-ocr-2','--operational-failure-targets','--paddle-layout-fallback-root',(Join-Path $private 'preofficial-operational-paddle-collection-r1\evidence'),'--output-root',$candidate)
    Invoke-LoggedPython -Event 'hybrid-overlay-output' -Arguments $arguments
}
$merged = Join-Path $generated 'folynta-merged-r4-hybrid-2026-08-06'
if (-not (Test-Path -LiteralPath $merged)) {
    $arguments=@((Join-Path $repository 'benchmark\runpod_eval\public_core_merge.py'))
    for($index=0;$index -lt 4;$index++){ $arguments += @('--worker',"$index=$(Join-Path $candidate ("worker-{0:d2}" -f $index))") }
    $arguments += @('--staged-root',(Join-Path $repository 'benchmark\datasets\staged-public-core'),'--shard-plan',(Join-Path $generated 'folynta-mineru344-public-core-4shard-plan-2026-08-04.json'),'--output-root',$merged)
    Invoke-LoggedPython -Event 'hybrid-merge-output' -Arguments $arguments
}
$merge = Get-Content -Raw -LiteralPath (Join-Path $merged 'merge-receipt.json') | ConvertFrom-Json
if ([int]$merge.completed -ne 5132 -or [int]$merge.failed -ne 0) { throw 'Hybrid recovery did not achieve 5,132/5,132 coverage' }
[ordered]@{schema='folynta.preofficial-hybrid-deepseek-terminal.v1';status='merged_complete';input_count=5132;completed=5132;unresolved=0;composite_root=$candidate;merged_root=$merged;pod_id=$PodId;pod_deleted=$true;completed_at_utc=[DateTimeOffset]::UtcNow.ToString('o')} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $terminalReceipt -Encoding utf8
Write-Event -Event 'hybrid-merged-complete'

$operationalTerminal = Join-Path $generated 'runpod-operational-retry-monitor-2026-08-04\terminal-receipt.json'
[ordered]@{schema='folynta.operational-retry-monitor-terminal.v1';status='merged_complete';planned=1788;round2_planned=20;alternate_model_planned=18;hybrid_model_planned=4;completed=5132;unresolved=0;merged_root=$merged;round2_pod_deleted=$true;paddle_operational_pod_deleted=$true;deepseek_operational_pod_deleted=$true;completed_at_utc=[DateTimeOffset]::UtcNow.ToString('o')} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $operationalTerminal -Encoding utf8

& (Join-Path $repository 'tools\release\continue_folynta_official_evaluations.ps1') -RepositoryRoot $repository -OperationalTerminal $operationalTerminal -MergedRoot $merged -EvaluationRoot (Join-Path $generated 'folynta-mineru344-public-core-official-evaluations-r1-2026-08-04') -FailureRecords (Join-Path $generated 'folynta-mineru344-public-failure-records-r1-2026-08-04.json') -QualityRetryStaging (Join-Path $private 'mineru-quality-retry-staging-r1') -PollSeconds $PollSeconds
if ($LASTEXITCODE -ne 0) { throw 'Official evaluation controller failed after hybrid recovery' }
Write-Event -Event 'preofficial-hybrid-controller-complete'
