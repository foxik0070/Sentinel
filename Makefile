# Sentinel Commander — Build & Dev helpers
.PHONY: build test restart clean help hooks

JS_FILES := sentinel/static/script-core.js \
            sentinel/static/script-ui.js \
            sentinel/static/script-agents.js \
            sentinel/static/script-modals.js
CSS_FILES := sentinel/static/style.css

help:
	@echo "Sentinel Commander — make targets:"
	@echo "  make build    — minify JS + CSS"
	@echo "  make test     — run test suite"
	@echo "  make restart  — restart systemd service"
	@echo "  make all      — build + test"

build:
	@echo "[build] Minifying JS..."
	@for f in $(JS_FILES); do \
		out=$${f%.js}.min.js; \
		npx terser $$f -o $$out --compress --mangle && echo "  ✓ $$out"; \
	done
	@echo "[build] Minifying i18n..."
	@npx terser sentinel/static/i18n.js -o sentinel/static/i18n.min.js --compress --mangle && echo "  ✓ i18n.min.js"
	@echo "[build] Minifying CSS..."
	@npx uglifycss $(CSS_FILES) > sentinel/static/style.min2.css && echo "  ✓ style.min2.css"
	@echo "[build] Done."

test:
	@echo "[test] JS syntax check..."
	@for f in $(JS_FILES); do \
		node --check $$f && echo "  ✓ $$f" || exit 1; \
	done
	@echo "[test] JS ESLint (no-redeclare errors)..."
	@npx eslint $(JS_FILES) --max-warnings=999 --rule '{"no-redeclare": "error"}' --quiet || exit 1
	@echo "[test] Ruff lint..."
	@ruff check sentinel/ --quiet || true
	@echo "[test] Python tests..."
	@bash tests/run_tests.sh

lint:
	@ruff check sentinel/ --fix

restart:
	@sudo systemctl restart sentinel && systemctl is-active sentinel

hooks:
	@cp .gitea/hooks/pre-push .git/hooks/pre-push 2>/dev/null || true
	@chmod +x .git/hooks/pre-push
	@echo "✓ Git hooks installed"

all: build test
