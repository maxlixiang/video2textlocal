"""Offline issuance/export. CA private keys never belong to service runtime exports."""
import argparse
import hashlib
import json
import os
import ssl
import subprocess
import time
import uuid
from pathlib import Path


def run(*args):
    subprocess.run(['openssl', *map(str, args)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def expires(path):
    return ssl.cert_time_to_seconds(ssl._ssl._test_decode_cert(str(path))['notAfter'])


def fingerprint(path):
    return hashlib.sha256(subprocess.check_output(['openssl', 'x509', '-in', str(path), '-outform', 'DER'])).hexdigest()


def atomic(path, data):
    temp = path.with_name(path.name + '.new')
    temp.write_bytes(data)
    temp.chmod(0o600)
    temp.replace(path)


def issue(root, identity, ca_days=365, leaf_days=90, authority=None):
    if not 1 <= leaf_days <= 90 or not 30 <= ca_days <= 730:
        raise ValueError('validity_outside_maintenance_policy')
    os.umask(0o077)
    generation = root / ('generation-' + time.strftime('%Y%m%d-%H%M%S', time.gmtime()) + '-' + uuid.uuid4().hex[:8])
    generation.mkdir(parents=True, exist_ok=False)
    signer = Path(authority) if authority else generation
    if authority:
        if expires(signer / 'ca.pem') < time.time() + (leaf_days + 1) * 86400:
            raise ValueError('rotate_ca_before_renewing_leaf')
    else:
        run('req', '-x509', '-newkey', 'rsa:3072', '-nodes', '-keyout', signer / 'ca.key',
            '-out', signer / 'ca.pem', '-days', ca_days, '-subj', '/CN=Video2Text dedicated adapter CA',
            '-addext', 'basicConstraints=critical,CA:TRUE,pathlen:0', '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
    for role in ('server', 'worker'):
        run('req', '-newkey', 'rsa:2048', '-nodes', '-keyout', generation / (role + '.key'),
            '-out', generation / (role + '.csr'), '-subj', '/CN=' + ('localhost' if role == 'server' else 'adapter-worker'))
        ext = generation / (role + '.ext')
        ext.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=' +
                       ('serverAuth\nsubjectAltName=DNS:localhost,IP:127.0.0.1' if role == 'server' else 'clientAuth') + '\n', encoding='utf-8')
        run('x509', '-req', '-in', generation / (role + '.csr'), '-CA', signer / 'ca.pem', '-CAkey', signer / 'ca.key',
            '-set_serial', int.from_bytes(os.urandom(16), 'big'), '-out', generation / (role + '.pem'),
            '-days', leaf_days, '-extfile', ext)
    manifest = {'worker_identity': identity, 'authority': str(signer.resolve()), 'ca_expires': expires(signer / 'ca.pem'),
                'leaf_expires': min(expires(generation / 'server.pem'), expires(generation / 'worker.pem'))}
    atomic(generation / 'manifest.json', json.dumps(manifest).encode())
    return generation


def export(generation, target, internal_key, overlap=None):
    """Produce separate allowlisted exports; optional old CA is public only."""
    generation = Path(generation)
    manifest = json.loads((generation / 'manifest.json').read_text())
    ca = Path(manifest['authority']) / 'ca.pem'
    if expires(ca) < time.time() + 86400 or manifest['leaf_expires'] < time.time() + 86400:
        raise ValueError('certificate_too_close_to_expiry')
    trust = ca.read_bytes()
    identities = {fingerprint(generation / 'worker.pem'): manifest['worker_identity']}
    if overlap:
        old = Path(overlap)
        trust += (old / 'ca.pem').read_bytes()
        identities.update(json.loads((old / 'workers.json').read_text()))
    server = target / 'download'
    client = target / 'windows'
    manager = target / 'manager'
    for directory in (server, client, manager): directory.mkdir(parents=True, exist_ok=True)
    atomic(manager / 'internal.key', Path(internal_key).read_bytes())
    atomic(server / 'internal.key', Path(internal_key).read_bytes())
    for directory, role in ((server, 'server'), (client, 'worker')):
        dest = directory / generation.name
        dest.mkdir(exist_ok=True)
        for suffix in ('.pem', '.key'): atomic(dest / (role + suffix), (generation / (role + suffix)).read_bytes())
        atomic(dest / 'ca.pem', trust)
        atomic(dest / 'expiry.json', json.dumps({k: manifest[k] for k in ('ca_expires', 'leaf_expires')}).encode())
        if role == 'server': atomic(dest / 'workers.json', json.dumps(identities).encode())
        link = directory / 'current.new'
        link.symlink_to(generation.name, target_is_directory=True)
        link.replace(directory / 'current')
    print(json.dumps({'generation': generation.name, 'overlap': bool(overlap), 'ca_expires_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(manifest['ca_expires'])), 'leaf_expires_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(manifest['leaf_expires']))}))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='action', required=True)
    create = sub.add_parser('issue');create.add_argument('--offline-directory', required=True);create.add_argument('--worker-id', required=True)
    create.add_argument('--authority');create.add_argument('--ca-days', type=int, default=365);create.add_argument('--leaf-days', type=int, default=90)
    out = sub.add_parser('export');out.add_argument('--generation', required=True);out.add_argument('--runtime-directory', required=True);out.add_argument('--internal-key-file', required=True);out.add_argument('--overlap-old-directory')
    a = p.parse_args()
    try:
        if a.action == 'issue': print(json.dumps({'generation': str(issue(Path(a.offline_directory), a.worker_id, a.ca_days, a.leaf_days, a.authority))}))
        else: export(Path(a.generation), Path(a.runtime_directory), a.internal_key_file, a.overlap_old_directory)
    except Exception: raise SystemExit('credential_operation_failed; check paths and public certificate validity') from None


if __name__ == '__main__': main()
