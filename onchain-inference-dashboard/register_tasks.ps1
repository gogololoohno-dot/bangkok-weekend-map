# Registers the daily Task Scheduler job. Time is LOCAL (Asia/Bangkok, UTC+7):
#   15:10 local = 08:10 UTC  (after Surplus generates ~08:01 UTC and Engy's hourly rollup lands)
#
# The repo path contains a space, so the inner quotes must reach schtasks as literal \" —
# backtick-escaped quotes get stripped when PowerShell hands the /TR value to the native exe.
$script = Join-Path $PSScriptRoot "run_daily.ps1"
$full = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \`"$script\`""

schtasks /Create /F /SC DAILY /ST 15:10 /TN "OnchainInferenceDaily" /TR $full
schtasks /Query /TN "OnchainInferenceDaily" /V /FO LIST | Select-String "Task To Run|Status|Next Run Time"
