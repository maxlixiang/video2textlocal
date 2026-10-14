"""Run with Windows Python: copy only worker credentials and atomically switch manifest."""
import argparse,json,os,ssl,time,uuid
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--config',required=True);p.add_argument('--trust-only',action='store_true');a=p.parse_args()
    source=Path(a.source).resolve();config=Path(a.config);settings=json.loads(config.read_text(encoding='utf-8'))
    manifest_path=Path(settings['credential_manifest']);target=manifest_path.parent/('generation-'+uuid.uuid4().hex)
    old=json.loads(manifest_path.read_text()) if a.trust_only else {}
    cert=Path(old['cert']) if a.trust_only else source/'worker.pem';private=Path(old['key']) if a.trust_only else source/'worker.key';context=ssl.create_default_context(cafile=str(source/'ca.pem'));context.load_cert_chain(str(cert),str(private))
    expiry=ssl.cert_time_to_seconds(ssl._ssl._test_decode_cert(str(cert))['notAfter'])
    if expiry<time.time()+86400:raise SystemExit('renew_client_before_install')
    target.mkdir(parents=True,exist_ok=False)
    for name,path in (('worker.pem',cert),('worker.key',private),('ca.pem',source/'ca.pem')): (target/name).write_bytes(path.read_bytes())
    value={k:str(target/name) for k,name in (('cert','worker.pem'),('key','worker.key'),('ca','ca.pem'))}
    temp=manifest_path.with_name(manifest_path.name+'.new');temp.write_text(json.dumps(value),encoding='utf-8');temp.replace(manifest_path)
    print(json.dumps({'worker_credentials_installed':True,'leaf_expires_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(expiry))}))


if __name__=='__main__':main()
