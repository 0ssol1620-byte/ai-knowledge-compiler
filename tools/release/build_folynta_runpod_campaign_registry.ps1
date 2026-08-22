param(
    [Parameter(Mandatory = $true)] [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)] [string]$CredentialFile,
    [Parameter(Mandatory = $true)] [string]$ReceiptOut
)

$ErrorActionPreference = 'Stop'
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
    throw 'Registry receipt must stay under benchmark/reports/generated'
}
$ids = [ordered]@{}

function Add-PodIdentity {
    param([string]$PodId, [string]$Source, [string]$Name = '')
    if ($PodId -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{9,63}$') { return }
    if (-not $ids.Contains($PodId)) {
        $ids[$PodId] = [ordered]@{
            pod_id = $PodId
            name = $Name
            evidence_sources = [System.Collections.Generic.List[string]]::new()
        }
    }
    if ($Name -and -not [string]$ids[$PodId].name) { $ids[$PodId].name = $Name }
    if (-not $ids[$PodId].evidence_sources.Contains($Source)) {
        $ids[$PodId].evidence_sources.Add($Source)
    }
}

function Find-PodIds {
    param([object]$Value, [string]$Source)
    if ($null -eq $Value) { return }
    if ($Value -is [string] -or $Value -is [ValueType]) { return }
    if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [pscustomobject]) {
        foreach ($item in $Value) { Find-PodIds -Value $item -Source $Source }
        return
    }
    foreach ($property in $Value.PSObject.Properties) {
        if ($property.Name -in @('pod_id', 'podId')) {
            Add-PodIdentity -PodId ([string]$property.Value) -Source $Source
        }
        else {
            Find-PodIds -Value $property.Value -Source $Source
        }
    }
}

$evidenceFiles = Get-ChildItem -LiteralPath $generated -Recurse -File -Filter '*.json' |
    Where-Object { $_.FullName -ne $receipt }
foreach ($file in $evidenceFiles) {
    try {
        $raw = Get-Content -Raw -LiteralPath $file.FullName
        $relative = $file.FullName.Substring($repository.Length).TrimStart('\', '/')
        foreach ($match in [regex]::Matches(
                $raw,
                '"(?:pod_id|podId)"\s*:\s*"([A-Za-z0-9_-]{10,64})"'
            )) {
            Add-PodIdentity -PodId $match.Groups[1].Value -Source $relative
        }
    }
    catch {
        # A non-JSON or partially written progress artifact is not registry evidence.
    }
}

$line = Get-Content -LiteralPath $credential |
    Where-Object { $_ -match '^\s*Runpod\s*:' } |
    Select-Object -First 1
if (-not $line) { throw 'RunPod credential label not found' }
$apiKey = ($line -split ':', 2)[1].Trim()
if (-not $apiKey -or $apiKey -match '\s') { throw 'RunPod credential malformed' }
$headers = @{ Authorization = "Bearer $apiKey"; Accept = 'application/json' }
$providerResponse = Invoke-RestMethod -Method Get `
    -Uri 'https://rest.runpod.io/v1/pods' -Headers $headers -TimeoutSec 30
foreach ($pod in @($providerResponse)) {
    if ([string]$pod.name -like 'folynta-*') {
        Add-PodIdentity -PodId ([string]$pod.id) `
            -Source 'GET https://rest.runpod.io/v1/pods' -Name ([string]$pod.name)
    }
}

$pods = @($ids.Values | ForEach-Object {
    [ordered]@{
        pod_id = [string]$_.pod_id
        name = [string]$_.name
        evidence_sources = @($_.evidence_sources | Sort-Object)
    }
} | Sort-Object pod_id)
if ($pods.Count -lt 12) { throw 'Campaign registry coverage is unexpectedly small' }
$payload = [ordered]@{
    schema = 'folynta.runpod-campaign-pod-registry.v1'
    pod_count = $pods.Count
    pods = $pods
    provider_name_scope = 'folynta-*'
    generated_evidence_scanned = $evidenceFiles.Count
    observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$null = New-Item -ItemType Directory -Path (Split-Path -Parent $receipt) -Force
$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $receipt -Encoding utf8
$payload | ConvertTo-Json -Compress -Depth 3
