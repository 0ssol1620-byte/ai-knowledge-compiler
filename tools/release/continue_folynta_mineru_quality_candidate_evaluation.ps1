param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)]
    [string]$QualityTerminal,
    [Parameter(Mandatory = $true)]
    [string]$QualityLaunch,
    [Parameter(Mandatory = $true)]
    [string]$BaselineComposite,
    [Parameter(Mandatory = $true)]
    [string]$QualityCollection,
    [Parameter(Mandatory = $true)]
    [string]$SelectivePlan,
    [Parameter(Mandatory = $true)]
    [string]$CandidateComposite,
    [Parameter(Mandatory = $true)]
    [string]$CandidateMerged,
    [Parameter(Mandatory = $true)]
    [string]$EvaluationRoot,
    [Parameter(Mandatory = $true)]
    [string]$FailureRecords,
    [int]$PollSeconds = 60
)

$ErrorActionPreference = 'Stop'
if ($PollSeconds -lt 30 -or $PollSeconds -gt 300) {
    throw 'PollSeconds must be between 30 and 300'
}
$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$qualityTerminalPath = [IO.Path]::GetFullPath($QualityTerminal)
$qualityLaunchPath = [IO.Path]::GetFullPath($QualityLaunch)
$baseline = [IO.Path]::GetFullPath($BaselineComposite)
$quality = [IO.Path]::GetFullPath($QualityCollection)
$selectivePlanPath = [IO.Path]::GetFullPath($SelectivePlan)
$candidate = [IO.Path]::GetFullPath($CandidateComposite)
$merged = [IO.Path]::GetFullPath($CandidateMerged)
$evaluations = [IO.Path]::GetFullPath($EvaluationRoot)
$failureRecordsPath = [IO.Path]::GetFullPath($FailureRecords)
$progressRoot = Join-Path `
    $repository `
    'benchmark\reports\generated\folynta-mineru-quality-candidate-controller-2026-08-04'
$progressLog = Join-Path $progressRoot 'progress.jsonl'
$terminalReceipt = Join-Path $progressRoot 'terminal-receipt.json'
$null = New-Item -ItemType Directory -Path $progressRoot -Force

function Write-CandidateEvent {
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

Write-CandidateEvent -Event 'waiting_for_mineru_quality_retry_collection'
while (-not (Test-Path -LiteralPath $qualityTerminalPath)) {
    Start-Sleep -Seconds $PollSeconds
}
$qualityTerminalPayload = Get-Content -Raw -LiteralPath $qualityTerminalPath |
    ConvertFrom-Json
if ($qualityTerminalPayload.status -ne 'collected') {
    throw "MinerU quality retry collection is not complete: $($qualityTerminalPayload.status)"
}
$launch = Get-Content -Raw -LiteralPath $qualityLaunchPath | ConvertFrom-Json
if (
    $launch.schema -ne 'folynta.mineru-quality-retry-launch.v1' -or
    [int]$launch.input_count -ne [int]$qualityTerminalPayload.input_count
) {
    throw 'MinerU quality retry launch and collection differ'
}
Write-CandidateEvent `
    -Event 'mineru_quality_retry_collection_observed' `
    -Fields @{ input_count = [int]$launch.input_count }

$python = Join-Path $repository '.venv\Scripts\python.exe'
$apply = Join-Path `
    $repository `
    'benchmark\runpod_eval\apply_mineru_quality_candidates.py'
if (-not (Test-Path -LiteralPath $candidate)) {
    $applyArgs = @($apply)
    for ($index = 0; $index -lt 4; $index++) {
        $applyArgs += @(
            '--baseline',
            "$index=$(Join-Path $baseline ("worker-{0:d2}" -f $index))"
        )
    }
    foreach ($launched in @($launch.launches)) {
        $index = [int]$launched.worker_index
        $applyArgs += @(
            '--quality',
            "$index=$(Join-Path $quality ("worker-{0:d2}" -f $index))"
        )
    }
    $applyArgs += @(
        '--selective-plan', $selectivePlanPath,
        '--output-root', $candidate
    )
    & $python @applyArgs 2>&1 | ForEach-Object {
        Write-CandidateEvent -Event 'candidate_overlay_output' -Fields @{ line = [string]$_ }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "MinerU quality candidate overlay failed with exit $LASTEXITCODE"
    }
}
Write-CandidateEvent -Event 'mineru_quality_candidate_overlay_complete'

$merger = Join-Path $repository 'benchmark\runpod_eval\public_core_merge.py'
if (-not (Test-Path -LiteralPath $merged)) {
    $mergeArgs = @($merger)
    for ($index = 0; $index -lt 4; $index++) {
        $mergeArgs += @(
            '--worker',
            "$index=$(Join-Path $candidate ("worker-{0:d2}" -f $index))"
        )
    }
    $mergeArgs += @(
        '--staged-root',
        (Join-Path $repository 'benchmark\datasets\staged-public-core'),
        '--shard-plan',
        (Join-Path $repository 'benchmark\reports\generated\folynta-mineru344-public-core-4shard-plan-2026-08-04.json'),
        '--output-root', $merged
    )
    & $python @mergeArgs 2>&1 | ForEach-Object {
        Write-CandidateEvent -Event 'candidate_merge_output' -Fields @{ line = [string]$_ }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "MinerU quality candidate merge failed with exit $LASTEXITCODE"
    }
}
$mergeReceipt = Get-Content -Raw -LiteralPath (Join-Path $merged 'merge-receipt.json') |
    ConvertFrom-Json
if (
    [int]$mergeReceipt.completed -ne 5132 -or
    [int]$mergeReceipt.failed -ne 0
) {
    throw 'MinerU quality candidate merge is incomplete'
}
Write-CandidateEvent -Event 'mineru_quality_candidate_merge_complete'

$bundle = Join-Path `
    $repository `
    'benchmark\runpod_eval\run_public_core_official_bundle.py'
$bundleReceipt = Join-Path $evaluations 'official-evaluation-bundle-receipt.json'
if (-not (Test-Path -LiteralPath $bundleReceipt)) {
    & $python $bundle `
        --repository-root $repository `
        --merged-root $merged `
        --output-root $evaluations `
        --failure-records $failureRecordsPath 2>&1 | ForEach-Object {
            Write-CandidateEvent `
                -Event 'candidate_official_bundle_output' `
                -Fields @{ line = [string]$_ }
        }
    if ($LASTEXITCODE -ne 0) {
        throw "MinerU quality candidate official bundle failed with exit $LASTEXITCODE"
    }
}
$evaluation = Get-Content -Raw -LiteralPath $bundleReceipt | ConvertFrom-Json
$terminal = [ordered]@{
    schema = 'folynta.mineru-quality-candidate-controller-terminal.v1'
    status = 'candidate_evaluated'
    input_count = [int]$evaluation.input_count
    official_failure_record_count = [int]$evaluation.official_failure_record_count
    recoverable_case_count = [int]$evaluation.recoverable_case_count
    failure_records = $failureRecordsPath
    evaluation_root = $evaluations
    candidate_merged_root = $merged
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$terminal | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $terminalReceipt -Encoding utf8
Write-CandidateEvent `
    -Event 'mineru_quality_candidate_evaluated' `
    -Fields @{
        official_failure_record_count = [int]$evaluation.official_failure_record_count
        recoverable_case_count = [int]$evaluation.recoverable_case_count
    }
exit 0
