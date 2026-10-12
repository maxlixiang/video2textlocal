"""Create dedicated TEST adapter PKI, no global trust changes or key output."""
import argparse,hashlib,json,os,secrets,subprocess
from pathlib import Path

def cmd(*args):subprocess.run(['openssl',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def main():
 p=argparse.ArgumentParser();p.add_argument('--directory',required=True);a=p.parse_args();d=Path(a.directory);d.mkdir(parents=True,exist_ok=False)
 cmd('req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(d/'ca.key'),'-out',str(d/'ca.pem'),'-subj','/CN=Video2Text Dedicated Test CA','-days','7')
 identities={}
 for name,cn in [('server','localhost'),('worker','adapter-test-worker'),('unlisted','unlisted-worker'),('rotated','adapter-test-worker')]:
  cmd('req','-newkey','rsa:2048','-nodes','-keyout',str(d/(name+'.key')),'-out',str(d/(name+'.csr')),'-subj','/CN='+cn)
  ext=d/(name+'.ext');ext.write_text('basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage='+('serverAuth\nsubjectAltName=DNS:localhost,IP:127.0.0.1' if name=='server' else 'clientAuth')+'\n')
  cmd('x509','-req','-in',str(d/(name+'.csr')),'-CA',str(d/'ca.pem'),'-CAkey',str(d/'ca.key'),'-CAcreateserial','-out',str(d/(name+'.pem')),'-days','2','-extfile',str(ext))
  der=subprocess.check_output(['openssl','x509','-in',str(d/(name+'.pem')),'-outform','DER'])
  if name in ('worker','rotated'):identities[hashlib.sha256(der).hexdigest()]='test-worker'
 (d/'workers.json').write_text(json.dumps(identities));(d/'internal.key').write_text(secrets.token_hex(32))
 for f in d.iterdir():f.chmod(0o600)
 print('Dedicated test certificates generated; validity 2 days, CA 7 days; no global trust changes')
if __name__=='__main__':main()
