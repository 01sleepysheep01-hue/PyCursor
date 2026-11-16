param(
    [string]$PythonCommand = "python",
    [string]$Version = "1.7.0",
    [string]$Wheelhouse = "",
    [string]$BuildDirectory = ".build-venv"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BuildPython = Join-Path $ProjectRoot "$BuildDirectory\Scripts\python.exe"
$BuildTools = Join-Path $ProjectRoot ".build-tools"

if (-not (Test-Path -LiteralPath $BuildPython)) {
    & $PythonCommand -m venv (Join-Path $ProjectRoot $BuildDirectory)
    if ($LASTEXITCODE -ne 0) {
        throw "Virtual environment creation failed with exit code $LASTEXITCODE"
    }
}

$PyInstallerPython = $BuildPython
& $BuildPython -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    if (Test-Path -LiteralPath (Join-Path $BuildTools "PyInstaller")) {
        $env:PYTHONPATH = if ($env:PYTHONPATH) {
            "$BuildTools;$env:PYTHONPATH"
        }
        else {
            $BuildTools
        }
        $PyInstallerPython = $PythonCommand
        & $PyInstallerPython -c "import PyInstaller" 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw "The bundled PyInstaller environment is incomplete."
        }
    }
    else {
        & $BuildPython -m pip --version 2>$null
        if ($LASTEXITCODE -ne 0) {
            & $BuildPython -m ensurepip --upgrade
            if ($LASTEXITCODE -ne 0) {
                throw "pip is unavailable in the build environment."
            }
        }
        if ($Wheelhouse) {
            & $BuildPython -m pip install --no-index --find-links $Wheelhouse "pyinstaller==6.22.3"
        }
        else {
            & $BuildPython -m pip install pyinstaller
        }
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller installation failed with exit code $LASTEXITCODE"
        }
    }
}

Push-Location $ProjectRoot
try {
    & $PyInstallerPython -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --windowed `
        --name CodeProof `
        --add-data "mcp_servers;mcp_servers" `
        --add-data "examples;examples" `
        --add-data "skills;examples/workspace/skills" `
        --add-data "AGENTS.md;examples/workspace" `
        --add-data "web;web" `
        --add-data "mcp.json;." `
        --hidden-import tkinter `
        run_codeproof.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$BuiltExe = Join-Path $ProjectRoot "dist\CodeProof\CodeProof.exe"
if (-not (Test-Path -LiteralPath $BuiltExe)) {
    throw "Build did not produce $BuiltExe"
}

Write-Host ""
if (Test-Path -LiteralPath (Join-Path $ProjectRoot "dist\CodeProof-Windows-x64.zip")) {
    Remove-Item -LiteralPath (Join-Path $ProjectRoot "dist\CodeProof-Windows-x64.zip") -Force
}
Compress-Archive `
    -Path (Join-Path $ProjectRoot "dist\CodeProof\*") `
    -DestinationPath (Join-Path $ProjectRoot "dist\CodeProof-Windows-x64.zip") `
    -CompressionLevel Optimal

Write-Host "Build complete: $ProjectRoot\dist\CodeProof\CodeProof.exe"
Write-Host "Windows release: $ProjectRoot\dist\CodeProof-Windows-x64.zip"
Write-Host "Version: $Version"
Write-Host "Create an installer next with scripts\build_sfx_setup.ps1."

