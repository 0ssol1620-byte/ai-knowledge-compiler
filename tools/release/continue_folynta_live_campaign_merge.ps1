param(
    [Parameter(Mandatory = $true)] [string]$RepositoryRoot,
    [int]$PollSeconds = 60
)

$ErrorActionPreference = 'Stop'
if ($PollSeconds -lt 30 -or $PollSeconds -gt 300) {
    throw 'PollSeconds must be between 30 and 300'
}

$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$python = Join-Path $repository '.venv\Scripts\python.exe'
$liveTerminal = Join-Path $repository `
    'benchmark\reports\generated\folynta-live-campaign-monitor-2026-08-05\terminal-receipt.json'
$progressRoot = Join-Path $repository `
    'benchmark\reports\generated\folynta-live-campaign-merge-controller-2026-08-05'
$progressLog = Join-Path $progressRoot 'progress.jsonl'
$null = New-Item -ItemType Directory -Path $progressRoot -Force

function Write-Event {
    param([string]$Event, [hashtable]$Fields = @{})
    $value = [ordered]@{
        event = $Event
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    foreach ($name in $Fields.Keys) { $value[$name] = $Fields[$name] }
    Add-Content `
        -LiteralPath $progressLog `
        -Value ($value | ConvertTo-Json -Compress -Depth 8) `
        -Encoding utf8
}

Write-Event -Event 'waiting_for_live_worker_collection'
while (-not (Test-Path -LiteralPath $liveTerminal)) {
    Start-Sleep -Seconds $PollSeconds
}
$live = Get-Content -Raw -LiteralPath $liveTerminal | ConvertFrom-Json
if ($live.status -ne 'all_workers_collected_and_deleted') {
    throw 'Live campaign monitor did not prove collection and Pod deletion'
}
Write-Event -Event 'live_worker_collection_observed'

$primaryRoot = Join-Path $repository `
    'benchmark\datasets\private\runpod-2026-08-04\collected-full'
$retryRoot = Join-Path $repository `
    'benchmark\datasets\private\runpod-2026-08-04\collected-operational-retry-2026-08-05'
$retryPlan = Join-Path $repository `
    'benchmark\datasets\private\runpod-2026-08-04\operational-retry-prefetch-staging\retry-plan-receipt.json'
$composite = Join-Path $repository `
    'benchmark\reports\generated\folynta-mineru344-public-core-composite-r1-2026-08-04'
$merged = Join-Path $repository `
    'benchmark\reports\generated\folynta-mineru344-public-core-merged-r1-2026-08-04'
$operationalTerminal = Join-Path $repository `
    'benchmark\reports\generated\runpod-operational-retry-monitor-2026-08-04\terminal-receipt.json'

if (-not (Test-Path -LiteralPath $composite)) {
    $args = @((Join-Path $repository 'benchmark\runpod_eval\apply_operational_retries.py'))
    for ($index = 0; $index -lt 4; $index++) {
        $args += @('--primary', "$index=$(Join-Path $primaryRoot ("worker-{0:d2}" -f $index))")
    }
    for ($index = 4; $index -lt 7; $index++) {
        $args += @('--retry', "$index=$(Join-Path $retryRoot ("worker-{0:d2}" -f $index))")
    }
    $args += @('--retry-plan', $retryPlan, '--output-root', $composite)
    & $python @args 2>&1 | ForEach-Object {
        Write-Event -Event 'operational-overlay-output' -Fields @{ line = [string]$_ }
    }
    if ($LASTEXITCODE -ne 0) { throw 'Operational retry overlay failed' }
}
Write-Event -Event 'operational-overlay-complete'

if (-not (Test-Path -LiteralPath $merged)) {
    $args = @((Join-Path $repository 'benchmark\runpod_eval\public_core_merge.py'))
    for ($index = 0; $index -lt 4; $index++) {
        $args += @('--worker', "$index=$(Join-Path $composite ("worker-{0:d2}" -f $index))")
    }
    $args += @(
        '--staged-root', (Join-Path $repository 'benchmark\datasets\staged-public-core'),
        '--shard-plan', (Join-Path $repository 'benchmark\reports\generated\folynta-mineru344-public-core-4shard-plan-2026-08-04.json'),
        '--output-root', $merged
    )
    & $python @args 2>&1 | ForEach-Object {
        Write-Event -Event 'public-core-merge-output' -Fields @{ line = [string]$_ }
    }
    if ($LASTEXITCODE -ne 0) { throw 'Public-core merge failed' }
}
$mergeReceipt = Get-Content -Raw -LiteralPath (Join-Path $merged 'merge-receipt.json') |
    ConvertFrom-Json
$status = if (
    [int]$mergeReceipt.completed -eq 5132 -and
    [int]$mergeReceipt.failed -eq 0 -and
    $mergeReceipt.complete_case_coverage -eq $true
) { 'merged_complete' } else { 'merged_with_unresolved' }
$operational = [ordered]@{
    schema = 'folynta.operational-retry-monitor-terminal.v1'
    status = $status
    planned = 1788
    completed = [int]$mergeReceipt.completed
    unresolved = [int]$mergeReceipt.failed
    merged_root = $merged
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$operational | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $operationalTerminal -Encoding utf8
Write-Event -Event $status -Fields @{ unresolved = [int]$mergeReceipt.failed }

if ($status -ne 'merged_complete') {
    exit 3
}

& (Join-Path $repository 'tools\release\continue_folynta_official_evaluations.ps1') `
    -RepositoryRoot $repository `
    -OperationalTerminal $operationalTerminal `
    -MergedRoot $merged `
    -EvaluationRoot (Join-Path $repository 'benchmark\reports\generated\folynta-mineru344-public-core-official-evaluations-r1-2026-08-04') `
    -FailureRecords (Join-Path $repository 'benchmark\reports\generated\folynta-mineru344-public-failure-records-r1-2026-08-04.json') `
    -QualityRetryStaging (Join-Path $repository 'benchmark\datasets\private\runpod-2026-08-04\mineru-quality-retry-staging-r1') `
    -PollSeconds $PollSeconds
if ($LASTEXITCODE -ne 0) {
    throw "Official evaluation controller failed with exit $LASTEXITCODE"
}
Write-Event -Event 'official-evaluation-controller-complete'
exit 0
