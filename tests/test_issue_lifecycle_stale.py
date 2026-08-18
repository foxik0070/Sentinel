"""
Tests: issue nesmí viset, když už neplatí.

Pokrývá tři cesty, kterými se do UI dostávaly neplatné issues:
  1. detektor ohlásí zotavení (status=resolved) — dřív se uložilo jako aktivní
  2. details JSON přebil sloupce — last_seen v UI i pro stale TTL bylo cizí
  3. restart přehrál tail logů — dávno vyřešené issue vstalo s čerstvým časem

Run:
    python -m pytest tests/test_issue_lifecycle_stale.py -v
    python -m unittest tests.test_issue_lifecycle_stale -v
"""
import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import api, config, state, watcher


import contextlib


@contextlib.contextmanager
def _snapshot_patterns(patterns):
    """Dočasně nastaví config.SNAPSHOT_LOGS a přegeneruje regexy watcheru."""
    orig = getattr(config, 'SNAPSHOT_LOGS', [])
    config.SNAPSHOT_LOGS = patterns
    watcher.compile_patterns()
    try:
        yield
    finally:
        config.SNAPSHOT_LOGS = orig
        watcher.compile_patterns()


def _data(msg="Test message", channel="general", plugin="test_plugin", **extra):
    d = {
        "last_line": msg,
        "channel_type": channel,
        "plugin_name": plugin,
        "host": "test-host",
    }
    d.update(extra)
    return d


class _DBTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self._tmp.close()
        self._orig_db = state.DB_FILE
        state.DB_FILE = self._tmp.name  # _db_file() čte override odsud
        state._local = threading.local()
        state.init_db()

    def tearDown(self):
        state.DB_FILE = self._orig_db
        os.unlink(self._tmp.name)


class TestDetectorRecovery(_DBTestCase):
    """report_problem(status='resolved') musí issue zavřít, ne ho uložit jako aktivní."""

    def test_resolved_status_closes_issue(self):
        key = "PERF|WIN|testpc|CPU"
        api.report_problem(key, _data("CPU 95.0%", plugin="detector_windows"))
        self.assertIsNotNone(state.get_problem(key), "příprava: issue má být aktivní")

        api.report_problem(key, {'status': 'resolved', 'last_seen':
                                 datetime.now(timezone.utc).isoformat()})
        self.assertIsNone(state.get_problem(key),
                          "zotavení hlášené detektorem musí issue odstranit")

    def test_resolved_payload_without_last_line_still_closes(self):
        """Payload zotavení nemá last_line — save_problem ho dřív tiše zahodil."""
        key = "PERF|WIN|testpc|RAM"
        api.report_problem(key, _data("RAM 95.0%", plugin="detector_windows"))
        api.report_problem(key, {'status': 'resolved'})
        self.assertIsNone(state.get_problem(key))

    def test_resolved_is_archived_with_reason(self):
        key = "PERF|WIN|testpc|DISK|C:"
        api.report_problem(key, _data("Disk C: 98%", plugin="detector_windows"))
        api.report_problem(key, {'status': 'resolved'})
        conn = state._get_conn()
        row = conn.execute(
            "SELECT resolve_reason FROM issue_history WHERE key=?", (key,)
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row, "vyřešené issue musí zůstat v historii")
        self.assertEqual(row[0], 'detector_ok')

    def test_resolve_of_unknown_key_is_noop(self):
        api.report_problem("NEEXISTUJE|X", {'status': 'resolved'})
        self.assertIsNone(state.get_problem("NEEXISTUJE|X"))

    def test_active_status_still_creates_issue(self):
        """Regrese: běžné hlášení se nesmí novou větví rozbít."""
        api.report_problem("SEC|X|abc", _data("Failed password"))
        self.assertIsNotNone(state.get_problem("SEC|X|abc"))


class TestAuthoritativeColumns(_DBTestCase):
    """Sloupce v problems přebijí details JSON — jinak UI ukazuje cizí čas."""

    def test_details_last_seen_does_not_override_column(self):
        stale = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        api.report_problem("K|1", _data("zpráva", last_seen=stale))
        prob = state.get_problem("K|1")
        self.assertNotEqual(prob['last_seen'], stale,
                            "last_seen z payloadu detektoru nesmí přebít skutečný čas uložení")

    def test_details_status_does_not_override_column(self):
        api.report_problem("K|2", _data("zpráva"))
        state.acknowledge_issue("K|2", "tester")
        prob = state.get_problem("K|2")
        self.assertEqual(prob['status'], 'acknowledged')

    def test_active_issues_uses_same_merge(self):
        stale = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        api.report_problem("K|3", _data("zpráva", last_seen=stale))
        issue = next(i for i in state.get_active_issues() if i['key'] == "K|3")
        self.assertNotEqual(issue['last_seen'], stale)

    def test_non_authoritative_details_field_survives(self):
        """cluster/log_file z payloadu se nesmí ztratit — sloupec pro ně není."""
        api.report_problem("K|4", _data("zpráva", cluster="KAROLINA"))
        self.assertEqual(state.get_problem("K|4").get('cluster'), "KAROLINA")


class TestStaleResolveUsesRealTime(_DBTestCase):
    """Stale sweep počítá stáří ze sloupce, ne z payloadu detektoru."""

    def _age_issue(self, key, hours):
        old = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        conn = state._get_conn()
        conn.execute("UPDATE problems SET last_seen=? WHERE key=?", (old, key))
        conn.commit()
        conn.close()

    def test_old_issue_is_resolved(self):
        api.report_problem("OLD|1", _data("dávná zpráva", plugin="detector_who"))
        self._age_issue("OLD|1", 200)
        state.resolve_stale_problems()
        self.assertIsNone(state.get_problem("OLD|1"),
                          "issue starší než TTL musí zmizet")

    def test_fresh_issue_survives(self):
        api.report_problem("FRESH|1", _data("čerstvá zpráva"))
        state.resolve_stale_problems()
        self.assertIsNotNone(state.get_problem("FRESH|1"))

    def test_future_last_seen_in_details_does_not_shield_issue(self):
        """Payload s časem v budoucnu dřív issue proti sweepu imunizoval."""
        future = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
        api.report_problem("OLD|2", _data("zpráva", last_seen=future))
        self._age_issue("OLD|2", 200)
        state.resolve_stale_problems()
        self.assertIsNone(state.get_problem("OLD|2"))


class TestAckAndSnoozeSurviveRedetection(_DBTestCase):
    """Re-detekce nesmí rušit potvrzení ani odložení."""

    def test_snooze_survives_redetection(self):
        api.report_problem("S|1", _data("opakující se zpráva"))
        state.snooze_problem("S|1", 24)
        api.report_problem("S|1", _data("opakující se zpráva"))
        conn = state._get_conn()
        row = conn.execute("SELECT snoozed_until FROM problems WHERE key='S|1'").fetchone()
        conn.close()
        self.assertIsNotNone(row[0], "snooze se při další detekci nesmí vynulovat")

    def test_ack_survives_redetection(self):
        api.report_problem("A|1", _data("opakující se zpráva"))
        state.acknowledge_issue("A|1", "tester")
        api.report_problem("A|1", _data("opakující se zpráva"))
        self.assertEqual(state.get_problem("A|1")['status'], 'acknowledged')

    def test_redetection_of_acked_issue_bumps_occurrence(self):
        api.report_problem("A|2", _data("opakující se zpráva"))
        state.acknowledge_issue("A|2", "tester")
        api.report_problem("A|2", _data("opakující se zpráva"))
        self.assertEqual(state.get_problem("A|2")['occurrence_count'], 2)


class TestSnapshotDispatch(unittest.TestCase):
    """Snapshot se musí dispatchovat i při nezměněné velikosti souboru.

    Reprodukce SV3: `: > sv3.log` + append stejně dlouhého obsahu → velikost
    sedí na uloženou pozici → dřív se vrátilo bez dispatche, detektoru se
    nezavolal process() a jeho resolve větev issue nikdy neuklidila.
    """

    def setUp(self):
        self._logdir = tempfile.mkdtemp()
        self._log = os.path.join(self._logdir, "sv3.log")
        self._dispatched = []

    def _rewrite(self, text):
        with open(self._log, "w") as f:
            f.write(text)

    def _fire(self, handler):
        handler._process_event(self._log, False, is_new_file=False)

    def _handler(self):
        h = watcher.LogHandler()
        import sentinel.plugin_manager as pm
        self._orig_dispatch = pm.dispatch
        pm.dispatch = lambda path, lines: self._dispatched.append(lines)
        self.addCleanup(lambda: setattr(pm, 'dispatch', self._orig_dispatch))
        return h

    def test_same_size_rewrite_is_dispatched(self):
        h = self._handler()
        with _snapshot_patterns(["sv3.log"]):
            self._rewrite("SV3_TEMP: 11.7C\n")
            self._fire(h)
            self._rewrite("SV3_TEMP: 11.8C\n")   # stejná délka
            self._fire(h)
        self.assertEqual(len(self._dispatched), 2,
                         "snapshot se musí dispatchovat i beze změny velikosti")
        self.assertEqual(self._dispatched[1], ["SV3_TEMP: 11.8C\n"])

    def test_snapshot_always_read_whole(self):
        h = self._handler()
        with _snapshot_patterns(["sv3.log"]):
            self._rewrite("SV3_TEMP: 18.7C\nSV3_ALARM WARN: 18.7C\n")
            self._fire(h)
            self._rewrite("SV3_TEMP: 11.7C\n")   # alarm zmizel
            self._fire(h)
        self.assertEqual(self._dispatched[1], ["SV3_TEMP: 11.7C\n"],
                         "snapshot se čte celý, ne jen přírůstek")

    def test_non_snapshot_keeps_incremental_behaviour(self):
        """Regrese: běžný log se nesmí začít číst celý dokola."""
        h = self._handler()
        with _snapshot_patterns([]):
            self._rewrite("radek 1\n")
            self._fire(h)
            with open(self._log, "a") as f:
                f.write("radek 2\n")
            self._fire(h)
        self.assertEqual(self._dispatched[1], ["radek 2\n"])

    def test_non_snapshot_same_size_is_skipped(self):
        h = self._handler()
        with _snapshot_patterns([]):
            self._rewrite("radek 1\n")
            self._fire(h)
            before = len(self._dispatched)
            self._fire(h)
        self.assertEqual(len(self._dispatched), before,
                         "u běžného logu beze změny velikosti se nemá číst")


class TestMissingCountPersisted(_DBTestCase):
    """Detektory si jím počítají 'kolikrát po sobě chybí' — musí přežít v DB."""

    def test_missing_count_saved(self):
        api.report_problem("M|1", _data("zpráva", missing_count=2))
        self.assertEqual(state.get_problem("M|1")['missing_count'], 2)

    def test_missing_count_survives_report_without_it(self):
        """Hlášení bez missing_count nesmí vynulovat počítadlo reconcile."""
        api.report_problem("M|2", _data("zpráva", missing_count=2))
        api.report_problem("M|2", _data("zpráva"))
        self.assertEqual(state.get_problem("M|2")['missing_count'], 2)

    def test_missing_count_can_be_reset(self):
        api.report_problem("M|3", _data("zpráva", missing_count=2))
        api.report_problem("M|3", _data("zpráva", missing_count=0))
        self.assertEqual(state.get_problem("M|3")['missing_count'], 0)

    def test_new_issue_defaults_to_zero(self):
        api.report_problem("M|4", _data("zpráva"))
        self.assertEqual(state.get_problem("M|4")['missing_count'], 0)

    def test_counter_roundtrip_via_active_issues(self):
        """Přesně smyčka detektor_sv3: přečti issue, zvyš, ulož, přečti zpět."""
        api.report_problem("M|5", _data("zpráva"))
        issue = next(i for i in state.get_active_issues() if i['key'] == "M|5")
        issue['missing_count'] = issue.get('missing_count', 0) + 1
        api.report_problem("M|5", issue)
        again = next(i for i in state.get_active_issues() if i['key'] == "M|5")
        self.assertEqual(again['missing_count'], 1)


class TestStableKeyHash(unittest.TestCase):
    """Klíč issue musí přežít restart procesu."""

    def test_stable_across_calls(self):
        line = "root pts/0 2026-08-07 11:30"
        self.assertEqual(api.stable_key_hash(line), api.stable_key_hash(line))

    def test_known_value(self):
        """Fixní hodnota — změna algoritmu osiří všechna existující issues."""
        self.assertEqual(api.stable_key_hash("abc"), "a9993e364706")

    def test_different_input_differs(self):
        self.assertNotEqual(api.stable_key_hash("a"), api.stable_key_hash("b"))

    def test_non_ascii_does_not_raise(self):
        self.assertTrue(api.stable_key_hash("Teplota 18.7°C přílišná"))


class TestActiveKeysByPrefix(_DBTestCase):
    """Snapshot detektory potřebují vědět, co mají uklidit."""

    def test_returns_only_matching_prefix(self):
        api.report_problem("ROOT_LOGIN|IT4I|aaa", _data("root session a"))
        api.report_problem("ROOT_LOGIN|IT4I|bbb", _data("root session b"))
        api.report_problem("SEC|IT4I|ccc", _data("jiný kanál"))
        keys = set(api.get_active_keys("ROOT_LOGIN|IT4I|"))
        self.assertEqual(keys, {"ROOT_LOGIN|IT4I|aaa", "ROOT_LOGIN|IT4I|bbb"})

    def test_includes_snoozed(self):
        """Odložené issue je pořád aktivní — snapshot ho musí umět uklidit."""
        api.report_problem("ROOT_LOGIN|IT4I|ddd", _data("root session d"))
        state.snooze_problem("ROOT_LOGIN|IT4I|ddd", 24)
        self.assertIn("ROOT_LOGIN|IT4I|ddd", api.get_active_keys("ROOT_LOGIN|IT4I|"))

    def test_empty_when_nothing_matches(self):
        self.assertEqual(api.get_active_keys("NIC|"), [])


class TestWatcherOffsets(_DBTestCase):
    """Pozice v logách přežívají restart — jinak se tail přehraje znovu."""

    def setUp(self):
        super().setUp()
        self._logdir = tempfile.mkdtemp()
        self._log = os.path.join(self._logdir, "test.log")

    def _write(self, text, mode="w"):
        with open(self._log, mode) as f:
            f.write(text)

    def test_unseen_file_is_not_replayed(self):
        self._write("stará zpráva 1\nstará zpráva 2\n")
        lines, offset = watcher.read_new_lines(self._log, None)
        self.assertEqual(lines, [], "historii logu nesmíme hlásit jako aktuální problém")
        self.assertEqual(offset, os.path.getsize(self._log))

    def test_only_new_lines_returned(self):
        self._write("stará\n")
        _, offset = watcher.read_new_lines(self._log, None)
        self._write("nová\n", mode="a")
        lines, new_offset = watcher.read_new_lines(self._log, offset)
        self.assertEqual(lines, ["nová\n"])
        self.assertEqual(new_offset, os.path.getsize(self._log))

    def test_nothing_new_returns_empty(self):
        self._write("řádek\n")
        _, offset = watcher.read_new_lines(self._log, None)
        lines, _ = watcher.read_new_lines(self._log, offset)
        self.assertEqual(lines, [])

    def test_rotation_reads_from_start(self):
        """Soubor se zmenšil = rotace/přepis snapshotu → číst celý."""
        self._write("dlouhý původní obsah, mnoho bajtů navíc\n")
        _, offset = watcher.read_new_lines(self._log, None)
        self._write("krátký\n")
        lines, _ = watcher.read_new_lines(self._log, offset)
        self.assertEqual(lines, ["krátký\n"])

    def test_offsets_roundtrip_through_db(self):
        self._write("obsah\n")
        watcher.save_offsets({self._log: 42})
        self.assertEqual(watcher.load_offsets().get(self._log), 42)

    def test_offsets_forget_deleted_files(self):
        watcher.save_offsets({self._log: 1, "/neexistuje/x.log": 2})
        self.assertNotIn("/neexistuje/x.log", watcher.load_offsets())

    def test_corrupt_offsets_do_not_raise(self):
        state.set_setting(watcher.OFFSETS_SETTING, "{tohle není JSON")
        self.assertEqual(watcher.load_offsets(), {})

    def test_max_lines_caps_burst(self):
        self._write("".join(f"řádek {n}\n" for n in range(500)))
        lines, _ = watcher.read_new_lines(self._log, 0, max_lines=200)
        self.assertEqual(len(lines), 200)

    def test_seed_unknown_file_starts_at_end(self):
        """Nový soubor bez uložené pozice = žádné přehrání historie."""
        self._write("historie\n")
        self.assertEqual(watcher.seed_positions(self._logdir)[self._log],
                         os.path.getsize(self._log))

    def test_seed_uses_saved_offset(self):
        self._write("aaa\nbbb\n")
        watcher.save_offsets({self._log: 4})
        self.assertEqual(watcher.seed_positions(self._logdir)[self._log], 4)

    def test_seed_snapshot_starts_at_zero(self):
        """Snapshot nese aktuální stav — po startu se čte celý, ne od konce."""
        self._write("SV3_TEMP: 11.7C\n")
        with _snapshot_patterns(["test.log"]):
            self.assertEqual(watcher.seed_positions(self._logdir)[self._log], 0)

    def test_snapshot_read_ignores_missing_offset(self):
        self._write("SV3_ALARM WARN: 18.7C\n")
        with _snapshot_patterns(["test.log"]):
            lines, _ = watcher.read_new_lines(self._log, None)
        self.assertEqual(lines, ["SV3_ALARM WARN: 18.7C\n"])

    def test_seed_ignores_non_log_files(self):
        self._write("x\n")
        with open(os.path.join(self._logdir, "poznamka.txt"), "w") as f:
            f.write("y\n")
        self.assertEqual(list(watcher.seed_positions(self._logdir)), [self._log])


if __name__ == '__main__':
    unittest.main()
