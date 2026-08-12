param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,
    [Parameter(Mandatory = $true)]
    [string]$LaunchReceipt,
    [Parameter(Mandatory = $true)]
    [string]$CollectionRoot,
    [int]$PollSeconds = 60
)

$ErrorActionPreference = 'Stop'
if ($PollSeconds -lt 30 -or $PollSeconds -gt 300) {
    throw 'PollSeconds must be between 30 and 300'
}
$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$configFile = [IO.Path]::GetFullPath($ConfigPath)
$launchPath = [IO.Path]::GetFullPath($LaunchReceipt)
$collection = [IO.Path]::GetFullPath($CollectionRoot)
$config = Get-Content -Raw -LiteralPath $configFile | ConvertFrom-Json
$key = [IO.Path]::GetFullPath((Join-Path $repository $config.key))
$knownHosts = [IO.Path]::GetFullPath((Join-Path $repository $config.known_hosts))
$deadline = [DateTimeOffset]::Parse($config.deadline_utc).ToUniversalTime()
$progressRoot = Join-Path `
    $repository `
    'benchmark\reports\generated\folynta-mineru-quality-retry-monitor-2026-08-04'
$progressLog = Join-Path $progressRoot 'progress.jsonl'
$terminalReceipt = Join-Path $progressRoot 'terminal-receipt.json'
$null = New-Item -ItemType Directory -Path $progressRoot -Force

function Write-QualityMonitorEvent {
    param([string]$Event, [hashtable]$Fields = @{})
    $payload = [ordered]@{
        event = $Event
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    foreach ($keyName in $Fields.Keys) {
        $payload[$keyName] = $Fields[$keyName]
    }
    Add-Content `
        -LiteralPath $progressLog `
        -Value ($payload | ConvertTo-Json -Compress -Depth 10) `
        -Encoding utf8
}

Write-QualityMonitorEvent -Event 'waiting_for_mineru_quality_retry_launch'
while (-not (Test-Path -LiteralPath $launchPath)) {
    if ([DateTimeOffset]::UtcNow -ge $deadline) {
        Write-QualityMonitorEvent -Event 'deadline_reached_before_quality_launch'
        exit 2
    }
    Start-Sleep -Seconds $PollSeconds
}
$launch = Get-Content -Raw -LiteralPath $launchPath | ConvertFrom-Json
if (
    $launch.schema -ne 'folynta.mineru-quality-retry-launch.v1' -or
    $launch.recovery_model -ne 'mineru-3.4.4-vlm-quality-retry'
) {
    throw 'MinerU quality retry launch identity is invalid'
}
$configWorkers = @{}
foreach ($worker in @($config.workers)) {
    $configWorkers[[int]$worker.worker_index] = $worker
}
Write-QualityMonitorEvent `
    -Event 'mineru_quality_retry_launch_observed' `
    -Fields @{
        worker_count = [int]$launch.worker_count
        input_count = [int]$launch.input_count
    }

$allComplete = $false
while (-not $allComplete -and [DateTimeOffset]::UtcNow -lt $deadline) {
    $allComplete = $true
    $observations = @()
    foreach ($launched in @($launch.launches)) {
        $index = [int]$launched.worker_index
        $endpoint = $configWorkers[$index]
        $suites = @($launched.suites)
        $checks = @(
            $suites | ForEach-Object {
                "test -f /workspace/folynta/results/mineru-quality-r1/$($_)/run-summary.json || c=0"
            }
        ) -join '; '
        $remote = "c=1; $checks; printf `"%s`" `"`$c`""
        try {
            $value = & ssh `
                -i $key `
                -o BatchMode=yes `
                -o ConnectTimeout=15 `
                -o StrictHostKeyChecking=yes `
                -o "UserKnownHostsFile=$knownHosts" `
                -p ([int]$endpoint.port) `
                "root@$($endpoint.host)" `
                $remote
            if ($LASTEXITCODE -ne 0) {
                throw "ssh_exit_$LASTEXITCODE"
            }
            $complete = $value.Trim() -eq '1'
            $allComplete = $allComplete -and $complete
            $observations += [ordered]@{
                worker_index = $index
                suites = $suites
                complete = $complete
            }
        }
        catch {
            $allComplete = $false
            $observations += [ordered]@{
                worker_index = $index
                suites = $suites
                complete = $false
                error = $_.Exception.Message
            }
        }
    }
    Write-QualityMonitorEvent -Event 'quality_retry_poll' -Fields @{ workers = $observations }
    if (-not $allComplete) {
        Start-Sleep -Seconds $PollSeconds
    }
}
if (-not $allComplete) {
    Write-QualityMonitorEvent -Event 'deadline_reached_before_quality_completion'
    exit 2
}

$python = Join-Path $repository '.venv\Scripts\python.exe'
$collector = Join-Path `
    $repository `
    'benchmark\runpod_eval\collect_mineru_quality_retry_worker.py'
foreach ($launched in @($launch.launches)) {
    $index = [int]$launched.worker_index
    $endpoint = $configWorkers[$index]
    $receipt = Join-Path `
        $collection `
        ("worker-{0:d2}-mineru-quality-retry-collection.json" -f $index)
    if (Test-Path -LiteralPath $receipt) {
        continue
    }
    $collectorArgs = @(
        $collector,
        '--worker-index', $index,
        '--host', [string]$endpoint.host,
        '--port', [int]$endpoint.port,
        '--key', $key,
        '--known-hosts', $knownHosts,
        '--output-root', $collection
    )
    foreach ($suite in @($launched.suites)) {
        $collectorArgs += @('--suite', [string]$suite)
    }
    & $python @collectorArgs 2>&1 | ForEach-Object {
        Write-QualityMonitorEvent -Event 'collector_output' -Fields @{ line = [string]$_ }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "MinerU quality retry collection failed for worker $index"
    }
}
$terminal = [ordered]@{
    schema = 'folynta.mineru-quality-retry-monitor-terminal.v1'
    status = 'collected'
    worker_count = [int]$launch.worker_count
    input_count = [int]$launch.input_count
    collection_root = $collection
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$terminal | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $terminalReceipt -Encoding utf8
Write-QualityMonitorEvent `
    -Event 'mineru_quality_retry_collected' `
    -Fields @{ input_count = [int]$launch.input_count }
exit 0
