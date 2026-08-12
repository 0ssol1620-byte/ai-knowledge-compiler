param(
    [Parameter(Mandatory = $true)] [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)] [string]$PostMineruTerminal,
    [Parameter(Mandatory = $true)] [string]$PaddleBootstrapTerminal,
    [Parameter(Mandatory = $true)] [string]$DeepSeekBootstrapTerminal,
    [Parameter(Mandatory = $true)] [string]$PaddleHost,
    [Parameter(Mandatory = $true)] [int]$PaddlePort,
    [Parameter(Mandatory = $true)] [string]$PaddlePodId,
    [Parameter(Mandatory = $true)] [string]$DeepSeekHost,
    [Parameter(Mandatory = $true)] [int]$DeepSeekPort,
    [Parameter(Mandatory = $true)] [string]$DeepSeekPodId,
    [Parameter(Mandatory = $true)] [string]$BaselinePodIdCsv,
    [Parameter(Mandatory = $true)] [string]$DeadlineUtc,
    # Recorded folynta.recovery-execution-decision.v1 receipt. Absent means both
    # alternate-recovery campaigns run, which is the original behaviour.
    [string]$ExecutionDecision,
    [int]$PollSeconds = 60
)

$ErrorActionPreference = 'Stop'
if ($PollSeconds -lt 30 -or $PollSeconds -gt 300) { throw 'PollSeconds is invalid' }
$deadline = [DateTimeOffset]::Parse($DeadlineUtc).ToUniversalTime()
$BaselinePodIds = @($BaselinePodIdCsv.Split(',') | Where-Object { $_ })
if ($BaselinePodIds.Count -ne 4 -or @($BaselinePodIds | Select-Object -Unique).Count -ne 4) {
    throw 'Exactly four unique baseline Pod ids are required'
}
$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$postTerminalPath = [IO.Path]::GetFullPath($PostMineruTerminal)
$paddleBootstrapPath = [IO.Path]::GetFullPath($PaddleBootstrapTerminal)
$deepseekBootstrapPath = [IO.Path]::GetFullPath($DeepSeekBootstrapTerminal)
$python = Join-Path $repository '.venv\Scripts\python.exe'
$controllerRoot = Join-Path `
    $repository `
    'benchmark\reports\generated\folynta-alternate-recovery-controller-2026-08-04'
$privateRoot = Join-Path `
    $repository `
    'benchmark\datasets\private\runpod-2026-08-04\alternate-recovery-live-r1'
$progressLog = Join-Path $controllerRoot 'progress.jsonl'
$terminalReceipt = Join-Path $controllerRoot 'terminal-receipt.json'
$null = New-Item -ItemType Directory -Path $controllerRoot -Force
$null = New-Item -ItemType Directory -Path $privateRoot -Force
$baseConfigPath = Join-Path `
    $repository `
    'benchmark\datasets\private\runpod-2026-08-04\public-core-workers.json'
$baseConfig = Get-Content -Raw -LiteralPath $baseConfigPath | ConvertFrom-Json
$key = [IO.Path]::GetFullPath((Join-Path $repository ([string]$baseConfig.key)))
$shardPlan = Join-Path `
    $repository `
    'benchmark\reports\generated\folynta-mineru344-public-core-4shard-plan-2026-08-04.json'
$stagedRoot = Join-Path $repository 'benchmark\datasets\staged-public-core'
$privateStagedRoot = Join-Path `
    $repository `
    'benchmark\datasets\private\mineru-public-core-workers-2026-08-04'
$workerHealth = Join-Path `
    $repository `
    'benchmark\reports\generated\runpod-operational-retry-controller-2026-08-04\operational-worker-health.json'

function Write-RecoveryEvent {
    param([string]$Event, [hashtable]$Fields = @{})
    $payload = [ordered]@{
        event = $Event
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    foreach ($name in $Fields.Keys) { $payload[$name] = $Fields[$name] }
    Add-Content `
        -LiteralPath $progressLog `
        -Value ($payload | ConvertTo-Json -Compress -Depth 12) `
        -Encoding utf8
}

function Invoke-LoggedPython {
    param([string]$Name, [object[]]$Arguments)
    & $python @Arguments 2>&1 | ForEach-Object {
        Write-RecoveryEvent -Event $Name -Fields @{ line = [string]$_ }
    }
    if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit $LASTEXITCODE" }
}

function Wait-ForFile {
    param([string]$Path, [string]$Event)
    while (-not (Test-Path -LiteralPath $Path)) {
        if ([DateTimeOffset]::UtcNow -ge $deadline) { throw "deadline waiting for $Path" }
        Write-RecoveryEvent -Event $Event
        Start-Sleep -Seconds $PollSeconds
    }
}

function Get-FailureRecordSummary {
    param([string]$FailureRecords)
    # The record file reaches ~77 MB, and ConvertFrom-Json materialises a
    # PSCustomObject per node, so the scalars come from the Python lane instead
    # of rebuilding the whole graph on every call.
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

function Get-RecoveryRouteCount {
    param([string]$FailureRecords, [string]$Model)
    $summary = Get-FailureRecordSummary -FailureRecords $FailureRecords
    $counts = $summary.recovery_route_counts_by_model
    $matched = $counts.PSObject.Properties | Where-Object { $_.Name -eq $Model }
    if (-not $matched) { return 0 }
    return [int]$matched.Value
}

function Get-WorkerArguments {
    param([string]$Flag, [string]$Root)
    $arguments = @()
    for ($index = 0; $index -lt 4; $index++) {
        $arguments += @(
            $Flag,
            "$index=$(Join-Path $Root ("worker-{0:d2}" -f $index))"
        )
    }
    return $arguments
}

function Invoke-MergeAndEvaluate {
    param(
        [string]$Name,
        [string]$Composite,
        [string]$Merged,
        [string]$EvaluationRoot,
        [string]$FailureRecords
    )
    if (-not (Test-Path -LiteralPath $Merged)) {
        $arguments = @(
            (Join-Path $repository 'benchmark\runpod_eval\public_core_merge.py')
        )
        $arguments += Get-WorkerArguments -Flag '--worker' -Root $Composite
        $arguments += @(
            '--staged-root', $stagedRoot,
            '--shard-plan', $shardPlan,
            '--output-root', $Merged
        )
        Invoke-LoggedPython -Name "$Name-merge" -Arguments $arguments
    }
    $mergeReceipt = Get-Content -Raw -LiteralPath (
        Join-Path $Merged 'merge-receipt.json'
    ) | ConvertFrom-Json
    if ([int]$mergeReceipt.completed -ne 5132 -or [int]$mergeReceipt.failed -ne 0) {
        throw "$Name merge is incomplete"
    }
    $bundleReceipt = Join-Path $EvaluationRoot 'official-evaluation-bundle-receipt.json'
    if (-not (Test-Path -LiteralPath $bundleReceipt)) {
        Invoke-LoggedPython `
            -Name "$Name-official-evaluation" `
            -Arguments @(
                (Join-Path $repository 'benchmark\runpod_eval\run_public_core_official_bundle.py'),
                '--repository-root', $repository,
                '--merged-root', $Merged,
                '--output-root', $EvaluationRoot,
                '--failure-records', $FailureRecords
            )
    }
    return Get-Content -Raw -LiteralPath $bundleReceipt | ConvertFrom-Json
}

function Invoke-DedicatedCampaign {
    param(
        [string]$Model,
        [string]$Staging,
        [string]$HostName,
        [int]$Port,
        [string]$PodId,
        [string]$KnownHosts,
        [string]$BootstrapTerminal,
        [string]$Slug
    )
    Wait-ForFile -Path $BootstrapTerminal -Event "waiting-for-$Slug-bootstrap"
    $bootstrap = Get-Content -Raw -LiteralPath $BootstrapTerminal | ConvertFrom-Json
    if ($bootstrap.status -ne 'runtime_ready' -or $bootstrap.pod_id -ne $PodId) {
        throw "$Model dedicated runtime identity is invalid"
    }
    $packageRoot = Join-Path $privateRoot "$Slug-packages"
    $packageReceipt = Join-Path $packageRoot 'package-receipt.json'
    if (-not (Test-Path -LiteralPath $packageReceipt)) {
        Invoke-LoggedPython `
            -Name "$Slug-package" `
            -Arguments @(
                (Join-Path $repository 'benchmark\runpod_eval\package_selective_recovery_inputs.py'),
                '--staging-root', $Staging,
                '--output-root', $packageRoot
            )
    }
    $launchReceipt = Join-Path $controllerRoot "$Slug-launch-receipt.json"
    if (-not (Test-Path -LiteralPath $launchReceipt)) {
        $modelRunner = if ($Model -eq 'paddleocr-vl-1.6') {
            Join-Path $repository 'benchmark\runpod_eval\paddleocr_vl_stage2.py'
        }
        else {
            Join-Path $repository 'benchmark\runpod_eval\deepseek_ocr2_stage2.py'
        }
        $arguments = @(
            (Join-Path $repository 'benchmark\runpod_eval\launch_dedicated_recovery.py'),
            '--repository-root', $repository,
            '--model', $Model,
            '--host', $HostName,
            '--port', [string]$Port,
            '--pod-id', $PodId,
            '--key', $key,
            '--known-hosts', $KnownHosts,
            '--package-receipt', $packageReceipt,
            '--package-root', $packageRoot,
            '--model-runner', $modelRunner,
            '--campaign-runner', (
                Join-Path $repository 'benchmark\runpod_eval\remote_run_dedicated_recovery.sh'
            ),
            '--input-contract', (
                Join-Path $repository 'benchmark\runpod_eval\input_contract.py'
            ),
            '--isolated-process', (
                Join-Path $repository 'benchmark\runpod_eval\isolated_case_process.py'
            ),
            '--output-receipt', $launchReceipt
        )
        foreach ($baselinePod in $BaselinePodIds) {
            $arguments += @('--forbid-pod-id', $baselinePod)
        }
        Invoke-LoggedPython -Name "$Slug-launch" -Arguments $arguments
    }
    $launch = Get-Content -Raw -LiteralPath $launchReceipt | ConvertFrom-Json
    $runnerPid = [int]$launch.runner_pid
    $remoteRoot = "/workspace/folynta/results/$Slug-r1"
    $sshArgs = @(
        '-i', $key,
        '-p', [string]$Port,
        '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=yes',
        '-o', "UserKnownHostsFile=$KnownHosts",
        '-o', 'KexAlgorithms=curve25519-sha256',
        '-o', 'ConnectTimeout=15'
    )
    while ($true) {
        if ([DateTimeOffset]::UtcNow -ge $deadline) { throw "$Model campaign deadline" }
        $command = "if test -f '$remoteRoot/campaign-state.jsonl' && " +
            "tail -1 '$remoteRoot/campaign-state.jsonl' | " +
            "grep -F 'dedicated_recovery_completed' >/dev/null; " +
            "then echo COMPLETE; elif kill -0 $runnerPid 2>/dev/null; " +
            "then echo RUNNING; else echo FAILED; fi"
        $status = (& ssh @sshArgs "root@$HostName" $command).Trim()
        if ($LASTEXITCODE -ne 0) {
            Write-RecoveryEvent -Event "$Slug-ssh-poll-failed"
            Start-Sleep -Seconds $PollSeconds
            continue
        }
        Write-RecoveryEvent -Event "$Slug-campaign-poll" -Fields @{ status = $status }
        if ($status -eq 'COMPLETE') { break }
        if ($status -eq 'FAILED') {
            $stderrTail = & ssh @sshArgs "root@$HostName" `
                "tail -120 '$remoteRoot.launcher.stderr.log' 2>/dev/null || true"
            Write-RecoveryEvent `
                -Event "$Slug-campaign-failed" `
                -Fields @{ stderr_tail = [string]($stderrTail -join "`n") }
            throw "$Model dedicated campaign failed"
        }
        Start-Sleep -Seconds $PollSeconds
    }
    $collectionRoot = Join-Path $privateRoot "$Slug-collection"
    $collectionReceipt = Join-Path $collectionRoot 'collection-receipt.json'
    if (-not (Test-Path -LiteralPath $collectionReceipt)) {
        Invoke-LoggedPython `
            -Name "$Slug-collection" `
            -Arguments @(
                (Join-Path $repository 'benchmark\runpod_eval\collect_dedicated_recovery.py'),
                '--model', $Model,
                '--host', $HostName,
                '--port', [string]$Port,
                '--key', $key,
                '--known-hosts', $KnownHosts,
                '--launch-receipt', $launchReceipt,
                '--output-root', $collectionRoot
            )
    }
    return Join-Path $collectionRoot 'evidence'
}

function Invoke-AlternateSelection {
    param(
        [string]$Model,
        [string]$Slug,
        [string]$BaselineComposite,
        [string]$BaselineMerged,
        [string]$BaselineEvaluation,
        [string]$BaselineFailures,
        [string]$Staging,
        [string]$RecoveryEvidence
    )
    $candidateComposite = Join-Path $privateRoot "$Slug-candidate-composite"
    if (-not (Test-Path -LiteralPath $candidateComposite)) {
        $arguments = @(
            (Join-Path $repository 'benchmark\runpod_eval\apply_alternate_candidates.py')
        )
        $arguments += Get-WorkerArguments -Flag '--baseline' -Root $BaselineComposite
        $arguments += @(
            '--recovery-root', $RecoveryEvidence,
            '--selective-plan', (Join-Path $Staging 'selective-recovery-receipt.json'),
            '--recovery-model', $Model,
            '--output-root', $candidateComposite
        )
        Invoke-LoggedPython -Name "$Slug-candidate-overlay" -Arguments $arguments
    }
    $candidateMerged = Join-Path $controllerRoot "$Slug-candidate-merged"
    $candidateEvaluation = Join-Path $controllerRoot "$Slug-candidate-evaluation"
    $candidateFailures = Join-Path $controllerRoot "$Slug-candidate-failures.json"
    $null = Invoke-MergeAndEvaluate `
        -Name "$Slug-candidate" `
        -Composite $candidateComposite `
        -Merged $candidateMerged `
        -EvaluationRoot $candidateEvaluation `
        -FailureRecords $candidateFailures
    $comparison = Join-Path $controllerRoot "$Slug-official-comparison.json"
    if (-not (Test-Path -LiteralPath $comparison)) {
        Invoke-LoggedPython `
            -Name "$Slug-official-comparison" `
            -Arguments @(
                (Join-Path $repository 'benchmark\runpod_eval\compare_official_failure_records.py'),
                '--baseline', $BaselineFailures,
                '--candidate', $candidateFailures,
                '--output', $comparison
            )
    }
    $acceptedComposite = Join-Path $privateRoot "$Slug-accepted-composite"
    if (-not (Test-Path -LiteralPath $acceptedComposite)) {
        $arguments = @(
            (Join-Path $repository 'benchmark\runpod_eval\apply_accepted_alternate_candidates.py')
        )
        $arguments += Get-WorkerArguments -Flag '--baseline' -Root $BaselineComposite
        $arguments += Get-WorkerArguments -Flag '--candidate' -Root $candidateComposite
        $arguments += @(
            '--selective-plan', (Join-Path $Staging 'selective-recovery-receipt.json'),
            '--comparison', $comparison,
            '--recovery-model', $Model,
            '--output-root', $acceptedComposite
        )
        Invoke-LoggedPython -Name "$Slug-accepted-overlay" -Arguments $arguments
    }
    $acceptedMerged = Join-Path $controllerRoot "$Slug-accepted-merged"
    $acceptedEvaluation = Join-Path $controllerRoot "$Slug-accepted-evaluation"
    $acceptedFailures = Join-Path $controllerRoot "$Slug-accepted-failures.json"
    $bundle = Invoke-MergeAndEvaluate `
        -Name "$Slug-accepted" `
        -Composite $acceptedComposite `
        -Merged $acceptedMerged `
        -EvaluationRoot $acceptedEvaluation `
        -FailureRecords $acceptedFailures
    $comparisonPayload = Get-Content -Raw -LiteralPath $comparison | ConvertFrom-Json
    $aggregateComparisonPath = Join-Path `
        $controllerRoot `
        "$Slug-aggregate-official-comparison.json"
    if (-not (Test-Path -LiteralPath $aggregateComparisonPath)) {
        Invoke-LoggedPython `
            -Name "$Slug-aggregate-official-comparison" `
            -Arguments @(
                (Join-Path $repository 'benchmark\runpod_eval\compare_official_evaluation_metrics.py'),
                '--baseline-root', $BaselineEvaluation,
                '--candidate-root', $acceptedEvaluation,
                '--baseline-failure-records', $BaselineFailures,
                '--candidate-failure-records', $acceptedFailures,
                '--output', $aggregateComparisonPath
            )
    }
    $aggregateComparison = Get-Content -Raw -LiteralPath $aggregateComparisonPath |
        ConvertFrom-Json
    $acceptedCount = [int]$comparisonPayload.accepted_quality_case_count
    $revertedCount = [int]$comparisonPayload.regressed_candidate_case_count
    $aggregateRollback = $aggregateComparison.no_regression -ne $true
    if ($aggregateRollback) {
        $revertedCount += $acceptedCount
        $acceptedCount = 0
        Write-RecoveryEvent `
            -Event "$Slug-aggregate-regression-rolled-back" `
            -Fields @{ delta = $aggregateComparison.delta }
    }
    Write-RecoveryEvent `
        -Event "$Slug-selection-complete" `
        -Fields @{
            accepted = $acceptedCount
            reverted = $revertedCount
            aggregate_rollback = $aggregateRollback
            remaining_failure_records = if ($aggregateRollback) {
                [int](Get-Content -Raw -LiteralPath $BaselineFailures |
                    ConvertFrom-Json).record_count
            } else { [int]$bundle.official_failure_record_count }
        }
    if ($aggregateRollback) {
        return [pscustomobject]@{
            composite = $BaselineComposite
            merged = $BaselineMerged
            evaluation = $BaselineEvaluation
            failures = $BaselineFailures
            comparison = $comparison
            aggregate_comparison = $aggregateComparisonPath
            aggregate_rollback = $true
            accepted = 0
            reverted = $revertedCount
        }
    }
    return [pscustomobject]@{
        composite = $acceptedComposite
        merged = $acceptedMerged
        evaluation = $acceptedEvaluation
        failures = $acceptedFailures
        comparison = $comparison
        aggregate_comparison = $aggregateComparisonPath
        aggregate_rollback = $false
        accepted = $acceptedCount
        reverted = $revertedCount
    }
}

Write-RecoveryEvent -Event 'waiting-for-post-mineru-selection'
Wait-ForFile -Path $postTerminalPath -Event 'waiting-for-post-mineru-selection'
$post = Get-Content -Raw -LiteralPath $postTerminalPath | ConvertFrom-Json
if ($post.status -ne 'alternate_recovery_staged') {
    throw 'post-MinerU selection terminal identity is invalid'
}
$currentComposite = [string]$post.composite_root
$currentMerged = [string]$post.merged_root
$currentEvaluation = [string]$post.evaluation_root
$currentFailures = [string]$post.failure_records
$paddleAccepted = 0
$paddleReverted = 0
$paddleAggregateComparison = $null
$paddleAggregateRollback = $false
$deepseekAccepted = 0
$deepseekReverted = 0
$deepseekAggregateComparison = $null
$deepseekAggregateRollback = $false

$alternateDecision = $null
$alternateDeclined = $false
if ($ExecutionDecision) {
    $alternateDecisionPath = [IO.Path]::GetFullPath($ExecutionDecision)
    $alternateDecision = Get-Content -Raw -LiteralPath $alternateDecisionPath |
        ConvertFrom-Json
    if ($alternateDecision.schema -ne 'folynta.recovery-execution-decision.v1') {
        throw 'Recovery execution decision schema is invalid'
    }
    $alternateDeclined = (
        $alternateDecision.execute_post_selection_alternate_recovery -eq $false
    )
    Write-RecoveryEvent -Event 'execution-decision-observed' -Fields @{
        decision = $alternateDecisionPath
        execute_post_selection_alternate_recovery = -not $alternateDeclined
        decision_sha256 = [string]$alternateDecision.decision_sha256
    }
}

# Candidate counts are always measured, so a declined campaign is reported as
# "this many cases were eligible and none were run", never as zero eligible.
$paddleCandidateRoutes = Get-RecoveryRouteCount `
    -FailureRecords $currentFailures `
    -Model 'paddleocr-vl-1.6'
$deepseekCandidateRoutes = Get-RecoveryRouteCount `
    -FailureRecords $currentFailures `
    -Model 'deepseek-ocr-2'
$paddleRoutes = if ($alternateDeclined) { 0 } else { $paddleCandidateRoutes }
if ($paddleRoutes -gt 0) {
    $paddleStaging = [string]$post.paddle_staging
    $paddleKnownHosts = Join-Path `
        $repository `
        'benchmark\datasets\private\runpod-2026-08-04\paddle-recovery\known_hosts'
    $evidence = Invoke-DedicatedCampaign `
        -Model 'paddleocr-vl-1.6' `
        -Staging $paddleStaging `
        -HostName $PaddleHost `
        -Port $PaddlePort `
        -PodId $PaddlePodId `
        -KnownHosts $paddleKnownHosts `
        -BootstrapTerminal $paddleBootstrapPath `
        -Slug 'paddle'
    $selected = Invoke-AlternateSelection `
        -Model 'paddleocr-vl-1.6' `
        -Slug 'paddle' `
        -BaselineComposite $currentComposite `
        -BaselineMerged $currentMerged `
        -BaselineEvaluation $currentEvaluation `
        -BaselineFailures $currentFailures `
        -Staging $paddleStaging `
        -RecoveryEvidence $evidence
    $currentComposite = $selected.composite
    $currentMerged = $selected.merged
    $currentEvaluation = $selected.evaluation
    $currentFailures = $selected.failures
    $paddleAccepted = $selected.accepted
    $paddleReverted = $selected.reverted
    $paddleAggregateComparison = $selected.aggregate_comparison
    $paddleAggregateRollback = $selected.aggregate_rollback
}

$deepseekRoutes = if ($alternateDeclined) {
    0
}
else {
    Get-RecoveryRouteCount -FailureRecords $currentFailures -Model 'deepseek-ocr-2'
}
if ($deepseekRoutes -gt 0) {
    $deepseekStaging = Join-Path $privateRoot 'deepseek-staging-after-paddle'
    if (-not (Test-Path -LiteralPath $deepseekStaging)) {
        Invoke-LoggedPython `
            -Name 'deepseek-staging-after-paddle' `
            -Arguments @(
                (Join-Path $repository 'benchmark\runpod_eval\stage_selective_recovery.py'),
                '--failure-records', $currentFailures,
                '--staged-root', $privateStagedRoot,
                '--shard-plan', $shardPlan,
                '--recovery-model', 'deepseek-ocr-2',
                '--output-root', $deepseekStaging,
                '--worker-health', $workerHealth
            )
    }
    $deepseekKnownHosts = Join-Path `
        $repository `
        'benchmark\datasets\private\runpod-2026-08-04\deepseek-recovery\known_hosts'
    $evidence = Invoke-DedicatedCampaign `
        -Model 'deepseek-ocr-2' `
        -Staging $deepseekStaging `
        -HostName $DeepSeekHost `
        -Port $DeepSeekPort `
        -PodId $DeepSeekPodId `
        -KnownHosts $deepseekKnownHosts `
        -BootstrapTerminal $deepseekBootstrapPath `
        -Slug 'deepseek'
    $selected = Invoke-AlternateSelection `
        -Model 'deepseek-ocr-2' `
        -Slug 'deepseek' `
        -BaselineComposite $currentComposite `
        -BaselineMerged $currentMerged `
        -BaselineEvaluation $currentEvaluation `
        -BaselineFailures $currentFailures `
        -Staging $deepseekStaging `
        -RecoveryEvidence $evidence
    $currentComposite = $selected.composite
    $currentMerged = $selected.merged
    $currentEvaluation = $selected.evaluation
    $currentFailures = $selected.failures
    $deepseekAccepted = $selected.accepted
    $deepseekReverted = $selected.reverted
    $deepseekAggregateComparison = $selected.aggregate_comparison
    $deepseekAggregateRollback = $selected.aggregate_rollback
}

$finalFailures = Get-FailureRecordSummary -FailureRecords $currentFailures
$terminal = [ordered]@{
    schema = 'folynta.alternate-recovery-controller-terminal.v1'
    status = 'alternate_recovery_officially_selected'
    input_count = 5132
    alternate_recovery_execution = if ($alternateDeclined) {
        'candidates_routed_not_executed_by_recorded_decision'
    }
    else { 'executed' }
    execution_decision = if ($alternateDecision) { $alternateDecisionPath } else { $null }
    execution_decision_sha256 = if ($alternateDecision) {
        [string]$alternateDecision.decision_sha256
    }
    else { $null }
    paddle_candidate_route_case_count = $paddleCandidateRoutes
    deepseek_candidate_route_case_count = $deepseekCandidateRoutes
    paddle_routed_case_count = $paddleRoutes
    paddle_accepted_case_count = $paddleAccepted
    paddle_reverted_regression_case_count = $paddleReverted
    paddle_aggregate_metric_comparison = $paddleAggregateComparison
    paddle_aggregate_metric_rollback = $paddleAggregateRollback
    deepseek_routed_case_count = $deepseekRoutes
    deepseek_accepted_case_count = $deepseekAccepted
    deepseek_reverted_regression_case_count = $deepseekReverted
    deepseek_aggregate_metric_comparison = $deepseekAggregateComparison
    deepseek_aggregate_metric_rollback = $deepseekAggregateRollback
    final_official_failure_record_count = [int]$finalFailures.record_count
    final_composite_root = $currentComposite
    final_merged_root = $currentMerged
    final_evaluation_root = $currentEvaluation
    final_failure_records = $currentFailures
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$terminal | ConvertTo-Json -Depth 10 |
    Set-Content -LiteralPath $terminalReceipt -Encoding utf8
Write-RecoveryEvent -Event 'alternate-recovery-officially-selected'
exit 0
