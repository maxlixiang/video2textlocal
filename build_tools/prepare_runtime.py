"""Fail closed preflight and persist role exports in Docker-managed volumes.
Run from WSL before Compose up. Never uses host bind mounts for daily runtime.
"""
import argparse
import io
import json
import os
import ssl
import subprocess
import tarfile
import time
from pathlib import Path

INSTALL = '''import io,os,sys,tarfile,pathlib,uuid
os.umask(0o077)
root=pathlib.Path('/runtime')
bundle=tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode='r:')
for item in bundle.getmembers():
 p=pathlib.PurePosixPath(item.name)
 if not item.isfile() or p.is_absolute() or '..' in p.parts:raise SystemExit('invalid_runtime_bundle')
 target=root.joinpath(*p.parts);target.parent.mkdir(parents=True,exist_ok=True)
 for parent in (target.parent,*target.parent.parents):
  if parent==root or root in parent.parents:os.chown(parent,1000,1000)
 tmp=target.with_name(target.name+'.new');tmp.write_bytes(bundle.extractfile(item).read());tmp.chmod(0o600);os.chown(tmp,1000,1000);tmp.replace(target)
current=os.getenv('CURRENT_GENERATION')
if current:
 link=root/'current.new';link.symlink_to(current,target_is_directory=True);link.replace(root/'current')
print('runtime_volume_prepared')
'''


def sync(volume, files, image, generation=None):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w') as archive:
        for name, path in files.items():
            raw = path.read_bytes();entry = tarfile.TarInfo(name);entry.size=len(raw);entry.mode=0o600
            archive.addfile(entry, io.BytesIO(raw))
    args = ['docker', 'run', '--rm', '-i', '--network', 'none', '--user', '0', '--security-opt', 'no-new-privileges', '--cap-drop', 'ALL', '--cap-add', 'CHOWN', '--cap-add', 'DAC_OVERRIDE', '--mount', 'type=volume,src='+volume+',dst=/runtime']
    if generation: args += ['-e', 'CURRENT_GENERATION='+generation]
    subprocess.run(args+[image, 'python', '-c', INSTALL], input=data.getvalue(), check=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--project',default='v2t-live-fixes');p.add_argument('--runtime-directory',default='.adapter-runtime');p.add_argument('--image',default='telegram-video2text-manager:health');p.add_argument('--config-directory',default='config')
    a=p.parse_args();root=Path(a.runtime_directory);config=Path(a.config_directory)
    os.umask(0o077)
    try:
        # Read and validate all source files before touching any runtime volume.
        if not (config/'hotwords.txt').is_file():raise ValueError('hotwords_missing')
        configs={str(path.relative_to(config)):path for path in config.rglob('*') if path.is_file()}
        if any(path.is_symlink() for path in configs.values()):raise ValueError('config_symlink')
        for path in configs.values():path.read_text(encoding='utf-8')
        if sum(p.stat().st_size for p in configs.values())>4*1024**2:raise ValueError('config_too_large')
        server=(root/'download'/'current').resolve(strict=True);generation=server.name
        manager=root/'manager'/'internal.key'
        if not manager.read_bytes() or manager.read_bytes()!=(root/'download'/'internal.key').read_bytes():raise ValueError('internal_key_mismatch')
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(server/'server.pem', server/'server.key');context.load_verify_locations(server/'ca.pem')
        expiry=json.loads((server/'expiry.json').read_text())
        actual_leaf=ssl.cert_time_to_seconds(ssl._ssl._test_decode_cert(str(server/'server.pem'))['notAfter'])
        actual_ca=ssl.cert_time_to_seconds(ssl._ssl._test_decode_cert(str(server/'ca.pem'))['notAfter'])
        if min(expiry['ca_expires'],expiry['leaf_expires'],actual_leaf,actual_ca)<time.time()+86400:raise ValueError('renew_certificates_before_start')
        if not json.loads((server/'workers.json').read_text()):raise ValueError('worker_identity_missing')
        # Absolute source directory names are never mounted into running services.
        files={generation+'/'+name:server/name for name in ('server.pem','server.key','ca.pem','workers.json','expiry.json')}
        files['internal.key']=root/'download'/'internal.key'
        sync(a.project+'_runtime_config',configs,a.image)
        sync(a.project+'_adapter_manager_credentials',{'internal.key':manager},a.image)
        sync(a.project+'_adapter_download_credentials',files,a.image,generation)
        print('preflight_passed; runtime_config_and_role_credentials_persisted')
    except Exception:raise SystemExit('runtime_preflight_failed; no services started; check files/certificate validity/Docker access') from None


if __name__=='__main__':main()
