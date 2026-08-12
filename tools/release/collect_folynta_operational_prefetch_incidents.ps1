param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryRoot,

    [Parameter(Mandatory = $true)]
    [string]$ConfigPath
)

$ErrorActionPreference = 'Stop'
$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$configFile = [IO.Path]::GetFullPath($ConfigPath)
$generated = [IO.Path]::GetFullPath(
    (Join-Path $repository 'benchmark\reports\generated')
)
$outputRoot = [IO.Path]::GetFullPath(
    (Join-Path $generated 'folynta-operational-prefetch-incident-evidence-2026-08-04')
)
if (-not $outputRoot.StartsWith(
        $generated + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw 'Incident evidence output escaped the generated evidence root'
}
$receiptPath = Join-Path $outputRoot 'incident-receipt.json'
if (Test-Path -LiteralPath $receiptPath) {
    Get-Content -Raw -LiteralPath $receiptPath
    exit 0
}
$null = New-Item -ItemType Directory -Path $outputRoot -Force

$config = Get-Content -Raw -LiteralPath $configFile | ConvertFrom-Json
$key = [IO.Path]::GetFullPath((Join-Path $repository $config.key))
$knownHosts = [IO.Path]::GetFullPath((Join-Path $repository $config.known_hosts))
$workers = @($config.workers |
    Where-Object { [int]$_.worker_index -ge 4 } |
    Sort-Object worker_index)
if ($workers.Count -lt 1) { throw 'No expansion workers are configured' }

$remoteIncidentNames = @(
    'operational-retry.failed-missing-input-contract-worker-{0:d2}',
    'operational-retry.failed-invalid-shard-index-worker-{0:d2}'
)
$workerObservations = @()
foreach ($worker in $workers) {
    $index = [int]$worker.worker_index
    $workerRoot = Join-Path $outputRoot ("worker-{0:d2}" -f $index)
    $null = New-Item -ItemType Directory -Path $workerRoot -Force
    $collected = @()
    foreach ($pattern in $remoteIncidentNames) {
        $name = $pattern -f $index
        $remotePath = "/workspace/folynta/results/$name"
        & ssh `
            -i $key `
            -o BatchMode=yes `
            -o ConnectTimeout=15 `
            -o StrictHostKeyChecking=yes `
            -o "UserKnownHostsFile=$knownHosts" `
            -p ([int]$worker.port) `
            "root@$($worker.host)" `
            "test -d '$remotePath'"
        if ($LASTEXITCODE -eq 0) {
            & scp `
                -r `
                -i $key `
                -o BatchMode=yes `
                -o ConnectTimeout=15 `
                -o StrictHostKeyChecking=yes `
                -o "UserKnownHostsFile=$knownHosts" `
                -P ([int]$worker.port) `
                "root@$($worker.host):$remotePath" `
                $workerRoot
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to collect incident evidence for worker $index"
            }
            $collected += $name
        }
    }
    $progressCommand = @'
c=$(find /workspace/folynta/results/operational-retry -name "*_model.json" -type f 2>/dev/null | wc -l)
s=$(find /workspace/folynta/results/operational-retry -name run-summary.json -type f 2>/dev/null | wc -l)
r=$(pgrep -fc "[r]emote_run_operational_retry.sh" || true)
printf '%s,%s,%s\n' "$c" "$s" "$r"
'@
    $progress = & ssh `
        -i $key `
        -o BatchMode=yes `
        -o ConnectTimeout=15 `
        -o StrictHostKeyChecking=yes `
        -o "UserKnownHostsFile=$knownHosts" `
        -p ([int]$worker.port) `
        "root@$($worker.host)" `
        $progressCommand
    if ($LASTEXITCODE -ne 0 -or [string]$progress -notmatch '^\d+,\d+,\d+$') {
        throw "Failed to observe corrected retry worker $index"
    }
    $values = ([string]$progress).Trim().Split(',')
    $workerObservations += [ordered]@{
        worker_index = $index
        collected_incident_directories = $collected
        corrected_run_model_artifact_count = [int]$values[0]
        corrected_run_summary_count = [int]$values[1]
        corrected_runner_process_count = [int]$values[2]
    }
}

$files = @()
function Repository-Relative {
    param([Parameter(Mandatory = $true)][string]$Path)
    $resolved = [IO.Path]::GetFullPath($Path)
    $prefix = $repository + [IO.Path]::DirectorySeparatorChar
    if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Evidence path escaped the repository: $resolved"
    }
    $resolved.Substring($prefix.Length).Replace('\', '/')
}
foreach ($file in Get-ChildItem -LiteralPath $outputRoot -Recurse -File) {
    if ($file.Length -gt 10MB -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Incident evidence file is unsafe or unexpectedly large: $($file.FullName)"
    }
    $relative = Repository-Relative -Path $file.FullName
    $files += [ordered]@{
        path = $relative
        size_bytes = $file.Length
        sha256 = 'sha256:' + (
            Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256
        ).Hash.ToLowerInvariant()
    }
}

function Bound-File {
    param([Parameter(Mandatory = $true)][string]$Path)
    $resolved = [IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "Required incident evidence file is missing: $resolved"
    }
    [ordered]@{
        path = Repository-Relative -Path $resolved
        sha256 = 'sha256:' + (
            Get-FileHash -LiteralPath $resolved -Algorithm SHA256
        ).Hash.ToLowerInvariant()
    }
}

$failedLaunch = Join-Path $generated `
    'folynta-operational-retry-prefetch-launch-failed-missing-result-parent-2026-08-04.json'
$failedTerminal = Join-Path $generated `
    'folynta-operational-retry-prefetch-controller-2026-08-04\terminal-receipt.failed-missing-result-parent.json'
$correctedLaunch = Join-Path $generated `
    'folynta-operational-retry-prefetch-launch-2026-08-04.json'
$receipt = [ordered]@{
    schema = 'folynta.operational-prefetch-incident-evidence.v1'
    evidence_kind = 'live-observed-prefetch-launch-faults-and-corrected-run'
    observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    incidents = @(
        [ordered]@{
            code = 'missing_result_parent_before_nohup_redirection'
            effect = 'PID-shaped launch receipt without a running retry process'
            correction = 'create the result parent and require worker-state readiness'
        },
        [ordered]@{
            code = 'missing_runtime_input_contract_dependency'
            effect = 'MinerU retry runner exited at Python import'
            correction = 'hash-verify and upload input_contract.py with mineru_stage2.py'
        },
        [ordered]@{
            code = 'expansion_worker_id_used_as_shard_ordinal'
            effect = 'public-core shard contract rejected shard index outside shard count'
            correction = 'separate retry worker identity from zero-based shard ordinal'
        }
    )
    failed_launch_receipt = (Bound-File -Path $failedLaunch)
    failed_controller_terminal = (Bound-File -Path $failedTerminal)
    corrected_launch_receipt = (Bound-File -Path $correctedLaunch)
    correction_sources = @(
        (Bound-File -Path (Join-Path $repository 'benchmark\runpod_eval\launch_operational_retry_workers.py'))
        (Bound-File -Path (Join-Path $repository 'benchmark\runpod_eval\plan_operational_retries.py'))
        (Bound-File -Path (Join-Path $repository 'tools\release\start_folynta_operational_retry_prefetch.ps1'))
    )
    corrected_worker_observations = $workerObservations
    collected_files = $files
    secret_free = $true
}
$encoded = $receipt | ConvertTo-Json -Compress -Depth 10
$hasher = [Security.Cryptography.SHA256]::Create()
try {
    $digest = $hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($encoded))
}
finally {
    $hasher.Dispose()
}
$receipt['receipt_sha256'] = 'sha256:' + (
    ($digest | ForEach-Object { $_.ToString('x2') }) -join ''
)
$receipt | ConvertTo-Json -Depth 10 |
    Set-Content -LiteralPath $receiptPath -Encoding utf8
$receipt | ConvertTo-Json -Compress -Depth 10
