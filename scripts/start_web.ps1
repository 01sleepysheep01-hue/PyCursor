param(
    [int]$Port = 8765,
    [switch]$Lan,
    [string]$Workspace = ".\examples\workspace"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonCommand = if (Test-Path -LiteralPath (Join-Path $ProjectRoot ".build-venv\Scripts\python.exe")) {
    Join-Path $ProjectRoot ".build-venv\Scripts\python.exe"
}
else {
    "python"
}
$HostAddress = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }
$GeneratedToken = $null

if ($Lan -and -not $env:PYCURSOR_WEB_TOKEN) {
    $bytes = New-Object byte[] 24
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    $GeneratedToken = [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
    $env:PYCURSOR_WEB_TOKEN = $GeneratedToken
}

Write-Host "CodeProof H5 (本机): http://127.0.0.1:$Port/"
if ($Lan) {
    $addresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            $_.AddressState -eq "Preferred"
        } |
        Select-Object -ExpandProperty IPAddress -Unique
    foreach ($address in $addresses) {
        Write-Host "CodeProof H5 (同一 Wi-Fi): http://${address}:$Port/"
    }
    if ($GeneratedToken) {
        Write-Host "本次访问令牌: $GeneratedToken"
    }
    else {
        Write-Host "访问令牌: 使用已设置的 PYCURSOR_WEB_TOKEN"
    }
}
Write-Host "工作区: $Workspace"
Write-Host "按 Ctrl+C 停止服务。"

Push-Location $ProjectRoot
try {
    & $PythonCommand -m pycursor.server --host $HostAddress --port $Port --workspace $Workspace
    if ($LASTEXITCODE -ne 0) {
        throw "CodeProof H5 server exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
