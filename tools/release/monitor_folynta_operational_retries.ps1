param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,
    [Parameter(Mandatory = $true)]
    [string]$LaunchReceipt,
    [Parameter(Mandatory = $true)]
    [string]$RetryPlan,
    [Parameter(Mandatory = $true)]
    [string]$PrimaryCollectionRoot,
    [Parameter(Mandatory = $true)]
    [string]$RetryCollectionRoot,
    [Parameter(Mandatory = $true)]
    [string]$CompositeRoot,
    [Parameter(Mandatory = $true)]
    [string]$MergedRoot,
    [int]$PollSeconds = 60
)

$ErrorActionPreference = 'Stop'
if ($PollSeconds -lt 30 -or $PollSeconds -gt 300) {
    throw 'PollSeconds must be between 30 and 300'
}

$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$configFile = [IO.Path]::GetFullPath($ConfigPath)
$launchPath = [IO.Path]::GetFullPath($LaunchReceipt)
$retryPlanPath = [IO.Path]::GetFullPath($RetryPlan)
$primaryCollection = [IO.Path]::GetFullPath($PrimaryCollectionRoot)
$retryCollection = [IO.Path]::GetFullPath($RetryCollectionRoot)
$composite = [IO.Path]::GetFullPath($CompositeRoot)
$merged = [IO.Path]::GetFullPath($MergedRoot)
$config = Get-Content -Raw -LiteralPath $configFile | ConvertFrom-Json
$key = [IO.Path]::GetFullPath((Join-Path $repository $config.key))
$knownHosts = [IO.Path]::GetFullPath((Join-Path $repository $config.known_hosts))
$deadline = [DateTimeOffset]::Parse($config.deadline_utc).ToUniversalTime()
$progressRoot = Join-Path `
    $repository `
    'benchmark\reports\generated\runpod-operational-retry-monitor-2026-08-04'
$progressLog = Join-Path $progressRoot 'progress.jsonl'
$terminalReceipt = Join-Path $progressRoot 'terminal-receipt.json'
$null = New-Item -ItemType Directory -Path $progressRoot -Force

function Write-MonitorEvent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Event,
        [hashtable]$Fields = @{}
    )
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

Write-MonitorEvent -Event 'waiting_for_operational_retry_launch'
while (-not (Test-Path -LiteralPath $launchPath)) {
    if ([DateTimeOffset]::UtcNow -ge $deadline) {
        Write-MonitorEvent -Event 'deadline_reached_before_retry_launch'
        exit 2
    }
    Start-Sleep -Seconds $PollSeconds
}
if (-not (Test-Path -LiteralPath $retryPlanPath)) {
    throw 'Operational retry launch exists without its retry plan'
}

$launch = Get-Content -Raw -LiteralPath $launchPath | ConvertFrom-Json
$plan = Get-Content -Raw -LiteralPath $retryPlanPath | ConvertFrom-Json
if (
    $launch.schema -ne 'folynta.operational-retry-launch.v1' -or
    [int]$launch.input_count -ne [int]$plan.failed_input_count
) {
    throw 'Operational retry launch and plan coverage differ'
}
$workerPlan = @{}
foreach ($worker in @($plan.workers)) {
    $index = [int]$worker.retry_worker_index
    $workerPlan[$index] = @($worker.suites | ForEach-Object { [string]$_.benchmark_id })
}
$configWorkers = @{}
foreach ($worker in @($config.workers)) {
    $configWorkers[[int]$worker.worker_index] = $worker
}
if (@($launch.launches).Count -ne $workerPlan.Count) {
    throw 'Operational retry launch worker coverage differs from the retry plan'
}
Write-MonitorEvent `
    -Event 'operational_retry_launch_observed' `
    -Fields @{
        worker_count = @($launch.launches).Count
        input_count = [int]$launch.input_count
    }

$allComplete = $false
while (-not $allComplete -and [DateTimeOffset]::UtcNow -lt $deadline) {
    $allComplete = $true
    $observations = @()
    foreach ($launched in @($launch.launches)) {
        $index = [int]$launched.worker_index
        $endpoint = $configWorkers[$index]
        $suites = @($workerPlan[$index])
        $checks = @(
            $suites | ForEach-Object {
                "test -f /workspace/folynta/results/operational-retry/$($_)/run-summary.json || c=0"
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
    Write-MonitorEvent -Event 'retry_poll' -Fields @{ workers = $observations }
    if (-not $allComplete) {
        Start-Sleep -Seconds $PollSeconds
    }
}
if (-not $allComplete) {
    Write-MonitorEvent -Event 'deadline_reached_before_retry_completion'
    exit 2
}

$python = Join-Path $repository '.venv\Scripts\python.exe'
$collector = Join-Path `
    $repository `
    'benchmark\runpod_eval\collect_operational_retry_worker.py'
foreach ($launched in @($launch.launches)) {
    $index = [int]$launched.worker_index
    $endpoint = $configWorkers[$index]
    $receipt = Join-Path `
        $retryCollection `
        ("worker-{0:d2}-operational-retry-collection.json" -f $index)
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
        '--output-root', $retryCollection
    )
    foreach ($suite in @($workerPlan[$index])) {
        $collectorArgs += @('--suite', $suite)
    }
    & $python @collectorArgs 2>&1 | ForEach-Object {
        Write-MonitorEvent -Event 'collector_output' -Fields @{ line = [string]$_ }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Operational retry collection failed for worker $index"
    }
}
Write-MonitorEvent -Event 'operational_retry_collected'

$apply = Join-Path $repository 'benchmark\runpod_eval\apply_operational_retries.py'
if (-not (Test-Path -LiteralPath $composite)) {
    $applyArgs = @($apply)
    for ($index = 0; $index -lt 4; $index++) {
        $applyArgs += @(
            '--primary',
            "$index=$(Join-Path $primaryCollection ("worker-{0:d2}" -f $index))"
        )
    }
    foreach ($launched in @($launch.launches)) {
        $index = [int]$launched.worker_index
        $applyArgs += @(
            '--retry',
            "$index=$(Join-Path $retryCollection ("worker-{0:d2}" -f $index))"
        )
    }
    $applyArgs += @(
        '--retry-plan', $retryPlanPath,
        '--output-root', $composite
    )
    & $python @applyArgs 2>&1 | ForEach-Object {
        Write-MonitorEvent -Event 'overlay_output' -Fields @{ line = [string]$_ }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Operational retry overlay failed with exit $LASTEXITCODE"
    }
}
Write-MonitorEvent -Event 'operational_retry_overlaid'

$merger = Join-Path $repository 'benchmark\runpod_eval\public_core_merge.py'
if (-not (Test-Path -LiteralPath $merged)) {
    $mergeArgs = @($merger)
    for ($index = 0; $index -lt 4; $index++) {
        $mergeArgs += @(
            '--worker',
            "$index=$(Join-Path $composite ("worker-{0:d2}" -f $index))"
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
        Write-MonitorEvent -Event 'merge_output' -Fields @{ line = [string]$_ }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Public-core merge failed with exit $LASTEXITCODE"
    }
}
$mergeReceipt = Get-Content -Raw -LiteralPath (Join-Path $merged 'merge-receipt.json') |
    ConvertFrom-Json
$status = if (
    [int]$mergeReceipt.completed -eq 5132 -and
    [int]$mergeReceipt.failed -eq 0 -and
    $mergeReceipt.complete_case_coverage -eq $true
) { 'merged_complete' } else { 'merged_with_unresolved' }
$terminal = [ordered]@{
    schema = 'folynta.operational-retry-monitor-terminal.v1'
    status = $status
    planned = [int]$plan.failed_input_count
    completed = [int]$mergeReceipt.completed
    unresolved = [int]$mergeReceipt.failed
    merged_root = $merged
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$terminal | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $terminalReceipt -Encoding utf8
Write-MonitorEvent -Event $status -Fields @{ unresolved = [int]$mergeReceipt.failed }
if ($status -eq 'merged_complete') { exit 0 }
exit 3
