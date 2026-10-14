"""Install only a named current-user task, with no credentials in its action."""
import argparse,json,os,shutil,subprocess,sys
from pathlib import Path
TASK='Video2TextLocal-DockerFollower'

def main():
    p=argparse.ArgumentParser();p.add_argument('--worker-config',required=True);a=p.parse_args()
    if os.name!='nt':raise SystemExit('Run with Windows Python')
    project=Path(__file__).resolve().parents[1];target=Path(os.environ['LOCALAPPDATA'])/'TelegramVideo2TextAdapter'/'launcher';target.mkdir(parents=True,exist_ok=True)
    config=Path(a.worker_config)
    if not config.is_file():raise SystemExit('worker_config_missing')
    python=Path(sys.executable);pythonw=python.with_name('pythonw.exe')
    if not pythonw.is_file():raise SystemExit('pythonw_missing')
    shutil.copyfile(project/'build_tools/windows_supervisor.py',target/'windows_supervisor.py')
    settings={'python':str(python),'worker_script':str(project/'windows_worker.py'),'worker_config':str(config),'wsl_distribution':'Ubuntu-24.04'}
    (target/'settings.json').write_text(json.dumps(settings),encoding='utf-8')
    # Refuse existing unrelated task rather than overwriting it.
    def quote(value):return "'"+str(value).replace("'","''")+"'"
    script='''$ErrorActionPreference='Stop'
$name='Video2TextLocal-DockerFollower'
$existing=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($existing) { throw 'Task already exists; inspect before changing it' }
$user=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action=New-ScheduledTaskAction -Execute PYTHONW -Argument ARGS -WorkingDirectory ROOT
$trigger=New-ScheduledTaskTrigger -AtLogOn -User $user
$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Follows Docker Desktop for the independent Video2TextLocal Windows worker' | Out-Null
Write-Output 'current_user_task_registered'
'''
    arguments='"'+str(target/'windows_supervisor.py')+'" --settings "'+str(target/'settings.json')+'"'
    script=script.replace('PYTHONW',quote(pythonw)).replace('ARGS',quote(arguments)).replace('ROOT',quote(target))
    result=subprocess.run(['powershell.exe','-NoProfile','-Command',script],capture_output=True,text=True)
    if result.returncode:
        # No platform error/env/credential dumps; user can run the exact installer interactively.
        print('task_registration_failed; run this installer in an authorized Windows terminal; no task started')
        return 1
    print(result.stdout.strip());return 0
if __name__=='__main__':raise SystemExit(main())
