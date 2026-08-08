param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryRoot,

    [Parameter(Mandatory = $true)]
    [string]$ConfigPath
)

$ErrorActionPreference = 'Stop'
$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$configFile = [IO.Path]::GetFullPath($ConfigPath)
$config = Get-Content -Raw -LiteralPath $configFile | ConvertFrom-Json
$expansionIndices = @($config.workers |
    Where-Object { [int]$_.worker_index -ge 4 } |
    ForEach-Object { [int]$_.worker_index } |
    Sort-Object)
if ($expansionIndices.Count -lt 2) {
    throw 'Operational retry prefetch requires at least two expansion workers'
}

$privateRoot = Join-Path $repository 'benchmark\datasets\private\runpod-2026-08-04'
$generatedRoot = Join-Path $repository 'benchmark\reports\generated'
$collection = Join-Path $privateRoot 'collected-full'
$staging = Join-Path $privateRoot 'operational-retry-prefetch-staging'
$packages = Join-Path $privateRoot 'operational-retry-prefetch-packages'
$launchReceipt = Join-Path $generatedRoot `
    'folynta-operational-retry-prefetch-launch-2026-08-04.json'
$terminalRoot = Join-Path $generatedRoot `
    'folynta-operational-retry-prefetch-controller-2026-08-04'
$terminal = Join-Path $terminalRoot 'terminal-receipt.json'
$log = Join-Path $terminalRoot 'controller.jsonl'
$null = New-Item -ItemType Directory -Path $terminalRoot -Force

function Write-PrefetchEvent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Event,
        [hashtable]$Fields = @{}
    )
    $payload = [ordered]@{
        event = $Event
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    foreach ($key in $Fields.Keys) { $payload[$key] = $Fields[$key] }
    Add-Content -LiteralPath $log `
        -Value ($payload | ConvertTo-Json -Compress -Depth 8) -Encoding utf8
}

if (Test-Path -LiteralPath $terminal) {
    Get-Content -Raw -LiteralPath $terminal
    exit 0
}

foreach ($worker in 1, 2) {
    $root = Join-Path $collection ("worker-{0:d2}" -f $worker)
    foreach ($suite in 'parsebench', 'omnidocbench', 'olmocr-bench') {
        if (-not (Test-Path -LiteralPath (Join-Path $root "$suite\run-summary.json"))) {
            throw "Completed worker $worker is missing $suite summary"
        }
    }
}

$python = Join-Path $repository '.venv\Scripts\python.exe'
$planner = Join-Path $repository 'benchmark\runpod_eval\plan_operational_retries.py'
$packager = Join-Path $repository `
    'benchmark\runpod_eval\package_operational_retry_inputs.py'
$launcher = Join-Path $repository `
    'benchmark\runpod_eval\launch_operational_retry_workers.py'
$shardPlan = Join-Path $generatedRoot `
    'folynta-mineru344-public-core-4shard-plan-2026-08-04.json'
$stagedRoot = Join-Path $repository `
    'benchmark\datasets\private\mineru-public-core-workers-2026-08-04'
$planReceipt = Join-Path $staging 'retry-plan-receipt.json'
$packageReceipt = Join-Path $packages 'package-receipt.json'

if (-not (Test-Path -LiteralPath $planReceipt)) {
    $plannerArgs = @(
        $planner,
        '--worker-result', "1=$(Join-Path $collection 'worker-01')",
        '--worker-result', "2=$(Join-Path $collection 'worker-02')",
        '--partial-primary-worker-index', 1,
        '--partial-primary-worker-index', 2,
        '--staged-root', $stagedRoot,
        '--shard-plan', $shardPlan,
        '--output-root', $staging
    )
    foreach ($worker in $expansionIndices) {
        $plannerArgs += @('--additional-retry-worker-index', $worker)
    }
    $route = $expansionIndices -join ','
    $plannerArgs += @('--retry-route', "1=$route", '--retry-route', "2=$route")
    & $python @plannerArgs 2>&1 | ForEach-Object {
        Write-PrefetchEvent -Event 'planner_output' -Fields @{ line = [string]$_ }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Operational retry prefetch planner failed with exit $LASTEXITCODE"
    }
}
$plan = Get-Content -Raw -LiteralPath $planReceipt | ConvertFrom-Json
if (
    $plan.routing_policy -ne 'explicit-primary-route-map-v1' -or
    $plan.complete_primary_scope -ne $false -or
    (@($plan.primary_worker_scope) -join ',') -ne '1,2' -or
    [int]$plan.failed_input_count -ne [int]$plan.staged_input_count -or
    $plan.different_worker_only -ne $true
) {
    throw 'Operational retry prefetch plan failed its coverage or route gate'
}
Write-PrefetchEvent -Event 'prefetch_planned' -Fields @{
    input_count = [int]$plan.failed_input_count
    expansion_workers = $expansionIndices
}

if (-not (Test-Path -LiteralPath $packageReceipt)) {
    & $python $packager --staging-root $staging --output-root $packages 2>&1 |
        ForEach-Object {
            Write-PrefetchEvent -Event 'packager_output' -Fields @{ line = [string]$_ }
        }
    if ($LASTEXITCODE -ne 0) {
        throw "Operational retry prefetch packager failed with exit $LASTEXITCODE"
    }
}
$package = Get-Content -Raw -LiteralPath $packageReceipt | ConvertFrom-Json
if ([int]$package.input_count -ne [int]$plan.failed_input_count) {
    throw 'Operational retry prefetch package coverage is invalid'
}

if (-not (Test-Path -LiteralPath $launchReceipt)) {
    & $python $launcher `
        --repository-root $repository `
        --config $configFile `
        --package-receipt $packageReceipt `
        --package-root $packages `
        --mineru-runner (Join-Path $repository 'benchmark\runpod_eval\mineru_stage2.py') `
        --retry-runner (Join-Path $repository 'benchmark\runpod_eval\remote_run_operational_retry.sh') `
        --stall-watchdog (Join-Path $repository 'benchmark\runpod_eval\remote_stall_watchdog.sh') `
        --retry-plan $planReceipt `
        --output-receipt $launchReceipt 2>&1 | ForEach-Object {
            Write-PrefetchEvent -Event 'launcher_output' -Fields @{ line = [string]$_ }
        }
    if ($LASTEXITCODE -ne 0) {
        throw "Operational retry prefetch launch failed with exit $LASTEXITCODE"
    }
}
$launch = Get-Content -Raw -LiteralPath $launchReceipt | ConvertFrom-Json
if (
    [int]$launch.input_count -ne [int]$plan.failed_input_count -or
    @($launch.launches).Count -ne @($plan.workers).Count
) {
    throw 'Operational retry prefetch launch coverage is invalid'
}

$receipt = [ordered]@{
    schema = 'folynta.operational-retry-prefetch-terminal.v1'
    status = 'launched_before_full_baseline_completion'
    primary_worker_scope = @(1, 2)
    retry_worker_indices = @($launch.launches | ForEach-Object { [int]$_.worker_index })
    input_count = [int]$launch.input_count
    plan = $planReceipt
    launch = $launchReceipt
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$receipt | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $terminal -Encoding utf8
Write-PrefetchEvent -Event 'prefetch_launched' -Fields @{
    input_count = [int]$launch.input_count
}
$receipt | ConvertTo-Json -Compress -Depth 8
