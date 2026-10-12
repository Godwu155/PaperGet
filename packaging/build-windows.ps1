param(
    [string]$OutputDir = 'dist'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$outputPath = if ([System.IO.Path]::IsPathRooted($OutputDir)) {
    $OutputDir
} else {
    Join-Path $repoRoot $OutputDir
}
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Create .venv and install paperget[gui] plus Nuitka before building.'
}

$env:TMP = Join-Path $repoRoot '.tmp'
$env:TEMP = $env:TMP
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null
$iconPath = Join-Path $repoRoot 'src\paperget\assets\paperget.ico'
& $pythonExe (Join-Path $PSScriptRoot 'make-icon.py')
if ($LASTEXITCODE -ne 0) {
    throw "Icon generation failed with exit code $LASTEXITCODE"
}

$arguments = @(
    '-m', 'nuitka',
    (Join-Path $PSScriptRoot 'windows_main.py'),
    '--standalone',
    '--enable-plugin=pyside6',
    '--include-package=paperget',
    '--include-package-data=paperget',
    '--include-module=keyring.backends.Windows',
    '--noinclude-qt-translations',
    '--windows-console-mode=disable',
    "--windows-icon-from-ico=$iconPath",
    '--assume-yes-for-downloads',
    '--output-filename=PaperGet.exe',
    "--output-dir=$outputPath"
)
& $pythonExe @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Windows build failed with exit code $LASTEXITCODE"
}
$standaloneDir = Join-Path $outputPath 'windows_main.dist'
# PaperGet opens PDFs with the system viewer; Qt's PDF image plugin is unused.
# Keep qt6pdf.dll: Qt also links against it during application startup.
$unusedPdfPlugin = Join-Path $standaloneDir 'PySide6\qt-plugins\imageformats\qpdf.dll'
if (Test-Path -LiteralPath $unusedPdfPlugin) {
    Remove-Item -LiteralPath $unusedPdfPlugin
}
Copy-Item -LiteralPath (Join-Path $repoRoot 'LICENSE') -Destination (Join-Path $standaloneDir 'LICENSE')
& $pythonExe (Join-Path $PSScriptRoot 'make-notices.py') $standaloneDir
if ($LASTEXITCODE -ne 0) {
    throw "Third-party notice generation failed with exit code $LASTEXITCODE"
}
