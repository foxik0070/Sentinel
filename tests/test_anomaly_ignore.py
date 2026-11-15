"""TELEMETRY_ANOMALY_IGNORE — metriky, u kterych se skok nehlasi.

Puvodne byly tyhle testy u port_detectoru, se kterym nesouvisi. Detektor
se presunul do sentinel-plugins, tohle patri k Sentinelu.
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import config


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
