"""capacity_detector: záchyt zmizí, když disk už není přes práh.

Orchestrátor posílá do capacity.log hlavičku `SERVER:` za každý prošlý
host, i když pod ní nic není. Detektor dřív reconcile pouštěl jen pro
servery, které měly aspoň jeden mount přes práh — host, kde se místo
uvolnilo, se tak v dávce vůbec neobjevil a DISK_FULL na něm visel dál
(host hlásil 94 % ještě dlouho po úklidu na 66 %).
"""
import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel.plugins import capacity_detector


class TestCapacityReconcile(unittest.TestCase):
    def _run(self, lines):
        det = capacity_detector.Detector("capacity_detector")
        with mock.patch.object(capacity_detector.api, 'report_problem') as rep, \
             mock.patch.object(capacity_detector.api, 'reconcile_issues') as rec, \
             mock.patch.object(capacity_detector.api, 'get_infrastructure_label',
                               return_value='OTHER'):
            det.process(lines, '/var/log/sentinel/logs/capacity.log')
        return rep, rec

    def test_server_without_mounts_is_reconciled_empty(self):
        rep, rec = self._run(["SERVER: host-a", "SERVER: nas",
                              "/dev/sda1 1T 900G 100G 90% /data"])
        rep.assert_called_once()
        calls = {c.kwargs['host']: c.args[1] for c in rec.call_args_list}
        self.assertEqual(calls['host-a'], set(), 'host-a nemá nic přes práh → zavřít')
        self.assertEqual(calls['nas'], {'DISK_FULL|nas|/data'})

    def test_server_missing_from_sweep_is_not_touched(self):
        """Host, který se nepřipojil, v dávce není — jeho záchyty nechat být."""
        _, rec = self._run(["SERVER: nas", "/dev/sda1 1T 900G 100G 90% /data"])
        self.assertEqual([c.kwargs['host'] for c in rec.call_args_list], ['nas'])


if __name__ == '__main__':
    unittest.main()
