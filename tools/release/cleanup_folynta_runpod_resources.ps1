param(
    [Parameter(Mandatory = $true)] [string]$CredentialFile,
    [Parameter(Mandatory = $true)] [string]$RegistryFile,
    [Parameter(Mandatory = $true)] [string]$ReceiptOut,
    [int]$PollSeconds = 10
)

$ErrorActionPreference = 'Stop'
if ($PollSeconds -lt 5 -or $PollSeconds -gt 60) {
    throw 'PollSeconds must be between 5 and 60'
}
$credential = [IO.Path]::GetFullPath($CredentialFile)
$registryPath = [IO.Path]::GetFullPath($RegistryFile)
$receipt = [IO.Path]::GetFullPath($ReceiptOut)
$registry = Get-Content -Raw -LiteralPath $registryPath | ConvertFrom-Json
if ($registry.schema -ne 'folynta.runpod-campaign-pod-registry.v1') {
    throw 'Campaign registry identity is invalid'
}
$registryIds = @($registry.pods | ForEach-Object { [string]$_.pod_id })

$line = Get-Content -LiteralPath $credential |
    Where-Object { $_ -match '^\s*Runpod\s*:' } |
    Select-Object -First 1
if (-not $line) { throw 'RunPod credential label not found' }
$apiKey = ($line -split ':', 2)[1].Trim()
if (-not $apiKey -or $apiKey -match '\s') { throw 'RunPod credential malformed' }
$headers = @{ Authorization = "Bearer $apiKey"; Accept = 'application/json' }
$providerResponse = Invoke-RestMethod -Method Get `
    -Uri 'https://rest.runpod.io/v1/pods' -Headers $headers -TimeoutSec 30
$providerPods = @($providerResponse | ForEach-Object { $_ })
$prefixPods = @($providerPods | Where-Object { [string]$_.name -like 'folynta-*' })
$ids = @($registryIds + @($prefixPods | ForEach-Object { [string]$_.id }) |
    Select-Object -Unique)
if ($ids.Count -lt [int]$registry.pod_count) {
    throw 'Cleanup identity coverage is smaller than the campaign registry'
}
$deletions = @()
foreach ($podId in $ids) {
    if ($podId -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{9,63}$') {
        throw 'Cleanup target contains an invalid Pod id'
    }
    $uri = "https://rest.runpod.io/v1/pods/$podId"
    $wasPresent = $true
    $providerName = ''
    try {
        $pod = Invoke-RestMethod -Method Get -Uri $uri -Headers $headers -TimeoutSec 30
        if ([string]$pod.id -ne $podId) { throw 'Provider Pod identity mismatch' }
        $providerName = [string]$pod.name
        if ($providerName -and $providerName -notlike 'folynta-*') {
            throw "Refusing to delete a non-FOLYNTA provider Pod: $providerName"
        }
    }
    catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        if ($statusCode -eq 404) { $wasPresent = $false } else { throw }
    }
    if ($wasPresent) {
        $null = Invoke-RestMethod -Method Delete -Uri $uri `
            -Headers $headers -TimeoutSec 30
    }
    $absent = $false
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        try {
            $null = Invoke-RestMethod -Method Get -Uri $uri `
                -Headers $headers -TimeoutSec 30
        }
        catch {
            if ($_.Exception.Response.StatusCode.value__ -eq 404) {
                $absent = $true
                break
            }
        }
        Start-Sleep -Seconds $PollSeconds
    }
    if (-not $absent) { throw "Provider absence was not verified for $podId" }
    $deletions += [ordered]@{
        pod_id = $podId
        name = $providerName
        was_present_before_delete = $wasPresent
        provider_absent_verified = $true
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
}
$afterResponse = Invoke-RestMethod -Method Get `
    -Uri 'https://rest.runpod.io/v1/pods' -Headers $headers -TimeoutSec 30
$remainingFOLYNTA = @($afterResponse | ForEach-Object { $_ } |
    Where-Object { [string]$_.name -like 'folynta-*' })
if ($remainingFOLYNTA.Count) {
    throw 'Provider still lists FOLYNTA Pods after cleanup'
}
$payload = [ordered]@{
    schema = 'folynta.runpod-campaign-cleanup.v1'
    registry_pod_count = [int]$registry.pod_count
    cleanup_target_count = $ids.Count
    pod_count = $ids.Count
    all_provider_absent = $true
    provider_prefix_remaining_count = 0
    pods = $deletions
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$null = New-Item -ItemType Directory -Path (Split-Path -Parent $receipt) -Force
$payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receipt -Encoding utf8
$payload | ConvertTo-Json -Compress -Depth 3
