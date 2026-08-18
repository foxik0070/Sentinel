"""
Testy pro uzavírání issues, které už neplatí.

Pokrývá tři mechanismy, které vznikly proto, že issues „hnily" v databázi:
  * resolve_aged_event_issues — strop stáří pro agregované event-typy
  * reconcile_detector_issues — rekonciliace pro detektory znající plný stav
  * issue_lifecycle.evaluate  — deterministická recheck pravidla

Run:
    python -m unittest tests.test_issue_lifecycle -v
"""
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import state, config, issue_lifecycle


def _iso(dt):
    return dt.isoformat()


def _ago(**kw):
    return datetime.now(timezone.utc) - timedelta(**kw)


class _DBCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self._tmp.close()
        self._orig_db = state.DB_FILE
        state.DB_FILE = self._tmp.name
        state._local = threading.local()
        state.init_db()

    def tearDown(self):
        state.DB_FILE = self._orig_db
        os.unlink(self._tmp.name)

    def _insert(self, key, first_seen, last_seen=None, status='active',
                host='h1', missing=0):
        conn = state._get_conn()
        conn.execute(
            "INSERT INTO problems (key, status, channel_type, last_seen, missing_count,"
            " details, plugin_name, host, last_line, occurrence_count, first_seen)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (key, status, 'infra', _iso(last_seen or datetime.now(timezone.utc)),
             missing, '{}', 'p', host, 'msg', 1, _iso(first_seen))
        )
        conn.commit()
        conn.close()

    def _keys(self):
        conn = state._get_conn()
        rows = [r[0] for r in conn.execute("SELECT key FROM problems").fetchall()]
        conn.close()
        return set(rows)

    def _history_reason(self, key):
        conn = state._get_conn()
        row = conn.execute(
            "SELECT resolve_reason FROM issue_history WHERE key=?", (key,)
        ).fetchone()
        conn.close()
        return row[0] if row else None


class TestAgedEventIssues(_DBCase):
    """Event-typy mají pořád čerstvý last_seen, takže je smí zavřít jen strop stáří."""

    def test_archives_event_issue_over_max_age(self):
        # Přesně ten případ z produkce: první výskyt před 68 dny, ale poslední
        # událost přišla teď — proto na něj TTL podle last_seen nesáhne.
        self._insert('SYS_ERR|proxmox02', first_seen=_ago(days=68),
                     last_seen=datetime.now(timezone.utc))
        n = state.resolve_aged_event_issues(max_age_hours=48, prefixes=['SYS_ERR'])
        self.assertEqual(n, 1)
        self.assertNotIn('SYS_ERR|proxmox02', self._keys())
        self.assertEqual(self._history_reason('SYS_ERR|proxmox02'), 'event_max_age')

    def test_keeps_young_event_issue(self):
        self._insert('SYS_ERR|host', first_seen=_ago(hours=3))
        self.assertEqual(state.resolve_aged_event_issues(48, ['SYS_ERR']), 0)
        self.assertIn('SYS_ERR|host', self._keys())

    def test_ignores_non_event_prefixes(self):
        # Stavové issue (disk plný) se stářím zavírat nesmí — pořád může platit.
        self._insert('DISK_FULL|host|/', first_seen=_ago(days=90))
        self.assertEqual(state.resolve_aged_event_issues(48, ['SYS_ERR']), 0)
        self.assertIn('DISK_FULL|host|/', self._keys())

    def test_prefix_match_is_anchored(self):
        # 'SYS_ERROR_X|...' nesmí spadnout pod prefix 'SYS_ERR'
        self._insert('SYS_ERROR_X|host', first_seen=_ago(days=90))
        self.assertEqual(state.resolve_aged_event_issues(48, ['SYS_ERR']), 0)
        self.assertIn('SYS_ERROR_X|host', self._keys())

    def test_disabled_when_max_age_zero(self):
        self._insert('SYS_ERR|host', first_seen=_ago(days=90))
        self.assertEqual(state.resolve_aged_event_issues(max_age_hours=0,
                                                         prefixes=['SYS_ERR']), 0)


class TestDetectorReconcile(_DBCase):
    """Detektor znající plný stav smí zavřít, co v běhu nenahlásil."""

    def test_missing_key_resolves_after_threshold(self):
        self._insert('DISK_FULL|h1|/var', first_seen=_ago(days=1))
        for _ in range(2):
            state.reconcile_detector_issues('DISK_FULL', set(), host='h1', threshold=3)
            self.assertIn('DISK_FULL|h1|/var', self._keys())
        state.reconcile_detector_issues('DISK_FULL', set(), host='h1', threshold=3)
        self.assertNotIn('DISK_FULL|h1|/var', self._keys())
        self.assertEqual(self._history_reason('DISK_FULL|h1|/var'), 'detector_state_ok')

    def test_reported_key_survives_and_resets_counter(self):
        self._insert('DISK_FULL|h1|/var', first_seen=_ago(days=1), missing=2)
        state.reconcile_detector_issues('DISK_FULL', {'DISK_FULL|h1|/var'},
                                        host='h1', threshold=3)
        conn = state._get_conn()
        mc = conn.execute("SELECT missing_count FROM problems WHERE key=?",
                          ('DISK_FULL|h1|/var',)).fetchone()[0]
        conn.close()
        self.assertEqual(mc, 0, "nahlášený klíč musí vynulovat missing_count")

    def test_other_host_untouched(self):
        # Sweep serveru h1 nesmí sáhnout na issues serveru h2.
        self._insert('DISK_FULL|h2|/var', first_seen=_ago(days=1), host='h2')
        for _ in range(5):
            state.reconcile_detector_issues('DISK_FULL', set(), host='h1', threshold=3)
        self.assertIn('DISK_FULL|h2|/var', self._keys())

    def test_other_prefix_untouched(self):
        self._insert('SYS_ERR|h1', first_seen=_ago(days=1))
        for _ in range(5):
            state.reconcile_detector_issues('DISK_FULL', set(), host='h1', threshold=3)
        self.assertIn('SYS_ERR|h1', self._keys())

    def test_empty_prefixes_is_noop(self):
        self._insert('DISK_FULL|h1|/var', first_seen=_ago(days=1))
        self.assertEqual(state.reconcile_detector_issues([], set(), host='h1'), [])
        self.assertIn('DISK_FULL|h1|/var', self._keys())


class TestRecheckRules(unittest.TestCase):
    """Deterministická pravidla — stejná pro UI i pro plánovač."""

    def setUp(self):
        self._orig = (config.RECHECK_FRESH_MIN, config.RECHECK_SOURCE_SILENCE_MIN)
        config.RECHECK_FRESH_MIN = 10
        config.RECHECK_SOURCE_SILENCE_MIN = 45

    def tearDown(self):
        config.RECHECK_FRESH_MIN, config.RECHECK_SOURCE_SILENCE_MIN = self._orig

    def test_fresh_issue_still_active(self):
        prob = {'last_seen': _iso(_ago(minutes=2))}
        verdict, _, _ = issue_lifecycle.evaluate(prob, 'SYS_ERR|h')
        self.assertEqual(verdict, issue_lifecycle.STILL_ACTIVE)

    def test_silent_source_resolves(self):
        prob = {'last_seen': _iso(_ago(minutes=90))}
        verdict, _, _ = issue_lifecycle.evaluate(prob, 'DISK_FULL|h|/')
        self.assertEqual(verdict, issue_lifecycle.RESOLVED)

    def test_between_thresholds_is_uncertain(self):
        prob = {'last_seen': _iso(_ago(minutes=20))}
        verdict, _, _ = issue_lifecycle.evaluate(prob, 'DISK_FULL|h|/')
        self.assertEqual(verdict, issue_lifecycle.UNCERTAIN)

    def test_unparsable_last_seen_does_not_crash(self):
        verdict, _, age = issue_lifecycle.evaluate({'last_seen': 'nesmysl'}, 'X|h')
        self.assertEqual(age, 0.0)
        self.assertEqual(verdict, issue_lifecycle.STILL_ACTIVE)


class TestSysErrMatching(unittest.TestCase):
    """Zúžené matchování — benigní šum ven, skutečné poruchy dovnitř."""

    def setUp(self):
        from sentinel.plugins import system_detector
        self.ign = system_detector._compiled('SYS_ERR_IGNORE_PATTERNS', [])
        self.kw = system_detector._compiled('SYS_ERR_KEYWORDS', [])

    def _matches(self, line):
        if any(r.search(line) for r in self.ign):
            return False
        return any(r.search(line) for r in self.kw)

    def test_benign_noise_ignored(self):
        for line in [
            "sshd[1]: error: kex_exchange_identification: read: Connection reset by peer",
            "login[127]: pam_systemd(login:session): Failed to create session: Seat has no VTs",
            "systemd-networkd-wait-online[1]: Timeout occurred while waiting for network",
            "rsyslogd[134]: activation of module imklog failed",
        ]:
            self.assertFalse(self._matches(line), f"mělo být ignorováno: {line[:50]}")

    def test_real_failures_detected(self):
        for line in [
            "systemd[1]: unciv@server.service: Failed with result 'exit-code'.",
            "corosync-qdevice[1084]: Connect timeout",
            "kernel: EXT4-fs error (device sda1): ext4_find_entry",
        ]:
            self.assertTrue(self._matches(line), f"mělo být zachyceno: {line[:50]}")

    def test_word_boundary_prevents_substring_hit(self):
        # Dřív "fail" chytlo i "failover" — hranice slov to řeší.
        self.assertFalse(self._matches("keepalived: VRRP failover completed to BACKUP"))


try:
    from sentinel.chat_service import _last_digest_date
    _HAS_CHAT_SERVICE = True
except ImportError:
    _HAS_CHAT_SERVICE = False


@unittest.skipUnless(_HAS_CHAT_SERVICE, "chat_service requires flask_socketio")
class TestDigestDateSeed(_DBCase):
    """Restart nesmí poslat denní AI digest podruhé."""

    def _seed(self):
        return _last_digest_date()

    def test_none_when_never_ran(self):
        self.assertIsNone(self._seed())

    def test_reads_stored_date(self):
        import json as _json
        state.set_setting('ai_daily_digest',
                          _json.dumps({"date": "2026-08-17 07:00", "text": "x"}))
        self.assertEqual(self._seed().isoformat(), '2026-08-17')

    def test_survives_garbage(self):
        state.set_setting('ai_daily_digest', 'tohle není JSON')
        self.assertIsNone(self._seed())

    def test_survives_missing_date_key(self):
        import json as _json
        state.set_setting('ai_daily_digest', _json.dumps({"text": "bez data"}))
        self.assertIsNone(self._seed())


if __name__ == '__main__':
    unittest.main()
