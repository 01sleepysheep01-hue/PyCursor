$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$OutputRoot = Join-Path $ProjectRoot "dist"
$StageRoot = Join-Path $OutputRoot "PyCursor-Portable"
$ZipPath = Join-Path $OutputRoot "PyCursor-Portable.zip"

if (-not $OutputRoot.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Output path escaped the project root."
}

if (Test-Path -LiteralPath $StageRoot) {
    Remove-Item -LiteralPath $StageRoot -Recurse -Force
}
if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

New-Item -ItemType Directory -Force -Path $StageRoot | Out-Null
foreach ($Name in @("pycursor", "mcp_servers", "examples", "scripts", "installer", "tests", "docs", "README.md", "report.md", "SUBMISSION.md", "RELEASE_NOTES_v1.0.0.md", "demo.mp4", "LICENSE", "pyproject.toml", "mcp.json", ".env.example", "PyCursor.cmd", "run_pycursor.py")) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot $Name) -Destination $StageRoot -Recurse
}

Get-ChildItem -LiteralPath $StageRoot -Recurse -Directory |
    Where-Object { $_.Name -eq "__pycache__" } |
    Remove-Item -Recurse -Force

Compress-Archive -Path (Join-Path $StageRoot "*") -DestinationPath $ZipPath -CompressionLevel Optimal
if (-not $StageRoot.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Stage path escaped the project root."
}
Remove-Item -LiteralPath $StageRoot -Recurse -Force
Write-Host "Portable release: $ZipPath"

