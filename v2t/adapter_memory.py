"""Windows kernel Job Object enforces entire child process-tree private commit limit."""
import ctypes,os
from ctypes import wintypes as w
from .core import Failure

class Basic(ctypes.Structure):
 _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),('flags',w.DWORD),('min_ws',ctypes.c_size_t),('max_ws',ctypes.c_size_t),('active_limit',w.DWORD),('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
class IO(ctypes.Structure):_fields_=[(n,ctypes.c_ulonglong) for n in ('read_count','write_count','other_count','read_bytes','write_bytes','other_bytes')]
class Extended(ctypes.Structure):
 _fields_=[('basic',Basic),('io',IO),('process_limit',ctypes.c_size_t),('job_limit',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
class Accounting(ctypes.Structure):
 _fields_=[('user',ctypes.c_longlong),('kernel',ctypes.c_longlong),('period_user',ctypes.c_longlong),('period_kernel',ctypes.c_longlong),('faults',w.DWORD),('total',w.DWORD),('active',w.DWORD),('terminated',w.DWORD)]

class Budget:
 def __init__(self,process,limit):
  if os.name!='nt':raise Failure('invalid_input')
  self.k=ctypes.WinDLL('kernel32',use_last_error=True)
  self.k.CreateJobObjectW.restype=w.HANDLE;self.k.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR]
  self.k.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
  self.k.QueryInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.c_void_p]
  self.k.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE];self.k.CloseHandle.argtypes=[w.HANDLE];self.k.TerminateJobObject.argtypes=[w.HANDLE,w.UINT]
  self.handle=self.k.CreateJobObjectW(None,None);self.limit=limit;self.max_active=0;self.sampled_private_peak=0;self.sampled_working_peak=0
  value=Extended();value.basic.flags=0x2000|0x200;value.job_limit=limit
  if not self.handle or not self.k.SetInformationJobObject(self.handle,9,ctypes.byref(value),ctypes.sizeof(value)) or not self.k.AssignProcessToJobObject(self.handle,w.HANDLE(int(process._handle))):
   process.kill();raise Failure('adapter_memory_limit')
 def metrics(self):
  x=Extended();a=Accounting()
  self.k.QueryInformationJobObject(self.handle,9,ctypes.byref(x),ctypes.sizeof(x),None)
  self.k.QueryInformationJobObject(self.handle,1,ctypes.byref(a),ctypes.sizeof(a),None);self.max_active=max(self.max_active,a.active)
  class PIDs(ctypes.Structure):_fields_=[('assigned',w.DWORD),('count',w.DWORD),('pids',ctypes.c_size_t*128)]
  class Memory(ctypes.Structure):_fields_=[('cb',w.DWORD),('faults',w.DWORD)]+[(n,ctypes.c_size_t) for n in ('peak_ws','ws','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile','private')]
  ids=PIDs();self.k.QueryInformationJobObject(self.handle,3,ctypes.byref(ids),ctypes.sizeof(ids),None)
  self.k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];self.k.OpenProcess.restype=w.HANDLE
  ps=ctypes.WinDLL('psapi');ps.GetProcessMemoryInfo.argtypes=[w.HANDLE,ctypes.c_void_p,w.DWORD]
  private=working=0
  for pid in list(ids.pids)[:min(ids.count,128)]:
   handle=self.k.OpenProcess(0x0400|0x0010,False,pid)
   if handle:
    m=Memory();m.cb=ctypes.sizeof(m)
    if ps.GetProcessMemoryInfo(handle,ctypes.byref(m),ctypes.sizeof(m)):private+=m.private;working+=m.ws
    self.k.CloseHandle(handle)
  self.sampled_private_peak=max(self.sampled_private_peak,private);self.sampled_working_peak=max(self.sampled_working_peak,working)
  return {'sampled_private_commit_peak_bytes':self.sampled_private_peak,'sampled_sum_working_set_peak_bytes':self.sampled_working_peak,'actual_kernel_limit_bytes':x.job_limit,'actual_kernel_flags':x.basic.flags,'budget_bytes':self.limit,'peak_private_commit_bytes':x.peak_job,'max_active_processes':self.max_active,'total_processes':a.total,'measurement':'Windows_QueryInformationJobObject_entire_browser_child_tree','kernel_job_memory_limit':True}
 def terminate(self):self.k.TerminateJobObject(self.handle,1)
 def close(self):self.k.CloseHandle(self.handle)
