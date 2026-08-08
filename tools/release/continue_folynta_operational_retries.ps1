param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryRoot,

    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,

    [Parameter(Mandatory = $true)]
    [string]$CollectionRoot,

    [Parameter(Mandatory = $true)]
    [string]$MonitorTerminal,

    [Parameter(Mandatory = $true)]
    [string]$RetryStagingRoot,

    [Parameter(Mandatory = $true)]
    [string]$RetryPackageRoot,

    [Parameter(Mandatory = $true)]
    [string]$LaunchReceipt,

    [int]$PollSeconds = 60
)

$ErrorActionPreference = 'Stop'
if ($PollSeconds -lt 30 -or $PollSeconds -gt 300) {
    throw 'PollSeconds must be between 30 and 300'
}

$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$configFile = [IO.Path]::GetFullPath($ConfigPath)
$collection = [IO.Path]::GetFullPath($CollectionRoot)
$terminal = [IO.Path]::GetFullPath($MonitorTerminal)
$retryStaging = [IO.Path]::GetFullPath($RetryStagingRoot)
$retryPackages = [IO.Path]::GetFullPath($RetryPackageRoot)
$launchReceiptPath = [IO.Path]::GetFullPath($LaunchReceipt)
$config = Get-Content -Raw -LiteralPath $configFile | ConvertFrom-Json
$deadline = [DateTimeOffset]::Parse($config.deadline_utc).ToUniversalTime()
$expansionIndices = @($config.workers |
    Where-Object { [int]$_.worker_index -ge 4 } |
    ForEach-Object { [int]$_.worker_index } |
    Sort-Object)
if ($expansionIndices.Count) {
    $expansionBootstrapPath = Join-Path `
        $repository `
        'benchmark\datasets\private\runpod-2026-08-04\mineru-retry-expansion\bootstrap-receipt.json'
    if (-not (Test-Path -LiteralPath $expansionBootstrapPath)) {
        throw 'Expanded retry workers have no bootstrap evidence'
    }
    $expansionBootstrap = Get-Content -Raw -LiteralPath $expansionBootstrapPath |
        ConvertFrom-Json
    $validatedIndices = @($expansionBootstrap.workers |
        ForEach-Object { [int]$_.worker_index } |
        Sort-Object)
    if (
        $expansionBootstrap.status -ne 'ready_identity_bound_and_smoke_passed' -or
        [string]$expansionBootstrap.model_artifact_manifest_sha256 -ne `
            'sha256:1611a8892cc0e7e287d31c4a1b5af87652f0f6e4a3f80276b92b4c71f982de84' -or
        (Compare-Object $expansionIndices $validatedIndices)
    ) {
        throw 'Expanded retry workers did not pass the pinned runtime gate'
    }
}
$progressRoot = Join-Path $repository `
    'benchmark\reports\generated\runpod-operational-retry-controller-2026-08-04'
$log = Join-Path $progressRoot 'controller.jsonl'
$null = New-Item -ItemType Directory -Path $progressRoot -Force

function Write-ControllerEvent {
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
        -LiteralPath $log `
        -Value ($payload | ConvertTo-Json -Compress -Depth 8) `
        -Encoding utf8
}

Write-ControllerEvent -Event 'waiting_for_full_collection'
while (-not (Test-Path -LiteralPath $terminal)) {
    if ([DateTimeOffset]::UtcNow -ge $deadline) {
        Write-ControllerEvent -Event 'deadline_reached_before_collection'
        exit 2
    }
    Start-Sleep -Seconds $PollSeconds
}

$terminalPayload = Get-Content -Raw -LiteralPath $terminal | ConvertFrom-Json
if ($terminalPayload.status -ne 'collected' -or [int]$terminalPayload.worker_count -ne 4) {
    throw 'Full collection terminal receipt is invalid'
}
Write-ControllerEvent -Event 'full_collection_observed'

$python = Join-Path $repository '.venv\Scripts\python.exe'
$planner = Join-Path $repository 'benchmark\runpod_eval\plan_operational_retries.py'
$classifier = Join-Path `
    $repository `
    'benchmark\runpod_eval\classify_operational_worker_health.py'
$packager = Join-Path `
    $repository `
    'benchmark\runpod_eval\package_operational_retry_inputs.py'
$launcher = Join-Path `
    $repository `
    'benchmark\runpod_eval\launch_operational_retry_workers.py'
$shardPlan = Join-Path `
    $repository `
    'benchmark\reports\generated\folynta-mineru344-public-core-4shard-plan-2026-08-04.json'
$stagedRoot = Join-Path `
    $repository `
    'benchmark\datasets\private\mineru-public-core-workers-2026-08-04'
$retryPlanReceipt = Join-Path $retryStaging 'retry-plan-receipt.json'
$workerHealthReceipt = Join-Path `
    $progressRoot `
    'operational-worker-health.json'
$packageReceipt = Join-Path $retryPackages 'package-receipt.json'

if (-not (Test-Path -LiteralPath $workerHealthReceipt)) {
    $classifierArgs = @($classifier)
    for ($worker = 0; $worker -lt 4; $worker++) {
        $workerRoot = Join-Path $collection ("worker-{0:d2}" -f $worker)
        $classifierArgs += @('--worker-result', "$worker=$workerRoot")
    }
    $classifierArgs += @('--output', $workerHealthReceipt)
    & $python @classifierArgs 2>&1 | ForEach-Object {
        Write-ControllerEvent -Event 'classifier_output' -Fields @{ line = [string]$_ }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Operational worker health classification failed with exit $LASTEXITCODE"
    }
}
$workerHealth = Get-Content -Raw -LiteralPath $workerHealthReceipt | ConvertFrom-Json
$combinedEligibleWorkerCount = @($workerHealth.eligible_retry_workers).Count + `
    $expansionIndices.Count
if ($combinedEligibleWorkerCount -lt 2) {
    throw 'Operational worker health and expansion pool provide fewer than two retry targets'
}
Write-ControllerEvent `
    -Event 'operational_worker_health_classified' `
    -Fields @{
        eligible_retry_workers = @($workerHealth.eligible_retry_workers)
        expansion_retry_workers = $expansionIndices
        combined_eligible_retry_worker_count = $combinedEligibleWorkerCount
        quarantined_worker_indices = @($workerHealth.quarantined_worker_indices)
    }

if (-not (Test-Path -LiteralPath $retryPlanReceipt)) {
    $plannerArgs = @($planner)
    for ($worker = 0; $worker -lt 4; $worker++) {
        $workerRoot = Join-Path $collection ("worker-{0:d2}" -f $worker)
        $plannerArgs += @('--worker-result', "$worker=$workerRoot")
    }
    $plannerArgs += @(
        '--staged-root', $stagedRoot,
        '--shard-plan', $shardPlan,
        '--output-root', $retryStaging,
        '--worker-health', $workerHealthReceipt
    )
    foreach ($worker in @($config.workers | Where-Object { [int]$_.worker_index -ge 4 })) {
        $plannerArgs += @('--additional-retry-worker-index', [int]$worker.worker_index)
    }
    if ($expansionIndices.Count) {
        $eligiblePrimary = @($workerHealth.eligible_retry_workers |
            ForEach-Object { [int]$_ } | Sort-Object)
        $quarantinedPrimary = @($workerHealth.quarantined_worker_indices |
            ForEach-Object { [int]$_ } | Sort-Object)
        for ($primary = 0; $primary -lt 4; $primary++) {
            if ($quarantinedPrimary -contains $primary) {
                $targets = @($expansionIndices)
            }
            else {
                $targets = @($eligiblePrimary | Where-Object { $_ -ne $primary })
                if (-not $targets.Count) {
                    $targets = @($expansionIndices)
                }
            }
            if (-not $targets.Count) {
                throw "No explicit retry target remains for primary worker $primary"
            }
            $plannerArgs += @('--retry-route', "$primary=$($targets -join ',')")
        }
    }
    & $python @plannerArgs 2>&1 | ForEach-Object {
        Write-ControllerEvent -Event 'planner_output' -Fields @{ line = [string]$_ }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Operational retry planner failed with exit $LASTEXITCODE"
    }
}
$retryPlan = Get-Content -Raw -LiteralPath $retryPlanReceipt | ConvertFrom-Json
if (
    [int]$retryPlan.failed_input_count -ne [int]$retryPlan.staged_input_count -or
    $retryPlan.different_worker_only -ne $true
) {
    throw 'Operational retry plan coverage or routing is invalid'
}
Write-ControllerEvent `
    -Event 'operational_retry_planned' `
    -Fields @{ failed_input_count = [int]$retryPlan.failed_input_count }

if (-not (Test-Path -LiteralPath $packageReceipt)) {
    & $python $packager `
        --staging-root $retryStaging `
        --output-root $retryPackages 2>&1 | ForEach-Object {
            Write-ControllerEvent -Event 'packager_output' -Fields @{ line = [string]$_ }
        }
    if ($LASTEXITCODE -ne 0) {
        throw "Operational retry packager failed with exit $LASTEXITCODE"
    }
}
$packages = Get-Content -Raw -LiteralPath $packageReceipt | ConvertFrom-Json
if ([int]$packages.input_count -ne [int]$retryPlan.failed_input_count) {
    throw 'Operational retry package coverage is invalid'
}
Write-ControllerEvent `
    -Event 'operational_retry_packaged' `
    -Fields @{
        package_count = [int]$packages.package_count
        input_count = [int]$packages.input_count
    }

if (-not (Test-Path -LiteralPath $launchReceiptPath)) {
    $launcherArgs = @(
        $launcher,
        '--repository-root', $repository,
        '--config', $configFile,
        '--package-receipt', $packageReceipt,
        '--package-root', $retryPackages,
        '--mineru-runner', (Join-Path $repository 'benchmark\runpod_eval\mineru_stage2.py'),
        '--retry-runner', (Join-Path $repository 'benchmark\runpod_eval\remote_run_operational_retry.sh'),
        '--stall-watchdog', (Join-Path $repository 'benchmark\runpod_eval\remote_stall_watchdog.sh'),
        '--retry-plan', $retryPlanReceipt,
        '--output-receipt', $launchReceiptPath
    )
    $prefetchLaunch = Join-Path $repository `
        'benchmark\reports\generated\folynta-operational-retry-prefetch-launch-2026-08-04.json'
    $prefetchPlan = Join-Path $repository `
        'benchmark\datasets\private\runpod-2026-08-04\operational-retry-prefetch-staging\retry-plan-receipt.json'
    if ((Test-Path -LiteralPath $prefetchLaunch) -and (Test-Path -LiteralPath $prefetchPlan)) {
        $launcherArgs += @(
            '--preexisting-launch-receipt', $prefetchLaunch,
            '--preexisting-retry-plan', $prefetchPlan
        )
    }
    & $python @launcherArgs 2>&1 | ForEach-Object {
            Write-ControllerEvent -Event 'launcher_output' -Fields @{ line = [string]$_ }
        }
    if ($LASTEXITCODE -ne 0) {
        throw "Operational retry launcher failed with exit $LASTEXITCODE"
    }
}
Write-ControllerEvent `
    -Event 'operational_retry_launched' `
    -Fields @{ launch_receipt = $launchReceiptPath }
exit 0
