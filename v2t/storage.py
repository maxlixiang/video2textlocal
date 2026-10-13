"""Admission and write protection. No deletion, fixed safe errors only."""
import os,shutil
from pathlib import Path
from .core import Failure

def protect(root,reserve=0,kind='results'):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    minimum=int(os.getenv('DB_MIN_FREE_BYTES','268435456'))
    floor=int(os.getenv('MEDIA_MIN_FREE_BYTES','2147483648')) if kind=='media' else int(os.getenv('RESULT_MIN_FREE_BYTES','536870912')) if kind=='results' else minimum
    if shutil.disk_usage(root).free-reserve < max(minimum,floor):raise Failure('disk_full')
    if kind in ('media','results'):
        quota=int(os.getenv('MEDIA_QUOTA_BYTES','8589934592') if kind=='media' else os.getenv('RESULT_QUOTA_BYTES','2147483648'))
        from .adapter_common import usage
        total=usage(root)
        if total+reserve>quota:raise Failure('adapter_quota')


def results_write(path,reserve):
    root=Path(os.getenv('DATA_ROOT',str(Path(path).parent)))
    if not Path(path).resolve().is_relative_to(root.resolve()):root=Path(path).parent
    protect(root,reserve,'results')
