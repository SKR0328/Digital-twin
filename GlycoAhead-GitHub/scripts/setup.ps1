param([Parameter(Mandatory=$true)][string]$DatasetPath, [string]$Python = 'python', [string]$Node = 'node')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:GLYCOAHEAD_HOME = $PWD.Path
$DatasetPath = (Resolve-Path -LiteralPath $DatasetPath).Path
if (-not (Test-Path -LiteralPath (Join-Path $DatasetPath 'Shanghai_T2DM_Summary.xlsx'))) {
    throw 'DatasetPath must contain Shanghai_T2DM/ and Shanghai_T2DM_Summary.xlsx.'
}
& $Python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required. Pass -Python with its executable path.' }
$runtime = Join-Path $PWD '.venv\Scripts\python.exe'
& $runtime -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& $runtime -m pip install --no-deps -e .
if ($LASTEXITCODE -ne 0) { throw 'Project installation failed' }
$env:OMP_NUM_THREADS = '4'
$env:OPENBLAS_NUM_THREADS = '4'
$env:MKL_NUM_THREADS = '4'
& $runtime -m glycoahead.cli import-shanghai $DatasetPath
if ($LASTEXITCODE -ne 0) { throw 'Dataset import failed' }
& $runtime -m glycoahead.cli install-model release/selected_model
if ($LASTEXITCODE -ne 0) { throw 'Packaged model installation failed' }
$nodeVersion = & $Node -p 'Number(process.versions.node.split(".")[0])'
if ([int]$nodeVersion -lt 22) { throw 'Use Node.js 22.12+ or 24 LTS for the frontend.' }
$nodePath = (Get-Command $Node).Source
$env:PATH = (Split-Path $nodePath -Parent) + [IO.Path]::PathSeparator + $env:PATH
Push-Location frontend
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependencies failed' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
} finally { Pop-Location }
Write-Output 'Ready. Run .\scripts\start.ps1 and open http://127.0.0.1:8000'
