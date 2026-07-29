# Architecture Decision Records

## ADR-001: SQLite jako primární datové úložiště

**Status:** Accepted  
**Datum:** 2026-06

### Kontext
Sentinel běží na Raspberry Pi 5 s omezenou pamětí. Potřebujeme perzistentní úložiště pro issues, telemetrii, sessions a konfiguraci.

### Rozhodnutí
Používáme SQLite 3 v WAL (Write-Ahead Log) módu.

### Důvody
- Nulová administrace, nevyžaduje daemon
- WAL mode umožňuje souběžné čtení z více vláken
- Dostatečný výkon pro <10k issues a <1M telemetry záznamů
- Snadné zálohy (jeden soubor)

### Kompromisy
- Není vhodné pro >100 souběžných zápisů
- Bez horizontálního škálování (jeden server)

---

## ADR-002: inotify místo pollingu pro log sledování

**Status:** Accepted  
**Datum:** 2026-06

### Rozhodnutí
Používáme Python `watchdog` (inotify) pro sledování log souborů.

### Důvody
- Okamžitá reakce na změny (< 1ms latence)
- Nulová CPU zátěž při nečinnosti
- Nativní kernel support na Linux

### Kompromisy
- Inotify limit (defaultně 8192 sledovaných souborů) — řešíme `/proc/sys/fs/inotify/max_user_watches`
- DB soubory musí být MIMO sledovaný adresář (LOG_DIR ≠ DB_DIR)

---

## ADR-003: Vlastní session auth místo Flask-Login

**Status:** Accepted  
**Datum:** 2026-06

### Rozhodnutí
Vlastní implementace session managementu v `auth.py`.

### Důvody
- Plná kontrola nad session lifetime a revokací
- Persistentní revokace v DB (přežije restart)
- Podpora 2FA (TOTP) bez závislosti na třetí straně
- Jednodušší pro LDAP integraci

### Kompromisy
- Více vlastního kódu k udržování
- Není kompatibilní s Flask-Login ekosystémem

---

## ADR-004: Hailo AI HAT 2+ (Hailo-10H) jako primární AI backend

**Status:** Accepted  
**Datum:** 2026-06

### Rozhodnutí
Primární AI inference přes `hailo-ollama` na NPU, fallback na CPU Ollama.

### Důvody
- 40 TOPS při 5W spotřebě (vs 15-40W pro CPU)
- Nativní podpora LLM modelů (Qwen, Llama) bez quantizace
- Lokální inference = nulové API náklady, offline provoz

### Kompromisy
- Vyžaduje Hailo Runtime a PCIe driver
- Kompatibilní pouze s RPi5
