# Registers two Task Scheduler jobs. Times are LOCAL (Asia/Bangkok, UTC+7):
#   15:10 local = 08:10 UTC  full run (after Surplus generates ~08:01 UTC)
#   03:10 local = 20:10 UTC  gm-only run (gm exposes exactly 24h of epochs; two runs give margin)
$here = $PSScriptRoot
$ps = "powershell.exe"
$full = "-NoProfile -ExecutionPolicy Bypass -File `"$here\run_daily.ps1`""
$gm   = "-NoProfile -ExecutionPolicy Bypass -File `"$here\run_daily.ps1`" -Only gm"

schtasks /Create /F /SC DAILY /ST 15:10 /TN "OnchainInferenceDaily" /TR "$ps $full"
schtasks /Create /F /SC DAILY /ST 03:10 /TN "OnchainInferenceGmEvening" /TR "$ps $gm"
schtasks /Query /TN "OnchainInferenceDaily"
schtasks /Query /TN "OnchainInferenceGmEvening"
