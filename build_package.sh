#!/bin/bash

# Zastavení v případě chyby
set -e

echo "=> Přesun do adresáře projektu..."
cd /opt/Sentinel

echo "=> Kontrola inicializačního souboru modulu..."
if [ ! -f "sentinel/__init__.py" ]; then
    echo "Vytvářím chybějící sentinel/__init__.py..."
    touch sentinel/__init__.py
fi

echo "=> Generování MANIFEST.in..."
cat << 'EOF' > MANIFEST.in
include README.md
include check.sh
include sentinel_init.py
include ollama_local.sh

# graft vezme celou složku včetně všech podadresářů a souborů
graft docs
graft sentinel/templates
graft sentinel/static

# Pro jistotu zahrneme i py soubory, pokud by nebyly v balíčcích
recursive-include sentinel *.py

# Vyhodíme smetí, které v balíčku nechceš
global-exclude *.pyc
global-exclude __pycache__
global-exclude .DS_Store
EOF

echo "=> Kontrola/Instalace modulu 'build'..."
python3 -m pip install --upgrade build --break-system-packages || echo "Build je již připraven."

echo "=> Budování Python balíčku (sestavuji wheel a tar.gz)..."
python3 -m build --no-isolation

echo "=================================================="
echo "HOTOVO! Balíčky byly úspěšně vygenerovány:"
ls -lh dist/
echo ""
echo "Můžeš je nainstalovat pomocí:"
echo "sudo python3 -m pip install /opt/Sentinel/dist/sentinel-*.whl --break-system-packages --force-reinstall"
echo "=================================================="
