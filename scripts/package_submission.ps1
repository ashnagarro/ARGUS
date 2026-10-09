$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$packageScript = Join-Path $PSScriptRoot 'package.ps1'
$archivePath = Join-Path $projectRoot 'dist\argus-demo.zip'
$verifier = Join-Path $PSScriptRoot 'verify_submission.py'
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Install the project virtual environment before packaging.'
}

& $packageScript
if ($LASTEXITCODE -ne 0) {
    throw 'Package creation failed.'
}
& $python $verifier $archivePath
if ($LASTEXITCODE -ne 0) {
    throw 'Submission verification failed.'
}
