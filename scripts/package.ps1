$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$gitRoot = (& git -C $projectRoot rev-parse --show-toplevel).Trim().Replace('/', '\')
if ($LASTEXITCODE -ne 0 -or -not [string]::Equals(
    [IO.Path]::GetFullPath($gitRoot).TrimEnd('\'),
    [IO.Path]::GetFullPath($projectRoot).TrimEnd('\'),
    [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Run this script from the ARGUS Git checkout.'
}

$outputDir = Join-Path $projectRoot 'dist'
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
$archivePath = Join-Path $outputDir 'argus-demo.zip'
& git -C $projectRoot archive --format=zip "--output=$archivePath" HEAD -- . ':(exclude)ledger/**'
if ($LASTEXITCODE -ne 0) {
    throw 'git archive failed.'
}
Write-Output "Package: $archivePath"
