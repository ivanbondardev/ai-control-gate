#!/usr/bin/env python3
"""Offline checks for deployment refusal paths. No SSH or Docker daemon is used."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('deploy', Path(__file__).with_name('deploy-staging.py'))
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)
SHA = 'a' * 40


class DeploymentGuards(unittest.TestCase):
    def fake_git(self, dirty='', local=SHA, fetched=SHA, branch='refs/heads/main'):
        def invoke(*args, **kwargs):
            self.assertEqual(args[0], 'git', 'Verification must never call SSH')
            command = args[1:]
            if command[0] == 'status': return dirty
            if command[:2] == ('remote', 'get-url'): return 'git@github.com:ivanbondardev/ai-control-gate.git'
            if command[0] == 'ls-remote': return 'ref: refs/heads/main\tHEAD\n' + SHA + '\tHEAD'
            if command[0] == 'fetch': return None
            if command == ('rev-parse', 'FETCH_HEAD'): return fetched
            if command == ('rev-parse', 'HEAD'): return local
            if command[:2] == ('symbolic-ref', '--quiet'): return branch
            self.fail('Unexpected command: ' + str(args))
        return invoke

    def test_untracked_or_modified_files_block_before_network(self):
        for status in ('?? new.py', ' M README.md', 'M  app/main.py'):
            with self.subTest(status=status), patch.object(deploy, 'run', return_value=status) as call:
                with self.assertRaises(SystemExit): deploy.verified_head()
                self.assertEqual(call.call_count, 1)

    def test_unpushed_or_stale_commit_is_rejected(self):
        with patch.object(deploy, 'run', side_effect=self.fake_git(local='b' * 40)):
            with self.assertRaises(SystemExit): deploy.verified_head()

    def test_remote_movement_during_fetch_is_rejected(self):
        with patch.object(deploy, 'run', side_effect=self.fake_git(fetched='b' * 40)):
            with self.assertRaises(SystemExit): deploy.verified_head()

    def test_other_branch_is_rejected_even_at_same_commit(self):
        with patch.object(deploy, 'run', side_effect=self.fake_git(branch='refs/heads/feature')):
            with self.assertRaises(SystemExit): deploy.verified_head()

    def test_clean_default_branch_at_remote_head_is_accepted(self):
        with patch.object(deploy, 'run', side_effect=self.fake_git()):
            self.assertEqual(deploy.verified_head(), SHA)


if __name__ == '__main__':
    unittest.main()
