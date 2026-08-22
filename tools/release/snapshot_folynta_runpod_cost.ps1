param(
    [Parameter(Mandatory = $true)]
    [string]$CredentialFile,

    [Parameter(Mandatory = $true)]
    [string]$InventoryFile,

    [Parameter(Mandatory = $true)]
    [string]$ReceiptOut,

    [string]$CarriedSnapshot,

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

if ($ApprovedCapUsd -le 0) {
    throw 'ApprovedCapUsd must be positive'
}

$repository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$generatedRoot = [IO.Path]::GetFullPath(
    (Join-Path $repository 'benchmark\reports\generated')
)
$receiptPath = [IO.Path]::GetFullPath($ReceiptOut)
if (-not $receiptPath.StartsWith(
        $generatedRoot + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw 'Cost receipt must stay under benchmark/reports/generated'
}

$credentialPath = [IO.Path]::GetFullPath($CredentialFile)
$inventoryPath = [IO.Path]::GetFullPath($InventoryFile)
$inventory = Get-Content -Raw -LiteralPath $inventoryPath | ConvertFrom-Json
$carriedTotal = [decimal]0
$carriedThrough = [DateTimeOffset]::MinValue
$carriedSnapshotSha256 = $null
if ($CarriedSnapshot) {
    $carriedPath = [IO.Path]::GetFullPath($CarriedSnapshot)
    $carried = Get-Content -Raw -LiteralPath $carriedPath | ConvertFrom-Json
    if (
        $carried.schema -ne 'folynta.runpod-campaign-cost-snapshot.v1' -or
        [decimal]$carried.approved_cap_usd -ne $ApprovedCapUsd -or
        $carried.within_approved_cap -ne $true
    ) {
        throw 'Carried cost snapshot is invalid or exceeds the approved cap'
    }
    $carriedTotal = [decimal]$carried.total_runtime_rate_estimate_usd
    $carriedThrough = [DateTimeOffset]::Parse(
        [string]$carried.observed_at_utc
    ).ToUniversalTime()
    $carriedSnapshotSha256 = 'sha256:' + (Get-Sha256Hex -Path $carriedPath)
}
$inventoryPods = @($inventory.pods)
if ($inventoryPods.Count -lt 1 -or $inventoryPods.Count -gt 16) {
    throw 'The campaign inventory must contain between one and sixteen Pods'
}
$inventoryIds = @($inventoryPods | ForEach-Object { [string]$_.pod_id })
if (@($inventoryIds | Select-Object -Unique).Count -ne $inventoryIds.Count) {
    throw 'The campaign inventory contains duplicate Pod ids'
}
$historicalAdjustments = @($inventory.historical_cost_adjustments)
if ($historicalAdjustments.Count -gt 16) {
    throw 'The campaign inventory contains too many historical cost adjustments'
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

$observedAt = [DateTimeOffset]::UtcNow
$podReceipts = @()
foreach ($inventoryPod in $inventoryPods) {
    $podId = [string]$inventoryPod.pod_id
    if ($podId -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$') {
        throw 'Inventory contains an invalid Pod id'
    }
    $pod = Invoke-RestMethod `
        -Method Get `
        -Uri "https://rest.runpod.io/v1/pods/$podId" `
        -Headers $headers `
        -TimeoutSec 30
    if ([string]$pod.id -ne $podId) {
        throw "RunPod response identity mismatch for $podId"
    }
    $started = [DateTimeOffset]::Parse(
        ([string]$pod.lastStartedAt -replace ' UTC$', '')
    ).ToUniversalTime()
    $effectiveStarted = if ($started -lt $carriedThrough) {
        $carriedThrough
    }
    else {
        $started
    }
    $hours = ($observedAt - $effectiveStarted).TotalHours
    if ($hours -lt 0) {
        throw "RunPod start time is in the future for $podId"
    }
    $rate = [decimal]$pod.costPerHr
    if ($rate -le 0) {
        throw "RunPod hourly rate is invalid for $podId"
    }
    $podReceipts += [ordered]@{
        pod_id = $podId
        name = [string]$pod.name
        desired_status = [string]$pod.desiredStatus
        last_started_at_utc = $started.ToString('o')
        cost_counted_from_utc = $effectiveStarted.ToString('o')
        observed_runtime_hours = [math]::Round($hours, 6)
        hourly_rate_usd = [math]::Round([double]$rate, 6)
        runtime_rate_estimate_usd = [math]::Round($hours * [double]$rate, 6)
    }
}

$currentPeriodTotal = [decimal]0
foreach ($podReceipt in $podReceipts) {
    $currentPeriodTotal += [decimal]$podReceipt.runtime_rate_estimate_usd
}
$historicalTotal = [decimal]0
foreach ($adjustment in $historicalAdjustments) {
    $adjustmentCost = [decimal]$adjustment.runtime_rate_estimate_usd
    if (
        $adjustmentCost -lt 0 -or
        [string]$adjustment.pod_id -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$' -or
        $inventoryIds -contains [string]$adjustment.pod_id
    ) {
        throw 'Historical cost adjustment is invalid or overlaps the active inventory'
    }
    $historicalTotal += $adjustmentCost
}
$currentPeriodTotal += $historicalTotal
$total = $carriedTotal + $currentPeriodTotal
$receipt = [ordered]@{
    schema = 'folynta.runpod-campaign-cost-snapshot.v1'
    evidence_kind = 'provider-runtime-rate-estimate'
    provider_endpoint = 'GET https://rest.runpod.io/v1/pods/{pod_id}'
    approved_cap_usd = [math]::Round([double]$ApprovedCapUsd, 2)
    observed_at_utc = $observedAt.ToString('o')
    carried_snapshot_sha256 = $carriedSnapshotSha256
    carried_through_utc = if ($CarriedSnapshot) { $carriedThrough.ToString('o') } else { $null }
    carried_total_usd = [math]::Round([double]$carriedTotal, 6)
    pod_count = $podReceipts.Count
    pods = $podReceipts
    historical_cost_adjustments = $historicalAdjustments
    historical_adjustment_total_usd = [math]::Round([double]$historicalTotal, 6)
    current_period_total_usd = [math]::Round([double]$currentPeriodTotal, 6)
    total_runtime_rate_estimate_usd = [math]::Round([double]$total, 6)
    remaining_cap_estimate_usd = [math]::Round(
        [double]($ApprovedCapUsd - $total),
        6
    )
    within_approved_cap = $total -le $ApprovedCapUsd
}

$directory = Split-Path -Parent $receiptPath
$null = New-Item -ItemType Directory -Path $directory -Force
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding utf8
$hash = (Get-Sha256Hex -Path $receiptPath)
[ordered]@{
    receipt = $receiptPath
    receipt_sha256 = "sha256:$hash"
    total_runtime_rate_estimate_usd = $receipt.total_runtime_rate_estimate_usd
    within_approved_cap = $receipt.within_approved_cap
} | ConvertTo-Json -Compress
