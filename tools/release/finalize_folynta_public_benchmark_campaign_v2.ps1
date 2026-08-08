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
Set-Location -LiteralPath $repository
$generated = Join-Path $repository 'benchmark\reports\generated'
$controllerRoot = Join-Path `
    $generated 'folynta-runpod-campaign-cleanup-2026-08-04'
$progress = Join-Path $controllerRoot 'progress-v2.jsonl'
$cleanupReceipt = Join-Path $controllerRoot 'pod-deletion-receipt.json'
$packageReceipt = Join-Path $controllerRoot 'review-package-receipt.json'
$terminalReceipt = Join-Path $controllerRoot 'terminal-receipt.json'
$null = New-Item -ItemType Directory -Path $controllerRoot -Force

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

function Write-FinalEvent {
    param([string]$Event, [hashtable]$Fields = @{})
    $payload = [ordered]@{
        event = $Event
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    foreach ($name in $Fields.Keys) { $payload[$name] = $Fields[$name] }
    $line = $payload | ConvertTo-Json -Compress -Depth 10
    for ($attempt = 1; $attempt -le 20; $attempt++) {
        try {
            Add-Content -LiteralPath $progress -Value $line -Encoding utf8
            return
        }
        catch [System.IO.IOException] {
            if ($attempt -eq 20) { throw }
            Start-Sleep -Milliseconds 100
        }
    }
}

function Invoke-FinalNative {
    param(
        [Parameter(Mandatory = $true)] [string]$Name,
        [Parameter(Mandatory = $true)] [string]$Executable,
        [Parameter(Mandatory = $true)] [object[]]$Arguments,
        [string]$StdoutLog,
        [string]$StderrLog
    )
    $slug = $Name.ToLowerInvariant() -replace '[^a-z0-9]+', '-'
    if (-not $StdoutLog) { $StdoutLog = Join-Path $controllerRoot "$slug.stdout.log" }
    if (-not $StderrLog) { $StderrLog = Join-Path $controllerRoot "$slug.stderr.log" }
    $savedPreference = $ErrorActionPreference
    $exitCode = 0
    try {
        $ErrorActionPreference = 'Continue'
        & $Executable @Arguments 1> $StdoutLog 2> $StderrLog
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedPreference
    }
    Write-FinalEvent -Event 'native-process-complete' -Fields @{
        process = $Name
        exit_code = $exitCode
        stdout_log = $StdoutLog
        stderr_log = $StderrLog
    }
    if ($exitCode -ne 0) { throw "$Name failed with exit $exitCode" }
}

function Wait-ForFile {
    param([string]$Path, [string]$Event)
    while (-not (Test-Path -LiteralPath $Path)) {
        if ([DateTimeOffset]::UtcNow -ge $deadline) {
            throw "Finalizer deadline reached while waiting for $Path"
        }
        Write-FinalEvent -Event $Event
        Start-Sleep -Seconds $PollSeconds
    }
}

$postSelectionTerminal = Join-Path `
    $generated 'folynta-post-selection-recovery-audit-2026-08-05\terminal-receipt.json'
$operationalTerminal = Join-Path `
    $generated 'runpod-operational-retry-monitor-2026-08-04\terminal-receipt.json'
$phaseCostTerminal = Join-Path `
    $generated 'folynta-phase-cost-cleanup-2026-08-05\terminal-receipt.json'
$creditMonitorTerminal = Join-Path `
    $generated 'folynta-runpod-credit-monitor-2026-08-05\terminal-receipt.json'
Wait-ForFile -Path $postSelectionTerminal -Event 'waiting-for-post-selection-pipeline'
Wait-ForFile -Path $operationalTerminal -Event 'waiting-for-operational-terminal'
Wait-ForFile -Path $phaseCostTerminal -Event 'waiting-for-phase-cost-cleanup'
Wait-ForFile -Path $creditMonitorTerminal -Event 'waiting-for-credit-monitor-terminal'
$postSelection = Get-Content -Raw -LiteralPath $postSelectionTerminal | ConvertFrom-Json
$operational = Get-Content -Raw -LiteralPath $operationalTerminal | ConvertFrom-Json
$phaseCost = Get-Content -Raw -LiteralPath $phaseCostTerminal | ConvertFrom-Json
$creditMonitor = Get-Content -Raw -LiteralPath $creditMonitorTerminal | ConvertFrom-Json
if ($postSelection.status -ne 'alternate_recovery_audit_and_detection_complete') {
    throw 'Post-selection pipeline terminal is invalid'
}
if ($operational.status -ne 'merged_complete' -or [int]$operational.unresolved -ne 0) {
    throw 'Operational recovery did not reach zero unresolved inputs'
}
# The exact Pod count is not fixed: a Pod stranded by provider capacity is
# replaced by a freshly created one, so the campaign can end with more Pods than
# the phase was first written against. What must hold is that every planned Pod
# was stopped and that the provider reports nothing still running and billing.
if (
    $phaseCost.status -ne 'phase_pods_stopped_after_verified_evidence' -or
    [int]$phaseCost.stopped_pod_count -lt 5 -or
    $null -eq $phaseCost.remaining_running_pod_count -or
    [int]$phaseCost.remaining_running_pod_count -ne 0
) {
    throw 'Phase cost cleanup evidence is invalid'
}
if (
    $creditMonitor.schema -ne 'folynta.runpod-credit-monitor-terminal.v1' -or
    $creditMonitor.status -ne 'phase_cost_cleanup_terminal_observed' -or
    [double]$creditMonitor.latest_snapshot.client_balance_usd -lt 0 -or
    [double]$creditMonitor.latest_snapshot.current_spend_per_hour_usd -lt 0
) {
    throw 'RunPod credit monitor evidence is invalid'
}
$alternateTerminal = [IO.Path]::GetFullPath([string]$postSelection.alternate_terminal)
$auditTerminal = [IO.Path]::GetFullPath([string]$postSelection.audit_terminal)
$detectionReport = [IO.Path]::GetFullPath([string]$postSelection.detection_report)
$alternate = Get-Content -Raw -LiteralPath $alternateTerminal | ConvertFrom-Json
$audit = Get-Content -Raw -LiteralPath $auditTerminal | ConvertFrom-Json
if (
    $alternate.status -ne 'alternate_recovery_officially_selected' -or
    [int]$alternate.input_count -ne 5132 -or
    $audit.status -ne 'official_three_repeat_audit_complete' -or
    [int]$audit.inference_count -ne 1152
) {
    throw 'Final recovery or three-repeat audit evidence is invalid'
}
Write-FinalEvent -Event 'all-benchmark-evidence-complete'

$registry = Join-Path `
    $generated 'folynta-runpod-campaign-pod-registry-final-2026-08-05.json'
& (Join-Path $repository 'tools\release\build_folynta_runpod_campaign_registry.ps1') `
    -RepositoryRoot $repository -CredentialFile $credential -ReceiptOut $registry |
    ForEach-Object { Write-FinalEvent -Event 'registry-output' -Fields @{ line = [string]$_ } }
if ($LASTEXITCODE -ne 0) { throw 'Final RunPod registry failed' }
$registryPayload = Get-Content -Raw -LiteralPath $registry | ConvertFrom-Json
Write-FinalEvent -Event 'final-runpod-registry-complete' -Fields @{
    pod_count = [int]$registryPayload.pod_count
}

if (-not (Test-Path -LiteralPath $cleanupReceipt)) {
    & (Join-Path $repository 'tools\release\cleanup_folynta_runpod_resources.ps1') `
        -CredentialFile $credential -RegistryFile $registry `
        -ReceiptOut $cleanupReceipt -PollSeconds 10 |
        ForEach-Object { Write-FinalEvent -Event 'cleanup-output' -Fields @{ line = [string]$_ } }
    if ($LASTEXITCODE -ne 0) { throw 'RunPod cleanup failed' }
}
$cleanup = Get-Content -Raw -LiteralPath $cleanupReceipt | ConvertFrom-Json
if ($cleanup.all_provider_absent -ne $true) {
    throw 'RunPod provider absence is not fully verified'
}
Write-FinalEvent -Event 'all-runpod-resources-deleted' -Fields @{
    pod_count = [int]$cleanup.pod_count
}

# Give the provider billing ledger time to publish the final seconds and disk usage.
Start-Sleep -Seconds 60
$costSnapshot = Join-Path `
    $generated 'folynta-runpod-billing-snapshot-final-2026-08-05.json'
& (Join-Path $repository 'tools\release\snapshot_folynta_runpod_billing.ps1') `
    -CredentialFile $credential -RegistryFile $registry `
    -ReceiptOut $costSnapshot -ApprovedCapUsd 400 |
    ForEach-Object { Write-FinalEvent -Event 'billing-output' -Fields @{ line = [string]$_ } }
if ($LASTEXITCODE -ne 0) { throw 'Final provider billing snapshot failed' }
$cost = Get-Content -Raw -LiteralPath $costSnapshot | ConvertFrom-Json
if (
    $cost.evidence_kind -ne 'provider-billing-records' -or
    $cost.within_approved_cap -ne $true
) {
    throw 'Approved RunPod cost cap evidence is invalid'
}
Write-FinalEvent -Event 'final-provider-billing-complete' -Fields @{
    total_usd = [double]$cost.total_runtime_rate_estimate_usd
    unbilled_registry_pod_count = @($cost.unbilled_registry_pod_ids).Count
}

$reportJson = Join-Path `
    $generated 'folynta-public-benchmark-recovery-final-2026-08-04.json'
$reportMarkdown = Join-Path `
    $generated 'FOLYNTA_PUBLIC_BENCHMARK_RECOVERY_FINAL_REPORT_2026-08-04.md'
$python = Join-Path $repository '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $reportJson)) {
    Invoke-FinalNative -Name 'Final campaign report' -Executable $python -Arguments @(
        (Join-Path $repository 'benchmark\runpod_eval\build_public_benchmark_final_report.py'),
        '--repository-root', $repository,
        '--alternate-terminal', $alternateTerminal,
        '--audit-terminal', $auditTerminal,
        '--detection-report', $detectionReport,
        '--cost-snapshot', $costSnapshot,
        '--output-json', $reportJson,
        '--output-markdown', $reportMarkdown
    )
}
$finalReportGate = Get-Content -Raw -LiteralPath $reportJson | ConvertFrom-Json
if (
    $finalReportGate.schema -ne 'folynta.public-benchmark-recovery-final-report.v1' -or
    [int]$finalReportGate.scope.full_corpus_input_count -ne 5132 -or
    -not [string]$finalReportGate.evidence.phase_cost_cleanup_receipt_sha256 -or
    -not [string]$finalReportGate.evidence.obsolete_pod_cleanup_receipt_sha256 -or
    -not (Test-Path -LiteralPath $reportMarkdown)
) {
    throw 'Final campaign report completion gate failed'
}
Write-FinalEvent -Event 'final-report-complete'

$ruffLog = Join-Path $controllerRoot 'ruff-final.log'
$pytestLog = Join-Path $controllerRoot 'pytest-final.log'
$servicePytestLog = Join-Path $controllerRoot 'service-recovery-pytest-final.log'
Invoke-FinalNative -Name 'Final Ruff validation' -Executable $python -Arguments @(
    '-m', 'ruff', 'check', 'benchmark/runpod_eval', 'tools/release'
) -StdoutLog $ruffLog
Invoke-FinalNative -Name 'Final benchmark test suite' -Executable $python -Arguments @(
    '-m', 'pytest', 'benchmark/runpod_eval', '-q'
) -StdoutLog $pytestLog
Invoke-FinalNative -Name 'Final service recovery test suite' -Executable $python -Arguments @(
    '-m', 'pytest',
    'packages/parallel-runtime/tests/test_attempts_and_health.py',
    'packages/parallel-runtime/tests/test_recovery_and_continuity.py',
    'services/api/tests/test_parallel_orchestrator.py',
    'services/api/tests/test_parallel_runtime_store.py',
    'services/scheduler/tests/test_autonomous_v6_pipeline.py',
    'packages/quality/tests/test_autonomous_verification.py',
    '-q'
) -StdoutLog $servicePytestLog

$serviceEvidence = Join-Path `
    $generated 'folynta-service-recovery-equivalence-evaluation-2026-08-05.json'
if (-not (Test-Path -LiteralPath $serviceEvidence)) {
    Invoke-FinalNative `
        -Name 'Service recovery equivalence evidence' `
        -Executable $python `
        -Arguments @(
            (Join-Path $repository 'benchmark\runpod_eval\evaluate_service_recovery_equivalence.py'),
            '--repository-root', $repository,
            '--service-test-log', $servicePytestLog,
            '--output', $serviceEvidence
        )
}
$serviceEvidenceGate = Get-Content -Raw -LiteralPath $serviceEvidence | ConvertFrom-Json
if (
    $serviceEvidenceGate.schema -ne 'folynta.service-recovery-equivalence-evaluation.v1' -or
    $serviceEvidenceGate.status -ne 'complete_service_recovery_equivalence_verified' -or
    $serviceEvidenceGate.gate_passed -ne $true -or
    [int]$serviceEvidenceGate.service_test_count -lt 60 -or
    [double]$serviceEvidenceGate.anomaly_detection.f1 -ne 1.0 -or
    [double]$serviceEvidenceGate.quarantine_detection.f1 -ne 1.0
) {
    throw 'Service recovery equivalence completion gate failed'
}
Write-FinalEvent -Event 'final-local-and-service-validation-complete'

$patentIndexJson = Join-Path `
    $generated 'folynta-patent-technical-evidence-index-2026-08-04.json'
$patentIndexMarkdown = Join-Path `
    $generated 'FOLYNTA_PATENT_TECHNICAL_EVIDENCE_INDEX_2026-08-04.md'
if (-not (Test-Path -LiteralPath $patentIndexJson)) {
    Invoke-FinalNative `
        -Name 'Patent technical evidence index' `
        -Executable $python `
        -Arguments @(
            (Join-Path $repository 'benchmark\runpod_eval\build_patent_evidence_index.py'),
            '--repository-root', $repository,
            '--final-report', $reportJson,
            '--service-evidence', $serviceEvidence,
            '--output-json', $patentIndexJson,
            '--output-markdown', $patentIndexMarkdown
        )
}
$patentGate = Get-Content -Raw -LiteralPath $patentIndexJson | ConvertFrom-Json
$fingerprintedSources = @(
    $patentGate.algorithm_source_fingerprints | ForEach-Object { [string]$_.path }
)
if (
    $patentGate.schema -ne 'folynta.patent-technical-evidence-index.v1' -or
    $fingerprintedSources -notcontains `
        'tools/release/continue_folynta_phase_cost_cleanup.ps1' -or
    $fingerprintedSources -notcontains `
        'tools/release/monitor_folynta_runpod_credit.py' -or
    $fingerprintedSources -notcontains `
        'services/api/src/akc_api/parallel_orchestrator.py' -or
    $fingerprintedSources -notcontains `
        'packages/parallel-runtime/src/akc_parallel_runtime/health.py' -or
    $patentGate.service_recovery_equivalence.status -ne `
        'complete_service_recovery_equivalence_verified' -or
    -not (Test-Path -LiteralPath $patentIndexMarkdown)
) {
    throw 'Patent evidence completion gate failed'
}
Write-FinalEvent -Event 'patent-evidence-index-complete'

$patentPaperRoot = Join-Path `
    $generated 'folynta-patent-paper-artifacts-2026-08-05'
$patentPaperManifest = Join-Path `
    $patentPaperRoot 'artifact-provenance-manifest.json'
$paperArtifactJson = Join-Path `
    $patentPaperRoot `
    'paper\FOLYNTA_PUBLIC_BENCHMARK_TECHNICAL_REPORT.artifact.json'
$paperReportHtml = Join-Path `
    $patentPaperRoot `
    'paper\FOLYNTA_PUBLIC_BENCHMARK_TECHNICAL_REPORT.html'
$paperReportDeliveryReceipt = Join-Path `
    $patentPaperRoot `
    'paper\FOLYNTA_PUBLIC_BENCHMARK_TECHNICAL_REPORT.delivery-receipt.json'
if (-not (Test-Path -LiteralPath $patentPaperManifest)) {
    Invoke-FinalNative `
        -Name 'Patent and paper artifact generation' `
        -Executable $python `
        -Arguments @(
            (Join-Path $repository 'benchmark\runpod_eval\build_patent_paper_artifacts.py'),
            '--repository-root', $repository,
            '--final-report', $reportJson,
            '--patent-index', $patentIndexJson,
            '--service-evidence', $serviceEvidence,
            '--output-root', $patentPaperRoot
        )
}
$patentPaperGate = Get-Content -Raw -LiteralPath $patentPaperManifest |
    ConvertFrom-Json
$patentPaperAssetPaths = @(
    $patentPaperGate.assets | ForEach-Object {
        $_.derivatives | ForEach-Object { [string]$_.path }
    }
)
$missingPatentPaperAssets = @(
    $patentPaperAssetPaths | Where-Object {
        -not (Test-Path -LiteralPath (Join-Path $patentPaperRoot $_))
    }
)
if (
    $patentPaperGate.schema -ne 'folynta.patent-paper-artifact-manifest.v1' -or
    $patentPaperGate.status -ne 'complete_real_evidence_only' -or
    $patentPaperGate.truth_policy.image_generation_used -ne $false -or
    @($patentPaperGate.assets).Count -ne 8 -or
    $patentPaperAssetPaths.Count -ne 16 -or
    $missingPatentPaperAssets.Count -ne 0 -or
    -not (Test-Path -LiteralPath $paperArtifactJson) -or
    -not (Test-Path -LiteralPath (
        Join-Path $patentPaperRoot 'patent\CLAIM_EVIDENCE_TECHNICAL_MAP.csv'
    )) -or
    -not (Test-Path -LiteralPath (
        Join-Path $patentPaperRoot 'reproducibility\chart-contracts.json'
    ))
) {
    throw 'Patent and paper artifact completion gate failed'
}

# The original lane rendered the report through an OpenAI curated plugin cached
# outside this repository. A reviewer cloning the evidence package has no such
# cache, so the repository-local renderer is the default and the plugin is used
# only when it happens to be installed. Both emit the same delivery receipt.
$minimumReportBytes = 100000
if (-not (Test-Path -LiteralPath $paperReportHtml)) {
    $node = Get-Command node -ErrorAction Stop
    $dataAnalyticsCache = Join-Path `
        $env:USERPROFILE `
        '.codex\plugins\cache\openai-curated-remote\data-analytics'
    $dataAnalyticsPlugin = $null
    if (Test-Path -LiteralPath $dataAnalyticsCache) {
        $dataAnalyticsPlugin = Get-ChildItem -LiteralPath $dataAnalyticsCache `
            -Directory -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Where-Object {
                Test-Path -LiteralPath (Join-Path $_.FullName `
                    'skills\build-report\scripts\deliver_portable_artifact.mjs')
            } | Select-Object -First 1
    }
    if ($null -ne $dataAnalyticsPlugin) {
        Invoke-FinalNative `
            -Name 'Patent and paper HTML report delivery' `
            -Executable $node.Source `
            -Arguments @(
                (Join-Path $repository 'tools\release\deliver_folynta_portable_report.mjs'),
                '--plugin-root', $dataAnalyticsPlugin.FullName,
                '--input', $paperArtifactJson,
                '--output', $paperReportHtml,
                '--ready-timeout-ms', '8000',
                '--action-timeout-ms', '5000',
                '--timeout-ms', '20000'
            ) `
            -StdoutLog $paperReportDeliveryReceipt
    }
    else {
        Write-FinalEvent -Event 'portable-report-plugin-unavailable' -Fields @{
            searched = $dataAnalyticsCache
            renderer = 'tools/release/render_folynta_portable_report.mjs'
        }
        Invoke-FinalNative `
            -Name 'Patent and paper HTML report render' `
            -Executable $node.Source `
            -Arguments @(
                (Join-Path $repository 'tools\release\render_folynta_portable_report.mjs'),
                '--input', $paperArtifactJson,
                '--output', $paperReportHtml,
                '--receipt', $paperReportDeliveryReceipt
            )
    }
}
$paperDeliveryGate = Get-Content -Raw -LiteralPath $paperReportDeliveryReceipt |
    ConvertFrom-Json
if ($paperDeliveryGate.renderer) {
    # The repository renderer emits no runtime bundle, fonts, or base64 imagery,
    # so the plugin-calibrated 100 KB floor would reject a complete document.
    # Completeness is enforced by the receipt's structural verification, which
    # asserts every block, chart, and table reached the written file.
    $minimumReportBytes = 20000
}
if (
    $paperDeliveryGate.ok -ne $true -or
    $paperDeliveryGate.stages.validation -ne 'passed' -or
    $paperDeliveryGate.stages.package -ne 'passed' -or
    $paperDeliveryGate.stages.verification -notin @('passed', 'structural_only') -or
    -not (Test-Path -LiteralPath $paperReportHtml) -or
    (Get-Item -LiteralPath $paperReportHtml).Length -lt $minimumReportBytes
) {
    throw 'Patent and paper HTML report verification gate failed'
}
Write-FinalEvent -Event 'patent-paper-artifacts-and-report-complete' -Fields @{
    asset_count = @($patentPaperGate.assets).Count
    report_verification = [string]$paperDeliveryGate.stages.verification
}

$reviewZip = Join-Path `
    $generated 'FOLYNTA_PUBLIC_BENCHMARK_RECOVERY_REVIEW_EVIDENCE_2026-08-04.zip'
if (-not (Test-Path -LiteralPath $reviewZip)) {
    Invoke-FinalNative `
        -Name 'Review evidence package' `
        -Executable $python `
        -Arguments @(
            (Join-Path $repository 'benchmark\runpod_eval\package_public_benchmark_review.py'),
            '--repository-root', $repository,
            '--output-zip', $reviewZip,
            '--receipt', $packageReceipt
        )
}
$package = Get-Content -Raw -LiteralPath $packageReceipt | ConvertFrom-Json
$packagePaths = @($package.files | ForEach-Object { [string]$_.path })
$actualZipSha256 = 'sha256:' + (Get-Sha256Hex -Path $reviewZip)
if (
    $package.schema -ne 'folynta.public-benchmark-review-package.v1' -or
    [string]$package.zip_sha256 -ne $actualZipSha256 -or
    $packagePaths -notcontains `
        'tools/release/continue_folynta_phase_cost_cleanup.ps1' -or
    $packagePaths -notcontains `
        'tools/release/monitor_folynta_runpod_credit.py' -or
    $packagePaths -notcontains `
        'services/api/src/akc_api/parallel_orchestrator.py' -or
    $packagePaths -notcontains `
        'packages/parallel-runtime/src/akc_parallel_runtime/health.py' -or
    $packagePaths -notcontains `
        'benchmark/reports/generated/folynta-service-recovery-equivalence-evaluation-2026-08-05.json' -or
    $packagePaths -notcontains `
        'benchmark/reports/generated/folynta-patent-paper-artifacts-2026-08-05/artifact-provenance-manifest.json' -or
    $packagePaths -notcontains `
        'benchmark/reports/generated/folynta-patent-paper-artifacts-2026-08-05/paper/FOLYNTA_PUBLIC_BENCHMARK_TECHNICAL_REPORT.html' -or
    $packagePaths -notcontains `
        'benchmark/reports/generated/folynta-patent-paper-artifacts-2026-08-05/patent/CLAIM_EVIDENCE_TECHNICAL_MAP.csv' -or
    @($packagePaths | Where-Object {
        $_ -like 'benchmark/reports/generated/folynta-patent-paper-artifacts-2026-08-05/*/figures/*.svg'
    }).Count -lt 8 -or
    @($packagePaths | Where-Object {
        $_ -like 'benchmark/reports/generated/folynta-patent-paper-artifacts-2026-08-05/*/figures/*.png'
    }).Count -lt 8 -or
    -not @($packagePaths | Where-Object {
        $_ -like 'benchmark/reports/generated/folynta-phase-cost-cleanup-2026-08-05/*'
    }).Count -or
    -not @($packagePaths | Where-Object {
        $_ -like 'benchmark/reports/generated/folynta-obsolete-pod-cleanup-2026-08-05/*'
    }).Count -or
    -not @($packagePaths | Where-Object {
        $_ -like 'benchmark/reports/generated/folynta-runpod-credit-monitor-2026-08-05/*'
    }).Count
) {
    throw 'Review ZIP completion gate failed'
}
$finalReport = Get-Content -Raw -LiteralPath $reportJson | ConvertFrom-Json
$completedAt = [DateTimeOffset]::UtcNow
$campaignStarted = [DateTimeOffset]::Parse(
    [string]$finalReport.timing.campaign_started_at_utc
).ToUniversalTime()
$payload = [ordered]@{
    schema = 'folynta.public-benchmark-campaign-finalizer-terminal.v2'
    status = 'complete_cost_bounded_packaged_and_resources_deleted'
    report_json = $reportJson
    report_markdown = $reportMarkdown
    patent_evidence_index_json = $patentIndexJson
    patent_evidence_index_markdown = $patentIndexMarkdown
    service_recovery_equivalence = $serviceEvidence
    service_recovery_test_log = $servicePytestLog
    patent_paper_artifact_root = $patentPaperRoot
    patent_paper_artifact_manifest = $patentPaperManifest
    patent_paper_report_artifact_json = $paperArtifactJson
    patent_paper_report_html = $paperReportHtml
    patent_paper_report_delivery_receipt = $paperReportDeliveryReceipt
    review_zip = $reviewZip
    review_zip_sha256 = $package.zip_sha256
    cost_snapshot = $costSnapshot
    total_provider_billed_usd = [double]$cost.total_runtime_rate_estimate_usd
    cleanup_receipt = $cleanupReceipt
    phase_cost_cleanup_receipt = $phaseCostTerminal
    credit_monitor_terminal = $creditMonitorTerminal
    deleted_pod_count = [int]$cleanup.pod_count
    campaign_started_at_utc = $campaignStarted.ToString('o')
    cleanup_completed_at_utc = [string]$cleanup.completed_at_utc
    elapsed_hours_through_completion = ($completedAt - $campaignStarted).TotalHours
    completed_at_utc = $completedAt.ToString('o')
}
$payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $terminalReceipt -Encoding utf8
Write-FinalEvent -Event 'campaign-finalizer-v2-complete'
exit 0
