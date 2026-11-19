# One-command demo for PeopleOps Copilot (Windows PowerShell).
#   .\run_demo.ps1                  seeds data, runs the story, opens the dashboard, keeps serving
#   .\run_demo.ps1 --no-browser     same, but does not open a browser
#   .\run_demo.ps1 --no-browser --no-serve   print the story and exit (good for a quick check)
# Needs Python 3.10+ and nothing else (no pip installs).

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$candidates = @(
    (Get-Command python -ErrorAction SilentlyContinue).Source,
    (Get-Command py -ErrorAction SilentlyContinue).Source
) + (Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | ForEach-Object FullName)
$python = $candidates | Where-Object { $_ } | Select-Object -First 1
if (-not $python) { Write-Error "Python 3.10+ not found. Install it from python.org, then run this again."; exit 1 }

$env:PYTHONPATH = $here
Set-Location $here
& $python -m peopleops demo @args
exit $LASTEXITCODE
