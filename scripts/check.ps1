[CmdletBinding()]
param(
    [switch]$SkipE2E,
    [switch]$SkipSecurity
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"

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

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Missing .venv. Run scripts/bootstrap.ps1 first."
}

Push-Location $projectRoot
try {
    Invoke-CheckedCommand $pythonPath @("-m", "ruff", "check", ".")
    Invoke-CheckedCommand $pythonPath @("-m", "ruff", "format", "--check", ".")
    Invoke-CheckedCommand $pythonPath @(
        "-m", "mypy", "packages", "services", "workers/cpu-document/src"
    )
    Invoke-CheckedCommand $pythonPath @("-m", "pip", "check")
    Invoke-CheckedCommand $pythonPath @(
        "-m",
        "pytest",
        "-m",
        "not provider and not slow",
        "--cov",
        "--cov-report=term-missing"
    )

    Invoke-CheckedCommand "pnpm" @("format:check")
    Invoke-CheckedCommand "pnpm" @("lint")
    Invoke-CheckedCommand "pnpm" @("typecheck")
    Invoke-CheckedCommand "pnpm" @("test")
    Invoke-CheckedCommand "pnpm" @("build")
    Invoke-CheckedCommand "pnpm" @("contracts:check")

    if (-not $SkipSecurity) {
        Invoke-CheckedCommand $pythonPath @(
            "-m", "bandit", "-c", "pyproject.toml", "-r", "packages", "services", "workers"
        )
        Invoke-CheckedCommand $pythonPath @("infra/security/validate_repository.py")
        Invoke-CheckedCommand $pythonPath @("infra/security/validate_deployment.py")
        Invoke-CheckedCommand $pythonPath @(
            "-m", "pip_audit", "--local", "--skip-editable", "--progress-spinner", "off"
        )
    }

    if (-not $SkipE2E) {
        Invoke-CheckedCommand "pnpm" @("test:e2e")
        Invoke-CheckedCommand "pnpm" @("test:e2e:live")
    }
}
finally {
    Pop-Location
}
