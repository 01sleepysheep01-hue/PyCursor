$ErrorActionPreference = "Stop"
$Source = Join-Path $PSScriptRoot "PyCursor"
$InstallRoot = if ($env:PYCURSOR_INSTALL_ROOT) {
    $env:PYCURSOR_INSTALL_ROOT
}
else {
    Join-Path $env:LOCALAPPDATA "Programs\PyCursor"
}
$Executable = Join-Path $InstallRoot "PyCursor.exe"

if (-not (Test-Path -LiteralPath (Join-Path $Source "PyCursor.exe"))) {
    throw "Install payload is incomplete: PyCursor.exe not found."
}

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
Copy-Item -Path (Join-Path $Source "*") -Destination $InstallRoot -Recurse -Force

if ($env:PYCURSOR_SKIP_SHORTCUTS -ne "1") {
    $Shell = New-Object -ComObject WScript.Shell
    $Desktop = [Environment]::GetFolderPath("Desktop")
    $Programs = [Environment]::GetFolderPath("Programs")
    foreach ($Folder in @($Desktop, $Programs)) {
        $ShortcutPath = Join-Path $Folder "PyCursor.lnk"
        $Shortcut = $Shell.CreateShortcut($ShortcutPath)
        $Shortcut.TargetPath = $Executable
        $Shortcut.WorkingDirectory = $InstallRoot
        $Shortcut.Description = "PyCursor desktop coding agent"
        $Shortcut.Save()
    }
}

Start-Process -FilePath $Executable -WorkingDirectory $InstallRoot

