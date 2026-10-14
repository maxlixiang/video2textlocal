"""Restart only the owned follower; wait for OS processes, not just scheduler state."""
import json,os,subprocess,time
from pathlib import Path

TASK='Video2TextLocal-DockerFollower'
def quote(value):return "'"+str(value).replace("'","''")+"'"
def main():
 if os.name!='nt':raise SystemExit('Windows required')
 root=Path(os.environ['LOCALAPPDATA'])/'TelegramVideo2TextAdapter'/'launcher'
 settings=json.loads((root/'settings.json').read_text(encoding='utf-8'))
 script="""$ErrorActionPreference='Stop'
$name='Video2TextLocal-DockerFollower'
$supervisor=SUPERVISOR
$config=CONFIG
$t=Get-ScheduledTask -TaskName $name
if ($t.Actions.Arguments -notlike ('*'+$supervisor+'*')) {throw 'unexpected task action'}
Stop-ScheduledTask -TaskName $name
$deadline=(Get-Date).AddSeconds(30)
do {
 $owned=@(Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'pythonw.exe' -and $_.CommandLine.Contains($supervisor)) -or ($_.Name -eq 'python.exe' -and $_.CommandLine -like '*windows_worker.py*' -and $_.CommandLine.Contains($config)) })
 if ($owned.Count -eq 0) {break}
 Start-Sleep -Milliseconds 250
} while ((Get-Date) -lt $deadline)
if ($owned.Count -ne 0) {throw 'owned processes still exiting; no replacement started'}
Start-ScheduledTask -TaskName $name
Write-Output 'owned_processes_exited_then_task_started'
"""
 script=script.replace('SUPERVISOR',quote(root/'windows_supervisor.py')).replace('CONFIG',quote(settings['worker_config']))
 result=subprocess.run(['powershell.exe','-NoProfile','-Command',script],capture_output=True,text=True)
 if result.returncode:raise SystemExit('follower_restart_failed; inspect owned task; no credentials printed')
 # Do not report success until the new follower actually owns a live worker.
 deadline=time.time()+40;started=time.time()
 while time.time()<deadline:
  try:
   status=json.loads((root/'status.json').read_text())
   if status.get('checked_at',0)>=started and status.get('state')=='running':
    print(json.dumps({'restarted':True,'worker_pid':status['worker_pid'],'state':'running'}));return 0
  except (OSError,ValueError):pass
  time.sleep(1)
 raise SystemExit('follower_restart_not_ready; check Docker/credentials before retrying')
if __name__=='__main__':raise SystemExit(main())
