param(
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [Parameter(Mandatory = $true)][string]$InstallDir
)
$ErrorActionPreference = 'Stop'
$setup = (Resolve-Path -LiteralPath $InstallerPath).Path
$target = [IO.Path]::GetFullPath($InstallDir)
$desktopLink = Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'Amos電腦手機連結器.lnk'
$programFolder = Join-Path ([Environment]::GetFolderPath('Programs')) 'Amos電腦手機連結器'
$menuLink = Join-Path $programFolder 'Amos電腦手機連結器.lnk'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{9ABF5441-8F5B-4352-80DC-F3B87625F2E9}_is1'
foreach ($path in @($target, $desktopLink, $programFolder, $uninstallKey)) {
    if (Test-Path -LiteralPath $path) { throw "Installer test requires an unused location: $path" }
}
$uninstaller = Join-Path $target 'unins000.exe'
try {
    $process = Start-Process -FilePath $setup -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', ('/DIR="' + $target + '"')) -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) { throw "Installer exit code: $($process.ExitCode)" }
    $exe = Join-Path $target 'AureoLink.exe'
    foreach ($path in @($exe, $desktopLink, $menuLink, $uninstaller, $uninstallKey)) {
        if (-not (Test-Path -LiteralPath $path)) { throw "Installed item missing: $path" }
    }
    $shell = New-Object -ComObject WScript.Shell
    foreach ($path in @($desktopLink, $menuLink)) {
        $inspectionLink = Join-Path $env:RUNNER_TEMP 'Amos-shortcut-inspection.lnk'
        Copy-Item -LiteralPath $path -Destination $inspectionLink -Force
        try { $shortcut = $shell.CreateShortcut($inspectionLink) }
        finally { Remove-Item -LiteralPath $inspectionLink -Force }
        if ($shortcut.TargetPath -ne $exe) { throw "Shortcut points to the wrong executable: $path; actual='$($shortcut.TargetPath)'; expected='$exe'" }
        if ($shortcut.WorkingDirectory -ne $target) { throw "Shortcut working directory is incorrect: $path" }
    }
    $registration = Get-ItemProperty -LiteralPath $uninstallKey
    if ($registration.DisplayVersion -ne '2.0.1') { throw 'Installed version is incorrect' }
    Write-Output 'PASS: install, default desktop shortcut, Start menu shortcut, and uninstall registration'
}
finally {
    if (Test-Path -LiteralPath $uninstaller) {
        $process = Start-Process -FilePath $uninstaller -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -Wait -PassThru -WindowStyle Hidden
        if ($process.ExitCode -ne 0) { throw "Uninstaller exit code: $($process.ExitCode)" }
    }
}
foreach ($path in @($desktopLink, $menuLink, $uninstallKey, (Join-Path $target 'AureoLink.exe'))) {
    if (Test-Path -LiteralPath $path) { throw "Uninstall did not remove its installed item: $path" }
}
Write-Output 'PASS: uninstall removes the installed application, shortcuts, and registration'
