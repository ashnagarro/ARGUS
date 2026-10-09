$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$gitRoot = (& git -C $projectRoot rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0 -or -not [string]::Equals($gitRoot, $projectRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Run this script from the ARGUS Git checkout.'
}

$outputDir = Join-Path $projectRoot 'dist'
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
$archivePath = Join-Path $outputDir 'argus-demo.zip'
& git -C $projectRoot archive --format=zip "--output=$archivePath" HEAD
if ($LASTEXITCODE -ne 0) {
    throw 'git archive failed.'
}
Write-Output "Package: $archivePath"
