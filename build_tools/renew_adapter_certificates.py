"""Dedicated leaf renewal; no OS trust changes, key material never printed."""
import argparse,hashlib,json,os,ssl,subprocess,time
from pathlib import Path

def run(*args):subprocess.run(['openssl',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def der(path):return subprocess.check_output(['openssl','x509','-in',str(path),'-outform','DER'])
def atomic(path,value):
 tmp=path.with_suffix(path.suffix+'.new');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.chmod(0o600);tmp.replace(path)
def main():
 p=argparse.ArgumentParser();p.add_argument('--directory',required=True);p.add_argument('--days',type=int,default=2);p.add_argument('--activate-server',action='store_true');a=p.parse_args();root=Path(a.directory).resolve()
 if not 1<=a.days<=7:raise SystemExit('leaf_validity_must_be_1_to_7_days')
 expiry=ssl.cert_time_to_seconds(ssl._ssl._test_decode_cert(str(root/'ca.pem'))['notAfter'])
 if expiry-time.time()<(a.days*86400+3600):raise SystemExit('ca_renewal_required_before_leaf_issuance')
 worker=hashlib.sha256(der(root/'worker.pem')).hexdigest();identities=json.loads((root/'workers.json').read_text());identity=identities.get(worker)
 if not identity:raise SystemExit('existing_worker_identity_missing')
 os.umask(0o077);directory=root/'renewals'/time.strftime('%Y%m%d-%H%M%S',time.gmtime());directory.mkdir(parents=True,exist_ok=False)
 for name in ('server','worker'):
  run('req','-newkey','rsa:2048','-nodes','-keyout',str(directory/(name+'.key')),'-out',str(directory/(name+'.csr')),'-subj','/CN='+('localhost' if name=='server' else 'adapter-worker'))
  ext=directory/(name+'.ext');ext.write_text('basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage='+('serverAuth\nsubjectAltName=DNS:localhost,IP:127.0.0.1' if name=='server' else 'clientAuth')+'\n',encoding='utf-8')
  run('x509','-req','-in',str(directory/(name+'.csr')),'-CA',str(root/'ca.pem'),'-CAkey',str(root/'ca.key'),'-set_serial',str(int.from_bytes(os.urandom(16),'big')),'-out',str(directory/(name+'.pem')),'-days',str(a.days),'-extfile',str(ext))
  for path in directory.glob(name+'.*'):path.chmod(0o600)
 identities[hashlib.sha256(der(directory/'worker.pem')).hexdigest()]=identity;atomic(root/'workers.json',identities)
 if a.activate_server:
  active=root/'tls-active.new';active.symlink_to(directory.relative_to(root),target_is_directory=True);active.replace(root/'tls-active');atomic(root/'active-generation.json',{'generation':directory.name})
 atomic(directory/'public-manifest.json',{'generation':directory.name,'leaf_days':a.days,'worker_identity_retained':True,'server_activated':a.activate_server})
 print(json.dumps({'generation':directory.name,'leaf_days':a.days,'worker_identity_retained':True,'server_activated':a.activate_server}))
if __name__=='__main__':main()
