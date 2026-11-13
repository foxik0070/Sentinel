# Sentinel API — Průvodce pro uživatele

## Přístup k API

Sentinel API je dostupné na:

```
https://sentinel.example.com/api/...
```

> **Pozor:** Adresa Sentinelu nemusí být totožná s hostitelským strojem. Pokud na
> stroji běží reverzní proxy, která `/api/` na Sentinel nepřeposílá, volání skončí
> chybou — používejte vždy adresu, na které Sentinel skutečně poslouchá.

## Autentizace

### API klíč (doporučeno pro skripty)

API klíč se předává v hlavičce `X-API-Key`:

```bash
curl -sk https://sentinel.example.com/api/status_check \
  -H "X-API-Key: VÁŠ_API_KLÍČ"
```

### Vytvoření API klíče

1. Přihlaste se do Sentinel webového rozhraní
2. Klikněte na svůj uživatelský badge v horní liště (zobrazí roli)
3. V modalu najděte sekci **API klíče**
4. Klikněte **Nový klíč**, zvolte scope a název
5. Zkopírujte klíč — zobrazí se pouze jednou

**Scopes:**
- `read` — čtení dat (mapuje se na roli `viewer`)
- `read:issues` — pouze čtení issues
- `read:root` — čtení včetně kanálu ROOT, **bez** práva zápisu
- `write` — čtení i zápis (mapuje se na roli `admin`, jen pro superadmin)
- `admin` — plný přístup (mapuje se na roli `superadmin`, jen pro superadmin)

Admin může vytvořit klíč se scope `read`, `read:issues` nebo `read:root`.
Superadmin může vytvořit klíč s libovolným scope.

### Kanál ROOT a scope

Role se odvozuje **ze scope klíče**, ne od uživatele, který ho vytvořil
(`auth.py`, `_SCOPE_TO_ROLE`). Scope `read` a `read:issues` dávají roli `viewer`,
`write` a `write:actions` roli `admin`, `admin` a `admin:users` roli `superadmin`.

Důsledek, na který se snadno narazí: **s klíčem `read` nebo `read:issues`
issues z kanálu ROOT v odpovědi prostě nejsou** — bez chyby, bez varování,
jen tiše chybí. Kdo to neví, považuje za klid něco, z čeho nevidí část.

Pro nástroj, který jen čte a ROOT potřebuje, je správná volba **`read:root`**
(od v2026.11.005): vidí ROOT, ale zapisovat neumí. Vydat ho smí i admin.

| scope | role | vidí ROOT | umí zapisovat | kdo smí vydat |
|---|---|---|---|---|
| `read`, `read:issues` | viewer | ne | ne | admin, superadmin |
| `read:root` | viewer | **ano** | ne | admin, superadmin |
| `write`, `write:actions` | admin | ano | ano | superadmin |
| `admin`, `admin:users` | superadmin | ano | ano | superadmin |

> Před v2026.11.005 šlo ROOT vidět jen přes `write`/`admin`, tedy za cenu
> klíče s právem zápisu. Pokud takový klíč používáte jen ke čtení, vyměňte
> ho za `read:root`.

## Příklady použití

### Stav systému

```bash
curl -sk https://sentinel.example.com/api/status_check \
  -H "X-API-Key: $KEY"
```

Odpověď:
```json
{
  "issues": 35,
  "agent_issues": 24,
  "security_issues": 15,
  "rt_issues": 81,
  "rt_enabled": true,
  "rag_ready": true,
  "teams_enabled": true
}
```

### Seznam issues (HTML)

```bash
# Kanály: infra, agent, security, root, rt, clusters, temperature, ecc, login
curl -sk https://sentinel.example.com/api/modal_issues/agent \
  -H "X-API-Key: $KEY"
```

### Závislosti infrastruktury

```bash
curl -sk "https://sentinel.example.com/api/analytics/dependencies?hosts=node1.cluster" \
  -H "X-API-Key: $KEY"
```

### Blast radius

```bash
curl -sk https://sentinel.example.com/api/hosts/node1.cluster/blast_radius \
  -H "X-API-Key: $KEY"
```

### Health forecast (týdenní přehled)

```bash
curl -sk https://sentinel.example.com/api/analytics/health_forecast \
  -H "X-API-Key: $KEY"
```

### Playbooks (doporučení)

```bash
curl -sk https://sentinel.example.com/api/analytics/playbooks \
  -H "X-API-Key: $KEY"
```

### Remediation plan (žebřík zásahů)

```bash
# key_b64 = base64url(issue_key)
KEY_B64=$(echo -n "AGENT|node1.cluster|agent_systemd_global_monitor" | base64)
curl -sk -X POST "https://sentinel.example.com/api/issues/${KEY_B64}/remediation_plan" \
  -H "X-API-Key: $KEY" \
  -H "Content-Type: application/json"
```

Odpověď:
```json
{
  "ladder": [
    {"level": 1, "command": "systemctl status ...", "desc": "Zjistit stav", "readonly": true},
    {"level": 2, "command": "journalctl -u ...", "desc": "Prozkoumat logy", "readonly": true},
    {"level": 3, "command": "systemctl restart ...", "desc": "Restart služby", "readonly": false}
  ],
  "next_step": {"level": 1, "command": "systemctl status ...", "desc": "Zjistit stav"},
  "attempts": []
}
```

### Issue markdown export

```bash
KEY_B64=$(echo -n "ISSUE_KEY" | base64)
curl -sk "https://sentinel.example.com/api/issues/${KEY_B64}/markdown" \
  -H "X-API-Key: $KEY"
```

### Postmortem report

```bash
KEY_B64=$(echo -n "ISSUE_KEY" | base64)
curl -sk "https://sentinel.example.com/api/issues/${KEY_B64}/postmortem" \
  -H "X-API-Key: $KEY"
```

### Prohlížení logů

```bash
curl -sk "https://sentinel.example.com/api/logs/view?filename=cluster.log" \
  -H "X-API-Key: $KEY"
```

### RT tikety

```bash
# Všechny tikety
curl -sk https://sentinel.example.com/api/rt/tickets \
  -H "X-API-Key: $KEY"

# Filtrace podle fronty
curl -sk "https://sentinel.example.com/api/rt/tickets?queue=Support" \
  -H "X-API-Key: $KEY"

# Hledání v předmětu
curl -sk "https://sentinel.example.com/api/rt/tickets?q=cluster" \
  -H "X-API-Key: $KEY"
```

### KB soubory (dokumentace)

```bash
curl -sk https://sentinel.example.com/api/kb/files \
  -H "X-API-Key: $KEY"
```

## Poznámky

- API klíč v query stringu (`?api_key=...`) je povolen **pouze** pro SSE endpoint
  `/api/logs/tail` (prohlížečový EventSource nemůže posílat custom headers).
  Pro všechny ostatní endpointy používejte hlavičku `X-API-Key`.
- RT tikety se aktualizují každých **5 minut** (systemd timer `get-rt`).
  Po změně stavu tiketu přes Sentinel může trvat až 5 minut, než se změna projeví v UI.
- Komentáře přidané přes Sentinel obsahují prefix `[Sentinel – username]`
  pro identifikaci autora.
