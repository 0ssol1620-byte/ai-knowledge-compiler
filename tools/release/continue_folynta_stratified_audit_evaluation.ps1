param(
    [Parameter(Mandatory = $true)] [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)] [string]$DeadlineUtc,
    [int]$PollSeconds = 60
)

$ErrorActionPreference = 'Stop'
if ($PollSeconds -lt 30 -or $PollSeconds -gt 300) { throw 'PollSeconds is invalid' }
$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$deadline = [DateTimeOffset]::Parse($DeadlineUtc).ToUniversalTime()
$results = Join-Path `
    $repository `
    'benchmark\datasets\private\runpod-2026-08-04\stratified-audit-results-r1'
$auditTerminal = Join-Path $results 'terminal-receipt.json'
$prepared = Join-Path `
    $repository `
    'benchmark\datasets\private\runpod-2026-08-04\stratified-audit-official-r1'
$evaluations = Join-Path `
    $repository `
    'benchmark\reports\generated\folynta-stratified-audit-official-evaluations-r1-2026-08-04'
$controllerRoot = Join-Path `
    $repository `
    'benchmark\reports\generated\folynta-stratified-audit-evaluation-controller-2026-08-04'
$progress = Join-Path $controllerRoot 'progress.jsonl'
$terminal = Join-Path $controllerRoot 'terminal-receipt.json'
$summary = Join-Path $controllerRoot 'stratified-audit-official-summary.json'
$null = New-Item -ItemType Directory -Path $controllerRoot -Force

function Write-EvaluationEvent {
    param([string]$Event, [hashtable]$Fields = @{})
    $payload = [ordered]@{
        event = $Event
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    foreach ($name in $Fields.Keys) { $payload[$name] = $Fields[$name] }
    Add-Content `
        -LiteralPath $progress `
        -Value ($payload | ConvertTo-Json -Compress -Depth 10) `
        -Encoding utf8
}

function Invoke-Logged {
    param([string]$Name, [string]$Python, [object[]]$Arguments)
    & $Python @Arguments 2>&1 | ForEach-Object {
        Write-EvaluationEvent -Event $Name -Fields @{ line = [string]$_ }
    }
    if ($LASTEXITCODE -ne 0) { throw "$Name failed: $LASTEXITCODE" }
}

Write-EvaluationEvent -Event 'waiting-for-stratified-audit-collection'
while (-not (Test-Path -LiteralPath $auditTerminal)) {
    if ([DateTimeOffset]::UtcNow -ge $deadline) {
        throw 'Stratified audit evaluation deadline reached'
    }
    Start-Sleep -Seconds $PollSeconds
}
$audit = Get-Content -Raw -LiteralPath $auditTerminal | ConvertFrom-Json
if ([int]$audit.inference_count -ne 1152) {
    throw 'Stratified audit terminal identity is invalid'
}
$mainPython = Join-Path $repository '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath (Join-Path $prepared 'preparation-receipt.json'))) {
    Invoke-Logged `
        -Name 'prepare-official-inputs' `
        -Python $mainPython `
        -Arguments @(
            (Join-Path $repository 'benchmark\runpod_eval\prepare_stratified_audit_official.py'),
            '--results-root', $results,
            '--staging-root', (
                Join-Path $repository `
                    'benchmark\datasets\private\runpod-2026-08-04\stratified-audit-inputs-r2'
            ),
            '--acquired-root', (
                Join-Path $repository 'benchmark\datasets\acquired\public-core'
            ),
            '--output-root', $prepared
        )
}
$manifests = Join-Path $prepared 'manifests'
$predictions = Join-Path $prepared 'predictions'
$datasets = Join-Path $prepared 'datasets'
$runpodEval = Join-Path $repository 'benchmark\runpod_eval'
$checkouts = Join-Path $repository 'benchmark\datasets\private\evaluator-checkouts'
$parsePython = Join-Path $repository 'benchmark\cache\parsebench\.venv\Scripts\python.exe'
for ($repeat = 1; $repeat -le 3; $repeat++) {
    $output = Join-Path $evaluations "parsebench\repeat-$repeat"
    if (-not (Test-Path -LiteralPath (Join-Path $output 'evaluation-summary.json'))) {
        Invoke-Logged `
            -Name "parsebench-repeat-$repeat" `
            -Python $parsePython `
            -Arguments @(
                (Join-Path $runpodEval 'evaluate_parsebench_official.py'),
                '--evaluator-dir', (Join-Path $checkouts 'parsebench'),
                '--predictions-root', (
                    Join-Path $predictions "parsebench\repeat-$repeat"
                ),
                '--dataset-root', (Join-Path $datasets 'parsebench'),
                '--source-manifest', (Join-Path $manifests 'parsebench.json'),
                '--output-root', $output,
                '--max-workers', '8'
            )
    }
}
$omniOutput = Join-Path $evaluations 'omnidocbench'
if (-not (Test-Path -LiteralPath (Join-Path $omniOutput 'evaluation-summary.json'))) {
    Invoke-Logged `
        -Name 'omnidocbench-three-repeats' `
        -Python (
            Join-Path $repository 'benchmark\cache\omnidoc\.venv\Scripts\python.exe'
        ) `
        -Arguments @(
            (Join-Path $runpodEval 'evaluate_omnidoc_repeats.py'),
            '--evaluator-dir', (Join-Path $checkouts 'omnidocbench'),
            '--ground-truth', (
                Join-Path $repository `
                    'benchmark\datasets\acquired\public-core\omnidocbench\OmniDocBench.json'
            ),
            '--predictions-root', (Join-Path $predictions 'omnidocbench'),
            '--output-dir', $omniOutput,
            '--source-manifest', (Join-Path $manifests 'omnidocbench.json'),
            '--repeats', '3',
            '--workers', '4'
        )
}
$olmPython = Join-Path `
    $repository `
    'benchmark\datasets\private\evaluator-venvs\olmocr\Scripts\python.exe'
for ($repeat = 1; $repeat -le 3; $repeat++) {
    $output = Join-Path $evaluations "olmocr-bench\repeat-$repeat"
    if (-not (Test-Path -LiteralPath (Join-Path $output 'evaluation-summary.json'))) {
        Invoke-Logged `
            -Name "olmocr-repeat-$repeat" `
            -Python $olmPython `
            -Arguments @(
                (Join-Path $runpodEval 'evaluate_olmocr_official.py'),
                '--evaluator-dir', (Join-Path $checkouts 'olmocr-bench'),
                '--dataset-root', (Join-Path $datasets 'olmocr-bench'),
                '--candidate-dir', (
                    Join-Path $predictions "olmocr-bench\repeat-$repeat"
                ),
                '--source-manifest', (Join-Path $manifests 'olmocr-bench.json'),
                '--output-root', $output,
                '--bootstrap-samples', '2000'
            )
    }
}
if (-not (Test-Path -LiteralPath $summary)) {
    Invoke-Logged `
        -Name 'summarize-stratified-audit' `
        -Python $mainPython `
        -Arguments @(
            (Join-Path $runpodEval 'summarize_stratified_audit_official.py'),
            '--results-root', $results,
            '--evaluation-root', $evaluations,
            '--output', $summary
        )
}
$payload = Get-Content -Raw -LiteralPath $summary | ConvertFrom-Json
$receipt = [ordered]@{
    schema = 'folynta.stratified-audit-evaluation-controller-terminal.v1'
    status = 'official_three_repeat_audit_complete'
    suite_count = 3
    input_count_per_suite = 128
    repeat_count = 3
    inference_count = 1152
    summary = $summary
    summary_receipt_sha256 = $payload.receipt_sha256
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$receipt | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $terminal -Encoding utf8
Write-EvaluationEvent -Event 'official-three-repeat-audit-complete'
exit 0
