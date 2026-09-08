# Registers two Task Scheduler jobs. Times are LOCAL (Asia/Bangkok, UTC+7):
#   15:10 local = 08:10 UTC  full run (after Surplus generates ~08:01 UTC)
#   03:10 local = 20:10 UTC  gm-only run (gm exposes exactly 24h of epochs; two runs give margin)
#
# The repo path contains a space, so the inner quotes must reach schtasks as literal \" —
# backtick-escaped quotes get stripped when PowerShell hands the /TR value to the native exe.
$script = Join-Path $PSScriptRoot "run_daily.ps1"
$full = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \`"$script\`""
$gm   = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \`"$script\`" -Only gm"

schtasks /Create /F /SC DAILY /ST 15:10 /TN "OnchainInferenceDaily" /TR $full
schtasks /Create /F /SC DAILY /ST 03:10 /TN "OnchainInferenceGmEvening" /TR $gm
schtasks /Query /TN "OnchainInferenceDaily" /V /FO LIST | Select-String "Task To Run|Status|Next Run Time"
schtasks /Query /TN "OnchainInferenceGmEvening" /V /FO LIST | Select-String "Task To Run|Status|Next Run Time"
