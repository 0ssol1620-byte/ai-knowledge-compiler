param(
    [Parameter(Mandatory = $true)] [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)] [string]$CredentialFile,
    [string]$DeadlineUtc = '2026-08-06T11:30:00Z'
)

$ErrorActionPreference = 'Stop'
$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$credential = [IO.Path]::GetFullPath($CredentialFile)
$deadline = [DateTimeOffset]::Parse($DeadlineUtc).ToUniversalTime()
if ($deadline -le [DateTimeOffset]::UtcNow.AddHours(1)) {
    throw 'Expansion watchdog deadline must be at least one hour in the future'
}

$privateRoot = Join-Path $repository 'benchmark\datasets\private\runpod-2026-08-04'
$generated = Join-Path $repository 'benchmark\reports\generated'
$originalConfigPath = Join-Path $privateRoot 'public-core-workers.json'
$expandedConfigPath = Join-Path $privateRoot 'operational-retry-workers-expanded.json'
$inventoryPath = Join-Path `
    $generated `
    'folynta-runpod-all-pod-inventory-live-r1-2026-08-04.json'
$expansionRoot = Join-Path $privateRoot 'mineru-retry-expansion'
$receiptPath = Join-Path $expansionRoot 'provisioning-receipt.json'
$journalPath = Join-Path $expansionRoot 'provisioning.jsonl'
$knownHosts = Join-Path $privateRoot 'known_hosts'
$publicKeyPath = Join-Path $privateRoot 'builder_ed25519.pub'
$watchdogScript = Join-Path $repository 'tools\release\runpod_pod_watchdog.ps1'
$null = New-Item -ItemType Directory -Path $expansionRoot -Force

if (Test-Path -LiteralPath $receiptPath) {
    Get-Content -Raw -LiteralPath $receiptPath
    exit 0
}
if (Test-Path -LiteralPath $expandedConfigPath) {
    throw 'Expanded worker config exists without its provisioning receipt'
}

function Write-JournalEvent {
    param([string]$Event, [hashtable]$Fields = @{})
    $value = [ordered]@{
        event = $Event
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    foreach ($name in $Fields.Keys) { $value[$name] = $Fields[$name] }
    Add-Content `
        -LiteralPath $journalPath `
        -Value ($value | ConvertTo-Json -Compress -Depth 8) `
        -Encoding utf8
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
    throw 'Expansion public key is malformed'
}

$originalConfig = Get-Content -Raw -LiteralPath $originalConfigPath | ConvertFrom-Json
if (@($originalConfig.workers).Count -ne 4) {
    throw 'Primary worker config must remain the frozen four-worker configuration'
}
$inventory = Get-Content -Raw -LiteralPath $inventoryPath | ConvertFrom-Json
if ([int]$inventory.pod_count -ne 6 -or @($inventory.pods).Count -ne 6) {
    throw 'Base campaign inventory must contain the original six Pods'
}

$sourcePod = Invoke-RestMethod `
    -Method Get `
    -Uri 'https://rest.runpod.io/v1/pods/nut7g2azdnrtm6' `
    -Headers $headers `
    -TimeoutSec 30
$expectedImage = `
    'runpod/pytorch@sha256:263d4144a3053f5125b04174e279d73b43768c5b798cd76c4871af7b737f0c84'
if (
    [string]$sourcePod.id -ne 'nut7g2azdnrtm6' -or
    [string]$sourcePod.desiredStatus -ne 'RUNNING' -or
    [string]$sourcePod.imageName -ne $expectedImage
) {
    throw 'Pinned MinerU source Pod identity or runtime image changed'
}

$indices = @(4, 5, 6)
$names = $indices | ForEach-Object { "folynta-mineru344-operational-retry-$($_)" }
$providerPods = @(Invoke-RestMethod `
    -Method Get `
    -Uri 'https://rest.runpod.io/v1/pods' `
    -Headers $headers `
    -TimeoutSec 30)
$journalPods = @(Get-Content -LiteralPath $journalPath |
    ForEach-Object { $_ | ConvertFrom-Json } |
    Where-Object { $_.event -eq 'pod-created' } |
    Group-Object worker_index |
    ForEach-Object { $_.Group | Select-Object -First 1 })
$existingExpansionPods = if ($journalPods.Count -eq 3) {
    @($journalPods | ForEach-Object {
        Invoke-RestMethod `
            -Method Get `
            -Uri "https://rest.runpod.io/v1/pods/$([string]$_.pod_id)" `
            -Headers $headers `
            -TimeoutSec 30
    })
}
else {
    @($providerPods | Where-Object { [string]$_.name -in $names })
}
if ($existingExpansionPods.Count -notin @(0, 3)) {
    throw 'Provider expansion inventory is partial or ambiguous'
}

$created = @()
foreach ($index in $indices) {
    $name = "folynta-mineru344-operational-retry-$index"
    $existing = @($existingExpansionPods | Where-Object { [string]$_.name -eq $name })
    if ($existing.Count -eq 1) {
        $pod = $existing[0]
        Write-JournalEvent -Event 'pod-adopted-after-provisioning-retry' -Fields @{
            worker_index = $index
            pod_id = [string]$pod.id
            name = $name
        }
    }
    elseif ($existing.Count -eq 0 -and $existingExpansionPods.Count -eq 0) {
        $payload = [ordered]@{
            name = $name
            imageName = $expectedImage
            cloudType = 'SECURE'
            computeType = 'GPU'
            gpuTypeIds = @('NVIDIA GeForce RTX 4090')
            gpuTypePriority = 'availability'
            gpuCount = 1
            containerDiskInGb = 100
            volumeInGb = 20
            volumeMountPath = '/workspace'
            ports = @('22/tcp')
            supportPublicIp = $true
            interruptible = $false
            dockerEntrypoint = @('/bin/bash', '-lc')
            dockerStartCmd = @([string]$sourcePod.dockerStartCmd[0])
            env = [ordered]@{
                PUBLIC_KEY = $publicKey
                FOLYNTA_QUALIFICATION_ONLY = '1'
                MINERU_API_MAX_CONCURRENT_REQUESTS = '1'
            }
        }
        $pod = Invoke-RestMethod `
            -Method Post `
            -Uri 'https://rest.runpod.io/v1/pods' `
            -Headers $headers `
            -ContentType 'application/json' `
            -Body ($payload | ConvertTo-Json -Compress -Depth 10) `
            -TimeoutSec 60
    }
    else {
        throw "Expansion Pod identity is missing or duplicated for worker $index"
    }
    $podId = [string]$pod.id
    if ($podId -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$') {
        throw 'RunPod create response omitted a valid Pod id'
    }
    Write-JournalEvent -Event 'pod-created' -Fields @{
        worker_index = $index
        pod_id = $podId
        name = $name
    }
    $watchdogReceipt = Join-Path $expansionRoot "worker-$index-watchdog.json"
    $priorWatchdogEvent = Get-Content -LiteralPath $journalPath |
        ForEach-Object { $_ | ConvertFrom-Json } |
        Where-Object {
            $_.event -eq 'watchdog-started' -and
            [string]$_.pod_id -eq $podId
        } |
        Select-Object -Last 1
    $watchdog = if (
        $priorWatchdogEvent -and
        (Get-Process -Id ([int]$priorWatchdogEvent.watchdog_pid) -ErrorAction SilentlyContinue)
    ) {
        [pscustomobject]@{ Id = [int]$priorWatchdogEvent.watchdog_pid }
    }
    else {
        $arguments = @(
            '-NoProfile',
            '-ExecutionPolicy', 'Bypass',
            '-File', $watchdogScript,
            '-PodId', $podId,
            '-CredentialFile', $credential,
            '-DeadlineUtc', $deadline.ToString('o'),
            '-ReceiptOut', $watchdogReceipt
        )
        $started = Start-Process `
            -FilePath 'powershell.exe' `
            -ArgumentList $arguments `
            -WindowStyle Hidden `
            -PassThru
        Write-JournalEvent -Event 'watchdog-started' -Fields @{
            worker_index = $index
            pod_id = $podId
            watchdog_pid = $started.Id
        }
        $started
    }
    $created += [ordered]@{
        worker_index = $index
        pod_id = $podId
        role = "mineru-operational-retry-worker-$index"
        name = $name
        watchdog_pid = $watchdog.Id
        watchdog_receipt = $watchdogReceipt
    }
}

foreach ($item in $created) {
    $ready = $null
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        $pod = Invoke-RestMethod `
            -Method Get `
            -Uri "https://rest.runpod.io/v1/pods/$($item.pod_id)" `
            -Headers $headers `
            -TimeoutSec 30
        $port = $pod.portMappings.'22'
        if (
            [string]$pod.desiredStatus -eq 'RUNNING' -and
            [string]$pod.publicIp -and
            $null -ne $port
        ) {
            $ready = $pod
            break
        }
        Start-Sleep -Seconds 10
    }
    if ($null -eq $ready) { throw "Expansion Pod did not become SSH-ready: $($item.pod_id)" }
    $item.public_ip = [string]$ready.publicIp
    $item.ssh_port = [int]$ready.portMappings.'22'
    $item.status = [string]$ready.desiredStatus
    $item.cost_per_hour_usd = [double]$ready.costPerHr
    $item.last_started_at = [string]$ready.lastStartedAt
    if ($item.cost_per_hour_usd -gt 0.75) {
        throw "Expansion Pod hourly rate exceeded the approved RTX 4090 bound"
    }
    $scan = $null
    for ($attempt = 1; $attempt -le 12; $attempt++) {
        $oldPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $scan = & wsl.exe `
            -e ssh-keyscan `
            -T 10 `
            -p $item.ssh_port `
            $item.public_ip 2>$null
        $scanExit = $LASTEXITCODE
        $ErrorActionPreference = $oldPreference
        if ($scanExit -eq 0 -and @($scan).Count) { break }
        Write-JournalEvent -Event 'ssh-host-key-not-ready' -Fields @{
            worker_index = $item.worker_index
            attempt = $attempt
        }
        Start-Sleep -Seconds 5
    }
    if (-not @($scan).Count) { throw "SSH host-key scan failed for worker $($item.worker_index)" }
    foreach ($hostLine in @($scan | Where-Object { $_ -and -not $_.StartsWith('#') })) {
        if (-not (Select-String -LiteralPath $knownHosts -SimpleMatch $hostLine -Quiet)) {
            Add-Content -LiteralPath $knownHosts -Value $hostLine -Encoding ascii
        }
    }
    Write-JournalEvent -Event 'pod-ssh-ready' -Fields @{
        worker_index = $item.worker_index
        pod_id = $item.pod_id
        public_ip = $item.public_ip
        ssh_port = $item.ssh_port
        cost_per_hour_usd = $item.cost_per_hour_usd
    }
}

$expandedWorkers = @($originalConfig.workers | ForEach-Object {
    [ordered]@{
        worker_index = [int]$_.worker_index
        host = [string]$_.host
        port = [int]$_.port
    }
})
$expandedWorkers += @($created | ForEach-Object {
    [ordered]@{
        worker_index = [int]$_.worker_index
        host = [string]$_.public_ip
        port = [int]$_.ssh_port
    }
})
$expandedConfig = [ordered]@{
    workers = $expandedWorkers
    key = [string]$originalConfig.key
    known_hosts = [string]$originalConfig.known_hosts
    deadline_utc = $deadline.ToString('o')
}
$expandedConfig | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $expandedConfigPath -Encoding utf8

$inventoryPods = @($inventory.pods)
$inventoryPods += @($created | ForEach-Object {
    [ordered]@{
        pod_id = [string]$_.pod_id
        role = [string]$_.role
        name = [string]$_.name
        status = [string]$_.status
        cost_per_hour_usd = [double]$_.cost_per_hour_usd
        image = $expectedImage
        last_started_at = [string]$_.last_started_at
        public_ip = [string]$_.public_ip
        ssh_port = [int]$_.ssh_port
    }
})
$updatedInventory = [ordered]@{
    schema = [string]$inventory.schema
    approved_cap_usd = [double]$inventory.approved_cap_usd
    pod_count = $inventoryPods.Count
    pods = $inventoryPods
    observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$updatedInventory | ConvertTo-Json -Depth 10 |
    Set-Content -LiteralPath $inventoryPath -Encoding utf8

$receipt = [ordered]@{
    schema = 'folynta.mineru-operational-retry-expansion-provisioning.v1'
    status = 'provisioned_ssh_ready'
    source_pod_id = 'nut7g2azdnrtm6'
    image_digest = $expectedImage
    gpu_type = 'NVIDIA GeForce RTX 4090'
    worker_count = $created.Count
    workers = $created
    expanded_config = $expandedConfigPath
    inventory = $inventoryPath
    deadline_utc = $deadline.ToString('o')
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$receipt | ConvertTo-Json -Depth 10 |
    Set-Content -LiteralPath $receiptPath -Encoding utf8
Write-JournalEvent -Event 'provisioning-complete' -Fields @{
    worker_count = $created.Count
    inventory_pod_count = $inventoryPods.Count
}
$receipt | ConvertTo-Json -Compress -Depth 10
