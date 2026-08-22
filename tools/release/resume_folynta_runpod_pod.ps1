param(
    [Parameter(Mandatory = $true)] [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)] [string]$CredentialFile,
    [Parameter(Mandatory = $true)] [string]$PodId,
    [Parameter(Mandatory = $true)] [string]$ExpectedName,
    [Parameter(Mandatory = $true)] [string]$ReceiptOut,
    [Parameter(Mandatory = $true)] [string]$DeadlineUtc,
    [int]$PollSeconds = 20
)

$ErrorActionPreference = 'Stop'
if ($PodId -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$') {
    throw 'PodId is invalid'
}
if ($ExpectedName -notmatch '^folynta-[a-z0-9-]{2,90}$') {
    throw 'ExpectedName is invalid'
}
if ($PollSeconds -lt 10 -or $PollSeconds -gt 120) {
    throw 'PollSeconds must be between 10 and 120'
}
$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$credential = [IO.Path]::GetFullPath($CredentialFile)
$receipt = [IO.Path]::GetFullPath($ReceiptOut)
$generated = [IO.Path]::GetFullPath(
    (Join-Path $repository 'benchmark\reports\generated')
)
if (-not $receipt.StartsWith(
        $generated + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw 'ReceiptOut must stay under benchmark/reports/generated'
}
$deadline = [DateTimeOffset]::Parse($DeadlineUtc).ToUniversalTime()
if ($deadline -le [DateTimeOffset]::UtcNow.AddMinutes(30)) {
    throw 'DeadlineUtc must be at least thirty minutes in the future'
}
if (Test-Path -LiteralPath $receipt) {
    $prior = Get-Content -Raw -LiteralPath $receipt | ConvertFrom-Json
    if (
        $prior.status -ne 'running_endpoint_ready' -or
        [string]$prior.pod_id -ne $PodId -or
        [string]$prior.name -ne $ExpectedName
    ) {
        throw 'Existing resume receipt identity is invalid'
    }
    Get-Content -Raw -LiteralPath $receipt
    exit 0
}

$line = Get-Content -LiteralPath $credential |
    Where-Object { $_ -match '^\s*Runpod\s*:' } |
    Select-Object -First 1
if (-not $line) { throw 'RunPod credential label not found' }
$apiKey = ($line -split ':', 2)[1].Trim()
if (-not $apiKey -or $apiKey -match '\s') { throw 'RunPod credential malformed' }
$headers = @{ Authorization = "Bearer $apiKey"; Accept = 'application/json' }
$uri = "https://rest.runpod.io/v1/pods/$PodId"
$pod = Invoke-RestMethod -Method Get -Uri $uri -Headers $headers -TimeoutSec 30
if ([string]$pod.id -ne $PodId -or [string]$pod.name -ne $ExpectedName) {
    throw 'Provider Pod identity does not match the requested dedicated runtime'
}
$resumeRequested = $false
if ([string]$pod.desiredStatus -eq 'EXITED') {
    $null = Invoke-RestMethod -Method Post -Uri "$uri/start" `
        -Headers $headers -TimeoutSec 60
    $resumeRequested = $true
}
elseif ([string]$pod.desiredStatus -ne 'RUNNING') {
    throw "Pod is not resumable from status $($pod.desiredStatus)"
}

$ready = $null
while ([DateTimeOffset]::UtcNow -lt $deadline) {
    $current = Invoke-RestMethod -Method Get -Uri $uri -Headers $headers -TimeoutSec 30
    $sshPort = $current.portMappings.'22'
    if (
        [string]$current.desiredStatus -eq 'RUNNING' -and
        [string]$current.publicIp -and
        $null -ne $sshPort
    ) {
        $ready = $current
        break
    }
    Start-Sleep -Seconds $PollSeconds
}
if ($null -eq $ready) { throw 'Pod did not expose SSH before the deadline' }
$rate = [double]$ready.costPerHr
if ($rate -le 0 -or $rate -gt 1.05) { throw 'Pod hourly rate is outside the approved gate' }

$receiptDirectory = Split-Path -Parent $receipt
$null = New-Item -ItemType Directory -Path $receiptDirectory -Force
$watchdogReceipt = Join-Path $receiptDirectory 'watchdog-receipt.json'
$watchdogArguments = @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass',
    '-File', (Join-Path $repository 'tools\release\runpod_pod_watchdog.ps1'),
    '-PodId', $PodId,
    '-CredentialFile', $credential,
    '-DeadlineUtc', $deadline.ToString('o'),
    '-ReceiptOut', $watchdogReceipt
)
$watchdog = Start-Process -FilePath 'powershell.exe' `
    -ArgumentList $watchdogArguments -WindowStyle Hidden -PassThru
$payload = [ordered]@{
    schema = 'folynta.runpod-resumed-pod.v1'
    status = 'running_endpoint_ready'
    pod_id = $PodId
    name = [string]$ready.name
    resume_requested = $resumeRequested
    host = [string]$ready.publicIp
    port = [int]$ready.portMappings.'22'
    gpu_type = [string]$ready.machine.gpuTypeId
    cost_per_hour_usd = $rate
    last_started_at_utc = [string]$ready.lastStartedAt
    watchdog_pid = $watchdog.Id
    watchdog_receipt = $watchdogReceipt
    observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receipt -Encoding utf8
Get-Content -Raw -LiteralPath $receipt
