param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)]
    [string]$QualityCandidateTerminal,
    [Parameter(Mandatory = $true)]
    [string]$BaselineComposite,
    [Parameter(Mandatory = $true)]
    [string]$CandidateComposite,
    [Parameter(Mandatory = $true)]
    [string]$BaselineFailures,
    [Parameter(Mandatory = $true)]
    [string]$CandidateFailures,
    [Parameter(Mandatory = $true)]
    [string]$SelectivePlan,
    [Parameter(Mandatory = $true)]
    [string]$OutputComposite,
    [Parameter(Mandatory = $true)]
    [string]$OutputMerged,
    [Parameter(Mandatory = $true)]
    [string]$OutputEvaluationRoot,
    [Parameter(Mandatory = $true)]
    [string]$OutputFailureRecords,
    [Parameter(Mandatory = $true)]
    [string]$PaddleStaging,
    [Parameter(Mandatory = $true)]
    [string]$DeepSeekStaging,
    [string]$BaselineMergedRoot,
    [string]$BaselineEvaluationRoot,
    [int]$PollSeconds = 60
)

$ErrorActionPreference = 'Stop'
if ($PollSeconds -lt 30 -or $PollSeconds -gt 300) {
    throw 'PollSeconds must be between 30 and 300'
}
$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$candidateTerminalPath = [IO.Path]::GetFullPath($QualityCandidateTerminal)
$baseline = [IO.Path]::GetFullPath($BaselineComposite)
$candidate = [IO.Path]::GetFullPath($CandidateComposite)
$baselineFailuresPath = [IO.Path]::GetFullPath($BaselineFailures)
$candidateFailuresPath = [IO.Path]::GetFullPath($CandidateFailures)
$selectivePlanPath = [IO.Path]::GetFullPath($SelectivePlan)
$output = [IO.Path]::GetFullPath($OutputComposite)
$merged = [IO.Path]::GetFullPath($OutputMerged)
$evaluations = [IO.Path]::GetFullPath($OutputEvaluationRoot)
$failuresPath = [IO.Path]::GetFullPath($OutputFailureRecords)
$paddle = [IO.Path]::GetFullPath($PaddleStaging)
$deepseek = [IO.Path]::GetFullPath($DeepSeekStaging)
$progressRoot = Join-Path `
    $repository `
    'benchmark\reports\generated\folynta-post-mineru-selection-controller-2026-08-04'
$progressLog = Join-Path $progressRoot 'progress.jsonl'
$terminalReceipt = Join-Path $progressRoot 'terminal-receipt.json'
$comparisonPath = Join-Path $progressRoot 'mineru-quality-official-comparison.json'
$null = New-Item -ItemType Directory -Path $progressRoot -Force

function Write-SelectionEvent {
    param([string]$Event, [hashtable]$Fields = @{})
    $payload = [ordered]@{
        event = $Event
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    foreach ($key in $Fields.Keys) {
        $payload[$key] = $Fields[$key]
    }
    Add-Content `
        -LiteralPath $progressLog `
        -Value ($payload | ConvertTo-Json -Compress -Depth 10) `
        -Encoding utf8
}

function Invoke-LoggedPython {
    param([string]$Name, [string]$Python, [object[]]$Arguments)
    & $Python @Arguments 2>&1 | ForEach-Object {
        Write-SelectionEvent -Event $Name -Fields @{ line = [string]$_ }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit $LASTEXITCODE"
    }
}

Write-SelectionEvent -Event 'waiting_for_mineru_quality_candidate_evaluation'
while (-not (Test-Path -LiteralPath $candidateTerminalPath)) {
    Start-Sleep -Seconds $PollSeconds
}
$terminal = Get-Content -Raw -LiteralPath $candidateTerminalPath | ConvertFrom-Json
if ($terminal.status -ne 'candidate_evaluated') {
    throw "MinerU quality candidate evaluation is not complete: $($terminal.status)"
}
$python = Join-Path $repository '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $comparisonPath)) {
    Invoke-LoggedPython `
        -Name 'official_comparison_output' `
        -Python $python `
        -Arguments @(
            (Join-Path $repository 'benchmark\runpod_eval\compare_official_failure_records.py'),
            '--baseline', $baselineFailuresPath,
            '--candidate', $candidateFailuresPath,
            '--output', $comparisonPath
        )
}
$comparison = Get-Content -Raw -LiteralPath $comparisonPath | ConvertFrom-Json
Write-SelectionEvent `
    -Event 'official_quality_comparison_complete' `
    -Fields @{
        accepted = [int]$comparison.accepted_quality_case_count
        persistent = [int]$comparison.persistent_case_count
        regressions_reverted = [int]$comparison.regressed_candidate_case_count
    }

if (-not (Test-Path -LiteralPath $output)) {
    $arguments = @(
        (Join-Path $repository 'benchmark\runpod_eval\apply_accepted_quality_candidates.py')
    )
    for ($index = 0; $index -lt 4; $index++) {
        $arguments += @(
            '--baseline', "$index=$(Join-Path $baseline ("worker-{0:d2}" -f $index))",
            '--candidate', "$index=$(Join-Path $candidate ("worker-{0:d2}" -f $index))"
        )
    }
    $arguments += @(
        '--selective-plan', $selectivePlanPath,
        '--comparison', $comparisonPath,
        '--output-root', $output
    )
    Invoke-LoggedPython -Name 'accepted_overlay_output' -Python $python -Arguments $arguments
}
Write-SelectionEvent -Event 'accepted_mineru_quality_overlay_complete'

if (-not (Test-Path -LiteralPath $merged)) {
    $arguments = @((Join-Path $repository 'benchmark\runpod_eval\public_core_merge.py'))
    for ($index = 0; $index -lt 4; $index++) {
        $arguments += @(
            '--worker', "$index=$(Join-Path $output ("worker-{0:d2}" -f $index))"
        )
    }
    $arguments += @(
        '--staged-root', (Join-Path $repository 'benchmark\datasets\staged-public-core'),
        '--shard-plan', (Join-Path $repository 'benchmark\reports\generated\folynta-mineru344-public-core-4shard-plan-2026-08-04.json'),
        '--output-root', $merged
    )
    Invoke-LoggedPython -Name 'accepted_merge_output' -Python $python -Arguments $arguments
}
$mergeReceipt = Get-Content -Raw -LiteralPath (Join-Path $merged 'merge-receipt.json') |
    ConvertFrom-Json
if ([int]$mergeReceipt.completed -ne 5132 -or [int]$mergeReceipt.failed -ne 0) {
    throw 'Accepted MinerU quality merge is incomplete'
}
Write-SelectionEvent -Event 'accepted_mineru_quality_merge_complete'

$bundleReceipt = Join-Path $evaluations 'official-evaluation-bundle-receipt.json'
if (-not (Test-Path -LiteralPath $bundleReceipt)) {
    Invoke-LoggedPython `
        -Name 'accepted_official_bundle_output' `
        -Python $python `
        -Arguments @(
            (Join-Path $repository 'benchmark\runpod_eval\run_public_core_official_bundle.py'),
            '--repository-root', $repository,
            '--merged-root', $merged,
            '--output-root', $evaluations,
            '--failure-records', $failuresPath
        )
}
$bundle = Get-Content -Raw -LiteralPath $bundleReceipt | ConvertFrom-Json
Write-SelectionEvent `
    -Event 'accepted_mineru_official_evaluation_complete' `
    -Fields @{
        official_failure_record_count = [int]$bundle.official_failure_record_count
        recoverable_case_count = [int]$bundle.recoverable_case_count
    }

$resolvedBaselineEvaluationRoot = if ($BaselineEvaluationRoot) {
    [IO.Path]::GetFullPath($BaselineEvaluationRoot)
}
else {
    Join-Path `
        $repository `
        'benchmark\reports\generated\folynta-mineru344-public-core-official-evaluations-r1-2026-08-04'
}
$resolvedBaselineMergedRoot = if ($BaselineMergedRoot) {
    [IO.Path]::GetFullPath($BaselineMergedRoot)
}
else {
    Join-Path `
        $repository `
        'benchmark\reports\generated\folynta-mineru344-public-core-merged-r1-2026-08-04'
}
$aggregateComparisonPath = Join-Path `
    $progressRoot `
    'mineru-quality-aggregate-official-comparison.json'
if (-not (Test-Path -LiteralPath $aggregateComparisonPath)) {
    Invoke-LoggedPython `
        -Name 'aggregate_official_comparison_output' `
        -Python $python `
        -Arguments @(
            (Join-Path $repository 'benchmark\runpod_eval\compare_official_evaluation_metrics.py'),
            '--baseline-root', $resolvedBaselineEvaluationRoot,
            '--candidate-root', $evaluations,
            '--baseline-failure-records', $baselineFailuresPath,
            '--candidate-failure-records', $failuresPath,
            '--output', $aggregateComparisonPath
        )
}
$aggregateComparison = Get-Content -Raw -LiteralPath $aggregateComparisonPath |
    ConvertFrom-Json
$acceptedMineruCount = [int]$comparison.accepted_quality_case_count
$revertedMineruCount = [int]$comparison.regressed_candidate_case_count
$aggregateRollback = $aggregateComparison.no_regression -ne $true
if ($aggregateRollback) {
    $revertedMineruCount += $acceptedMineruCount
    $acceptedMineruCount = 0
    $output = $baseline
    $merged = $resolvedBaselineMergedRoot
    $evaluations = $resolvedBaselineEvaluationRoot
    $failuresPath = $baselineFailuresPath
    $baselineFailurePayload = Get-Content -Raw -LiteralPath $failuresPath |
        ConvertFrom-Json
    $bundle = [pscustomobject]@{
        official_failure_record_count = [int]$baselineFailurePayload.record_count
        recoverable_case_count = [int]$baselineFailurePayload.recoverable_case_count
    }
    Write-SelectionEvent `
        -Event 'mineru-quality-aggregate-regression-rolled-back' `
        -Fields @{ delta = $aggregateComparison.delta }
}
else {
    Write-SelectionEvent `
        -Event 'mineru-quality-aggregate-non-regression-passed' `
        -Fields @{ delta = $aggregateComparison.delta }
}

$failurePayload = Get-Content -Raw -LiteralPath $failuresPath | ConvertFrom-Json
$paddleCount = @(
    $failurePayload.routes |
        Where-Object { $_.request_recovery -eq $true -and $_.candidate_models -contains 'paddleocr-vl-1.6' }
).Count
$deepseekCount = @(
    $failurePayload.routes |
        Where-Object { $_.request_recovery -eq $true -and $_.candidate_models -contains 'deepseek-ocr-2' }
).Count
$workerHealth = Join-Path `
    $repository `
    'benchmark\reports\generated\runpod-operational-retry-controller-2026-08-04\operational-worker-health.json'
$stager = Join-Path $repository 'benchmark\runpod_eval\stage_selective_recovery.py'
$common = @(
    '--failure-records', $failuresPath,
    '--staged-root', (Join-Path $repository 'benchmark\datasets\private\mineru-public-core-workers-2026-08-04'),
    '--shard-plan', (Join-Path $repository 'benchmark\reports\generated\folynta-mineru344-public-core-4shard-plan-2026-08-04.json'),
    '--worker-health', $workerHealth
)
if ($paddleCount -gt 0 -and -not (Test-Path -LiteralPath $paddle)) {
    Invoke-LoggedPython `
        -Name 'paddle_staging_output' `
        -Python $python `
        -Arguments @($stager) + $common + @(
            '--recovery-model', 'paddleocr-vl-1.6', '--output-root', $paddle
        )
}
if ($deepseekCount -gt 0 -and -not (Test-Path -LiteralPath $deepseek)) {
    Invoke-LoggedPython `
        -Name 'deepseek_staging_output' `
        -Python $python `
        -Arguments @($stager) + $common + @(
            '--recovery-model', 'deepseek-ocr-2', '--output-root', $deepseek
        )
}

$outputTerminal = [ordered]@{
    schema = 'folynta.post-mineru-selection-controller-terminal.v1'
    status = 'alternate_recovery_staged'
    input_count = 5132
    accepted_mineru_quality_case_count = $acceptedMineruCount
    reverted_mineru_regression_case_count = $revertedMineruCount
    aggregate_metric_rollback = $aggregateRollback
    aggregate_metric_comparison = $aggregateComparisonPath
    official_failure_record_count = [int]$bundle.official_failure_record_count
    recoverable_case_count = [int]$bundle.recoverable_case_count
    paddle_case_count = $paddleCount
    deepseek_case_count = $deepseekCount
    comparison = $comparisonPath
    composite_root = $output
    merged_root = $merged
    evaluation_root = $evaluations
    failure_records = $failuresPath
    paddle_staging = if ($paddleCount -gt 0) { $paddle } else { $null }
    deepseek_staging = if ($deepseekCount -gt 0) { $deepseek } else { $null }
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$outputTerminal | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $terminalReceipt -Encoding utf8
Write-SelectionEvent `
    -Event 'alternate_recovery_staged' `
    -Fields @{ paddle = $paddleCount; deepseek = $deepseekCount }
exit 0
