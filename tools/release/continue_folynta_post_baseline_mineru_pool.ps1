param(
    [Parameter(Mandatory = $true)] [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)] [string]$CredentialFile,
    [Parameter(Mandatory = $true)] [string]$DeadlineUtc,
    # Recorded folynta.recovery-execution-decision.v1 receipt. Absent means every
    # lane runs, which is the original behaviour.
    [string]$ExecutionDecision,
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
    throw 'Post-baseline deadline must be at least one hour in the future'
}
Set-Location -LiteralPath $repository
$privateRoot = Join-Path $repository 'benchmark\datasets\private\runpod-2026-08-04'
$generated = Join-Path $repository 'benchmark\reports\generated'
$controllerRoot = Join-Path $generated 'folynta-post-baseline-mineru-pool-2026-08-05'
$progress = Join-Path $controllerRoot 'progress.jsonl'
$terminalReceipt = Join-Path $controllerRoot 'terminal-receipt.json'
$poolConfig = Join-Path $privateRoot 'post-baseline-mineru-pool-workers.json'
$poolReceipt = Join-Path $controllerRoot 'pool-receipt.json'
$null = New-Item -ItemType Directory -Path $controllerRoot -Force

function Write-PoolEvent {
    param([string]$Event, [hashtable]$Fields = @{})
    $value = [ordered]@{
        event = $Event
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    foreach ($name in $Fields.Keys) { $value[$name] = $Fields[$name] }
    # The progress log is append-only and shared with sibling controllers and
    # with whatever is tailing it, so a transient sharing violation must not end
    # a campaign that is otherwise healthy. $ErrorActionPreference is Stop here,
    # which wraps the IOException in an ActionPreferenceStopException, so the
    # retry catches broadly and only rethrows once the file stays locked.
    $line = $value | ConvertTo-Json -Compress -Depth 10
    for ($attempt = 1; $attempt -le 40; $attempt++) {
        try {
            Add-Content -LiteralPath $progress -Value $line -Encoding utf8 -ErrorAction Stop
            return
        }
        catch {
            if ($attempt -eq 40) { throw }
            Start-Sleep -Milliseconds 250
        }
    }
}

function Wait-ForFile {
    param([string]$Path, [string]$Event)
    while (-not (Test-Path -LiteralPath $Path)) {
        if ([DateTimeOffset]::UtcNow -ge $deadline) {
            throw "Deadline reached while waiting for $Path"
        }
        Write-PoolEvent -Event $Event
        Start-Sleep -Seconds $PollSeconds
    }
}

function Get-FailureRecordSummary {
    param([string]$FailureRecords)
    # The record file reaches ~77 MB and ConvertFrom-Json materialises a
    # PSCustomObject per node, so the scalars come from the Python lane instead.
    $summarizer = Join-Path `
        $repository `
        'benchmark\runpod_eval\summarize_failure_records.py'
    $python = Join-Path $repository '.venv\Scripts\python.exe'
    $summaryJson = & $python $summarizer --failure-records $FailureRecords
    if ($LASTEXITCODE -ne 0) { throw 'Failure record summary failed' }
    $summary = $summaryJson | ConvertFrom-Json
    if ($summary.schema -ne 'folynta.public-failure-record-summary.v1') {
        throw 'Failure record summary schema is invalid'
    }
    return $summary
}

$officialTerminal = Join-Path `
    $generated 'folynta-official-evaluation-controller-2026-08-04\terminal-receipt.json'
Write-PoolEvent -Event 'waiting-for-official-evaluation'
Wait-ForFile -Path $officialTerminal -Event 'waiting-for-official-evaluation'
$official = Get-Content -Raw -LiteralPath $officialTerminal | ConvertFrom-Json
if ($official.status -notin @('quality_retry_staged', 'quality_retry_not_needed')) {
    throw "Official evaluation terminal is not ready: $($official.status)"
}
Write-PoolEvent -Event 'official-evaluation-observed' -Fields @{
    status = [string]$official.status
    recoverable_case_count = [int]$official.recoverable_case_count
}

$poolMappings = @(
    [ordered]@{ worker_index = 4; pod_id = 'p2tvagqhw6almp' },
    [ordered]@{ worker_index = 5; pod_id = '12lbrsp8nz0oie' },
    [ordered]@{ worker_index = 6; pod_id = 'nut7g2azdnrtm6' }
)
$provisionScript = Join-Path `
    $repository 'tools\release\provision_folynta_mineru_recovery_worker.ps1'

function Start-PoolWorker {
    param(
        [int]$Index,
        [string]$PodId,
        [string]$Slug,
        [string]$Name
    )
    $stateRoot = Join-Path $privateRoot $Slug
    $null = New-Item -ItemType Directory -Path $stateRoot -Force
    $stdout = Join-Path $stateRoot 'provision.stdout.log'
    $stderr = Join-Path $stateRoot 'provision.stderr.log'
    $arguments = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $provisionScript,
        '-RepositoryRoot', $repository,
        '-CredentialFile', $credential,
        '-DeadlineUtc', $deadline.ToString('o'),
        '-WorkerIndex', [string]$Index,
        '-Name', $Name,
        '-StateSlug', $Slug,
        '-PollSeconds', [string]([Math]::Max(10, [Math]::Min(120, $PollSeconds)))
    )
    # Omitting -ExistingPodId makes the provisioner adopt a Pod with this name or
    # create a fresh one, which is how a stranded Pod gets replaced.
    if ($PodId) { $arguments += @('-ExistingPodId', $PodId) }
    $child = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
        -WindowStyle Hidden -PassThru
    return [ordered]@{
        worker_index = $Index
        pod_id = $PodId
        slug = $Slug
        replacement = -not $PodId
        process_id = $child.Id
        receipt = Join-Path $stateRoot 'provisioning-receipt.json'
        stdout = $stdout
        stderr = $stderr
    }
}

function Get-PoolWorkerReceipt {
    # A replaced worker keeps its index but provisions under an "r" slug, so a
    # worker counts as provisioned when either slug produced a receipt.
    param([int]$Index)
    $candidates = @("mineru-post-baseline-worker-{0:d2}" -f $Index)
    for ($attempt = 1; $attempt -le 8; $attempt++) {
        $candidates += ("mineru-post-baseline-worker-{0:d2}r{1}" -f $Index, $attempt)
    }
    $candidates += ("mineru-post-baseline-worker-{0:d2}r" -f $Index)
    foreach ($candidate in $candidates) {
        $path = Join-Path $privateRoot "$candidate\provisioning-receipt.json"
        if (Test-Path -LiteralPath $path) { return $path }
    }
    return $null
}

$children = @()
foreach ($mapping in $poolMappings) {
    $index = [int]$mapping.worker_index
    $slug = "mineru-post-baseline-worker-{0:d2}" -f $index
    if (Get-PoolWorkerReceipt -Index $index) { continue }
    $child = Start-PoolWorker -Index $index -PodId ([string]$mapping.pod_id) `
        -Slug $slug -Name "folynta-mineru344-post-baseline-$index"
    $children += $child
    Write-PoolEvent -Event 'pool-worker-resume-started' -Fields @{
        worker_index = $index
        pod_id = [string]$mapping.pod_id
        process_id = [int]$child.process_id
    }
}

# A stopped Pod can lose its host GPUs to another tenant while it is EXITED, and
# RunPod then refuses to start it. That is provider capacity, not a defect in the
# campaign, so the stranded Pod is replaced once with a freshly provisioned one.
# The audit assigns one benchmark suite per Pod, so the pool only degrades below
# three workers when a replacement also fails, and never below two.
$MINIMUM_POOL_WORKERS = 2
# Provider GPU stock fluctuates, so a placement miss is retried rather than
# being treated as a permanent loss of the worker.
$MAXIMUM_REPLACEMENT_ATTEMPTS = 8
$unavailable = @()
$replaced = @()
$replacementAttempted = @()
$unavailableReceipt = Join-Path $controllerRoot 'pool-capacity-incident.json'

while ($true) {
    $unavailableIndices = @($unavailable | ForEach-Object { [int]$_.worker_index })
    $missing = @()
    foreach ($mapping in $poolMappings) {
        if ($unavailableIndices -contains [int]$mapping.worker_index) { continue }
        if (-not (Get-PoolWorkerReceipt -Index ([int]$mapping.worker_index))) {
            $missing += $mapping
        }
    }
    if (-not $missing.Count) { break }
    if ([DateTimeOffset]::UtcNow -ge $deadline) {
        throw 'Post-baseline MinerU pool provisioning exceeded its deadline'
    }
    foreach ($item in @($children)) {
        $index = [int]$item.worker_index
        if ($unavailableIndices -contains $index) { continue }
        # A child that already handed its worker to a replacement must not be
        # re-inspected, or the next poll would read its dead process again and
        # retire a worker that is provisioning normally.
        if ($item.retired) { continue }
        if (
            -not (Test-Path -LiteralPath $item.receipt) -and
            -not (Get-Process -Id ([int]$item.process_id) -ErrorAction SilentlyContinue)
        ) {
            $errorTail = if (Test-Path -LiteralPath $item.stderr) {
                (Get-Content -LiteralPath $item.stderr -Tail 80) -join "`n"
            }
            else { 'no stderr log' }
            Write-PoolEvent -Event 'pool-worker-resume-failed' -Fields @{
                worker_index = $index
                pod_id = [string]$item.pod_id
                stderr_tail = $errorTail
            }
            # Placement failures are transient: when provider GPU stock is Low a
            # created Pod never receives a public IP, but a later attempt lands
            # on a host that can offer one. One attempt was not enough, so keep
            # retrying within the controller deadline instead of writing the
            # worker off after a single miss.
            $attempts = @($replacementAttempted | Where-Object { $_ -eq $index }).Count
            if ($attempts -lt $MAXIMUM_REPLACEMENT_ATTEMPTS) {
                $replacementAttempted += $index
                $item['retired'] = $true
                $slug = "mineru-post-baseline-worker-{0:d2}r{1}" -f $index, ($attempts + 1)
                $replacementChild = Start-PoolWorker -Index $index -PodId '' `
                    -Slug $slug -Name "folynta-mineru344-post-baseline-$index-r$($attempts + 1)"
                $children += $replacementChild
                $replaced += [ordered]@{
                    worker_index = $index
                    stranded_pod_id = [string]$item.pod_id
                    replacement_slug = $slug
                    reason = 'provider_capacity_start_refused'
                    observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
                }
                Write-PoolEvent -Event 'pool-worker-replacement-started' -Fields @{
                    worker_index = $index
                    stranded_pod_id = [string]$item.pod_id
                    process_id = [int]$replacementChild.process_id
                }
                continue
            }
            $unavailable += [ordered]@{
                worker_index = $index
                pod_id = [string]$item.pod_id
                classification = 'provider_capacity_start_refused_and_replacement_failed'
                stderr_tail = $errorTail
                observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
            }
            $unavailableIndices = @($unavailable | ForEach-Object { [int]$_.worker_index })
        }
    }
    if (($poolMappings.Count - $unavailable.Count) -lt $MINIMUM_POOL_WORKERS) {
        throw (
            'Post-baseline MinerU pool has fewer than ' +
            "$MINIMUM_POOL_WORKERS startable Pods"
        )
    }
    Write-PoolEvent -Event 'pool-provisioning-poll' -Fields @{
        pending_worker_indices = @($missing | ForEach-Object { [int]$_.worker_index })
        unavailable_worker_indices = $unavailableIndices
    }
    Start-Sleep -Seconds $PollSeconds
}

if ($unavailable.Count -or $replaced.Count) {
    [ordered]@{
        schema = 'folynta.post-baseline-pool-capacity-incident.v1'
        status = if ($unavailable.Count) {
            'pool_reduced_by_provider_capacity'
        }
        else { 'pool_restored_by_replacement_pod' }
        requested_worker_count = $poolMappings.Count
        available_worker_count = $poolMappings.Count - $unavailable.Count
        minimum_worker_count = $MINIMUM_POOL_WORKERS
        replaced_workers = $replaced
        unavailable_workers = $unavailable
    } | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath $unavailableReceipt -Encoding utf8
    Write-PoolEvent -Event 'pool-capacity-incident-recorded' -Fields @{
        replaced_worker_indices = @($replaced | ForEach-Object { [int]$_.worker_index })
        unavailable_worker_indices = @($unavailable | ForEach-Object { [int]$_.worker_index })
        receipt = $unavailableReceipt
    }
}

$unavailableIndices = @($unavailable | ForEach-Object { [int]$_.worker_index })
$validated = @()
foreach ($mapping in $poolMappings) {
    $index = [int]$mapping.worker_index
    if ($unavailableIndices -contains $index) { continue }
    $receipt = Get-PoolWorkerReceipt -Index $index
    if (-not $receipt) { throw "Post-baseline MinerU worker $index has no receipt" }
    $worker = Get-Content -Raw -LiteralPath $receipt | ConvertFrom-Json
    if (
        $worker.status -ne 'ready_identity_bound_and_smoke_passed' -or
        [int]$worker.worker_index -ne $index -or
        [string]$worker.model_artifact_manifest_sha256 -ne `
            'sha256:1611a8892cc0e7e287d31c4a1b5af87652f0f6e4a3f80276b92b4c71f982de84'
    ) {
        throw "Post-baseline MinerU worker $index failed the identity gate"
    }
    $validated += $worker
}
if ($validated.Count -lt $MINIMUM_POOL_WORKERS) {
    throw "Post-baseline MinerU pool validated fewer than $MINIMUM_POOL_WORKERS workers"
}

$configWorkers = @($validated | ForEach-Object {
    [ordered]@{
        worker_index = [int]$_.worker_index
        host = [string]$_.host
        port = [int]$_.port
    }
})
$config = [ordered]@{
    workers = $configWorkers
    key = 'benchmark/datasets/private/runpod-2026-08-04/builder_ed25519'
    known_hosts = 'benchmark/datasets/private/runpod-2026-08-04/known_hosts'
    deadline_utc = $deadline.ToString('o')
}
$config | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $poolConfig -Encoding utf8
$pool = [ordered]@{
    schema = 'folynta.post-baseline-mineru-pool.v1'
    status = 'ready_identity_bound_and_smoke_passed_pool'
    worker_count = $validated.Count
    workers = $validated
    config = $poolConfig
    model_artifact_manifest_sha256 = 'sha256:1611a8892cc0e7e287d31c4a1b5af87652f0f6e4a3f80276b92b4c71f982de84'
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$pool | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $poolReceipt -Encoding utf8
Write-PoolEvent -Event 'post-baseline-mineru-pool-ready' -Fields @{
    worker_count = $validated.Count
}

$operationalTerminal = Join-Path `
    $generated 'runpod-operational-retry-monitor-2026-08-04\terminal-receipt.json'
$operational = Get-Content -Raw -LiteralPath $operationalTerminal | ConvertFrom-Json
if ($operational.status -ne 'merged_complete' -or [int]$operational.unresolved -ne 0) {
    throw 'Post-baseline controller requires complete operational recovery'
}
$baselineMerged = [string]$operational.merged_root
$round2Composite = Join-Path `
    $generated 'folynta-mineru344-public-core-composite-r2-2026-08-05'
$baselineComposite = if (Test-Path -LiteralPath $round2Composite) {
    $round2Composite
}
else {
    Join-Path $generated 'folynta-mineru344-public-core-composite-r1-2026-08-04'
}
$baselineEvaluation = Join-Path `
    $generated 'folynta-mineru344-public-core-official-evaluations-r1-2026-08-04'
$baselineFailures = Join-Path `
    $generated 'folynta-mineru344-public-failure-records-r1-2026-08-04.json'
$qualityStaging = Join-Path $privateRoot 'mineru-quality-retry-staging-r1'
$postTerminal = Join-Path `
    $generated 'folynta-post-mineru-selection-controller-2026-08-04\terminal-receipt.json'

$decision = $null
if ($ExecutionDecision) {
    $decisionPath = [IO.Path]::GetFullPath($ExecutionDecision)
    $decision = Get-Content -Raw -LiteralPath $decisionPath | ConvertFrom-Json
    if ($decision.schema -ne 'folynta.recovery-execution-decision.v1') {
        throw 'Recovery execution decision schema is invalid'
    }
    Write-PoolEvent -Event 'execution-decision-observed' -Fields @{
        decision = $decisionPath
        execute_mineru_quality_retry = [bool]$decision.execute_mineru_quality_retry
        decision_sha256 = [string]$decision.decision_sha256
    }
}
$qualityRetryDeclined = (
    $null -ne $decision -and $decision.execute_mineru_quality_retry -eq $false
)

if ($official.status -eq 'quality_retry_not_needed' -or $qualityRetryDeclined) {
    $failures = Get-FailureRecordSummary -FailureRecords $baselineFailures
    # A declined lane is recorded, never implied. The candidate scope stays in
    # the receipt so the final report can state exactly what was left unrun.
    $qualityExecution = if ($qualityRetryDeclined) {
        'staged_not_executed_by_recorded_decision'
    }
    else { 'not_needed_no_recoverable_case' }
    $post = [ordered]@{
        schema = 'folynta.post-mineru-selection-controller-terminal.v1'
        status = 'alternate_recovery_staged'
        input_count = 5132
        accepted_mineru_quality_case_count = 0
        reverted_mineru_regression_case_count = 0
        aggregate_metric_rollback = $false
        official_failure_record_count = [int]$failures.record_count
        recoverable_case_count = [int]$failures.recoverable_case_count
        mineru_quality_retry_execution = $qualityExecution
        mineru_quality_retry_candidate_case_count = [int]$failures.recoverable_case_count
        mineru_quality_retry_staging = if ($qualityRetryDeclined) { $qualityStaging } else { $null }
        execution_decision = if ($decision) { $decisionPath } else { $null }
        execution_decision_sha256 = if ($decision) { [string]$decision.decision_sha256 } else { $null }
        paddle_case_count = 0
        deepseek_case_count = 0
        composite_root = $baselineComposite
        merged_root = $baselineMerged
        evaluation_root = $baselineEvaluation
        failure_records = $baselineFailures
        paddle_staging = $null
        deepseek_staging = $null
        completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    $null = New-Item -ItemType Directory -Path (Split-Path $postTerminal) -Force
    $post | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $postTerminal -Encoding utf8
    Write-PoolEvent -Event 'post-selection-ready-without-quality-retry' -Fields @{
        mineru_quality_retry_execution = $qualityExecution
        candidate_case_count = [int]$failures.recoverable_case_count
    }
}
else {
    $qualityPackages = Join-Path $privateRoot 'mineru-quality-retry-packages-r1'
    $qualityLaunch = Join-Path $controllerRoot 'quality-launch-receipt.json'
    & (Join-Path $repository 'tools\release\continue_folynta_mineru_quality_retry.ps1') `
        -RepositoryRoot $repository -ConfigPath $poolConfig `
        -OfficialTerminal $officialTerminal -QualityRetryStaging $qualityStaging `
        -QualityRetryPackages $qualityPackages -LaunchReceipt $qualityLaunch `
        -PollSeconds $PollSeconds
    if ($LASTEXITCODE -ne 0) { throw 'MinerU quality retry controller failed' }

    $qualityCollection = Join-Path $privateRoot 'mineru-quality-retry-collection-r1'
    & (Join-Path $repository 'tools\release\monitor_folynta_mineru_quality_retry.ps1') `
        -RepositoryRoot $repository -ConfigPath $poolConfig `
        -LaunchReceipt $qualityLaunch -CollectionRoot $qualityCollection `
        -PollSeconds $PollSeconds
    if ($LASTEXITCODE -ne 0) { throw 'MinerU quality retry monitor failed' }

    $qualityTerminal = Join-Path `
        $generated 'folynta-mineru-quality-retry-monitor-2026-08-04\terminal-receipt.json'
    $candidateComposite = Join-Path $privateRoot 'mineru-quality-candidate-composite-r1'
    $candidateMerged = Join-Path $generated 'folynta-mineru-quality-candidate-merged-r1-2026-08-05'
    $candidateEvaluation = Join-Path $generated 'folynta-mineru-quality-candidate-evaluation-r1-2026-08-05'
    $candidateFailures = Join-Path $generated 'folynta-mineru-quality-candidate-failures-r1-2026-08-05.json'
    & (Join-Path $repository 'tools\release\continue_folynta_mineru_quality_candidate_evaluation.ps1') `
        -RepositoryRoot $repository -QualityTerminal $qualityTerminal `
        -QualityLaunch $qualityLaunch -BaselineComposite $baselineComposite `
        -QualityCollection $qualityCollection `
        -SelectivePlan (Join-Path $qualityStaging 'selective-recovery-receipt.json') `
        -CandidateComposite $candidateComposite -CandidateMerged $candidateMerged `
        -EvaluationRoot $candidateEvaluation -FailureRecords $candidateFailures `
        -PollSeconds $PollSeconds
    if ($LASTEXITCODE -ne 0) { throw 'MinerU quality candidate evaluation failed' }

    $qualityCandidateTerminal = Join-Path `
        $generated 'folynta-mineru-quality-candidate-controller-2026-08-04\terminal-receipt.json'
    & (Join-Path $repository 'tools\release\continue_folynta_post_mineru_selection.ps1') `
        -RepositoryRoot $repository -QualityCandidateTerminal $qualityCandidateTerminal `
        -BaselineComposite $baselineComposite -CandidateComposite $candidateComposite `
        -BaselineFailures $baselineFailures -CandidateFailures $candidateFailures `
        -SelectivePlan (Join-Path $qualityStaging 'selective-recovery-receipt.json') `
        -OutputComposite (Join-Path $privateRoot 'mineru-quality-accepted-composite-r1') `
        -OutputMerged (Join-Path $generated 'folynta-mineru-quality-accepted-merged-r1-2026-08-05') `
        -OutputEvaluationRoot (Join-Path $generated 'folynta-mineru-quality-accepted-evaluation-r1-2026-08-05') `
        -OutputFailureRecords (Join-Path $generated 'folynta-mineru-quality-accepted-failures-r1-2026-08-05.json') `
        -PaddleStaging (Join-Path $privateRoot 'paddle-selective-recovery-staging-r1') `
        -DeepSeekStaging (Join-Path $privateRoot 'deepseek-selective-recovery-staging-r1') `
        -BaselineMergedRoot $baselineMerged -BaselineEvaluationRoot $baselineEvaluation `
        -PollSeconds $PollSeconds
    if ($LASTEXITCODE -ne 0) { throw 'Post-MinerU official selection failed' }
}

$terminal = [ordered]@{
    schema = 'folynta.post-baseline-mineru-pool-controller-terminal.v1'
    status = 'post_mineru_selection_complete_pool_retained_for_audit'
    pool_config = $poolConfig
    pool_receipt = $poolReceipt
    post_mineru_terminal = $postTerminal
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$terminal | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $terminalReceipt -Encoding utf8
Write-PoolEvent -Event 'post-baseline-mineru-controller-complete'
exit 0
