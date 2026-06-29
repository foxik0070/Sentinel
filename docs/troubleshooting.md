# Sentinel Commander — Troubleshooting Guide

## Service nespustí

### ImportError / ModuleNotFoundError
```bash
python3 -m py_compile sentinel/chat_service.py
pip3 install -r requirements.txt --break-system-packages
```

### DB locked / sqlite3.OperationalError
```bash
fuser /var/lib/sentinel/sentinel_state.db
sqlite3 /var/lib/sentinel/sentinel_state.db "PRAGMA wal_checkpoint(TRUNCATE);"
rm -f /var/lib/sentinel/sentinel_state.db-wal /var/lib/sentinel/sentinel_state.db-shm
```

### Port 5050 obsazen
```bash
fuser -k 5050/tcp
```

---

## Watcher přestane fungovat / "tuhne"

### Příznaky
- Žádné nové issues ze sledovaných logů
- `sentinel.lines_parsed_per_min` klesne na 0 v telemetrii

### Řešení
```bash
# Zkontrolovat inotify limity
cat /proc/sys/fs/inotify/max_user_watches
echo 65536 | sudo tee /proc/sys/fs/inotify/max_user_watches

# Restart služby (SIGHUP reload config bez restartu)
sudo kill -HUP $(pidof -s sentinel)
# nebo
sudo systemctl restart sentinel
```

---

## AI timeout / "AI odpovídá s chybou"

### Ollama nedostupné
```bash
systemctl status ollama
ollama ps
curl http://localhost:11434/api/tags
```

### Fronta přetížena
```bash
# Zkontrolovat fronta depth v dashboard
curl -s http://localhost:5050/api/dashboard | python3 -c "import sys,json; d=json.load(sys.stdin); print('AI queue:', d['ai_queue'])"
```

### Hailo-ollama nedostupné (RPi5)
```bash
systemctl status hailo-ollama
hailortcli scan
# Restart
sudo systemctl restart hailo-ollama
```

---

## DB roste příliš rychle

```bash
# Zkontrolovat velikost
ls -lh /var/lib/sentinel/sentinel_state.db

# Ruční prune
curl -s -u admin:PASS -X POST http://localhost:5050/api/admin/prune

# Aggregate starou telemetrii
curl -s -u admin:PASS -X POST -H 'Content-Type: application/json' \
  -d '{"after_hours": 24}' http://localhost:5050/api/admin/aggregate_telemetry

# VACUUM
sqlite3 /var/lib/sentinel/sentinel_state.db "VACUUM;"
```

---

## LDAP přihlášení nefunguje

```bash
# Test LDAP spojení
ldapsearch -x -H ldap://HOST -D "cn=service,dc=example,dc=com" \
  -w PASS -b "dc=example,dc=com" "(uid=USERNAME)"

# SIGHUP pro reload LDAP konfigurace bez restartu
sudo kill -HUP $(pidof -s sentinel)
```

---

## Agenti se nepřipojují

```bash
# Ověřit token agenta
curl -s -X POST http://SENTINEL:5050/api/v1/ingest \
  -H "Authorization: Bearer AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"hostname":"test","alerts":[]}'

# Zkontrolovat SSH known_hosts
cat /var/lib/sentinel/known_hosts | grep HOSTNAME
```

---

## WebSocket se neustále odpojuje

### Příznaky: "Reconnecting..." v UI

```bash
# Zkontrolovat nginx/Traefik proxy — musí mít WebSocket support
# nginx: přidat do location bloku:
#   proxy_http_version 1.1;
#   proxy_set_header Upgrade $http_upgrade;
#   proxy_set_header Connection "upgrade";
#   proxy_read_timeout 3600;
```

---

## Logy (zkrácení)

```bash
# Sentinel log
journalctl -u sentinel -n 100 --no-pager
tail -f /var/log/sentinel/sentinel.log

# Zvýšit log level za běhu
curl -X POST -u admin:PASS -H 'Content-Type: application/json' \
  -d '{"level":"DEBUG"}' http://localhost:5050/api/admin/log_level
```
