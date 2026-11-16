$ErrorActionPreference = "Stop"
$Source = Join-Path $PSScriptRoot "CodeProof"
$InstallRoot = if ($env:CODEPROOF_INSTALL_ROOT) {
    $env:CODEPROOF_INSTALL_ROOT
}
else {
    Join-Path $env:LOCALAPPDATA "Programs\CodeProof"
}
$Executable = Join-Path $InstallRoot "CodeProof.exe"

if (-not (Test-Path -LiteralPath (Join-Path $Source "CodeProof.exe"))) {
    throw "Install payload is incomplete: CodeProof.exe not found."
}

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
Copy-Item -Path (Join-Path $Source "*") -Destination $InstallRoot -Recurse -Force

if ($env:CODEPROOF_SKIP_SHORTCUTS -ne "1") {
    $Shell = New-Object -ComObject WScript.Shell
    $Desktop = [Environment]::GetFolderPath("Desktop")
    $Programs = [Environment]::GetFolderPath("Programs")
    foreach ($Folder in @($Desktop, $Programs)) {
        $ShortcutPath = Join-Path $Folder "CodeProof.lnk"
        $Shortcut = $Shell.CreateShortcut($ShortcutPath)
        $Shortcut.TargetPath = $Executable
        $Shortcut.WorkingDirectory = $InstallRoot
        $Shortcut.Description = "CodeProof desktop coding agent"
        $Shortcut.Save()
    }
}

if ($env:CODEPROOF_SKIP_AUTOSTART -ne "1") {
    Start-Process -FilePath $Executable -WorkingDirectory $InstallRoot
}

