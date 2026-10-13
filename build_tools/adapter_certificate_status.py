"""Public expiry metadata only; never reads private keys."""
import argparse,json,ssl,time
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--directory',required=True);a=p.parse_args();r=Path(a.directory);g=json.loads((r/'active-generation.json').read_text())['generation'];rows=[]
 for role,path in [('ca',r/'ca.pem'),('server',r/'renewals'/g/'server.pem'),('worker',r/'renewals'/g/'worker.pem')]:
  expires=ssl.cert_time_to_seconds(ssl._ssl._test_decode_cert(str(path))['notAfter']);left=expires-time.time();rows.append({'role':role,'expires_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(expires)),'hours_remaining':round(left/3600,2),'status':'expired' if left<=0 else 'renew_soon' if left<86400 else 'valid'})
 print(json.dumps(rows,ensure_ascii=False,indent=2));return 1 if any(x['status']=='expired' for x in rows) else 0
if __name__=='__main__':raise SystemExit(main())
