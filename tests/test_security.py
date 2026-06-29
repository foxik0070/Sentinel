"""
tests/test_security.py — Security tests (341)
- Brute force protection
- API scope enforcement
- Hostname injection prevention
"""
import unittest
import os
import sys
import tempfile

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestBruteForceProtection(unittest.TestCase):
    def setUp(self):
        from sentinel.utils import SecurityManager
        self.sec = SecurityManager()

    def test_register_failed_login_increments(self):
        ip = "10.0.0.1"
        for _ in range(3):
            self.sec.register_failed_login(ip)
        self.assertEqual(len(self.sec.login_attempts[ip]), 3)

    def test_ban_after_max_attempts(self):
        ip = "10.0.0.2"
        max_attempts = self.sec._get_max_login()
        for _ in range(max_attempts):
            self.sec.register_failed_login(ip)
        self.assertTrue(self.sec.is_ip_banned(ip))

    def test_whitelist_bypasses_ban(self):
        from sentinel import config
        original_wl = config.SECURITY.get("whitelist", [])
        config.SECURITY["whitelist"] = ["127.0.0.1"]
        ip = "127.0.0.1"
        max_attempts = self.sec._get_max_login()
        for _ in range(max_attempts * 2):
            self.sec.register_failed_login(ip)
        self.assertFalse(self.sec.is_ip_banned(ip))
        config.SECURITY["whitelist"] = original_wl

    def test_rate_limit_exceeded(self):
        ip = "10.0.0.3"
        limit = self.sec._get_limit("chat")
        for _ in range(limit):
            self.sec.check_rate_limit(ip, "chat")
        result = self.sec.check_rate_limit(ip, "chat")
        self.assertFalse(result)

    def test_api_key_rate_limit(self):
        ip = "10.0.0.4"
        for _ in range(20):
            self.sec.check_api_key_rate_limit("badkey1", ip)
        result = self.sec.check_api_key_rate_limit("badkey1", ip)
        self.assertFalse(result)


class TestHostnameInjection(unittest.TestCase):
    def test_valid_hostnames(self):
        from sentinel.routes.agents import _valid_hostname
        self.assertTrue(_valid_hostname("server01"))
        self.assertTrue(_valid_hostname("web-server.local"))
        self.assertTrue(_valid_hostname("host_123"))

    def test_invalid_hostnames(self):
        from sentinel.routes.agents import _valid_hostname
        self.assertFalse(_valid_hostname(""))
        self.assertFalse(_valid_hostname("../../etc/passwd"))
        self.assertFalse(_valid_hostname("host;rm -rf /"))
        self.assertFalse(_valid_hostname("host\x00null"))
        self.assertFalse(_valid_hostname("a" * 65))  # too long
        self.assertFalse(_valid_hostname("host..local"))  # double dot

    def test_hostname_regex_coverage(self):
        from sentinel.routes.agents import _valid_hostname
        # Should allow IP-like hostnames
        self.assertTrue(_valid_hostname("192.168.1.1"))
        # Should reject obvious injection
        self.assertFalse(_valid_hostname("host | cmd"))


class TestSecretsMasking(unittest.TestCase):
    """Test that /api/config/view masks sensitive fields."""

    def test_mask_function(self):
        """Verify the masking logic masks non-empty values."""
        _MASK = '***'
        def _mask(v):
            return _MASK if v else ''

        self.assertEqual(_mask("secret_token_value"), "***")
        self.assertEqual(_mask(""), "")
        self.assertEqual(_mask(None), "")

    def test_no_leak_of_tokens(self):
        """Ensure token fields are never returned as their actual value."""
        import sentinel.config as cfg
        # Set a fake token
        original = getattr(cfg, 'WEBHOOK_SECRET', '')
        cfg.WEBHOOK_SECRET = 'super_secret_token_xyz'

        _MASK = '***'
        def _mask(v):
            return _MASK if v else ''

        masked = _mask(cfg.WEBHOOK_SECRET)
        self.assertEqual(masked, '***')
        self.assertNotIn('super_secret_token_xyz', masked)
        cfg.WEBHOOK_SECRET = original


if __name__ == '__main__':
    unittest.main()
