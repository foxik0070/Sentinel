"""
081: SNMP Trap receiver — přijímá SNMPv1/v2c trapy a ukládá jako Sentinel issues.

Konfigurace v config.yaml:
    snmp_trap:
      enabled: true
      port: 1162          # UDP port (162 vyžaduje root; 1162+ bez rootu)
      host: "0.0.0.0"
      community: ""       # prázdný = přijmout vše
      channel: "infra"    # výchozí kanál
      oid_map:            # OID prefix → {channel, severity, message}
        "1.3.6.1.4.1.9": {channel: "infra", severity: "high", message: "Cisco trap"}
"""
import socket
import struct
import threading
import logging
from datetime import datetime, timezone

logger = logging.getLogger("sentinel.snmp_trap")


# ── Minimální BER/ASN.1 parser ────────────────────────────────────────────

def _ber_decode(data: bytes, offset: int = 0):
    """Decode one BER TLV element. Returns (tag, value_bytes, next_offset)."""
    if offset >= len(data):
        return None, b'', offset
    tag = data[offset]; offset += 1
    if offset >= len(data):
        return tag, b'', offset
    length = data[offset]; offset += 1
    if length & 0x80:
        n_bytes = length & 0x7F
        if offset + n_bytes > len(data):
            return tag, b'', offset
        length = int.from_bytes(data[offset:offset + n_bytes], 'big')
        offset += n_bytes
    end = offset + length
    value = data[offset:end]
    return tag, value, end


def _decode_oid(raw: bytes) -> str:
    """Decode BER OID bytes to dotted string."""
    if not raw:
        return ''
    first = raw[0]
    oid = [first // 40, first % 40]
    val = 0
    for b in raw[1:]:
        if b & 0x80:
            val = (val << 7) | (b & 0x7F)
        else:
            val = (val << 7) | b
            oid.append(val)
            val = 0
    return '.'.join(str(x) for x in oid)


def _extract_oid_and_info(pdu_bytes: bytes):
    """Extract enterprise OID and variable bindings from PDU bytes."""
    offset = 0
    enterprise_oid = ''
    varbinds = []
    try:
        # SNMPv1 Trap-PDU structure:
        #  enterprise OID, agent-addr, generic-trap, specific-trap, timestamp, varbinds
        # SNMPv2c Trap (v2Trap-PDU) structure:
        #  varbinds sequence directly
        tag, val, offset = _ber_decode(pdu_bytes, 0)
        if tag == 0x06:  # OID (SNMPv1 enterprise)
            enterprise_oid = _decode_oid(val)
            # Skip agent addr (4 bytes IP)
            _ber_decode(pdu_bytes, offset)  # agent-addr
            tag2, v2, offset = _ber_decode(pdu_bytes, offset)
            tag3, v3, offset = _ber_decode(pdu_bytes, offset)  # generic
            tag4, v4, offset = _ber_decode(pdu_bytes, offset)  # specific
            tag5, v5, offset = _ber_decode(pdu_bytes, offset)  # timestamp
        # Parse varbinds sequence
        tag6, vb_bytes, _ = _ber_decode(pdu_bytes, offset)
        if tag6 == 0x30:  # SEQUENCE
            vb_off = 0
            while vb_off < len(vb_bytes):
                # Each varbind is a SEQUENCE {OID, value}
                _, vb_inner, vb_off = _ber_decode(vb_bytes, vb_off)
                if not vb_inner:
                    break
                oid_tag, oid_raw, _ = _ber_decode(vb_inner, 0)
                if oid_tag == 0x06:
                    varbinds.append(_decode_oid(oid_raw))
                    if not enterprise_oid:
                        enterprise_oid = _decode_oid(oid_raw)
    except Exception as e:
        logger.debug(f"SNMP BER parse error: {e}")
    return enterprise_oid, varbinds


def _parse_trap(data: bytes, src_ip: str) -> dict:
    """Parse raw SNMP trap UDP packet. Returns dict or None."""
    try:
        # SNMP message: SEQUENCE { INTEGER(version), OCTET_STRING(community), PDU }
        tag, msg_bytes, _ = _ber_decode(data, 0)
        if tag != 0x30:
            return None
        offset = 0
        # version
        vtag, vval, offset = _ber_decode(msg_bytes, offset)
        version = int.from_bytes(vval, 'big') if vval else 0
        # community
        ctag, cval, offset = _ber_decode(msg_bytes, offset)
        community = cval.decode('ascii', errors='replace') if cval else ''
        # PDU type
        pdu_tag, pdu_bytes, _ = _ber_decode(msg_bytes, offset)
        # 0xA4 = Trap-PDU (v1), 0xA7 = snmpV2-Trap-PDU
        pdu_type = 'v1_trap' if pdu_tag == 0xA4 else 'v2_trap' if pdu_tag == 0xA7 else f'0x{pdu_tag:02x}'
        enterprise_oid, varbinds = _extract_oid_and_info(pdu_bytes)
        return {
            'version': version,
            'community': community,
            'pdu_type': pdu_type,
            'enterprise_oid': enterprise_oid,
            'varbinds': varbinds,
            'src_ip': src_ip,
            'ts': datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.debug(f"SNMP parse failed from {src_ip}: {e}")
        return None


# ── OID mapping helper ────────────────────────────────────────────────────

def _match_oid_map(oid: str, oid_map: dict) -> dict:
    """Match OID against config oid_map (prefix match). Returns mapping or {}."""
    best = ('', {})
    for prefix, info in (oid_map or {}).items():
        if oid.startswith(str(prefix)) and len(prefix) > len(best[0]):
            best = (prefix, info)
    return best[1]


# ── UDP server ────────────────────────────────────────────────────────────

def start(cfg: dict, report_fn):
    """
    Start SNMP trap UDP listener in a daemon thread.
    cfg: snmp_trap section from config.yaml
    report_fn: callable(key, data_dict) to create an issue
    """
    port = int(cfg.get('port', 1162))
    host = cfg.get('host', '0.0.0.0')
    community_filter = cfg.get('community', '')
    channel = cfg.get('channel', 'infra')
    oid_map = cfg.get('oid_map') or {}

    def _run():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            sock.settimeout(2.0)
            logger.info(f"SNMP trap receiver listening on {host}:{port}")
        except Exception as e:
            logger.error(f"SNMP trap bind failed on {host}:{port}: {e}")
            return

        while True:
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except Exception as e:
                logger.warning(f"SNMP recv error: {e}")
                continue

            src_ip = addr[0]
            trap = _parse_trap(data, src_ip)
            if not trap:
                continue

            if community_filter and trap['community'] != community_filter:
                logger.debug(f"SNMP trap ignored (community mismatch): {src_ip}")
                continue

            oid = trap['enterprise_oid']
            mapping = _match_oid_map(oid, oid_map)

            ch = mapping.get('channel', channel)
            sev = mapping.get('severity', 'medium')
            msg_tmpl = mapping.get('message', '')
            msg = msg_tmpl or f"SNMP trap from {src_ip}: OID={oid or '(unknown)'}"

            key = f"snmp_trap:{src_ip}:{oid or 'unknown'}"
            data_dict = {
                'plugin_name': 'SNMP_TRAP',
                'channel_type': ch,
                'host': src_ip,
                'last_line': msg,
                'severity': sev,
                'details': {
                    'snmp_version': trap['version'],
                    'community': trap['community'],
                    'pdu_type': trap['pdu_type'],
                    'enterprise_oid': oid,
                    'varbinds': trap['varbinds'][:10],
                    'src_ip': src_ip,
                }
            }
            try:
                report_fn(key, data_dict)
                logger.info(f"SNMP trap issue: {key}")
            except Exception as e:
                logger.error(f"SNMP report_problem failed: {e}")

    t = threading.Thread(target=_run, daemon=True, name='snmp-trap-receiver')
    t.start()
    return t
