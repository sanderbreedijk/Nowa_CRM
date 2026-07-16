$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$output = Join-Path (Split-Path -Parent $root) "outputs"
$env:PYTHONPATH = Join-Path $root "src"

python -m compileall -q (Join-Path $root "src")
python -m pytest -q
python -m PyInstaller --noconfirm --clean --windowed --onedir `
  --name NOWA_CRM --paths (Join-Path $root "src") `
  --distpath $output --workpath (Join-Path $root "build") `
  (Join-Path $root "src\nowa_crm\app.py")

$forbidden = Get-ChildItem -Recurse (Join-Path $output "NOWA_CRM") -File |
  Where-Object { $_.Name -match '\.(sqlite3|db)$' -or $_.Name -eq 'vault.key' }
if ($forbidden) { throw "Release bevat gebruikersdata of een kluissleutel." }
Write-Host "Release gereed: $output\NOWA_CRM"
