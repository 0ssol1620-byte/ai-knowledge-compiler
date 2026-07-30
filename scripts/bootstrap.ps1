[CmdletBinding()]
param(
    [switch]$SkipNode,
    [switch]$SkipPython,
    [ValidatePattern("^https://")]
    [string]$PythonIndexUrl = "https://pypi.org/simple"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory, Position = 0)]
        [string]$FilePath,
        [Parameter(Mandatory, Position = 1, ValueFromRemainingArguments)]
        [string[]]$ArgumentList
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath exited with code $LASTEXITCODE."
    }
}

Push-Location $projectRoot
try {
    if (-not $SkipPython) {
        if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
            Invoke-CheckedCommand "py" @("-3", "-m", "venv", ".venv")
        }
        # A venv-local override prevents machine-global secondary indexes from
        # silently participating in build-isolation dependency resolution.
        Invoke-CheckedCommand ".venv\Scripts\python.exe" @(
            "-m", "pip", "config", "--site", "set", "global.index-url", $PythonIndexUrl
        )
        Invoke-CheckedCommand ".venv\Scripts\python.exe" @(
            "-m", "pip", "config", "--site", "set", "global.extra-index-url", $PythonIndexUrl
        )
        Invoke-CheckedCommand ".venv\Scripts\python.exe" @(
            "-m", "pip", "install", "--index-url", $PythonIndexUrl, "--upgrade", "pip"
        )
        Invoke-CheckedCommand ".venv\Scripts\python.exe" @(
            "-m", "pip", "install", "--index-url", $PythonIndexUrl, "-e", ".[dev]"
        )
        Invoke-CheckedCommand ".venv\Scripts\uv.exe" @(
            "sync",
            "--locked",
            "--extra",
            "dev",
            "--inexact",
            "--python",
            ".venv\Scripts\python.exe"
        )
    }

    if (-not $SkipNode) {
        Invoke-CheckedCommand "pnpm" @("install", "--no-frozen-lockfile")
    }

    if (-not (Test-Path -LiteralPath ".env")) {
        Copy-Item -LiteralPath ".env.example" -Destination ".env"
        Write-Host "Created .env from .env.example. Replace all non-local secrets before deployment."
    }
}
finally {
    Pop-Location
}
