param(
    [Parameter(Mandatory = $true)] [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)] [string]$CredentialFile,
    [Parameter(Mandatory = $true)] [string]$DeadlineUtc,
    [int]$PollSeconds = 60
)

$ErrorActionPreference = 'Stop'
if ($PollSeconds -lt 30 -or $PollSeconds -gt 300) {
    throw 'PollSeconds is invalid'
}
$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$credential = [IO.Path]::GetFullPath($CredentialFile)
$deadline = [DateTimeOffset]::Parse($DeadlineUtc).ToUniversalTime()
Set-Location -LiteralPath $repository
$generated = Join-Path $repository 'benchmark\reports\generated'
$controllerRoot = Join-Path `
    $generated `
    'folynta-runpod-campaign-cleanup-2026-08-04'
$progress = Join-Path $controllerRoot 'progress.jsonl'
$cleanupReceipt = Join-Path $controllerRoot 'pod-deletion-receipt.json'
$packageReceipt = Join-Path $controllerRoot 'review-package-receipt.json'
$terminalReceipt = Join-Path $controllerRoot 'terminal-receipt.json'
$null = New-Item -ItemType Directory -Path $controllerRoot -Force

function Write-FinalEvent {
    param([string]$Event, [hashtable]$Fields = @{})
    $payload = [ordered]@{
        event = $Event
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    foreach ($name in $Fields.Keys) { $payload[$name] = $Fields[$name] }
    Add-Content `
        -LiteralPath $progress `
        -Value ($payload | ConvertTo-Json -Compress -Depth 10) `
        -Encoding utf8
}

$alternateTerminal = Join-Path `
    $generated `
    'folynta-alternate-recovery-controller-2026-08-04\terminal-receipt.json'
$auditTerminal = Join-Path `
    $generated `
    'folynta-stratified-audit-evaluation-controller-2026-08-04\terminal-receipt.json'
$detectionReport = Join-Path `
    $generated `
    'folynta-operational-detection-evaluation-2026-08-04\operational-detection-evaluation.json'
$paddleTerminal = Join-Path `
    $generated `
    'folynta-paddle-recovery-bootstrap-2026-08-04\terminal-receipt.json'
$deepseekTerminal = Join-Path `
    $generated `
    'folynta-deepseek-recovery-bootstrap-2026-08-04\terminal-receipt.json'
$operationalTerminal = Join-Path `
    $generated `
    'runpod-operational-retry-monitor-2026-08-04\terminal-receipt.json'
$required = @(
    $alternateTerminal,
    $auditTerminal,
    $detectionReport,
    $paddleTerminal,
    $deepseekTerminal,
    $operationalTerminal
)
Write-FinalEvent -Event 'waiting-for-all-campaign-evidence'
while (@($required | Where-Object { -not (Test-Path -LiteralPath $_) }).Count -gt 0) {
    if ([DateTimeOffset]::UtcNow -ge $deadline) {
        throw 'Final campaign controller deadline reached before evidence completion'
    }
    Start-Sleep -Seconds $PollSeconds
}
$alternate = Get-Content -Raw -LiteralPath $alternateTerminal | ConvertFrom-Json
$audit = Get-Content -Raw -LiteralPath $auditTerminal | ConvertFrom-Json
$operational = Get-Content -Raw -LiteralPath $operationalTerminal | ConvertFrom-Json
if ($alternate.status -ne 'alternate_recovery_officially_selected') {
    throw 'Alternate recovery terminal status is invalid'
}
if ($audit.status -ne 'official_three_repeat_audit_complete') {
    throw 'Audit terminal status is invalid'
}
if ($operational.status -ne 'merged_complete' -or [int]$operational.unresolved -ne 0) {
    throw 'Operational retry did not resolve every input'
}
Write-FinalEvent -Event 'all-campaign-evidence-complete'

$inventory = Join-Path `
    $generated `
    'folynta-runpod-all-pod-inventory-live-r1-2026-08-04.json'
$costSnapshot = Join-Path `
    $generated `
    'folynta-runpod-cost-snapshot-final-2026-08-04.json'
if (-not (Test-Path -LiteralPath $costSnapshot)) {
    & (Join-Path $repository 'tools\release\snapshot_folynta_runpod_cost.ps1') `
        -CredentialFile $credential `
        -InventoryFile $inventory `
        -ReceiptOut $costSnapshot `
        -ApprovedCapUsd 400 2>&1 | ForEach-Object {
            Write-FinalEvent -Event 'cost-snapshot-output' -Fields @{ line = [string]$_ }
        }
}
$cost = Get-Content -Raw -LiteralPath $costSnapshot | ConvertFrom-Json
if ($cost.within_approved_cap -ne $true) { throw 'Approved RunPod cost cap exceeded' }
Write-FinalEvent `
    -Event 'final-cost-snapshot-complete' `
    -Fields @{ total_usd = [double]$cost.total_runtime_rate_estimate_usd }

$reportJson = Join-Path `
    $generated `
    'folynta-public-benchmark-recovery-final-2026-08-04.json'
$reportMarkdown = Join-Path `
    $generated `
    'FOLYNTA_PUBLIC_BENCHMARK_RECOVERY_FINAL_REPORT_2026-08-04.md'
$python = Join-Path $repository '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $reportJson)) {
    & $python `
        (Join-Path $repository 'benchmark\runpod_eval\build_public_benchmark_final_report.py') `
        --repository-root $repository `
        --alternate-terminal $alternateTerminal `
        --audit-terminal $auditTerminal `
        --detection-report $detectionReport `
        --cost-snapshot $costSnapshot `
        --output-json $reportJson `
        --output-markdown $reportMarkdown 2>&1 | ForEach-Object {
            Write-FinalEvent -Event 'final-report-output' -Fields @{ line = [string]$_ }
        }
    if ($LASTEXITCODE -ne 0) { throw 'Final campaign report failed' }
}
Write-FinalEvent -Event 'final-report-complete'

$patentIndexJson = Join-Path `
    $generated `
    'folynta-patent-technical-evidence-index-2026-08-04.json'
$patentIndexMarkdown = Join-Path `
    $generated `
    'FOLYNTA_PATENT_TECHNICAL_EVIDENCE_INDEX_2026-08-04.md'
if (-not (Test-Path -LiteralPath $patentIndexJson)) {
    & $python `
        (Join-Path $repository 'benchmark\runpod_eval\build_patent_evidence_index.py') `
        --repository-root $repository `
        --final-report $reportJson `
        --output-json $patentIndexJson `
        --output-markdown $patentIndexMarkdown 2>&1 | ForEach-Object {
            Write-FinalEvent -Event 'patent-evidence-index-output' -Fields @{ line = [string]$_ }
        }
    if ($LASTEXITCODE -ne 0) { throw 'Patent technical evidence index failed' }
}
Write-FinalEvent -Event 'patent-evidence-index-complete'

$ruffLog = Join-Path $controllerRoot 'ruff-final.log'
$pytestLog = Join-Path $controllerRoot 'pytest-final.log'
& $python -m ruff check benchmark/runpod_eval tools/release 2>&1 |
    Set-Content -LiteralPath $ruffLog -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw 'Final Ruff validation failed' }
& $python -m pytest benchmark/runpod_eval -q 2>&1 |
    Set-Content -LiteralPath $pytestLog -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw 'Final benchmark test suite failed' }
Write-FinalEvent -Event 'final-local-validation-complete'

if (-not (Test-Path -LiteralPath $cleanupReceipt)) {
    $inventoryPayload = Get-Content -Raw -LiteralPath $inventory | ConvertFrom-Json
    $pods = @($inventoryPayload.pods)
    $ids = @($pods | ForEach-Object { [string]$_.pod_id })
    $expectedPodCount = [int]$inventoryPayload.pod_count
    if (
        $expectedPodCount -lt 6 -or
        $ids.Count -ne $expectedPodCount -or
        @($ids | Select-Object -Unique).Count -ne $expectedPodCount
    ) {
        throw 'Cleanup inventory Pod count or identity coverage is invalid'
    }
    if (@($ids | Where-Object { $_ -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$' }).Count) {
        throw 'Cleanup inventory contains an invalid Pod id'
    }
    $line = Get-Content -LiteralPath $credential |
        Where-Object { $_ -match '^\s*Runpod\s*:' } |
        Select-Object -First 1
    if (-not $line) { throw 'RunPod credential label not found' }
    $apiKey = ($line -split ':', 2)[1].Trim()
    if (-not $apiKey -or $apiKey -match '\s') { throw 'RunPod credential malformed' }
    $headers = @{ Authorization = "Bearer $apiKey"; Accept = 'application/json' }
    $deletions = @()
    foreach ($podId in $ids) {
        $uri = "https://rest.runpod.io/v1/pods/$podId"
        $wasPresent = $true
        try {
            $pod = Invoke-RestMethod -Method Get -Uri $uri -Headers $headers -TimeoutSec 30
            if ([string]$pod.id -ne $podId) { throw 'Provider Pod identity mismatch' }
        }
        catch {
            $statusCode = $_.Exception.Response.StatusCode.value__
            if ($statusCode -eq 404) { $wasPresent = $false } else { throw }
        }
        if ($wasPresent) {
            $null = Invoke-RestMethod `
                -Method Delete `
                -Uri $uri `
                -Headers $headers `
                -TimeoutSec 30
        }
        $absent = $false
        for ($attempt = 1; $attempt -le 20; $attempt++) {
            try {
                $null = Invoke-RestMethod `
                    -Method Get `
                    -Uri $uri `
                    -Headers $headers `
                    -TimeoutSec 30
            }
            catch {
                if ($_.Exception.Response.StatusCode.value__ -eq 404) {
                    $absent = $true
                    break
                }
            }
            Start-Sleep -Seconds 10
        }
        if (-not $absent) { throw "Provider absence was not verified for $podId" }
        $deletions += [ordered]@{
            pod_id = $podId
            was_present_before_delete = $wasPresent
            provider_absent_verified = $true
            observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        }
        Write-FinalEvent -Event 'pod-provider-absence-verified' -Fields @{ pod_id = $podId }
    }
    $cleanup = [ordered]@{
        schema = 'folynta.runpod-campaign-cleanup.v1'
        pod_count = $expectedPodCount
        all_provider_absent = $true
        pods = $deletions
        completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    $cleanup | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath $cleanupReceipt -Encoding utf8
}
Write-FinalEvent -Event 'all-runpod-resources-deleted'

$reviewZip = Join-Path `
    $generated `
    'FOLYNTA_PUBLIC_BENCHMARK_RECOVERY_REVIEW_EVIDENCE_2026-08-04.zip'
if (-not (Test-Path -LiteralPath $reviewZip)) {
    & $python `
        (Join-Path $repository 'benchmark\runpod_eval\package_public_benchmark_review.py') `
        --repository-root $repository `
        --output-zip $reviewZip `
        --receipt $packageReceipt 2>&1 | ForEach-Object {
            Write-FinalEvent -Event 'review-package-output' -Fields @{ line = [string]$_ }
        }
    if ($LASTEXITCODE -ne 0) { throw 'Review evidence package failed' }
}
$package = Get-Content -Raw -LiteralPath $packageReceipt | ConvertFrom-Json
$finalReport = Get-Content -Raw -LiteralPath $reportJson | ConvertFrom-Json
$cleanupPayload = Get-Content -Raw -LiteralPath $cleanupReceipt | ConvertFrom-Json
$campaignStarted = [DateTimeOffset]::Parse(
    [string]$finalReport.timing.campaign_started_at_utc
).ToUniversalTime()
$completedAt = [DateTimeOffset]::UtcNow
$terminal = [ordered]@{
    schema = 'folynta.public-benchmark-campaign-finalizer-terminal.v1'
    status = 'complete_cost_bounded_packaged_and_resources_deleted'
    report_json = $reportJson
    report_markdown = $reportMarkdown
    patent_evidence_index_json = $patentIndexJson
    patent_evidence_index_markdown = $patentIndexMarkdown
    review_zip = $reviewZip
    review_zip_sha256 = $package.zip_sha256
    cost_snapshot = $costSnapshot
    total_runtime_rate_estimate_usd = [double]$cost.total_runtime_rate_estimate_usd
    cleanup_receipt = $cleanupReceipt
    deleted_pod_count = [int]$cleanupPayload.pod_count
    campaign_started_at_utc = $campaignStarted.ToString('o')
    cleanup_completed_at_utc = [string]$cleanupPayload.completed_at_utc
    elapsed_seconds_through_cleanup = ($completedAt - $campaignStarted).TotalSeconds
    elapsed_hours_through_cleanup = ($completedAt - $campaignStarted).TotalHours
    completed_at_utc = $completedAt.ToString('o')
}
$terminal | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $terminalReceipt -Encoding utf8
Write-FinalEvent -Event 'campaign-finalizer-complete'
exit 0
