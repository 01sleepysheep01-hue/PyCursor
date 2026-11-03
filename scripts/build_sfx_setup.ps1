param(
    [string]$RarExecutable = "C:\Program Files\WinRAR\Rar.exe"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StagingRoot = Join-Path $ProjectRoot ".sfx-stage"
$OutputPath = Join-Path $ProjectRoot "dist\PyCursor-Setup-1.0.0.exe"
$Payload = Join-Path $ProjectRoot "dist-windows\PyCursor"

if (-not (Test-Path -LiteralPath (Join-Path $Payload "PyCursor.exe"))) {
    throw "Run scripts\build_windows.ps1 first."
}
if (-not (Test-Path -LiteralPath $RarExecutable)) {
    throw "Rar.exe not found: $RarExecutable"
}

if (Test-Path -LiteralPath $StagingRoot) {
    if (-not $StagingRoot.StartsWith($ProjectRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Staging path escaped project root."
    }
    Remove-Item -LiteralPath $StagingRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $StagingRoot | Out-Null
Copy-Item -LiteralPath $Payload -Destination (Join-Path $StagingRoot "PyCursor") -Recurse
Copy-Item -LiteralPath (Join-Path $ProjectRoot "installer\setup.cmd") -Destination $StagingRoot
Copy-Item -LiteralPath (Join-Path $ProjectRoot "installer\install.ps1") -Destination $StagingRoot

Push-Location $StagingRoot
try {
    & $RarExecutable a -m5 -s -r -sfx -z"$ProjectRoot\installer\sfx-config.txt" $OutputPath "PyCursor" "setup.cmd" "install.ps1"
    if ($LASTEXITCODE -ne 0) {
        throw "Rar failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

Write-Host "Setup created: $OutputPath"

