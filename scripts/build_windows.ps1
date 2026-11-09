param(
    [string]$PythonCommand = "python",
    [string]$Version = "1.2.0"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BuildPython = Join-Path $ProjectRoot ".build-venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $BuildPython)) {
    & $PythonCommand -m venv (Join-Path $ProjectRoot ".build-venv")
    if ($LASTEXITCODE -ne 0) {
        throw "Virtual environment creation failed with exit code $LASTEXITCODE"
    }
}

& $BuildPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip bootstrap failed with exit code $LASTEXITCODE"
}
& $BuildPython -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller installation failed with exit code $LASTEXITCODE"
}

Push-Location $ProjectRoot
try {
    & $BuildPython -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --windowed `
        --name PyCursor `
        --add-data "mcp_servers;mcp_servers" `
        --add-data "examples;examples" `
        --add-data "skills;examples/workspace/skills" `
        --add-data "AGENTS.md;examples/workspace" `
        --add-data "mcp.json;." `
        --hidden-import tkinter `
        run_pycursor.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$BuiltExe = Join-Path $ProjectRoot "dist\PyCursor\PyCursor.exe"
if (-not (Test-Path -LiteralPath $BuiltExe)) {
    throw "Build did not produce $BuiltExe"
}

Write-Host ""
if (Test-Path -LiteralPath (Join-Path $ProjectRoot "dist\PyCursor-Windows-x64.zip")) {
    Remove-Item -LiteralPath (Join-Path $ProjectRoot "dist\PyCursor-Windows-x64.zip") -Force
}
Compress-Archive `
    -Path (Join-Path $ProjectRoot "dist\PyCursor\*") `
    -DestinationPath (Join-Path $ProjectRoot "dist\PyCursor-Windows-x64.zip") `
    -CompressionLevel Optimal

Write-Host "Build complete: $ProjectRoot\dist\PyCursor\PyCursor.exe"
Write-Host "Windows release: $ProjectRoot\dist\PyCursor-Windows-x64.zip"
Write-Host "Version: $Version"
Write-Host "Create an installer next with scripts\build_sfx_setup.ps1."

