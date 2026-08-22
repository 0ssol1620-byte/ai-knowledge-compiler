param(
    [Parameter(Mandatory = $true)] [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)] [string]$CredentialFile,
    [Parameter(Mandatory = $true)] [string]$DeadlineUtc,
    # Recorded folynta.recovery-execution-decision.v1 receipt, forwarded to the
    # alternate-recovery controller. Absent means every lane runs.
    [string]$ExecutionDecision,
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
    throw 'DeadlineUtc must be at least one hour in the future'
}
Set-Location -LiteralPath $repository
$generated = Join-Path $repository 'benchmark\reports\generated'
$controllerRoot = Join-Path `
    $generated 'folynta-post-selection-recovery-audit-2026-08-05'
$progress = Join-Path $controllerRoot 'progress.jsonl'
$terminal = Join-Path $controllerRoot 'terminal-receipt.json'
$null = New-Item -ItemType Directory -Path $controllerRoot -Force

function Write-PipelineEvent {
    param([string]$Event, [hashtable]$Fields = @{})
    $payload = [ordered]@{
        event = $Event
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    foreach ($name in $Fields.Keys) { $payload[$name] = $Fields[$name] }
    # Shared append-only log: retry through transient sharing violations instead
    # of ending an otherwise healthy campaign. $ErrorActionPreference is Stop,
    # which wraps the IOException, so the retry catches broadly.
    $line = $payload | ConvertTo-Json -Compress -Depth 10
    for ($attempt = 1; $attempt -le 40; $attempt++) {
        try {
            Add-Content -LiteralPath $progress -Value $line -Encoding utf8 -ErrorAction Stop
            return
        }
        catch {
            if ($attempt -eq 40) { throw }
            Start-Sleep -Milliseconds 250
        }
    }
}

function Wait-ForFile {
    param([string]$Path, [string]$Event)
    while (-not (Test-Path -LiteralPath $Path)) {
        if ([DateTimeOffset]::UtcNow -ge $deadline) {
            throw "Deadline reached while waiting for $Path"
        }
        Write-PipelineEvent -Event $Event
        Start-Sleep -Seconds $PollSeconds
    }
}

function Start-Controller {
    param([string]$Name, [string]$Script, [object[]]$Arguments)
    $stdout = Join-Path $controllerRoot "$Name.stdout.log"
    $stderr = Join-Path $controllerRoot "$Name.stderr.log"
    $processArguments = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Script
    ) + $Arguments
    $child = Start-Process -FilePath 'powershell.exe' `
        -ArgumentList $processArguments `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
        -WindowStyle Hidden -PassThru
    Write-PipelineEvent -Event 'controller-started' -Fields @{
        name = $Name
        process_id = $child.Id
        process = $child
    }
    return [pscustomobject]@{
        name = $Name
        # Wait-Controller polls this handle. Omitting it made the first wait
        # throw InvokeMethodOnNull and abandon a child that was running fine.
        process = $child
        process_id = $child.Id
        stdout = $stdout
        stderr = $stderr
    }
}

function Wait-Controller {
    param([pscustomobject]$Controller)
    $process = $Controller.process
    if ($null -eq $process) {
        $process = Get-Process -Id ([int]$Controller.process_id) -ErrorAction SilentlyContinue
    }
    while ($null -ne $process -and -not $process.HasExited) {
        if ([DateTimeOffset]::UtcNow -ge $deadline) {
            throw "Controller deadline reached: $($Controller.name)"
        }
        Start-Sleep -Seconds $PollSeconds
        $process.Refresh()
    }
    $stderrTail = if (Test-Path -LiteralPath $Controller.stderr) {
        (Get-Content -LiteralPath $Controller.stderr -Tail 100) -join "`n"
    }
    else { '' }
    if ($stderrTail.Trim()) {
        Write-PipelineEvent -Event 'controller-stderr-observed' -Fields @{
            name = $Controller.name
            stderr_tail = $stderrTail
        }
    }
    if ($null -eq $process) {
        throw "Controller handle was lost before completion: $($Controller.name)"
    }
    if ([int]$process.ExitCode -ne 0) {
        throw "Controller failed: $($Controller.name), exit $($process.ExitCode)"
    }
}

$poolTerminal = Join-Path `
    $generated 'folynta-post-baseline-mineru-pool-2026-08-05\terminal-receipt.json'
Write-PipelineEvent -Event 'waiting-for-post-baseline-mineru-pool'
Wait-ForFile -Path $poolTerminal -Event 'waiting-for-post-baseline-mineru-pool'
$pool = Get-Content -Raw -LiteralPath $poolTerminal | ConvertFrom-Json
if ($pool.status -ne 'post_mineru_selection_complete_pool_retained_for_audit') {
    throw 'Post-baseline MinerU pool terminal is invalid'
}
$postTerminal = [IO.Path]::GetFullPath([string]$pool.post_mineru_terminal)
$post = Get-Content -Raw -LiteralPath $postTerminal | ConvertFrom-Json
if ($post.status -ne 'alternate_recovery_staged') {
    throw 'Post-MinerU selection terminal is invalid'
}
Write-PipelineEvent -Event 'post-mineru-selection-observed' -Fields @{
    paddle_case_count = [int]$post.paddle_case_count
    deepseek_case_count = [int]$post.deepseek_case_count
}

$audit = Start-Controller `
    -Name 'stratified-audit' `
    -Script (Join-Path $repository 'tools\release\continue_folynta_stratified_audit.ps1') `
    -Arguments @(
        '-RepositoryRoot', $repository,
        '-PostMineruTerminal', $postTerminal,
        '-DeadlineUtc', $deadline.ToString('o'),
        '-ConfigPath', [string]$pool.pool_config,
        '-PoolReceipt', [string]$pool.pool_receipt,
        '-PollSeconds', [string]$PollSeconds
    )

$dedicated = @(
    [ordered]@{
        slug = 'paddle'
        role = 'paddleocr-vl-1.6'
        pod_id = '8q4p95vk8aqrqc'
        name = 'folynta-paddleocr-vl16-recovery-r1'
        case_count = [int]$post.paddle_case_count
        initial_terminal = Join-Path $generated `
            'folynta-paddle-recovery-bootstrap-2026-08-04\terminal-receipt.json'
    },
    [ordered]@{
        slug = 'deepseek'
        role = 'deepseek-ocr-2'
        pod_id = '68lo3k8a2lft1i'
        name = 'folynta-deepseek-ocr2-recovery-r1'
        case_count = [int]$post.deepseek_case_count
        initial_terminal = Join-Path $generated `
            'folynta-deepseek-recovery-bootstrap-2026-08-04\terminal-receipt.json'
    }
)
$bootstrapChildren = @()
foreach ($item in $dedicated) {
    if ([int]$item.case_count -le 0) {
        $initial = Get-Content -Raw -LiteralPath $item.initial_terminal | ConvertFrom-Json
        $item['host'] = [string]$initial.host
        $item['port'] = [int]$initial.port
        $item['bootstrap_terminal'] = [string]$item.initial_terminal
        Write-PipelineEvent -Event 'dedicated-recovery-not-needed' -Fields @{
            role = [string]$item.role
        }
        continue
    }
    $resumeReceipt = Join-Path $controllerRoot "$($item.slug)-resume-receipt.json"
    & (Join-Path $repository 'tools\release\resume_folynta_runpod_pod.ps1') `
        -RepositoryRoot $repository -CredentialFile $credential `
        -PodId ([string]$item.pod_id) -ExpectedName ([string]$item.name) `
        -ReceiptOut $resumeReceipt -DeadlineUtc $deadline.ToString('o') `
        -PollSeconds ([Math]::Max(10, [Math]::Min(120, $PollSeconds)))
    if ($LASTEXITCODE -ne 0) { throw "Failed to resume $($item.role) Pod" }
    $resumed = Get-Content -Raw -LiteralPath $resumeReceipt | ConvertFrom-Json
    $item['host'] = [string]$resumed.host
    $item['port'] = [int]$resumed.port
    $stateSlug = "resume-r1-2026-08-05"
    $bootstrapTerminal = Join-Path `
        $generated `
        "folynta-$($item.slug)-recovery-bootstrap-$stateSlug\terminal-receipt.json"
    $item['bootstrap_terminal'] = $bootstrapTerminal
    $bootstrapChildren += Start-Controller `
        -Name "$($item.slug)-bootstrap" `
        -Script (Join-Path $repository 'tools\release\bootstrap_folynta_dedicated_recovery_pod.ps1') `
        -Arguments @(
            '-Role', [string]$item.role,
            '-RepositoryRoot', $repository,
            '-HostName', [string]$resumed.host,
            '-Port', [string]$resumed.port,
            '-PodId', [string]$item.pod_id,
            '-DeadlineUtc', $deadline.ToString('o'),
            '-StateSlug', $stateSlug,
            '-RemoteReceiptSlug', "$($item.slug)-resume-r1",
            '-PollSeconds', [string]$PollSeconds
        )
}
foreach ($child in $bootstrapChildren) { Wait-Controller -Controller $child }
foreach ($item in $dedicated | Where-Object { [int]$_.case_count -gt 0 }) {
    Wait-ForFile -Path ([string]$item.bootstrap_terminal) `
        -Event "waiting-for-$($item.slug)-bootstrap"
    $identity = Get-Content -Raw -LiteralPath $item.bootstrap_terminal | ConvertFrom-Json
    if (
        $identity.status -ne 'runtime_ready' -or
        [string]$identity.pod_id -ne [string]$item.pod_id -or
        [string]$identity.host -ne [string]$item.host -or
        [int]$identity.port -ne [int]$item.port
    ) {
        throw "Dedicated recovery identity gate failed: $($item.role)"
    }
}

$paddle = $dedicated[0]
$deepseek = $dedicated[1]
$alternateArguments = @{
    RepositoryRoot = $repository
    PostMineruTerminal = $postTerminal
    PaddleBootstrapTerminal = [string]$paddle.bootstrap_terminal
    DeepSeekBootstrapTerminal = [string]$deepseek.bootstrap_terminal
    PaddleHost = [string]$paddle.host
    PaddlePort = [int]$paddle.port
    PaddlePodId = [string]$paddle.pod_id
    DeepSeekHost = [string]$deepseek.host
    DeepSeekPort = [int]$deepseek.port
    DeepSeekPodId = [string]$deepseek.pod_id
    BaselinePodIdCsv = 'xk1371aijxy7hm,p2tvagqhw6almp,12lbrsp8nz0oie,rop1r15ph47bx6'
    DeadlineUtc = $deadline.ToString('o')
    PollSeconds = $PollSeconds
}
if ($ExecutionDecision) {
    $alternateArguments['ExecutionDecision'] = $ExecutionDecision
}
& (Join-Path $repository 'tools\release\continue_folynta_alternate_recovery.ps1') `
    @alternateArguments
if ($LASTEXITCODE -ne 0) { throw 'Alternate recovery controller failed' }
Write-PipelineEvent -Event 'alternate-recovery-complete'

Wait-Controller -Controller $audit
$auditResult = Join-Path `
    $repository 'benchmark\datasets\private\runpod-2026-08-04\stratified-audit-results-r1\terminal-receipt.json'
Wait-ForFile -Path $auditResult -Event 'waiting-for-stratified-audit-result'

$evaluation = Start-Controller `
    -Name 'stratified-audit-evaluation' `
    -Script (Join-Path $repository 'tools\release\continue_folynta_stratified_audit_evaluation.ps1') `
    -Arguments @(
        '-RepositoryRoot', $repository,
        '-DeadlineUtc', $deadline.ToString('o'),
        '-PollSeconds', [string]$PollSeconds
    )
$detection = Start-Controller `
    -Name 'operational-detection-evaluation' `
    -Script (Join-Path $repository 'tools\release\continue_folynta_detection_evaluation.ps1') `
    -Arguments @(
        '-RepositoryRoot', $repository,
        '-DeadlineUtc', $deadline.ToString('o'),
        '-PollSeconds', [string]$PollSeconds
    )
Wait-Controller -Controller $evaluation
Wait-Controller -Controller $detection

$alternateTerminal = Join-Path `
    $generated 'folynta-alternate-recovery-controller-2026-08-04\terminal-receipt.json'
$auditTerminal = Join-Path `
    $generated 'folynta-stratified-audit-evaluation-controller-2026-08-04\terminal-receipt.json'
$detectionReport = Join-Path `
    $generated 'folynta-operational-detection-evaluation-2026-08-04\operational-detection-evaluation.json'
foreach ($required in @($alternateTerminal, $auditTerminal, $detectionReport)) {
    Wait-ForFile -Path $required -Event 'waiting-for-post-selection-evidence'
}
$payload = [ordered]@{
    schema = 'folynta.post-selection-recovery-audit-terminal.v1'
    status = 'alternate_recovery_audit_and_detection_complete'
    alternate_terminal = $alternateTerminal
    audit_terminal = $auditTerminal
    detection_report = $detectionReport
    paddle_case_count = [int]$post.paddle_case_count
    deepseek_case_count = [int]$post.deepseek_case_count
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $terminal -Encoding utf8
Write-PipelineEvent -Event 'post-selection-recovery-audit-complete'
exit 0
