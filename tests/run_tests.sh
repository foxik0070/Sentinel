#!/bin/bash
# Spustí všechny Sentinel testy z kořenového adresáře projektu
# Použití: bash tests/run_tests.sh [--verbose]

cd "$(dirname "$0")/.." || exit 1

VERBOSE=""
[ "$1" = "--verbose" ] || [ "$1" = "-v" ] && VERBOSE="-v"

echo "=== Sentinel Test Suite ==="
echo ""

# Safety tests (bez externích závislostí)
echo "[1/8] Safety (AI guardrails)..."
python -m unittest tests.test_safety $VERBOSE 2>&1

# Config tests
echo ""
echo "[2/8] Config..."
python -m unittest tests.test_config $VERBOSE 2>&1

# State/DB tests
echo ""
echo "[3/8] State / Database..."
python -m unittest tests.test_state $VERBOSE 2>&1

# Hailo integration tests
echo ""
echo "[4/8] Hailo AI HAT 2+ integration..."
python -m unittest tests.test_hailo $VERBOSE 2>&1

# v2026.06 features
echo ""
echo "[5/8] v2026.06 features (telemetrie, false-positive, deps, Socket.IO, cache)..."
python -m unittest tests.test_v006_features $VERBOSE 2>&1

# Security tests (341)
echo ""
echo "[6/8] Security (brute force, API scope, hostname injection)..."
python -m unittest tests.test_security $VERBOSE 2>&1

# Integration tests (342)
echo ""
echo "[7/8] Integration lifecycle (save_problem → active → resolved)..."
python -m unittest tests.test_integration $VERBOSE 2>&1

# Issue lifecycle — uzavírání issues, které už neplatí
echo ""
echo "[8/8] Issue lifecycle (strop stáří, rekonciliace, recheck pravidla)..."
python -m unittest tests.test_issue_lifecycle $VERBOSE 2>&1

echo ""
echo "=== Hotovo ==="
