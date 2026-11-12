"""Teplota jen z hostů s vlastním čidlem + PBS TLS šum.

LXC kontejnery a VM čtou čidlo hypervizoru. Jedna horká noc na hypervizoru
(75 °C místo 60) tak udělala telemetry anomálii — jednu za každého hosta.
"""
import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import config
from sentinel.plugins import temperature_detector as td
from sentinel.plugins import system_detector as sd


class TestTemperatureHosts(unittest.TestCase):
    LOG = ["SERVER: hypervisor01", "75000", "SERVER: guest01", "75000",
           "SERVER: host-a", "63350"]

    def _run(self, hosts, active=None):
        active = active or set()
        with mock.patch.object(config, 'TEMPERATURE_HOSTS', hosts), \
             mock.patch.object(td.api, 'save_telemetry_snapshot') as tel, \
             mock.patch.object(td.api, 'report_problem') as rep, \
             mock.patch.object(td.api, 'resolve_problem') as res, \
             mock.patch.object(td.api, 'get_problem', side_effect=lambda k: k in active), \
             mock.patch.object(td.api, 'get_infrastructure_label', return_value='HOME'):
            td.Detector("temperature_detector").process(self.LOG, "/x/temperature.log")
        sampled = [list(c.args[1])[0] for c in tel.call_args_list]
        return sampled, rep, res

    def test_empty_list_keeps_all_hosts(self):
        sampled, _, _ = self._run([])
        self.assertEqual(sampled, ['temp.hypervisor01', 'temp.guest01', 'temp.host-a'])

    def test_guest_is_skipped(self):
        sampled, rep, _ = self._run(['hypervisor*', 'host-a'])
        self.assertEqual(sampled, ['temp.hypervisor01', 'temp.host-a'])
        hosts = {c.args[1]['host'] for c in rep.call_args_list}
        self.assertNotIn('guest01', hosts)

    def test_leftover_guest_issues_are_closed(self):
        _, _, res = self._run(['hypervisor*', 'host-a'],
                              active={'TELEMETRY_ANOMALY|Hardware|temp.guest01'})
        self.assertIn(mock.call('TELEMETRY_ANOMALY|Hardware|temp.guest01'), res.call_args_list)
        self.assertNotIn(mock.call('TEMP_HIGH|guest01'), res.call_args_list,
                         'neexistující záchyt se neresolvuje')


class TestPbsTlsNoise(unittest.TestCase):
    def test_pbs_tls_peek_ignored(self):
        line = ("Nov 12 09:46:46 pbs01 proxmox-backup-proxy[555965]: "
                "[[::ffff:10.0.0.5]:40566] failed to check for TLS handshake: "
                "couldn't peek into incoming TCP stream")
        with mock.patch.object(sd.api, 'report_problem') as rep, \
             mock.patch.object(sd.api, 'get_infrastructure_label', return_value='HOME'):
            sd.Detector("system_detector").process(
                ["SERVER: pbs01", line], "/x/system.log")
        rep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
