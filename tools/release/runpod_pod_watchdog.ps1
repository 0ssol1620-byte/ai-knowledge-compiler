param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$')]
    [string]$PodId,

    [Parameter(Mandatory = $true)]
    [string]$CredentialFile,

    [Parameter(Mandatory = $true)]
    [string]$DeadlineUtc,

    [Parameter(Mandatory = $true)]
    [string]$ReceiptOut,

    # Optional shell command that prints at least one line when the Pod is still
    # doing work. When it reports busy at the deadline the Pod is stopped rather
    # than deleted, so results on the persistent volume survive.
    [string]$LivenessProbeCommand,

    # Preferred over the command above. Given an SSH identity, the watchdog asks
    # the provider for the Pod's *current* address at the deadline and probes
    # that, instead of trusting an address captured when the Pod was created.
    # A Pod that is stopped and restarted comes back on a different port, so a
    # baked-in address stops resolving while the Pod itself is busy -- and a
    # caller that supplies no probe at all leaves the protection switched off
    # entirely, which is how four working Pods were deleted mid-run.
    [string]$SshKey,
    [string]$KnownHosts,
    [string]$RemoteBusyCommand = "ps -eo cmd | grep -c '[m]ineru' | grep -v '^0$'"
)

$ErrorActionPreference = 'Stop'
$deadline = [DateTimeOffset]::Parse($DeadlineUtc).ToUniversalTime()
if ($deadline -le [DateTimeOffset]::UtcNow) {
    throw 'Watchdog deadline must be in the future'
}

$credentialPath = [IO.Path]::GetFullPath($CredentialFile)
$receiptPath = [IO.Path]::GetFullPath($ReceiptOut)
$privateRoot = [IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot '..\..\benchmark\datasets\private')
)
if (-not $receiptPath.StartsWith(
        $privateRoot + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw 'Watchdog receipt must stay under benchmark/datasets/private'
}

$line = Get-Content -LiteralPath $credentialPath |
    Where-Object { $_ -match '^\s*Runpod\s*:' } |
    Select-Object -First 1
if (-not $line) {
    throw 'Runpod credential label not found'
}
$apiKey = ($line -split ':', 2)[1].Trim()
if (-not $apiKey -or $apiKey -match '\s') {
    throw 'Runpod credential malformed'
}
$headers = @{
    Authorization = "Bearer $apiKey"
    Accept = 'application/json'
}
$uri = "https://rest.runpod.io/v1/pods/$PodId"

function Test-PodAbsent {
    try {
        $null = Invoke-RestMethod -Method Get -Uri $uri -Headers $headers -TimeoutSec 30
        return $false
    }
    catch {
        $status = $_.Exception.Response.StatusCode.value__
        if ($status -eq 404) {
            return $true
        }
        return $false
    }
}

while ([DateTimeOffset]::UtcNow -lt $deadline) {
    if (Test-PodAbsent) {
        $receipt = @{
            schema = 'folynta.runpod-builder-watchdog.v1'
            pod_id = $PodId
            terminal_state = 'already_absent'
            deadline_utc = $deadline.ToString('o')
            observed_at = [DateTimeOffset]::UtcNow.ToString('o')
        }
        $directory = Split-Path -Parent $receiptPath
        $null = New-Item -ItemType Directory -Path $directory -Force
        $receipt | ConvertTo-Json | Set-Content -LiteralPath $receiptPath -Encoding utf8
        exit 0
    }
    Start-Sleep -Seconds 60
}

# The watchdog is a cost backstop for a Pod that is building or idling, not a
# scheduler. Deleting a Pod that is mid-inference destroys work that cannot be
# recovered: a four-hour deadline once fired across a seven-hour audit and took
# two suites with it. Stop an actively working Pod instead, which ends the GPU
# charge while leaving the /workspace volume and its results intact, and only
# delete a Pod that has nothing running on it.
# The probe has three outcomes, not two. It can report work, it can report none,
# or it can fail to answer at all -- and the third is not the second. A Pod that
# is restarted gets new ports, so a probe still holding the address from
# provisioning time cannot connect, and reading that silence as "idle" deletes a
# Pod in the middle of its run. That is exactly how a quality retry was lost at
# 117 of 372 documents with all four workers busy. An unanswered probe is
# unknown, and unknown stops rather than deletes.
$busyState = 'idle'
if ($SshKey -and $KnownHosts) {
    # Resolve the address now rather than trusting one from provisioning time.
    $current = $null
    try { $current = Invoke-RestMethod -Method Get -Uri $uri -Headers $headers -TimeoutSec 30 }
    catch { $current = $null }
    $host4 = $current.publicIp
    $port4 = $null
    if ($current -and $current.portMappings) { $port4 = $current.portMappings.'22' }
    if (-not $host4 -or -not $port4) {
        # The provider cannot tell us where the Pod is. That is not evidence
        # that the Pod is idle.
        $busyState = 'unknown'
    }
    else {
        $probeOutput = & ssh.exe -n -i $SshKey `
            -o BatchMode=yes -o ConnectTimeout=15 `
            -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$KnownHosts" `
            -p $port4 "root@$host4" $RemoteBusyCommand 2>$null
        if ($LASTEXITCODE -eq 255) { $busyState = 'unknown' }
        elseif (@($probeOutput).Count -gt 0) { $busyState = 'busy' }
    }
}
elseif ($LivenessProbeCommand) {
    $probeOutput = & cmd.exe /c $LivenessProbeCommand 2>$null
    if ($LASTEXITCODE -ne 0) {
        $busyState = 'unknown'
    }
    elseif (@($probeOutput).Count -gt 0) {
        $busyState = 'busy'
    }
}
if ($busyState -ne 'idle') {
    try {
        $null = Invoke-RestMethod -Method Post -Uri "$uri/stop" `
            -Headers $headers -TimeoutSec 30
    }
    catch {
        if (-not (Test-PodAbsent)) { throw 'Watchdog could not stop the busy Pod' }
    }
    $receipt = @{
        schema = 'folynta.runpod-builder-watchdog.v1'
        pod_id = $PodId
        terminal_state = if ($busyState -eq 'busy') {
            'stopped_at_deadline_while_busy'
        } else {
            'stopped_at_deadline_liveness_unknown'
        }
        deadline_utc = $deadline.ToString('o')
        observed_at = [DateTimeOffset]::UtcNow.ToString('o')
        liveness_state = $busyState
        note = if ($busyState -eq 'busy') {
            'Pod was running work at the deadline; stopped instead of deleted so results survive.'
        } else {
            'Liveness could not be determined at the deadline; stopped instead of deleted because an unanswered probe is not proof of an idle Pod.'
        }
    }
    $directory = Split-Path -Parent $receiptPath
    $null = New-Item -ItemType Directory -Path $directory -Force
    $receipt | ConvertTo-Json | Set-Content -LiteralPath $receiptPath -Encoding utf8
    exit 0
}

try {
    $null = Invoke-RestMethod -Method Delete -Uri $uri -Headers $headers -TimeoutSec 30
}
catch {
    if (-not (Test-PodAbsent)) {
        throw 'Watchdog could not terminate the builder Pod'
    }
}

$absent = $false
for ($attempt = 0; $attempt -lt 10; $attempt++) {
    if (Test-PodAbsent) {
        $absent = $true
        break
    }
    Start-Sleep -Seconds 15
}
if (-not $absent) {
    throw 'Watchdog termination was not followed by provider absence'
}

$receipt = @{
    schema = 'folynta.runpod-builder-watchdog.v1'
    pod_id = $PodId
    terminal_state = 'deleted_at_deadline'
    deadline_utc = $deadline.ToString('o')
    observed_at = [DateTimeOffset]::UtcNow.ToString('o')
}
$directory = Split-Path -Parent $receiptPath
$null = New-Item -ItemType Directory -Path $directory -Force
$receipt | ConvertTo-Json | Set-Content -LiteralPath $receiptPath -Encoding utf8
