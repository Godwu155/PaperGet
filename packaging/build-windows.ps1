param(
    [string]$OutputDir = 'dist',
    [string]$PythonExe = '.venv\Scripts\python.exe'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$outputPath = if ([System.IO.Path]::IsPathRooted($OutputDir)) {
    $OutputDir
} else {
    Join-Path $repoRoot $OutputDir
}
$pythonExe = if ([System.IO.Path]::IsPathRooted($PythonExe)) {
    $PythonExe
} else {
    Join-Path $repoRoot $PythonExe
}
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Create a Python 3.12 virtual environment and install paperget[gui] plus Nuitka before building.'
}
$pythonVersion = & $pythonExe -c 'import sys; print(sys.version_info.major, sys.version_info.minor, sep=chr(46))'
if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne '3.12') {
    throw "Windows builds currently require Python 3.12; found $pythonVersion."
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
    '--zig',
    '--enable-plugin=pyside6',
    '--include-package=paperget',
    '--include-package-data=paperget',
    '--include-module=keyring.backends.Windows',
    '--noinclude-qt-translations',
    # Nuitka 4.1.1's disable mode can fail at startup with codeobject.c:356.
    # Attach uses an existing console without opening one from Explorer.
    '--windows-console-mode=attach',
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
# Qt Essentials includes the PDF image plugin, which PaperGet never uses.
$unusedPdfPlugin = Join-Path $standaloneDir 'PySide6\qt-plugins\imageformats\qpdf.dll'
if (Test-Path -LiteralPath $unusedPdfPlugin) {
    Remove-Item -LiteralPath $unusedPdfPlugin
}
Copy-Item -LiteralPath (Join-Path $repoRoot 'LICENSE') -Destination (Join-Path $standaloneDir 'LICENSE')
& $pythonExe (Join-Path $PSScriptRoot 'make-notices.py') $standaloneDir
if ($LASTEXITCODE -ne 0) {
    throw "Third-party notice generation failed with exit code $LASTEXITCODE"
}
