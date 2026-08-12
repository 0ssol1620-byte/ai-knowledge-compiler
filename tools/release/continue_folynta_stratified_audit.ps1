param(
    [Parameter(Mandatory = $true)] [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)] [string]$PostMineruTerminal,
    [Parameter(Mandatory = $true)] [string]$DeadlineUtc,
    [string]$ConfigPath,
    [string]$PoolReceipt,
    [int]$PollSeconds = 60
)

$ErrorActionPreference = 'Stop'
if ($PollSeconds -lt 30 -or $PollSeconds -gt 300) { throw 'PollSeconds is invalid' }
$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$terminal = [IO.Path]::GetFullPath($PostMineruTerminal)
$deadline = [DateTimeOffset]::Parse($DeadlineUtc).ToUniversalTime()
$progressRoot = Join-Path `
    $repository `
    'benchmark\reports\generated\folynta-stratified-audit-controller-2026-08-04'
$progress = Join-Path $progressRoot 'progress.jsonl'
$null = New-Item -ItemType Directory -Path $progressRoot -Force

function Write-AuditEvent {
    param([string]$Event, [hashtable]$Fields = @{})
    $payload = [ordered]@{
        event = $Event
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    foreach ($name in $Fields.Keys) { $payload[$name] = $Fields[$name] }
    Add-Content `
        -LiteralPath $progress `
        -Value ($payload | ConvertTo-Json -Compress -Depth 8) `
        -Encoding utf8
}

Write-AuditEvent -Event 'waiting-for-post-mineru-selection'
while (-not (Test-Path -LiteralPath $terminal)) {
    if ([DateTimeOffset]::UtcNow -ge $deadline) {
        throw 'Stratified audit deadline reached before post-MinerU selection'
    }
    Start-Sleep -Seconds $PollSeconds
}
$post = Get-Content -Raw -LiteralPath $terminal | ConvertFrom-Json
if ($post.status -ne 'alternate_recovery_staged') {
    throw 'Post-MinerU terminal identity is invalid for stratified audit'
}
$expandedConfig = if ($ConfigPath) {
    [IO.Path]::GetFullPath($ConfigPath)
}
else {
    Join-Path `
        $repository `
        'benchmark\datasets\private\runpod-2026-08-04\operational-retry-workers-expanded.json'
}
$expansionReceiptPath = if ($PoolReceipt) {
    [IO.Path]::GetFullPath($PoolReceipt)
}
else {
    Join-Path `
        $repository `
        'benchmark\datasets\private\runpod-2026-08-04\mineru-retry-expansion\bootstrap-receipt.json'
}
$expansionBootstrap = Get-Content -Raw -LiteralPath $expansionReceiptPath |
    ConvertFrom-Json
if (
    $expansionBootstrap.status -notin @(
        'ready_identity_bound_and_smoke_passed',
        'ready_identity_bound_and_smoke_passed_pool'
    ) -or
    [string]$expansionBootstrap.model_artifact_manifest_sha256 -ne `
        'sha256:1611a8892cc0e7e287d31c4a1b5af87652f0f6e4a3f80276b92b4c71f982de84'
) {
    throw 'Expanded stratified-audit workers did not pass the pinned runtime gate'
}
$configuredIndices = @(
    (Get-Content -Raw -LiteralPath $expandedConfig | ConvertFrom-Json).workers |
        ForEach-Object { [int]$_.worker_index }
)
if (@($configuredIndices | Where-Object { $_ -ge 4 }).Count -lt 3) {
    throw 'Stratified audit requires three revalidated pool workers'
}
$python = Join-Path $repository '.venv\Scripts\python.exe'
$arguments = @(
    (Join-Path $repository 'benchmark\runpod_eval\run_stratified_audit_campaign.py'),
    '--repository-root', $repository,
    '--config', $expandedConfig,
    '--worker-health', (
        Join-Path $repository `
            'benchmark\reports\generated\runpod-operational-retry-controller-2026-08-04\operational-worker-health.json'
    ),
    '--package-receipt', (
        Join-Path $repository `
            'benchmark\datasets\private\runpod-2026-08-04\stratified-audit-packages\package-receipt.json'
    ),
    '--package-root', (
        Join-Path $repository `
            'benchmark\datasets\private\runpod-2026-08-04\stratified-audit-packages'
    ),
    '--mineru-runner', (
        Join-Path $repository 'benchmark\runpod_eval\mineru_stage2.py'
    ),
    '--audit-runner', (
        Join-Path $repository 'benchmark\runpod_eval\remote_run_stratified_audit.sh'
    ),
    '--input-contract', (
        Join-Path $repository 'benchmark\runpod_eval\input_contract.py'
    ),
    '--output-root', (
        Join-Path $repository `
            'benchmark\datasets\private\runpod-2026-08-04\stratified-audit-results-r1'
    ),
    '--deadline-unix', [string]$deadline.ToUnixTimeSeconds(),
    '--poll-seconds', [string]$PollSeconds
)
& $python @arguments 2>&1 | ForEach-Object {
    Write-AuditEvent -Event 'campaign-output' -Fields @{ line = [string]$_ }
}
if ($LASTEXITCODE -ne 0) { throw "Stratified audit campaign failed: $LASTEXITCODE" }
Write-AuditEvent -Event 'stratified-audit-collected'
exit 0
