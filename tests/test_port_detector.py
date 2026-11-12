"""port_detector: loopback porty nejsou bezpečnostní změna.

Vývojové nástroje a IDE otevírají na 127.0.0.1 náhodný port pro
každou session. Detektor bral porty z celého řádku `ss -tuln` včetně
loopbacku, takže každá nová session vyrobila „Port list changed".
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import config
from sentinel.plugins import port_detector as pd

HDR = "Netid State  Recv-Q Send-Q Local Address:Port  Peer Address:Port"


def ss(*locals_):
    return [HDR] + [f"tcp   LISTEN 0      512    {a}      0.0.0.0:*" for a in locals_]


class TestPortDetector(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self._orig = config.LOG_DIR
        config.LOG_DIR = self._dir

    def tearDown(self):
        config.LOG_DIR = self._orig
        shutil.rmtree(self._dir, ignore_errors=True)

    def _sweep(self, det, lines):
        with mock.patch.object(pd.api, 'report_problem') as rep, \
             mock.patch.object(pd.api, 'get_problem', return_value=None), \
             mock.patch.object(pd.api, 'resolve_problem'), \
             mock.patch.object(pd.api, 'get_infrastructure_label', return_value='HOME'):
            det.process(["SERVER: host-a"] + lines, os.path.join(self._dir, 'ports.log'))
        return rep

    def test_loopback_ports_ignored(self):
        det = pd.Detector("port_detector")
        self._sweep(det, ss("0.0.0.0:22", "127.0.0.1:43129"))
        rep = self._sweep(det, ss("0.0.0.0:22", "127.0.0.1:45303", "[::1]:5000",
                                  "[::ffff:127.0.0.1]:6000"))
        rep.assert_not_called()

    def test_public_port_still_alerts(self):
        det = pd.Detector("port_detector")
        self._sweep(det, ss("0.0.0.0:22"))
        rep = self._sweep(det, ss("0.0.0.0:22", "0.0.0.0:8080"))
        rep.assert_called_once()
        self.assertIn("Added: 8080", rep.call_args.args[1]['last_line'])

    def test_peer_column_not_counted(self):
        """Port z „Peer Address" není poslouchající port."""
        det = pd.Detector("port_detector")
        self._sweep(det, ss("0.0.0.0:22"))
        rep = self._sweep(det, [HDR, "tcp LISTEN 0 512 0.0.0.0:22 10.0.0.5:9999"])
        rep.assert_not_called()

    def test_old_baseline_format_is_rebuilt_silently(self):
        with open(os.path.join(self._dir, 'ports_baseline.json'), 'w') as f:
            json.dump({'host-a': '22,43129'}, f)
        det = pd.Detector("port_detector")
        rep = self._sweep(det, ss("0.0.0.0:22", "127.0.0.1:43129"))
        rep.assert_not_called()
        with open(os.path.join(self._dir, 'ports_baseline.json')) as f:
            self.assertEqual(json.load(f), {'host-a': '22', '_format': pd._BASELINE_FORMAT})


class TestAnomalyIgnore(unittest.TestCase):
    def test_default_ignores_ai_sessions(self):
        import fnmatch
        self.assertTrue(any(fnmatch.fnmatch('ai_sessions', p)
                            for p in config.TELEMETRY_ANOMALY_IGNORE))

    def test_ignore_list_checked_in_detection(self):
        src = open(os.path.join(_ROOT, 'sentinel/state_issues.py'), encoding='utf-8').read()
        self.assertIn('TELEMETRY_ANOMALY_IGNORE', src)


if __name__ == '__main__':
    unittest.main()
