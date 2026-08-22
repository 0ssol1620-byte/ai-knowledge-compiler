param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('paddleocr-vl-1.6', 'deepseek-ocr-2')]
    [string]$Role,
    [Parameter(Mandatory = $true)]
    [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)]
    [string]$HostName,
    [Parameter(Mandatory = $true)]
    [int]$Port,
    [Parameter(Mandatory = $true)]
    [string]$PodId,
    [Parameter(Mandatory = $true)]
    [string]$DeadlineUtc,
    [string]$StateSlug = '2026-08-04',
    [string]$RemoteReceiptSlug,
    [int]$PollSeconds = 60
)

$ErrorActionPreference = 'Stop'
if ($Port -lt 1 -or $Port -gt 65535) { throw 'SSH port is invalid' }
if ($PodId -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$') { throw 'Pod id is invalid' }
if ($StateSlug -notmatch '^[a-z0-9][a-z0-9-]{2,63}$') { throw 'StateSlug is invalid' }
if ($PollSeconds -lt 30 -or $PollSeconds -gt 300) { throw 'PollSeconds is invalid' }
$deadline = [DateTimeOffset]::Parse($DeadlineUtc).ToUniversalTime()
$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$slug = if ($Role -eq 'paddleocr-vl-1.6') { 'paddle' } else { 'deepseek' }
$privateRoot = Join-Path `
    $repository `
    "benchmark\datasets\private\runpod-2026-08-04\$slug-recovery"
$generatedRoot = Join-Path `
    $repository `
    "benchmark\reports\generated\folynta-$slug-recovery-bootstrap-$StateSlug"
$knownHosts = Join-Path $privateRoot 'known_hosts'
$progressLog = Join-Path $generatedRoot 'progress.jsonl'
$terminalReceipt = Join-Path $generatedRoot 'terminal-receipt.json'
$collectionRoot = if ($StateSlug -eq '2026-08-04') {
    Join-Path $privateRoot 'bootstrap-evidence'
}
else {
    Join-Path $privateRoot "bootstrap-evidence-$StateSlug"
}
$null = New-Item -ItemType Directory -Path $privateRoot -Force
$null = New-Item -ItemType Directory -Path $generatedRoot -Force
$baseConfig = Get-Content -Raw -LiteralPath (
    Join-Path $repository 'benchmark\datasets\private\runpod-2026-08-04\public-core-workers.json'
) | ConvertFrom-Json
$key = [IO.Path]::GetFullPath((Join-Path $repository ([string]$baseConfig.key)))
$remoteRunSlug = if ($RemoteReceiptSlug) { $RemoteReceiptSlug } else { "$slug-r1" }
if ($remoteRunSlug -notmatch '^[a-z0-9][a-z0-9-]{2,63}$') {
    throw 'RemoteReceiptSlug is invalid'
}

function Write-BootstrapEvent {
    param([string]$Event, [hashtable]$Fields = @{})
    $payload = [ordered]@{
        event = $Event
        role = $Role
        pod_id = $PodId
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    foreach ($name in $Fields.Keys) { $payload[$name] = $Fields[$name] }
    Add-Content `
        -LiteralPath $progressLog `
        -Value ($payload | ConvertTo-Json -Compress -Depth 8) `
        -Encoding utf8
}

function Get-SshBase {
    return @(
        '-i', $key,
        '-p', [string]$Port,
        '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=yes',
        '-o', "UserKnownHostsFile=$knownHosts",
        '-o', 'KexAlgorithms=curve25519-sha256',
        '-o', 'ConnectTimeout=15'
    )
}

Write-BootstrapEvent -Event 'waiting_for_ssh'
$savedPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
if (Test-Path -LiteralPath $knownHosts) {
    & ssh-keygen -f $knownHosts -R "[$HostName]:$Port" 2>$null | Out-Null
}
$ErrorActionPreference = $savedPreference
$sshReady = $false
while ([DateTimeOffset]::UtcNow -lt $deadline) {
    $initialHostPolicy = 'accept-new'
    $initialArgs = @(
        '-i', $key,
        '-p', [string]$Port,
        '-o', 'BatchMode=yes',
        '-o', "StrictHostKeyChecking=$initialHostPolicy",
        '-o', "UserKnownHostsFile=$knownHosts",
        '-o', 'KexAlgorithms=curve25519-sha256',
        '-o', 'ConnectTimeout=15'
    )
    $savedPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & ssh @initialArgs "root@$HostName" 'printf ready' 2>$null | Out-Null
    $ErrorActionPreference = $savedPreference
    if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $knownHosts)) {
        $sshReady = $true
        break
    }
    Start-Sleep -Seconds 30
}
if (-not $sshReady) { throw 'Dedicated recovery Pod never became SSH-ready' }
Write-BootstrapEvent -Event 'ssh_ready'

$runnerRoot = '/workspace/folynta/runner'
$remoteReceipt = "/workspace/folynta/bootstrap/$remoteRunSlug"
$remoteLogRoot = '/workspace/folynta/bootstrap-logs'
& ssh @(Get-SshBase) "root@$HostName" `
    "mkdir -p $runnerRoot $remoteLogRoot /workspace/folynta/bootstrap" | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Remote bootstrap directory creation failed' }
$scpBase = @(
    '-i', $key,
    '-P', [string]$Port,
    '-o', 'BatchMode=yes',
    '-o', 'StrictHostKeyChecking=yes',
    '-o', "UserKnownHostsFile=$knownHosts",
    '-o', 'KexAlgorithms=curve25519-sha256',
    '-o', 'ConnectTimeout=15'
)
$artifactRunner = Join-Path $repository 'benchmark\runpod_eval\artifact_manifest.py'
if ($Role -eq 'paddleocr-vl-1.6') {
    $bootstrap = Join-Path `
        $repository `
        'benchmark\runpod_eval\remote_bootstrap_paddle_recovery.sh'
    $backend = Join-Path `
        $repository `
        'benchmark\runpod_eval\paddle-fastdeploy-backend.yaml'
    $uploads = @(
        @($bootstrap, "$runnerRoot/remote_bootstrap_paddle_recovery.sh"),
        @($artifactRunner, "$runnerRoot/artifact_manifest.py"),
        @($backend, "$runnerRoot/paddle-fastdeploy-backend.yaml")
    )
    $remoteCommand = "nohup bash $runnerRoot/remote_bootstrap_paddle_recovery.sh " +
        "$runnerRoot/paddle-fastdeploy-backend.yaml $remoteReceipt " +
        "$runnerRoot/artifact_manifest.py >$remoteLogRoot/$slug.stdout.log " +
        "2>$remoteLogRoot/$slug.stderr.log < /dev/null & echo `$!"
}
else {
    $bootstrap = Join-Path `
        $repository `
        'benchmark\runpod_eval\remote_bootstrap_deepseek_recovery.sh'
    $uploads = @(
        @($bootstrap, "$runnerRoot/remote_bootstrap_deepseek_recovery.sh"),
        @($artifactRunner, "$runnerRoot/artifact_manifest.py")
    )
    $remoteCommand = "nohup bash $runnerRoot/remote_bootstrap_deepseek_recovery.sh " +
        "$remoteReceipt $runnerRoot/artifact_manifest.py " +
        ">$remoteLogRoot/$slug.stdout.log 2>$remoteLogRoot/$slug.stderr.log " +
        "< /dev/null & echo `$!"
}
foreach ($upload in $uploads) {
    & scp @scpBase $upload[0] "root@${HostName}:$($upload[1])" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Bootstrap upload failed: $($upload[0])" }
}
$remotePid = (& ssh @(Get-SshBase) "root@$HostName" $remoteCommand).Trim()
if ($LASTEXITCODE -ne 0 -or $remotePid -notmatch '^[1-9][0-9]*$') {
    throw 'Dedicated recovery bootstrap launch failed'
}
Write-BootstrapEvent -Event 'bootstrap_launched' -Fields @{ remote_pid = [int]$remotePid }

while ([DateTimeOffset]::UtcNow -lt $deadline) {
    $statusCommand = "if test -f $remoteReceipt/runtime-identity.json; " +
        "then echo READY; elif kill -0 $remotePid 2>/dev/null; " +
        "then echo RUNNING; else echo FAILED; fi"
    $status = (& ssh @(Get-SshBase) "root@$HostName" $statusCommand).Trim()
    if ($LASTEXITCODE -ne 0) {
        Write-BootstrapEvent -Event 'ssh_poll_failed'
        Start-Sleep -Seconds $PollSeconds
        continue
    }
    Write-BootstrapEvent -Event 'bootstrap_poll' -Fields @{ status = $status }
    if ($status -eq 'READY') { break }
    if ($status -eq 'FAILED') {
        $stderrTail = & ssh @(Get-SshBase) "root@$HostName" `
            "tail -120 $remoteLogRoot/$slug.stderr.log 2>/dev/null || true"
        Write-BootstrapEvent `
            -Event 'bootstrap_failed' `
            -Fields @{ stderr_tail = [string]($stderrTail -join "`n") }
        throw 'Dedicated recovery bootstrap failed; see progress evidence'
    }
    Start-Sleep -Seconds $PollSeconds
}
if ([DateTimeOffset]::UtcNow -ge $deadline) { throw 'Dedicated recovery bootstrap deadline reached' }

$remoteArchive = "/workspace/folynta/bootstrap/$remoteRunSlug-evidence.tar.gz"
& ssh @(Get-SshBase) "root@$HostName" `
    "tar -C /workspace/folynta/bootstrap -czf $remoteArchive $remoteRunSlug && sha256sum $remoteArchive" `
    > (Join-Path $generatedRoot 'remote-archive-sha256.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dedicated recovery evidence archive failed' }
if (Test-Path -LiteralPath $collectionRoot) {
    throw 'Dedicated recovery bootstrap collection already exists'
}
$null = New-Item -ItemType Directory -Path $collectionRoot
$localArchive = Join-Path $collectionRoot "$remoteRunSlug-evidence.tar.gz"
& scp @scpBase "root@${HostName}:$remoteArchive" $localArchive | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Dedicated recovery evidence download failed' }
tar -xzf $localArchive -C $collectionRoot
if ($LASTEXITCODE -ne 0) { throw 'Dedicated recovery evidence extraction failed' }
$identity = Get-Content -Raw -LiteralPath (
    Join-Path $collectionRoot "$remoteRunSlug\runtime-identity.json"
) | ConvertFrom-Json
$archiveHash = (Get-FileHash -LiteralPath $localArchive -Algorithm SHA256).Hash.ToLowerInvariant()
$receipt = [ordered]@{
    schema = 'folynta.dedicated-recovery-bootstrap-terminal.v1'
    status = 'runtime_ready'
    role = $Role
    pod_id = $PodId
    host = $HostName
    port = $Port
    runtime_identity = $identity
    archive_sha256 = "sha256:$archiveHash"
    completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
}
$receipt | ConvertTo-Json -Depth 10 |
    Set-Content -LiteralPath $terminalReceipt -Encoding utf8
Write-BootstrapEvent -Event 'runtime_ready'
exit 0
