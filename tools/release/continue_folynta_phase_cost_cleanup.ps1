param(
    [Parameter(Mandatory = $true)] [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)] [string]$CredentialFile,
    [Parameter(Mandatory = $true)] [string]$DeadlineUtc,
    [int]$PollSeconds = 60
)

$ErrorActionPreference = 'Stop'
if ($PollSeconds -lt 30 -or $PollSeconds -gt 300) {
    throw 'PollSeconds must be between 30 and 300'
}
$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$credential = [IO.Path]::GetFullPath($CredentialFile)
$deadline = [DateTimeOffset]::Parse($DeadlineUtc).ToUniversalTime()
if ($deadline -le [DateTimeOffset]::UtcNow.AddHours(1)) {
    throw 'DeadlineUtc must be at least one hour in the future'
}
$generated = Join-Path $repository 'benchmark\reports\generated'
$controllerRoot = Join-Path `
    $generated 'folynta-phase-cost-cleanup-2026-08-05'
$progress = Join-Path $controllerRoot 'progress.jsonl'
$terminal = Join-Path $controllerRoot 'terminal-receipt.json'
$null = New-Item -ItemType Directory -Path $controllerRoot -Force

function Get-Sha256Hex {
    # Get-FileHash lives in Microsoft.PowerShell.Utility and was not resolvable
    # in the hosted session this controller runs under, which killed the phase
    # after it had already stopped Pods. Hashing through .NET removes the module
    # dependency entirely and produces the identical digest.
    param([Parameter(Mandatory = $true)] [string]$Path)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        try {
            $bytes = $sha.ComputeHash($stream)
        }
        finally { $stream.Dispose() }
    }
    finally { $sha.Dispose() }
    return ([BitConverter]::ToString($bytes) -replace '-', '').ToLowerInvariant()
}

function Write-CostEvent {
    param([string]$Event, [hashtable]$Fields = @{})
    $payload = [ordered]@{
        event = $Event
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    foreach ($name in $Fields.Keys) { $payload[$name] = $Fields[$name] }
    Add-Content -LiteralPath $progress `
        -Value ($payload | ConvertTo-Json -Compress -Depth 10) -Encoding utf8
}

function Wait-ForFile {
    param([string]$Path, [string]$Event)
    while (-not (Test-Path -LiteralPath $Path)) {
        if ([DateTimeOffset]::UtcNow -ge $deadline) {
            throw "Deadline reached while waiting for $Path"
        }
        Write-CostEvent -Event $Event
        Start-Sleep -Seconds $PollSeconds
    }
}

$line = Get-Content -LiteralPath $credential |
    Where-Object { $_ -match '^\s*Runpod\s*:' } |
    Select-Object -First 1
if (-not $line) { throw 'RunPod credential label not found' }
$apiKey = ($line -split ':', 2)[1].Trim()
if (-not $apiKey -or $apiKey -match '\s') {
    throw 'RunPod credential malformed'
}
$headers = @{ Authorization = "Bearer $apiKey"; Accept = 'application/json' }

function Stop-VerifiedPod {
    param(
        [string]$PodId,
        [string]$ExpectedName,
        [string]$Phase
    )
    if ($PodId -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{9,63}$') {
        throw "Invalid Pod id for $Phase"
    }
    $uri = "https://rest.runpod.io/v1/pods/$PodId"
    try {
        $pod = Invoke-RestMethod -Method Get -Uri $uri `
            -Headers $headers -TimeoutSec 30
    }
    catch {
        if ([int]$_.Exception.Response.StatusCode -eq 404) {
            return [ordered]@{
                pod_id = $PodId
                expected_name = $ExpectedName
                phase = $Phase
                provider_status = 'ABSENT'
                stop_requested = $false
                stopped_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
            }
        }
        throw
    }
    if (
        [string]$pod.id -ne $PodId -or
        [string]$pod.name -ne $ExpectedName
    ) {
        throw "Pod identity mismatch for $PodId"
    }
    $requested = $false
    if ([string]$pod.desiredStatus -eq 'RUNNING') {
        $null = Invoke-RestMethod -Method Post -Uri "$uri/stop" `
            -Headers $headers -TimeoutSec 30
        $requested = $true
    }
    elseif ([string]$pod.desiredStatus -ne 'EXITED') {
        throw "Pod $PodId cannot be safely stopped from $($pod.desiredStatus)"
    }
    do {
        if ([DateTimeOffset]::UtcNow -ge $deadline) {
            throw "Deadline reached while stopping Pod $PodId"
        }
        $current = Invoke-RestMethod -Method Get -Uri $uri `
            -Headers $headers -TimeoutSec 30
        if (
            [string]$current.id -ne $PodId -or
            [string]$current.name -ne $ExpectedName
        ) {
            throw "Pod identity changed while stopping $PodId"
        }
        if ([string]$current.desiredStatus -eq 'EXITED') { break }
        Start-Sleep -Seconds ([Math]::Min(30, $PollSeconds))
    } while ($true)
    return [ordered]@{
        pod_id = $PodId
        expected_name = $ExpectedName
        phase = $Phase
        provider_status = [string]$current.desiredStatus
        stop_requested = $requested
        cost_per_hour_usd = [double]$current.costPerHr
        stopped_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
}

$alternateTerminal = Join-Path `
    $generated 'folynta-alternate-recovery-controller-2026-08-04\terminal-receipt.json'
Wait-ForFile -Path $alternateTerminal -Event 'waiting-for-alternate-recovery'
$alternate = Get-Content -Raw -LiteralPath $alternateTerminal | ConvertFrom-Json
if (
    $alternate.schema -ne 'folynta.alternate-recovery-controller-terminal.v1' -or
    $alternate.status -ne 'alternate_recovery_officially_selected' -or
    [int]$alternate.input_count -ne 5132
) {
    throw 'Alternate recovery evidence gate failed before cost cleanup'
}
$dedicatedStops = @(
    Stop-VerifiedPod -PodId '8q4p95vk8aqrqc' `
        -ExpectedName 'folynta-paddleocr-vl16-recovery-r1' `
        -Phase 'alternate-recovery-complete'
    Stop-VerifiedPod -PodId '68lo3k8a2lft1i' `
        -ExpectedName 'folynta-deepseek-ocr2-recovery-r1' `
        -Phase 'alternate-recovery-complete'
)
$dedicatedReceipt = Join-Path $controllerRoot 'dedicated-pod-stop-receipt.json'
[ordered]@{
    schema = 'folynta.phase-cost-cleanup.v1'
    phase = 'alternate-recovery-complete'
    evidence_sha256 = 'sha256:' + (Get-Sha256Hex -Path $alternateTerminal)
    pods = $dedicatedStops
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $dedicatedReceipt -Encoding utf8
Write-CostEvent -Event 'dedicated-recovery-pods-stopped' -Fields @{
    pod_count = $dedicatedStops.Count
}

$auditTerminal = Join-Path `
    $repository `
    'benchmark\datasets\private\runpod-2026-08-04\stratified-audit-results-r1\terminal-receipt.json'
Wait-ForFile -Path $auditTerminal -Event 'waiting-for-stratified-audit'
$audit = Get-Content -Raw -LiteralPath $auditTerminal | ConvertFrom-Json
if (
    $audit.schema -ne 'folynta.public-core-stratified-audit-campaign.v1' -or
    [int]$audit.input_count_per_repeat -ne 384 -or
    [int]$audit.repeat_count -ne 3 -or
    [int]$audit.inference_count -ne 1152 -or
    [int]$audit.suite_count -ne 3
) {
    throw 'Stratified audit evidence gate failed before cost cleanup'
}
# The audit pool is whatever the pool controller actually validated, which is not
# always the three Pods this phase was first written against: a Pod stranded by
# provider capacity gets replaced by a freshly created one under a new id. Read
# the pool receipt so a replacement Pod is stopped instead of being left running
# and billing after "cleanup" reported success.
$poolReceiptPath = Join-Path `
    $generated 'folynta-post-baseline-mineru-pool-2026-08-05\pool-receipt.json'
$poolTargets = @()
if (Test-Path -LiteralPath $poolReceiptPath) {
    $poolPayload = Get-Content -Raw -LiteralPath $poolReceiptPath | ConvertFrom-Json
    foreach ($worker in @($poolPayload.workers)) {
        $poolTargets += [ordered]@{
            pod_id = [string]$worker.pod_id
            name = [string]$worker.name
        }
    }
}
# Pods named in the original phase plan are still stopped even when they never
# joined the validated pool, so a stranded Pod cannot be silently forgotten.
foreach ($legacy in @(
        [ordered]@{ pod_id = 'p2tvagqhw6almp'; name = 'folynta-mineru344-worker-1' },
        [ordered]@{ pod_id = '12lbrsp8nz0oie'; name = 'folynta-mineru344-worker-2' },
        [ordered]@{ pod_id = 'nut7g2azdnrtm6'; name = 'folynta-mineru344-qualification-r1' }
    )) {
    if (-not @($poolTargets | Where-Object { $_.pod_id -eq $legacy.pod_id }).Count) {
        $poolTargets += $legacy
    }
}
if (-not $poolTargets.Count) { throw 'Stratified audit pool has no Pods to stop' }
$poolStops = @(
    foreach ($target in $poolTargets) {
        Stop-VerifiedPod -PodId ([string]$target.pod_id) `
            -ExpectedName ([string]$target.name) `
            -Phase 'stratified-audit-complete'
    }
)
$poolReceipt = Join-Path $controllerRoot 'mineru-pool-stop-receipt.json'
[ordered]@{
    schema = 'folynta.phase-cost-cleanup.v1'
    phase = 'stratified-audit-complete'
    evidence_sha256 = 'sha256:' + (Get-Sha256Hex -Path $auditTerminal)
    pods = $poolStops
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $poolReceipt -Encoding utf8
Write-CostEvent -Event 'mineru-audit-pool-stopped' -Fields @{
    pod_count = $poolStops.Count
}

# A stopped-Pod tally alone cannot prove the phase left nothing billing, because
# the campaign can acquire Pods this script was never told about. Ask the
# provider directly instead.
$providerResponse = Invoke-RestMethod -Method Get `
    -Uri 'https://rest.runpod.io/v1/pods' -Headers $headers -TimeoutSec 30
$providerPods = @($providerResponse | ForEach-Object { $_ })
$stillRunning = @(
    $providerPods | Where-Object {
        [string]$_.name -like 'folynta-*' -and [string]$_.desiredStatus -eq 'RUNNING'
    }
)
Write-CostEvent -Event 'provider-running-pod-survey' -Fields @{
    remaining_running_pod_count = $stillRunning.Count
    remaining_running_pod_ids = @($stillRunning | ForEach-Object { [string]$_.id })
}

$payload = [ordered]@{
    schema = 'folynta.phase-cost-cleanup-terminal.v1'
    status = 'phase_pods_stopped_after_verified_evidence'
    dedicated_stop_receipt = $dedicatedReceipt
    mineru_pool_stop_receipt = $poolReceipt
    stopped_pod_count = $dedicatedStops.Count + $poolStops.Count
    remaining_running_pod_count = $stillRunning.Count
    remaining_running_pod_ids = @($stillRunning | ForEach-Object { [string]$_.id })
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $terminal -Encoding utf8
Write-CostEvent -Event 'phase-cost-cleanup-complete'
$apiKey = $null
exit 0
