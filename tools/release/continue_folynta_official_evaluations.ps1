param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)]
    [string]$OperationalTerminal,
    [Parameter(Mandatory = $true)]
    [string]$MergedRoot,
    [Parameter(Mandatory = $true)]
    [string]$EvaluationRoot,
    [Parameter(Mandatory = $true)]
    [string]$FailureRecords,
    [Parameter(Mandatory = $true)]
    [string]$QualityRetryStaging,
    [int]$PollSeconds = 60
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
# The frozen evaluator defaults to an optional Anthropic judge. This campaign
# has no judge credential by design, so make the effective fallback explicit
# and deterministic instead of importing and failing once per record.
$env:LLAMACLOUD_BENCH_LLM_NORMALIZATION = 'off'
if ($PollSeconds -lt 30 -or $PollSeconds -gt 300) {
    throw 'PollSeconds must be between 30 and 300'
}

$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$operationalTerminalPath = [IO.Path]::GetFullPath($OperationalTerminal)
$merged = [IO.Path]::GetFullPath($MergedRoot)
$evaluations = [IO.Path]::GetFullPath($EvaluationRoot)
$failureRecordsPath = [IO.Path]::GetFullPath($FailureRecords)
$qualityRetry = [IO.Path]::GetFullPath($QualityRetryStaging)
$progressRoot = Join-Path `
    $repository `
    'benchmark\reports\generated\folynta-official-evaluation-controller-2026-08-04'
$progressLog = Join-Path $progressRoot 'progress.jsonl'
$terminalReceipt = Join-Path $progressRoot 'terminal-receipt.json'
$null = New-Item -ItemType Directory -Path $progressRoot -Force

function Write-EvaluationEvent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Event,
        [hashtable]$Fields = @{}
    )
    $payload = [ordered]@{
        event = $Event
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    foreach ($key in $Fields.Keys) {
        $payload[$key] = $Fields[$key]
    }
    $line = $payload | ConvertTo-Json -Compress -Depth 10
    for ($attempt = 1; $attempt -le 20; $attempt++) {
        try {
            Add-Content -LiteralPath $progressLog -Value $line -Encoding utf8
            return
        }
        catch [System.IO.IOException] {
            if ($attempt -eq 20) { throw }
            Start-Sleep -Milliseconds 100
        }
    }
}

function Invoke-Evaluator {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Python,
        [Parameter(Mandatory = $true)]
        [object[]]$Arguments
    )
    $slug = $Name.ToLowerInvariant() -replace '[^a-z0-9]+', '-'
    $stdoutLog = Join-Path $progressRoot "$slug.stdout.log"
    $stderrLog = Join-Path $progressRoot "$slug.stderr.log"
    $savedPreference = $ErrorActionPreference
    $exitCode = 0
    try {
        $ErrorActionPreference = 'Continue'
        & $Python @Arguments 1> $stdoutLog 2> $stderrLog
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedPreference
    }
    Write-EvaluationEvent -Event 'evaluator_process_complete' -Fields @{
        evaluator = $Name
        exit_code = $exitCode
        stdout_log = $stdoutLog
        stderr_log = $stderrLog
    }
    if ($exitCode -ne 0) {
        throw "$Name evaluator failed with exit $exitCode"
    }
}

function Invoke-LoggedPython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Python,
        [Parameter(Mandatory = $true)]
        [object[]]$Arguments
    )
    $slug = $Name.ToLowerInvariant() -replace '[^a-z0-9]+', '-'
    $stdoutLog = Join-Path $progressRoot "$slug.stdout.log"
    $stderrLog = Join-Path $progressRoot "$slug.stderr.log"
    $savedPreference = $ErrorActionPreference
    $exitCode = 0
    try {
        $ErrorActionPreference = 'Continue'
        & $Python @Arguments 1> $stdoutLog 2> $stderrLog
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedPreference
    }
    Write-EvaluationEvent -Event 'python_process_complete' -Fields @{
        process = $Name
        exit_code = $exitCode
        stdout_log = $stdoutLog
        stderr_log = $stderrLog
    }
    if ($exitCode -ne 0) {
        throw "$Name failed with exit $exitCode"
    }
}

Write-EvaluationEvent -Event 'waiting_for_complete_operational_merge'
while (-not (Test-Path -LiteralPath $operationalTerminalPath)) {
    Start-Sleep -Seconds $PollSeconds
}
$operational = Get-Content -Raw -LiteralPath $operationalTerminalPath | ConvertFrom-Json
if ($operational.status -ne 'merged_complete') {
    $terminal = [ordered]@{
        schema = 'folynta.official-evaluation-controller-terminal.v1'
        status = 'waiting_for_additional_operational_recovery'
        unresolved = [int]$operational.unresolved
        completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    $terminal | ConvertTo-Json -Depth 6 |
        Set-Content -LiteralPath $terminalReceipt -Encoding utf8
    Write-EvaluationEvent `
        -Event 'additional_operational_recovery_required' `
        -Fields @{ unresolved = [int]$operational.unresolved }
    exit 3
}
$mergeReceipt = Get-Content -Raw -LiteralPath (Join-Path $merged 'merge-receipt.json') |
    ConvertFrom-Json
if (
    [int]$mergeReceipt.completed -ne 5132 -or
    [int]$mergeReceipt.failed -ne 0 -or
    $mergeReceipt.complete_case_coverage -ne $true
) {
    throw 'Operational terminal and merge receipt disagree on complete coverage'
}
Write-EvaluationEvent -Event 'complete_operational_merge_observed'

$parsePython = Join-Path $repository 'benchmark\cache\parsebench\.venv\Scripts\python.exe'
$omniPython = Join-Path $repository 'benchmark\cache\omnidoc\.venv\Scripts\python.exe'
$olmPython = Join-Path `
    $repository `
    'benchmark\datasets\private\evaluator-venvs\olmocr\Scripts\python.exe'
$parseScript = Join-Path $repository 'benchmark\runpod_eval\evaluate_parsebench_official.py'
$omniScript = Join-Path $repository 'benchmark\runpod_eval\evaluate_omnidoc_repeats.py'
$olmScript = Join-Path $repository 'benchmark\runpod_eval\evaluate_olmocr_official.py'
$parseEvaluator = Join-Path `
    $repository `
    'benchmark\datasets\private\evaluator-checkouts\parsebench'
$omniEvaluator = Join-Path `
    $repository `
    'benchmark\datasets\private\evaluator-checkouts\omnidocbench'
$olmEvaluator = Join-Path `
    $repository `
    'benchmark\datasets\private\evaluator-checkouts\olmocr-bench'
$acquired = Join-Path $repository 'benchmark\datasets\acquired\public-core'
$manifests = Join-Path `
    $repository `
    'benchmark\reports\generated\public-core-manifests'
$null = New-Item -ItemType Directory -Path $evaluations -Force

$parseOutput = Join-Path $evaluations 'parsebench'
if (-not (Test-Path -LiteralPath (Join-Path $parseOutput 'evaluation-summary.json'))) {
    $savedPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = Join-Path $parseEvaluator 'src'
        Invoke-Evaluator `
            -Name 'ParseBench' `
            -Python $parsePython `
            -Arguments @(
                $parseScript,
                '--evaluator-dir', $parseEvaluator,
                '--predictions-root', (Join-Path $merged 'official\parsebench'),
                '--dataset-root', (Join-Path $acquired 'parsebench'),
                '--source-manifest', (Join-Path $manifests 'parsebench-source-manifest.json'),
                '--output-root', $parseOutput,
                '--max-workers', '2'
            )
    }
    finally {
        $env:PYTHONPATH = $savedPythonPath
    }
}
Write-EvaluationEvent -Event 'parsebench_official_complete'

$omniOutput = Join-Path $evaluations 'omnidocbench'
if (-not (Test-Path -LiteralPath (Join-Path $omniOutput 'evaluation-summary.json'))) {
    Invoke-Evaluator `
        -Name 'OmniDocBench' `
        -Python $omniPython `
        -Arguments @(
            $omniScript,
            '--evaluator-dir', $omniEvaluator,
            '--ground-truth', (Join-Path $acquired 'omnidocbench\OmniDocBench.json'),
            '--predictions-root', (Join-Path $merged 'official\omnidocbench'),
            '--output-dir', $omniOutput,
            '--source-manifest', (Join-Path $manifests 'omnidocbench-source-manifest.json'),
            '--repeats', '1',
            '--workers', '4'
        )
}
Write-EvaluationEvent -Event 'omnidocbench_official_complete'

$olmOutput = Join-Path $evaluations 'olmocr-bench'
if (-not (Test-Path -LiteralPath (Join-Path $olmOutput 'evaluation-summary.json'))) {
    Invoke-Evaluator `
        -Name 'olmOCR-Bench' `
        -Python $olmPython `
        -Arguments @(
            $olmScript,
            '--evaluator-dir', $olmEvaluator,
            '--dataset-root', (Join-Path $acquired 'olmocr-bench'),
            '--candidate-dir', (Join-Path $merged 'official\olmocr-bench\mineru344'),
            '--source-manifest', (Join-Path $manifests 'olmocr-bench-source-manifest.json'),
            '--output-root', $olmOutput,
            '--bootstrap-samples', '2000'
        )
}
Write-EvaluationEvent -Event 'olmocr_official_complete'

$rootPython = Join-Path $repository '.venv\Scripts\python.exe'
$failureBuilder = Join-Path `
    $repository `
    'benchmark\runpod_eval\build_public_failure_records.py'
if (-not (Test-Path -LiteralPath $failureRecordsPath)) {
    Invoke-LoggedPython `
        -Name 'Official failure record builder' `
        -Python $rootPython `
        -Arguments @(
            $failureBuilder,
            '--merged-root', $merged,
            '--evaluation', "parsebench=$parseOutput",
            '--evaluation', "omnidocbench=$omniOutput",
            '--evaluation', "olmocr-bench=$olmOutput",
            '--output', $failureRecordsPath
        )
}
# The record file holds 43k official decisions (~77 MB). ConvertFrom-Json builds
# a PSCustomObject per node, which burned 25+ minutes and ~1 GB to recover two
# integers, so the scalars are summarised by the Python lane instead.
$failureSummarizer = Join-Path `
    $repository `
    'benchmark\runpod_eval\summarize_failure_records.py'
$failureSummaryJson = & $rootPython $failureSummarizer `
    --failure-records $failureRecordsPath
if ($LASTEXITCODE -ne 0) { throw 'Official failure record summary failed' }
$failures = $failureSummaryJson | ConvertFrom-Json
if ($failures.schema -ne 'folynta.public-failure-record-summary.v1') {
    throw 'Official failure record summary schema is invalid'
}
Write-EvaluationEvent `
    -Event 'official_failure_records_complete' `
    -Fields @{
        record_count = [int]$failures.record_count
        recoverable_case_count = [int]$failures.recoverable_case_count
    }

$qualityRetryNeeded = [int]$failures.recoverable_case_count -gt 0
if ($qualityRetryNeeded -and -not (Test-Path -LiteralPath $qualityRetry)) {
    $stager = Join-Path $repository 'benchmark\runpod_eval\stage_selective_recovery.py'
    $workerHealth = Join-Path `
        $repository `
        'benchmark\reports\generated\runpod-operational-retry-controller-2026-08-04\operational-worker-health.json'
    $expandedConfigPath = Join-Path `
        $repository `
        'benchmark\datasets\private\runpod-2026-08-04\operational-retry-workers-expanded.json'
    $expansionBootstrapPath = Join-Path `
        $repository `
        'benchmark\datasets\private\runpod-2026-08-04\mineru-retry-expansion\bootstrap-receipt.json'
    $additionalQualityWorkers = @()
    if (Test-Path -LiteralPath $expandedConfigPath) {
        $expandedConfig = Get-Content -Raw -LiteralPath $expandedConfigPath |
            ConvertFrom-Json
        $additionalQualityWorkers = @($expandedConfig.workers |
            Where-Object { [int]$_.worker_index -ge 4 } |
            ForEach-Object { [int]$_.worker_index } |
            Sort-Object)
    }
    if ($additionalQualityWorkers.Count) {
        $expansionBootstrap = Get-Content -Raw -LiteralPath $expansionBootstrapPath |
            ConvertFrom-Json
        $validatedQualityWorkers = @($expansionBootstrap.workers |
            ForEach-Object { [int]$_.worker_index } |
            Sort-Object)
        if (
            $expansionBootstrap.status -ne 'ready_identity_bound_and_smoke_passed' -or
            [string]$expansionBootstrap.model_artifact_manifest_sha256 -ne `
                'sha256:1611a8892cc0e7e287d31c4a1b5af87652f0f6e4a3f80276b92b4c71f982de84' -or
            (Compare-Object $additionalQualityWorkers $validatedQualityWorkers)
        ) {
            throw 'Expanded MinerU quality workers did not pass the pinned runtime gate'
        }
    }
    $stagerArgs = @(
        $stager,
        '--failure-records', $failureRecordsPath,
        '--staged-root', (Join-Path $repository 'benchmark\datasets\private\mineru-public-core-workers-2026-08-04'),
        '--shard-plan', (Join-Path $repository 'benchmark\reports\generated\folynta-mineru344-public-core-4shard-plan-2026-08-04.json'),
        '--recovery-model', 'mineru-3.4.4-vlm-quality-retry',
        '--worker-health', $workerHealth,
        '--output-root', $qualityRetry
    )
    foreach ($workerIndex in $additionalQualityWorkers) {
        $stagerArgs += @('--additional-recovery-worker-index', $workerIndex)
    }
    Invoke-LoggedPython `
        -Name 'MinerU quality retry stager' `
        -Python $rootPython `
        -Arguments $stagerArgs
}

$terminalStatus = if ($qualityRetryNeeded) {
    'quality_retry_staged'
} else {
    'quality_retry_not_needed'
}
$terminal = [ordered]@{
    schema = 'folynta.official-evaluation-controller-terminal.v1'
    status = $terminalStatus
    input_count = 5132
    official_failure_record_count = [int]$failures.record_count
    recoverable_case_count = [int]$failures.recoverable_case_count
    failure_records = $failureRecordsPath
    quality_retry_staging = if ($qualityRetryNeeded) { $qualityRetry } else { $null }
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$terminal | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $terminalReceipt -Encoding utf8
Write-EvaluationEvent -Event $terminalStatus
exit 0
