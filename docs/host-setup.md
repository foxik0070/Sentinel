# Příprava monitorovaného stroje pro AI funkce

Aby AI vrstva fungovala naplno, potřebuje Sentinel na každém monitorovaném
stroji účet, kterým se přihlásí, a přesně vymezená oprávnění. Tenhle dokument
popisuje **co nastavit a proč** — ne jen příkazy k opsání.

Bez tohohle nastavení Sentinel dál běží a hlásí problémy, ale **nedokáže si
o nich zjistit podrobnosti**. Diagnostika vrátí prázdno, AI bude odpovídat na
základě jediné řádky z logu a její návrhy budou o dost horší.

---

## Proč dedikovaný účet a ne root

Sentinel má SSH přístup na celou infrastrukturu a část jeho rozhodnutí navrhuje
jazykový model. Kdyby se hlásil jako root, jakákoli chyba — v kódu, v modelu,
nebo podstrčená útočníkem přes obsah logu — by měla neomezené následky.

Účet `sentinel` proto standardně nemá žádná zvláštní práva. Root dostane jen
pro konkrétní příkazy vyjmenované v sudoers, a to je seznam, který si můžeš
přečíst a odsouhlasit. **Co v něm není, Sentinel neprovede** — ani kdyby to
model navrhl.

---

## 1. Uživatel a SSH klíč

Založ účet bez hesla a bez shellu pro interaktivní přihlášení není nutný;
Sentinel spouští jednotlivé příkazy, ne relace.

```bash
useradd --system --create-home --shell /bin/bash sentinel
mkdir -p /home/sentinel/.ssh && chmod 700 /home/sentinel/.ssh
# veřejný klíč Sentinelu (protějšek k ssh_execution.key_path na serveru)
echo 'ssh-ed25519 AAAA... sentinel@rpi5' > /home/sentinel/.ssh/authorized_keys
chmod 600 /home/sentinel/.ssh/authorized_keys
chown -R sentinel:sentinel /home/sentinel/.ssh
```

Sentinel se připojuje s `BatchMode=yes` — **žádný příkaz se nesmí ptát na
heslo**. Když se zeptá, spojení tiše selže. Proto se dole u sudoers používá
`NOPASSWD`.

Klíč doporučuji omezit i na straně `authorized_keys` (`from="IP_SENTINELU"`),
aby ho nešlo použít odjinud.

---

## 2. Skupina `systemd-journal` — bez ní je diagnostika poloslepá

Toto je nejčastěji opomenutý krok a projeví se nenápadně: `journalctl` místo
chyby vrátí zdvořilou hlášku, že nic nevidí, a AI z toho usoudí, že v logu nic
není.

```bash
usermod -aG systemd-journal sentinel
```

Členství se projeví **až po novém přihlášení**. Pozor na sdílená SSH spojení
(`ControlPersist`) — ta drží původní skupiny, dokud nevyprší.

Ověření:

```bash
ssh sentinel@HOST id -nG          # musí obsahovat systemd-journal
ssh sentinel@HOST journalctl -n 5 --no-pager
```

Když druhý příkaz vypíše *„You are currently not seeing messages from other
users and the system"*, skupina chybí nebo se ještě neprojevila.

---

## 3. Sudoers — co Sentinel smí jako root

Sudoers musí být **podmnožinou** aplikačního whitelistu (`allowed_commands`
v konfiguraci Sentinelu). Aplikace i systém tak musí souhlasit, jinak se
příkaz neprovede — dvě nezávislé pojistky.

Vytvoř `/etc/sudoers.d/sentinel` (vždy přes `visudo -f`, ať se překlep
neprojeví zamčeným sudo):

```
# Diagnostika — read-only, ale root pro plný výstup
sentinel ALL=(root) NOPASSWD: /usr/bin/ss -tlnp
sentinel ALL=(root) NOPASSWD: /usr/bin/ss -tlnH
sentinel ALL=(root) NOPASSWD: /usr/bin/du -sh /var/*
sentinel ALL=(root) NOPASSWD: /bin/mount
sentinel ALL=(root) NOPASSWD: /usr/bin/dpkg -l

# Remediace — jen konkrétní služby, ne obecně
sentinel ALL=(root) NOPASSWD: /bin/systemctl restart nginx.service
sentinel ALL=(root) NOPASSWD: /bin/systemctl restart <další konkrétní jednotky>

# Údržba logů
sentinel ALL=(root) NOPASSWD: /usr/bin/journalctl --vacuum-time=7d
sentinel ALL=(root) NOPASSWD: /usr/bin/journalctl --rotate
```

Zvaž pořádně, co sem dáš. **Nepiš `systemctl restart *`** — tím bys povolil
restart čehokoli včetně `sshd`, a přišel tak o vlastní přístup na stroj.
Vyjmenuj konkrétní jednotky, které chceš nechat spravovat automaticky.

Ověření (nesmí se ptát na heslo):

```bash
ssh sentinel@HOST 'sudo -n ss -tlnp | head -3'
```

### Které příkazy sudo vyžadují

Sentinel prefixuje `sudo -n` **jen** u těchto začátků příkazu; všechno ostatní
běží bez zvýšených práv:

| Skupina | Příkazy |
|---|---|
| Správa služeb | `systemctl restart/start/stop/enable/disable/mask/unmask/reload/daemon-reload` |
| Souborové systémy | `mount`, `umount` |
| Balíčky | `apt-get`, `apt`, `dpkg` |
| Údržba logů | `journalctl --rotate`, `journalctl --vacuum` |
| Zálohy | `proxmox-backup-client garbage-collect` |
| Restart stroje | `reboot`, `shutdown`, `poweroff` |
| Diagnostika s plným výstupem | `ss`, `du` |

Naopak **bez sudo** běží běžná diagnostika: `df`, `free`, `uptime`, `ps`,
`systemctl status`, `systemctl --failed`, `journalctl -p err`, `ip addr`,
`dmesg`, `who`, `uname`.

---

## 4. Co má být na stroji nainstalované

AI diagnostika si vybírá z pevného katalogu příkazů. Chybějící nástroj
neshodí Sentinel, jen daný krok vrátí chybu — ale zbytečně.

| Balíček | K čemu |
|---|---|
| `iproute2` | `ss`, `ip` — porty a rozhraní |
| `procps` | `free`, `uptime`, `ps` |
| `coreutils` | `df`, `du`, `who` |
| `systemd` | `systemctl`, `journalctl`, `timedatectl` |
| `util-linux` | `dmesg`, `mount` |

Na minimálních obrazech (Alpine, distroless kontejnery) část z nich chybí nebo
má jinou syntaxi. Tam počítej s tím, že diagnostika bude omezená.

---

## 5. Čtení logů aplikací

Sentinel čte systémový journal, ale aplikace často píšou do vlastních souborů.
Když je adresář přístupný jen rootovi, diagnostika se k nim nedostane a
**dozvíš se jen to, že služba spadla, ne proč**.

Máš tři možnosti, seřazené od nejlepší:

1. **Nechat aplikaci psát do journalu** (`StandardOutput=journal` v unitu).
   Nejčistší — Sentinel na to má přístup přes `systemd-journal` a nic dalšího
   se nenastavuje.
2. **Přidat `sentinel` do skupiny, která log vlastní** (`usermod -aG adm sentinel`,
   pokud logy patří skupině `adm`).
3. **Povolit konkrétní čtení v sudoers** — nejadresnější, ale musíš to udržovat:
   ```
   sentinel ALL=(root) NOPASSWD: /usr/bin/tail -n 50 /var/log/mojeapp/app.log
   ```

> Konkrétní příklad z provozu: `/var/log/rpi-backup/` má práva `drwxr-x--- root
> root`, takže Sentinel vidí, že záloha selhala, ale příčinu v logu nepřečte.

---

## 6. Ověření, že je hotovo

```bash
HOST=vas-stroj

ssh sentinel@$HOST id -nG                    # obsahuje systemd-journal?
ssh sentinel@$HOST journalctl -n 3 --no-pager # vrací záznamy, ne hlášku o právech?
ssh sentinel@$HOST 'sudo -n ss -tlnp | head' # projde bez dotazu na heslo?
ssh sentinel@$HOST 'df -h; free -m; systemctl --failed --no-pager'
```

Ze samotného Sentinelu pak nejrychleji takhle:

```bash
sudo python3 -c "
from sentinel import actions
for c in ('id -nG', 'journalctl -n 3 --no-pager', 'df -h'):
    ok, out = actions.run_ssh_command_real('$HOST', c, timeout=20, internal=True)
    print(('OK  ' if ok else 'CHYBA'), c, '->', out[:80].replace(chr(10),' '))"
```

Pozor: testuj to jako **root** (`sudo`), protože soubor známých hostů
`/var/lib/sentinel/known_hosts` patří rootovi. Jako jiný uživatel selže
přidání dosud neznámého stroje.

---

## 7. Co dělat, když AI odpovídá špatně

Než začneš ladit prompty, ověř tohle — ve většině případů je příčina tady:

| Příznak | Nejpravděpodobnější příčina |
|---|---|
| „Nemám dost informací" u všeho | Chybí `systemd-journal`, diagnostika vrací prázdno |
| Diagnostika hlásí prázdný výstup | Chybí nástroj (`iproute2`, `procps`) |
| Návrhy jsou obecné, neodkazují na stav stroje | Diagnostické kroky selhávají — zkontroluj sudoers |
| „sudo: a password is required" | Chybí `NOPASSWD` nebo příkaz není v sudoers |
| Zná, že služba spadla, ale ne proč | Log aplikace je mimo journal a nečitelný — viz bod 5 |

Kompletní seznam provozních pastí je v [troubleshooting.md](troubleshooting.md).

---

## Shrnutí minimálního nastavení

```bash
useradd --system --create-home --shell /bin/bash sentinel
usermod -aG systemd-journal sentinel
install -d -m 700 -o sentinel -g sentinel /home/sentinel/.ssh
echo 'ssh-ed25519 AAAA... sentinel@rpi5' > /home/sentinel/.ssh/authorized_keys
chmod 600 /home/sentinel/.ssh/authorized_keys
chown sentinel:sentinel /home/sentinel/.ssh/authorized_keys
visudo -f /etc/sudoers.d/sentinel     # viz bod 3
```

Tím Sentinel získá **čtení stavu stroje a systémového logu**. Právo cokoli
měnit má jen tam, kde mu ho výslovně dáš v sudoers — a i tak návrh na změnu
prochází schválením v UI.
