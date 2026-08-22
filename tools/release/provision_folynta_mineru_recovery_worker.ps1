param(
    [Parameter(Mandatory = $true)] [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)] [string]$CredentialFile,
    [Parameter(Mandatory = $true)] [string]$DeadlineUtc,
    [int]$WorkerIndex = 7,
    [string]$Name = 'folynta-mineru344-operational-recovery-r2',
    [string]$StateSlug = 'mineru-operational-recovery-r2',
    [string]$ExistingPodId,
    # RunPod network volume to mount at /workspace. Without one a Pod's results
    # live on its host and are lost when the Pod is reclaimed or deleted.
    [string]$NetworkVolumeId,
    [int]$PollSeconds = 20
)

$ErrorActionPreference = 'Stop'
if ($WorkerIndex -lt 4 -or $WorkerIndex -gt 99) {
    throw 'WorkerIndex must be between 4 and 99'
}
if ($PollSeconds -lt 10 -or $PollSeconds -gt 120) {
    throw 'PollSeconds must be between 10 and 120'
}
if ($StateSlug -notmatch '^[a-z0-9][a-z0-9-]{2,63}$') {
    throw 'StateSlug is invalid'
}
$deadline = [DateTimeOffset]::Parse($DeadlineUtc).ToUniversalTime()
if ($deadline -le [DateTimeOffset]::UtcNow.AddHours(1)) {
    throw 'Recovery worker deadline must be at least one hour in the future'
}

$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$credential = [IO.Path]::GetFullPath($CredentialFile)
$privateRoot = Join-Path $repository 'benchmark\datasets\private\runpod-2026-08-04'
$stateRoot = Join-Path $privateRoot $StateSlug
$receiptPath = Join-Path $stateRoot 'provisioning-receipt.json'
$journalPath = Join-Path $stateRoot 'provisioning.jsonl'
$configPath = Join-Path $stateRoot 'workers.json'
$knownHosts = Join-Path $privateRoot 'known_hosts'
$key = Join-Path $privateRoot 'builder_ed25519'
$publicKeyPath = Join-Path $privateRoot 'builder_ed25519.pub'
$watchdogScript = Join-Path $repository 'tools\release\runpod_pod_watchdog.ps1'
$watchdogReceipt = Join-Path $stateRoot 'watchdog-receipt.json'
$null = New-Item -ItemType Directory -Path $stateRoot -Force

function Write-JournalEvent {
    param([string]$Event, [hashtable]$Fields = @{})
    $value = [ordered]@{
        event = $Event
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    foreach ($field in $Fields.Keys) { $value[$field] = $Fields[$field] }
    Add-Content -LiteralPath $journalPath `
        -Value ($value | ConvertTo-Json -Compress -Depth 10) -Encoding utf8
}

if (Test-Path -LiteralPath $receiptPath) {
    $existing = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
    if (
        $existing.status -ne 'ready_identity_bound_and_smoke_passed' -or
        [int]$existing.worker_index -ne $WorkerIndex
    ) {
        throw 'Existing recovery provisioning receipt is invalid'
    }
    Get-Content -Raw -LiteralPath $receiptPath
    exit 0
}

$line = Get-Content -LiteralPath $credential |
    Where-Object { $_ -match '^\s*Runpod\s*:' } |
    Select-Object -First 1
if (-not $line) { throw 'RunPod credential label not found' }
$apiKey = ($line -split ':', 2)[1].Trim()
if (-not $apiKey -or $apiKey -match '\s') { throw 'RunPod credential malformed' }
$headers = @{ Authorization = "Bearer $apiKey"; Accept = 'application/json' }
$publicKey = (Get-Content -Raw -LiteralPath $publicKeyPath).Trim()
if ($publicKey -notmatch '^ssh-(?:ed25519|rsa)\s+[A-Za-z0-9+/=]+(?:\s+.*)?$') {
    throw 'Recovery public key is malformed'
}

$resumedExistingPod = $false
if ($ExistingPodId) {
    if ($ExistingPodId -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$') {
        throw 'ExistingPodId is invalid'
    }
    $pod = Invoke-RestMethod -Method Get `
        -Uri "https://rest.runpod.io/v1/pods/$ExistingPodId" `
        -Headers $headers -TimeoutSec 30
    if ([string]$pod.id -ne $ExistingPodId) {
        throw 'Existing recovery Pod identity mismatch'
    }
    if ([string]$pod.desiredStatus -eq 'EXITED') {
        $null = Invoke-RestMethod -Method Post `
            -Uri "https://rest.runpod.io/v1/pods/$ExistingPodId/start" `
            -Headers $headers -TimeoutSec 60
        $resumedExistingPod = $true
        Write-JournalEvent -Event 'pod-resume-requested' -Fields @{ pod_id = $ExistingPodId }
    }
    elseif ([string]$pod.desiredStatus -ne 'RUNNING') {
        throw 'Existing recovery Pod is not resumable'
    }
    else {
        Write-JournalEvent -Event 'running-pod-adopted' -Fields @{ pod_id = $ExistingPodId }
    }
}
else {
    $providerResponse = Invoke-RestMethod -Method Get `
        -Uri 'https://rest.runpod.io/v1/pods' -Headers $headers -TimeoutSec 30
    # GET /v1/pods answers with a bare JSON array. Testing $response.pods on an
    # array triggers PowerShell member enumeration, which returns a truthy
    # projection of every element and silently selects the wrong branch, so the
    # name lookup finds nothing and a duplicate Pod gets created. Decide on the
    # response shape instead of on a member that enumeration can fabricate.
    $providerPods = if ($providerResponse -is [System.Array]) {
        @($providerResponse)
    }
    elseif ($null -ne $providerResponse.pods) {
        @($providerResponse.pods)
    }
    else {
        @($providerResponse)
    }
    $matches = @($providerPods | Where-Object { [string]$_.name -eq $Name })
    if ($matches.Count -gt 1) { throw 'Recovery Pod name is ambiguous at the provider' }
    if ($matches.Count -eq 1) {
        $pod = $matches[0]
        Write-JournalEvent -Event 'pod-adopted' -Fields @{ pod_id = [string]$pod.id }
    }
    else {
        $startCommand = @'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends openssh-server git ca-certificates curl jq
rm -rf /var/lib/apt/lists/*
install -d -m 0700 /root/.ssh
printf '%s\n' "$PUBLIC_KEY" > /root/.ssh/authorized_keys
chmod 0600 /root/.ssh/authorized_keys
install -d -m 0755 /run/sshd /workspace/folynta
exec /usr/sbin/sshd -D -e
'@
        # A machine-local volume ties the Pod's results to one physical host.
        # RunPod documents that a stopped Pod cannot restart once another tenant
        # takes its GPU, and that a network volume "decouples your data from a
        # specific physical machine" so a replacement Pod can attach the same
        # storage anywhere. Passing -NetworkVolumeId turns a lost worker into a
        # reattach instead of a total loss of its output.
        $payload = [ordered]@{
            name = $Name
            imageName = 'runpod/pytorch@sha256:263d4144a3053f5125b04174e279d73b43768c5b798cd76c4871af7b737f0c84'
            cloudType = 'SECURE'
            computeType = 'GPU'
            gpuTypeIds = @('NVIDIA GeForce RTX 5090', 'NVIDIA GeForce RTX 4090')
            gpuTypePriority = 'availability'
            gpuCount = 1
            containerDiskInGb = 100
            volumeMountPath = '/workspace'
            ports = @('22/tcp')
            supportPublicIp = $true
            interruptible = $false
            dockerEntrypoint = @('/bin/bash', '-lc')
            dockerStartCmd = @($startCommand)
            env = [ordered]@{
                PUBLIC_KEY = $publicKey
                FOLYNTA_QUALIFICATION_ONLY = '1'
                MINERU_API_MAX_CONCURRENT_REQUESTS = '1'
            }
        }
        if ($NetworkVolumeId) {
            $payload['networkVolumeId'] = $NetworkVolumeId
            Write-JournalEvent -Event 'network-volume-requested' -Fields @{
                network_volume_id = $NetworkVolumeId
            }
        }
        else {
            # Machine-local fallback keeps the historical behaviour, but then the
            # Pod's /workspace dies with the Pod.
            $payload['volumeInGb'] = 20
            Write-JournalEvent -Event 'machine-local-volume-used' -Fields @{
                risk = 'workspace results are lost if the Pod is reclaimed or deleted'
            }
        }
        $pod = $null
        for ($attempt = 1; $attempt -le 6; $attempt++) {
            try {
                $pod = Invoke-RestMethod -Method Post `
                    -Uri 'https://rest.runpod.io/v1/pods' -Headers $headers `
                    -ContentType 'application/json' `
                    -Body ($payload | ConvertTo-Json -Compress -Depth 10) -TimeoutSec 60
                break
            }
            catch {
                $statusCode = $null
                if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
                    $statusCode = [int]$_.Exception.Response.StatusCode.value__
                }
                $retryable = $statusCode -in @(429, 500, 502, 503, 504)
                if (-not $retryable -or $attempt -eq 6) { throw }
                $delaySeconds = [Math]::Min(60, 10 * $attempt)
                Write-JournalEvent -Event 'pod-create-retry' -Fields @{
                    attempt = $attempt
                    status_code = $statusCode
                    delay_seconds = $delaySeconds
                }
                Start-Sleep -Seconds $delaySeconds
            }
        }
        if ($null -eq $pod) { throw 'RunPod recovery Pod creation exhausted retries' }
        Write-JournalEvent -Event 'pod-created' -Fields @{ pod_id = [string]$pod.id }
    }
}
$podId = [string]$pod.id
if ($podId -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$') {
    throw 'RunPod did not return a valid recovery Pod id'
}

$priorWatchdog = Get-Content -LiteralPath $journalPath -ErrorAction SilentlyContinue |
    ForEach-Object { $_ | ConvertFrom-Json } |
    Where-Object { $_.event -eq 'watchdog-started' -and $_.pod_id -eq $podId } |
    Select-Object -Last 1
if (-not $priorWatchdog -or -not (
    Get-Process -Id ([int]$priorWatchdog.watchdog_pid) -ErrorAction SilentlyContinue
)) {
    # Hand the watchdog an SSH identity so it can look up the Pod's current
    # address at the deadline and ask whether work is running. Without this it
    # has no probe at all, every deadline reads as idle, and a Pod mid-inference
    # is deleted rather than stopped.
    $arguments = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $watchdogScript,
        '-PodId', $podId, '-CredentialFile', $credential,
        '-DeadlineUtc', $deadline.ToString('o'), '-ReceiptOut', $watchdogReceipt,
        '-SshKey', $key, '-KnownHosts', $knownHosts
    )
    $watchdog = Start-Process -FilePath 'powershell.exe' `
        -ArgumentList $arguments -WindowStyle Hidden -PassThru
    Write-JournalEvent -Event 'watchdog-started' -Fields @{
        pod_id = $podId
        watchdog_pid = $watchdog.Id
    }
}

$ready = $null
# Readiness has two independent phases and they fail for different reasons.
#
#   placement  - the provider assigns a public IP. This happens within a minute
#                on a host that can offer one. When GPU stock is Low the Pod is
#                still created and reports RUNNING, but no IP is ever assigned;
#                waiting longer never helps, so fail fast and let the caller
#                retry on a different host.
#   image pull - the SSH port appears once the pinned pytorch image is on the
#                host. A cold pull legitimately takes many minutes.
#
# Collapsing both into one long timeout burned twenty-five minutes of billing
# per placement failure and hid which of the two had actually gone wrong.
$placementMinutes = 5
$readinessMinutes = 25
$placementDeadline = [DateTimeOffset]::UtcNow.AddMinutes($placementMinutes)
$readinessDeadline = [DateTimeOffset]::UtcNow.AddMinutes($readinessMinutes)
if ($readinessDeadline -gt $deadline) { $readinessDeadline = $deadline }
if ($placementDeadline -gt $readinessDeadline) { $placementDeadline = $readinessDeadline }
$lastObserved = $null
$placed = $false
while ([DateTimeOffset]::UtcNow -lt $readinessDeadline) {
    $current = Invoke-RestMethod -Method Get `
        -Uri "https://rest.runpod.io/v1/pods/$podId" -Headers $headers -TimeoutSec 30
    $lastObserved = $current
    if ([string]$current.publicIp) { $placed = $true }
    $port = $current.portMappings.'22'
    if (
        [string]$current.desiredStatus -eq 'RUNNING' -and
        [string]$current.publicIp -and $null -ne $port
    ) {
        $ready = $current
        break
    }
    if (-not $placed -and [DateTimeOffset]::UtcNow -ge $placementDeadline) {
        Write-JournalEvent -Event 'pod-placement-timeout' -Fields @{
            pod_id = $podId
            timeout_minutes = $placementMinutes
            last_desired_status = [string]$current.desiredStatus
            classification = 'provider_assigned_no_public_ip'
        }
        break
    }
    Start-Sleep -Seconds $PollSeconds
}
if ($null -eq $ready) {
    Write-JournalEvent -Event 'pod-readiness-timeout' -Fields @{
        pod_id = $podId
        timeout_minutes = $readinessMinutes
        last_desired_status = [string]$lastObserved.desiredStatus
        last_public_ip_present = [bool][string]$lastObserved.publicIp
    }
    try {
        $null = Invoke-RestMethod -Method Delete `
            -Uri "https://rest.runpod.io/v1/pods/$podId" `
            -Headers $headers -TimeoutSec 30
    }
    catch {
        if ($_.Exception.Response.StatusCode.value__ -ne 404) { throw }
    }
    Write-JournalEvent -Event 'unready-pod-delete-requested' -Fields @{
        pod_id = $podId
    }
    throw "Recovery Pod did not become SSH-ready within $readinessMinutes minutes"
}
$hostName = [string]$ready.publicIp
$port = [int]$ready.portMappings.'22'
$rate = [double]$ready.costPerHr
if ($rate -le 0 -or $rate -gt 1.05) { throw 'Recovery Pod hourly rate is invalid' }

$savedPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& ssh-keygen -f $knownHosts -R "[$hostName]:$port" 2>$null | Out-Null
$ErrorActionPreference = $savedPreference
$scan = $null
for ($attempt = 1; $attempt -le 18; $attempt++) {
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $scan = & wsl.exe -e ssh-keyscan -T 10 -p $port $hostName 2>$null
    $scanExit = $LASTEXITCODE
    $ErrorActionPreference = $oldPreference
    if ($scanExit -eq 0 -and @($scan).Count) { break }
    Start-Sleep -Seconds 5
}
if (-not @($scan).Count) { throw 'Recovery Pod SSH host-key scan failed' }
foreach ($hostLine in @($scan | Where-Object { $_ -and -not $_.StartsWith('#') })) {
    if (-not (Select-String -LiteralPath $knownHosts -SimpleMatch $hostLine -Quiet)) {
        Add-Content -LiteralPath $knownHosts -Value $hostLine -Encoding ascii
    }
}

# ConnectTimeout only bounds the handshake. A Pod whose TCP session is dropped
# mid-command — routine behind the provider proxy — leaves ssh blocked forever,
# which stalled a bootstrap poll for five and a half hours while three GPUs kept
# billing. Keepalives make a dead session fail in about a minute so the caller
# can retry.
$SshKeepAlive = @(
    '-o', 'ServerAliveInterval=15',
    '-o', 'ServerAliveCountMax=4'
)

function Invoke-RecoverySsh {
    param([string]$Command)
    $output = & ssh -i $key -o BatchMode=yes -o ConnectTimeout=20 @SshKeepAlive `
        -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$knownHosts" `
        -p $port "root@$hostName" $Command
    if ($LASTEXITCODE -ne 0) { throw 'Recovery Pod SSH command failed' }
    return $output
}
function Copy-ToRecovery {
    param([string]$Source, [string]$Destination)
    & scp -i $key -o BatchMode=yes -o ConnectTimeout=20 @SshKeepAlive `
        -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$knownHosts" `
        -P $port $Source "root@${hostName}:$Destination"
    if ($LASTEXITCODE -ne 0) { throw "Recovery Pod upload failed: $Source" }
}

$bootstrap = Join-Path $repository 'infra\runpod\v6\bootstrap\mineru-3.4.4-transformers-c1.sh'
$artifactManifest = Join-Path $repository 'benchmark\runpod_eval\artifact_manifest.py'
$mineruRunner = Join-Path $repository 'benchmark\runpod_eval\mineru_stage2.py'
$inputContract = Join-Path $repository 'benchmark\runpod_eval\input_contract.py'
$retryRunner = Join-Path $repository 'benchmark\runpod_eval\remote_run_operational_retry.sh'
$stallWatchdog = Join-Path $repository 'benchmark\runpod_eval\remote_stall_watchdog.sh'
$smokeInput = Get-ChildItem -LiteralPath (Join-Path $privateRoot 'qualification-smoke') `
    -File | Select-Object -First 1
if (-not $smokeInput) { throw 'Qualification smoke input is missing' }
$null = Invoke-RecoverySsh `
    'mkdir -p /workspace/folynta/runner /workspace/folynta/qualification-smoke'
Copy-ToRecovery $bootstrap '/workspace/folynta/runner/bootstrap-mineru-3.4.4.sh'
Copy-ToRecovery $artifactManifest '/workspace/folynta/runner/artifact_manifest.py'
Copy-ToRecovery $mineruRunner '/workspace/folynta/runner/mineru_stage2.py'
Copy-ToRecovery $inputContract '/workspace/folynta/runner/input_contract.py'
Copy-ToRecovery $retryRunner '/workspace/folynta/runner/remote_run_operational_retry.sh'
Copy-ToRecovery $stallWatchdog '/workspace/folynta/runner/remote_stall_watchdog.sh'
Copy-ToRecovery $smokeInput.FullName '/workspace/folynta/qualification-smoke/input.png'

# BOOTSTRAP_COMPLETE lives on the persistent /workspace volume, but the packages
# it attests to are installed on the container disk, which RunPod resets on every
# stop/start. On a resumed Pod the receipt survives while mineru, torch and
# transformers do not, so the receipt is only trusted together with a live probe
# of the ephemeral runtime.
$runtimeProbe = @'
folynta_runtime_present() {
  test -x /usr/local/bin/mineru &&
    /usr/bin/python3.11 -c 'import mineru, torch, transformers' >/dev/null 2>&1
}
'@
$launchBootstrap = @"
set -euo pipefail
chmod 700 /workspace/folynta/runner/*.sh
$runtimeProbe
if test -f /workspace/folynta/receipts/BOOTSTRAP_COMPLETE && folynta_runtime_present; then
  echo already-complete
elif test -f /workspace/folynta/receipts/bootstrap.pid && kill -0 "`$(cat /workspace/folynta/receipts/bootstrap.pid)" 2>/dev/null; then
  echo already-running
else
  mkdir -p /workspace/folynta/receipts
  rm -f /workspace/folynta/receipts/BOOTSTRAP_COMPLETE /workspace/folynta/receipts/SMOKE_COMPLETE
  nohup env PYTHON_BIN=/usr/bin/python3.11 bash /workspace/folynta/runner/bootstrap-mineru-3.4.4.sh \
    >/workspace/folynta/receipts/bootstrap.stdout.log \
    2>/workspace/folynta/receipts/bootstrap.stderr.log </dev/null &
  printf '%s\n' "`$!" >/workspace/folynta/receipts/bootstrap.pid
  echo launched
fi
"@
$null = Invoke-RecoverySsh $launchBootstrap
while ([DateTimeOffset]::UtcNow -lt $deadline) {
    $state = [string](@(Invoke-RecoverySsh @"
$runtimeProbe
if test -f /workspace/folynta/receipts/BOOTSTRAP_COMPLETE && folynta_runtime_present; then
  echo complete
elif test -f /workspace/folynta/receipts/bootstrap.pid && kill -0 "`$(cat /workspace/folynta/receipts/bootstrap.pid)" 2>/dev/null; then
  echo running
else
  echo failed
fi
"@)[-1]).Trim()
    Write-JournalEvent -Event 'bootstrap-poll' -Fields @{ pod_id = $podId; state = $state }
    if ($state -eq 'complete') { break }
    if ($state -eq 'failed') { throw 'Recovery MinerU bootstrap failed' }
    Start-Sleep -Seconds $PollSeconds
}
if ($state -ne 'complete') { throw 'Recovery MinerU bootstrap exceeded deadline' }

$identity = 'opendatalab/MinerU2.5-Pro-2605-1.2B@bff20d4ae2bf202df9f45284b4d43681555a97ed'
$validate = @"
set -euo pipefail
/usr/bin/python3.11 /workspace/folynta/runner/artifact_manifest.py \
  --root /workspace/folynta/models/MinerU2.5-Pro-2605-1.2B \
  --output /workspace/folynta/receipts/model-artifact-primary.json \
  --identity '$identity' --exclude-prefix .cache >/dev/null
/usr/bin/python3.11 - <<'PY'
import json
from pathlib import Path
value = json.loads(Path('/workspace/folynta/receipts/runtime-identity.json').read_text())
assert value['packages'] == {
    'accelerate': '1.14.0', 'mineru': '3.4.4', 'mineru-vl-utils': '1.0.5',
    'torch': '2.8.0+cu128', 'torchvision': '0.23.0+cu128',
    'transformers': '4.57.3',
}
assert value['mineru_revision'] == '79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7'
assert value['model_revision'] == 'bff20d4ae2bf202df9f45284b4d43681555a97ed'
assert value['gpu'].startswith(('NVIDIA GeForce RTX 4090,', 'NVIDIA GeForce RTX 5090,'))
PY
if ! test -f /workspace/folynta/receipts/SMOKE_COMPLETE; then
  rm -rf /workspace/folynta/qualification-smoke/output
  env MINERU_MODEL_SOURCE=local MINERU_TOOLS_CONFIG_JSON=/root/mineru.json \
    timeout 900 /usr/local/bin/mineru \
    -p /workspace/folynta/qualification-smoke/input.png \
    -o /workspace/folynta/qualification-smoke/output -b vlm-engine -m ocr \
    >/workspace/folynta/receipts/smoke.stdout.log \
    2>/workspace/folynta/receipts/smoke.stderr.log
  find /workspace/folynta/qualification-smoke/output -type f -name '*.md' -size +0c | grep -q .
  touch /workspace/folynta/receipts/SMOKE_COMPLETE
fi
printf '%s\n' "`$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"
printf '%s\n' "`$(sha256sum /workspace/folynta/receipts/runtime-identity.json | head -c 64)"
printf '%s\n' "`$(sha256sum /workspace/folynta/receipts/model-artifact-primary.json | head -c 64)"
"@
$evidence = @(Invoke-RecoverySsh $validate | ForEach-Object { [string]$_ })
if ($evidence.Count -lt 3) { throw 'Recovery runtime evidence shape is invalid' }
$gpu = $evidence[-3].Trim()
$runtimeSha = $evidence[-2].Trim()
$modelSha = $evidence[-1].Trim()
if ($modelSha -ne '1611a8892cc0e7e287d31c4a1b5af87652f0f6e4a3f80276b92b4c71f982de84') {
    throw 'Recovery model artifact differs from the frozen MinerU baseline'
}

$baseConfig = Get-Content -Raw -LiteralPath (Join-Path $privateRoot 'public-core-workers.json') |
    ConvertFrom-Json
$workers = @($baseConfig.workers | ForEach-Object {
    [ordered]@{
        worker_index = [int]$_.worker_index
        host = [string]$_.host
        port = [int]$_.port
    }
})
$workers += [ordered]@{ worker_index = $WorkerIndex; host = $hostName; port = $port }
$config = [ordered]@{
    workers = $workers
    key = 'benchmark/datasets/private/runpod-2026-08-04/builder_ed25519'
    known_hosts = 'benchmark/datasets/private/runpod-2026-08-04/known_hosts'
}
$config | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $configPath -Encoding utf8

$receipt = [ordered]@{
    schema = 'folynta.mineru-operational-recovery-worker.v1'
    status = 'ready_identity_bound_and_smoke_passed'
    worker_index = $WorkerIndex
    pod_id = $podId
    name = [string]$ready.name
    host = $hostName
    port = $port
    gpu = $gpu
    hourly_rate_usd = $rate
    image = [string]$ready.imageName
    runtime_identity_sha256 = "sha256:$runtimeSha"
    model_identity = $identity
    model_artifact_manifest_sha256 = "sha256:$modelSha"
    config = $configPath
    watchdog_receipt = $watchdogReceipt
    resumed_existing_pod = $resumedExistingPod
    deadline_utc = $deadline.ToString('o')
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$receipt | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $receiptPath -Encoding utf8
Write-JournalEvent -Event 'provisioning-complete' -Fields @{
    pod_id = $podId
    gpu = $gpu
    model_artifact_manifest_sha256 = "sha256:$modelSha"
}
$receipt | ConvertTo-Json -Compress -Depth 10
