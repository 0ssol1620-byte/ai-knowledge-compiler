param(
    [Parameter(Mandatory = $true)] [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)] [string]$DeadlineUtc,
    # The primary operational retry campaign staged 1,788 failed cases from the
    # prefetch lane and applied them into composite r1. The defaults below name
    # that campaign; earlier revisions pointed at directory names the campaign
    # never actually produced.
    [string]$RetryPlan,
    [string]$OperationalOverlay,
    [int]$PollSeconds = 60
)

$ErrorActionPreference = 'Stop'
if ($PollSeconds -lt 30 -or $PollSeconds -gt 300) { throw 'PollSeconds is invalid' }
$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$deadline = [DateTimeOffset]::Parse($DeadlineUtc).ToUniversalTime()
$retryPlan = if ($RetryPlan) { [IO.Path]::GetFullPath($RetryPlan) } else {
    Join-Path `
        $repository `
        'benchmark\datasets\private\runpod-2026-08-04\operational-retry-prefetch-staging\retry-plan-receipt.json'
}
$workerHealth = Join-Path `
    $repository `
    'benchmark\reports\generated\runpod-operational-retry-controller-2026-08-04\operational-worker-health.json'
$operationalOverlay = if ($OperationalOverlay) {
    [IO.Path]::GetFullPath($OperationalOverlay)
}
else {
    Join-Path `
        $repository `
        'benchmark\reports\generated\folynta-mineru344-public-core-composite-r1-2026-08-04\operational-retry-overlay-receipt.json'
}
$controlledFaultEvaluation = Join-Path `
    $repository `
    'benchmark\reports\generated\folynta-operational-fault-injection-evaluation-2026-08-04.json'
$livePrefetchIncidentEvidence = Join-Path `
    $repository `
    'benchmark\reports\generated\folynta-operational-prefetch-incident-evidence-2026-08-04\incident-receipt.json'
$progressRoot = Join-Path `
    $repository `
    'benchmark\reports\generated\folynta-operational-detection-evaluation-2026-08-04'
$progress = Join-Path $progressRoot 'progress.jsonl'
$output = Join-Path $progressRoot 'operational-detection-evaluation.json'
$null = New-Item -ItemType Directory -Path $progressRoot -Force

function Write-DetectionEvent {
    param([string]$Event, [hashtable]$Fields = @{})
    $payload = [ordered]@{
        event = $Event
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    foreach ($name in $Fields.Keys) { $payload[$name] = $Fields[$name] }
    Add-Content `
        -LiteralPath $progress `
        -Value ($payload | ConvertTo-Json -Compress -Depth 8) `
        -Encoding utf8
}

Write-DetectionEvent -Event 'waiting-for-operational-plan-and-retry-outcome'
while (
    -not (Test-Path -LiteralPath $retryPlan) -or
    -not (Test-Path -LiteralPath $workerHealth) -or
    -not (Test-Path -LiteralPath $operationalOverlay) -or
    -not (Test-Path -LiteralPath $controlledFaultEvaluation) -or
    -not (Test-Path -LiteralPath $livePrefetchIncidentEvidence)
) {
    if ([DateTimeOffset]::UtcNow -ge $deadline) {
        throw 'Operational detection evaluation deadline reached'
    }
    Start-Sleep -Seconds $PollSeconds
}
if (-not (Test-Path -LiteralPath $output)) {
    $arguments = @(
        (Join-Path $repository 'benchmark\runpod_eval\evaluate_operational_detection.py')
    )
    $collection = Join-Path `
        $repository `
        'benchmark\datasets\private\runpod-2026-08-04\collected-full'
    for ($index = 0; $index -lt 4; $index++) {
        $arguments += @(
            '--worker-result',
            "$index=$(Join-Path $collection ("worker-{0:d2}" -f $index))"
        )
    }
    $arguments += @(
        '--retry-plan', $retryPlan,
        '--worker-health', $workerHealth,
        '--operational-overlay', $operationalOverlay,
        '--controlled-fault-evaluation', $controlledFaultEvaluation,
        '--live-prefetch-incident-evidence', $livePrefetchIncidentEvidence,
        '--output', $output
    )
    $python = Join-Path $repository '.venv\Scripts\python.exe'
    & $python @arguments 2>&1 | ForEach-Object {
        Write-DetectionEvent -Event 'evaluator-output' -Fields @{ line = [string]$_ }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Operational detection evaluation failed: $LASTEXITCODE"
    }
}
$result = Get-Content -Raw -LiteralPath $output | ConvertFrom-Json
Write-DetectionEvent `
    -Event 'operational-detection-evaluated' `
    -Fields @{
        case_precision = $result.case_failure_detection.precision
        case_recall = $result.case_failure_detection.recall
        live_retry_confirmed = `
            [int]$result.live_different_pod_retry_confirmation.different_pod_retry_completed
        controlled_state_accuracy = `
            $result.controlled_fault_injection.state_exact_accuracy
        invalid_retry_targets = [int]$result.invalid_retry_target_count
    }
exit 0
