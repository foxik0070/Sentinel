#!/bin/bash
# Spustí všechny Sentinel testy z kořenového adresáře projektu
# Použití: bash tests/run_tests.sh [--verbose]

cd "$(dirname "$0")/.." || exit 1

VERBOSE=""
[ "$1" = "--verbose" ] || [ "$1" = "-v" ] && VERBOSE="-v"

echo "=== Sentinel Test Suite ==="
echo ""

# Safety tests (bez externích závislostí)
echo "[1/7] Safety (AI guardrails)..."
python -m unittest tests.test_safety $VERBOSE 2>&1

# Config tests
echo ""
echo "[2/7] Config..."
python -m unittest tests.test_config $VERBOSE 2>&1

# State/DB tests
echo ""
echo "[3/7] State / Database..."
python -m unittest tests.test_state $VERBOSE 2>&1

# Hailo integration tests
echo ""
echo "[4/7] Hailo AI HAT 2+ integration..."
python -m unittest tests.test_hailo $VERBOSE 2>&1

# v2026.06 features
echo ""
echo "[5/7] v2026.06 features (telemetrie, false-positive, deps, Socket.IO, cache)..."
python -m unittest tests.test_v006_features $VERBOSE 2>&1

# Security tests (341)
echo ""
echo "[6/7] Security (brute force, API scope, hostname injection)..."
python -m unittest tests.test_security $VERBOSE 2>&1

# Integration tests (342)
echo ""
echo "[7/7] Integration lifecycle (save_problem → active → resolved)..."
python -m unittest tests.test_integration $VERBOSE 2>&1

echo ""
echo "=== Hotovo ==="
