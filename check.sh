#!/bin/bash

echo "--- KONTROLA ADRESARU ---"
for d in \
  /opt/Sentinel \
  /opt/Sentinel/sentinel \
  /opt/Sentinel/sentinel/plugins \
  /opt/Sentinel/sentinel/templates \
  /opt/Sentinel/sentinel/static \
  /var/log/sentinel/logs \
  /opt/Sentinel/data \
  /opt/Sentinel/learning_knowledge_base; \
do \
  if [ -d "$d" ]; then echo -e "[\033[32mOK\033[0m] Adresar: $d"; else echo -e "[\033[31mCHYBI\033[0m] Adresar: $d"; fi; \
done

echo ""
echo "--- KONTROLA SOUBORU ---"
for f in \
  /etc/sentinel/config.yaml \
  /opt/Sentinel/setup.py \
  /opt/Sentinel/sentinel/__init__.py \
  /opt/Sentinel/sentinel/__main__.py \
  /opt/Sentinel/sentinel/api.py \
  /opt/Sentinel/sentinel/config.py \
  /opt/Sentinel/sentinel/plugin_manager.py \
  /opt/Sentinel/sentinel/utils.py \
  /opt/Sentinel/sentinel/watcher.py \
  /opt/Sentinel/sentinel/ollama_service.py \
  /opt/Sentinel/sentinel/state.py \
  /opt/Sentinel/sentinel/actions.py \
  /opt/Sentinel/sentinel/analytics.py \
  /opt/Sentinel/sentinel/rag.py \
  /opt/Sentinel/sentinel/chat_service.py \
  /opt/Sentinel/sentinel/plugins/__init__.py \
  /opt/Sentinel/sentinel/plugins/base.py \
  /opt/Sentinel/sentinel/plugins/detector_universal_security.py \
  /opt/Sentinel/sentinel/plugins/system_detector.py \
  /opt/Sentinel/sentinel/plugins/security_detector.py \
  /opt/Sentinel/sentinel/plugins/services_detector.py \
  /opt/Sentinel/sentinel/plugins/storage_detector.py \
  /opt/Sentinel/sentinel/plugins/capacity_detector.py \
  /opt/Sentinel/sentinel/plugins/temperature_detector.py \
  /opt/Sentinel/sentinel/plugins/port_detector.py \
  /opt/Sentinel/sentinel/plugins/availability_detector.py \
  /opt/Sentinel/sentinel/plugins/audit_detector.py \
  /opt/Sentinel/sentinel/plugins/ha_detector.py \
  /opt/Sentinel/sentinel/templates/index.html \
  /opt/Sentinel/sentinel/templates/login.html \
  /opt/Sentinel/sentinel/static/script.js \
  /opt/Sentinel/sentinel/static/style.css \
  /opt/Sentinel/sentinel/static/i18n.js; \
do \
  if [ -f "$f" ]; then echo -e "[\033[32mOK\033[0m] Soubor: $f"; else echo -e "[\033[31mCHYBI\033[0m] Soubor: $f"; fi; \
done

echo ""
echo "--- KONTROLA PYTHON IMPORTU ---"
python3 -c "
import sys
modules = [
    'sentinel.config', 'sentinel.state', 'sentinel.utils',
    'sentinel.rag', 'sentinel.analytics', 'sentinel.watcher',
    'sentinel.actions', 'sentinel.safety', 'sentinel.chat_service',
]
ok = True
for m in modules:
    try:
        __import__(m)
        print(f'\033[32m[OK]\033[0m Import: {m}')
    except Exception as e:
        print(f'\033[31m[CHYBI]\033[0m Import: {m} — {e}')
        ok = False
" 2>/dev/null

echo ""
echo "--- KONTROLA SLUZBY ---"
if systemctl is-active --quiet sentinel 2>/dev/null; then
  echo -e "[\033[32mOK\033[0m] Sluzba sentinel bezi"
else
  echo -e "[\033[33mWARN\033[0m] Sluzba sentinel nebezi (nebo neni systemd)"
fi
