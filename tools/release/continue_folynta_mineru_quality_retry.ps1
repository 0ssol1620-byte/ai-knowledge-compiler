param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,
    [Parameter(Mandatory = $true)]
    [string]$OfficialTerminal,
    [Parameter(Mandatory = $true)]
    [string]$QualityRetryStaging,
    [Parameter(Mandatory = $true)]
    [string]$QualityRetryPackages,
    [Parameter(Mandatory = $true)]
    [string]$LaunchReceipt,
    [int]$PollSeconds = 60
)

$ErrorActionPreference = 'Stop'
if ($PollSeconds -lt 30 -or $PollSeconds -gt 300) {
    throw 'PollSeconds must be between 30 and 300'
}

$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$config = [IO.Path]::GetFullPath($ConfigPath)
$officialTerminalPath = [IO.Path]::GetFullPath($OfficialTerminal)
$staging = [IO.Path]::GetFullPath($QualityRetryStaging)
$packages = [IO.Path]::GetFullPath($QualityRetryPackages)
$launchPath = [IO.Path]::GetFullPath($LaunchReceipt)
$progressRoot = Join-Path `
    $repository `
    'benchmark\reports\generated\folynta-mineru-quality-retry-controller-2026-08-04'
$progressLog = Join-Path $progressRoot 'progress.jsonl'
$terminalReceipt = Join-Path $progressRoot 'terminal-receipt.json'
$null = New-Item -ItemType Directory -Path $progressRoot -Force

function Write-QualityEvent {
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
    Add-Content `
        -LiteralPath $progressLog `
        -Value ($payload | ConvertTo-Json -Compress -Depth 10) `
        -Encoding utf8
}

Write-QualityEvent -Event 'waiting_for_quality_retry_staging'
while (-not (Test-Path -LiteralPath $officialTerminalPath)) {
    Start-Sleep -Seconds $PollSeconds
}
$official = Get-Content -Raw -LiteralPath $officialTerminalPath | ConvertFrom-Json
if ($official.status -eq 'quality_retry_not_needed') {
    $terminal = [ordered]@{
        schema = 'folynta.mineru-quality-retry-controller-terminal.v1'
        status = 'not_needed'
        completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    $terminal | ConvertTo-Json -Depth 6 |
        Set-Content -LiteralPath $terminalReceipt -Encoding utf8
    Write-QualityEvent -Event 'quality_retry_not_needed'
    exit 0
}
if ($official.status -ne 'quality_retry_staged') {
    throw "Official evaluation controller is not ready: $($official.status)"
}
$stagingReceipt = Join-Path $staging 'selective-recovery-receipt.json'
if (-not (Test-Path -LiteralPath $stagingReceipt)) {
    throw 'Official evaluation terminal exists without quality retry staging'
}
$staged = Get-Content -Raw -LiteralPath $stagingReceipt | ConvertFrom-Json
if (
    $staged.recovery_model -ne 'mineru-3.4.4-vlm-quality-retry' -or
    [int]$staged.input_count -ne [int]$official.recoverable_case_count
) {
    throw 'MinerU quality retry staging coverage is invalid'
}
Write-QualityEvent `
    -Event 'quality_retry_staging_observed' `
    -Fields @{ input_count = [int]$staged.input_count }

$python = Join-Path $repository '.venv\Scripts\python.exe'
$packager = Join-Path `
    $repository `
    'benchmark\runpod_eval\package_selective_recovery_inputs.py'
$packageReceipt = Join-Path $packages 'package-receipt.json'
if (-not (Test-Path -LiteralPath $packageReceipt)) {
    & $python $packager `
        --staging-root $staging `
        --output-root $packages 2>&1 | ForEach-Object {
            Write-QualityEvent -Event 'packager_output' -Fields @{ line = [string]$_ }
        }
    if ($LASTEXITCODE -ne 0) {
        throw "MinerU quality retry packaging failed with exit $LASTEXITCODE"
    }
}
$packaged = Get-Content -Raw -LiteralPath $packageReceipt | ConvertFrom-Json
if ([int]$packaged.input_count -ne [int]$staged.input_count) {
    throw 'MinerU quality retry package coverage is invalid'
}
Write-QualityEvent `
    -Event 'quality_retry_packaged' `
    -Fields @{
        package_count = [int]$packaged.package_count
        input_count = [int]$packaged.input_count
    }

$launcher = Join-Path `
    $repository `
    'benchmark\runpod_eval\launch_mineru_quality_retry_workers.py'
if (-not (Test-Path -LiteralPath $launchPath)) {
    & $python $launcher `
        --repository-root $repository `
        --config $config `
        --package-receipt $packageReceipt `
        --package-root $packages `
        --mineru-runner (Join-Path $repository 'benchmark\runpod_eval\mineru_stage2.py') `
        --quality-runner (Join-Path $repository 'benchmark\runpod_eval\remote_run_mineru_quality_retry.sh') `
        --stall-watchdog (Join-Path $repository 'benchmark\runpod_eval\remote_stall_watchdog.sh') `
        --output-receipt $launchPath 2>&1 | ForEach-Object {
            Write-QualityEvent -Event 'launcher_output' -Fields @{ line = [string]$_ }
        }
    if ($LASTEXITCODE -ne 0) {
        throw "MinerU quality retry launch failed with exit $LASTEXITCODE"
    }
}
$launch = Get-Content -Raw -LiteralPath $launchPath | ConvertFrom-Json
if ([int]$launch.input_count -ne [int]$staged.input_count) {
    throw 'MinerU quality retry launch coverage is invalid'
}
$terminal = [ordered]@{
    schema = 'folynta.mineru-quality-retry-controller-terminal.v1'
    status = 'launched'
    worker_count = [int]$launch.worker_count
    input_count = [int]$launch.input_count
    launch_receipt = $launchPath
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$terminal | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $terminalReceipt -Encoding utf8
Write-QualityEvent `
    -Event 'quality_retry_launched' `
    -Fields @{ input_count = [int]$launch.input_count }
exit 0
