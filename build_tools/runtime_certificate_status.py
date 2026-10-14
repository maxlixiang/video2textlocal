"""Show only public expiry and maintenance dates for the active dedicated PKI."""
import argparse,json,time
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--runtime-directory',default='.adapter-runtime');a=p.parse_args()
 data=json.loads((Path(a.runtime_directory)/'download'/'current'/'expiry.json').read_text())
 rows=[]
 for role,threshold in (('ca',30),('leaf',14)):
  expiry=data[role+'_expires'];left=(expiry-time.time())/86400
  rows.append({'role':role,'expires_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(expiry)),'maintenance_due_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(expiry-threshold*86400)), 'days_remaining':round(left,2),'status':'expired' if left<=0 else 'maintenance_due' if left<threshold else 'valid'})
 print(json.dumps(rows,indent=2));return 1 if any(r['status']=='expired' for r in rows) else 0
if __name__=='__main__':raise SystemExit(main())
