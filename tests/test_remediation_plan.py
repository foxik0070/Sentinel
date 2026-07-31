"""489/491/492/495/497/498/500/502/503: plánování zásahu v kontextu.

Tentýž příkaz je jindy neškodný a jindy výpadek — rozdíl je v tom, CO
restartuje, KDY a co se dělo předtím.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import remediation_plan as rp

NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)      # čtvrtek, poledne
NIGHT = datetime(2026, 7, 31, 23, 0, 0, tzinfo=timezone.utc)
WEEKEND = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)   # sobota


class TestRollback(unittest.TestCase):
    def test_stop_reverses_to_start(self):
        r = rp.rollback_for('systemctl stop nginx')
        self.assertTrue(r['reversible'])
        self.assertEqual(r['rollback'], 'systemctl start nginx')

    def test_disable_reverses(self):
        self.assertEqual(rp.rollback_for('systemctl disable x')['rollback'],
                         'systemctl enable x')

    def test_iptables_add_reverses_to_delete(self):
        r = rp.rollback_for('iptables -A INPUT -p tcp --dport 22 -j DROP')
        self.assertIn('-D INPUT', r['rollback'])

    def test_destructive_marked_irreversible(self):
        """„Nedá se vrátit" je pro rozhodování důležitější než mlčení."""
        for cmd in ('rm -rf /var/log/old', 'mkfs.ext4 /dev/sdb1',
                    'journalctl --vacuum-time=7d', 'dd if=/dev/zero of=/tmp/x',
                    'truncate -s 0 /var/log/syslog', 'apt-get remove nginx'):
            r = rp.rollback_for(cmd)
            self.assertFalse(r['reversible'], cmd)
            self.assertIn('NEVRATNÉ', r['note'])

    def test_restart_has_no_opposite(self):
        r = rp.rollback_for('systemctl restart nginx')
        self.assertTrue(r['reversible'])
        self.assertIsNone(r['rollback'])
        self.assertIn('diagnostika', r['note'])

    def test_reboot_irreversible(self):
        self.assertFalse(rp.rollback_for('reboot')['reversible'])

    def test_unknown_command_admits_ignorance(self):
        r = rp.rollback_for('nejaky-vlastni-skript --flag')
        self.assertIsNone(r['reversible'])
        self.assertIn('posuď ručně', r['note'])

    def test_empty(self):
        self.assertIsNone(rp.rollback_for('')['reversible'])


class TestContextualRisk(unittest.TestCase):
    def test_database_restart_is_high(self):
        """`systemctl restart` má u klasifikátoru nulu, ale u DB je to výpadek."""
        r = rp.contextual_risk('systemctl restart mariadb', base_score=0)
        self.assertEqual(r['level'], 'high')

    def test_cache_restart_is_low(self):
        r = rp.contextual_risk('systemctl restart redis', base_score=0)
        self.assertEqual(r['level'], 'low')

    def test_ssh_warns_about_own_connection(self):
        r = rp.contextual_risk('systemctl restart sshd')
        self.assertTrue(any('spojení' in x for x in r['reasons']))

    def test_unknown_target_adds_caution(self):
        r = rp.contextual_risk('systemctl restart nejakasluzba')
        self.assertTrue(any('neznáme' in x for x in r['reasons']))

    def test_dependents_raise_score(self):
        a = rp.contextual_risk('systemctl restart redis', dependents=0)['score']
        b = rp.contextual_risk('systemctl restart redis', dependents=6)['score']
        self.assertGreater(b, a)

    def test_base_score_respected(self):
        r = rp.contextual_risk('systemctl restart redis', base_score=50)
        self.assertGreaterEqual(r['score'], 50)

    def test_target_extracted(self):
        self.assertEqual(rp.contextual_risk('systemctl restart nginx.service')['target'], 'nginx')


class TestDryRun(unittest.TestCase):
    def test_apt_has_simulation(self):
        r = rp.dry_run_for('apt-get install nginx')
        self.assertTrue(r['available'])
        self.assertIn('-s', r['command'])

    def test_rsync_has_dry_run(self):
        self.assertIn('--dry-run', rp.dry_run_for('rsync -a /a /b')['command'])

    def test_mount_has_fake(self):
        self.assertIn('--fake', rp.dry_run_for('mount /dev/sdb1 /mnt')['command'])

    def test_systemctl_falls_back_to_status(self):
        self.assertIn('status', rp.dry_run_for('systemctl restart nginx')['command'])

    def test_unknown_has_none(self):
        self.assertFalse(rp.dry_run_for('vlastni-skript')['available'])


class TestMaintenanceWindow(unittest.TestCase):
    def test_work_hours_blocks_routine(self):
        r = rp.in_maintenance_window(now=NOW, severity='medium')
        self.assertFalse(r['allowed'])
        self.assertIn('Odlož', r['note'])

    def test_critical_always_allowed(self):
        """Výpadek už běží — čekat nemá smysl."""
        for sev in ('critical', 'high'):
            self.assertTrue(rp.in_maintenance_window(now=NOW, severity=sev)['allowed'], sev)

    def test_night_allowed(self):
        self.assertTrue(rp.in_maintenance_window(now=NIGHT, severity='medium')['allowed'])

    def test_weekend_allowed(self):
        self.assertTrue(rp.in_maintenance_window(now=WEEKEND, severity='medium')['allowed'])


class TestPhysicalIntervention(unittest.TestCase):
    def test_disk_failure_detected(self):
        """Nabízet restart u vadného disku odkládá objednávku dílu."""
        for msg in ('SMART: 2 reallocated sectors, disk failing',
                    'Current_Pending_Sector count 5',
                    'Medium error on /dev/sda'):
            r = rp.needs_physical_intervention(msg)
            self.assertTrue(r['physical'], msg)
            self.assertIn('disku', r['action'])

    def test_memory_failure_detected(self):
        self.assertTrue(rp.needs_physical_intervention('ECC uncorrectable error')['physical'])

    def test_fan_failure_detected(self):
        self.assertTrue(rp.needs_physical_intervention('Fan failure detected')['physical'])

    def test_software_problem_not_physical(self):
        for msg in ('disk 97% full', 'nginx.service failed', 'connection refused'):
            self.assertFalse(rp.needs_physical_intervention(msg)['physical'], msg)

    def test_empty(self):
        self.assertFalse(rp.needs_physical_intervention('')['physical'])


class TestConflicts(unittest.TestCase):
    def rec(self, cmd, min_ago=5):
        return {'command': cmd, 'at': (NOW - timedelta(minutes=min_ago)).isoformat()}

    def test_start_after_stop_is_conflict(self):
        c = rp.conflicts_with('systemctl start nginx', [self.rec('systemctl stop nginx')], now=NOW)
        self.assertEqual(len(c), 1)

    def test_enable_after_disable_is_conflict(self):
        c = rp.conflicts_with('systemctl enable x', [self.rec('systemctl disable x')], now=NOW)
        self.assertTrue(c)

    def test_different_target_not_conflict(self):
        c = rp.conflicts_with('systemctl start nginx', [self.rec('systemctl stop mariadb')], now=NOW)
        self.assertEqual(c, [])

    def test_old_action_not_conflict(self):
        c = rp.conflicts_with('systemctl start nginx',
                              [self.rec('systemctl stop nginx', min_ago=999)], now=NOW)
        self.assertEqual(c, [])

    def test_same_action_not_conflict(self):
        c = rp.conflicts_with('systemctl restart nginx',
                              [self.rec('systemctl restart nginx')], now=NOW)
        self.assertEqual(c, [])

    def test_malformed(self):
        for v in (None, [], [None], ['x'], [{}]):
            self.assertEqual(rp.conflicts_with('systemctl start x', v, now=NOW), [])


class TestResolutionEstimate(unittest.TestCase):
    def hist(self, minutes, n=5):
        return [{'plugin_name': 'storage', 'last_line': 'disk 90% full',
                 'first_seen': (NOW - timedelta(minutes=minutes)).isoformat(),
                 'resolved_at': NOW.isoformat()} for _ in range(n)]

    def test_estimate_from_history(self):
        issue = {'plugin_name': 'storage', 'last_line': 'disk 97% full'}
        r = rp.estimate_resolution_time(issue, self.hist(30))
        self.assertTrue(r['known'])
        self.assertAlmostEqual(r['median_min'], 30, delta=1)

    def test_too_few_samples(self):
        issue = {'plugin_name': 'storage', 'last_line': 'disk 97% full'}
        self.assertFalse(rp.estimate_resolution_time(issue, self.hist(30, n=2))['known'])

    def test_different_plugin_ignored(self):
        issue = {'plugin_name': 'network', 'last_line': 'disk 97% full'}
        self.assertFalse(rp.estimate_resolution_time(issue, self.hist(30))['known'])

    def test_empty(self):
        self.assertFalse(rp.estimate_resolution_time({}, [])['known'])


class TestPrioritize(unittest.TestCase):
    def issue(self, key='K1', sev='medium', hours=1, msg='disk full', plugin='storage'):
        return {'key': key, 'severity': sev, 'plugin_name': plugin, 'last_line': msg,
                'host': 'rpi', 'first_seen': (NOW - timedelta(hours=hours)).isoformat()}

    def test_critical_ranks_higher(self):
        r = rp.prioritize([self.issue('LOW', sev='low'), self.issue('CRIT', sev='critical')], now=NOW)
        self.assertEqual(r[0]['key'], 'CRIT')

    def test_playbook_raises_confidence(self):
        from sentinel.playbooks import signature
        pb = [{'signature': signature('storage', 'disk full')}]
        r = rp.prioritize([self.issue()], playbooks=pb, now=NOW)
        self.assertTrue(r[0]['has_playbook'])
        self.assertGreater(r[0]['confidence'], 50)

    def test_physical_problem_gets_low_confidence(self):
        """Softwarem to nespravíme, tak to nemá blokovat frontu."""
        r = rp.prioritize([self.issue(msg='SMART reallocated sectors, disk failing')], now=NOW)
        self.assertLess(r[0]['confidence'], 10)

    def test_age_increases_impact(self):
        r = rp.prioritize([self.issue('NEW', hours=0), self.issue('OLD', hours=100)], now=NOW)
        self.assertEqual(r[0]['key'], 'OLD')

    def test_empty(self):
        self.assertEqual(rp.prioritize([], now=NOW), [])


class TestBatchGrouping(unittest.TestCase):
    def issue(self, host, msg='pending updates: 5 packages'):
        return {'key': f'K-{host}', 'host': host, 'plugin_name': 'audit',
                'last_line': msg}

    def test_same_problem_grouped(self):
        issues = [self.issue(f'h{i}', f'pending updates: {i} packages') for i in range(5)]
        r = rp.group_for_batch(issues)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]['host_count'], 5)

    def test_single_host_not_batched(self):
        self.assertEqual(rp.group_for_batch([self.issue('h1')]), [])

    def test_different_problems_separate(self):
        issues = [self.issue(f'h{i}') for i in range(3)] + \
                 [self.issue(f'g{i}', 'disk full') for i in range(3)]
        self.assertEqual(len(rp.group_for_batch(issues)), 2)

    def test_note_suggests_one_plan(self):
        issues = [self.issue(f'h{i}') for i in range(4)]
        self.assertIn('jeden', rp.group_for_batch(issues)[0]['note'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
