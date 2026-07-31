"""493/529: Učení z ručních zásahů a generování evalů z incidentů.

Zásada: „problém zmizel po příkazu" neznamená, že ho ten příkaz vyřešil.
Testy hlídají, že se z jedné náhody nestane postup.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import playbooks as pb
from sentinel import ai_evals

NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)


def ago(m):
    return (NOW - timedelta(minutes=m)).isoformat()


def issue(key='K1', host='rpi', plugin='storage', msg='disk 97% full', resolved=0):
    return {'key': key, 'host': host, 'plugin_name': plugin, 'last_line': msg,
            'resolved_at': ago(resolved), 'first_seen': ago(resolved + 60)}


def ssh(cmd='systemctl restart nginx', host='rpi', actor='foxik', minutes=10, ok=True):
    return {'hostname': host, 'command': cmd, 'actor': actor,
            'executed_at': ago(minutes), 'success': ok}


class TestSignature(unittest.TestCase):
    def test_same_problem_same_signature(self):
        self.assertEqual(pb.signature('storage', 'disk 97% full'),
                         pb.signature('storage', 'disk 42% full'))

    def test_different_plugin_differs(self):
        self.assertNotEqual(pb.signature('storage', 'x'), pb.signature('network', 'x'))


class TestDerive(unittest.TestCase):
    def test_repeated_manual_fix_becomes_playbook(self):
        issues = [issue(key=f'K{i}', resolved=i) for i in range(3)]
        log = [ssh(minutes=i + 5) for i in range(3)]
        r = pb.derive(issues, ssh_log=log)
        self.assertTrue(r)
        self.assertEqual(r[0]['command'], 'systemctl restart nginx')

    def test_single_occurrence_not_enough(self):
        """Z jedné shody se postup dělat nedá — problém mohl pominout sám."""
        self.assertEqual(pb.derive([issue()], ssh_log=[ssh()]), [])

    def test_command_after_resolution_ignored(self):
        """Příkaz spuštěný PO vyřešení problém vyřešit nemohl."""
        issues = [issue(key=f'K{i}', resolved=30) for i in range(3)]
        log = [ssh(minutes=5) for _ in range(3)]      # 5 min zpět = po vyřešení
        self.assertEqual(pb.derive(issues, ssh_log=log), [])

    def test_command_too_long_before_ignored(self):
        issues = [issue(key=f'K{i}', resolved=0) for i in range(3)]
        log = [ssh(minutes=600) for _ in range(3)]
        self.assertEqual(pb.derive(issues, ssh_log=log), [])

    def test_other_host_ignored(self):
        issues = [issue(key=f'K{i}', host='rpi', resolved=i) for i in range(3)]
        log = [ssh(host='jiny', minutes=i + 5) for i in range(3)]
        self.assertEqual(pb.derive(issues, ssh_log=log), [])

    def test_failed_command_ignored(self):
        """Co selhalo, není postup."""
        issues = [issue(key=f'K{i}', resolved=i) for i in range(3)]
        log = [ssh(minutes=i + 5, ok=False) for i in range(3)]
        self.assertEqual(pb.derive(issues, ssh_log=log), [])

    def test_automated_actor_ignored(self):
        """Zásahy automatu řeší 486/505, ne tenhle modul."""
        issues = [issue(key=f'K{i}', resolved=i) for i in range(3)]
        for bot in ('ai_auto', 'System', 'auto-verify'):
            log = [ssh(minutes=i + 5, actor=bot) for i in range(3)]
            self.assertEqual(pb.derive(issues, ssh_log=log), [], bot)

    def test_actions_source_also_used(self):
        issues = [issue(key=f'K{i}', resolved=i) for i in range(3)]
        acts = [{'status': 'executed', 'executed_by': 'lukas', 'node': 'rpi',
                 'command': 'systemctl restart nginx', 'executed_at': ago(i + 5),
                 'problem_key': f'K{i}'} for i in range(3)]
        r = pb.derive(issues, actions=acts)
        self.assertTrue(r)
        self.assertGreater(r[0]['direct_links'], 0)

    def test_unexecuted_action_ignored(self):
        issues = [issue(key=f'K{i}', resolved=i) for i in range(3)]
        acts = [{'status': 'pending', 'executed_by': 'lukas', 'node': 'rpi',
                 'command': 'x', 'executed_at': ago(i + 5)} for i in range(3)]
        self.assertEqual(pb.derive(issues, actions=acts), [])

    def test_confidence_rises_with_evidence(self):
        def conf(n):
            issues = [issue(key=f'K{i}', resolved=i) for i in range(n)]
            log = [ssh(minutes=i + 5) for i in range(n)]
            r = pb.derive(issues, ssh_log=log)
            return r[0]['confidence'] if r else 0
        self.assertLess(conf(2), conf(5))

    def test_caveat_always_present(self):
        issues = [issue(key=f'K{i}', resolved=i) for i in range(3)]
        r = pb.derive(issues, ssh_log=[ssh(minutes=i + 5) for i in range(3)])
        self.assertIn('pominout', r[0]['caveat'])

    def test_empty_inputs(self):
        for args in (([], None, None), (None, [], []), ([issue()], [], [])):
            self.assertEqual(pb.derive(*args), [])

    def test_malformed_rows_do_not_raise(self):
        pb.derive([None, 'x', {}], ssh_log=[None, 'y'], actions=[None, 3])


class TestFindForIssue(unittest.TestCase):
    def test_matches_by_signature(self):
        books = [{'signature': pb.signature('storage', 'disk 50% full'), 'command': 'x'}]
        self.assertTrue(pb.find_for_issue(books, issue()))

    def test_no_match_other_plugin(self):
        books = [{'signature': pb.signature('network', 'x'), 'command': 'y'}]
        self.assertEqual(pb.find_for_issue(books, issue()), [])


class TestEvalsFromIncidents(unittest.TestCase):
    HIST = [{'key': 'K1', 'plugin_name': 'storage', 'host': 'rpi',
             'last_line': 'disk full on /var'}]

    def test_verified_fix_becomes_case(self):
        fixes = [{'problem_key': 'K1', 'status': 'worked',
                  'command': 'journalctl --vacuum-time=7d'}]
        c = ai_evals.generate_from_incidents(fixes, self.HIST)
        self.assertEqual(len(c), 1)
        self.assertIn('journalctl', c[0]['expect_any'])
        self.assertIn('disk full', c[0]['prompt'])

    def test_unverified_fix_ignored(self):
        """Bez známé správné odpovědi test neměří kvalitu."""
        for status in ('failed', 'pending', 'uncertain'):
            fixes = [{'problem_key': 'K1', 'status': status, 'command': 'x y z'}]
            self.assertEqual(ai_evals.generate_from_incidents(fixes, self.HIST), [], status)

    def test_unknown_issue_ignored(self):
        fixes = [{'problem_key': 'NEEXISTUJE', 'status': 'worked', 'command': 'systemctl'}]
        self.assertEqual(ai_evals.generate_from_incidents(fixes, self.HIST), [])

    def test_duplicate_incident_types_collapsed(self):
        fixes = [{'problem_key': 'K1', 'status': 'worked',
                  'command': 'journalctl --vacuum-time=7d'} for _ in range(10)]
        self.assertEqual(len(ai_evals.generate_from_incidents(fixes, self.HIST)), 1)

    def test_max_cases_respected(self):
        hist = [{'key': f'K{i}', 'plugin_name': f'p{i}', 'host': 'h',
                 'last_line': f'problem {i}'} for i in range(50)]
        fixes = [{'problem_key': f'K{i}', 'status': 'worked',
                  'command': f'tool{i} arg'} for i in range(50)]
        self.assertLessEqual(len(ai_evals.generate_from_incidents(fixes, hist, max_cases=5)), 5)

    def test_empty_inputs(self):
        for a, b in ((None, None), ([], []), (None, self.HIST)):
            self.assertEqual(ai_evals.generate_from_incidents(a, b), [])


class TestCommandKeywords(unittest.TestCase):
    def test_flags_skipped(self):
        """Kdyby se čekalo „-n", prošlo by skoro cokoli."""
        kw = ai_evals._command_keywords('systemctl restart nginx -n 20')
        self.assertNotIn('-n', kw)
        self.assertIn('systemctl', kw)

    def test_sudo_skipped(self):
        self.assertNotIn('sudo', ai_evals._command_keywords('sudo systemctl restart x'))

    def test_path_stripped(self):
        self.assertIn('systemctl', ai_evals._command_keywords('/usr/bin/systemctl status x'))

    def test_short_tokens_skipped(self):
        self.assertEqual(ai_evals._command_keywords('df -h'), [])

    def test_deduplicated(self):
        kw = ai_evals._command_keywords('systemctl restart systemctl')
        self.assertEqual(kw.count('systemctl'), 1)

    def test_capped(self):
        self.assertLessEqual(len(ai_evals._command_keywords(' '.join(f'tok{i}' for i in range(50)))), 6)

    def test_empty(self):
        for v in ('', None, '   ', '-a -b'):
            self.assertEqual(ai_evals._command_keywords(v), [])

    def test_evidence_counts_distinct_incidents(self):
        """Tri incidenty a tri prikazy v okne nesmi dat devet dukazu."""
        issues = [issue(key=f'K{i}', resolved=i) for i in range(3)]
        log = [ssh(minutes=i + 5) for i in range(3)]
        r = pb.derive(issues, ssh_log=log)
        self.assertLessEqual(r[0]['evidence'], 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
