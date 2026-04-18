param(
    [int]$Port = 8000,
    [switch]$SkipInstall,
    [switch]$Seed
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Set-Location $PSScriptRoot

$pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $pythonExe)) {
    Write-Output 'Creating virtual environment in .venv...'
    py -m venv .venv
}

if (-not $SkipInstall) {
    Write-Output 'Installing dependencies...'
    & $pythonExe -m pip install -r requirements.txt
}

if ($Seed) {
    Write-Output 'Seeding local database...'
    & $pythonExe -m app.seed
} else {
    Write-Output 'Skipping seed to preserve existing local data. Use -Seed to reseed.'
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Write-Output ("Stopping existing process on port {0} (PID {1})..." -f $Port, $listener.OwningProcess)
    Stop-Process -Id $listener.OwningProcess -Force
}

Write-Output ("Starting app at http://127.0.0.1:{0}/" -f $Port)
& $pythonExe -m uvicorn app.main:app --host 127.0.0.1 --port $Port --reload
