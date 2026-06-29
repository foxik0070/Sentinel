// ─── Sentinel Satellites ─────────────────────────────────────────────────────

let _netRegTab = 'agents';

function openNetRegisterModal() {
    const panels = ['agents','alert','hw'];
    _netRegTab = panels.find(p => {
        const el = document.getElementById('sat-panel-' + p);
        return el && el.style.display !== 'none';
    }) || 'agents';

    const titles = { agents: 'Registrovat agenta', alert: 'Registrovat Alert Node', hw: 'Registrovat HW zařízení' };
    const icons  = { agents: 'fa-server', alert: 'fa-tower-broadcast', hw: 'fa-microchip' };
    const hints  = { agents: 'server-01', alert: 'sentinel-alert-lab', hw: 'bedroom-sentinel' };
    document.getElementById('net-reg-title').innerHTML =
        `<i class="fa-solid ${icons[_netRegTab]}" style="color:var(--accent);"></i> ${titles[_netRegTab]}`;
    document.getElementById('net-reg-hostname').placeholder = hints[_netRegTab];
    document.getElementById('net-reg-hostname').value = '';
    document.getElementById('net-reg-url').value = '';
    document.getElementById('net-reg-url-wrap').style.display = _netRegTab !== 'agents' ? 'block' : 'none';
    document.getElementById('net-reg-token-display').style.display = 'none';
    document.getElementById('net-reg-test-result').style.display = 'none';
    document.getElementById('net-reg-submit').style.display = '';
    document.getElementById('net-register-modal').style.display = 'flex';
}

function closeNetRegisterModal() {
    document.getElementById('net-register-modal').style.display = 'none';
}

async function testNetConnection() {
    const url = document.getElementById('net-reg-url').value.trim();
    const res_el = document.getElementById('net-reg-test-result');
    if (!url) { res_el.style.display='block'; res_el.innerHTML='<span style="color:#f87171;">Zadejte URL.</span>'; return; }
    res_el.style.display='block';
    res_el.innerHTML='<i class="fa-solid fa-spinner fa-spin"></i> Testování...';
    try {
        const r = await fetch('/api/system/test-url', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({url}), signal: AbortSignal.timeout(8000)
        });
        const d = await r.json();
        if (d.ok) {
            res_el.innerHTML=`<span style="color:var(--success);"><i class="fa-solid fa-check"></i> Dostupné (${d.ms} ms)</span>`;
        } else {
            res_el.innerHTML=`<span style="color:#f87171;"><i class="fa-solid fa-xmark"></i> Nedostupné: ${d.error||d.status||''}</span>`;
        }
    } catch(e) {
        res_el.innerHTML=`<span style="color:#f87171;"><i class="fa-solid fa-xmark"></i> ${e.message}</span>`;
    }
}

async function submitNetRegister() {
    const hostname = document.getElementById('net-reg-hostname').value.trim();
    const webUrl   = document.getElementById('net-reg-url').value.trim();
    if (!hostname) { alert(t('enter_valid_hostname')); return; }
    const btn = document.getElementById('net-reg-submit');
    btn.disabled = true;
    try {
        let res, data;
        if (_netRegTab === 'hw') {
            res  = await fetch('/api/sentinel-hw/register', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({hostname, web_ui_url: webUrl})});
            data = await res.json();
        } else {
            const category = _netRegTab === 'alert' ? 'alert' : undefined;
            const body = {hostname};
            if (webUrl) body.web_ui_url = webUrl;
            if (category) body.category = category;
            res  = await fetch('/api/agents/register', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
            data = await res.json();
        }
        if (data.status === 'ok') {
            const tok = document.getElementById('net-reg-token-display');
            tok.style.display = 'block';
            tok.innerHTML = `<b style="color:var(--success);">Token pro ${data.hostname}:</b><br><code id="net-reg-token-value" style="word-break:break-all;background:var(--input-bg,#222);padding:2px 6px;border-radius:3px;">${data.token}</code> <button onclick="safeCopyText(document.getElementById('net-reg-token-value').textContent);this.innerHTML='<i class=&quot;fa-solid fa-check&quot;></i>';" title="Kopírovat token" style="margin-left:6px;padding:3px 9px;background:var(--accent,#0078d4);color:#fff;border:none;border-radius:4px;cursor:pointer;"><i class="fa-solid fa-copy"></i></button><br><small style="color:#888;">Uložte si token — nebude znovu zobrazen.</small>`;
            document.getElementById('net-reg-submit').style.display = 'none';
            if (_netRegTab === 'agents') loadAgentsList(false);
            else if (_netRegTab === 'alert') loadSentinelAlertAgents();
            else loadSentinelHWDevices();
            updateSentinelAlertBadge();
        } else {
            alert((data.message || data.error || t('api_comm_error')));
        }
    } catch(e) {
        alert(t('api_error') + ' ' + e.message);
    } finally {
        btn.disabled = false;
    }
}

function switchSatTab(tab, loadData = true) {
    const panels = ['agents', 'alert', 'hw'];
    panels.forEach(p => {
        const el = document.getElementById('sat-panel-' + p);
        if (el) el.style.display = p === tab ? 'block' : 'none';
        const btn = document.getElementById('sat-tab-' + p);
        if (btn) {
            if (p === tab) {
                btn.style.borderBottom = '2px solid var(--accent)';
                btn.style.color = 'var(--accent)';
                btn.style.fontWeight = '600';
            } else {
                btn.style.borderBottom = '2px solid transparent';
                btn.style.color = 'var(--text-muted)';
                btn.style.fontWeight = '';
            }
        }
    });
    if (!loadData) return;
    if (tab === 'hw') loadSentinelHWDevices();
    if (tab === 'alert') loadSentinelAlertAgents();
    if (tab === 'agents') loadAgentsList(false);
}

async function loadSentinelHWDevices() {
    const tbody = document.getElementById('hw-devices-tbody');
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="5" style="padding:20px; text-align:center; color:#666;"><i class="fa-solid fa-spinner fa-spin"></i> ${t('loading')}</td></tr>`;
    try {
        const res = await fetch('/api/sentinel-hw/list');
        const data = await res.json();
        if (!data.devices || data.devices.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" style="padding:20px; text-align:center; color:#888;">${t('no_hw_registered')}</td></tr>`;
            return;
        }
        tbody.innerHTML = data.devices.map(dev => {
            const statusColor = dev.online ? 'var(--success)' : 'var(--error)';
            const statusTxt   = dev.online ? '🟢 Online' : '🔴 Offline';
            const lastSeen    = dev.last_seen ? new Date(dev.last_seen).toLocaleString('cs-CZ') : '—';
            const ignored     = !!dev.ignore_offline;
            const bellIcon    = ignored
                ? `<i class="fa-solid fa-bell-slash" style="color:var(--text-muted);" title="Offline ignorováno (kliknout pro zapnutí hlášení)"></i>`
                : `<i class="fa-solid fa-bell" style="color:var(--success);" title="Ignorovat offline stav"></i>`;
            return `
                <tr style="border-bottom:1px solid var(--border); cursor:pointer; ${ignored ? 'opacity:0.65;' : ''}"
                    onclick="openDeviceDetailModal('${dev.hostname}', 'hw', '${dev.web_ui_url}')">
                    <td style="padding:10px; font-weight:bold;"><i class="fa-solid fa-microchip" style="color:var(--accent); margin-right:6px;"></i>${dev.hostname}</td>
                    <td style="padding:10px;"><span style="color:${statusColor}; font-weight:bold;">${statusTxt}</span>${ignored && !dev.online ? ' <span style="font-size:0.75em;color:var(--text-muted);">(ignorováno)</span>' : ''}</td>
                    <td style="padding:10px; font-family:monospace; color:#aaa; font-size:.85em;">${lastSeen}</td>
                    <td style="padding:10px; text-align:center; color:${dev.active_issues > 0 ? 'var(--error)' : 'var(--success)'}; font-weight:bold;">${dev.active_issues}</td>
                    <td style="padding:10px; text-align:center; display:flex; gap:6px; justify-content:center;" onclick="event.stopPropagation()">
                        <span style="cursor:pointer;" onclick="toggleAgentIgnoreOffline('${dev.hostname}', ${ignored}).then(loadSentinelHWDevices)">${bellIcon}</span>
                        ${dev.has_token ? `<button onclick="revokeHWToken('${dev.hostname}')" style="padding:4px 8px; font-size:.75em; background:transparent; border:1px solid #666; cursor:pointer;" title="Zneplatnit token"><i class="fa-solid fa-ban"></i></button>` : ''}
                        <button onclick="deleteHWDevice('${dev.hostname}')" style="padding:4px 8px; font-size:.75em; background:transparent; border:1px solid var(--error); color:var(--error); cursor:pointer;" title="${t('delete_btn')}"><i class="fa-solid fa-trash"></i></button>
                    </td>
                </tr>`;
        }).join('');
    } catch(e) {
        tbody.innerHTML = `<tr><td colspan="5" style="padding:20px; color:var(--error); text-align:center;">${t('load_error_detail', {msg: e.message})}</td></tr>`;
    }
}

async function registerNewSentinelHW() {
    const hostname = document.getElementById('hw-new-hostname')?.value.trim();
    const webUrl   = document.getElementById('hw-new-url')?.value.trim();
    if (!hostname) { alert(t('enter_valid_hostname')); return; }
    try {
        const res = await fetch('/api/sentinel-hw/register', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({hostname, web_ui_url: webUrl}),
        });
        const data = await res.json();
        if (data.status === 'ok') {
            document.getElementById('hw-new-hostname').value = '';
            document.getElementById('hw-new-url').value = '';
            showTokenModal(data.hostname, data.token);
            loadSentinelHWDevices();
            updateSentinelAlertBadge();
        } else {
            alert(t('api_comm_error') + ' ' + (data.message || ''));
        }
    } catch(e) { alert(t('api_error') + ' ' + e.message); }
}

async function revokeHWToken(hostname) {
    if (!confirm(`Vygenerovat nový token pro '${hostname}'?`)) return;
    const res = await fetch(`/api/sentinel-hw/${hostname}/revoke-token`, {method:'POST', headers:{'Content-Type':'application/json'}});
    const d = await res.json();
    if (d.status === 'ok') {
        loadSentinelHWDevices();
        showTokenModal(hostname, d.token);
    } else {
        alert(t('api_comm_error') + ' ' + d.message);
    }
}

async function deleteHWDevice(hostname) {
    if (!confirm(t('confirm_delete_hw', {hostname}))) return;
    const res = await fetch(`/api/sentinel-hw/${hostname}/delete`, {method:'POST', headers:{'Content-Type':'application/json'}});
    const d = await res.json();
    if (d.status === 'ok') loadSentinelHWDevices();
    else alert(t('api_comm_error') + ' ' + d.message);
}

// ─── Device detail modal ─────────────────────────────────────────────────────

// ---- Agent Detail Modal ----

async function openAgentDetailModal(hostname) {
    const modal = document.getElementById('agent-detail-modal');
    const body = document.getElementById('agent-detail-body');
    document.getElementById('agent-detail-hostname').textContent = hostname;
    // SSH tlačítko (jen admin+)
    const existingBtn = modal.querySelector('.ssh-agent-btn');
    if (existingBtn) existingBtn.remove();
    if (window.currentRole === 'admin' || window.currentRole === 'superadmin') {
        const hdr = modal.querySelector('.modal-header');
        if (hdr) {
            // SSH button
            const btn = document.createElement('button');
            btn.className = 'ssh-agent-btn';
            btn.innerHTML = '<i class="fa-solid fa-terminal"></i> SSH';
            btn.style.cssText = 'padding:4px 10px;font-size:.8em;background:transparent;border:1px solid var(--border);border-radius:4px;cursor:pointer;color:var(--accent);margin-right:4px;';
            btn.onclick = () => { closeAgentDetailModal(); openSshModal(hostname); };
            hdr.insertBefore(btn, hdr.lastElementChild);
            // 143: Ping button
            const pingBtn = document.createElement('button');
            pingBtn.className = 'ping-agent-btn';
            pingBtn.id = `ping-btn-${hostname}`;
            pingBtn.innerHTML = '<i class="fa-solid fa-satellite-dish"></i> Ping';
            pingBtn.title = 'Otestovat dostupnost (TCP + ICMP)';
            pingBtn.style.cssText = 'padding:4px 10px;font-size:.8em;background:transparent;border:1px solid var(--border);border-radius:4px;cursor:pointer;color:var(--text-muted);margin-right:8px;';
            pingBtn.onclick = () => _agentPing(hostname);
            hdr.insertBefore(pingBtn, hdr.lastElementChild);
        }
    }
    modal.style.display = 'flex';
    body.innerHTML = `<div style="text-align:center;padding:30px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i></div>`;

    const [issR, healthR, histR] = await Promise.all([
        fetch(`/api/agents/${encodeURIComponent(hostname)}/issues`).then(r=>r.json()).catch(()=>({issues:[]})),
        fetch('/api/agents/health').then(r=>r.json()).catch(()=>({agents:[]})),
        fetch(`/api/agents/${encodeURIComponent(hostname)}/health_history?days=30`).then(r=>r.json()).catch(()=>({history:[]}))
    ]);

    const agent = (healthR.agents||[]).find(a=>a.hostname===hostname) || {};
    const issues = issR.issues || [];

    const statusColor = agent.status==='ONLINE' ? 'var(--success)' : 'var(--error)';
    const score = agent.health_score ?? '?';
    const scoreColor = score >= 80 ? 'var(--success)' : score >= 60 ? 'var(--warning)' : score >= 40 ? '#fd7e14' : 'var(--error)';
    const scoreGrade = score >= 80 ? 'A' : score >= 60 ? 'B' : score >= 40 ? 'C' : 'D';
    const lagStr = agent.last_data_lag_ms != null
        ? (agent.last_data_lag_ms < 60000 ? `${Math.round(agent.last_data_lag_ms/1000)}s`
           : agent.last_data_lag_ms < 3600000 ? `${Math.round(agent.last_data_lag_ms/60000)}m`
           : `${Math.round(agent.last_data_lag_ms/3600000)}h`)
        : 'N/A';
    const lagColor = agent.last_data_lag_ms > 300000 ? 'var(--warning)' : lagStr==='N/A' ? 'var(--text-muted)' : 'var(--success)';

    const sevColors = {critical:'#ff4500', high:'#fd7e14', medium:'#ffc107', low:'#6c757d'};

    const issuesHtml = issues.length ? issues.map(iss => {
        const sev = iss.severity || '';
        const sc = sevColors[sev] || 'var(--accent)';
        const occ = iss.occurrence_count > 1 ? ` <span style="background:#555;color:#fff;border-radius:10px;font-size:.7em;padding:1px 5px;">×${iss.occurrence_count}</span>` : '';
        return `<div style="padding:7px 10px;margin-bottom:4px;background:var(--bg);border:1px solid var(--border);border-left:3px solid ${sc};border-radius:4px;font-size:.83em;">
            <div style="color:var(--text-muted);font-size:.8em;">${iss.plugin_name?.toUpperCase()||'?'} · ${iss.last_seen?.slice(0,16)||''} ${occ}</div>
            <div>${_escape(iss.last_line||'')}</div>
        </div>`;
    }).join('') : `<div style="color:var(--success);text-align:center;padding:12px;"><i class="fa-solid fa-check-circle"></i> Žádné aktivní issues</div>`;

    // Telemetry, SSH history, thresholds
    const telemR = await fetch(`/api/agents/${encodeURIComponent(hostname)}/telemetry?days=1`).then(r=>r.json()).catch(()=>({telemetry:[]}));
    const telemData = telemR.telemetry || [];

    // Group telemetry by metric, take last 24 points each
    const metricGroups = {};
    telemData.forEach(t => {
        const k = t.metric;
        if (!metricGroups[k]) metricGroups[k] = [];
        metricGroups[k].unshift(t); // reverse (was DESC)
    });
    const topMetrics = Object.entries(metricGroups).slice(0, 4);

    const chartDivs = topMetrics.map(([metric, pts], idx) => {
        const vals = pts.map(p=>p.value);
        const labels = pts.map(p=>(p.ts||'').slice(11,16));
        const cid = `agchart_${idx}`;
        const vMin = vals.length ? Math.min(...vals) : 0;
        const vMax = vals.length ? Math.max(...vals) : 0;
        const vAvg = vals.length ? (vals.reduce((a,b)=>a+b,0)/vals.length).toFixed(1) : 0;
        const unit = metric.includes('pct')||metric.includes('cpu')||metric.includes('ram') ? '%' : metric.includes('temp') ? '°' : '';
        return `<div style="background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:8px;">
            <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px;">
                <div style="font-size:.72em;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:60%;" title="${_escape(metric)}">${_escape(metric.split('.').pop())}</div>
                <div style="font-size:.68em;color:var(--text-muted);display:flex;gap:6px;flex-shrink:0;">
                    <span title="Min" style="color:#4ade80;">▼${vMin.toFixed(1)}${unit}</span>
                    <span title="Avg" style="color:var(--accent);">⊘${vAvg}${unit}</span>
                    <span title="Max" style="color:#f87171;">▲${vMax.toFixed(1)}${unit}</span>
                </div>
            </div>
            <canvas id="${cid}" height="55"></canvas>
            <script>
            (function(){const ctx=document.getElementById('${cid}');if(!ctx||!window.Chart)return;
            const vals=${JSON.stringify(vals)};
            const avg=${vAvg};
            new Chart(ctx,{type:'line',data:{labels:${JSON.stringify(labels)},datasets:[
                {data:vals,borderColor:'var(--accent)',borderWidth:1.5,pointRadius:0,fill:true,backgroundColor:'rgba(0,120,212,0.07)',tension:0.3},
                {data:vals.map(()=>avg),borderColor:'rgba(255,255,255,0.2)',borderWidth:1,borderDash:[3,3],pointRadius:0,fill:false,label:'avg'}
            ]},options:{animation:false,interaction:{mode:'index',intersect:false},plugins:{legend:{display:false},tooltip:{backgroundColor:'rgba(20,20,30,.9)',callbacks:{label:ctx=>' '+ctx.raw.toFixed(2)+'${unit}'}}},scales:{x:{display:false},y:{display:true,ticks:{font:{size:8},maxTicksLimit:4,color:'rgba(255,255,255,.4)'},grid:{color:'rgba(255,255,255,.04)'}}}}});})();
            <\/script>
        </div>`;
    }).join('');

    body.innerHTML = `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div style="background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:14px;">
                <div style="font-size:.78em;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);margin-bottom:10px;">Info</div>
                <table style="width:100%;font-size:.85em;border-collapse:collapse;">
                    <tr><td style="color:var(--text-muted);padding:3px 0;">Stav</td><td style="font-weight:700;color:${statusColor};">${agent.status||'?'}</td></tr>
                    <tr><td style="color:var(--text-muted);padding:3px 0;">Health</td><td><span style="color:${scoreColor};font-weight:700;">${scoreGrade} (${score}/100)</span></td></tr>
                    <tr><td style="color:var(--text-muted);padding:3px 0;">Skupina</td><td>${_escape(agent.agent_group||'—')}</td></tr>
                    <tr><td style="color:var(--text-muted);padding:3px 0;">Verze</td><td style="font-family:monospace;color:var(--accent);">${_escape(agent.agent_version||'—')}</td></tr>
                    <tr><td style="color:var(--text-muted);padding:3px 0;">Data lag</td><td style="color:${lagColor};">${lagStr}</td></tr>
                    <tr><td style="color:var(--text-muted);padding:3px 0;">Registrován</td><td>${agent.registered_at?.slice(0,10)||'—'}</td></tr>
                    <tr><td style="color:var(--text-muted);padding:3px 0;">Poslední ping</td><td>${agent.last_seen?.slice(0,16).replace('T',' ')||'—'}</td></tr>
                    ${agent.notes ? `<tr><td style="color:var(--text-muted);padding:3px 0;">Poznámka</td><td>${_escape(agent.notes)}</td></tr>` : ''}
                </table>
            </div>
            <div style="background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:14px;">
                <div style="font-size:.78em;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);margin-bottom:10px;">Statistiky alertů (30 dní)</div>
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;text-align:center;margin-bottom:10px;">
                    <div><div style="font-size:1.6em;font-weight:700;color:${agent.alerts_24h>0?'var(--error)':'var(--text-main)'};">${agent.alerts_24h||0}</div><div style="font-size:.72em;color:var(--text-muted);">24h</div></div>
                    <div><div style="font-size:1.6em;font-weight:700;">${agent.alerts_7d||0}</div><div style="font-size:.72em;color:var(--text-muted);">7 dní</div></div>
                    <div><div style="font-size:1.6em;font-weight:700;">${agent.alerts_total||0}</div><div style="font-size:.72em;color:var(--text-muted);">Celkem</div></div>
                </div>
                ${_agentHealthSparkline(histR.history||[])}
            </div>
        </div>
        ${topMetrics.length ? `<div style="background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:14px;">
            <div style="font-size:.78em;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);margin-bottom:10px;">Telemetrie (24h)</div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;">${chartDivs}</div>
        </div>` : ''}
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:14px;">
            <div style="font-size:.78em;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);margin-bottom:10px;">Aktivní issues (${issues.length})</div>
            <div style="max-height:200px;overflow-y:auto;">${issuesHtml}</div>
        </div>`;
    // Execute chart scripts
    body.querySelectorAll('script').forEach(s => { try { eval(s.textContent); } catch {} });
    // Load SSH history, thresholds and labels lazily
    if (window.currentRole === 'admin' || window.currentRole === 'superadmin') {
        _loadAgentSshHistory(hostname, body);
        _loadAgentThresholds(hostname, body);
        _loadAgentLabels(hostname, body);
        _appendPackagesSection(hostname, body);
        _appendCveScanSection(hostname, body);
        _appendHwMetricsSection(hostname, body);
        _appendScheduledActionsSection(hostname, body);
        _appendSshKeysSection(hostname, body);
    }
}

// 328: SSH known_hosts management v agent detailu
async function _appendSshKeysSection(hostname, container) {
    try {
        const r = await fetch(`/api/agents/${encodeURIComponent(hostname)}/ssh_keys`);
        const d = await r.json();
        const keys = d.keys || [];
        const sec = document.createElement('div');
        sec.style.cssText = 'background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:14px;margin-top:12px;';
        sec.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
            <div style="font-size:.78em;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);"><i class="fa-solid fa-key"></i> SSH Known Hosts (${keys.length})</div>
            <div style="display:flex;gap:6px;">
                <button onclick="_agentSshRescan('${_escape(hostname)}', this.closest('div').parentElement.parentElement)" style="padding:3px 9px;background:transparent;border:1px solid var(--accent);color:var(--accent);border-radius:3px;cursor:pointer;font-size:.78em;"><i class="fa-solid fa-rotate"></i> Rescan</button>
                <button onclick="_agentSshDeleteKeys('${_escape(hostname)}', this.closest('div').parentElement.parentElement)" style="padding:3px 9px;background:transparent;border:1px solid var(--error);color:var(--error);border-radius:3px;cursor:pointer;font-size:.78em;"><i class="fa-solid fa-trash"></i></button>
            </div>
        </div>
        ${keys.length ? `<div style="font-family:monospace;font-size:.72em;color:var(--text-muted);max-height:100px;overflow-y:auto;">${keys.map(k=>`<div style="white-space:pre-wrap;word-break:break-all;padding:2px 0;">${_escape(k.slice(0,120))}${k.length>120?'…':''}</div>`).join('')}</div>`
        : '<span style="color:var(--text-muted);font-size:.82em;">Žádné záznamy. Spusť rescan.</span>'}`;
        container.appendChild(sec);
    } catch {}
}

async function _agentSshRescan(hostname, sec) {
    try {
        const r = await fetch(`/api/agents/${encodeURIComponent(hostname)}/ssh_keys/rescan`, {method:'POST', headers:{'Content-Type':'application/json'}});
        const d = await r.json();
        _showToast(d.status === 'ok' ? `✓ ${hostname} SSH klíče aktualizovány` : `Rescan selhal`, d.status === 'ok' ? 'success' : 'error');
        sec?.remove();
    } catch(e) { _showToast(`Chyba: ${e.message}`, 'error'); }
}

async function _agentSshDeleteKeys(hostname, sec) {
    if (!confirm(`Smazat SSH known_hosts záznamy pro ${hostname}?`)) return;
    try {
        await fetch(`/api/agents/${encodeURIComponent(hostname)}/ssh_keys`, {method:'DELETE', headers:{'Content-Type':'application/json'}});
        _showToast(`SSH klíče ${hostname} smazány`, 'info');
        sec?.remove();
    } catch(e) { _showToast(`Chyba: ${e.message}`, 'error'); }
}

// 269: Záložka "Plánované akce" — pending akce z actions tabulky pro tohoto agenta
async function _appendScheduledActionsSection(hostname, container) {
    try {
        const r = await fetch(`/api/agents/${encodeURIComponent(hostname)}/scheduled_actions`);
        const d = await r.json();
        const actions = d.actions || [];
        const sec = document.createElement('div');
        sec.style.cssText = 'background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:14px;margin-top:12px;';
        const scolor = {pending:'#fbbf24',reviewing:'#60a5fa',dry_run_completed:'#4ade80'};
        const rows = actions.length ? actions.map(a => `
            <tr style="border-bottom:1px solid var(--border);font-size:.82em;">
                <td style="padding:5px 6px;color:var(--text-muted);">${(a.created_at||'').slice(0,16).replace('T',' ')}</td>
                <td style="padding:5px 6px;font-family:monospace;color:var(--accent);">${_escape(a.command||'')}</td>
                <td style="padding:5px 6px;"><span style="color:${scolor[a.status]||'#aaa'};font-weight:600;">${a.status||''}</span></td>
                <td style="padding:5px 6px;color:var(--text-muted);">${a.mode||''} (risk:${a.risk_score||0})</td>
            </tr>`).join('') : `<tr><td colspan="4" style="text-align:center;padding:10px;color:var(--text-muted);">Žádné plánované akce</td></tr>`;
        sec.innerHTML = `<div style="font-size:.78em;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);margin-bottom:8px;">Plánované akce (${actions.length})</div>
            <div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;min-width:0;">
                <thead><tr style="font-size:.72em;color:var(--text-muted);">
                    <th style="text-align:left;padding:4px 6px;">Čas</th>
                    <th style="text-align:left;padding:4px 6px;">Příkaz</th>
                    <th style="text-align:left;padding:4px 6px;">Stav</th>
                    <th style="text-align:left;padding:4px 6px;">Režim</th>
                </tr></thead>
                <tbody>${rows}</tbody>
            </table></div>`;
        container.appendChild(sec);
    } catch {}
}

async function _loadAgentLabels(hostname, container) {
    try {
        const r = await fetch(`/api/agents/${encodeURIComponent(hostname)}/labels`);
        const d = await r.json();
        const labels = d.labels || {};
        const sec = document.createElement('div');
        sec.id = `agent-labels-sec-${hostname}`;
        sec.style.cssText = 'background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:14px;margin-top:12px;';
        const labelsHtml = (entries => entries.length
            ? entries.map(([k,v]) => `<span style="display:inline-flex;align-items:center;gap:4px;background:rgba(0,120,212,.15);border:1px solid rgba(0,120,212,.3);border-radius:10px;padding:2px 8px;font-size:.78em;margin:2px;">
                <b style="color:var(--accent);">${_escape(k)}</b><span style="color:var(--text-muted);">=</span>${_escape(v)}
                <span onclick="_removeAgentLabel('${_escape(hostname)}','${_escape(k)}')" style="cursor:pointer;color:var(--error);margin-left:3px;font-size:.9em;">×</span>
              </span>`).join('')
            : '<span style="color:var(--text-muted);font-size:.85em;">Žádné štítky</span>'
        )(Object.entries(labels));
        sec.innerHTML = `<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
            <div style="font-size:.78em;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);">Štítky (Labels)</div>
        </div>
        <div id="agent-labels-list-${hostname}" style="margin-bottom:8px;">${labelsHtml}</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
            <input id="lbl-key-${hostname}" placeholder="klíč" style="flex:1;min-width:80px;padding:4px 7px;font-size:.8em;background:var(--input-bg);border:1px solid var(--border);border-radius:4px;color:var(--text-main);">
            <input id="lbl-val-${hostname}" placeholder="hodnota" style="flex:2;min-width:100px;padding:4px 7px;font-size:.8em;background:var(--input-bg);border:1px solid var(--border);border-radius:4px;color:var(--text-main);">
            <button onclick="_addAgentLabel('${_escape(hostname)}')" style="padding:4px 10px;font-size:.8em;background:var(--accent);color:#fff;border:none;border-radius:4px;cursor:pointer;">+ Přidat</button>
        </div>`;
        container.appendChild(sec);
    } catch(e) {}
}

async function _addAgentLabel(hostname) {
    const key = document.getElementById(`lbl-key-${hostname}`)?.value.trim();
    const val = document.getElementById(`lbl-val-${hostname}`)?.value.trim();
    if (!key) return;
    const r = await fetch(`/api/agents/${encodeURIComponent(hostname)}/labels`);
    const existing = (await r.json()).labels || {};
    existing[key] = val || '';
    await fetch(`/api/agents/${encodeURIComponent(hostname)}/labels`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({labels: existing})
    });
    document.getElementById(`lbl-key-${hostname}`).value = '';
    document.getElementById(`lbl-val-${hostname}`).value = '';
    const sec = document.getElementById(`agent-labels-sec-${hostname}`);
    if (sec) sec.remove();
    _loadAgentLabels(hostname, document.getElementById('agent-detail-body'));
}

async function _removeAgentLabel(hostname, key) {
    const r = await fetch(`/api/agents/${encodeURIComponent(hostname)}/labels`);
    const existing = (await r.json()).labels || {};
    delete existing[key];
    await fetch(`/api/agents/${encodeURIComponent(hostname)}/labels`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({labels: existing})
    });
    const sec = document.getElementById(`agent-labels-sec-${hostname}`);
    if (sec) sec.remove();
    _loadAgentLabels(hostname, document.getElementById('agent-detail-body'));
}

async function _loadAgentSshHistory(hostname, container) {
    try {
        const r = await fetch(`/api/agents/${encodeURIComponent(hostname)}/ssh_history?limit=10`);
        const d = await r.json();
        const hist = d.history || [];
        if (!hist.length) return;
        const sec = document.createElement('div');
        sec.style.cssText = 'background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:14px;margin-top:12px;';
        sec.innerHTML = `<div style="font-size:.78em;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);margin-bottom:8px;">SSH History (047)</div>` +
            hist.map(h => `<div style="font-size:.78em;padding:4px 0;border-bottom:1px solid var(--border);display:flex;gap:8px;cursor:pointer;"
                onclick="_showSshRecord('${_escape(hostname)}',${h.id||0})">
                <span style="color:${h.success?'var(--success)':'var(--error)'};">${h.success?'✓':'✗'}</span>
                <code style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--accent);">${_escape(h.command)}</code>
                <span style="color:var(--text-muted);min-width:100px;text-align:right;">${(h.at||'').slice(0,16).replace('T',' ')}</span>
            </div>`).join('');
        container.appendChild(sec);
    } catch {}
}

async function _showSshRecord(hostname, id) {
    if (!id) return;
    const r = await fetch(`/api/agents/${encodeURIComponent(hostname)}/ssh_history/${id}`);
    const d = await r.json();
    if (d.error) return;
    const w = window.open('', '_blank', 'width=700,height=500,resizable=yes');
    w.document.write(`<pre style="background:#1a1a2e;color:#e0e0e0;padding:16px;margin:0;font-family:monospace;font-size:13px;white-space:pre-wrap;">`
        + `# ${_escape(d.command)}\n# ${d.executed_at||''} | actor: ${d.actor||'?'} | ${d.success?'OK':'FAIL'}\n`
        + `${'─'.repeat(60)}\n${_escape(d.output||'(no output)')}</pre>`);
    w.document.close();
}

// 197-200: HW metrics section (net/GPU/SMART/UPS)
function _appendHwMetricsSection(hostname, container) {
    const sec = document.createElement('div');
    sec.style.cssText = 'background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:14px;margin-top:12px;';
    sec.innerHTML = `
        <div style="font-size:.78em;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);margin-bottom:8px;"><i class="fa-solid fa-microchip"></i> HW Metriky (SSH)</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;">
            ${['net','gpu','smart','ups'].map(t => `<button onclick="_loadHwMetric('${_escape(hostname)}','${t}')"
                style="padding:3px 9px;font-size:.75em;background:transparent;border:1px solid var(--border);color:var(--text-muted);border-radius:4px;cursor:pointer;"
                onmouseover="this.style.borderColor='var(--accent)'" onmouseout="this.style.borderColor='var(--border)'">
                ${t.toUpperCase()}
            </button>`).join('')}
        </div>
        <div id="hw-metric-out-${_escape(hostname)}" style="font-size:.76em;font-family:monospace;color:var(--text-muted);max-height:120px;overflow-y:auto;"></div>`;
    container.appendChild(sec);
}

async function _loadHwMetric(hostname, type) {
    const el = document.getElementById(`hw-metric-out-${hostname}`);
    if (!el) return;
    el.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
    try {
        const r = await fetch(`/api/agents/${encodeURIComponent(hostname)}/hw_metrics`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({type}),
        });
        const d = await r.json();
        if (d.error) { el.innerHTML = `<span style="color:var(--error);">${_escape(d.error)}</span>`; return; }
        const lines = d.lines || [];
        if (!lines.length || (lines.length === 1 && lines[0].includes('NOT_FOUND'))) {
            el.innerHTML = `<span style="color:var(--text-muted);">${type.toUpperCase()} — nedostupné nebo nenalezeno.</span>`;
            return;
        }
        el.innerHTML = lines.map(l => `<div>${_escape(l)}</div>`).join('');
    } catch(e) {
        el.innerHTML = `<span style="color:var(--error);">Chyba: ${_escape(e.message)}</span>`;
    }
}

// 171: CVE scan section
function _appendCveScanSection(hostname, container) {
    const sec = document.createElement('div');
    sec.id = `agent-cve-sec-${hostname}`;
    sec.style.cssText = 'background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:14px;margin-top:12px;';
    sec.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
            <div style="font-size:.78em;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);"><i class="fa-solid fa-shield-virus" style="color:var(--error);"></i> CVE / Security scan</div>
            <button onclick="_runCveScan('${_escape(hostname)}')" id="cve-scan-btn-${_escape(hostname)}"
                style="padding:3px 9px;font-size:.78em;background:transparent;border:1px solid var(--error,#dc3545);color:var(--error,#dc3545);border-radius:4px;cursor:pointer;">
                <i class="fa-solid fa-magnifying-glass"></i> Skenovat
            </button>
        </div>
        <div id="cve-content-${_escape(hostname)}" style="color:var(--text-muted);font-size:.82em;">Kliknutím spustíte SSH scan bezpečnostních aktualizací.</div>`;
    container.appendChild(sec);
}

async function _runCveScan(hostname) {
    const btn = document.getElementById(`cve-scan-btn-${hostname}`);
    const el  = document.getElementById(`cve-content-${hostname}`);
    if (!el) return;
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>'; }
    try {
        const r = await fetch(`/api/agents/${encodeURIComponent(hostname)}/cve_scan`, {method:'POST'});
        const d = await r.json();
        if (d.error) { el.innerHTML = `<span style="color:var(--error);">${_escape(d.error)}</span>`; return; }
        const findings = d.findings || [];
        el.innerHTML = findings.length
            ? `<div style="color:var(--error);font-weight:600;margin-bottom:6px;">${findings.length} bezpečnostních aktualizací:</div>` +
              findings.map(f => `<div style="padding:3px 0;border-bottom:1px solid rgba(255,255,255,.05);font-size:.78em;"><b style="color:var(--warning);">${_escape(f.package)}</b> <span style="color:var(--text-muted);">${_escape(f.info)}</span></div>`).join('')
            : `<span style="color:var(--success);">✓ ${_escape(d.message || 'Žádné bezpečnostní aktualizace.')}</span>`;
    } catch(e) {
        el.innerHTML = `<span style="color:var(--error);">Chyba: ${_escape(e.message)}</span>`;
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-magnifying-glass"></i> Skenovat'; }
    }
}

// 146: Packages section — on-demand SSH query
function _appendPackagesSection(hostname, container) {
    const sec = document.createElement('div');
    sec.id = `agent-packages-sec-${hostname}`;
    sec.style.cssText = 'background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:14px;margin-top:12px;';
    sec.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
            <div style="font-size:.78em;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);">Nainstalované balíčky</div>
            <button onclick="_loadAgentPackages('${_escape(hostname)}')" id="pkg-load-btn-${_escape(hostname)}"
                style="padding:3px 9px;font-size:.78em;background:transparent;border:1px solid var(--accent);color:var(--accent);border-radius:4px;cursor:pointer;">
                <i class="fa-solid fa-box"></i> Načíst přes SSH
            </button>
        </div>
        <div id="pkg-content-${_escape(hostname)}" style="color:var(--text-muted);font-size:.82em;">Kliknutím načtete balíčky přes SSH.</div>`;
    container.appendChild(sec);
}

async function _loadAgentPackages(hostname) {
    const btn = document.getElementById(`pkg-load-btn-${hostname}`);
    const content = document.getElementById(`pkg-content-${hostname}`);
    if (!content) return;
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Načítám…'; }

    const filterVal = document.getElementById(`pkg-filter-${hostname}`)?.value?.trim() || '';
    try {
        const r = await fetch(`/api/agents/${encodeURIComponent(hostname)}/packages`, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({filter: filterVal}),
        });
        const d = await r.json();
        if (d.error) { content.innerHTML = `<span style="color:var(--error);">${_escape(d.error)}</span>`; return; }
        const pkgs = d.packages || [];
        content.innerHTML = `
            <div style="display:flex;gap:6px;align-items:center;margin-bottom:8px;">
                <input id="pkg-filter-${_escape(hostname)}" type="search" placeholder="Filtrovat…" value="${_escape(filterVal)}"
                    style="flex:1;padding:4px 8px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:4px;font-size:.8em;"
                    onkeydown="if(event.key==='Enter')_loadAgentPackages('${_escape(hostname)}')">
                <span style="font-size:.78em;color:var(--text-muted);white-space:nowrap;">${pkgs.length} balíčků${filterVal?' (filtr)':''}</span>
            </div>
            <div style="max-height:220px;overflow-y:auto;font-size:.78em;font-family:monospace;">
                ${pkgs.length ? pkgs.map(p =>
                    `<div style="display:flex;gap:8px;padding:2px 0;border-bottom:1px solid rgba(255,255,255,.04);">
                        <span style="flex:1;color:var(--text-main);">${_escape(p.name)}</span>
                        <span style="color:var(--text-muted);white-space:nowrap;">${_escape(p.version)}</span>
                    </div>`).join('')
                : '<span style="color:var(--text-muted);">Žádné balíčky.</span>'}
            </div>`;
    } catch(e) {
        content.innerHTML = `<span style="color:var(--error);">Chyba: ${_escape(e.message)}</span>`;
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-rotate"></i> Obnovit'; }
    }
}

async function _loadAgentThresholds(hostname, container) {
    try {
        const r = await fetch(`/api/agents/${encodeURIComponent(hostname)}/thresholds`);
        const d = await r.json();
        const thresholds = d.thresholds || [];
        const sec = document.createElement('div');
        sec.style.cssText = 'background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:14px;margin-top:12px;';
        const sfxEsc = hostname.replace(/\W/g,'_');
        sec.innerHTML = `<div style="font-size:.78em;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);margin-bottom:8px;">Per-Agent Thresholds</div>` +
            (thresholds.length ? thresholds.map(t => `<div style="display:flex;gap:8px;font-size:.8em;padding:3px 0;border-bottom:1px solid var(--border);">
                <code style="flex:1;color:var(--accent);">${_escape(t.metric_pattern)}</code>
                ${t.above!=null?`<span style="color:var(--error);">↑ ${t.above}</span>`:''}
                ${t.below!=null?`<span style="color:#0078d4;">↓ ${t.below}</span>`:''}
                <span style="color:var(--text-muted);">${t.channel}</span>
                <i class="fa-solid fa-trash" style="cursor:pointer;color:var(--error);" onclick="_deleteAgentThreshold(${t.id}, '${_escape(hostname)}')"></i>
            </div>`).join('') : '<span style="color:var(--text-muted);font-size:.82em;">Žádné thresholdy</span>') +
            `<div style="margin-top:6px;display:flex;gap:4px;flex-wrap:wrap;">
                <span style="font-size:.72em;color:var(--text-muted);align-self:center;">Rychlé:</span>
                <button onclick="_quickThreshold('${_escape(hostname)}','cpu_pct',90)" style="padding:2px 7px;font-size:.72em;background:rgba(220,53,69,.15);border:1px solid rgba(220,53,69,.4);color:#dc3545;border-radius:3px;cursor:pointer;">CPU &gt;90%</button>
                <button onclick="_quickThreshold('${_escape(hostname)}','ram_pct',90)" style="padding:2px 7px;font-size:.72em;background:rgba(220,53,69,.15);border:1px solid rgba(220,53,69,.4);color:#dc3545;border-radius:3px;cursor:pointer;">RAM &gt;90%</button>
                <button onclick="_quickThreshold('${_escape(hostname)}','disk_pct',85)" style="padding:2px 7px;font-size:.72em;background:rgba(255,130,0,.15);border:1px solid rgba(255,130,0,.4);color:#fa8231;border-radius:3px;cursor:pointer;">Disk &gt;85%</button>
            </div>
            <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;">
                <input id="thresh-pattern-${sfxEsc}" placeholder="metric_*" style="flex:1;min-width:100px;padding:4px 7px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:3px;font-size:.78em;font-family:monospace;">
                <input id="thresh-above-${sfxEsc}" type="number" placeholder="↑ nad" style="width:70px;padding:4px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:3px;font-size:.78em;">
                <input id="thresh-below-${sfxEsc}" type="number" placeholder="↓ pod" style="width:70px;padding:4px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:3px;font-size:.78em;">
                <button onclick="_addAgentThreshold('${hostname}')" style="padding:4px 10px;background:var(--accent);color:#fff;border:none;border-radius:3px;cursor:pointer;font-size:.78em;">+</button>
            </div>`;
        container.appendChild(sec);
    } catch {}
}

async function _addAgentThreshold(hostname) {
    const sfx = hostname.replace(/\W/g,'_');
    const pattern = document.getElementById(`thresh-pattern-${sfx}`)?.value.trim();
    const above = document.getElementById(`thresh-above-${sfx}`)?.value;
    const below = document.getElementById(`thresh-below-${sfx}`)?.value;
    if (!pattern) return;
    await fetch(`/api/agents/${encodeURIComponent(hostname)}/thresholds`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({metric_pattern: pattern, above: above||null, below: below||null})
    });
    await openAgentDetailModal(hostname);
}

async function _quickThreshold(hostname, metric, aboveVal) {
    await fetch(`/api/agents/${encodeURIComponent(hostname)}/thresholds`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({metric_pattern: metric, above: aboveVal, below: null})
    });
    await openAgentDetailModal(hostname);
}

async function _deleteAgentThreshold(id, hostname) {
    await fetch(`/api/agents/thresholds/${id}`, {method:'DELETE'});
    if (hostname) await openAgentDetailModal(hostname);
}

function closeAgentDetailModal() {
    document.getElementById('agent-detail-modal').style.display = 'none';
}

// 145: Batch SSH modal
async function openBatchSshModal() {
    const modal = document.getElementById('batch-ssh-modal');
    if (!modal) return;
    modal.style.display = 'flex';
    document.getElementById('batch-ssh-results').style.display = 'none';
    const agentsEl = document.getElementById('batch-ssh-agents');
    agentsEl.innerHTML = '<span style="color:var(--text-muted);font-size:.85em;"><i class="fa-solid fa-spinner fa-spin"></i> Načítám…</span>';
    try {
        const r = await fetch('/api/agents/list');
        const d = await r.json();
        const agents = (d.agents || []).filter(a => a.hostname);
        if (!agents.length) {
            agentsEl.innerHTML = '<span style="color:var(--text-muted);font-size:.85em;">Žádní agenti.</span>';
            return;
        }
        agentsEl.innerHTML = agents.map(a => {
            const online = a.status === 'ONLINE';
            const dot = online ? 'var(--success,#28a745)' : 'var(--error,#dc3545)';
            return `<label style="display:inline-flex;align-items:center;gap:5px;padding:3px 8px;border:1px solid var(--border);border-radius:12px;cursor:pointer;font-size:.82em;white-space:nowrap;">
                <input type="checkbox" class="batch-ssh-cb" value="${_escape(a.hostname)}" ${online?'checked':''}>
                <span style="width:7px;height:7px;border-radius:50%;background:${dot};display:inline-block;"></span>
                ${_escape(a.hostname)}
            </label>`;
        }).join('');
    } catch(e) {
        agentsEl.innerHTML = `<span style="color:var(--error);font-size:.85em;">Chyba načítání agentů.</span>`;
    }
}

function closeBatchSshModal() {
    const modal = document.getElementById('batch-ssh-modal');
    if (modal) modal.style.display = 'none';
}

function batchSshSelectAll(checked) {
    document.querySelectorAll('.batch-ssh-cb').forEach(cb => { cb.checked = checked; });
}

async function runBatchSsh() {
    const command = (document.getElementById('batch-ssh-cmd')?.value || '').trim();
    const hosts = [...document.querySelectorAll('.batch-ssh-cb:checked')].map(cb => cb.value);
    if (!command) { alert('Zadejte příkaz.'); return; }
    if (!hosts.length) { alert('Vyberte alespoň jednoho agenta.'); return; }

    const btn = document.getElementById('batch-ssh-run-btn');
    const resultsEl = document.getElementById('batch-ssh-results');
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Běží…'; }
    resultsEl.style.display = 'none';

    try {
        const r = await fetch('/api/ssh/batch', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({hosts, command}),
        });
        const d = await r.json();
        if (d.error) { alert(d.error); return; }
        const results = d.results || [];
        resultsEl.style.display = 'flex';
        resultsEl.innerHTML = `<div style="font-size:.78em;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">
            Výsledky — <code style="color:var(--accent);">${_escape(command)}</code> (${results.filter(r=>r.ok).length}/${results.length} OK)
        </div>` + results.map(res => `
            <div style="border-left:3px solid ${res.ok?'var(--success,#28a745)':'var(--error,#dc3545)'};padding:6px 10px;margin-bottom:4px;background:rgba(255,255,255,.02);border-radius:0 4px 4px 0;">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:3px;">
                    <i class="fa-solid fa-${res.ok?'check':'times'}" style="color:${res.ok?'var(--success,#28a745)':'var(--error,#dc3545)'};font-size:.8em;"></i>
                    <b style="font-size:.85em;font-family:monospace;">${_escape(res.host)}</b>
                </div>
                ${res.output ? `<pre style="font-size:.75em;color:#aaa;margin:0;white-space:pre-wrap;max-height:80px;overflow-y:auto;">${_escape(res.output.slice(0,500))}</pre>` : ''}
            </div>`).join('');
    } catch(e) {
        alert('Chyba při spouštění batch SSH: ' + e.message);
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-play"></i> Spustit'; }
    }
}

// 060: Runbook modal
let _runbookCtx = {};
async function openRunbookModal(plugin, channel, llB64) {
    _runbookCtx = { plugin, channel, llB64 };
    const modal = document.getElementById('runbook-modal');
    const title = document.getElementById('runbook-title');
    const body = document.getElementById('runbook-body');
    const meta = document.getElementById('runbook-meta');
    const issueType = (channel ? channel.toUpperCase() + '|' : '') + plugin;
    if (title) title.textContent = issueType;
    modal.style.display = 'flex';
    body.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i></div>';
    // Zkus načíst existující runbook
    try {
        const issueTypeB64 = btoa(unescape(encodeURIComponent(issueType)));
        const r = await fetch(`/api/runbooks/${encodeURIComponent(issueTypeB64)}`);
        if (r.ok) {
            const d = await r.json();
            body.textContent = d.content || '';
            if (meta) meta.textContent = `Vytvořil: ${d.created_by || 'AI'} · ${(d.updated_at||'').slice(0,16)}`;
            return;
        }
    } catch(_) {}
    // Žádný runbook — nabídni generování
    body.innerHTML = `<div style="color:var(--text-muted);text-align:center;padding:20px;">
        <i class="fa-solid fa-book-open" style="font-size:2em;margin-bottom:10px;opacity:.4;display:block;"></i>
        Runbook pro <b>${_escape(issueType)}</b> zatím neexistuje.<br>
        <small>Klikněte na "Generovat AI" pro vytvoření.</small>
    </div>`;
    if (meta) meta.textContent = '';
}

async function _runbookGenerate() {
    const { plugin, channel, llB64 } = _runbookCtx;
    if (!plugin) return;
    const btn = document.getElementById('runbook-gen-btn');
    const body = document.getElementById('runbook-body');
    const meta = document.getElementById('runbook-meta');
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>'; }
    body.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i> AI generuje runbook…</div>';
    try {
        let lastLine = '';
        try { lastLine = decodeURIComponent(escape(atob(llB64))); } catch(_) {}
        const r = await fetch('/api/runbooks/generate', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({plugin, channel, last_line: lastLine})
        });
        const d = await r.json();
        if (d.status === 'ok') {
            body.textContent = d.content;
            if (meta) meta.textContent = `Vytvořil: AI · právě teď`;
        } else {
            body.innerHTML = `<div style="color:var(--error);">Chyba: ${_escape(d.error||'?')}</div>`;
        }
    } catch(e) {
        body.innerHTML = `<div style="color:var(--error);">Chyba: ${_escape(e.message)}</div>`;
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> (Re)generovat AI'; }
    }
}

// 040: Agent compare
async function openAgentCompare(preselect) {
    const modal = document.getElementById('agent-compare-modal');
    modal.style.display = 'flex';
    // Načti seznam agentů do selectů
    try {
        const r = await fetch('/api/agents/list');
        const d = await r.json();
        const agents = (d.agents || []).map(a => a.hostname);
        ['cmp-agent-a','cmp-agent-b'].forEach((id, idx) => {
            const sel = document.getElementById(id);
            sel.innerHTML = agents.map(h =>
                `<option value="${_escape(h)}" ${(preselect && h===preselect[idx])?'selected':''}>${_escape(h)}</option>`
            ).join('');
        });
        // Předvyber B jako druhý agent
        const selB = document.getElementById('cmp-agent-b');
        if (agents.length > 1 && selB) selB.selectedIndex = 1;
    } catch(e) {}
}

async function runAgentCompare() {
    const a = document.getElementById('cmp-agent-a')?.value;
    const b = document.getElementById('cmp-agent-b')?.value;
    const days = document.getElementById('cmp-days')?.value || 3;
    const body = document.getElementById('agent-compare-body');
    if (!a || !b || a === b) {
        if (body) body.innerHTML = '<div style="color:var(--error);padding:20px;">Vyberte dva různé agenty.</div>';
        return;
    }
    body.innerHTML = '<div style="text-align:center;padding:30px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i></div>';
    try {
        const r = await fetch(`/api/agents/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}&days=${days}`);
        const d = await r.json();
        const common = d.common_metrics || [];
        if (!common.length) {
            body.innerHTML = '<div style="color:var(--text-muted);padding:20px;">Žádné společné metriky k porovnání.</div>';
            return;
        }
        // Vytvoř side-by-side grafy pro prvních 6 společných metrik
        const charts = common.slice(0, 6).map((metric, idx) => {
            const da = (d.data[a]?.[metric] || []).slice(-48);
            const db = (d.data[b]?.[metric] || []).slice(-48);
            const labels = da.map(p => (p.ts||'').slice(11,16));
            const cid = `cmp_chart_${idx}`;
            return `<div style="background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:12px;">
                <div style="font-size:.75em;color:var(--text-muted);margin-bottom:6px;font-weight:600;">${_escape(metric)}</div>
                <canvas id="${cid}" height="80"></canvas>
                <script>(function(){
                    const ctx=document.getElementById('${cid}');
                    if(!ctx||!window.Chart)return;
                    new Chart(ctx,{type:'line',data:{
                        labels:${JSON.stringify(labels)},
                        datasets:[
                            {label:${JSON.stringify(a)},data:${JSON.stringify(da.map(p=>p.v))},borderColor:'#0078d4',borderWidth:1.5,pointRadius:0,fill:false,tension:0.2},
                            {label:${JSON.stringify(b)},data:${JSON.stringify(db.map(p=>p.v))},borderColor:'#28a745',borderWidth:1.5,pointRadius:0,fill:false,tension:0.2,borderDash:[4,2]}
                        ]
                    },options:{animation:false,plugins:{legend:{labels:{color:'#aaa',font:{size:9}}}},scales:{x:{display:false},y:{ticks:{color:'#aaa',font:{size:9},maxTicksLimit:3}}}}});
                })();<\/script>
            </div>`;
        }).join('');
        // Přehled statistik
        const statsA = d.data[a] || {}; const statsB = d.data[b] || {};
        const statRows = common.slice(0,8).map(m => {
            const valsA = (statsA[m]||[]).map(p=>p.v).filter(v=>v!=null);
            const valsB = (statsB[m]||[]).map(p=>p.v).filter(v=>v!=null);
            const avgA = valsA.length ? (valsA.reduce((s,v)=>s+v,0)/valsA.length).toFixed(2) : '—';
            const avgB = valsB.length ? (valsB.reduce((s,v)=>s+v,0)/valsB.length).toFixed(2) : '—';
            const diff = (valsA.length && valsB.length) ? ((parseFloat(avgA)-parseFloat(avgB)).toFixed(2)) : '—';
            const diffColor = diff === '—' ? 'var(--text-muted)' : (parseFloat(diff) > 0 ? '#f87171' : '#4caf50');
            return `<tr style="border-bottom:1px solid rgba(255,255,255,.04);">
                <td style="padding:5px 8px;font-size:.78em;font-family:monospace;color:var(--text-muted);">${_escape(m)}</td>
                <td style="padding:5px 8px;text-align:right;color:#0078d4;">${avgA}</td>
                <td style="padding:5px 8px;text-align:right;color:#28a745;">${avgB}</td>
                <td style="padding:5px 8px;text-align:right;color:${diffColor};">${diff !== '—' && parseFloat(diff) > 0 ? '+' : ''}${diff}</td>
            </tr>`;
        }).join('');

        body.innerHTML = `
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:12px;font-size:.82em;">
                <div style="background:rgba(0,120,212,.1);border:1px solid rgba(0,120,212,.3);border-radius:6px;padding:8px;text-align:center;">
                    <i class="fa-solid fa-server" style="color:#0078d4;"></i> <b style="color:#0078d4;">${_escape(a)}</b>
                </div>
                <div style="background:rgba(40,167,69,.1);border:1px solid rgba(40,167,69,.3);border-radius:6px;padding:8px;text-align:center;">
                    <i class="fa-solid fa-server" style="color:#28a745;"></i> <b style="color:#28a745;">${_escape(b)}</b>
                </div>
            </div>
            <div style="margin-bottom:14px;">
                <div style="font-size:.75em;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);margin-bottom:8px;">Průměrné hodnoty (${days}d)</div>
                <table style="width:100%;border-collapse:collapse;">
                    <thead><tr style="border-bottom:1px solid var(--border);">
                        <th style="padding:4px 8px;text-align:left;font-size:.72em;color:var(--text-muted);font-weight:400;">Metrika</th>
                        <th style="padding:4px 8px;text-align:right;font-size:.72em;color:#0078d4;">${_escape(a)}</th>
                        <th style="padding:4px 8px;text-align:right;font-size:.72em;color:#28a745;">${_escape(b)}</th>
                        <th style="padding:4px 8px;text-align:right;font-size:.72em;color:var(--text-muted);">Δ rozdíl</th>
                    </tr></thead>
                    <tbody>${statRows}</tbody>
                </table>
            </div>
            <div style="font-size:.75em;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);margin-bottom:8px;">Grafy (${common.length} metrik)</div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px;">${charts}</div>`;
        body.querySelectorAll('script').forEach(s => { try { eval(s.textContent); } catch {} });
    } catch(e) {
        body.innerHTML = `<div style="color:var(--error);padding:20px;">Chyba: ${_escape(e.message)}</div>`;
    }
}

// ---- Tag Cloud Widget ----

async function openTagCloud() {
    try {
        const r = await fetch('/api/issues/tags/all');
        const d = await r.json();
        const tags = d.tags || [];
        if (!tags.length) { alert('Žádné tagy zatím.'); return; }

        // Inject tag cloud panel do tools modal nebo standalone popup
        let panel = document.getElementById('tag-cloud-panel');
        if (!panel) {
            panel = document.createElement('div');
            panel.id = 'tag-cloud-panel';
            panel.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:9000;background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:20px;min-width:340px;max-width:520px;box-shadow:0 8px 32px rgba(0,0,0,.5);';
            document.body.appendChild(panel);
        }
        const maxCnt = Math.max(...tags.map(t=>t.count));
        const tagsHtml = tags.map(t => {
            const size = 0.8 + (t.count / maxCnt) * 0.8;
            return `<span onclick="_filterByTag('${_escape(t.tag)}');panel.remove();" style="cursor:pointer;display:inline-block;margin:4px;font-size:${size.toFixed(2)}em;background:rgba(0,120,212,0.15);color:#a3cfff;border:1px solid rgba(0,120,212,0.25);border-radius:12px;padding:3px 10px;">#${_escape(t.tag)} <small style="opacity:.6;">${t.count}</small></span>`;
        }).join('');
        panel.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
            <b style="color:var(--accent);"><i class="fa-solid fa-tags"></i> Tag Cloud</b>
            <i class="fa-solid fa-times" style="cursor:pointer;" onclick="document.getElementById('tag-cloud-panel').remove()"></i>
        </div>
        <div style="line-height:2.2;">${tagsHtml}</div>`;
        // Zavřít kliknutím mimo
        setTimeout(() => document.addEventListener('click', e => {
            if (!panel.contains(e.target)) panel.remove();
        }, {once:true}), 100);
    } catch (e) { alert('Chyba načítání tagů'); }
}

async function openDeviceDetailModal(hostname, type, webUiUrl) {
    const modal = document.getElementById('device-detail-modal');
    const body  = document.getElementById('dd-body');
    const title = document.getElementById('dd-title');
    const link  = document.getElementById('dd-webui-link');

    const typeIcon = type === 'hw'
        ? '<i class="fa-solid fa-microchip" style="color:var(--accent);"></i>'
        : type === 'alert'
            ? '<i class="fa-solid fa-tower-broadcast" style="color:var(--accent);"></i>'
            : '<i class="fa-solid fa-server" style="color:var(--accent);"></i>';
    title.innerHTML = `${typeIcon} ${hostname}`;

    link.innerHTML = webUiUrl
        ? `<a href="${webUiUrl}" target="_blank" style="color:var(--accent);"><i class="fa-solid fa-arrow-up-right-from-square"></i> Otevřít Web UI</a>`
        : '';

    modal.style.display = 'flex';
    body.innerHTML = `<span style="color:#666;"><i class="fa-solid fa-spinner fa-spin"></i> ${t('loading')}</span>`;

    try {
        if (type === 'agent') {
            body.innerHTML = await _fetchAgentDetail(hostname);
            _loadHostMaintWindows(hostname);
        } else if (type === 'alert' || type === 'hw') {
            const issuesHtml = await _fetchDeviceIssues(hostname);
            let sensorsHtml = type === 'hw' ? await _fetchHWSensors(hostname) : null;
            body.innerHTML = `
                <div style="font-weight:600; color:var(--accent); margin-bottom:10px; font-size:.9rem; text-transform:uppercase; letter-spacing:.05em;">${t('active_incidents')}</div>
                ${issuesHtml}
                ${sensorsHtml ? `
                    <div style="font-weight:600; color:var(--accent); margin:16px 0 10px 0; font-size:.9rem; text-transform:uppercase; letter-spacing:.05em;">${t('sensors_live')}</div>
                    ${sensorsHtml}` : ''}`;
        }
    } catch(e) {
        body.innerHTML = `<span style="color:var(--error);">✗ ${t('load_error_detail', {msg: e.message})}</span>`;
    }
}

async function _fetchDeviceIssues(hostname) {
    try {
        const res = await fetch('/api/v1/issues');
        const data = await res.json();
        const issues = (data.issues || []).filter(i => (i.host || '').includes(hostname));
        if (!issues.length) return `<p style="color:#666; font-size:.9rem;">${t('no_active_incidents')}</p>`;
        return issues.slice(0, 20).map(i => {
            const catColors = {security:'#f87171', root:'#fb923c', agent:'#fbbf24', infra:'#facc15'};
            const _rawCat = (i.channel_type || 'infra').toLowerCase();
            const cat = {info:'infra', clusters:'infra', 'infra':'infra', security:'security', root:'root', agent:'agent'}[_rawCat] || 'infra';
            const catLabel = {infra:'Infra', security:'Security', root:'Root', agent:'Agent'}[cat] || cat.toUpperCase();
            const col = catColors[cat] || '#facc15';
            const ts  = i.last_seen ? i.last_seen.slice(0,16) : '—';
            return `<div style="border-left:3px solid ${col}; padding:6px 10px; margin-bottom:6px; background:rgba(255,255,255,.02); border-radius:0 4px 4px 0;">
                <span style="color:${col}; font-weight:700; font-size:.8rem; margin-right:6px;">${catLabel}</span>
                <b style="font-size:.9rem;">${i.host || '?'}</b>
                <span style="color:#888; font-size:.8rem; margin-left:6px;">${ts}</span>
                <div style="color:#aaa; font-size:.82rem; margin-top:2px;">${(i.last_line||'').slice(0,80)}</div>
            </div>`;
        }).join('');
    } catch(e) {
        return `<p style="color:var(--error); font-size:.9rem;">${t('load_incidents_error', {msg: e.message})}</p>`;
    }
}

async function _fetchAgentDetail(hostname) {
    const r = await fetch(`/api/agents/${encodeURIComponent(hostname)}/detail`);
    const d = await r.json();
    if (!r.ok || d.error) return `<p style="color:var(--error);">✗ ${d.error || 'Chyba'}</p>`;

    const ag = d.agent || {};
    const statusColor = ag.status === 'ONLINE' ? 'var(--success,#28a745)' : 'var(--error,#dc3545)';
    const lastSeen = ag.last_seen ? new Date(ag.last_seen).toLocaleString('cs-CZ') : '—';
    const regAt    = ag.registered_at ? new Date(ag.registered_at).toLocaleString('cs-CZ') : '—';
    const isSuperAdmin = window.currentRole === 'superadmin';
    const isAdmin = window.currentRole === 'admin' || isSuperAdmin;
    const ips = (() => { try { return JSON.parse(ag.ip_addresses || '[]'); } catch(_) { return []; } })();
    const ipsHtml = ips.length ? ips.join(', ') : '—';

    const metaHtml = `
        <table style="width:100%;border-collapse:collapse;font-size:.88rem;margin-bottom:14px;">
            <tr style="border-bottom:1px solid var(--border);">
                <td style="padding:6px 0;color:var(--text-muted);width:42%;">Status</td>
                <td style="padding:6px 0;"><b style="color:${statusColor};">● ${ag.status || '—'}</b></td>
            </tr>
            <tr style="border-bottom:1px solid var(--border);">
                <td style="padding:6px 0;color:var(--text-muted);">IP adres${ips.length > 1 ? 'y' : 'a'}</td>
                <td style="padding:6px 0;font-family:monospace;">${ipsHtml}</td>
            </tr>
            <tr style="border-bottom:1px solid var(--border);">
                <td style="padding:6px 0;color:var(--text-muted);">Poslední kontakt</td>
                <td style="padding:6px 0;">${lastSeen}</td>
            </tr>
            <tr style="border-bottom:1px solid var(--border);">
                <td style="padding:6px 0;color:var(--text-muted);">Registrován</td>
                <td style="padding:6px 0;">${regAt}</td>
            </tr>
            <tr style="border-bottom:1px solid var(--border);">
                <td style="padding:6px 0;color:var(--text-muted);">Aktivní issues</td>
                <td style="padding:6px 0;"><b style="color:${d.active_issues > 0 ? 'var(--warning,#ffc107)' : 'var(--success)'}">${d.active_issues}</b></td>
            </tr>
            <tr style="border-bottom:1px solid var(--border);">
                <td style="padding:6px 0;color:var(--text-muted);">Resolved (7 dní)</td>
                <td style="padding:6px 0;">${d.resolved_7d}</td>
            </tr>
            ${ag.agent_version ? `<tr style="border-bottom:1px solid var(--border);">
                <td style="padding:6px 0;color:var(--text-muted);">Verze agenta</td>
                <td style="padding:6px 0;font-family:monospace;font-size:.85rem;color:#a3cfff;">${_escape(ag.agent_version)}</td>
            </tr>` : ''}
        </table>`;

    const issues = d.recent_issues || [];
    const issuesHtml = issues.length ? issues.map(i => {
        const _rawCat2 = (i.channel_type || 'infra').toLowerCase();
        const _cat2 = {info:'infra', clusters:'infra', infra:'infra', security:'security', root:'root', agent:'agent'}[_rawCat2] || 'infra';
        const _catLabel2 = {infra:'Infra', security:'Security', root:'Root', agent:'Agent'}[_cat2] || _cat2.toUpperCase();
        const col = {security:'#f87171',root:'#fb923c',agent:'#fbbf24',infra:'#facc15'}[_cat2] || '#facc15';
        return `<div style="border-left:3px solid ${col};padding:5px 10px;margin-bottom:5px;background:rgba(255,255,255,.02);border-radius:0 4px 4px 0;">
            <span style="color:${col};font-weight:700;font-size:.78rem;">${_catLabel2}</span>
            <span style="color:#aaa;font-size:.78rem;margin-left:8px;">${(i.last_seen||'').slice(0,16)}</span>
            <div style="color:#ccc;font-size:.82rem;margin-top:2px;">${_escape((i.last_line||'').slice(0,90))}</div>
        </div>`;
    }).join('') : `<p style="color:#666;font-size:.9rem;">${t('no_active_incidents')}</p>`;

    const notesVal = _escape(ag.notes || '');
    const notesHtml = isAdmin ? `
        <div style="font-weight:600;color:var(--accent);margin:14px 0 8px;font-size:.85rem;text-transform:uppercase;letter-spacing:.05em;">Poznámky</div>
        <textarea id="dd-notes-${hostname}" style="width:100%;background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:4px;color:var(--text-main);padding:6px 8px;font-size:.85rem;resize:vertical;min-height:60px;">${notesVal}</textarea>
        <button onclick="_saveAgentNotes('${hostname}')" style="margin-top:6px;background:transparent;border:1px solid var(--accent);color:var(--accent);padding:4px 12px;border-radius:4px;cursor:pointer;font-size:.82rem;">Uložit poznámku</button>` : (ag.notes ? `<div style="margin-top:12px;color:#aaa;font-size:.85rem;border-left:2px solid var(--border);padding-left:8px;">${notesVal}</div>` : '');

    const groupVal = _escape(ag.agent_group || '');
    const groupHtml = isAdmin ? `
        <div style="font-weight:600;color:var(--accent);margin:14px 0 8px;font-size:.85rem;text-transform:uppercase;letter-spacing:.05em;"><i class="fa-solid fa-layer-group"></i> Skupina</div>
        <div style="display:flex;gap:6px;align-items:center;">
            <input id="dd-group-${hostname}" type="text" value="${groupVal}" placeholder="bez skupiny"
                style="flex:1;background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:4px;color:var(--text-main);padding:5px 8px;font-size:.85rem;">
            <button onclick="_saveAgentGroup('${hostname}')" style="background:transparent;border:1px solid var(--accent);color:var(--accent);padding:4px 10px;border-radius:4px;cursor:pointer;font-size:.82rem;">Uložit</button>
        </div>` : (ag.agent_group ? `<div style="margin-top:8px;color:#aaa;font-size:.82rem;"><i class="fa-solid fa-layer-group"></i> ${groupVal}</div>` : '');

    const hbTimeout = d.heartbeat_timeout ?? ag.heartbeat_timeout;
    const hbGlobal  = 180;
    const hbHtml = isAdmin ? `
        <div style="font-weight:600;color:var(--accent);margin:14px 0 8px;font-size:.85rem;text-transform:uppercase;letter-spacing:.05em;"><i class="fa-solid fa-heart-pulse"></i> Heartbeat timeout</div>
        <div style="display:flex;gap:6px;align-items:center;">
            <input id="dd-hb-${hostname}" type="number" min="30" max="86400" step="30"
                value="${hbTimeout ?? hbGlobal}"
                style="width:90px;background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:4px;color:var(--text-main);padding:5px 8px;font-size:.85rem;">
            <span style="font-size:.8rem;color:var(--text-muted);">s ${hbTimeout ? '' : '(globální default)'}</span>
            <button onclick="_saveHeartbeatTimeout('${hostname}')" style="background:transparent;border:1px solid var(--accent);color:var(--accent);padding:4px 10px;border-radius:4px;cursor:pointer;font-size:.82rem;">Uložit</button>
            ${hbTimeout ? `<button onclick="_clearHeartbeatTimeout('${hostname}')" style="background:transparent;border:1px solid var(--border);color:var(--text-muted);padding:4px 10px;border-radius:4px;cursor:pointer;font-size:.82rem;">Reset</button>` : ''}
        </div>` : '';

    const regenHtml = isSuperAdmin ? `
        <button onclick="_regenAgentToken('${hostname}')" style="margin-top:10px;background:transparent;border:1px solid var(--error,#dc3545);color:var(--error,#dc3545);padding:4px 12px;border-radius:4px;cursor:pointer;font-size:.82rem;">
            <i class="fa-solid fa-key"></i> Regenerovat token
        </button>` : '';

    const maintUntil = ag.maintenance_until ? new Date(ag.maintenance_until) : null;
    const inMaint = maintUntil && maintUntil > new Date();
    const maintHtml = isAdmin ? `
        <div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap;align-items:center;">
            ${inMaint
                ? `<span style="color:#fa8231;font-size:.82rem;"><i class="fa-solid fa-wrench"></i> Údržba do ${maintUntil.toLocaleString('cs-CZ')}</span>
                   <button onclick="_setMaintenance('${hostname}', 0)" style="background:transparent;border:1px solid #fa8231;color:#fa8231;padding:3px 10px;border-radius:4px;cursor:pointer;font-size:.8rem;">Ukončit</button>`
                : `<button onclick="_setMaintenance('${hostname}', 30)"  style="background:transparent;border:1px solid var(--border);color:var(--text-muted);padding:3px 10px;border-radius:4px;cursor:pointer;font-size:.8rem;"><i class="fa-solid fa-wrench"></i> Údržba 30 min</button>
                   <button onclick="_setMaintenance('${hostname}', 120)" style="background:transparent;border:1px solid var(--border);color:var(--text-muted);padding:3px 10px;border-radius:4px;cursor:pointer;font-size:.8rem;">2 hod</button>
                   <button onclick="_setMaintenance('${hostname}', 480)" style="background:transparent;border:1px solid var(--border);color:var(--text-muted);padding:3px 10px;border-radius:4px;cursor:pointer;font-size:.8rem;">8 hod</button>`
            }
        </div>` : '';

    const schedMaintHtml = isAdmin ? `
        <div style="font-weight:600;color:var(--accent);margin:14px 0 8px;font-size:.85rem;text-transform:uppercase;letter-spacing:.05em;"><i class="fa-solid fa-calendar-check"></i> Plánovaná okna údržby</div>
        <div id="agent-sched-maint-${hostname}"></div>
        <div style="display:flex;gap:6px;align-items:center;margin-top:6px;flex-wrap:wrap;">
            <input type="text" id="sm-name-${hostname}" placeholder="Název" style="flex:1;min-width:80px;background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:4px;color:var(--text-main);padding:4px 8px;font-size:.8rem;">
            <input type="number" id="sm-start-${hostname}" min="0" max="23" value="2" title="Od (h)" style="width:46px;background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:4px;color:var(--text-main);padding:4px 6px;font-size:.8rem;">
            <span style="color:var(--text-muted);font-size:.8rem;">–</span>
            <input type="number" id="sm-end-${hostname}" min="0" max="23" value="6" title="Do (h)" style="width:46px;background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:4px;color:var(--text-main);padding:4px 6px;font-size:.8rem;">
            <button onclick="_addHostMaintWindow('${hostname}')" style="background:transparent;border:1px solid var(--accent);color:var(--accent);padding:3px 10px;border-radius:4px;cursor:pointer;font-size:.8rem;"><i class="fa-solid fa-plus"></i> Přidat</button>
        </div>` : '';

    return `
        <div style="font-weight:600;color:var(--accent);margin-bottom:10px;font-size:.85rem;text-transform:uppercase;letter-spacing:.05em;">Metadata agenta</div>
        ${metaHtml}
        <div style="font-weight:600;color:var(--accent);margin-bottom:8px;font-size:.85rem;text-transform:uppercase;letter-spacing:.05em;">Aktivní issues</div>
        ${issuesHtml}
        ${groupHtml}
        ${hbHtml}
        ${notesHtml}
        ${maintHtml}
        ${schedMaintHtml}
        ${regenHtml}`;
}

async function _setMaintenance(hostname, minutes) {
    const body = minutes > 0 ? {minutes} : {clear: true};
    const r = await fetch(`/api/agents/${encodeURIComponent(hostname)}/maintenance`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    });
    const d = await r.json();
    if (d.status === 'ok') { openDeviceDetailModal(hostname, 'agent'); loadAgentHealth(); }
    else alert(d.message || 'Chyba');
}

async function _setGroupMaintenance(grpB64, minutes) {
    const grp = decodeURIComponent(escape(atob(grpB64)));
    const body = minutes > 0 ? {minutes} : {clear: true};
    const r = await fetch(`/api/agents/group/${encodeURIComponent(grp)}/maintenance`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    });
    const d = await r.json();
    if (d.status === 'ok') loadAgentHealth();
    else alert(d.message || 'Chyba');
}

async function _loadHostMaintWindows(hostname) {
    const el = document.getElementById(`agent-sched-maint-${hostname}`);
    if (!el) return;
    try {
        const r = await fetch('/api/snooze/rules');
        const d = await r.json();
        const rules = (d.rules || []).filter(rule => {
            if (!rule.hosts || rule.hosts === '*') return false;
            return rule.hosts.split(',').map(h => h.trim().toLowerCase()).includes(hostname.toLowerCase());
        });
        if (!rules.length) {
            el.innerHTML = `<div style="font-size:.78rem;color:var(--text-muted);padding:4px 0;">Žádná plánovaná okna pro tento host.</div>`;
            return;
        }
        el.innerHTML = rules.map(rule => `
            <div style="display:flex;align-items:center;gap:8px;padding:5px 8px;margin-bottom:4px;background:rgba(255,255,255,.03);border:1px solid var(--border);border-radius:4px;font-size:.78rem;">
                <span style="flex:1;">${_escape(rule.name)}</span>
                <span style="color:var(--text-muted);">${String(rule.start_hour).padStart(2,'0')}:00–${String(rule.end_hour).padStart(2,'0')}:00</span>
                <span style="color:var(--text-muted);">${rule.days === '*' ? 'každý den' : rule.days.split(',').map(d => ['Po','Út','St','Čt','Pá','So','Ne'][+d]||d).join(',')}</span>
                <i class="fa-solid fa-trash" style="color:var(--error);cursor:pointer;opacity:.6;" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='.6'" onclick="_deleteHostMaintWindow(${rule.id},'${hostname}')"></i>
            </div>`).join('');
    } catch(e) {
        el.innerHTML = `<div style="font-size:.78rem;color:var(--error);">Chyba načítání.</div>`;
    }
}

async function _addHostMaintWindow(hostname) {
    const name   = (document.getElementById(`sm-name-${hostname}`) || {}).value?.trim();
    const start_h = parseInt((document.getElementById(`sm-start-${hostname}`) || {}).value);
    const end_h   = parseInt((document.getElementById(`sm-end-${hostname}`) || {}).value);
    if (!name) { alert('Zadejte název okna.'); return; }
    const r = await fetch('/api/snooze/rules', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name, start_hour: start_h, end_hour: end_h, channels: '*', days: '*', hosts: hostname}),
    });
    const d = await r.json();
    if (d.status === 'ok') {
        document.getElementById(`sm-name-${hostname}`).value = '';
        await _loadHostMaintWindows(hostname);
    } else {
        alert(d.error || 'Chyba při přidávání.');
    }
}

async function _deleteHostMaintWindow(ruleId, hostname) {
    if (!confirm('Smazat toto okno?')) return;
    await fetch(`/api/snooze/rules/${ruleId}`, {method: 'DELETE'});
    await _loadHostMaintWindows(hostname);
}

async function _saveAgentGroup(hostname) {
    const inp = document.getElementById(`dd-group-${hostname}`);
    if (!inp) return;
    const r = await fetch(`/api/agents/${encodeURIComponent(hostname)}/group`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ group: inp.value.trim() }),
    });
    const d = await r.json();
    inp.style.borderColor = d.status === 'ok' ? 'var(--success)' : 'var(--error)';
    setTimeout(() => { inp.style.borderColor = ''; }, 2000);
    if (d.status === 'ok') loadAgentHealth();
}

async function _saveAgentNotes(hostname) {
    const ta = document.getElementById(`dd-notes-${hostname}`);
    if (!ta) return;
    const r = await fetch(`/api/agents/${encodeURIComponent(hostname)}/notes`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ notes: ta.value }),
    });
    const d = await r.json();
    const msg = d.status === 'ok' ? '✅ Uloženo' : '❌ Chyba';
    ta.style.borderColor = d.status === 'ok' ? 'var(--success)' : 'var(--error)';
    setTimeout(() => { ta.style.borderColor = ''; }, 2000);
}

async function _saveHeartbeatTimeout(hostname) {
    const inp = document.getElementById(`dd-hb-${hostname}`);
    if (!inp) return;
    const val = parseInt(inp.value);
    if (isNaN(val) || val < 30) { inp.style.borderColor = 'var(--error)'; return; }
    const r = await fetch(`/api/agents/${encodeURIComponent(hostname)}/heartbeat-timeout`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({timeout: val}),
    });
    const d = await r.json();
    inp.style.borderColor = d.status === 'ok' ? 'var(--success)' : 'var(--error)';
    setTimeout(() => { inp.style.borderColor = ''; }, 2000);
    if (d.status === 'ok') openDeviceDetailModal(hostname, 'agent');
}

async function _clearHeartbeatTimeout(hostname) {
    await fetch(`/api/agents/${encodeURIComponent(hostname)}/heartbeat-timeout`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({timeout: null}),
    });
    openDeviceDetailModal(hostname, 'agent');
}

async function _regenAgentToken(hostname) {
    if (!confirm(`Opravdu regenerovat token pro ${hostname}? Stávající agent přestane fungovat dokud nedostane nový token.`)) return;
    const r = await fetch(`/api/agents/${encodeURIComponent(hostname)}/regenerate-token`, { method: 'POST' });
    const d = await r.json();
    if (d.status === 'ok') {
        showTokenModal(hostname, d.token);
    } else {
        alert('Chyba: ' + (d.error || 'unknown'));
    }
}

async function _fetchHWSensors(hostname) {
    try {
        const res = await fetch(`/api/sentinel-hw/${hostname}/live`, {signal: AbortSignal.timeout(7000)});
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            return `<p style="color:#7a8494; font-size:.85rem;"><i class="fa-solid fa-triangle-exclamation"></i> ${t('webui_unavailable', {msg: err.message || res.statusText})}</p>`;
        }
        const d = await res.json();
        const rows = [
            [t('state_label'), d.status?.toUpperCase() || '–'],
            [t('api_connection'), (d.connected || d.status === 'online') ? t('connected_status') : t('not_connected_status')],
            [t('light_label'), d.lux != null ? d.lux + ' lux' : '–'],
            [t('presence_label'), d.presence ? t('presence_detected') : t('presence_none')],
            [t('incidents_label'), d.issues_count ?? '–'],
            [t('notifications_label'), d.notify_active ? t('active_status') : '–'],
            [t('name_label'), d.device_name || '–'],
        ];
        return `<table style="width:100%; border-collapse:collapse; font-size:.88rem;">
            ${rows.map(([k,v]) => `<tr style="border-bottom:1px solid #1a1f2e;">
                <td style="padding:5px 0; color:#7a8494; width:40%">${k}</td>
                <td style="padding:5px 0; color:#e2e8f0">${v}</td>
            </tr>`).join('')}
        </table>`;
    } catch(e) {
        return `<p style="color:#7a8494; font-size:.85rem;"><i class="fa-solid fa-triangle-exclamation"></i> ${t('webui_unavailable', {msg: e.message})}</p>`;
    }
}

function closeDeviceDetailModal() {
    const modal = document.getElementById('device-detail-modal');
    if (modal) modal.style.display = 'none';
}

// ─── Issues filter ────────────────────────────────────────────────────────────

function filterIssueCards(query) {
    const body = document.getElementById('dedicated-modal-body');
    if (!body) return;
    const q = query.trim().toLowerCase();
    const isTagFilter = q.startsWith('#');
    const tagQuery = isTagFilter ? q.slice(1) : null;
    body.querySelectorAll('[data-issue-card]').forEach(card => {
        let match;
        if (!q) {
            match = true;
        } else if (isTagFilter) {
            // Match tag pills inside card
            const tags = Array.from(card.querySelectorAll('span[style*="border-radius:10px"]'))
                .map(el => el.textContent.replace('#','').trim().toLowerCase());
            match = tags.some(t => t.includes(tagQuery));
        } else {
            match = card.textContent.toLowerCase().includes(q);
        }
        card.style.display = match ? '' : 'none';
    });
    body.querySelectorAll('[data-group-row]').forEach(row => {
        row.style.display = q ? 'none' : '';
    });
}

// ─── Snooze ───────────────────────────────────────────────────────────────────

function toggleShowSnoozed() {
    _showSnoozed = !_showSnoozed;
    const btn = document.getElementById('show-snoozed-btn');
    if (btn) btn.style.color = _showSnoozed ? 'var(--accent)' : 'var(--text-muted)';
    refreshModalIssuesContent(false);
}

function snoozeIssue(kb64, el) {
    const existing = document.getElementById('snooze-dropdown');
    if (existing) existing.remove();

    const menu = document.createElement('div');
    menu.id = 'snooze-dropdown';
    menu.style.cssText = (
        'position:fixed; background:var(--card-bg,#1e1e2e); border:1px solid var(--border,#333); '
        + 'border-radius:6px; padding:4px 0; z-index:9999; box-shadow:0 4px 16px rgba(0,0,0,0.4); '
        + 'min-width:120px;'
    );

    const rect = el.getBoundingClientRect();
    menu.style.top  = (rect.bottom + 4) + 'px';
    menu.style.left = (rect.left - 60) + 'px';

    // 384: Snooze presets — přidány "do rána" a "do pondělí"
    const now = new Date();
    const tomorrow8 = new Date(now); tomorrow8.setDate(tomorrow8.getDate()+1); tomorrow8.setHours(8,0,0,0);
    const hoursToMorning = Math.max(1, Math.round((tomorrow8-now)/3600000));
    const daysToMonday = (8 - now.getDay()) % 7 || 7;
    const monday8 = new Date(now); monday8.setDate(monday8.getDate()+daysToMonday); monday8.setHours(8,0,0,0);
    const hoursToMonday = Math.max(1, Math.round((monday8-now)/3600000));

    [[1,'1 hodina'], [4,'4 hodiny'], [hoursToMorning,'Do rána (8:00)'], [24,'24 hodin'], [hoursToMonday,'Do pondělí'], [72,'72 hodin']].forEach(([h, label]) => {
        const item = document.createElement('div');
        item.textContent = label;
        item.style.cssText = 'padding:6px 14px; cursor:pointer; font-size:0.88em; color:var(--text-main);';
        item.onmouseenter = () => item.style.background = 'rgba(255,255,255,0.07)';
        item.onmouseleave = () => item.style.background = '';
        item.onclick = async () => {
            menu.remove();
            await fetch('/api/issues/snooze', {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({key: kb64, hours: h})
            });
            refreshModalIssuesContent(false);
        };
        menu.appendChild(item);
    });

    document.body.appendChild(menu);
    const closeMenu = (e) => { if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener('click', closeMenu); } };
    setTimeout(() => document.addEventListener('click', closeMenu), 10);
}

async function unsnoozeIssue(kb64) {
    await fetch('/api/issues/unsnooze', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({key: kb64})
    });
    refreshModalIssuesContent(false);
}

// ─── Issue Comments ───────────────────────────────────────────────────────────

async function openIssueCommentsModal(kb64) {
    _commentsKey = kb64;
    document.getElementById('comments-modal').style.display = 'flex';
    if (currentOpenChannel) _pushBreadcrumb('comments-modal', 'Issues', () => openIssuesModal(currentOpenChannel));
    try {
        const raw = atob(kb64);
        document.getElementById('comments-issue-key').textContent = raw;
    } catch { document.getElementById('comments-issue-key').textContent = kb64; }
    document.getElementById('comments-msg').textContent = '';
    document.getElementById('comments-input').value = '';
    await _loadComments(kb64);
}

function closeIssueCommentsModal() {
    document.getElementById('comments-modal').style.display = 'none';
    _commentsKey = null;
    _clearBreadcrumb('comments-modal');
}

async function _loadComments(kb64) {
    const thread = document.getElementById('comments-thread');
    thread.innerHTML = `<div style="text-align:center; padding:16px; color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>`;
    try {
        const r = await fetch(`/api/issues/${encodeURIComponent(kb64)}/comments`);
        const d = await r.json();
        const comments = d.comments || [];
        if (!comments.length) {
            thread.innerHTML = `<div style="text-align:center; padding:20px; color:var(--text-muted); font-size:0.88em;">${t('comments_no_comments')}</div>`;
            return;
        }
        thread.innerHTML = comments.map(c => {
            const ts = c.created_at ? c.created_at.slice(0,16) : '';
            return `<div style="margin-bottom:12px; padding:10px 12px; background:var(--panel); border-radius:6px; border:1px solid var(--border);">
                <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:6px;">
                    <span style="font-size:0.8em; font-weight:600; color:var(--accent);">${_escape(c.author)}</span>
                    <div style="display:flex; align-items:center; gap:8px;">
                        <span style="font-size:0.72em; color:var(--text-muted);">${ts}</span>
                        <i class="fa-solid fa-trash" style="font-size:0.75em; color:var(--error); opacity:0.5; cursor:pointer;"
                           onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.5'"
                           onclick="deleteIssueComment(${c.id}, '${kb64}')"></i>
                    </div>
                </div>
                <div style="font-size:0.88em; white-space:pre-wrap; word-break:break-word;">${_escape(c.text)}</div>
            </div>`;
        }).join('');
        thread.scrollTop = thread.scrollHeight;
        // Update badge on the card
        _updateCommentBadge(kb64, comments.length);
    } catch(e) {
        thread.innerHTML = `<div style="text-align:center; padding:16px; color:var(--error); font-size:0.85em;">${t('comments_load_error')}</div>`;
    }
}

async function addIssueComment() {
    if (!_commentsKey) return;
    const input = document.getElementById('comments-input');
    const msgEl = document.getElementById('comments-msg');
    const text = input.value.trim();
    if (!text) { msgEl.style.color = 'var(--error)'; msgEl.textContent = t('comments_empty_error'); return; }
    try {
        const r = await fetch(`/api/issues/${encodeURIComponent(_commentsKey)}/comments`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({text})
        });
        const d = await r.json();
        if (d.status === 'ok') {
            input.value = '';
            msgEl.textContent = '';
            await _loadComments(_commentsKey);
        } else {
            msgEl.style.color = 'var(--error)';
            msgEl.textContent = d.error || t('comments_add_error');
        }
    } catch(e) {
        msgEl.style.color = 'var(--error)';
        msgEl.textContent = t('comments_add_error');
    }
}

async function deleteIssueComment(id, kb64) {
    if (!confirm(t('comments_delete_confirm'))) return;
    await fetch(`/api/issues/comments/${id}`, {method: 'DELETE'});
    await _loadComments(kb64);
}

function _updateCommentBadge(kb64, count) {
    const badge = document.getElementById(`cbadge-${kb64}`);
    if (!badge) return;
    const icon = badge.querySelector('i');
    if (count > 0) {
        badge.style.color = 'var(--accent)';
        badge.innerHTML = `<i class="fa-solid fa-comment-dots"></i><span style="font-size:0.7em; vertical-align:top; margin-left:1px;">${count}</span>`;
    } else {
        badge.style.color = 'var(--text-muted)';
        badge.innerHTML = `<i class="fa-regular fa-comment-dots"></i>`;
    }
}

async function loadCommentCounts() {
    try {
        const r = await fetch('/api/issues/comment_counts');
        const counts = await r.json();
        Object.entries(counts).forEach(([kb64, cnt]) => _updateCommentBadge(kb64, cnt));
    } catch { /* silent */ }
}

// ─── Bulk select ──────────────────────────────────────────────────────────────

function toggleBulkMode() {
    _bulkMode = !_bulkMode;
    _bulkSelected.clear();
    const bar = document.getElementById('bulk-action-bar');
    const btn = document.getElementById('bulk-mode-btn');
    if (bar) bar.style.display = _bulkMode ? 'flex' : 'none';
    if (btn) {
        btn.style.borderColor = _bulkMode ? 'var(--accent)' : 'var(--border)';
        btn.style.color = _bulkMode ? 'var(--accent)' : 'var(--text-muted)';
    }
    _injectBulkCheckboxes();
}

function _injectBulkCheckboxes() {
    const body = document.getElementById('dedicated-modal-body');
    if (!body) return;
    body.querySelectorAll('[data-issue-card]').forEach(card => {
        const existing = card.querySelector('.bulk-cb-wrap');
        if (_bulkMode && !existing) {
            const kb64 = card.dataset.issueKey || '';
            const wrap = document.createElement('div');
            wrap.className = 'bulk-cb-wrap';
            wrap.style.cssText = 'display:flex;align-items:center;padding:0 8px 0 4px;flex-shrink:0;';
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.style.cssText = 'width:16px;height:16px;cursor:pointer;';
            cb.checked = _bulkSelected.has(kb64);
            cb.onchange = () => {
                if (cb.checked) _bulkSelected.add(kb64); else _bulkSelected.delete(kb64);
                const cnt = document.getElementById('bulk-count');
                if (cnt) cnt.textContent = t('selected_count', {count: _bulkSelected.size});
            };
            wrap.appendChild(cb);
            card.insertBefore(wrap, card.firstChild);
        } else if (!_bulkMode && existing) {
            existing.remove();
        }
    });
}

function bulkSelectAll() {
    const body = document.getElementById('dedicated-modal-body');
    if (!body) return;
    body.querySelectorAll('[data-issue-card] input[type=checkbox]').forEach(cb => {
        cb.checked = true;
        const kb64 = cb.closest('[data-issue-card]')?.dataset.issueKey || '';
        if (kb64) _bulkSelected.add(kb64);
    });
    const cnt = document.getElementById('bulk-count');
    if (cnt) cnt.textContent = t('selected_count', {count: _bulkSelected.size});
}

function bulkIgnore() {
    if (_bulkSelected.size === 0) return;
    _bulkSelected.forEach(kb64 => triggerAction(`ignore_key ${kb64}`));
    _bulkSelected.clear();
    toggleBulkMode();
    setTimeout(() => refreshModalIssuesContent(false), 400);
}

function bulkDelete() {
    if (_bulkSelected.size === 0) return;
    _bulkSelected.forEach(kb64 => triggerAction(`delete_key ${kb64}`));
    _bulkSelected.clear();
    toggleBulkMode();
    setTimeout(() => refreshModalIssuesContent(false), 400);
}

// 208: Bulk severity + bulk assign
async function bulkSetSeverity() {
    if (_bulkSelected.size === 0) return;
    const sel = document.getElementById('bulk-severity-sel');
    const severity = sel ? sel.value : '';
    if (!severity) return;
    const keys = [..._bulkSelected];
    try {
        await fetch('/api/issues/bulk_severity', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({keys, severity})});
    } catch(e) {}
    _bulkSelected.clear(); toggleBulkMode();
    setTimeout(() => refreshModalIssuesContent(false), 200);
}

async function bulkAssign() {
    if (_bulkSelected.size === 0) return;
    const inp = document.getElementById('bulk-assign-inp');
    const username = inp ? inp.value.trim() : '';
    if (!username) return;
    const keys = [..._bulkSelected];
    try {
        await fetch('/api/issues/bulk_assign', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({keys, username})});
    } catch(e) {}
    if (inp) inp.value = '';
    _bulkSelected.clear(); toggleBulkMode();
    setTimeout(() => refreshModalIssuesContent(false), 200);
}

// ─── KB Reindex + Upload ──────────────────────────────────────────────────────

// 217: KB fulltext search
async function _kbSearch() {
    const inp = document.getElementById('kb-search-inp');
    const res = document.getElementById('kb-search-results');
    if (!inp || !res) return;
    const q = inp.value.trim();
    if (!q) return;
    res.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Hledám…';
    try {
        const r = await fetch(`/api/kb/search?q=${encodeURIComponent(q)}`);
        const d = await r.json();
        if (d.error) { res.innerHTML = `<span style="color:var(--text-muted);">${d.error}</span>`; return; }
        const results = d.results || [];
        if (!results.length) { res.innerHTML = `<span style="color:var(--text-muted);">Žádné výsledky pro „${_escape(q)}"</span>`; return; }
        res.innerHTML = results.map(r =>
            `<div style="margin-bottom:10px;border-left:3px solid var(--accent);padding-left:8px;">
                <div style="font-size:.78em;color:var(--accent);font-weight:700;margin-bottom:4px;">${_escape(r.file)}</div>
                ${r.hits.map(h => `<div style="color:var(--text-muted);margin-bottom:2px;">
                    <span style="color:#555;font-size:.72em;">L${h.line}</span> ${_escape(h.text)}
                </div>`).join('')}
             </div>`
        ).join('');
    } catch(e) { res.innerHTML = `<span style="color:var(--error);">Chyba: ${_escape(String(e))}</span>`; }
}

async function _kbLoadFiles() {
    const el = document.getElementById('kb-files-list');
    if (!el) return;
    try {
        const r = await fetch('/api/kb/files');
        const d = await r.json();
        const files = d.files || [];
        if (!files.length) {
            el.innerHTML = `<span style="color:var(--text-muted);">Žádné soubory</span>`;
            return;
        }
        const dirLabels = {'docs': 'docs', 'admindocs': 'admindocs', 'uploads': 'uploads'};
        const grouped = {};
        files.forEach(f => {
            if (!grouped[f.dir]) grouped[f.dir] = [];
            grouped[f.dir].push(f);
        });
        el.innerHTML = Object.entries(grouped).map(([dir, items]) => `
            <div style="margin-bottom:10px;">
                <div style="font-size:0.75em;color:var(--accent);text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px;">${dirLabels[dir] || dir}</div>
                ${items.map(f => `
                <div style="display:flex;justify-content:space-between;align-items:center;padding:4px 8px;background:rgba(255,255,255,0.02);border-radius:4px;margin-bottom:2px;">
                    <span style="font-family:monospace;font-size:0.85em;">${_escape(f.name)}</span>
                    <span style="display:flex;align-items:center;gap:8px;">
                        <span style="color:var(--text-muted);font-size:0.78em;">${f.size_str}</span>
                        ${dir === 'uploads' ? `<i class="fa-solid fa-trash" style="cursor:pointer;color:var(--error);font-size:0.85em;" onclick="_kbDelete('${_escape(f.name)}')"></i>` : ''}
                    </span>
                </div>`).join('')}
            </div>`).join('');
    } catch(e) {
        el.innerHTML = `<span style="color:var(--error);">Chyba načtení</span>`;
    }
}

async function _kbUpload(file) {
    if (!file) return;
    const msg = document.getElementById('kb-upload-msg');
    if (msg) msg.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Nahrávám ${_escape(file.name)}…`;
    const fd = new FormData();
    fd.append('file', file);
    try {
        const r = await fetch('/api/kb/upload', {method: 'POST', body: fd});
        const d = await r.json();
        if (d.status === 'ok') {
            if (msg) msg.innerHTML = `<span style="color:var(--success);">✓ Nahráno: ${_escape(d.filename)}</span>`;
            _kbLoadFiles();
        } else {
            if (msg) msg.innerHTML = `<span style="color:var(--error);">✗ ${_escape(d.message || 'Chyba')}</span>`;
        }
    } catch(e) {
        if (msg) msg.innerHTML = `<span style="color:var(--error);">✗ Chyba spojení</span>`;
    }
    const inp = document.getElementById('kb-upload-input');
    if (inp) inp.value = '';
}

function _kbDrop(e) {
    e.preventDefault();
    document.getElementById('kb-drop-zone').style.borderColor = 'var(--border)';
    const file = e.dataTransfer?.files?.[0];
    if (file) _kbUpload(file);
}

async function _kbDelete(filename) {
    if (!confirm(`Smazat soubor '${filename}'?`)) return;
    const r = await fetch('/api/kb/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({filename})});
    const d = await r.json();
    if (d.status === 'ok') _kbLoadFiles();
    else alert(d.message || 'Chyba');
}

async function triggerKBReindex() {
    const btn = document.getElementById('kb-reindex-btn');
    if (btn) { btn.disabled = true; btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> ${t('kb_reindexing')}`; }
    try {
        const r = await fetch('/api/kb/reindex', { method: 'POST' });
        const d = await r.json();
        if (d.status === 'ok') {
            if (btn) btn.innerHTML = `<i class="fa-solid fa-check"></i> ${t('kb_reindex_started')}`;
            setTimeout(() => { if (btn) { btn.disabled = false; btn.innerHTML = `<i class="fa-solid fa-database"></i> ${t('kb_reindex_label')}`; } }, 5000);
        } else {
            alert(d.message || t('kb_reindexing'));
            if (btn) { btn.disabled = false; btn.innerHTML = `<i class="fa-solid fa-database"></i> ${t('kb_reindex_label')}`; }
        }
    } catch (e) {
        if (btn) { btn.disabled = false; btn.innerHTML = `<i class="fa-solid fa-database"></i> ${t('kb_reindex_label')}`; }
    }
}

// ─── Print Report modal ───────────────────────────────────────────────────────

async function openReportModal() {
    document.getElementById('report-modal').style.display = 'flex';
    const plList = document.getElementById('report-plugins-list');
    plList.innerHTML = `<span style="color:var(--text-muted);font-size:.82em;"><i class="fa-solid fa-spinner fa-spin"></i> ${t('loading_dots')}</span>`;
    try {
        const r = await fetch('/api/issues/meta');
        const d = await r.json();

        // Rebuild channel checkboxes from live data
        const chWrap = document.getElementById('report-channels');
        const allChannels = ['INFRA','SECURITY','AGENT','ROOT','LOGIN','ICINGA','GENERAL'];
        const liveChannels = new Set(d.channels || []);
        chWrap.innerHTML = allChannels.map(ch => {
            const has = liveChannels.has(ch);
            return `<label class="report-cb-label" ${!has ? 'style="opacity:.45;"':''}>
                <input type="checkbox" value="${ch}" ${has ? 'checked' : ''}> ${ch}
                ${has ? `<span style="font-size:.75em;color:var(--text-muted);"></span>` : ''}
            </label>`;
        }).join('');

        // Rebuild status checkboxes
        const liveStatuses = new Set(d.statuses || []);
        document.querySelectorAll('#report-modal input[value="active"], #report-modal input[value="validating"], #report-modal input[value="new"]')
            .forEach(cb => { cb.checked = liveStatuses.has(cb.value) || liveStatuses.size === 0; });

        // Plugin checkboxes
        if (!d.plugins || d.plugins.length === 0) {
            plList.innerHTML = `<span style="color:var(--text-muted);font-size:.82em;">${t('no_active_plugins_issues')}</span>`;
        } else {
            plList.innerHTML = d.plugins.map(p =>
                `<label class="report-cb-label"><input type="checkbox" value="${p}" checked> ${p}</label>`
            ).join('');
        }
    } catch(e) {
        plList.innerHTML = `<span style="color:var(--error);font-size:.82em;">${t('data_load_failed')}</span>`;
    }
}

function closeReportModal() {
    document.getElementById('report-modal').style.display = 'none';
}

function reportSelectAll(state) {
    document.querySelectorAll('#report-channels input, #report-plugins-list input, #report-modal .modal-body input[type=checkbox]')
        .forEach(cb => { cb.checked = state; });
}

function _reportPreset(days) {
    const to = new Date();
    const from = new Date();
    from.setDate(from.getDate() - days + 1);
    const fmt = d => d.toISOString().slice(0, 10);
    const fEl = document.getElementById('report-date-from');
    const tEl = document.getElementById('report-date-to');
    if (fEl) fEl.value = fmt(from);
    if (tEl) tEl.value = fmt(to);
}

function openFilteredReport() {
    const channels = [...document.querySelectorAll('#report-channels input:checked')].map(c => c.value);
    const statuses = [...document.querySelectorAll('#report-modal .modal-body input[type=checkbox][value="active"],' +
        '#report-modal .modal-body input[type=checkbox][value="validating"],' +
        '#report-modal .modal-body input[type=checkbox][value="new"]')].filter(c => c.checked).map(c => c.value);
    const plugins  = [...document.querySelectorAll('#report-plugins-list input:checked')].map(c => c.value);
    const host     = document.getElementById('report-host-filter')?.value.trim() || '';
    const dateFrom = document.getElementById('report-date-from')?.value || '';
    const dateTo   = document.getElementById('report-date-to')?.value || '';

    const params = new URLSearchParams();
    if (channels.length) params.set('channels', channels.join(','));
    if (statuses.length) params.set('statuses', statuses.join(','));
    if (plugins.length)  params.set('plugins',  plugins.join(','));
    if (host)            params.set('host', host);
    if (dateFrom)        params.set('from', dateFrom);
    if (dateTo)          params.set('to', dateTo);

    window.open(`/api/export/incidents.html?${params.toString()}`, '_blank');
    closeReportModal();
}


// 144: Health/alert sparkline SVG for agent detail
function _agentHealthSparkline(history) {
    if (!history.length) return '';
    const W = 220, H = 40, PAD = 2;
    const counts = history.map(h => h.count);
    const maxV = Math.max(1, ...counts);
    const pts = counts.map((v, i) => {
        const x = PAD + (i / (counts.length - 1)) * (W - PAD * 2);
        const y = PAD + (1 - v / maxV) * (H - PAD * 2);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    const hasAlerts = counts.some(c => c > 0);
    const color = hasAlerts ? '#f97316' : '#22c55e';
    const last7 = counts.slice(-7);
    const last7label = last7.join(' ');
    return `<div title="Denní počty alertů (30 dní): ${last7label}">
        <svg width="${W}" height="${H}" style="display:block;width:100%;height:${H}px;">
            <polyline points="${pts.join(' ')}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>
            <polyline points="${PAD},${H-PAD} ${pts.join(' ')} ${W-PAD},${H-PAD}" fill="${color}" fill-opacity="0.1" stroke="none"/>
        </svg>
        <div style="font-size:.68em;color:var(--text-muted);text-align:right;">${history[0]?.day?.slice(5)||''} → dnes · max ${maxV} alertů/den</div>
    </div>`;
}

// 143: Ping / port-check agent
async function _agentPing(hostname) {
    const btn = document.getElementById(`ping-btn-${hostname}`);
    if (btn) { btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>'; btn.disabled = true; }
    try {
        const r = await fetch(`/api/agents/${encodeURIComponent(hostname)}/ping`, {method: 'POST'});
        const d = await r.json();
        const ports = d.ports || {};
        const icmp = d.icmp === true ? '✓' : d.icmp === false ? '✗' : '?';
        const rows = Object.entries(ports).map(([n, v]) =>
            `<span style="color:${v.open?'var(--success)':'var(--text-muted)'};">${v.open?'✓':'✗'} ${n}${v.rtt_ms?` ${v.rtt_ms}ms`:''}</span>`
        ).join(' &nbsp;');
        const result = `<div id="ping-result-${hostname}" style="background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:8px 12px;margin-top:10px;font-size:.82em;">
            <b>Ping ${_escape(d.ip||hostname)}</b> &nbsp;
            <span style="color:${d.icmp?'var(--success)':'var(--text-muted)'};">ICMP ${icmp}</span> &nbsp; ${rows}
        </div>`;
        // Insert at top of detail body
        const body = document.getElementById('agent-detail-body');
        const existing = document.getElementById(`ping-result-${hostname}`);
        if (existing) existing.remove();
        body.insertAdjacentHTML('afterbegin', result);
        if (btn) { btn.innerHTML = '<i class="fa-solid fa-satellite-dish"></i> Ping'; btn.disabled = false; btn.style.color = 'var(--success)'; setTimeout(()=>{ btn.style.color='var(--text-muted)'; }, 3000); }
    } catch(e) {
        if (btn) { btn.innerHTML = '<i class="fa-solid fa-satellite-dish"></i> Ping'; btn.disabled = false; }
    }
}
