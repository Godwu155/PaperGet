$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Create .venv and install paperget[gui] plus Nuitka before building.'
}

$env:TMP = Join-Path $repoRoot '.tmp'
$env:TEMP = $env:TMP
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null

$arguments = @(
    '-m', 'nuitka',
    (Join-Path $PSScriptRoot 'windows_main.py'),
    '--standalone',
    '--enable-plugin=pyside6',
    '--include-package=paperget',
    '--include-module=keyring.backends.Windows',
    '--noinclude-qt-translations',
    '--include-qt-plugins=platforminputcontexts',
    '--windows-console-mode=disable',
    '--assume-yes-for-downloads',
    '--output-filename=PaperGet.exe',
    "--output-dir=$(Join-Path $repoRoot 'dist')"
)
& $pythonExe @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Windows build failed with exit code $LASTEXITCODE"
}
