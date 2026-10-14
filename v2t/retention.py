"""Completed-task media retention. One exact file per operation; never remove directories."""
import os,re,stat,time
from pathlib import Path
from .core import Failure

DAY=86400

def seconds():
 days=int(os.getenv('MEDIA_RETENTION_DAYS','0'))
 if not 0<=days<=365:raise Failure('invalid_input')
 return days*DAY

def eligible(store,worker=None,cursor='',limit=100):
 ttl=seconds()
 if not ttl:return []
 values=[time.time()-ttl,cursor];where="t.status='done' AND t.updated<=? AND t.id>?"
 if store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='adapter_jobs'").fetchone():
  where+=" AND NOT EXISTS (SELECT 1 FROM adapter_jobs a WHERE a.task_id=t.id AND a.state IN ('waiting','leased','uploading','validating'))"
 if worker is None and store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_retention'").fetchone():
  where+=" AND NOT EXISTS (SELECT 1 FROM media_retention m WHERE m.task_id=t.id)"
 if worker is not None:
  where+=" AND EXISTS (SELECT 1 FROM adapter_jobs a WHERE a.task_id=t.id AND a.worker=? AND a.state='complete')";values.append(worker)
 return [dict(r) for r in store.db.execute('SELECT t.id,t.updated FROM tasks t WHERE '+where+' ORDER BY t.id LIMIT ?',(*values,limit))]

def safe_parent(path):
 # Also rejects Windows junction/reparse directories, not just POSIX symlinks.
 try:s=path.lstat()
 except FileNotFoundError:return False
 if stat.S_ISLNK(s.st_mode) or getattr(s,'st_file_attributes',0)&0x400:raise Failure('invalid_input')
 return True

def candidates(root,tid):
 if not re.fullmatch('[a-f0-9]{32}',tid):raise Failure('invalid_input')
 root=Path(root)
 if not safe_parent(root):return []
 d=root/tid
 if not safe_parent(d):return []
 names=['media.bin','audio.wav','media.complete','media.part','audio.part.wav']
 out=[d/n for n in names]
 for p in d.iterdir():
  if re.fullmatch(r'(?:yt|x|dy)-[a-f0-9]{32}\.(?:mp4|webm|m4a|mp3|wav|ogg|part)(?:\.part(?:-Frag\d+)?)?',p.name):out.append(p)
 a=d/'adapter'
 if a.exists():
  safe_parent(a)
  for g in a.iterdir():
   if re.fullmatch('[a-f0-9]{32}',g.name) and safe_parent(g) and g.is_dir():out.extend([g/'media.part',g/'audio.part.wav'])
 return out

def remove_one(root,tid,cutoff=None):
 deferred=False
 for p in candidates(root,tid):
  try:s=p.lstat()
  except FileNotFoundError:continue
  if not stat.S_ISREG(s.st_mode) or getattr(s,'st_file_attributes',0)&0x400:raise Failure('invalid_input')
  if cutoff is not None and s.st_mtime>cutoff:deferred=True;continue
  # Root/task/adapter parents have already been validated; check again before unlink.
  for parent in [p.parent,*p.parents]:
   if parent==Path(root).parent:break
   safe_parent(parent)
   if parent==Path(root):break
  p.unlink()
  return {'removed':1,'bytes':s.st_size,'complete':False}
 return {'removed':0,'bytes':0,'complete':not deferred,'deferred':deferred}
