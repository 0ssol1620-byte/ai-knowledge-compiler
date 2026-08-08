param(
    [Parameter(Mandatory = $true)] [string]$RepositoryRoot,
    [int]$PollSeconds = 30
)

$ErrorActionPreference = 'Stop'
if ($PollSeconds -lt 15 -or $PollSeconds -gt 120) {
    throw 'PollSeconds must be between 15 and 120'
}
$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$privateRoot = Join-Path $repository 'benchmark\datasets\private\runpod-2026-08-04'
$expansionRoot = Join-Path $privateRoot 'mineru-retry-expansion'
$provisioningPath = Join-Path $expansionRoot 'provisioning-receipt.json'
$receiptPath = Join-Path $expansionRoot 'bootstrap-receipt.json'
$progressPath = Join-Path $expansionRoot 'bootstrap.jsonl'
$key = Join-Path $privateRoot 'builder_ed25519'
$knownHosts = Join-Path $privateRoot 'known_hosts'
$bootstrap = Join-Path `
    $repository `
    'infra\runpod\v6\bootstrap\mineru-3.4.4-transformers-c1.sh'
$artifactManifest = Join-Path $repository 'benchmark\runpod_eval\artifact_manifest.py'
$mineruRunner = Join-Path $repository 'benchmark\runpod_eval\mineru_stage2.py'
$retryRunner = Join-Path `
    $repository `
    'benchmark\runpod_eval\remote_run_operational_retry.sh'
$stallWatchdog = Join-Path `
    $repository `
    'benchmark\runpod_eval\remote_stall_watchdog.sh'
$smokeInput = Get-ChildItem `
    -LiteralPath (Join-Path $privateRoot 'qualification-smoke') `
    -File |
    Select-Object -First 1
if (-not $smokeInput) { throw 'Qualification smoke input is missing' }
if (Test-Path -LiteralPath $receiptPath) {
    Get-Content -Raw -LiteralPath $receiptPath
    exit 0
}
$provisioning = Get-Content -Raw -LiteralPath $provisioningPath | ConvertFrom-Json
if (
    $provisioning.status -ne 'provisioned_ssh_ready' -or
    [int]$provisioning.worker_count -ne 3
) {
    throw 'Expansion provisioning receipt is invalid'
}

function Write-BootstrapEvent {
    param([string]$Event, [hashtable]$Fields = @{})
    $value = [ordered]@{
        event = $Event
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    foreach ($name in $Fields.Keys) { $value[$name] = $Fields[$name] }
    Add-Content `
        -LiteralPath $progressPath `
        -Value ($value | ConvertTo-Json -Compress -Depth 8) `
        -Encoding utf8
}

function Invoke-WorkerSsh {
    param([object]$Worker, [string]$Command)
    $output = & ssh `
        -i $key `
        -o BatchMode=yes `
        -o ConnectTimeout=20 `
        -o StrictHostKeyChecking=yes `
        -o "UserKnownHostsFile=$knownHosts" `
        -p ([int]$Worker.ssh_port) `
        "root@$($Worker.public_ip)" `
        $Command
    if ($LASTEXITCODE -ne 0) {
        throw "SSH command failed for expansion worker $($Worker.worker_index)"
    }
    return $output
}

function Copy-ToWorker {
    param([object]$Worker, [string]$Source, [string]$Destination)
    & scp `
        -i $key `
        -o BatchMode=yes `
        -o ConnectTimeout=20 `
        -o StrictHostKeyChecking=yes `
        -o "UserKnownHostsFile=$knownHosts" `
        -P ([int]$Worker.ssh_port) `
        $Source `
        "root@$($Worker.public_ip):$Destination"
    if ($LASTEXITCODE -ne 0) {
        throw "SCP upload failed for expansion worker $($Worker.worker_index)"
    }
}

$workers = @($provisioning.workers | Sort-Object { [int]$_.worker_index })
foreach ($worker in $workers) {
    $null = Invoke-WorkerSsh `
        -Worker $worker `
        -Command 'mkdir -p /workspace/folynta/runner /workspace/folynta/qualification-smoke'
    Copy-ToWorker $worker $bootstrap '/workspace/folynta/runner/bootstrap-mineru-3.4.4.sh'
    Copy-ToWorker $worker $artifactManifest '/workspace/folynta/runner/artifact_manifest.py'
    Copy-ToWorker $worker $mineruRunner '/workspace/folynta/runner/mineru_stage2.py'
    Copy-ToWorker $worker $retryRunner '/workspace/folynta/runner/remote_run_operational_retry.sh'
    Copy-ToWorker $worker $stallWatchdog '/workspace/folynta/runner/remote_stall_watchdog.sh'
    Copy-ToWorker $worker $smokeInput.FullName '/workspace/folynta/qualification-smoke/input.png'
    $launch = @'
set -euo pipefail
chmod 700 /workspace/folynta/runner/*.sh
if test -f /workspace/folynta/receipts/BOOTSTRAP_COMPLETE; then
  printf '%s\n' already-complete
  exit 0
fi
if test -f /workspace/folynta/receipts/bootstrap.pid && \
   kill -0 "$(cat /workspace/folynta/receipts/bootstrap.pid)" 2>/dev/null; then
  printf '%s\n' already-running
  exit 0
fi
mkdir -p /workspace/folynta/receipts
nohup env PYTHON_BIN=/usr/bin/python3.11 \
  bash /workspace/folynta/runner/bootstrap-mineru-3.4.4.sh \
  >/workspace/folynta/receipts/bootstrap.stdout.log \
  2>/workspace/folynta/receipts/bootstrap.stderr.log </dev/null &
printf '%s\n' "$!" | tee /workspace/folynta/receipts/bootstrap.pid
'@
    $launchState = Invoke-WorkerSsh -Worker $worker -Command $launch
    Write-BootstrapEvent -Event 'bootstrap-launched' -Fields @{
        worker_index = [int]$worker.worker_index
        pod_id = [string]$worker.pod_id
        launch_state = [string](@($launchState)[-1])
    }
}

$bootstrapDeadline = [DateTimeOffset]::UtcNow.AddMinutes(30)
$bootstrapComplete = @{}
while ($bootstrapComplete.Count -lt $workers.Count) {
    if ([DateTimeOffset]::UtcNow -ge $bootstrapDeadline) {
        throw 'MinerU retry expansion bootstrap exceeded 30 minutes'
    }
    foreach ($worker in $workers) {
        $index = [int]$worker.worker_index
        if ($bootstrapComplete.ContainsKey($index)) { continue }
        $state = Invoke-WorkerSsh -Worker $worker -Command @'
if test -f /workspace/folynta/receipts/BOOTSTRAP_COMPLETE; then
  printf '%s\n' complete
elif test -f /workspace/folynta/receipts/bootstrap.pid && \
     kill -0 "$(cat /workspace/folynta/receipts/bootstrap.pid)" 2>/dev/null; then
  printf '%s\n' running
else
  printf '%s\n' failed
fi
'@
        $value = [string](@($state)[-1]).Trim()
        Write-BootstrapEvent -Event 'bootstrap-poll' -Fields @{
            worker_index = $index
            state = $value
        }
        if ($value -eq 'complete') {
            $bootstrapComplete[$index] = $true
        }
        elseif ($value -eq 'failed') {
            throw "MinerU bootstrap process failed for expansion worker $index"
        }
    }
    if ($bootstrapComplete.Count -lt $workers.Count) {
        Start-Sleep -Seconds $PollSeconds
    }
}

$identity = 'opendatalab/MinerU2.5-Pro-2605-1.2B@bff20d4ae2bf202df9f45284b4d43681555a97ed'
foreach ($worker in $workers) {
    $validateAndLaunchSmoke = @"
set -euo pipefail
/usr/bin/python3.11 /workspace/folynta/runner/artifact_manifest.py \
  --root /workspace/folynta/models/MinerU2.5-Pro-2605-1.2B \
  --output /workspace/folynta/receipts/model-artifact-primary.json \
  --identity '$identity' \
  --exclude-prefix .cache \
  >/workspace/folynta/receipts/model-artifact-primary.stdout.json
/usr/bin/python3.11 - <<'PY'
import json
from pathlib import Path
value = json.loads(Path('/workspace/folynta/receipts/runtime-identity.json').read_text())
assert value['packages'] == {
    'accelerate': '1.14.0',
    'mineru': '3.4.4',
    'mineru-vl-utils': '1.0.5',
    'torch': '2.8.0+cu128',
    'torchvision': '0.23.0+cu128',
    'transformers': '4.57.3',
}
assert value['mineru_revision'] == '79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7'
assert value['model_revision'] == 'bff20d4ae2bf202df9f45284b4d43681555a97ed'
assert value['gpu'].startswith('NVIDIA GeForce RTX 4090,')
PY
if test -f /workspace/folynta/receipts/SMOKE_COMPLETE; then
  printf '%s\n' already-complete
  exit 0
fi
rm -rf /workspace/folynta/qualification-smoke/output
nohup env MINERU_MODEL_SOURCE=local MINERU_TOOLS_CONFIG_JSON=/root/mineru.json \
  timeout 900 /usr/local/bin/mineru \
  -p /workspace/folynta/qualification-smoke/input.png \
  -o /workspace/folynta/qualification-smoke/output \
  -b vlm-engine -m ocr \
  >/workspace/folynta/receipts/smoke.stdout.log \
  2>/workspace/folynta/receipts/smoke.stderr.log </dev/null && \
  find /workspace/folynta/qualification-smoke/output -type f -name '*.md' -size +0c \
    | grep -q . && \
  touch /workspace/folynta/receipts/SMOKE_COMPLETE &
printf '%s\n' "`$!" | tee /workspace/folynta/receipts/smoke.pid
"@
    $smokeState = Invoke-WorkerSsh -Worker $worker -Command $validateAndLaunchSmoke
    Write-BootstrapEvent -Event 'identity-validated-smoke-launched' -Fields @{
        worker_index = [int]$worker.worker_index
        state = [string](@($smokeState)[-1])
    }
}

$smokeDeadline = [DateTimeOffset]::UtcNow.AddMinutes(20)
$smokeComplete = @{}
while ($smokeComplete.Count -lt $workers.Count) {
    if ([DateTimeOffset]::UtcNow -ge $smokeDeadline) {
        throw 'MinerU retry expansion smoke inference exceeded 20 minutes'
    }
    foreach ($worker in $workers) {
        $index = [int]$worker.worker_index
        if ($smokeComplete.ContainsKey($index)) { continue }
        $state = Invoke-WorkerSsh -Worker $worker -Command @'
if test -f /workspace/folynta/receipts/SMOKE_COMPLETE; then
  printf '%s\n' complete
elif test -f /workspace/folynta/receipts/smoke.pid && \
     kill -0 "$(cat /workspace/folynta/receipts/smoke.pid)" 2>/dev/null; then
  printf '%s\n' running
else
  printf '%s\n' failed
fi
'@
        $value = [string](@($state)[-1]).Trim()
        Write-BootstrapEvent -Event 'smoke-poll' -Fields @{
            worker_index = $index
            state = $value
        }
        if ($value -eq 'complete') {
            $smokeComplete[$index] = $true
        }
        elseif ($value -eq 'failed') {
            throw "MinerU smoke inference failed for expansion worker $index"
        }
    }
    if ($smokeComplete.Count -lt $workers.Count) {
        Start-Sleep -Seconds $PollSeconds
    }
}

$validated = @()
foreach ($worker in $workers) {
    $evidence = Invoke-WorkerSsh -Worker $worker -Command @'
set -euo pipefail
printf '%s\n' "$(sha256sum /workspace/folynta/receipts/runtime-identity.json | cut -d' ' -f1)"
printf '%s\n' "$(sha256sum /workspace/folynta/receipts/model-artifact-primary.json | cut -d' ' -f1)"
printf '%s\n' "$(find /workspace/folynta/qualification-smoke/output -type f -name '*.md' -size +0c | wc -l)"
'@
    $lines = @($evidence | ForEach-Object { [string]$_ })
    if ($lines.Count -ne 3 -or [int]$lines[2] -lt 1) {
        throw "Expansion evidence shape is invalid for worker $($worker.worker_index)"
    }
    $validated += [ordered]@{
        worker_index = [int]$worker.worker_index
        pod_id = [string]$worker.pod_id
        runtime_identity_sha256 = "sha256:$($lines[0])"
        model_artifact_manifest_sha256 = "sha256:$($lines[1])"
        nonempty_smoke_markdown_count = [int]$lines[2]
        mineru_version = '3.4.4'
        model_revision = 'bff20d4ae2bf202df9f45284b4d43681555a97ed'
    }
}
$modelHashes = @($validated.model_artifact_manifest_sha256 | Select-Object -Unique)
if ($modelHashes.Count -ne 1) {
    throw 'Expansion workers do not have byte-identical primary model artifacts'
}
$receipt = [ordered]@{
    schema = 'folynta.mineru-operational-retry-expansion-bootstrap.v1'
    status = 'ready_identity_bound_and_smoke_passed'
    worker_count = $validated.Count
    model_identity = $identity
    model_artifact_manifest_sha256 = $modelHashes[0]
    workers = $validated
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$receipt | ConvertTo-Json -Depth 10 |
    Set-Content -LiteralPath $receiptPath -Encoding utf8
Write-BootstrapEvent -Event 'bootstrap-validation-complete' -Fields @{
    worker_count = $validated.Count
    model_artifact_manifest_sha256 = $modelHashes[0]
}
$receipt | ConvertTo-Json -Compress -Depth 10
