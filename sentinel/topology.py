"""
120: Síťová topologie — sestavuje a cachuje topologická data ze zdrojů:
  1. Agenti Sentinelu (skupiny = síťové segmenty)
  2. Manuální linky z config.yaml (topology.manual_links)
  3. SNMP CDP/LLDP sousedi (volitelné, pokud je snmpwalk dostupný)

Konfigurace v config.yaml:
    topology:
      manual_links:           # manuální hrany grafu
        - from: "node01"
          to:   "core-sw01"
          label: "GigE0/1"
      snmp_targets:           # SNMP CDP/LLDP polling
        - host: "192.168.1.1"
          community: "public"
          version: "2c"
      snmp_poll_interval: 300 # sekundy (default 5 min)
"""
import subprocess
import threading
import logging
import time
import json
from datetime import datetime, timezone

logger = logging.getLogger("sentinel.topology")

# In-memory topology cache
_topo_lock = threading.Lock()
_topo_cache = {
    "nodes": [],    # [{id, label, type, status, group, ip}]
    "edges": [],    # [{from, to, label, source}]
    "updated_at": None,
}

_SNMP_CDP_NEIGHBORS_OID = "1.3.6.1.4.1.9.9.23.1.2.1.1"   # Cisco CDP neighbors table
_SNMP_LLDP_NEIGHBORS_OID = "1.0.8802.1.1.2.1.4"            # LLDP neighbors table


def _snmpwalk(host: str, community: str, oid: str, version: str = "2c", timeout: int = 5) -> list:
    """Run snmpwalk via subprocess. Returns list of (oid, value) tuples."""
    try:
        result = subprocess.run(
            ["snmpwalk", f"-v{version}", "-c", community, "-t", str(timeout), host, oid],
            capture_output=True, text=True, timeout=timeout + 2
        )
        lines = []
        for line in result.stdout.splitlines():
            if " = " in line:
                oid_part, val_part = line.split(" = ", 1)
                lines.append((oid_part.strip(), val_part.strip()))
        return lines
    except FileNotFoundError:
        return []  # snmpwalk not installed
    except Exception as e:
        logger.debug(f"snmpwalk {host} {oid}: {e}")
        return []


def _poll_snmp_cdp(host: str, community: str, version: str = "2c") -> list:
    """Query a device for CDP neighbors. Returns list of {from, to, label} dicts."""
    edges = []
    # CDP device ID (neighbor hostname) — OID .6 = deviceId
    device_ids = _snmpwalk(host, community, f"{_SNMP_CDP_NEIGHBORS_OID}.6", version)
    for oid, val in device_ids:
        neighbor = val.replace("STRING:", "").replace('"', '').strip()
        if neighbor:
            # Extract interface from OID (last segment)
            iface = oid.rsplit(".", 2)[-2] if "." in oid else "?"
            edges.append({"from": host, "to": neighbor, "label": f"CDP/{iface}", "source": "snmp_cdp"})
    return edges


def _poll_snmp_lldp(host: str, community: str, version: str = "2c") -> list:
    """Query a device for LLDP neighbors. Returns list of {from, to, label} dicts."""
    edges = []
    port_names = _snmpwalk(host, community, f"{_SNMP_LLDP_NEIGHBORS_OID}.1.1.9", version)
    sys_names = _snmpwalk(host, community, f"{_SNMP_LLDP_NEIGHBORS_OID}.1.1.10", version)
    for (_, sys_name) in sys_names:
        neighbor = sys_name.replace("STRING:", "").replace('"', '').strip()
        if neighbor:
            edges.append({"from": host, "to": neighbor, "label": "LLDP", "source": "snmp_lldp"})
    return edges


def build_topology(agents: list, config_topo: dict) -> dict:
    """
    Build topology graph from agents + manual links + SNMP.
    Returns {nodes: [...], edges: [...]}.
    """
    nodes = {}
    edges = []

    # 1. Agenti jako nody
    for ag in agents:
        nid = ag.get("hostname", "?")
        ips = json.loads(ag.get("ip_addresses") or "[]") if isinstance(ag.get("ip_addresses"), str) else []
        nodes[nid] = {
            "id": nid,
            "label": nid,
            "type": "agent",
            "status": ag.get("status", "UNKNOWN"),
            "group": ag.get("agent_group") or "(bez skupiny)",
            "ip": ips[0] if ips else "",
            "health_score": ag.get("health_score"),
        }

    # 2. Group nodes (switch/router reprezentující skupinu)
    # Collect groups from agents first, then add group nodes
    agent_list = list(nodes.values())
    for n in agent_list:
        g = n["group"]
        grp_id = f"__grp_{g}"
        if grp_id not in nodes:
            nodes[grp_id] = {"id": grp_id, "label": g, "type": "group", "status": "group", "group": g, "ip": ""}
        edges.append({"from": n["id"], "to": grp_id, "label": "", "source": "group"})

    # 3. Manuální linky z configu
    for link in (config_topo.get("manual_links") or []):
        f, t = str(link.get("from", "")), str(link.get("to", ""))
        if not f or not t:
            continue
        # Přidej nody pokud neexistují
        for nid in (f, t):
            if nid not in nodes:
                nodes[nid] = {"id": nid, "label": nid, "type": "manual", "status": "unknown", "group": "", "ip": ""}
        edges.append({"from": f, "to": t, "label": link.get("label", ""), "source": "manual"})

    # 4. SNMP nody ze SNMP cache
    snmp_edges = _topo_cache.get("snmp_edges", [])
    for e in snmp_edges:
        f, t = e.get("from", ""), e.get("to", "")
        if not f or not t:
            continue
        for nid in (f, t):
            if nid not in nodes:
                nodes[nid] = {"id": nid, "label": nid, "type": "snmp", "status": "unknown", "group": "", "ip": ""}
        edges.append(e)

    return {"nodes": list(nodes.values()), "edges": edges, "updated_at": datetime.now(timezone.utc).isoformat()}


def start_snmp_poller(config_topo: dict):
    """Start background SNMP polling thread if targets are configured."""
    targets = config_topo.get("snmp_targets") or []
    if not targets:
        return
    interval = int(config_topo.get("snmp_poll_interval", 300))

    def _poll():
        while True:
            all_edges = []
            for target in targets:
                host = target.get("host", "")
                community = target.get("community", "public")
                version = target.get("version", "2c")
                if not host:
                    continue
                all_edges.extend(_poll_snmp_cdp(host, community, version))
                all_edges.extend(_poll_snmp_lldp(host, community, version))
            with _topo_lock:
                _topo_cache["snmp_edges"] = all_edges
                _topo_cache["snmp_updated"] = datetime.now(timezone.utc).isoformat()
            if all_edges:
                logger.info(f"SNMP topology: {len(all_edges)} edges from {len(targets)} targets")
            time.sleep(interval)

    t = threading.Thread(target=_poll, daemon=True, name="topology-snmp-poll")
    t.start()
