param(
    [Parameter(Mandatory = $true)] [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)] [string]$CredentialFile,
    [Parameter(Mandatory = $true)] [string]$DeadlineUtc,
    [int]$WorkerIndex = 7,
    [int]$PollSeconds = 60
)

$ErrorActionPreference = 'Stop'
if ($PollSeconds -lt 30 -or $PollSeconds -gt 300) {
    throw 'PollSeconds must be between 30 and 300'
}
$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$credential = [IO.Path]::GetFullPath($CredentialFile)
$deadline = [DateTimeOffset]::Parse($DeadlineUtc).ToUniversalTime()
if ($deadline -le [DateTimeOffset]::UtcNow.AddHours(1)) {
    throw 'Round-2 deadline must be at least one hour in the future'
}
Set-Location -LiteralPath $repository

$python = Join-Path $repository '.venv\Scripts\python.exe'
$privateRoot = Join-Path $repository 'benchmark\datasets\private\runpod-2026-08-04'
$generated = Join-Path $repository 'benchmark\reports\generated'
$controllerRoot = Join-Path $generated 'folynta-operational-recovery-round2-2026-08-05'
$progressLog = Join-Path $controllerRoot 'progress.jsonl'
$terminalReceipt = Join-Path $controllerRoot 'terminal-receipt.json'
$null = New-Item -ItemType Directory -Path $controllerRoot -Force

function Write-Round2Event {
    param([string]$Event, [hashtable]$Fields = @{})
    $value = [ordered]@{
        event = $Event
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    foreach ($name in $Fields.Keys) { $value[$name] = $Fields[$name] }
    Add-Content -LiteralPath $progressLog `
        -Value ($value | ConvertTo-Json -Compress -Depth 10) -Encoding utf8
}

function Invoke-LoggedPython {
    param([string]$Event, [object[]]$Arguments)
    & $python @Arguments 2>&1 | ForEach-Object {
        Write-Round2Event -Event $Event -Fields @{ line = [string]$_ }
    }
    if ($LASTEXITCODE -ne 0) { throw "$Event failed with exit $LASTEXITCODE" }
}

function Wait-ForPath {
    param([string]$Path, [string]$Event)
    while (-not (Test-Path -LiteralPath $Path)) {
        if ([DateTimeOffset]::UtcNow -ge $deadline) {
            throw "Deadline reached while waiting for $Path"
        }
        Write-Round2Event -Event $Event
        Start-Sleep -Seconds $PollSeconds
    }
}

$operationalTerminal = Join-Path `
    $generated 'runpod-operational-retry-monitor-2026-08-04\terminal-receipt.json'
$firstComposite = Join-Path `
    $generated 'folynta-mineru344-public-core-composite-r1-2026-08-04'
Wait-ForPath -Path $operationalTerminal -Event 'waiting-for-round1-operational-terminal'
$round1 = Get-Content -Raw -LiteralPath $operationalTerminal | ConvertFrom-Json
if ($round1.status -eq 'merged_complete' -and [int]$round1.unresolved -eq 0) {
    $terminal = [ordered]@{
        schema = 'folynta.operational-recovery-round2-terminal.v1'
        status = 'not_needed'
        unresolved_after_round1 = 0
        completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    $terminal | ConvertTo-Json -Depth 6 |
        Set-Content -LiteralPath $terminalReceipt -Encoding utf8
    Write-Round2Event -Event 'round2-not-needed'
    exit 0
}
if ([int]$round1.unresolved -lt 1) {
    throw 'Round-1 operational terminal is neither complete nor recoverable'
}
Wait-ForPath -Path $firstComposite -Event 'waiting-for-round1-composite'
Write-Round2Event -Event 'round2-required' -Fields @{
    unresolved = [int]$round1.unresolved
}

$staging = Join-Path $privateRoot 'operational-recovery-round2-staging'
$planReceipt = Join-Path $staging 'retry-plan-receipt.json'
if (-not (Test-Path -LiteralPath $planReceipt)) {
    $arguments = @(
        (Join-Path $repository 'benchmark\runpod_eval\plan_operational_retries.py')
    )
    for ($index = 0; $index -lt 4; $index++) {
        $arguments += @(
            '--worker-result',
            "$index=$(Join-Path $firstComposite ("worker-{0:d2}" -f $index))"
        )
    }
    $arguments += @(
        '--staged-root', (Join-Path $repository 'benchmark\datasets\private\mineru-public-core-workers-2026-08-04'),
        '--shard-plan', (Join-Path $generated 'folynta-mineru344-public-core-4shard-plan-2026-08-04.json'),
        '--additional-retry-worker-index', [string]$WorkerIndex
    )
    for ($primary = 0; $primary -lt 4; $primary++) {
        $arguments += @('--retry-route', "$primary=$WorkerIndex")
    }
    $arguments += @('--output-root', $staging)
    Invoke-LoggedPython -Event 'round2-staging-output' -Arguments $arguments
}
$plan = Get-Content -Raw -LiteralPath $planReceipt | ConvertFrom-Json
if (
    [int]$plan.failed_input_count -ne [int]$round1.unresolved -or
    [int]$plan.staged_input_count -ne [int]$round1.unresolved -or
    $plan.different_worker_only -ne $true -or
    @($plan.eligible_retry_workers).Count -ne 1 -or
    [int]$plan.eligible_retry_workers[0] -ne $WorkerIndex
) {
    throw 'Round-2 staging does not exactly cover the unresolved inputs'
}
Write-Round2Event -Event 'round2-staged' -Fields @{
    input_count = [int]$plan.failed_input_count
}

$packages = Join-Path $privateRoot 'operational-recovery-round2-packages'
$packageReceipt = Join-Path $packages 'package-receipt.json'
if (-not (Test-Path -LiteralPath $packageReceipt)) {
    Invoke-LoggedPython -Event 'round2-package-output' -Arguments @(
        (Join-Path $repository 'benchmark\runpod_eval\package_operational_retry_inputs.py'),
        '--staging-root', $staging,
        '--output-root', $packages
    )
}
$package = Get-Content -Raw -LiteralPath $packageReceipt | ConvertFrom-Json
if ([int]$package.input_count -ne [int]$plan.failed_input_count) {
    throw 'Round-2 package coverage differs from its plan'
}

$provisionScript = Join-Path `
    $repository 'tools\release\provision_folynta_mineru_recovery_worker.ps1'
$provisioning = Join-Path `
    $privateRoot 'mineru-operational-recovery-r2\provisioning-receipt.json'
if (-not (Test-Path -LiteralPath $provisioning)) {
    & $provisionScript -RepositoryRoot $repository -CredentialFile $credential `
        -DeadlineUtc $deadline.ToString('o') -WorkerIndex $WorkerIndex `
        -PollSeconds ([Math]::Max(10, [Math]::Min(120, $PollSeconds))) 2>&1 |
        ForEach-Object {
            Write-Round2Event -Event 'round2-provision-output' -Fields @{ line = [string]$_ }
        }
    if ($LASTEXITCODE -ne 0) { throw 'Round-2 MinerU worker provisioning failed' }
}
$provisioned = Get-Content -Raw -LiteralPath $provisioning | ConvertFrom-Json
if (
    $provisioned.status -ne 'ready_identity_bound_and_smoke_passed' -or
    [int]$provisioned.worker_index -ne $WorkerIndex -or
    [string]$provisioned.model_artifact_manifest_sha256 -ne `
        'sha256:1611a8892cc0e7e287d31c4a1b5af87652f0f6e4a3f80276b92b4c71f982de84'
) {
    throw 'Round-2 MinerU worker identity gate failed'
}
Write-Round2Event -Event 'round2-worker-ready' -Fields @{
    pod_id = [string]$provisioned.pod_id
    gpu = [string]$provisioned.gpu
    hourly_rate_usd = [double]$provisioned.hourly_rate_usd
}

$launchReceipt = Join-Path $controllerRoot 'launch-receipt.json'
if (-not (Test-Path -LiteralPath $launchReceipt)) {
    Invoke-LoggedPython -Event 'round2-launch-output' -Arguments @(
        (Join-Path $repository 'benchmark\runpod_eval\launch_operational_retry_workers.py'),
        '--repository-root', $repository,
        '--config', [string]$provisioned.config,
        '--package-receipt', $packageReceipt,
        '--package-root', $packages,
        '--mineru-runner', (Join-Path $repository 'benchmark\runpod_eval\mineru_stage2.py'),
        '--retry-runner', (Join-Path $repository 'benchmark\runpod_eval\remote_run_operational_retry.sh'),
        '--stall-watchdog', (Join-Path $repository 'benchmark\runpod_eval\remote_stall_watchdog.sh'),
        '--output-receipt', $launchReceipt
    )
}
$launch = Get-Content -Raw -LiteralPath $launchReceipt | ConvertFrom-Json
if (
    [int]$launch.worker_count -ne 1 -or
    [int]$launch.input_count -ne [int]$plan.failed_input_count
) {
    throw 'Round-2 launch coverage is invalid'
}

$key = Join-Path $privateRoot 'builder_ed25519'
$knownHosts = Join-Path $privateRoot 'known_hosts'
$hostName = [string]$provisioned.host
$port = [int]$provisioned.port
$remoteRoot = '/workspace/folynta/results/operational-retry'
$runnerPid = [int]$launch.launches[0].runner_pid
$watchdogPattern = '[/]workspace/folynta/runner/remote_stall_watchdog.sh'
$suites = @($plan.workers[0].suites | ForEach-Object { [string]$_.benchmark_id })
if (-not $suites.Count) { throw 'Round-2 launch has no routed suites' }
while ($true) {
    if ([DateTimeOffset]::UtcNow -ge $deadline) {
        throw 'Round-2 inference exceeded its deadline'
    }
    $checks = @($suites | ForEach-Object {
        "test -s '$remoteRoot/$_/run-summary.json'"
    }) -join ' && '
    $command = "if $checks; then echo COMPLETE; " +
        "elif ! kill -0 $runnerPid 2>/dev/null; then echo FAILED; " +
        "elif pgrep -f '$watchdogPattern' >/dev/null; then echo RUNNING; " +
        "else echo WATCHDOG_FAILED; fi"
    $status = (& ssh -i $key -o BatchMode=yes -o ConnectTimeout=20 `
        -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$knownHosts" `
        -p $port "root@$hostName" $command).Trim()
    if ($LASTEXITCODE -ne 0) {
        Write-Round2Event -Event 'round2-ssh-poll-failed'
        Start-Sleep -Seconds $PollSeconds
        continue
    }
    Write-Round2Event -Event 'round2-inference-poll' -Fields @{ status = $status }
    if ($status -eq 'COMPLETE') { break }
    if ($status -eq 'WATCHDOG_FAILED') {
        $restartCommand = "nohup bash /workspace/folynta/runner/remote_stall_watchdog.sh " +
            "2100 60 '$remoteRoot' >'$remoteRoot.stall-watchdog.stdout.log' " +
            "2>'$remoteRoot.stall-watchdog.stderr.log' < /dev/null & " +
            "sleep 2; pgrep -n -f '$watchdogPattern'"
        $replacementPid = (& ssh -i $key -o BatchMode=yes -o ConnectTimeout=20 `
            -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$knownHosts" `
            -p $port "root@$hostName" $restartCommand).Trim()
        if ($LASTEXITCODE -ne 0 -or $replacementPid -notmatch '^[0-9]+$') {
            Write-Round2Event -Event 'round2-stall-watchdog-restart-failed'
            Start-Sleep -Seconds $PollSeconds
            continue
        }
        Write-Round2Event -Event 'round2-stall-watchdog-restarted' -Fields @{
            watchdog_pid = [int]$replacementPid
        }
        Start-Sleep -Seconds $PollSeconds
        continue
    }
    if ($status -eq 'FAILED') {
        $stderrTail = & ssh -i $key -o BatchMode=yes -o ConnectTimeout=20 `
            -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$knownHosts" `
            -p $port "root@$hostName" `
            "tail -120 '$remoteRoot.launcher.stderr.log' 2>/dev/null || true"
        Write-Round2Event -Event 'round2-inference-failed' -Fields @{
            stderr_tail = [string]($stderrTail -join "`n")
        }
        throw 'Round-2 inference process failed'
    }
    Start-Sleep -Seconds $PollSeconds
}

$collection = Join-Path $privateRoot 'collected-operational-recovery-round2'
$collectionReceipt = Join-Path `
    $collection ("worker-{0:d2}-operational-retry-collection.json" -f $WorkerIndex)
if (-not (Test-Path -LiteralPath $collectionReceipt)) {
    $arguments = @(
        (Join-Path $repository 'benchmark\runpod_eval\collect_operational_retry_worker.py'),
        '--worker-index', [string]$WorkerIndex,
        '--host', $hostName,
        '--port', [string]$port,
        '--key', $key,
        '--known-hosts', $knownHosts,
        '--output-root', $collection
    )
    foreach ($suite in $suites) { $arguments += @('--suite', $suite) }
    Invoke-LoggedPython -Event 'round2-collection-output' -Arguments $arguments
}
$collected = Get-Content -Raw -LiteralPath $collectionReceipt | ConvertFrom-Json
if (
    [int]$collected.worker_index -ne $WorkerIndex -or
    (@($collected.summaries | Measure-Object -Property input_count -Sum).Sum) -ne `
        [int]$plan.failed_input_count
) {
    throw 'Round-2 collection coverage is invalid'
}
Write-Round2Event -Event 'round2-collection-verified' -Fields @{
    archive_sha256 = [string]$collected.archive_sha256
}

$line = Get-Content -LiteralPath $credential |
    Where-Object { $_ -match '^\s*Runpod\s*:' } | Select-Object -First 1
if (-not $line) { throw 'RunPod credential label not found for cleanup' }
$apiKey = ($line -split ':', 2)[1].Trim()
$headers = @{ Authorization = "Bearer $apiKey"; Accept = 'application/json' }
$podId = [string]$provisioned.pod_id
$uri = "https://rest.runpod.io/v1/pods/$podId"
try {
    $provider = Invoke-RestMethod -Method Get -Uri $uri -Headers $headers -TimeoutSec 30
    if ([string]$provider.id -ne $podId) { throw 'Round-2 cleanup Pod identity mismatch' }
    $null = Invoke-RestMethod -Method Delete -Uri $uri -Headers $headers -TimeoutSec 30
}
catch {
    if ($_.Exception.Response.StatusCode.value__ -ne 404) { throw }
}
$absent = $false
for ($attempt = 1; $attempt -le 20; $attempt++) {
    try {
        $null = Invoke-RestMethod -Method Get -Uri $uri -Headers $headers -TimeoutSec 30
    }
    catch {
        if ($_.Exception.Response.StatusCode.value__ -eq 404) {
            $absent = $true
            break
        }
    }
    Start-Sleep -Seconds 10
}
if (-not $absent) { throw 'Round-2 Pod provider absence was not verified' }
Write-Round2Event -Event 'round2-pod-deleted' -Fields @{ pod_id = $podId }

$secondComposite = Join-Path `
    $generated 'folynta-mineru344-public-core-composite-r2-2026-08-05'
if (-not (Test-Path -LiteralPath $secondComposite)) {
    $arguments = @(
        (Join-Path $repository 'benchmark\runpod_eval\apply_operational_retries.py')
    )
    for ($index = 0; $index -lt 4; $index++) {
        $arguments += @(
            '--primary',
            "$index=$(Join-Path $firstComposite ("worker-{0:d2}" -f $index))"
        )
    }
    $arguments += @(
        '--retry', "$WorkerIndex=$(Join-Path $collection ("worker-{0:d2}" -f $WorkerIndex))",
        '--retry-plan', $planReceipt,
        '--output-root', $secondComposite
    )
    Invoke-LoggedPython -Event 'round2-overlay-output' -Arguments $arguments
}

$secondMerged = Join-Path `
    $generated 'folynta-mineru344-public-core-merged-r2-2026-08-05'
if (-not (Test-Path -LiteralPath $secondMerged)) {
    $arguments = @((Join-Path $repository 'benchmark\runpod_eval\public_core_merge.py'))
    for ($index = 0; $index -lt 4; $index++) {
        $arguments += @(
            '--worker',
            "$index=$(Join-Path $secondComposite ("worker-{0:d2}" -f $index))"
        )
    }
    $arguments += @(
        '--staged-root', (Join-Path $repository 'benchmark\datasets\staged-public-core'),
        '--shard-plan', (Join-Path $generated 'folynta-mineru344-public-core-4shard-plan-2026-08-04.json'),
        '--output-root', $secondMerged
    )
    Invoke-LoggedPython -Event 'round2-merge-output' -Arguments $arguments
}
$merge = Get-Content -Raw -LiteralPath (Join-Path $secondMerged 'merge-receipt.json') |
    ConvertFrom-Json
$status = if (
    [int]$merge.completed -eq 5132 -and [int]$merge.failed -eq 0 -and
    $merge.complete_case_coverage -eq $true
) { 'merged_complete' } else { 'merged_with_unresolved_after_round2' }
$operational = [ordered]@{
    schema = 'folynta.operational-retry-monitor-terminal.v1'
    status = $status
    planned = 1788
    round2_planned = [int]$plan.failed_input_count
    completed = [int]$merge.completed
    unresolved = [int]$merge.failed
    merged_root = $secondMerged
    round2_pod_id = $podId
    round2_pod_deleted = $true
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$operational | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $operationalTerminal -Encoding utf8
Write-Round2Event -Event $status -Fields @{ unresolved = [int]$merge.failed }
if ($status -ne 'merged_complete') {
    $terminal = [ordered]@{
        schema = 'folynta.operational-recovery-round2-terminal.v1'
        status = 'additional_model_recovery_required'
        unresolved = [int]$merge.failed
        merged_root = $secondMerged
        completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    $terminal | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath $terminalReceipt -Encoding utf8
    exit 4
}

$evaluationRoot = Join-Path `
    $generated 'folynta-mineru344-public-core-official-evaluations-r1-2026-08-04'
$failureRecords = Join-Path `
    $generated 'folynta-mineru344-public-failure-records-r1-2026-08-04.json'
$qualityStaging = Join-Path `
    $privateRoot 'mineru-quality-retry-staging-r1'
& (Join-Path $repository 'tools\release\continue_folynta_official_evaluations.ps1') `
    -RepositoryRoot $repository -OperationalTerminal $operationalTerminal `
    -MergedRoot $secondMerged -EvaluationRoot $evaluationRoot `
    -FailureRecords $failureRecords -QualityRetryStaging $qualityStaging `
    -PollSeconds $PollSeconds
if ($LASTEXITCODE -ne 0) { throw 'Official evaluation controller failed after round 2' }

$terminal = [ordered]@{
    schema = 'folynta.operational-recovery-round2-terminal.v1'
    status = 'merged_complete_and_official_evaluation_started'
    input_count = 5132
    recovered_input_count = [int]$plan.failed_input_count
    unresolved = 0
    merged_root = $secondMerged
    pod_id = $podId
    pod_deleted = $true
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$terminal | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $terminalReceipt -Encoding utf8
Write-Round2Event -Event 'round2-controller-complete'
exit 0
