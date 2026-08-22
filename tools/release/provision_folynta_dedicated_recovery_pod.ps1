param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('paddleocr-vl-1.6', 'deepseek-ocr-2')]
    [string]$Role,
    [Parameter(Mandatory = $true)] [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)] [string]$CredentialFile,
    [Parameter(Mandatory = $true)] [string]$DeadlineUtc,
    [Parameter(Mandatory = $true)] [string]$StateSlug,
    [Parameter(Mandatory = $true)] [string]$Name,
    [ValidateSet('NVIDIA GeForce RTX 4090', 'NVIDIA GeForce RTX 5090', 'NVIDIA A40')]
    [string]$GpuTypeId = 'NVIDIA GeForce RTX 4090',
    [int]$PollSeconds = 20
)

$ErrorActionPreference = 'Stop'
if ($StateSlug -notmatch '^[a-z0-9][a-z0-9-]{2,63}$') { throw 'StateSlug is invalid' }
if ($Name -notmatch '^[a-z0-9][a-z0-9-]{2,63}$') { throw 'Name is invalid' }
if ($PollSeconds -lt 10 -or $PollSeconds -gt 120) { throw 'PollSeconds is invalid' }
$deadline = [DateTimeOffset]::Parse($DeadlineUtc).ToUniversalTime()
if ($deadline -le [DateTimeOffset]::UtcNow.AddHours(1)) { throw 'Deadline must be at least one hour away' }
$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$credential = [IO.Path]::GetFullPath($CredentialFile)
$private = Join-Path $repository 'benchmark\datasets\private\runpod-2026-08-04'
$stateRoot = Join-Path $private $StateSlug
$receiptPath = Join-Path $stateRoot 'provisioning-receipt.json'
$journalPath = Join-Path $stateRoot 'provisioning.jsonl'
$modelSlug = if ($Role -eq 'paddleocr-vl-1.6') { 'paddle' } else { 'deepseek' }
$knownHosts = Join-Path $private "$modelSlug-recovery\known_hosts"
$publicKeyPath = Join-Path $private 'builder_ed25519.pub'
$null = New-Item -ItemType Directory -Path $stateRoot -Force
$null = New-Item -ItemType Directory -Path (Split-Path $knownHosts) -Force

function Write-Event {
    param([string]$Event, [hashtable]$Fields = @{})
    $payload = [ordered]@{ event = $Event; observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o') }
    foreach ($key in $Fields.Keys) { $payload[$key] = $Fields[$key] }
    Add-Content -LiteralPath $journalPath -Value ($payload | ConvertTo-Json -Compress -Depth 8) -Encoding utf8
}

function Remove-BoundedPod {
    param([string]$PodId, [string]$Reason)
    if ($PodId -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$') { return }
    Write-Event -Event 'pod-delete-requested' -Fields @{ pod_id = $PodId; reason = $Reason }
    try {
        Invoke-RestMethod -Method Delete -Uri "https://rest.runpod.io/v1/pods/$PodId" -Headers $headers -TimeoutSec 30 | Out-Null
    }
    catch {
        $statusCode = [int]$_.Exception.Response.StatusCode
        if ($statusCode -ne 404) {
            Write-Event -Event 'pod-delete-failed' -Fields @{ pod_id = $PodId; reason = $Reason; error = $_.Exception.Message }
            throw
        }
    }
    for ($attempt = 1; $attempt -le 12; $attempt++) {
        try {
            Invoke-RestMethod -Method Get -Uri "https://rest.runpod.io/v1/pods/$PodId" -Headers $headers -TimeoutSec 30 | Out-Null
        }
        catch {
            if ([int]$_.Exception.Response.StatusCode -eq 404) {
                Write-Event -Event 'pod-delete-verified' -Fields @{ pod_id = $PodId; reason = $Reason }
                return
            }
            throw
        }
        Start-Sleep -Seconds 5
    }
    Write-Event -Event 'pod-delete-unverified' -Fields @{ pod_id = $PodId; reason = $Reason }
    throw 'Dedicated recovery Pod deletion could not be verified'
}

if (Test-Path -LiteralPath $receiptPath) {
    Get-Content -Raw -LiteralPath $receiptPath
    exit 0
}
$line = Get-Content -LiteralPath $credential | Where-Object { $_ -match '^\s*Runpod\s*:' } | Select-Object -First 1
if (-not $line) { throw 'RunPod credential label not found' }
$apiKey = ($line -split ':', 2)[1].Trim()
if (-not $apiKey -or $apiKey -match '\s') { throw 'RunPod credential malformed' }
$headers = @{ Authorization = "Bearer $apiKey"; Accept = 'application/json' }
$publicKey = (Get-Content -Raw -LiteralPath $publicKeyPath).Trim()
if ($publicKey -notmatch '^ssh-(?:ed25519|rsa)\s+[A-Za-z0-9+/=]+(?:\s+.*)?$') { throw 'SSH public key is malformed' }

$provider = Invoke-RestMethod -Method Get -Uri 'https://rest.runpod.io/v1/pods' -Headers $headers -TimeoutSec 30
# GET /v1/pods answers with a bare JSON array; testing $provider.pods on an array
# triggers PowerShell member enumeration, which is truthy and selects the wrong
# branch, so the name lookup misses and a duplicate Pod gets created.
$pods = if ($provider -is [System.Array]) { @($provider) }
elseif ($null -ne $provider.pods) { @($provider.pods) }
else { @($provider) }
$matches = @($pods | Where-Object { [string]$_.name -eq $Name })
if ($matches.Count -gt 1) { throw 'Dedicated recovery Pod name is ambiguous' }
if ($matches.Count -eq 1) {
    $pod = $matches[0]
    Write-Event -Event 'pod-adopted' -Fields @{ pod_id = [string]$pod.id }
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
    $payload = [ordered]@{
        name = $Name
        imageName = 'runpod/pytorch@sha256:263d4144a3053f5125b04174e279d73b43768c5b798cd76c4871af7b737f0c84'
        cloudType = 'SECURE'; computeType = 'GPU'
        gpuTypeIds = @($GpuTypeId); gpuTypePriority = 'availability'; gpuCount = 1
        containerDiskInGb = 100; volumeInGb = 20; volumeMountPath = '/workspace'
        ports = @('22/tcp'); supportPublicIp = $true; interruptible = $false
        dockerEntrypoint = @('/bin/bash', '-lc'); dockerStartCmd = @($startCommand)
        env = [ordered]@{ PUBLIC_KEY = $publicKey; FOLYNTA_DEDICATED_RECOVERY = $Role }
    }
    $pod = $null
    for ($attempt = 1; $attempt -le 6; $attempt++) {
        try {
            $pod = Invoke-RestMethod -Method Post -Uri 'https://rest.runpod.io/v1/pods' -Headers $headers `
                -ContentType 'application/json' -Body ($payload | ConvertTo-Json -Compress -Depth 10) -TimeoutSec 60
            break
        }
        catch {
            $statusCode = if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
                [int]$_.Exception.Response.StatusCode
            } else { 0 }
            if ($statusCode -notin @(429, 500, 502, 503, 504) -or $attempt -eq 6) { throw }
            $delaySeconds = [Math]::Min(60, 10 * $attempt)
            Write-Event -Event 'pod-create-retry' -Fields @{
                requested_gpu = $GpuTypeId; attempt = $attempt
                status_code = $statusCode; delay_seconds = $delaySeconds
            }
            Start-Sleep -Seconds $delaySeconds
        }
    }
    if ($null -eq $pod) { throw 'Dedicated recovery Pod creation exhausted retries' }
    Write-Event -Event 'pod-created' -Fields @{ pod_id = [string]$pod.id; requested_gpu = $GpuTypeId }
}
$podId = [string]$pod.id
if ($podId -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$') { throw 'Provider omitted a valid Pod id' }
$ready = $null
$readinessDeadline = [DateTimeOffset]::UtcNow.AddMinutes(10)
if ($readinessDeadline -gt $deadline) { $readinessDeadline = $deadline }
while ([DateTimeOffset]::UtcNow -lt $readinessDeadline) {
    $current = Invoke-RestMethod -Method Get -Uri "https://rest.runpod.io/v1/pods/$podId" -Headers $headers -TimeoutSec 30
    if ([string]$current.desiredStatus -eq 'RUNNING' -and [string]$current.publicIp -and $null -ne $current.portMappings.'22') {
        $ready = $current; break
    }
    Start-Sleep -Seconds $PollSeconds
}
if ($null -eq $ready) {
    Remove-BoundedPod -PodId $podId -Reason 'ssh-readiness-timeout'
    throw 'Dedicated recovery Pod did not expose SSH before deadline and was deleted'
}
$hostName = [string]$ready.publicIp
$port = [int]$ready.portMappings.'22'
$rate = [double]$ready.costPerHr
if ($rate -le 0 -or $rate -gt 1.05) { throw 'Dedicated recovery Pod hourly rate is invalid' }
$savedPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
if (Test-Path -LiteralPath $knownHosts) { & ssh-keygen -f $knownHosts -R "[$hostName]:$port" 2>$null | Out-Null }
$ErrorActionPreference = $savedPreference
$scan = $null
for ($attempt = 1; $attempt -le 24; $attempt++) {
    $savedPreference = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    $scan = & wsl.exe -e ssh-keyscan -T 10 -p $port $hostName 2>$null
    $scanExit = $LASTEXITCODE; $ErrorActionPreference = $savedPreference
    if ($scanExit -eq 0 -and @($scan).Count) { break }
    Start-Sleep -Seconds 5
}
if (-not @($scan).Count) { throw 'Dedicated recovery SSH host-key scan failed' }
foreach ($hostLine in @($scan | Where-Object { $_ -and -not $_.StartsWith('#') })) {
    if (-not (Select-String -LiteralPath $knownHosts -SimpleMatch $hostLine -Quiet -ErrorAction SilentlyContinue)) {
        Add-Content -LiteralPath $knownHosts -Value $hostLine -Encoding ascii
    }
}
$receipt = [ordered]@{
    schema = 'folynta.dedicated-recovery-provisioning.v1'; status = 'running_ssh_exposed'
    role = $Role; pod_id = $podId; name = $Name; host = $hostName; port = $port
    gpu = if ($ready.gpu.type) { [string]$ready.gpu.type } else { $GpuTypeId }; cost_per_hour_usd = $rate
    image = 'runpod/pytorch@sha256:263d4144a3053f5125b04174e279d73b43768c5b798cd76c4871af7b737f0c84'
    created_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding utf8
Write-Event -Event 'pod-ssh-ready' -Fields @{ pod_id = $podId; host = $hostName; port = $port; hourly_rate_usd = $rate }
$receipt | ConvertTo-Json -Depth 8
