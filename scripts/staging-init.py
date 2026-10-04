#!/usr/bin/env python3
"""Generate fresh server-local staging credentials; never replace an existing setup."""
import argparse
import json
import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]


def initialize(destination, email):
    destination = Path(destination)
    env_path = destination / '.env.staging'
    secret_dir = destination / 'secrets' / 'staging'
    if env_path.exists() or secret_dir.exists():
        raise SystemExit('Staging configuration already exists; refusing to replace credentials.')
    if '@' not in email or any(c.isspace() or c in '$#\"\'' for c in email):
        raise SystemExit('Supply a valid ACME contact email without whitespace or env syntax.')
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'secrets').mkdir(mode=0o700, exist_ok=True)
    (destination / 'secrets').chmod(0o700)
    secret_dir.mkdir(mode=0o755)
    # Files must be readable by container UID 10001; the host secrets parent is private.
    secret_dir.chmod(0o755)
    principals = json.loads((ROOT / 'app/policy/principals.json').read_text())
    for principal in principals['principals']:
        principal['token'] = secrets.token_hex(32)
        principal['description'] = 'Staging identity; token generated on the server.'
    credentials = {'version': 1, 'scopes': {
        service: {'gate-mcp': secrets.token_hex(32)}
        for service in ('documents', 'outbox', 'tickets')}}
    for name, data in [('principals.json', principals), ('credentials.json', credentials)]:
        path = secret_dir / name
        path.write_text(json.dumps(data, indent=2) + '\n')
        path.chmod(0o644)
    replacements = {
        'COMPOSE_PROJECT_NAME': 'action-gate-staging',
        'APP_ENV': 'staging', 'APP_HOST': 'ai-control-gate.ivbon.dev',
        'APP_HASH_SALT': secrets.token_hex(32),
        'POSTGRES_PASSWORD': secrets.token_hex(32),
        'DEMO_MCP_ENDPOINT': 'http://gate-mcp:8010/mcp',
    }
    lines = []
    for line in (ROOT / '.env.example').read_text().splitlines():
        key = line.split('=', 1)[0]
        lines.append(key + '=' + replacements[key] if key in replacements else line)
    lines += ['', 'ACME_EMAIL=' + email]
    fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write('\n'.join(lines) + '\n')
    print('Created .env.staging and secrets/staging. No credentials printed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--email', required=True)
    parser.add_argument('--directory', type=Path, default=ROOT)
    args = parser.parse_args()
    initialize(args.directory, args.email)
