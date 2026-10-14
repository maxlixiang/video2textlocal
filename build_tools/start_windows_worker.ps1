param([Parameter(Mandatory=$true)][string]$Config)
$ErrorActionPreference = 'Stop'
$project = '\\wsl.localhost\Ubuntu-24.04\home\codex\workspace\telegram-video2text'
$python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Windows Python 3.10 not found' }
# Opens WSL before accessing its UNC source. No startup/service/task registration.
& wsl.exe -d Ubuntu-24.04 -- true
if ($LASTEXITCODE -ne 0) { throw 'WSL unavailable' }
if (-not (Test-Path -LiteralPath $Config)) { throw 'Worker config missing' }
$owned = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*windows_worker.py*' -and $_.CommandLine.Contains($Config) })
if ($owned.Count -ne 0) { throw 'A worker with this config already exists; do not launch a second worker' }
& $python "$project\windows_worker.py" --config $Config
exit $LASTEXITCODE
