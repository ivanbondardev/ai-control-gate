"""Service-side checks for the acceptance run: the stored row is the independent evidence."""

import json
import sys


def main(path, kind):
    snapshot = json.load(open(path, encoding='utf-8'))
    if kind == 'outbox':
        messages = snapshot['state']['messages']
        recipients = [row['recipient'] for row in messages]
        if 'colleague@acme.example' not in recipients:
            print(f'expected the internal recipient to be stored, saw {recipients}')
            return 1
        if any('external.example' in value for value in recipients):
            print(f'an external recipient was stored: {recipients}')
            return 1
        bodies = snapshot.get('state', {}).get('bodies') or {}
        if not bodies:
            print('no stored-message count was reported')
            return 1
        print(f'messages stored: {bodies.get("stored")}; recipients: {recipients}')
        return 0
    if kind == 'documents':
        documents = {row['doc_id']: row for row in snapshot['state']['documents']}
        target = documents.get('KB-1042', {})
        if target.get('content') != 'Synthetic acceptance rewrite.':
            print(f'KB-1042 content is {target.get("content")!r}')
            return 1
        if target.get('version', 0) < 2:
            print(f'KB-1042 version is {target.get("version")}')
            return 1
        protected = documents.get('KB-9000', {})
        if protected.get('version') != 1:
            print(f'KB-9000 was modified: version {protected.get("version")}')
            return 1
        receipts = snapshot['receipts']
        if not receipts:
            print('no receipts were recorded')
            return 1
        print(f'KB-1042 version {target["version"]}, KB-9000 untouched, receipts {len(receipts)}')
        return 0
    print(f'unknown check {kind!r}')
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
