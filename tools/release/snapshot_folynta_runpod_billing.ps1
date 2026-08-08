param(
    [Parameter(Mandatory = $true)] [string]$CredentialFile,
    [Parameter(Mandatory = $true)] [string]$RegistryFile,
    [Parameter(Mandatory = $true)] [string]$ReceiptOut,
    [string]$StartUtc = '2026-08-03T22:00:00Z',
    [decimal]$ApprovedCapUsd = 400
)

$ErrorActionPreference = 'Stop'

function Get-Sha256Hex {
    # Get-FileHash lives in Microsoft.PowerShell.Utility and was not resolvable
    # in the hosted session these controllers run under. Hashing through .NET
    # removes the module dependency and produces the identical digest.
    param([Parameter(Mandatory = $true)] [string]$Path)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        try { $bytes = $sha.ComputeHash($stream) }
        finally { $stream.Dispose() }
    }
    finally { $sha.Dispose() }
    return ([BitConverter]::ToString($bytes) -replace '-', '').ToLowerInvariant()
}

if ($ApprovedCapUsd -le 0) { throw 'ApprovedCapUsd must be positive' }
$credential = [IO.Path]::GetFullPath($CredentialFile)
$registryPath = [IO.Path]::GetFullPath($RegistryFile)
$receipt = [IO.Path]::GetFullPath($ReceiptOut)
$registry = Get-Content -Raw -LiteralPath $registryPath | ConvertFrom-Json
if ($registry.schema -ne 'folynta.runpod-campaign-pod-registry.v1') {
    throw 'Campaign registry identity is invalid'
}
$registryIds = @($registry.pods | ForEach-Object { [string]$_.pod_id })
if (
    $registryIds.Count -ne [int]$registry.pod_count -or
    @($registryIds | Select-Object -Unique).Count -ne $registryIds.Count
) {
    throw 'Campaign registry coverage is invalid'
}
$start = [DateTimeOffset]::Parse($StartUtc).ToUniversalTime()
$observed = [DateTimeOffset]::UtcNow
if ($start -ge $observed) { throw 'Billing start must precede the observation time' }

$line = Get-Content -LiteralPath $credential |
    Where-Object { $_ -match '^\s*Runpod\s*:' } |
    Select-Object -First 1
if (-not $line) { throw 'RunPod credential label not found' }
$apiKey = ($line -split ':', 2)[1].Trim()
if (-not $apiKey -or $apiKey -match '\s') { throw 'RunPod credential malformed' }
$headers = @{ Authorization = "Bearer $apiKey"; Accept = 'application/json' }
$query = @{
    bucketSize = 'day'
    grouping = 'podId'
    startTime = $start.ToString('yyyy-MM-ddTHH:mm:ssZ')
    endTime = $observed.ToString('yyyy-MM-ddTHH:mm:ssZ')
}
$uri = 'https://rest.runpod.io/v1/billing/pods?' + (
    @($query.GetEnumerator() | Sort-Object Name | ForEach-Object {
        [Uri]::EscapeDataString([string]$_.Name) + '=' +
            [Uri]::EscapeDataString([string]$_.Value)
    }) -join '&'
)
$providerBilling = Invoke-RestMethod -Method Get -Uri $uri -Headers $headers -TimeoutSec 60
$records = @($providerBilling | ForEach-Object { $_ })
$selected = @($records | Where-Object { $registryIds -contains [string]$_.podId })
if (-not $selected.Count) { throw 'Provider billing returned no campaign records' }
$grouped = @($selected | Group-Object podId)
$pods = @()
$total = [decimal]0
foreach ($group in $grouped) {
    $amount = [decimal]0
    $runtimeMs = [long]0
    $diskGb = [long]0
    foreach ($row in $group.Group) {
        $amount += [decimal]$row.amount
        $runtimeMs += [long]$row.timeBilledMs
        $diskGb += [long]$row.diskSpaceBilledGB
    }
    $total += $amount
    $metadata = $registry.pods | Where-Object { [string]$_.pod_id -eq $group.Name } |
        Select-Object -First 1
    $runtimeHours = [double]$runtimeMs / 3600000.0
    $pods += [ordered]@{
        pod_id = [string]$group.Name
        name = [string]$metadata.name
        desired_status = 'BILLED'
        last_started_at_utc = $start.ToString('o')
        cost_counted_from_utc = $start.ToString('o')
        observed_runtime_hours = [math]::Round($runtimeHours, 6)
        hourly_rate_usd = if ($runtimeHours -gt 0) {
            [math]::Round([double]$amount / $runtimeHours, 6)
        }
        else { 0 }
        runtime_rate_estimate_usd = [math]::Round([double]$amount, 6)
        provider_billed_usd = [math]::Round([double]$amount, 9)
        time_billed_ms = $runtimeMs
        disk_space_billed_gb = $diskGb
        bucket_count = $group.Count
    }
}
$unbilledRegistryIds = @($registryIds | Where-Object {
    $grouped.Name -notcontains $_
})
$payload = [ordered]@{
    schema = 'folynta.runpod-campaign-cost-snapshot.v1'
    evidence_kind = 'provider-billing-records'
    provider_endpoint = 'GET https://rest.runpod.io/v1/billing/pods'
    approved_cap_usd = [math]::Round([double]$ApprovedCapUsd, 2)
    observed_at_utc = $observed.ToString('o')
    billing_start_utc = $start.ToString('o')
    registry_sha256 = 'sha256:' + (Get-Sha256Hex -Path $registryPath)
    pod_count = $pods.Count
    pods = @($pods | Sort-Object pod_id)
    provider_record_count = $selected.Count
    registry_pod_count = $registryIds.Count
    unbilled_registry_pod_ids = $unbilledRegistryIds
    total_runtime_rate_estimate_usd = [math]::Round([double]$total, 6)
    remaining_cap_estimate_usd = [math]::Round(
        [double]($ApprovedCapUsd - $total), 6
    )
    within_approved_cap = $total -le $ApprovedCapUsd
}
$null = New-Item -ItemType Directory -Path (Split-Path -Parent $receipt) -Force
$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $receipt -Encoding utf8
$payload | ConvertTo-Json -Compress -Depth 3
