# Full daily run: scrape all sources, rebuild data.json. Exit code propagates to Task Scheduler.
param([string]$Only)
Set-Location $PSScriptRoot
$log = Join-Path $PSScriptRoot "scrape.log"
"=== $(Get-Date -Format o) only=$Only ===" | Out-File -Append -Encoding utf8 $log
if ($Only) { uv run python scrape.py --only $Only 2>&1 | Out-File -Append -Encoding utf8 $log }
else       { uv run python scrape.py                2>&1 | Out-File -Append -Encoding utf8 $log }
$rc = $LASTEXITCODE
uv run python build.py 2>&1 | Out-File -Append -Encoding utf8 $log
exit $rc
