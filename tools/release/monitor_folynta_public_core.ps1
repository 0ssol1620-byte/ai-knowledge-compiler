param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,
    [Parameter(Mandatory = $true)]
    [string]$CollectionRoot,
    [int]$PollSeconds = 60
)

$ErrorActionPreference = 'Stop'
if ($PollSeconds -lt 30 -or $PollSeconds -gt 300) {
    throw 'PollSeconds must be between 30 and 300.'
}

$repository = [IO.Path]::GetFullPath($RepositoryRoot)
$configFile = [IO.Path]::GetFullPath($ConfigPath)
$collection = [IO.Path]::GetFullPath($CollectionRoot)
$config = Get-Content -Raw -LiteralPath $configFile | ConvertFrom-Json
$key = [IO.Path]::GetFullPath((Join-Path $repository $config.key))
$knownHosts = [IO.Path]::GetFullPath((Join-Path $repository $config.known_hosts))
$deadline = [DateTimeOffset]::Parse($config.deadline_utc).ToUniversalTime()
$progressRoot = Join-Path $repository 'benchmark\reports\generated\runpod-public-core-live-monitor-2026-08-04'
$progressLog = Join-Path $progressRoot 'progress.jsonl'
$terminalReceipt = Join-Path $progressRoot 'terminal-receipt.json'
New-Item -ItemType Directory -Path $progressRoot -Force | Out-Null

function Write-ProgressRecord {
    param([hashtable]$Payload)
    $Payload['observed_at_utc'] = [DateTimeOffset]::UtcNow.ToString('o')
    Add-Content -LiteralPath $progressLog -Value ($Payload | ConvertTo-Json -Compress -Depth 8) -Encoding utf8
}

while ([DateTimeOffset]::UtcNow -lt $deadline) {
    $observations = @()
    $allComplete = $true
    foreach ($worker in $config.workers) {
        $remote = 'p=$(find /workspace/folynta/results/full/parsebench/repeat-1 -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l); o=$(find /workspace/folynta/results/full/omnidocbench/repeat-1 -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l); m=$(find /workspace/folynta/results/full/olmocr-bench/repeat-1 -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l); c=0; test -f /workspace/folynta/results/full/parsebench/run-summary.json && test -f /workspace/folynta/results/full/omnidocbench/run-summary.json && test -f /workspace/folynta/results/full/olmocr-bench/run-summary.json && c=1; printf "%s,%s,%s,%s" "$p" "$o" "$m" "$c"'
        try {
            $value = & ssh -i $key -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$knownHosts" -p ([int]$worker.port) "root@$($worker.host)" $remote
            if ($LASTEXITCODE -ne 0) {
                throw "ssh_exit_$LASTEXITCODE"
            }
            $parts = $value.Trim().Split(',')
            if ($parts.Count -ne 4) {
                throw 'invalid_progress_shape'
            }
            $complete = $parts[3] -eq '1'
            $allComplete = $allComplete -and $complete
            $observations += [ordered]@{
                worker_index = [int]$worker.worker_index
                parsebench_directories = [int]$parts[0]
                omnidocbench_directories = [int]$parts[1]
                olmocr_bench_directories = [int]$parts[2]
                all_summaries_complete = $complete
            }
        }
        catch {
            $allComplete = $false
            $observations += [ordered]@{
                worker_index = [int]$worker.worker_index
                error = $_.Exception.Message
                all_summaries_complete = $false
            }
        }
    }
    Write-ProgressRecord @{ event = 'poll'; workers = $observations }

    if ($allComplete) {
        $python = Join-Path $repository '.venv\Scripts\python.exe'
        $collector = Join-Path $repository 'benchmark\runpod_eval\collect_public_core_worker.py'
        foreach ($worker in $config.workers) {
            $receipt = Join-Path $collection ("worker-{0:d2}-collection-receipt.json" -f [int]$worker.worker_index)
            if (Test-Path -LiteralPath $receipt) {
                continue
            }
            & $python $collector `
                --worker-index ([int]$worker.worker_index) `
                --host ([string]$worker.host) `
                --port ([int]$worker.port) `
                --key $key `
                --known-hosts $knownHosts `
                --output-root $collection
            if ($LASTEXITCODE -ne 0) {
                throw "worker collection failed for $($worker.worker_index)"
            }
        }
        $terminal = [ordered]@{
            schema = 'folynta.public-core-monitor-terminal.v1'
            status = 'collected'
            worker_count = @($config.workers).Count
            collection_root = $collection
            completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        }
        $terminal | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $terminalReceipt -Encoding utf8
        Write-ProgressRecord @{ event = 'collection_completed'; collection_root = $collection }
        exit 0
    }
    Start-Sleep -Seconds $PollSeconds
}

Write-ProgressRecord @{ event = 'deadline_reached'; deadline_utc = $deadline.ToString('o') }
exit 2
