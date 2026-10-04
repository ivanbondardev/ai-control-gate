#!/usr/bin/env python3
"""Deploy GitHub default-branch HEAD via SSH, only from a clean, synchronized checkout."""
import argparse
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REMOTE = 'origin'
EXPECTED_REPOSITORY = 'ivanbondardev/ai-control-gate'
TARGET = 'root@95.217.5.223'
KEY = Path('~/.ssh/grisha_htz_id_ed25519').expanduser()


def run(*args, capture=False, **kwargs):
    result = subprocess.run(args, cwd=ROOT, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None, **kwargs)
    return result.stdout.strip() if capture else None


def verified_head():
    if run('git', 'status', '--porcelain', '--untracked-files=all', capture=True):
        raise SystemExit('Refusing deployment: commit and push all local changes first (including untracked files).')
    url = run('git', 'remote', 'get-url', REMOTE, capture=True)
    if url.removesuffix('.git') not in (
            'git@github.com:' + EXPECTED_REPOSITORY,
            'https://github.com/' + EXPECTED_REPOSITORY):
        raise SystemExit('origin must point to the expected GitHub repository.')
    advertised = run('git', 'ls-remote', '--symref', REMOTE, 'HEAD', capture=True)
    branch_match = re.search(r'^ref: (refs/heads/[^\s]+)\s+HEAD$', advertised, re.M)
    sha_match = re.search(r'^([0-9a-f]{40})\s+HEAD$', advertised, re.M)
    if not branch_match or not sha_match:
        raise SystemExit('Cannot resolve GitHub default-branch HEAD.')
    ref, sha = branch_match[1], sha_match[1]
    run('git', 'fetch', '--no-tags', REMOTE, ref)
    if run('git', 'rev-parse', 'FETCH_HEAD', capture=True) != sha:
        raise SystemExit('Remote HEAD moved during verification; retry.')
    if run('git', 'rev-parse', 'HEAD', capture=True) != sha:
        raise SystemExit('Local HEAD differs from GitHub HEAD; commit/push or synchronize before deploying.')
    if run('git', 'symbolic-ref', '--quiet', 'HEAD', capture=True) != ref:
        raise SystemExit('Check out the GitHub default branch before deploying.')
    # A final clean check catches changes made during the fetch.
    if run('git', 'status', '--porcelain', '--untracked-files=all', capture=True):
        raise SystemExit('Working tree changed during verification; retry.')
    print('Verified GitHub HEAD: ' + ref + ' ' + sha, flush=True)
    return sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify Git only; no server connection or deployment')
    parser.add_argument('--email', default='ivan.bondar.dev@gmail.com',
                        help='ACME contact email (default: ivan.bondar.dev@gmail.com)')
    args = parser.parse_args()
    sha = verified_head()
    if args.check:
        return
    if not KEY.is_file():
        raise SystemExit('SSH key not found: ' + str(KEY))
    paths = ['app', 'infra', 'scripts', 'compose.yaml', 'compose.staging.yaml',
             '.env.example', 'Makefile', 'VERSION', 'README.md', 'docs/staging.md']
    files = run('git', 'ls-tree', '-r', '--name-only', sha, '--', *paths, capture=True).splitlines()
    for file in files:
        parts = Path(file).parts
        if ('secrets' in parts or Path(file).name.startswith('.env') and file != '.env.example'
                or file.endswith(('.pem', '.key', '.local'))):
            raise SystemExit('Refusing to package a possible secret/local file: ' + file)
    ssh = ['ssh', '-i', str(KEY), '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', TARGET]
    remote_archive = '/opt/action-gate/incoming/' + sha + '.tar.gz'
    with tempfile.TemporaryDirectory(prefix='action-gate-deploy-') as directory:
        archive = Path(directory) / 'release.tar.gz'
        run('git', 'archive', '--format=tar.gz', '--output=' + str(archive), sha, '--', *paths)
        run(*ssh, 'mkdir -p /opt/action-gate/incoming')
        run('scp', '-i', str(KEY), '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            str(archive), TARGET + ':' + remote_archive)
    # The remote deploy logic also comes from the verified commit, never a working-tree file.
    script = run('git', 'show', sha + ':scripts/staging-remote.sh', capture=True)
    command = 'bash -s -- ' + shlex.quote(sha) + ' ' + shlex.quote(args.email or '')
    run(*ssh, command, input=script + '\n')


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit('Deployment stopped: command exited ' + str(error.returncode)) from error
