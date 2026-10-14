"""Current-user Docker Desktop follower; never starts/stops Docker itself.
Installed locally so idle supervision does not depend on WSL or this chat.
"""
import argparse
import ctypes
import json
import logging
import logging.handlers
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from ctypes import wintypes as w

class ProcessEntry(ctypes.Structure):
    _fields_=[('size',w.DWORD),('usage',w.DWORD),('pid',w.DWORD),('heap',ctypes.c_size_t),('module',w.DWORD),('threads',w.DWORD),('parent',w.DWORD),('priority',w.LONG),('flags',w.DWORD),('exe',w.WCHAR*260)]


def desktop_running():
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD];k.CreateToolhelp32Snapshot.restype=w.HANDLE
    k.Process32FirstW.argtypes=[w.HANDLE,ctypes.POINTER(ProcessEntry)];k.Process32NextW.argtypes=k.Process32FirstW.argtypes;k.CloseHandle.argtypes=[w.HANDLE]
    handle=k.CreateToolhelp32Snapshot(2,0)
    if handle in (None,ctypes.c_void_p(-1).value):raise OSError('process_snapshot_failed')
    names=set();entry=ProcessEntry();entry.size=ctypes.sizeof(entry)
    try:
        valid=k.Process32FirstW(handle,ctypes.byref(entry))
        while valid:
            names.add(entry.exe.lower());valid=k.Process32NextW(handle,ctypes.byref(entry))
    finally:k.CloseHandle(handle)
    return {'docker desktop.exe','com.docker.backend.exe'} <= names


class Job:
    """Own only our child tree. Closing supervisor also closes this job handle."""
    def __init__(self,process):
        class Basic(ctypes.Structure):
            _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),('flags',w.DWORD),('min_ws',ctypes.c_size_t),('max_ws',ctypes.c_size_t),('active_limit',w.DWORD),('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
        class IO(ctypes.Structure):
            _fields_=[(n,ctypes.c_ulonglong) for n in ('read_count','write_count','other_count','read_bytes','write_bytes','other_bytes')]
        class Extended(ctypes.Structure):
            _fields_=[('basic',Basic),('io',IO),('process_limit',ctypes.c_size_t),('job_limit',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
        self.k=ctypes.WinDLL('kernel32',use_last_error=True)
        self.k.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];self.k.CreateJobObjectW.restype=w.HANDLE
        self.k.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
        self.k.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE];self.k.CloseHandle.argtypes=[w.HANDLE]
        self.handle=self.k.CreateJobObjectW(None,None);value=Extended();value.basic.flags=0x2000
        if not self.handle or not self.k.SetInformationJobObject(self.handle,9,ctypes.byref(value),ctypes.sizeof(value)) or not self.k.AssignProcessToJobObject(self.handle,w.HANDLE(int(process._handle))):
            if self.handle:self.k.CloseHandle(self.handle)
            process.terminate();process.wait(timeout=10);raise OSError('worker_job_attachment_failed')
    def close(self):
        if self.handle:self.k.CloseHandle(self.handle);self.handle=None


class Controller:
    def __init__(self,command,log,job_factory=Job,popen=subprocess.Popen):
        self.command=command;self.log=log;self.job_factory=job_factory;self.popen=popen
        self.process=None;self.job=None;self.next_start=0;self.failures=0;self.state='waiting_for_docker';self.last_desktop=False
    def stop(self,reason):
        if self.job:self.job.close();self.job=None
        if self.process:
            if self.process.poll() is None:
                try:self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=10)
            self.process=None;self.log.info(reason)
    def step(self,desktop,ready,now):
        if not desktop:
            self.stop('worker_stopped_with_docker');self.state='waiting_for_docker';self.failures=0;self.next_start=0;self.last_desktop=False;return
        self.last_desktop=True
        if self.process:
            code=self.process.poll()
            if code is None:self.state='running';return
            self.stop('worker_exited');self.failures+=1;self.next_start=now+(min(60,2**min(self.failures,6)) if self.failures<3 else 300)
        if now<self.next_start:self.state='restart_backoff';return
        if not ready:self.state='waiting_for_services_or_credentials';return
        self.process=self.popen(self.command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.job=self.job_factory(self.process);self.state='running';self.log.info('worker_started')


def adapter_ready(config):
    try:
        value=json.loads(Path(config).read_text(encoding='utf-8'))
        if value.get('credential_manifest'):value.update(json.loads(Path(value['credential_manifest']).read_text(encoding='utf-8')))
        # Dedicated loopback only; no environment/global proxy use.
        from urllib.parse import urlsplit
        url=urlsplit(value['endpoint'])
        if url.scheme!='https' or url.hostname not in ('127.0.0.1','localhost') or url.username or url.password:return False
        ctx=ssl.create_default_context(cafile=value['ca']);ctx.load_cert_chain(value['cert'],value['key'])
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ctx))
        request=urllib.request.Request(value['endpoint'].rstrip('/')+'/v1/retention',data=b'{}',headers={'Content-Type':'application/json'})
        with opener.open(request,timeout=3) as response:
            data=json.loads(response.read(32768));return not data.get('error')
    except Exception:return False


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--settings',required=True);args=parser.parse_args()
    if os.name!='nt':raise SystemExit('Windows required')
    import msvcrt
    settings_path=Path(args.settings);settings=json.loads(settings_path.read_text(encoding='utf-8'));directory=settings_path.parent
    lock=(directory/'supervisor.lock').open('a+b');lock.seek(0)
    try:
        lock.write(b'0');lock.flush();lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:return 0
    logger=logging.getLogger('v2t-supervisor');logger.setLevel(logging.INFO)
    logger.addHandler(logging.handlers.RotatingFileHandler(directory/'supervisor.log',maxBytes=1024**2,backupCount=2,encoding='utf-8'))
    controller=Controller([settings['python'],settings['worker_script'],'--config',settings['worker_config']],logger)
    previous=None;wsl_retry=0
    try:
        while not (directory/'pause').exists():
            now=time.time()
            try:
                desktop=desktop_running();ready=False
                if desktop and controller.process is None and now>=controller.next_start:
                    if not Path(settings['worker_script']).is_file() and now>=wsl_retry:
                        subprocess.run(['wsl.exe','-d',settings['wsl_distribution'],'--','true'],timeout=30,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW);wsl_retry=now+30
                    ready=Path(settings['worker_script']).is_file() and adapter_ready(settings['worker_config'])
                controller.step(desktop,ready,now)
            except Exception:
                logger.warning('supervisor_operation_retry');time.sleep(10);continue
            state={'state':controller.state,'worker_pid':controller.process.pid if controller.process else None,'docker_desktop_running':desktop,'checked_at':now}
            temp=directory/'status.json.new';temp.write_text(json.dumps(state),encoding='utf-8');temp.replace(directory/'status.json')
            if controller.state!=previous:logger.info(controller.state);previous=controller.state
            time.sleep(5)
    finally:controller.stop('supervisor_stopped')
    return 0


if __name__=='__main__':raise SystemExit(main())
