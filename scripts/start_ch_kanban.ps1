param([switch]$SelfTest)

# Windows PowerShell 5.1 compatible. No policy changes, installs or environment creation.
$ErrorActionPreference = 'Stop'
$logFile = $null

function Test-UnderRoot([string]$Path, [string]$Root) {
    if (-not $Root -or -not [IO.Path]::IsPathRooted($Path)) { return $false }
    $full = [IO.Path]::GetFullPath($Path)
    $parent = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    return $full.StartsWith($parent, [StringComparison]::OrdinalIgnoreCase)
}

function Test-AllowedConda([string]$Path) {
    foreach ($root in @($env:USERPROFILE, $env:ProgramData, $env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (Test-UnderRoot $Path $root) { return $true }
    }
    return $false
}

function Find-Conda {
    if ($env:CONDA_EXE) {
        if (-not (Test-AllowedConda $env:CONDA_EXE) -or -not (Test-Path -LiteralPath $env:CONDA_EXE -PathType Leaf)) {
            throw 'CONDA_EXE must point to your own conda or an approved all-users conda installation.'
        }
        return $env:CONDA_EXE
    }
    foreach ($root in @($env:USERPROFILE, $env:ProgramData, $env:ProgramFiles)) {
        if (-not $root) { continue }
        foreach ($name in @('miniconda3', 'anaconda3', 'miniforge3', 'mambaforge')) {
            foreach ($relative in @('Scripts\conda.exe', 'condabin\conda.bat')) {
                $candidate = Join-Path (Join-Path $root $name) $relative
                if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
            }
        }
    }
    foreach ($command in @(Get-Command conda.exe -All -ErrorAction SilentlyContinue)) {
        if (Test-AllowedConda $command.Source) { return $command.Source }
    }
    throw 'conda was not found. Ask your administrator to prepare conda, or set your user CONDA_EXE.'
}

function Write-StartupLog([string]$Message) {
    Add-Content -LiteralPath $script:logFile -Value $Message -Encoding UTF8
    Write-Host $Message
}

function Invoke-CondaPython([string[]]$PythonArgs) {
    & $script:conda run -p $script:prefix --no-capture-output $script:python @PythonArgs 2>&1 |
        ForEach-Object { Write-StartupLog "$_" }
    if ($LASTEXITCODE -ne 0) { throw "conda / DIG_new Python failed (exit $LASTEXITCODE). See the startup log." }
}

try {
    if (-not $env:USERPROFILE) { throw 'USERPROFILE is missing. Sign in with your Windows account.' }
    $local = $env:LOCALAPPDATA
    if (-not $local) { $local = Join-Path $env:USERPROFILE 'AppData\Local' }
    $logDir = Join-Path $local 'CHKanban\output\logs'
    [IO.Directory]::CreateDirectory($logDir) | Out-Null
    $logFile = Join-Path $logDir ('startup_' + [guid]::NewGuid().ToString('N') + '.log')
    "Started: $(Get-Date -Format o)" | Set-Content -LiteralPath $logFile -Encoding UTF8
    Write-Host "Log: $logFile"

    # A name alone is ambiguous with shared conda installs. Never guess or fall back to base.
    if (-not [IO.Path]::IsPathRooted($env:CH_KANBAN_ENV_PREFIX)) {
        throw 'CH_KANBAN_ENV_PREFIX must be an absolute path to your DIG_new folder.'
    }
    $prefix = [IO.Path]::GetFullPath($env:CH_KANBAN_ENV_PREFIX)
    if (-not (Test-UnderRoot $prefix $env:USERPROFILE) -or (Split-Path $prefix -Leaf) -ine 'DIG_new') {
        throw 'CH_KANBAN_ENV_PREFIX must be an absolute DIG_new folder under your own USERPROFILE (not base or another user).'
    }
    $python = Join-Path $prefix 'python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or -not (Test-Path -LiteralPath (Join-Path $prefix 'conda-meta') -PathType Container)) {
        throw 'Your DIG_new environment or python.exe was not found. Prepare it using the approved setup procedure.'
    }
    $conda = Find-Conda
    $appDir = Split-Path -Parent $PSScriptRoot
    Set-Location -LiteralPath $appDir
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONPATH = $appDir
    Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    $env:CONDA_REPORT_ERRORS = 'false'
    $env:CONDA_OFFLINE = 'true'
    Write-StartupLog "Conda: $conda`nDIG_new: $prefix`nApp: $appDir"
    Invoke-CondaPython @('-B', '-m', 'src.app.startup_check', '--expected-python', $python)
    if (-not $SelfTest) {
        Invoke-CondaPython @('-B', '-m', 'src.app.gui')
    }
    exit 0
} catch {
    $message = '[ERROR] ' + $_.Exception.Message
    Write-Host $message
    if ($logFile) {
        try { Add-Content -LiteralPath $logFile -Value $message -Encoding UTF8 } catch { Write-Host '[ERROR] Could not write the startup log.' }
    }
    exit 1
}
