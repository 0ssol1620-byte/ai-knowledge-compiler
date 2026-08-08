param(
    [Parameter(Mandatory = $true)] [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)] [string]$CredentialFile,
    [Parameter(Mandatory = $true)] [string]$DeadlineUtc,
    [int]$PollSeconds = 60
)
$ErrorActionPreference='Stop'
$repository=[IO.Path]::GetFullPath($RepositoryRoot)
$deadline=[DateTimeOffset]::Parse($DeadlineUtc).ToUniversalTime()
$provisioning=Join-Path $repository 'benchmark\datasets\private\runpod-2026-08-04\deepseek-operational-r2\provisioning-receipt.json'
while(-not (Test-Path -LiteralPath $provisioning)){
    if([DateTimeOffset]::UtcNow -ge $deadline){throw 'DeepSeek provisioning deadline'}
    Start-Sleep -Seconds $PollSeconds
}
$pod=Get-Content -Raw -LiteralPath $provisioning | ConvertFrom-Json
if($pod.status -ne 'running_ssh_exposed' -or $pod.role -ne 'deepseek-ocr-2'){throw 'DeepSeek provisioning identity is invalid'}
$bootstrapScript=Join-Path $repository 'tools\release\bootstrap_folynta_dedicated_recovery_pod.ps1'
& $bootstrapScript -Role 'deepseek-ocr-2' -RepositoryRoot $repository -HostName ([string]$pod.host) -Port ([int]$pod.port) -PodId ([string]$pod.pod_id) -DeadlineUtc $deadline.ToString('o') -StateSlug 'operational-r2-2026-08-06' -RemoteReceiptSlug 'deepseek-operational-r2' -PollSeconds $PollSeconds
if($LASTEXITCODE -ne 0){throw 'DeepSeek bootstrap failed'}
$bootstrapTerminal=Join-Path $repository 'benchmark\reports\generated\folynta-deepseek-recovery-bootstrap-operational-r2-2026-08-06\terminal-receipt.json'
& (Join-Path $repository 'tools\release\continue_folynta_preofficial_operational_deepseek.ps1') -RepositoryRoot $repository -CredentialFile $CredentialFile -HostName ([string]$pod.host) -Port ([int]$pod.port) -PodId ([string]$pod.pod_id) -BootstrapTerminal $bootstrapTerminal -DeadlineUtc $deadline.ToString('o') -RemoteBootstrapSlug 'deepseek-operational-r2' -PollSeconds $PollSeconds
if($LASTEXITCODE -ne 0){throw 'DeepSeek hybrid continuation failed'}
