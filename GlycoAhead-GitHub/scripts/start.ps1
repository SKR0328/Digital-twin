param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$runtime = Join-Path $PWD '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $runtime)) { $runtime = Join-Path (Split-Path $PWD -Parent) '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $runtime)) { throw 'Run scripts/setup.ps1 first.' }
$env:OMP_NUM_THREADS = '4'
$env:OPENBLAS_NUM_THREADS = '4'
$env:MKL_NUM_THREADS = '4'
# A shared parent environment must still import this checkout's source and data.
$env:PYTHONPATH = Join-Path $PWD 'backend'
$env:GLYCOAHEAD_HOME = $PWD.Path
Write-Output "GlycoAhead: http://127.0.0.1:$Port (Ctrl+C to stop)"
& $runtime -m glycoahead.cli serve --port $Port
