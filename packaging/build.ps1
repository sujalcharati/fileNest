# Builds FileNest.exe (PyInstaller) and FileNestSetup.exe (Inno Setup).
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1 [-Version 0.2.0] [-SkipInstaller]
#
# Output:  build\dist\FileNest\FileNest.exe   and   build\installer\FileNestSetup.exe

param(
    [string]$Version = "",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# Python: the project's .venv locally, or whatever "python" is on PATH (CI).
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

if (-not $Version) {
    $Version = & $Python -c "import filenest; print(filenest.__version__)"
}
$Version = $Version.Trim().TrimStart("v")
Write-Host "== Building FileNest $Version" -ForegroundColor Cyan

$Build = Join-Path $Root "build"
$Icon = Join-Path $Build "FileNest.ico"

Write-Host "== 1/3 Icon"
& $Python packaging\make_icon.py $Icon
if ($LASTEXITCODE -ne 0) { throw "icon generation failed" }

Write-Host "== 2/3 FileNest.exe (PyInstaller)"
& $Python -m PyInstaller --noconfirm --clean --windowed `
    --name FileNest `
    --icon $Icon `
    --distpath (Join-Path $Build "dist") `
    --workpath (Join-Path $Build "work") `
    --specpath $Build `
    --exclude-module tkinter `
    FileNest.pyw
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# Remove Qt parts FileNest never uses (QML/Quick, PDF, virtual keyboard, software
# OpenGL, extra platform plugins, translations). Roughly halves the download.
$Qt = Join-Path $Build "dist\FileNest\_internal\PySide6"
$Unused = @(
    "opengl32sw.dll", "Qt6Pdf.dll", "Qt6Quick.dll", "Qt6Qml.dll", "Qt6QmlMeta.dll",
    "Qt6QmlModels.dll", "Qt6QmlWorkerScript.dll", "Qt6VirtualKeyboard.dll", "Qt6OpenGL.dll",
    "translations",
    "plugins\imageformats\qpdf.dll",
    "plugins\platforminputcontexts",
    "plugins\generic",
    "plugins\platforms\qdirect2d.dll", "plugins\platforms\qminimal.dll", "plugins\platforms\qoffscreen.dll",
    "plugins\tls\qopensslbackend.dll", "plugins\tls\qcertonlybackend.dll"
)
foreach ($item in $Unused) {
    $p = Join-Path $Qt $item
    if (Test-Path $p) { Remove-Item $p -Recurse -Force }
}

if ($SkipInstaller) {
    Write-Host "Done (installer skipped): build\dist\FileNest\FileNest.exe" -ForegroundColor Green
    exit 0
}

Write-Host "== 3/3 FileNestSetup.exe (Inno Setup)"
$Iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    throw "Inno Setup 6 not found. Install it:  winget install JRSoftware.InnoSetup"
}
& $Iscc "/DAppVersion=$Version" "/Q" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

Write-Host "Done: build\installer\FileNestSetup.exe" -ForegroundColor Green
