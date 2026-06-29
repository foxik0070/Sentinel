// ─── Dashboard ────────────────────────────────────────────────────────────────

let _dashChart1 = null, _dashChart2 = null;

async function openDashboard() {
    document.getElementById('dashboard-modal').style.display = 'flex';
    await loadDashboard();
}

function closeDashboard() {
    document.getElementById('dashboard-modal').style.display = 'none';
    if (_dashChart1) { _dashChart1.destroy(); _dashChart1 = null; }
    if (_dashChart2) { _dashChart2.destroy(); _dashChart2 = null; }
}

async function loadDashboard() {
    const body = document.getElementById('dashboard-body');
    body.innerHTML = `<div style="text-align:center; padding:40px; color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i></div>`;
    if (_dashChart1) { _dashChart1.destroy(); _dashChart1 = null; }
    if (_dashChart2) { _dashChart2.destroy(); _dashChart2 = null; }
    try {
        const [dr, tl] = await Promise.all([
            fetch('/api/dashboard').then(r => r.json()),
            fetch('/api/alerts/timeline?days=7').then(r => r.json()),
        ]);
        _renderDashboard(dr, tl);
        const vEl = document.getElementById('dash-version');
        if (vEl) vEl.textContent = `v${dr.version || ''}`;
    } catch(e) {
        body.innerHTML = `<div style="padding:20px; color:var(--error); text-align:center;">${t('data_load_failed')}</div>`;
    }
}

function _dashStatCard(icon, label, value, color, sub) {
    return `<div style="background:var(--panel); border:1px solid var(--border); border-radius:6px; padding:14px 16px; flex:1; min-width:110px;">
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:6px;">
            <i class="${icon}" style="color:${color}; font-size:1.1em;"></i>
            <span style="font-size:0.72em; color:var(--text-muted); text-transform:uppercase; letter-spacing:.4px;">${label}</span>
        </div>
        <div style="font-size:1.6em; font-weight:700; color:${color}; line-height:1;">${value}</div>
        ${sub ? `<div style="font-size:0.72em; color:var(--text-muted); margin-top:4px;">${sub}</div>` : ''}
    </div>`;
}

function _sparklineSvg(data, w=100, h=28, color='#4da6ff') {
    if (!data || data.length < 2) return `<div style="height:${h}px;"></div>`;
    const min = Math.min(...data), max = Math.max(...data);
    const range = max - min || 1;
    const pts = data.map((v, i) => {
        const x = ((i / (data.length - 1)) * (w - 2) + 1).toFixed(1);
        const y = (h - 1 - ((v - min) / range) * (h - 2)).toFixed(1);
        return `${x},${y}`;
    }).join(' ');
    return `<svg width="${w}" height="${h}" style="display:block;overflow:visible;">
        <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
    </svg>`;
}

function _barPct(pct) {
    const c = pct > 90 ? 'var(--error)' : pct > 70 ? 'var(--warning)' : 'var(--success)';
    return `<div style="height:4px; background:rgba(255,255,255,0.08); border-radius:2px; margin-top:4px;">
        <div style="height:100%; width:${pct}%; background:${c}; border-radius:2px; transition:width 0.4s;"></div>
    </div>`;
}

// 135: Collapsible dashboard widgets
function _dashWidget(id, icon, title, content, style) {
    if (localStorage.getItem(`dash_hide_${id}`) === '1') return '';
    const collapsed = localStorage.getItem(`dash_w_${id}`) === '1';
    return `<div style="background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:12px;${style||''}">
        <div style="display:flex;justify-content:space-between;align-items:center;cursor:pointer;${collapsed?'':'margin-bottom:8px;'}" onclick="_toggleDashWidget('${id}')">
            <div style="font-size:.72em;color:var(--text-muted);text-transform:uppercase;letter-spacing:.4px;user-select:none;">
                <i class="fa-solid fa-${icon}" style="margin-right:4px;opacity:.7;"></i>${title}
            </div>
            <i id="dash-chev-${id}" class="fa-solid fa-chevron-${collapsed?'down':'up'}" style="font-size:.65em;color:var(--text-muted);transition:transform .2s;"></i>
        </div>
        <div id="dash-wb-${id}" style="display:${collapsed?'none':''};">${content}</div>
    </div>`;
}
// 9: Nastavení viditelnosti widgetů dashboardu
const _DASH_WIDGETS = [
    {id:'sys',   label:'Systém'},
    {id:'temp',  label:'Teploty hostů'},
    {id:'charts',label:'Trend / Donut'},
    {id:'plugins',label:'Top pluginy'},
    {id:'recent', label:'Nedávné incidenty'},
];
function _dashWidgetSettings() {
    const existing = document.getElementById('dash-settings-panel');
    if (existing) { existing.remove(); return; }
    const body = document.getElementById('dashboard-body');
    if (!body) return;
    const panel = document.createElement('div');
    panel.id = 'dash-settings-panel';
    panel.style.cssText = 'background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:12px 16px;margin-bottom:12px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;';
    panel.innerHTML = `<span style="font-size:.8em;color:var(--text-muted);font-weight:600;margin-right:4px;">Widgety:</span>` +
        _DASH_WIDGETS.map(w => {
            const hidden = localStorage.getItem(`dash_hide_${w.id}`) === '1';
            return `<label style="display:inline-flex;align-items:center;gap:5px;font-size:.82em;cursor:pointer;">
                <input type="checkbox" ${hidden?'':'checked'} onchange="_dashWidgetToggleHide('${w.id}',this.checked)">
                ${_escape(w.label)}
            </label>`;
        }).join('') +
        `<button onclick="_dashWidgetApply()" style="margin-left:auto;padding:3px 10px;background:var(--accent);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.82em;">Použít</button>`;
    body.insertBefore(panel, body.firstChild);
}
function _dashWidgetToggleHide(id, visible) {
    localStorage.setItem(`dash_hide_${id}`, visible ? '0' : '1');
}
function _dashWidgetApply() {
    const panel = document.getElementById('dash-settings-panel');
    if (panel) panel.remove();
    loadDashboard();
}

function _toggleDashWidget(id) {
    const body = document.getElementById(`dash-wb-${id}`);
    const chev = document.getElementById(`dash-chev-${id}`);
    if (!body) return;
    const nowCollapsed = body.style.display === 'none';
    body.style.display = nowCollapsed ? '' : 'none';
    body.previousElementSibling.style.marginBottom = nowCollapsed ? '8px' : '';
    if (chev) chev.className = `fa-solid fa-chevron-${nowCollapsed ? 'up' : 'down'}`;
    localStorage.setItem(`dash_w_${id}`, nowCollapsed ? '0' : '1');
}

function _renderDashboard(d, tl) {
    const body = document.getElementById('dashboard-body');
    const iss = d.issues || {};
    const agt = d.agents || {};
    const channelColors = {INFRA:'#0078d4',SECURITY:'#dc3545',AGENT:'#28a745',ROOT:'#ffc107',LOGIN:'#6f42c1',GENERAL:'#888'};

    // ── Stat cards ─────────────────────────────────────────────────────────
    const alertColor = iss.total > 0 ? 'var(--error)' : 'var(--success)';
    const agentSub = `${agt.online} ${t('dash_online')} / ${agt.offline} ${t('dash_offline')}`;
    const cards = [
        _dashStatCard('fa-solid fa-triangle-exclamation', t('dash_total_alerts'), iss.total, alertColor,
            `INFRA ${iss.infra} · AGENT ${iss.agent} · SEC ${iss.security}`),
        _dashStatCard('fa-solid fa-pause-circle', t('dash_snoozed'), iss.snoozed || 0, 'var(--text-muted)', ''),
        _dashStatCard('fa-solid fa-server', t('dash_agents'), agt.total, agt.online > 0 ? 'var(--success)' : 'var(--text-muted)', agentSub),
        _dashStatCard('fa-solid fa-robot', t('dash_pending'), d.pending_actions || 0, d.pending_actions > 0 ? 'var(--warning)' : 'var(--text-muted)', `${t('dash_ai_queue')}: ${d.ai_queue}`),
        _dashStatCard('fa-solid fa-bolt', t('dash_ai_latency'), d.ai_latency || 'N/A', 'var(--accent)', `${d.ai_requests || 0} ${t('dash_ai_requests')}`),
        _dashStatCard('fa-solid fa-clock-rotate-left', t('dash_uptime'), d.uptime || '-', 'var(--text-main)', `v${d.version || ''}`),
    ];

    // ── System mini-bars ───────────────────────────────────────────────────
    const sysCards = [
        { label: t('dash_cpu'), pct: d.cpu_pct || 0 },
        { label: t('dash_ram'), pct: d.ram_pct || 0 },
        { label: t('dash_disk'), pct: d.disk_pct || 0 },
    ].map(s => `<div style="background:var(--panel); border:1px solid var(--border); border-radius:6px; padding:10px 14px; flex:1; min-width:80px;">
        <div style="font-size:0.72em; color:var(--text-muted); text-transform:uppercase;">${s.label}</div>
        <div style="font-size:1.2em; font-weight:700; margin:3px 0;">${s.pct}%</div>
        ${_barPct(s.pct)}
    </div>`).join('');

    // ── Temperature sparklines ─────────────────────────────────────────────
    const sparks = (d.sparklines || []);
    const sparksHtml = sparks.length ? `
    <div style="margin-bottom:12px;">
        <div style="font-size:0.72em; color:var(--text-muted); text-transform:uppercase; letter-spacing:.4px; margin-bottom:8px;">
            <i class="fa-solid fa-temperature-half" style="color:#fa8231;margin-right:4px;"></i>${t('dash_temp_sparklines') || 'Teploty hostů'}
        </div>
        <div style="display:flex; gap:8px; flex-wrap:wrap;">
            ${sparks.map(s => {
                const temp = s.latest;
                const color = temp >= 75 ? '#dc3545' : temp >= 60 ? '#ffc107' : '#4da6ff';
                return `<div style="background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:8px 10px;min-width:120px;flex:1;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                        <div style="font-size:0.78em;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:70%;" title="${_escape(s.host)}">${_escape(s.host)}</div>
                        <div style="font-size:0.9em;font-weight:700;color:${color};">${temp}°</div>
                    </div>
                    ${_sparklineSvg(s.history, 100, 28, color)}
                </div>`;
            }).join('')}
        </div>
    </div>` : '';

    // ── Charts ─────────────────────────────────────────────────────────────
    const chartsHtml = `
    <div style="display:grid; grid-template-columns:2fr 1fr; gap:12px; margin-bottom:14px;">
        <div style="background:var(--panel); border:1px solid var(--border); border-radius:6px; padding:12px;">
            <div style="font-size:0.72em; color:var(--text-muted); text-transform:uppercase; letter-spacing:.4px; margin-bottom:8px;">${t('dash_trend')}</div>
            <div style="position:relative; height:140px;"><canvas id="dash-chart-trend"></canvas></div>
        </div>
        <div style="background:var(--panel); border:1px solid var(--border); border-radius:6px; padding:12px;">
            <div style="font-size:0.72em; color:var(--text-muted); text-transform:uppercase; letter-spacing:.4px; margin-bottom:8px;">${t('dash_channel_dist')}</div>
            <div style="position:relative; height:140px;"><canvas id="dash-chart-donut"></canvas></div>
        </div>
    </div>`;

    // ── Top plugins + Recent issues ────────────────────────────────────────
    const plugins = (d.top_plugins || []).slice(0, 5);
    const pluginsHtml = plugins.length
        ? plugins.map(p => `
            <div style="display:flex; justify-content:space-between; align-items:center; padding:5px 0; border-bottom:1px solid var(--border);">
                <div style="font-size:0.83em; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:70%;">${_escape(p.plugin)}</div>
                <div style="font-size:0.83em; color:${p.today>0?'var(--error)':'var(--text-muted)'}; font-weight:${p.today>0?'700':'400'}; flex-shrink:0;">
                    ${p.today} / ${p.total}
                </div>
            </div>`).join('')
        : `<div style="padding:10px 0; color:var(--text-muted); font-size:0.83em;">${t('dash_no_plugins')}</div>`;

    const recent = (d.recent_issues || []).slice(0, 6);
    const recentHtml = recent.length
        ? recent.map(r => {
            const ch = (r.channel || '').toUpperCase();
            const bc = channelColors[ch] || '#888';
            return `<div style="padding:5px 0; border-bottom:1px solid var(--border); display:flex; gap:8px; align-items:baseline;">
                <span style="font-size:0.68em; background:${bc}33; color:${bc}; padding:1px 5px; border-radius:3px; flex-shrink:0; font-weight:600;">${ch}</span>
                <span style="font-size:0.8em; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                    <b>${_escape(r.host)}</b>: ${_escape((r.last_line||'').slice(0,60))}
                </span>
            </div>`;
        }).join('')
        : `<div style="padding:10px 0; color:var(--text-muted); font-size:0.83em;">${t('dash_no_issues')}</div>`;

    body.innerHTML = `
        <div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:12px;">${cards.join('')}</div>
        ${_dashWidget('sys', 'microchip', 'Systém', `<div style="display:flex;gap:10px;">${sysCards}</div>`, 'margin-bottom:12px;')}
        ${sparks.length ? _dashWidget('temp', 'temperature-half', t('dash_temp_sparklines')||'Teploty hostů', `<div style="display:flex;gap:8px;flex-wrap:wrap;">${sparks.map(s=>{const temp=s.latest;const color=temp>=75?'#dc3545':temp>=60?'#ffc107':'#4da6ff';return`<div style="background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px 10px;min-width:120px;flex:1;"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;"><div style="font-size:.78em;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:70%;" title="${_escape(s.host)}">${_escape(s.host)}</div><div style="font-size:.9em;font-weight:700;color:${color};">${temp}°</div></div>${_sparklineSvg(s.history,100,28,color)}</div>`;}).join('')}</div>`, 'margin-bottom:12px;') : ''}
        ${_dashWidget('charts', 'chart-line', t('dash_trend'), `<div style="display:grid;grid-template-columns:2fr 1fr;gap:12px;"><div style="position:relative;height:140px;"><canvas id="dash-chart-trend"></canvas></div><div style="position:relative;height:140px;"><canvas id="dash-chart-donut"></canvas></div></div>`, 'margin-bottom:12px;')}
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            ${_dashWidget('plugins', 'puzzle-piece', t('dash_top_plugins'), pluginsHtml)}
            ${_dashWidget('recent', 'clock-rotate-left', t('dash_recent'), recentHtml)}
        </div>
        <div id="dash-flapping-widget" style="margin-top:12px;"></div>
        <div id="dash-health-trend" style="margin-top:12px;"></div>`;
    // 302: Async načtení flapping issues widgetu
    _loadFlappingWidget();
    // 318: Health snapshot trend
    _loadHealthTrend();

    // Build trend bar chart
    const heatmap = tl.heatmap || [];
    const byChannel = tl.by_channel || [];
    const allDays = [];
    const now = new Date();
    for (let i = 6; i >= 0; i--) {
        const d2 = new Date(now); d2.setDate(d2.getDate() - i);
        allDays.push(d2.toISOString().slice(0,10));
    }
    const channels = [...new Set(byChannel.map(r => r.channel))];
    const trendDatasets = channels.map(ch => ({
        label: ch, borderWidth: 1,
        backgroundColor: (channelColors[ch] || '#888') + 'bb',
        data: allDays.map(day => { const f = byChannel.find(r => r.day===day && r.channel===ch); return f ? f.count : 0; }),
    }));

    // ── Trend bar chart — moderní s tooltipem + avg line ──────────────────────
    const totalPerDay = allDays.map(day =>
        (byChannel.filter(r => r.day === day).reduce((s,r) => s + r.count, 0)));
    const avgTotal = totalPerDay.length ? Math.round(totalPerDay.reduce((a,b) => a+b, 0) / totalPerDay.length) : 0;
    const maxTotal = Math.max(...totalPerDay, 1);
    const minTotal = Math.min(...totalPerDay);

    _dashChart1 = new Chart(document.getElementById('dash-chart-trend').getContext('2d'), {
        type: 'bar',
        data: {
            labels: allDays.map(d => d.slice(5)),
            datasets: [
                ...trendDatasets,
                // Průměrná linie
                {
                    type: 'line', label: `Průměr (${avgTotal})`,
                    data: allDays.map(() => avgTotal),
                    borderColor: 'rgba(255,255,255,0.4)', borderWidth: 1.5,
                    borderDash: [4, 3], pointRadius: 0, fill: false, order: 0,
                },
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    display: true,
                    labels: { color: 'rgba(255,255,255,0.45)', font:{size:9}, boxWidth:10,
                               filter: item => item.datasetIndex < trendDatasets.length || item.text.includes('Průměr') }
                },
                tooltip: {
                    backgroundColor: 'rgba(20,20,30,0.92)', titleColor: '#fff',
                    bodyColor: 'rgba(255,255,255,0.75)', borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1,
                    callbacks: {
                        afterBody: (items) => {
                            const dayIdx = items[0]?.dataIndex;
                            const total = totalPerDay[dayIdx] ?? 0;
                            const mark = total === maxTotal ? ' ▲ MAX' : total === minTotal ? ' ▼ MIN' : '';
                            return [`Celkem: ${total}${mark}`];
                        }
                    }
                }
            },
            scales: {
                x: { stacked: true, ticks: { color: 'rgba(255,255,255,0.45)', font:{size:9} }, grid: { color:'rgba(255,255,255,0.04)' } },
                y: { stacked: true, beginAtZero: true, ticks: { color: 'rgba(255,255,255,0.45)', font:{size:9}, stepSize:1 }, grid: { color:'rgba(255,255,255,0.06)' } },
            }
        }
    });

    // ── Donut by channel — moderní s legendou a středním součtem ──────────────
    const donutData = {};
    byChannel.forEach(r => { donutData[r.channel] = (donutData[r.channel]||0) + r.count; });
    const donutLabels = Object.keys(donutData);
    const donutValues = donutLabels.map(k => donutData[k]);
    const donutColors = donutLabels.map(k => channelColors[k] || '#888');
    const donutTotal = donutValues.reduce((a,b)=>a+b,0);

    _dashChart2 = new Chart(document.getElementById('dash-chart-donut').getContext('2d'), {
        type: 'doughnut',
        data: { labels: donutLabels, datasets: [{ data: donutValues, backgroundColor: donutColors,
            borderWidth: 2, borderColor: 'rgba(0,0,0,0.25)', hoverBorderColor:'rgba(255,255,255,0.3)', hoverOffset: 6 }] },
        options: {
            responsive: true, maintainAspectRatio: false, cutout: '68%',
            plugins: {
                legend: { position: 'right', labels: { color:'rgba(255,255,255,0.55)', font:{size:9}, boxWidth:10, padding:6 } },
                tooltip: {
                    backgroundColor: 'rgba(20,20,30,0.92)', titleColor:'#fff', bodyColor:'rgba(255,255,255,0.75)',
                    callbacks: {
                        label: ctx => ` ${ctx.label}: ${ctx.raw} (${donutTotal ? Math.round(ctx.raw/donutTotal*100) : 0}%)`
                    }
                }
            }
        },
        plugins: [{
            id: 'donutCenter',
            afterDraw(chart) {
                const {ctx, chartArea:{top,bottom,left,right}} = chart;
                const cx = (left+right)/2, cy = (top+bottom)/2;
                ctx.save();
                ctx.textAlign='center'; ctx.textBaseline='middle';
                ctx.fillStyle='rgba(255,255,255,0.85)'; ctx.font='bold 16px sans-serif';
                ctx.fillText(donutTotal, cx, cy-7);
                ctx.fillStyle='rgba(255,255,255,0.4)'; ctx.font='10px sans-serif';
                ctx.fillText('issues', cx, cy+8);
                ctx.restore();
            }
        }]
    });
}

// ─── Maintenance Windows modal ────────────────────────────────────────────────

async function openMaintWindowsModal() {
    document.getElementById('maint-modal').style.display = 'flex';
    await loadMaintRules();
}

function closeMaintWindowsModal() {
    document.getElementById('maint-modal').style.display = 'none';
}

async function loadMaintRules() {
    const el = document.getElementById('maint-rules-list');
    el.innerHTML = `<div style="padding:12px; color:var(--text-muted); text-align:center;"><i class="fa-solid fa-spinner fa-spin"></i></div>`;
    try {
        const r = await fetch('/api/snooze/rules');
        const d = await r.json();
        const rules = d.rules || [];
        if (!rules.length) {
            el.innerHTML = `<div style="text-align:center; padding:16px; color:var(--text-muted); font-size:0.88em;">${t('maint_no_rules')}</div>`;
            return;
        }
        const now = new Date();
        const curH = now.getHours();
        const curDow = now.getDay() === 0 ? 6 : now.getDay() - 1; // 0=Mon

        el.innerHTML = rules.map(rule => {
            const sh = rule.start_hour, eh = rule.end_hour;
            const inWindow = (sh <= eh ? curH >= sh && curH < eh : curH >= sh || curH < eh)
                && (rule.days === '*' || rule.days.split(',').map(Number).includes(curDow));
            const badge = (inWindow && rule.enabled)
                ? `<span style="font-size:0.7em; padding:2px 7px; background:var(--warning); color:#000; border-radius:10px; font-weight:700;">${t('maint_active_badge')}</span>` : '';

            return `<div style="display:flex; align-items:center; gap:10px; padding:10px 12px; margin-bottom:6px; background:var(--panel); border:1px solid var(--border); border-radius:5px; ${!rule.enabled ? 'opacity:0.5;' : ''}">
                <label style="display:flex; align-items:center; cursor:pointer;">
                    <input type="checkbox" ${rule.enabled ? 'checked' : ''} onchange="toggleMaintRule(${rule.id}, this.checked)" style="margin-right:6px;">
                </label>
                <div style="flex:1; min-width:0;">
                    <div style="font-weight:600; font-size:0.92em;">${_escape(rule.name)} ${badge}</div>
                    <div style="font-size:0.75em; color:var(--text-muted);">
                        ${String(sh).padStart(2,'0')}:00 – ${String(eh).padStart(2,'0')}:00 &bull;
                        ${t('channel')}: ${_escape(rule.channels)} &bull;
                        ${rule.days === '*' ? 'Každý den' : rule.days.split(',').map(d => ['Po','Út','St','Čt','Pá','So','Ne'][+d]||d).join(', ')}
                        ${rule.hosts && rule.hosts !== '*' ? ` &bull; <i class="fa-solid fa-server" style="font-size:0.9em;"></i> ${_escape(rule.hosts)}` : ''}
                    </div>
                </div>
                <i class="fa-solid fa-trash" style="color:var(--error); opacity:0.6; cursor:pointer; padding:4px;"
                   onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.6'"
                   onclick="deleteMaintRule(${rule.id})"></i>
            </div>`;
        }).join('');
    } catch(e) {
        el.innerHTML = `<div style="text-align:center; padding:12px; color:var(--error); font-size:0.88em;">${t('data_load_failed')}</div>`;
    }
}

function _maintDayToggle(btn) {
    const dow = btn.dataset.dow;
    const btns = document.querySelectorAll('#maint-days-btns button');
    const allBtn = document.querySelector('#maint-days-btns button[data-dow="7"]');
    if (dow === '7') {
        // "Každý den" selected — deselect all specific days
        btns.forEach(b => { b.style.background = 'transparent'; b.style.color = 'var(--text-muted)'; b.style.borderColor = 'var(--border)'; });
        btn.style.background = 'var(--accent)'; btn.style.color = '#fff'; btn.style.borderColor = 'var(--accent)';
    } else {
        // Deselect "Každý den"
        allBtn.style.background = 'transparent'; allBtn.style.color = 'var(--text-muted)'; allBtn.style.borderColor = 'var(--border)';
        const active = btn.style.background === 'var(--accent)' || btn.style.backgroundColor.includes('0, 120');
        btn.style.background = active ? 'transparent' : 'var(--accent)';
        btn.style.color = active ? 'var(--text-muted)' : '#fff';
        btn.style.borderColor = active ? 'var(--border)' : 'var(--accent)';
        // If no specific day selected → revert to "Každý den"
        const anySelected = [...btns].filter(b => b.dataset.dow !== '7' && (b.style.background === 'var(--accent)' || b.style.backgroundColor.includes('0, 120'))).length;
        if (!anySelected) { allBtn.style.background = 'var(--accent)'; allBtn.style.color = '#fff'; allBtn.style.borderColor = 'var(--accent)'; }
    }
}

function _getMaintDays() {
    const btns = document.querySelectorAll('#maint-days-btns button');
    const allBtn = document.querySelector('#maint-days-btns button[data-dow="7"]');
    if (allBtn && (allBtn.style.background === 'var(--accent)' || allBtn.style.backgroundColor.includes('0, 120'))) return '*';
    const sel = [...btns].filter(b => b.dataset.dow !== '7' && (b.style.background === 'var(--accent)' || b.style.backgroundColor.includes('0, 120'))).map(b => b.dataset.dow);
    return sel.length ? sel.join(',') : '*';
}

async function addMaintRule() {
    const name     = document.getElementById('maint-name').value.trim();
    const start_h  = parseInt(document.getElementById('maint-start').value);
    const end_h    = parseInt(document.getElementById('maint-end').value);
    const channels = document.getElementById('maint-channels').value.trim() || '*';
    const days     = _getMaintDays();
    const hostsRaw = (document.getElementById('maint-hosts') || {}).value || '';
    const hosts    = hostsRaw.trim() || null;
    const msgEl    = document.getElementById('maint-add-msg');
    if (!name) { msgEl.style.color = 'var(--error)'; msgEl.textContent = t('maint_rule_error'); return; }
    try {
        const r = await fetch('/api/snooze/rules', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, start_hour: start_h, end_hour: end_h, channels, days, hosts})
        });
        const d = await r.json();
        if (d.status === 'ok') {
            msgEl.style.color = 'var(--success)';
            msgEl.textContent = t('maint_rule_added');
            document.getElementById('maint-name').value = '';
            setTimeout(() => { msgEl.textContent = ''; }, 3000);
            await loadMaintRules();
        } else {
            msgEl.style.color = 'var(--error)';
            msgEl.textContent = d.error || t('maint_rule_error');
        }
    } catch(e) {
        msgEl.style.color = 'var(--error)';
        msgEl.textContent = t('maint_rule_error');
    }
}

async function deleteMaintRule(id) {
    if (!confirm(t('maint_rule_delete_confirm'))) return;
    await fetch(`/api/snooze/rules/${id}`, {method: 'DELETE'});
    await loadMaintRules();
}

async function toggleMaintRule(id, enabled) {
    await fetch(`/api/snooze/rules/${id}/toggle`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({enabled})
    });
    await loadMaintRules();
}

// ─── Agent Health modal ───────────────────────────────────────────────────────

async function openAgentHealthModal() {
    document.getElementById('agent-health-modal').style.display = 'flex';
    await loadAgentHealth();
}

function closeAgentHealthModal() {
    document.getElementById('agent-health-modal').style.display = 'none';
}

async function loadAgentHealth(isAuto = false) {
    // Nepřerušit práci při auto-refresh
    if (isAuto) {
        const detailOpen = document.getElementById('device-detail-modal')?.style.display === 'flex';
        const batchOpen  = document.getElementById('batch-ssh-modal')?.style.display === 'flex';
        if (detailOpen || batchOpen) return;
    }
    const el = document.getElementById('agent-health-content');
    if (!isAuto) el.innerHTML = `<div style="text-align:center; padding:20px; color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i> ${t('loading_dots')}</div>`;
    try {
        const r = await fetch('/api/agents/health');
        const d = await r.json();
        const agents = d.agents || [];
        if (!agents.length) {
            el.innerHTML = `<div style="text-align:center; padding:24px; color:var(--text-muted);">${t('agent_health_no_agents')}</div>`;
            return;
        }
        const now = Date.now();

        const renderAgent = (ag) => {
            const online = ag.status === 'ONLINE';
            const ignored = ag.ignore_offline;
            const inMaint = ag.maintenance_until && new Date(ag.maintenance_until) > new Date();
            const statusColor = inMaint ? '#fa8231' : online ? 'var(--success)' : (ignored ? 'var(--text-muted)' : 'var(--error)');
            const statusLabel = inMaint ? '🔧 Údržba' : online ? t('agent_health_online') : t('agent_health_offline');
            let lastSeenStr = '-';
            if (ag.last_seen) {
                try {
                    const secs = Math.round((now - new Date(ag.last_seen).getTime()) / 1000);
                    if (secs < 60) lastSeenStr = `${secs}s`;
                    else if (secs < 3600) lastSeenStr = `${Math.round(secs/60)}m`;
                    else if (secs < 86400) lastSeenStr = `${Math.round(secs/3600)}h`;
                    else lastSeenStr = `${Math.round(secs/86400)}d`;
                } catch { lastSeenStr = ag.last_seen.slice(0,16); }
            }
            const alertColor24h = ag.alerts_24h > 0 ? 'var(--error)' : 'var(--text-muted)';
            const hs = ag.health_score ?? null;
            const hsColor = hs === null ? 'var(--text-muted)' : hs >= 80 ? 'var(--success)' : hs >= 50 ? '#fd7e14' : 'var(--error)';
            const hsCell = hs !== null ? `<div style="text-align:center;min-width:40px;">
                <div style="font-size:1.1em;font-weight:700;color:${hsColor};">${hs}</div>
                <div style="font-size:0.72em;color:var(--text-muted);">score</div>
            </div>` : '';
            let lagStr = '', lagColor = 'var(--text-muted)';
            if (ag.last_data_lag_ms != null) {
                const lagS = Math.round(ag.last_data_lag_ms / 1000);
                lagStr = lagS < 60 ? `${lagS}s` : lagS < 3600 ? `${Math.round(lagS/60)}m` : `${Math.round(lagS/3600)}h`;
                lagColor = lagS > 300 ? 'var(--warning)' : lagS > 60 ? '#fa8231' : 'var(--success)';
            }
            const lagCell = ag.last_data_lag_ms != null ? `
                <div style="text-align:center; min-width:48px;">
                    <div style="font-size:1em; font-weight:700; color:${lagColor};">${lagStr}</div>
                    <div style="font-size:0.72em; color:var(--text-muted);">data lag</div>
                </div>` : '';
            return `<div style="display:flex; align-items:center; gap:12px; padding:12px; margin-bottom:6px; background:var(--panel); border:1px solid var(--border); border-radius:6px; cursor:pointer; ${!online && !ignored ? 'border-color:rgba(255,60,60,0.3);' : ''}"
                        onclick="openAgentDetailModal('${_escape(ag.hostname)}')">
                ${hsCell}
                <div style="width:10px; height:10px; border-radius:50%; background:${statusColor}; flex-shrink:0; ${online ? 'box-shadow:0 0 6px ' + statusColor : ''}"></div>
                <div style="flex:1; min-width:0;">
                    <div style="font-weight:600; font-size:0.95em;">${_escape(ag.hostname)}</div>
                    <div style="font-size:0.75em; color:var(--text-muted); margin-top:2px;">
                        ${t('agent_health_registered')}: ${ag.registered_at ? ag.registered_at.slice(0,10) : '-'}
                        ${ag.notes ? ` · ${_escape(ag.notes)}` : ''}
                        ${ag.agent_version ? ` · <span style="font-family:monospace;color:var(--accent);">${_escape(ag.agent_version.slice(0,8))}</span>` : ''}
                    </div>
                </div>
                <div style="text-align:center; min-width:56px;">
                    <div style="font-size:1.1em; font-weight:700; color:${statusColor};">${statusLabel}</div>
                    <div style="font-size:0.72em; color:var(--text-muted);">${t('agent_health_last_seen')}: ${lastSeenStr}</div>
                </div>
                ${lagCell}
                <div style="text-align:center; min-width:44px;">
                    <div style="font-size:1.1em; font-weight:700; color:${alertColor24h};">${ag.alerts_24h}</div>
                    <div style="font-size:0.72em; color:var(--text-muted);">${t('agent_health_24h')}</div>
                </div>
                <div style="text-align:center; min-width:44px;">
                    <div style="font-size:1.1em; font-weight:700;">${ag.alerts_7d}</div>
                    <div style="font-size:0.72em; color:var(--text-muted);">${t('agent_health_7d')}</div>
                </div>
                <div style="text-align:center; min-width:56px;">
                    <div style="font-size:1.1em; font-weight:700;">${ag.alerts_total}</div>
                    <div style="font-size:0.72em; color:var(--text-muted);">${t('agent_health_total_alerts')}</div>
                </div>
            </div>`;
        };

        // Group agents by agent_group
        const grouped = {};
        const UNGROUPED = '\x00';
        agents.forEach(ag => {
            const g = ag.agent_group || UNGROUPED;
            if (!grouped[g]) grouped[g] = [];
            grouped[g].push(ag);
        });

        let html = '';
        const sortedGroups = Object.keys(grouped).sort((a, b) => {
            if (a === UNGROUPED) return 1;
            if (b === UNGROUPED) return -1;
            return a.localeCompare(b);
        });

        const isAdmin = window.currentRole === 'admin' || window.currentRole === 'superadmin';
        sortedGroups.forEach(grp => {
            if (grp !== UNGROUPED) {
                const cnt = grouped[grp].length;
                const onlineCnt = grouped[grp].filter(a => a.status === 'ONLINE').length;
                const grpB64 = btoa(unescape(encodeURIComponent(grp)));
                const bulkBtns = isAdmin ? `
                    <span onclick="event.stopPropagation();" style="display:inline-flex;gap:4px;margin-left:10px;">
                        <button onclick="_setGroupMaintenance('${grpB64}', 30)" title="Údržba 30 min" style="padding:2px 7px;font-size:.75em;background:transparent;border:1px solid var(--border);color:var(--text-muted);border-radius:3px;cursor:pointer;"><i class="fa-solid fa-wrench"></i> 30m</button>
                        <button onclick="_setGroupMaintenance('${grpB64}', 120)" title="Údržba 2 hod" style="padding:2px 7px;font-size:.75em;background:transparent;border:1px solid var(--border);color:var(--text-muted);border-radius:3px;cursor:pointer;">2h</button>
                        <button onclick="_setGroupMaintenance('${grpB64}', 0)" title="Ukončit údržbu" style="padding:2px 7px;font-size:.75em;background:transparent;border:1px solid #fa8231;color:#fa8231;border-radius:3px;cursor:pointer;"><i class="fa-solid fa-xmark"></i></button>
                    </span>` : '';
                html += `<details open style="margin-bottom:10px;">
                    <summary style="cursor:pointer; font-size:0.8em; color:var(--accent); text-transform:uppercase; letter-spacing:.06em; font-weight:700; padding:6px 2px; user-select:none; display:flex; align-items:center;">
                        <i class="fa-solid fa-layer-group"></i>&nbsp;${_escape(grp)}
                        <span style="color:var(--text-muted); font-weight:400; margin-left:6px;">${onlineCnt}/${cnt} online</span>
                        ${bulkBtns}
                    </summary>
                    <div style="padding-left:8px; margin-top:4px;">
                        ${grouped[grp].map(renderAgent).join('')}
                    </div>
                </details>`;
            }
        });

        // Ungrouped agents last
        if (grouped[UNGROUPED]) {
            if (sortedGroups.length > 1) {
                html += `<div style="font-size:0.8em; color:var(--text-muted); text-transform:uppercase; letter-spacing:.06em; padding:6px 2px; margin-bottom:4px;">Bez skupiny</div>`;
            }
            html += grouped[UNGROUPED].map(renderAgent).join('');
        }

        el.innerHTML = html;
    } catch(e) {
        el.innerHTML = `<div style="text-align:center; padding:20px; color:var(--error);">${t('data_load_failed')}</div>`;
    }
}

// ─── Alert Timeline modal ─────────────────────────────────────────────────────

let _timelineChart = null;

async function openTimelineModal() {
    document.getElementById('timeline-modal').style.display = 'flex';
    await loadTimeline(7);
}

function closeTimelineModal() {
    document.getElementById('timeline-modal').style.display = 'none';
    if (_timelineChart) { _timelineChart.destroy(); _timelineChart = null; }
}

function _tlActiveDaysBtn(days) {
    [7, 14, 30].forEach(d => {
        const b = document.getElementById(`tl-btn-${d}`);
        if (!b) return;
        if (d === days) {
            b.style.background = 'var(--accent)';
            b.style.border = 'none';
            b.style.color = '#fff';
        } else {
            b.style.background = 'var(--panel)';
            b.style.border = '1px solid var(--border)';
            b.style.color = 'var(--text-muted)';
        }
    });
}

async function loadTimeline(days) {
    _tlActiveDaysBtn(days);
    const heatmapEl = document.getElementById('timeline-heatmap');
    const statsEl   = document.getElementById('timeline-stats');
    heatmapEl.innerHTML = `<div style="padding:20px; color:var(--text-muted); text-align:center;"><i class="fa-solid fa-spinner fa-spin"></i> ${t('loading_dots')}</div>`;
    statsEl.innerHTML = '';

    try {
        const r = await fetch(`/api/alerts/timeline?days=${days}`);
        const d = await r.json();
        _renderTimeline(d, days);
    } catch(e) {
        heatmapEl.innerHTML = `<div style="padding:20px; color:var(--error); text-align:center;">${t('data_load_failed')}</div>`;
    }
}

function _renderTimeline(data, days) {
    const heatmap   = data.heatmap   || [];
    const byChannel = data.by_channel || [];

    // ── Stats summary ──────────────────────────────────────────────────────
    const total = heatmap.reduce((s, r) => s + r.count, 0);
    const dayTotals = {};
    const hourTotals = new Array(24).fill(0);
    heatmap.forEach(r => {
        dayTotals[r.day] = (dayTotals[r.day] || 0) + r.count;
        hourTotals[r.hour] += r.count;
    });
    const busiestDay  = Object.entries(dayTotals).sort((a, b) => b[1] - a[1])[0];
    const busiestHour = hourTotals.reduce((best, v, i) => v > best[1] ? [i, v] : best, [0, 0]);

    const statsEl = document.getElementById('timeline-stats');
    statsEl.innerHTML = [
        [t('timeline_total'),        total,                             'var(--accent)'],
        [t('timeline_busiest_day'),  busiestDay  ? busiestDay[0]  : '-', 'var(--warning)'],
        [t('timeline_busiest_hour'), busiestHour[1] > 0 ? `${String(busiestHour[0]).padStart(2,'0')}:00` : '-', 'var(--success)'],
    ].map(([label, value, color]) =>
        `<div style="background:var(--panel); border:1px solid var(--border); border-radius:5px; padding:10px 16px; flex:1; min-width:120px;">
            <div style="font-size:0.75em; color:var(--text-muted); text-transform:uppercase; letter-spacing:.4px;">${label}</div>
            <div style="font-size:1.4em; font-weight:700; color:${color}; margin-top:3px;">${_escape(String(value))}</div>
        </div>`
    ).join('');

    // ── Heatmap (days × hours 0-23) ───────────────────────────────────────
    const maxCount = Math.max(1, ...heatmap.map(r => r.count));

    // Build sorted list of unique days (last N)
    const allDays = [];
    const now = new Date();
    for (let i = days - 1; i >= 0; i--) {
        const d = new Date(now);
        d.setDate(d.getDate() - i);
        allDays.push(d.toISOString().slice(0, 10));
    }

    // Build lookup: day+hour → count
    const lookup = {};
    heatmap.forEach(r => { lookup[`${r.day}_${r.hour}`] = r.count; });

    const CELL = 20;
    const LABEL_W = 58;

    let html = `<div style="font-size:11px; font-family:monospace; overflow-x:auto;">`;
    // Header: hour labels
    html += `<div style="display:flex; gap:2px; margin-bottom:3px; padding-left:${LABEL_W + 4}px;">`;
    for (let h = 0; h < 24; h++) {
        html += `<div style="width:${CELL}px; text-align:center; color:var(--text-muted); font-size:0.82em;">${String(h).padStart(2,'0')}</div>`;
    }
    html += '</div>';

    // Rows: each day
    allDays.forEach(day => {
        const dayLabel = day.slice(5); // MM-DD
        html += `<div style="display:flex; gap:2px; margin-bottom:2px; align-items:center;">`;
        html += `<div style="width:${LABEL_W}px; text-align:right; padding-right:6px; color:var(--text-muted); font-size:0.82em; flex-shrink:0; white-space:nowrap;">${dayLabel}</div>`;
        for (let h = 0; h < 24; h++) {
            const cnt = lookup[`${day}_${h}`] || 0;
            const intensity = cnt === 0 ? 0 : Math.min(1, cnt / (maxCount * 0.6 + 0.01));
            const bg = cnt === 0
                ? 'rgba(255,255,255,0.04)'
                : `rgba(${Math.round(255 * Math.min(1, intensity * 2))},${Math.round(140 * (1 - intensity))},0,${0.35 + intensity * 0.65})`;
            html += `<div title="${day} ${String(h).padStart(2,'0')}:00 — ${cnt} alertů"
                style="width:${CELL}px;height:${CELL}px;background:${bg};border-radius:2px;display:flex;align-items:center;justify-content:center;cursor:default;font-size:0.72em;color:${cnt>2?'rgba(255,255,255,0.9)':'transparent'};">
                ${cnt > 2 ? cnt : ''}
            </div>`;
        }
        html += '</div>';
    });
    html += '</div>';
    document.getElementById('timeline-heatmap').innerHTML = html;

    // ── Daily bar chart ────────────────────────────────────────────────────
    const channelColors = {
        INFRA: '#0078d4', SECURITY: '#d41a1a', AGENT: '#28a745',
        ROOT: '#9932cc', LOGIN: '#fd7e14', GENERAL: '#888', OTHER: '#555'
    };
    const channels = [...new Set(byChannel.map(r => r.channel))];
    const datasets = channels.map(ch => {
        return {
            label: ch,
            data: allDays.map(day => {
                const found = byChannel.find(r => r.day === day && r.channel === ch);
                return found ? found.count : 0;
            }),
            backgroundColor: (channelColors[ch] || '#888') + 'cc',
            borderColor: channelColors[ch] || '#888',
            borderWidth: 1,
        };
    });

    // Celkový počet per den pro avg/min/max anotace
    const tlTotalPerDay = allDays.map(day => channels.reduce((s, ch) => {
        const f = byChannel.find(r => r.day===day && r.channel===ch);
        return s + (f ? f.count : 0);
    }, 0));
    const tlAvg = tlTotalPerDay.length ? Math.round(tlTotalPerDay.reduce((a,b)=>a+b,0)/tlTotalPerDay.length) : 0;
    const tlMax = Math.max(...tlTotalPerDay, 0);
    const tlMin = Math.min(...tlTotalPerDay);

    const ctx = document.getElementById('timeline-chart').getContext('2d');
    if (_timelineChart) { _timelineChart.destroy(); }
    _timelineChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: allDays.map(d => d.slice(5)),
            datasets: [
                ...datasets,
                { type:'line', label:`Průměr (${tlAvg})`, data: allDays.map(()=>tlAvg),
                  borderColor:'rgba(255,255,255,0.35)', borderWidth:1.5, borderDash:[5,3],
                  pointRadius:0, fill:false, order:0 },
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { mode:'index', intersect:false },
            plugins: {
                legend: { labels: { color:'rgba(255,255,255,0.6)', font:{size:10}, boxWidth:10 } },
                tooltip: {
                    backgroundColor:'rgba(20,20,30,0.92)', titleColor:'#fff',
                    bodyColor:'rgba(255,255,255,0.75)', borderColor:'rgba(255,255,255,0.1)', borderWidth:1,
                    callbacks: {
                        afterBody: (items) => {
                            const i = items[0]?.dataIndex ?? -1;
                            if (i < 0) return [];
                            const total = tlTotalPerDay[i] ?? 0;
                            const mark = total === tlMax ? ' ▲ MAX' : total === tlMin ? ' ▼ MIN' : '';
                            return [`Celkem: ${total}${mark}`, `Průměr: ${tlAvg}`];
                        }
                    }
                }
            },
            scales: {
                x: { stacked:true, ticks:{color:'rgba(255,255,255,0.5)',font:{size:10}}, grid:{color:'rgba(255,255,255,0.05)'} },
                y: { stacked:true, beginAtZero:true, ticks:{color:'rgba(255,255,255,0.5)',font:{size:10}}, grid:{color:'rgba(255,255,255,0.06)'} },
            }
        }
    });
}

// ─── Plugin Stats modal ───────────────────────────────────────────────────────

async function openPluginStatsModal() {
    document.getElementById('plugin-stats-modal').style.display = 'flex';
    const el = document.getElementById('plugin-stats-content');
    el.innerHTML = `<div style="text-align:center; padding:20px; color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i> ${t('loading_dots')}</div>`;
    try {
        const r = await fetch('/api/plugins/stats');
        const d = await r.json();
        const rows = d.stats || [];
        if (!rows.length) {
            el.innerHTML = `<div style="text-align:center; padding:20px; color:var(--text-muted);">${t('no_data_yet')}</div>`;
            return;
        }
        const isAdmin = window.currentRole === 'admin' || window.currentRole === 'superadmin';
        el.innerHTML = `
            <table style="width:100%; border-collapse:collapse; font-size:0.88em;">
                <thead>
                    <tr style="color:var(--text-muted); border-bottom:1px solid var(--border);">
                        <th style="text-align:left; padding:8px 4px;">${t('plugin_col')}</th>
                        <th style="text-align:right; padding:8px 4px;">${t('today_col')}</th>
                        <th style="text-align:right; padding:8px 4px;">${t('week_col')}</th>
                        <th style="text-align:right; padding:8px 4px;">${t('total_col')}</th>
                        <th style="text-align:center; padding:8px 4px;" title="Notifikace při novém issue"><i class="fa-solid fa-bell"></i></th>
                        <th style="text-align:right; padding:8px 4px;">${t('last_seen_col')}</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows.map(r => {
                        const notifyOn = r.notify !== false;
                        const notifyBtn = isAdmin
                            ? `<button onclick="_togglePluginNotify('${_escape(r.plugin)}', ${!notifyOn})"
                                  title="${notifyOn ? 'Vypnout notifikace' : 'Zapnout notifikace'}"
                                  style="background:none;border:none;cursor:pointer;padding:2px 6px;color:${notifyOn?'var(--accent)':'var(--text-muted)'};"
                                  ><i class="fa-solid ${notifyOn?'fa-bell':'fa-bell-slash'}"></i></button>`
                            : `<i class="fa-solid ${notifyOn?'fa-bell':'fa-bell-slash'}" style="color:${notifyOn?'var(--accent)':'var(--text-muted)'}; font-size:.9em;"></i>`;
                        return `<tr style="border-bottom:1px solid var(--border); opacity:${r.enabled!==false?1:0.45};">
                            <td style="padding:8px 4px;"><i class="fa-solid fa-puzzle-piece" style="color:var(--accent); margin-right:6px; font-size:0.8em;"></i>${_escape(r.plugin)}</td>
                            <td style="text-align:right; padding:8px 4px; ${r.today > 0 ? 'color:var(--error); font-weight:600;' : ''}">${r.today}</td>
                            <td style="text-align:right; padding:8px 4px;">${r.week}</td>
                            <td style="text-align:right; padding:8px 4px;">${r.total}</td>
                            <td style="text-align:center; padding:8px 4px;">${notifyBtn}</td>
                            <td style="text-align:right; padding:8px 4px; color:var(--text-muted); font-size:0.82em;">${r.last_seen ? r.last_seen.slice(0,16) : '-'}</td>
                        </tr>`;
                    }).join('')}
                </tbody>
            </table>
            <div style="margin-top:10px;font-size:.75em;color:var(--text-muted);padding-top:8px;border-top:1px solid var(--border);">
                <i class="fa-solid fa-bell" style="color:var(--accent);"></i> = HA + MQTT notifikace při vzniku nového issue
            </div>`;
    } catch(e) {
        el.innerHTML = `<div style="text-align:center; padding:20px; color:var(--error);">${t('data_load_failed')}</div>`;
    }
}

function closePluginStatsModal() {
    document.getElementById('plugin-stats-modal').style.display = 'none';
}

// ─── Live Log Tail (SSE) ──────────────────────────────────────────────────────

function openLiveTail(filename) {
    const modal = document.getElementById('live-tail-modal');
    modal.style.display = 'flex';
    document.getElementById('live-tail-fname').textContent = filename;
    const out = document.getElementById('live-tail-output');
    out.innerHTML = '';
    const statusEl = document.getElementById('live-tail-status');
    statusEl.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> ${t('live_tail_connecting')}`;

    if (_liveTailES) { _liveTailES.close(); _liveTailES = null; }

    _liveTailES = new EventSource(`/api/logs/tail/${encodeURIComponent(filename)}`);

    _liveTailES.onopen = () => {
        statusEl.innerHTML = `<i class="fa-solid fa-circle fa-beat" style="color:var(--accent);"></i> ${t('live_tail_connected')}`;
    };

    let _lineCount = 0;
    _liveTailES.onmessage = (e) => {
        const d = JSON.parse(e.data);
        if (d.error) {
            statusEl.innerHTML = `<i class="fa-solid fa-circle-exclamation" style="color:var(--error);"></i> ${_escape(d.error)}`;
            return;
        }
        const txt = d.line || '';
        const line = document.createElement('div');
        line.className = 'lt-line';
        line.style.cssText = 'border-bottom:1px solid rgba(255,255,255,0.03);padding:2px 0;font-size:0.82em;font-family:monospace;white-space:pre-wrap;word-break:break-all;';

        // Colour coding by severity keywords
        const tl = txt.toLowerCase();
        if (!d.init) {
            if (/\b(error|critical|crit|emerg|alert|fail|fatal)\b/.test(tl))
                line.style.color = '#f87171';
            else if (/\b(warn|warning)\b/.test(tl))
                line.style.color = '#ffc107';
            else
                line.style.color = 'var(--accent)';
        } else {
            line.style.color = 'var(--text-muted)';
        }

        line.textContent = txt;
        out.appendChild(line);
        _lineCount++;
        // Keep only last 2000 lines to avoid memory bloat
        if (_lineCount > 2000) { out.removeChild(out.firstChild); _lineCount--; }
        // Apply search filter if active
        const q = document.getElementById('live-tail-filter')?.value.toLowerCase();
        if (q && !tl.includes(q)) line.style.display = 'none';
        if (document.getElementById('live-tail-scroll').checked) out.scrollTop = out.scrollHeight;
        if (!d.init) statusEl.innerHTML = `<i class="fa-solid fa-circle fa-beat" style="color:var(--accent);"></i> ${t('live_tail_live')}`;
    };

    _liveTailES.onerror = () => {
        statusEl.innerHTML = `<i class="fa-solid fa-circle-exclamation" style="color:var(--warning);"></i> ${t('live_tail_reconnecting')}`;
    };
}

function closeLiveTail() {
    _ltExitFullscreen();
    document.getElementById('live-tail-modal').style.display = 'none';
    if (_liveTailES) { _liveTailES.close(); _liveTailES = null; }
}

// 004: Fullscreen pro live tail
let _ltFullscreen = false;
function _ltToggleFullscreen() {
    _ltFullscreen ? _ltExitFullscreen() : _ltEnterFullscreen();
}
function _ltEnterFullscreen() {
    const modal = document.getElementById('live-tail-modal');
    const inner = modal?.querySelector('.modal');
    if (!inner) return;
    _ltFullscreen = true;
    inner.style.cssText = 'width:100vw;max-width:100vw;height:100vh;max-height:100vh;border-radius:0;';
    modal.style.padding = '0';
    document.getElementById('lt-fullscreen-btn')?.classList.replace('fa-expand','fa-compress');
}
function _ltExitFullscreen() {
    if (!_ltFullscreen) return;
    _ltFullscreen = false;
    const inner = document.getElementById('live-tail-modal')?.querySelector('.modal');
    if (inner) inner.style.cssText = 'width:800px;max-width:95%;height:80vh;display:flex;flex-direction:column;';
    const ov = document.getElementById('live-tail-modal');
    if (ov) ov.style.padding = '';
    document.getElementById('lt-fullscreen-btn')?.classList.replace('fa-compress','fa-expand');
}

function clearLiveTail() {
    document.getElementById('live-tail-output').innerHTML = '';
}

function _ltFilter(q) {
    const out = document.getElementById('live-tail-output');
    if (!out) return;
    const lq = q.toLowerCase();
    out.querySelectorAll('.lt-line').forEach(el => {
        el.style.display = (!lq || el.textContent.toLowerCase().includes(lq)) ? '' : 'none';
    });
}

// ─── Settings modal ───────────────────────────────────────────────────────────

// ---- API Keys Management ----
async function _apikeyLoadList() {
    const el = document.getElementById('apikeys-list');
    if (!el) return;
    try {
        const r = await fetch('/api/apikeys');
        const d = await r.json();
        const keys = d.keys || [];
        if (!keys.length) { el.innerHTML = '<div style="color:var(--text-muted);font-size:.82em;">Žádné API klíče.</div>'; return; }
        el.innerHTML = keys.map(k => `<div style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:.82em;border-bottom:1px solid var(--border);">
            <b>${_escape(k.name)}</b>
            <span style="background:rgba(0,120,212,.15);color:#a3cfff;border-radius:8px;padding:1px 6px;">${k.scope}</span>
            <span style="color:var(--text-muted);font-size:.78em;">${k.expires_at?'exp:'+k.expires_at.slice(0,10):'no expiry'}</span>
            <span style="color:var(--text-muted);font-size:.78em;flex:1;">${k.last_used?'last:'+k.last_used.slice(0,16).replace('T',' '):''}</span>
            <i class="fa-solid fa-trash" style="cursor:pointer;color:var(--error);" onclick="_apikeyDelete(${k.id})"></i>
        </div>`).join('');
    } catch {}
}
async function _apikeyCreate() {
    const name = document.getElementById('apikey-name')?.value.trim();
    const scope = document.getElementById('apikey-scope')?.value || 'read';
    const tok = document.getElementById('apikey-new-token');
    if (!name) { alert('Zadejte název klíče'); return; }
    try {
        const r = await fetch('/api/apikeys', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name, scope})});
        const d = await r.json();
        if (d.token) {
            tok.style.display = 'block';
            tok.innerHTML = `<b>Token (zkopírujte — zobrazí se jen jednou!):</b><br>${_escape(d.token)}`;
            document.getElementById('apikey-name').value = '';
            await _apikeyLoadList();
        } else alert(d.error || 'Chyba');
    } catch (e) { alert('Chyba: ' + e); }
}
async function _apikeyDelete(id) {
    if (!confirm('Smazat API klíč?')) return;
    await fetch(`/api/apikeys/${id}`, {method:'DELETE'});
    await _apikeyLoadList();
}

function _cfgSet(id, val) { const el = document.getElementById(id); if (!el) return; if (el.type === 'checkbox') el.checked = !!val; else el.value = val ?? ''; }

async function openSettingsModal() {
    document.getElementById('settings-modal').style.display = 'flex';
    document.getElementById('settings-loading').style.display = 'block';
    document.getElementById('settings-form').style.display = 'none';
    document.getElementById('settings-msg').style.display = 'none';
    _apikeyLoadList();
    _loadDbStats();
    // 214: Show config validation warnings
    fetch('/api/config/validate').then(r => r.json()).then(d => {
        const warns = d.warnings || [];
        const el = document.getElementById('cfg-validation-banner');
        if (!el || !warns.length) return;
        const colors = {critical:'#ef4444', error:'#f97316', warning:'#eab308', info:'#888'};
        el.style.display = 'block';
        el.innerHTML = `<div style="font-size:.78em;font-weight:700;margin-bottom:4px;color:#eab308;"><i class="fa-solid fa-triangle-exclamation"></i> Varování konfigurace (${warns.length})</div>` +
            warns.map(w => `<div style="color:${colors[w.level]||'#888'};padding:2px 0;font-size:.76em;">${w.level.toUpperCase()}: ${_escape(w.message)}</div>`).join('');
    }).catch(() => {});

    try {
        const r = await fetch('/api/config/view');
        const d = await r.json();
        // Základní
        _cfgSet('cfg-instance-name', d.instance_name);
        _cfgSet('cfg-worker-threads', d.worker_threads);
        _cfgSet('cfg-log-dir', d.log_dir);
        // AI
        _cfgSet('cfg-ollama-url', d.ollama_url);
        _cfgSet('cfg-ollama-model', d.ollama_model);
        _cfgSet('cfg-ollama-num-ctx', d.ollama_num_ctx || 2048);
        _cfgSet('cfg-hailo-enabled', d.hailo_ollama_enabled);
        _cfgSet('cfg-hailo-url', d.hailo_ollama_url);
        _cfgSet('cfg-hailo-model', d.hailo_ollama_model);
        _cfgSet('cfg-auto-severity',  d.auto_severity_enabled  ?? false);
        _cfgSet('cfg-auto-duplicate', d.auto_duplicate_enabled ?? true);
        // MQTT a HA jsou konfigurovány v Notifikace & Integrace modalu
        // LDAP
        _cfgSet('cfg-ldap-enabled', d.ldap_enabled);
        _cfgSet('cfg-ldap-host', d.ldap_host);
        _cfgSet('cfg-ldap-port', d.ldap_port || 389);
        _cfgSet('cfg-ldap-ssl', d.ldap_use_ssl);
        _cfgSet('cfg-ldap-basedn', d.ldap_base_dn);
        _cfgSet('cfg-ldap-binddn', d.ldap_bind_dn);
        // 209: Issue expiry
        const expiry = d.issue_expiry_days || {};
        _cfgSet('cfg-expiry-infra',    expiry.infra    || '');
        _cfgSet('cfg-expiry-agent',    expiry.agent    || '');
        _cfgSet('cfg-expiry-security', expiry.security || '');
        _cfgSet('cfg-expiry-root',     expiry.root     || '');
        // Readonly info
        const roInfo = document.getElementById('cfg-readonly-info');
        roInfo.innerHTML = [
            ['Version', d.version], ['Git', d.subversion],
            ['Data Dir', d.data_dir], ['Web Port', d.web_port],
            ['Plugin Dir', d.plugin_dir], ['Teams', d.teams_enabled ? 'enabled' : 'disabled'],
        ].map(([k,v]) => `<div style="color:var(--text-muted);">${k}:</div><div style="color:var(--text-main); word-break:break-all;">${v}</div>`).join('');
        document.getElementById('settings-loading').style.display = 'none';
        document.getElementById('settings-form').style.display = 'block';
    } catch(e) {
        document.getElementById('settings-loading').innerHTML = `<span style="color:var(--error);">${t('settings_load_failed')}: ${e}</span>`;
    }
}

// ── 305: Runbooks CRUD ────────────────────────────────────────────────────────
async function _rbLoad() {
    const el = document.getElementById('rb-list');
    if (!el) return;
    el.innerHTML = '<div style="padding:12px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>';
    try {
        const r = await fetch('/api/runbooks');
        const d = await r.json();
        const rbs = d.runbooks || [];
        const isAdmin = window.currentRole === 'admin' || window.currentRole === 'superadmin';
        el.innerHTML = rbs.length
            ? rbs.map(rb => `<div style="display:flex;align-items:center;gap:10px;padding:8px 12px;border-bottom:1px solid var(--border);font-size:.85em;">
                <i class="fa-solid fa-book-open" style="color:#fb923c;flex-shrink:0;"></i>
                <div style="flex:1;cursor:pointer;color:var(--accent);" onclick="_rbOpen('${btoa(encodeURIComponent(rb.issue_type))}')">${_escape(rb.issue_type)}</div>
                <div style="font-size:.72em;color:var(--text-muted);">${_escape(rb.plugin||'')} ${_escape(rb.channel||'')}</div>
                ${isAdmin ? `<i class="fa-solid fa-trash" style="cursor:pointer;color:var(--error);font-size:.85em;" onclick="_rbDelete(${rb.id})"></i>` : ''}
              </div>`).join('')
            : '<div style="padding:14px;color:var(--text-muted);text-align:center;">Žádné runbooky. Runbooky se generují z issue karet (tlačítko 📖).</div>';
    } catch(e) { el.innerHTML = `<div style="color:var(--error);padding:12px;">${_escape(e.message)}</div>`; }
}

async function _rbOpen(issueTypeB64) {
    try {
        const r = await fetch(`/api/runbooks/${issueTypeB64}`);
        const d = await r.json();
        const modal = document.getElementById('runbook-modal');
        if (modal) {
            document.getElementById('runbook-title').textContent = d.issue_type || '';
            document.getElementById('runbook-body').textContent = d.content || '';
            document.getElementById('runbook-meta').textContent = `Autor: ${d.created_by||'?'} · ${(d.updated_at||'').slice(0,10)}`;
            modal.style.display = 'flex';
        }
    } catch(e) { _showToast(`Chyba: ${e.message}`, 'error'); }
}

async function _rbDelete(id) {
    if (!confirm('Smazat runbook?')) return;
    try {
        await fetch(`/api/runbooks/${id}`, {method:'DELETE', headers:{'Content-Type':'application/json'}});
        _rbLoad();
        _showToast('Runbook smazán', 'info');
    } catch(e) { _showToast(`Chyba: ${e.message}`, 'error'); }
}

// ── 382: Relativní časy ───────────────────────────────────────────────────────
function _relTime(isoStr) {
    if (!isoStr) return '';
    try {
        const diff = (Date.now() - new Date(isoStr).getTime()) / 1000;
        if (diff < 60) return 'právě';
        if (diff < 3600) return `před ${Math.floor(diff/60)} min`;
        if (diff < 86400) return `před ${Math.floor(diff/3600)} h`;
        if (diff < 604800) return `před ${Math.floor(diff/86400)} d`;
        return new Date(isoStr).toLocaleDateString('cs-CZ');
    } catch { return isoStr.slice(0,16).replace('T',' '); }
}

// ── 376: Global search (Ctrl+K) ───────────────────────────────────────────────
function _openGlobalSearch() {
    let overlay = document.getElementById('global-search-overlay');
    if (overlay) { overlay.remove(); return; }
    overlay = document.createElement('div');
    overlay.id = 'global-search-overlay';
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;z-index:9999;background:rgba(0,0,0,.6);display:flex;align-items:flex-start;justify-content:center;padding-top:80px;';
    overlay.innerHTML = `<div style="background:var(--panel);border:1px solid var(--border);border-radius:10px;width:560px;max-width:95%;box-shadow:0 20px 60px rgba(0,0,0,.5);">
        <div style="display:flex;align-items:center;padding:12px 16px;border-bottom:1px solid var(--border);">
            <i class="fa-solid fa-magnifying-glass" style="color:var(--text-muted);margin-right:10px;"></i>
            <input id="gs-input" type="text" placeholder="Hledej issues, agenty, wiki…" autofocus
                   style="flex:1;background:transparent;border:none;outline:none;color:var(--text-main);font-size:1em;">
            <kbd style="font-size:.72em;color:var(--text-muted);border:1px solid var(--border);border-radius:3px;padding:2px 5px;">Esc</kbd>
        </div>
        <div id="gs-results" style="max-height:400px;overflow-y:auto;padding:8px 0;"></div>
    </div>`;
    document.body.appendChild(overlay);
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
    const inp = document.getElementById('gs-input');
    inp?.addEventListener('keydown', e => { if (e.key === 'Escape') overlay.remove(); });
    let _gsTimer;
    inp?.addEventListener('input', () => {
        clearTimeout(_gsTimer);
        _gsTimer = setTimeout(_gsSearch, 250);
    });
}

async function _gsSearch() {
    const q = document.getElementById('gs-input')?.value?.trim();
    const el = document.getElementById('gs-results');
    if (!el) return;
    if (!q || q.length < 2) { el.innerHTML = '<div style="padding:12px 16px;color:var(--text-muted);font-size:.85em;">Zadej alespoň 2 znaky…</div>'; return; }
    el.innerHTML = '<div style="padding:12px 16px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>';
    try {
        const r = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=15`);
        const d = await r.json();
        const results = d.results || [];
        const typeLabel = {issue:'Issue', agent:'Agent', wiki:'Wiki'};
        el.innerHTML = results.length
            ? results.map(r => `<div style="display:flex;align-items:center;gap:12px;padding:8px 16px;cursor:pointer;border-radius:4px;transition:background .1s;"
                onmouseover="this.style.background='rgba(255,255,255,.05)'" onmouseout="this.style.background=''"
                onclick="_gsSelect('${r.type}','${_escape(r.key)}')">
                <i class="fa-solid fa-${_escape(r.icon||'circle')}" style="color:var(--accent);width:16px;flex-shrink:0;"></i>
                <div style="flex:1;min-width:0;">
                    <div style="font-size:.87em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_escape(r.title)}</div>
                    <div style="font-size:.72em;color:var(--text-muted);">${typeLabel[r.type]||r.type} · ${_escape(r.subtitle||'')}</div>
                </div>
              </div>`).join('')
            : '<div style="padding:14px 16px;color:var(--text-muted);font-size:.85em;">Nic nenalezeno.</div>';
    } catch(e) { el.innerHTML = `<div style="padding:12px 16px;color:var(--error);">Chyba: ${_escape(e.message)}</div>`; }
}

function _gsSelect(type, key) {
    document.getElementById('global-search-overlay')?.remove();
    if (type === 'issue') {
        const kb64 = btoa(key);
        if (typeof openIssuesModal === 'function') openIssuesModal('infra');
    } else if (type === 'agent') {
        if (typeof openDeviceDetailModal === 'function') openDeviceDetailModal(key, 'agent');
    }
}

// ── 311: Audit trail viewer ───────────────────────────────────────────────────
async function _openAuditTrailPanel() {
    let panel = document.getElementById('audit-trail-panel');
    if (panel) { panel.remove(); return; }
    panel = document.createElement('div');
    panel.id = 'audit-trail-panel';
    panel.style.cssText = 'padding:14px 20px;border-top:1px solid var(--border);';
    panel.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <div style="font-size:.78em;text-transform:uppercase;letter-spacing:.07em;color:var(--accent);"><i class="fa-solid fa-clipboard-list"></i> Audit Trail</div>
        <i class="fa-solid fa-times" style="cursor:pointer;color:var(--text-muted);" onclick="document.getElementById('audit-trail-panel')?.remove()"></i>
    </div>
    <div id="audit-trail-body" style="max-height:250px;overflow-y:auto;"><i class="fa-solid fa-spinner fa-spin"></i></div>`;
    const form = document.getElementById('settings-form');
    if (form) form.insertBefore(panel, form.firstChild);
    try {
        const r = await fetch('/api/admin/audit_trail?limit=50');
        const d = await r.json();
        const events = d.events || [];
        const typeColors = {config_change:'#60a5fa', ssh_execute:'#4ade80', action_approved:'#fbbf24', action_rejected:'#f87171'};
        document.getElementById('audit-trail-body').innerHTML = events.length
            ? events.map(e => `<div style="display:flex;gap:10px;padding:4px 0;border-bottom:1px solid var(--border);font-size:.78em;align-items:baseline;">
                <span style="color:var(--text-muted);flex-shrink:0;width:130px;">${(e.at||'').slice(0,16).replace('T',' ')}</span>
                <span style="flex-shrink:0;width:80px;overflow:hidden;text-overflow:ellipsis;color:var(--accent);">${_escape(e.actor||'?')}</span>
                <span style="flex-shrink:0;width:110px;color:${typeColors[e.type]||'#888'};font-size:.72em;font-weight:600;">${_escape(e.type||'')}</span>
                <span style="flex:1;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${_escape(e.detail||'')}">${_escape((e.detail||'').slice(0,80))}</span>
            </div>`).join('')
            : '<span style="color:var(--text-muted);">Žádné záznamy.</span>';
    } catch(e) {
        document.getElementById('audit-trail-body').innerHTML = `<span style="color:var(--error);">Chyba: ${_escape(e.message)}</span>`;
    }
}

// ── 301+303: Analytics tab — SLA + alert fatigue ─────────────────────────────
let _fatigue_chart = null;
async function _toolsAnalyticsLoad() {
    const days = document.getElementById('analytics-days')?.value || 30;
    const slaBody = document.getElementById('analytics-sla-body');
    if (slaBody) slaBody.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
    try {
        const [resR, fatR] = await Promise.all([
            fetch(`/api/analytics/resolution_time?days=${days}`).then(r => r.json()),
            fetch(`/api/analytics/alert_fatigue?days=${days}`).then(r => r.json()),
        ]);
        // 301: SLA resolution time table
        const stats = resR.stats || [];
        if (slaBody) slaBody.innerHTML = stats.length
            ? `<table style="width:100%;border-collapse:collapse;font-size:.8em;">
                <tr style="color:var(--text-muted);font-size:.72em;"><th style="text-align:left;padding:3px;">Plugin</th><th>Počet</th><th>Avg h</th><th>Min h</th><th>Max h</th></tr>
                ${stats.map(s => `<tr style="border-bottom:1px solid var(--border);">
                    <td style="padding:3px 6px;">${_escape(s.plugin||'?')}</td>
                    <td style="text-align:right;padding:3px 6px;">${s.count}</td>
                    <td style="text-align:right;padding:3px 6px;color:${s.avg_h>4?'var(--error)':'var(--success)'};">${s.avg_h}h</td>
                    <td style="text-align:right;padding:3px 6px;">${s.min_h}h</td>
                    <td style="text-align:right;padding:3px 6px;">${s.max_h}h</td>
                </tr>`).join('')}
               </table>`
            : '<span style="color:var(--text-muted);">Žádná data.</span>';
        // 303: Alert fatigue bar chart
        const fp = fatR.stats || [];
        const cvs = document.getElementById('analytics-fatigue-chart');
        if (cvs && fp.length && window.Chart) {
            if (_fatigue_chart) { _fatigue_chart.destroy(); _fatigue_chart = null; }
            _fatigue_chart = new Chart(cvs, {
                type: 'bar',
                data: {
                    labels: fp.map(f => f.plugin || '?'),
                    datasets: [{ data: fp.map(f => f.fp_count), backgroundColor: '#f97316bb', borderWidth: 0 }]
                },
                options: {
                    animation: false, responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { ticks: { color:'rgba(255,255,255,.45)', font:{size:8}, maxRotation:45 }, grid:{color:'rgba(255,255,255,.04)'} },
                        y: { beginAtZero: true, ticks: { color:'rgba(255,255,255,.45)', font:{size:8} }, grid:{color:'rgba(255,255,255,.04)'} }
                    }
                }
            });
        } else if (cvs && !fp.length) {
            cvs.parentElement.innerHTML = '<span style="color:var(--text-muted);font-size:.82em;">Žádné false positive záznamy.</span>';
        }
    } catch(e) {
        if (slaBody) slaBody.innerHTML = `<span style="color:var(--error);">Chyba: ${_escape(e.message)}</span>`;
    }
}

// ── 318: Health snapshot trend ────────────────────────────────────────────────
async function _loadHealthTrend() {
    const el = document.getElementById('dash-health-trend');
    if (!el || !window.Chart) return;
    try {
        const r = await fetch('/api/health/history?days=7');
        const d = await r.json();
        const hist = d.history || [];
        if (hist.length < 2) { el.innerHTML = ''; return; }
        const labels = hist.map(h => (h.ts||'').slice(5,13).replace('T',' '));
        const scores = hist.map(h => h.score);
        const issues = hist.map(h => h.issues);
        const cid = 'health-trend-chart';
        el.innerHTML = _dashWidget('healthtrend', 'heart-pulse', 'Zdraví systému (7 dní)',
            `<div style="position:relative;height:80px;"><canvas id="${cid}"></canvas></div>`,
            'margin-top:0;');
        requestAnimationFrame(() => {
            const cvs = document.getElementById(cid);
            if (!cvs) return;
            new Chart(cvs, {
                type: 'line',
                data: {
                    labels,
                    datasets: [
                        {label:'Skóre', data: scores, borderColor:'#4ade80', borderWidth:1.5, pointRadius:0, fill:false, yAxisID:'y'},
                        {label:'Issues', data: issues, borderColor:'#f87171', borderWidth:1, pointRadius:0, fill:false, yAxisID:'y1'},
                    ]
                },
                options: {
                    animation: false, responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: true, labels: { color:'rgba(255,255,255,.5)', font:{size:9}, boxWidth:10 } } },
                    scales: {
                        x: { display: false },
                        y: { min:0, max:100, ticks:{color:'rgba(255,255,255,.4)',font:{size:8},maxTicksLimit:3}, grid:{color:'rgba(255,255,255,.04)'} },
                        y1: { position:'right', beginAtZero:true, ticks:{color:'rgba(255,255,255,.4)',font:{size:8},maxTicksLimit:3}, grid:{display:false} }
                    }
                }
            });
        });
    } catch(e) { el.innerHTML = ''; }
}

// ── 302: Flapping issues dashboard widget ─────────────────────────────────────
async function _loadFlappingWidget() {
    const el = document.getElementById('dash-flapping-widget');
    if (!el) return;
    try {
        const r = await fetch('/api/analytics/flapping?days=7&min=3');
        const d = await r.json();
        const issues = (d.issues || []).slice(0, 5);
        if (!issues.length) { el.innerHTML = ''; return; }
        const rows = issues.map(i =>
            `<div style="display:flex;align-items:center;gap:10px;padding:4px 0;border-bottom:1px solid var(--border);font-size:.82em;">
                <span style="min-width:30px;text-align:right;font-weight:700;color:var(--error);">${i.count}×</span>
                <span style="min-width:90px;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_escape(i.host||'?')}</span>
                <span style="flex:1;color:var(--text-main);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_escape(i.plugin||'?')}</span>
                <span style="font-size:.72em;color:var(--text-muted);">${(i.last_resolved||'').slice(0,10)}</span>
            </div>`).join('');
        el.innerHTML = _dashWidget('flapping', 'rotate',
            'Top flapping issues (7 dní)',
            `<div style="font-size:.72em;display:flex;gap:16px;color:var(--text-muted);padding-bottom:4px;border-bottom:1px solid var(--border);margin-bottom:4px;">
                <span style="min-width:30px;text-align:right;">Počet</span><span style="min-width:90px;">Host</span><span>Plugin</span>
             </div>${rows}`,
            'margin-top:0;');
    } catch(e) { el.innerHTML = ''; }
}

// ── 313: DB retention panel ───────────────────────────────────────────────────
async function _loadDbStats() {
    const row = document.getElementById('db-stats-row');
    if (!row) return;
    try {
        const r = await fetch('/api/admin/db_stats');
        const d = await r.json();
        const kb = d.db_size_kb ?? 0;
        const fmt = kb >= 1024 ? `${(kb/1024).toFixed(1)} MB` : `${kb} KB`;
        const c = d.counts || {};
        row.innerHTML = [
            ['Velikost DB', fmt, kb > 100*1024 ? 'var(--error)' : 'var(--text-main)'],
            ['Issues', c.problems ?? 0, ''],
            ['Historie', c.issue_history ?? 0, ''],
            ['Telemetrie', (c.telemetry ?? 0).toLocaleString(), ''],
            ['Akce', c.actions ?? 0, ''],
        ].map(([k, v, col]) =>
            `<div style="background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:6px 8px;text-align:center;">
                <div style="font-size:1em;font-weight:700;color:${col||'var(--text-main)'};">${v}</div>
                <div style="font-size:.72em;color:var(--text-muted);">${k}</div>
            </div>`
        ).join('');
    } catch(e) {
        if (row) row.innerHTML = `<span style="color:var(--error);font-size:.82em;">Chyba: ${_escape(e.message)}</span>`;
    }
}

async function _runPruneNow() {
    const msg = document.getElementById('db-action-msg');
    if (msg) msg.textContent = 'Pruning…';
    try {
        const r = await fetch('/api/admin/prune', {method:'POST', headers:{'Content-Type':'application/json'}});
        const d = await r.json();
        if (msg) msg.textContent = d.message || (d.status === 'ok' ? 'Hotovo.' : d.error || 'Chyba');
        _loadDbStats();
    } catch(e) { if (msg) msg.textContent = `Chyba: ${e.message}`; }
}

async function _runAggregateNow() {
    const msg = document.getElementById('db-action-msg');
    if (msg) msg.textContent = 'Agreguje…';
    try {
        const r = await fetch('/api/admin/aggregate_telemetry', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}' });
        const d = await r.json();
        if (msg) msg.textContent = d.compressed_buckets !== undefined
            ? `Zkomprimováno ${d.compressed_buckets} bucket.` : (d.error || 'Chyba');
        _loadDbStats();
    } catch(e) { if (msg) msg.textContent = `Chyba: ${e.message}`; }
}

// ── 347: Bcrypt hash generátor ────────────────────────────────────────────────
function _openHashPwModal() {
    const panel = document.getElementById('hash-pw-panel');
    if (!panel) return;
    panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    if (panel.style.display === 'block') {
        document.getElementById('hash-pw-input')?.focus();
        document.getElementById('hash-pw-result').style.display = 'none';
    }
}

async function _generatePasswordHash() {
    const input = document.getElementById('hash-pw-input');
    const result = document.getElementById('hash-pw-result');
    const pw = input?.value || '';
    if (!pw || pw.length < 8) { _showToast('Heslo musí mít alespoň 8 znaků', 'error'); return; }
    try {
        const r = await fetch('/api/config/hash_password', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({password: pw})
        });
        const d = await r.json();
        if (d.hash) {
            result.style.display = 'block';
            result.innerHTML = `<div style="color:var(--text-muted);margin-bottom:4px;">Vložte do config.yaml:</div>` +
                `<div style="color:var(--accent); user-select:all;" onclick="navigator.clipboard.writeText(this.textContent);_showToast('Zkopírováno','success');" title="Klik = kopírovat">${_escape(d.hash)}</div>`;
            input.value = '';
        } else {
            _showToast(d.error || 'Chyba', 'error');
        }
    } catch(e) { _showToast(`Chyba: ${e.message}`, 'error'); }
}

// ── 346: 2FA / TOTP ──────────────────────────────────────────────────────────
async function _open2faModal() {
    const panel = document.getElementById('totp-panel');
    if (!panel) return;
    panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    if (panel.style.display === 'none') return;
    const statusRow = document.getElementById('totp-status-row');
    const setupArea = document.getElementById('totp-setup-area');
    statusRow.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Načítám…';
    try {
        const r = await fetch('/api/2fa/status');
        const d = await r.json();
        if (d.enabled) {
            statusRow.innerHTML = `<span style="color:var(--success);"><i class="fa-solid fa-shield-check"></i> 2FA je <b>aktivní</b></span>
                <button onclick="_totp2faDisable()" style="margin-left:12px;padding:4px 10px;background:transparent;border:1px solid var(--error);color:var(--error);border-radius:4px;cursor:pointer;font-size:.82em;">Deaktivovat</button>`;
            if (setupArea) setupArea.style.display = 'none';
        } else {
            statusRow.innerHTML = `<span style="color:var(--text-muted);"><i class="fa-solid fa-shield-xmark"></i> 2FA není aktivní</span>
                <button onclick="_totp2faStartSetup()" style="margin-left:12px;padding:4px 10px;background:var(--accent);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.82em;"><i class="fa-solid fa-plus"></i> Aktivovat</button>`;
            if (setupArea) setupArea.style.display = 'none';
        }
    } catch(e) {
        statusRow.innerHTML = `<span style="color:var(--error);">Chyba: ${_escape(e.message)}</span>`;
    }
}

async function _totp2faStartSetup() {
    const setupArea = document.getElementById('totp-setup-area');
    const msg = document.getElementById('totp-msg');
    setupArea.style.display = 'block';
    try {
        const r = await fetch('/api/2fa/setup', {method:'POST', headers:{'Content-Type':'application/json'}});
        const d = await r.json();
        document.getElementById('totp-qr').src = `data:image/png;base64,${d.qr_png_b64}`;
        document.getElementById('totp-status-row').innerHTML =
            `<span style="color:var(--text-muted);">Naskenuj QR a zadej kód pro potvrzení.</span>`;
        if (msg) msg.style.display = 'none';
    } catch(e) {
        if (msg) { msg.textContent = `Chyba: ${e.message}`; msg.style.display='block'; msg.style.color='var(--error)'; }
    }
}

async function _totp2faEnable() {
    const code = (document.getElementById('totp-confirm-code')?.value || '').trim();
    const msg = document.getElementById('totp-msg');
    if (!code) return;
    try {
        const r = await fetch('/api/2fa/enable', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({code})});
        const d = await r.json();
        if (d.status === 'ok') {
            _showToast('✓ 2FA aktivováno', 'success');
            _open2faModal();  // refresh stavu
        } else {
            if (msg) { msg.textContent = d.error || 'Neplatný kód'; msg.style.display='block'; msg.style.color='var(--error)'; }
        }
    } catch(e) {
        if (msg) { msg.textContent = `Chyba: ${e.message}`; msg.style.display='block'; msg.style.color='var(--error)'; }
    }
}

async function _totp2faDisable() {
    if (!confirm('Opravdu deaktivovat 2FA?')) return;
    try {
        const r = await fetch('/api/2fa/disable', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({})});
        const d = await r.json();
        if (d.status === 'ok') { _showToast('2FA deaktivováno', 'info'); _open2faModal(); }
        else _showToast(d.error || 'Chyba', 'error');
    } catch(e) { _showToast(`Chyba: ${e.message}`, 'error'); }
}

function closeSettingsModal() {
    document.getElementById('settings-modal').style.display = 'none';
    const p = document.getElementById('ssh-key-panel');
    if (p) p.style.display = 'none';
}

async function openSshKeyManager() {
    const modal = document.getElementById('ssh-key-modal');
    if (!modal) return;
    modal.style.display = 'flex';
    try {
        const r = await fetch('/api/system/ssh-config');
        const d = await r.json();
        const info = document.getElementById('ssh-key-modal-info');
        if (info) {
            const exists = d.key_exists
                ? `<span style="color:var(--success);">✓ Existuje</span>`
                : `<span style="color:var(--error);">✗ Soubor nenalezen</span>`;
            info.innerHTML = `
                <div><b>Cesta:</b> ${_escape(d.key_path || '—')}&nbsp;&nbsp;${exists}</div>
                ${d.fingerprint ? `<div style="margin-top:4px;"><b>Fingerprint:</b> ${_escape(d.fingerprint)}</div>` : ''}
                <div style="margin-top:4px;"><b>Uživatel:</b> ${_escape(d.ssh_user || 'root')}&nbsp;&nbsp;<b>Jump:</b> ${_escape(d.jump_host || '—')}</div>`;
            if (d.pubkey) {
                document.getElementById('skm-pubkey-text').textContent = d.pubkey;
                document.getElementById('skm-pubkey-display').style.display = 'block';
            }
        }
        document.getElementById('skm-user').value = d.ssh_user || 'root';
        document.getElementById('skm-jump').value = d.jump_host || '';
        document.getElementById('skm-keypath').value = d.key_path || '';
    } catch(e) {
        const info = document.getElementById('ssh-key-modal-info');
        if (info) info.innerHTML = `<span style="color:var(--error);">Chyba načtení: ${e}</span>`;
    }
}

function closeSshKeyModal() {
    const modal = document.getElementById('ssh-key-modal');
    if (modal) modal.style.display = 'none';
}

async function _skmCfgSave() {
    const user = document.getElementById('skm-user')?.value.trim();
    const jump = document.getElementById('skm-jump')?.value.trim();
    const keypath = document.getElementById('skm-keypath')?.value.trim();
    const msg = document.getElementById('skm-cfg-msg');
    try {
        const r = await fetch('/api/system/ssh-config', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ssh_user: user, jump_host: jump, key_path: keypath})
        });
        const d = await r.json();
        if (msg) {
            msg.style.color = d.status === 'ok' ? 'var(--success)' : 'var(--error)';
            msg.textContent = d.status === 'ok' ? '✓ Uloženo' : (d.error || 'Chyba');
        }
    } catch(e) { if (msg) { msg.style.color = 'var(--error)'; msg.textContent = String(e); } }
}

function _skmKeyFromFile(input) {
    const file = input.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = e => { document.getElementById('skm-pem').value = e.target.result; };
    reader.readAsText(file);
}

async function _skmKeyUpload() {
    const pem = document.getElementById('skm-pem')?.value.trim();
    const msg = document.getElementById('skm-key-msg');
    if (!pem) { if (msg) { msg.style.color='var(--error)'; msg.textContent='Vložte obsah klíče.'; } return; }
    try {
        if (msg) { msg.style.color='var(--text-muted)'; msg.textContent='Nahrávám…'; }
        const r = await fetch('/api/system/ssh-key', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({pem})
        });
        const d = await r.json();
        if (d.status === 'ok') {
            if (msg) { msg.style.color='var(--success)'; msg.textContent=`✓ Klíč nahrán: ${d.fingerprint}`; }
            document.getElementById('skm-pem').value = '';
            if (d.pubkey) {
                document.getElementById('skm-pubkey-text').textContent = d.pubkey;
                document.getElementById('skm-pubkey-display').style.display = 'block';
            }
            await openSshKeyManager();
        } else {
            if (msg) { msg.style.color='var(--error)'; msg.textContent=d.error || 'Chyba'; }
        }
    } catch(e) { if (msg) { msg.style.color='var(--error)'; msg.textContent=String(e); } }
}

async function _skmTestSsh() {
    const host = document.getElementById('skm-test-host')?.value.trim();
    const res = document.getElementById('skm-test-result');
    if (!host || !res) return;
    res.style.display = 'block';
    res.style.background = 'rgba(0,0,0,.15)';
    res.style.color = 'var(--text-muted)';
    res.textContent = 'Testuji…';
    try {
        const r = await fetch('/api/system/ssh-test', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({host})
        });
        const d = await r.json();
        res.style.background = d.ok ? 'rgba(76,175,80,.1)' : 'rgba(220,53,69,.1)';
        res.style.color = d.ok ? '#4caf50' : 'var(--error)';
        res.textContent = (d.ok ? '✓ ' : '✗ ') + (d.output || '');
    } catch(e) {
        res.style.background = 'rgba(220,53,69,.1)';
        res.style.color = 'var(--error)';
        res.textContent = '✗ ' + String(e);
    }
}

async function _sshCfgSave() {
    const user = document.getElementById('ssh-cfg-user')?.value.trim();
    const jump = document.getElementById('ssh-cfg-jump')?.value.trim();
    const keypath = document.getElementById('ssh-cfg-keypath')?.value.trim();
    const msg = document.getElementById('ssh-key-msg');
    try {
        const r = await fetch('/api/system/ssh-config', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ssh_user: user, jump_host: jump, key_path: keypath})
        });
        const d = await r.json();
        if (msg) {
            msg.style.color = d.status === 'ok' ? 'var(--success)' : 'var(--error)';
            msg.textContent = d.status === 'ok' ? '✓ Uloženo' : (d.error || 'Chyba');
        }
    } catch(e) { if (msg) { msg.style.color = 'var(--error)'; msg.textContent = String(e); } }
}

function _sshKeyFromFile(input) {
    const file = input.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = e => { document.getElementById('ssh-key-pem').value = e.target.result; };
    reader.readAsText(file);
}

async function _sshKeyUpload() {
    const pem = document.getElementById('ssh-key-pem')?.value.trim();
    const msg = document.getElementById('ssh-key-msg');
    if (!pem) { if (msg) { msg.style.color='var(--error)'; msg.textContent='Vložte obsah klíče.'; } return; }
    try {
        if (msg) { msg.style.color='var(--text-muted)'; msg.textContent='Nahrávám…'; }
        const r = await fetch('/api/system/ssh-key', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({pem})
        });
        const d = await r.json();
        if (d.status === 'ok') {
            if (msg) { msg.style.color='var(--success)'; msg.textContent=`✓ Klíč nahrán: ${d.fingerprint}`; }
            document.getElementById('ssh-key-pem').value = '';
            if (d.pubkey) {
                document.getElementById('ssh-pubkey-text').textContent = d.pubkey;
                document.getElementById('ssh-pubkey-display').style.display = 'block';
            }
            // Obnov info panel
            await openSshKeyManager();
        } else {
            if (msg) { msg.style.color='var(--error)'; msg.textContent=d.error || 'Chyba'; }
        }
    } catch(e) { if (msg) { msg.style.color='var(--error)'; msg.textContent=String(e); } }
}

function _cfgGet(id) { const el = document.getElementById(id); if (!el) return undefined; return el.type === 'checkbox' ? el.checked : el.value.trim(); }

// 206: Config restore
async function configRestore(input) {
    const msg = document.getElementById('cfg-restore-msg');
    const file = input.files[0];
    if (!file) return;
    if (!confirm(`Nahradit aktuální config.yaml souborem "${file.name}"? Sentinel automaticky načte novou konfiguraci.`)) { input.value = ''; return; }
    const fd = new FormData();
    fd.append('file', file);
    if (msg) { msg.style.color = 'var(--text-muted)'; msg.textContent = '⏳ Nahrávám…'; }
    try {
        const r = await fetch('/api/config/restore', {method: 'POST', body: fd});
        const d = await r.json();
        if (msg) {
            msg.style.color = d.status === 'ok' ? 'var(--success)' : 'var(--error)';
            msg.textContent = d.status === 'ok' ? '✅ Obnoveno' : `⚠ ${d.error || 'Chyba'}`;
        }
    } catch(e) {
        if (msg) { msg.style.color = 'var(--error)'; msg.textContent = `⚠ ${e}`; }
    }
    input.value = '';
}

async function saveSettings() {
    const msgEl = document.getElementById('settings-msg');
    msgEl.style.display = 'none';

    // Validation
    const numCtx = parseInt(_cfgGet('cfg-ollama-num-ctx'));
    const workerT = parseInt(_cfgGet('cfg-worker-threads'));
    if (isNaN(numCtx) || numCtx < 128) { _cfgShowMsg(msgEl, 'error', 'num_ctx musí být ≥ 128'); return; }
    if (isNaN(workerT) || workerT < 1) { _cfgShowMsg(msgEl, 'error', 'worker_threads musí být ≥ 1'); return; }

    const payload = {
        // Základní
        'instance_name':   _cfgGet('cfg-instance-name'),
        'worker_threads':  workerT,
        'log_dir':         _cfgGet('cfg-log-dir'),
        // AI
        'ollama_url':      _cfgGet('cfg-ollama-url'),
        'ollama_model':    _cfgGet('cfg-ollama-model'),
        'ollama_num_ctx':  numCtx,
        'hailo_ollama.enabled': _cfgGet('cfg-hailo-enabled'),
        'hailo_ollama.url':     _cfgGet('cfg-hailo-url'),
        'hailo_ollama.model':   _cfgGet('cfg-hailo-model'),
        'auto_severity_enabled':  _cfgGet('cfg-auto-severity'),
        'auto_duplicate_enabled': _cfgGet('cfg-auto-duplicate'),
        // LDAP
        'ldap.enabled':  _cfgGet('cfg-ldap-enabled'),
        'ldap.host':     _cfgGet('cfg-ldap-host'),
        'ldap.port':     parseInt(_cfgGet('cfg-ldap-port')) || 389,
        'ldap.use_ssl':  _cfgGet('cfg-ldap-ssl'),
        'ldap.base_dn':  _cfgGet('cfg-ldap-basedn'),
        'ldap.bind_dn':  _cfgGet('cfg-ldap-binddn'),
    };

    // Only include password fields if non-empty
    const ldapPw = _cfgGet('cfg-ldap-bindpw');
    if (ldapPw) payload['ldap.bind_password'] = ldapPw;

    // 209: Issue expiry — sestavit dict jen z neprázdných hodnot
    const expiryDict = {};
    ['infra','agent','security','root'].forEach(ch => {
        const v = parseInt(_cfgGet(`cfg-expiry-${ch}`));
        if (v > 0) expiryDict[ch] = v;
    });
    payload['issue_expiry_days'] = expiryDict;

    try {
        const r = await fetch('/api/config/update', {
            method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)
        });
        const d = await r.json();
        if (d.status === 'ok' || d.status === 'warning') {
            _cfgShowMsg(msgEl, 'ok', d.status === 'ok' ? '✓ Uloženo' : `⚠ Uloženo v paměti: ${d.message || ''}`);
            // Restart after save
            if (document.getElementById('cfg-restart-after-save')?.checked) {
                msgEl.textContent += ' — restartuju…';
                fetch('/api/system/restart', {method:'POST'}).catch(()=>{});
                setTimeout(() => { msgEl.textContent += ' Stránka se znovu načte za 5 s…'; }, 500);
                setTimeout(() => window.location.reload(), 6000);
            }
        } else {
            _cfgShowMsg(msgEl, 'error', d.message || 'Chyba uložení');
        }
    } catch(e) {
        _cfgShowMsg(msgEl, 'error', `Síťová chyba: ${e}`);
    }
}

function _cfgShowMsg(el, type, text) {
    el.style.display = 'block';
    el.style.background = type === 'ok' ? 'rgba(16,124,16,0.15)' : 'rgba(197,15,31,0.12)';
    el.style.color = type === 'ok' ? 'var(--success)' : 'var(--error)';
    el.style.border = type === 'ok' ? '1px solid rgba(16,124,16,0.3)' : '1px solid rgba(197,15,31,0.3)';
    el.textContent = text;
}

// ─── Unified Tools Modal (Monitoring & Nástroje) ─────────────────────────────

let _activeToolsTab = 'agent_health';
let _toolsTabLoaded = new Set();

function openToolsModal(tab = 'agent_health') {
    document.getElementById('tools-modal').style.display = 'flex';
    _tabDragRestoreOrder();
    switchToolsTab(tab);
}

// 133: Drag & drop přeřazení záložek Tools modalu
let _tabDragSrc = null;
function _tabDragInit() {
    const bar = document.getElementById('tools-tabs-bar');
    if (!bar || bar.dataset.dragInited) return;
    bar.dataset.dragInited = '1';
    bar.addEventListener('dragstart', e => {
        const btn = e.target.closest('.tools-tab');
        if (!btn) return;
        _tabDragSrc = btn;
        btn.style.opacity = '.5';
        e.dataTransfer.effectAllowed = 'move';
    });
    bar.addEventListener('dragend', e => {
        const btn = e.target.closest('.tools-tab');
        if (btn) btn.style.opacity = '';
        _tabDragSrc = null;
    });
    bar.addEventListener('dragover', e => {
        e.preventDefault();
        const btn = e.target.closest('.tools-tab');
        if (!btn || btn === _tabDragSrc) return;
        const rect = btn.getBoundingClientRect();
        const after = e.clientX > rect.left + rect.width / 2;
        bar.insertBefore(_tabDragSrc, after ? btn.nextSibling : btn);
    });
    bar.addEventListener('drop', e => {
        e.preventDefault();
        _tabDragSaveOrder();
    });
    // Make tabs draggable
    bar.querySelectorAll('.tools-tab').forEach(b => { b.draggable = true; b.style.cursor = 'grab'; });
}
function _tabDragSaveOrder() {
    const bar = document.getElementById('tools-tabs-bar');
    if (!bar) return;
    const order = [...bar.querySelectorAll('.tools-tab')].map(b => b.id.replace('tools-tab-', ''));
    localStorage.setItem('tools_tab_order', JSON.stringify(order));
}
function _tabDragRestoreOrder() {
    const bar = document.getElementById('tools-tabs-bar');
    if (!bar) return;
    _tabDragInit();
    const saved = localStorage.getItem('tools_tab_order');
    if (!saved) return;
    try {
        const order = JSON.parse(saved);
        order.forEach(id => {
            const btn = document.getElementById(`tools-tab-${id}`);
            if (btn) bar.appendChild(btn);
        });
    } catch(e) { /* ignore corrupt data */ }
}

let _toolsRefreshInterval = null;
function closeToolsModal() {
    document.getElementById('tools-modal').style.display = 'none';
    _toolsTabLoaded.clear();
    if (_timelineChart) { _timelineChart.destroy(); _timelineChart = null; }
    if (_toolsRefreshInterval) { clearInterval(_toolsRefreshInterval); _toolsRefreshInterval = null; }
}

function switchToolsTab(tab) {
    _activeToolsTab = tab;
    document.querySelectorAll('.tools-tab').forEach(b => b.classList.remove('active'));
    const btn = document.getElementById(`tools-tab-${tab}`);
    if (btn) btn.classList.add('active');
    document.querySelectorAll('[id^="tools-pane-"]').forEach(p => p.style.display = 'none');
    const pane = document.getElementById(`tools-pane-${tab}`);
    if (pane) pane.style.display = '';
    if (!_toolsTabLoaded.has(tab)) {
        _toolsTabLoaded.add(tab);
        if (tab === 'agent_health') {
            loadAgentHealth();
            if (_toolsRefreshInterval) clearInterval(_toolsRefreshInterval);
            _toolsRefreshInterval = setInterval(() => { if (_activeToolsTab === 'agent_health') loadAgentHealth(true); }, 30000);
        }
        else if (tab === 'timeline') loadTimeline(7);
        else if (tab === 'plugin_stats') loadPluginStats();
        else if (tab === 'maint') loadMaintRules();
        else if (tab === 'kb') _kbLoadFiles();
        else if (tab === 'issue_history') _ihSearch();
        else if (tab === 'suppress') _supLoad();
        else if (tab === 'fp') _fpLoadList();
        else if (tab === 'depgraph') _depGraphLoad();
        else if (tab === 'geomap') _geoMapLoad();
        else if (tab === 'wiki') _wikiLoad();
        // Inline panes (dříve otvíraly vlastní modaly)
        else if (tab === 'heatmap') _toolsHeatmapLoad();
        else if (tab === 'graf') _toolsGrafLoad();
        else if (tab === 'analytics') _toolsAnalyticsLoad();
        else if (tab === 'runbooks') _rbLoad();
        else if (tab === 'config_diff') _toolsConfigDiffLoad();
        else if (tab === 'topology') _toolsTopologyLoad();
        else if (tab === 'changelog') _toolsChangelogLoad();
        else if (tab === 'ai_trend') _toolsAiTrendLoad();
        else if (tab === 'capacity') { /* on-demand only */ }
        else if (tab === 'compare') { /* on-demand only */ }
        else if (tab === 'patterns') _toolsPatternsLoad();
        else if (tab === 'srovnat') _toolsSrovnatLoad();
    }
}

let _ihSearchTimer = null;
function _ihSearch() {
    clearTimeout(_ihSearchTimer);
    _ihSearchTimer = setTimeout(_ihLoad, 300);
}

async function _ihLoad() {
    const el = document.getElementById('ih-results');
    if (!el) return;
    const q = document.getElementById('ih-search')?.value.trim() || '';
    const days = document.getElementById('ih-days')?.value || '30';
    const channel = document.getElementById('ih-channel')?.value || '';
    el.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i>`;
    try {
        const params = new URLSearchParams({days, limit: 200});
        if (q) params.set('q', q);
        if (channel) params.set('channel', channel);
        const r = await fetch(`/api/issues/history?${params}`);
        const d = await r.json();
        const items = d.items || [];
        if (!items.length) { el.innerHTML = `<div style="color:var(--text-muted);padding:20px;text-align:center;">Žádné záznamy</div>`; return; }
        const chColors = {security:'#f87171',infra:'#4da6ff',agent:'#28a745',root:'#ffc107'};
        el.innerHTML = items.map(i => {
            const col = chColors[(i.channel_type||'').toLowerCase()] || '#888';
            const isActive = i.issue_status === 'active';
            const ts = isActive
                ? (i.last_seen||'').slice(0,16).replace('T',' ')
                : (i.resolved_at||'').slice(0,16).replace('T',' ');
            const badge = isActive
                ? `<span style="background:#f87171;color:#fff;font-size:.68rem;padding:1px 5px;border-radius:3px;margin-left:5px;">AKTIVNÍ</span>`
                : `<span style="background:#28a745;color:#fff;font-size:.68rem;padding:1px 5px;border-radius:3px;margin-left:5px;">VYŘEŠEN</span>`;
            return `<div style="border-left:3px solid ${col};padding:6px 10px;margin-bottom:5px;background:rgba(255,255,255,.02);border-radius:0 4px 4px 0;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px;">
                    <span style="color:${col};font-weight:700;font-size:.75rem;">${(i.channel_type||'?').toUpperCase()}${badge}</span>
                    <span style="color:#666;font-size:.75rem;">${ts}</span>
                </div>
                <div style="color:var(--text-main);font-size:.83rem;"><b>${_escape(i.host||'?')}</b>: ${_escape((i.last_line||'').slice(0,120))}</div>
            </div>`;
        }).join('') + `<div style="color:#666;font-size:.78rem;margin-top:8px;text-align:right;">${items.length} záznamů</div>`;
    } catch(e) {
        el.innerHTML = `<div style="color:var(--error);">Chyba: ${_escape(e.message)}</div>`;
    }
}

function loadPluginStats() {
    openPluginStatsModal(true);
}

// ── Tools modal inline pane loaders ──────────────────────────────────────────
async function _toolsHeatmapLoad() {
    const el = document.getElementById('tools-heatmap-body');
    if (!el) return;
    const days = parseInt(document.getElementById('heatmap-days-sel')?.value || 7);
    el.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>';
    try {
        const r = await fetch(`/api/alerts/host_heatmap?days=${days}`);
        const d = await r.json();
        const data = d.data || {};

        // Description header
        const desc = `<div style="background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:10px 14px;margin-bottom:12px;font-size:.82rem;color:var(--text-muted);line-height:1.5;">
            <i class="fa-solid fa-fire" style="color:#e25;margin-right:6px;"></i>
            <b style="color:var(--text-main);">Host Heatmap</b> — každá buňka = počet nových alertů za jeden den pro daný host.
            Červenější = více alertů. Klikni na buňku pro detail. Řádky = hosté (max 25), sloupce = dny. Pomáhá identifikovat,
            který host a kdy generuje nejvíce šumu.
        </div>`;

        if (!Object.keys(data).length) { el.innerHTML = desc + '<div style="color:var(--text-muted);padding:20px;text-align:center;"><i class="fa-solid fa-check-circle" style="color:var(--success);"></i> Žádné alerty v daném období.</div>'; return; }

        const hosts = Object.keys(data).sort().slice(0, 25);
        const allDays = [...new Set(hosts.flatMap(h => Object.keys(data[h] || {})))].sort().slice(-days);
        const maxVal = Math.max(1, ...hosts.flatMap(h => Object.values(data[h] || {}).map(Number)));

        const CELL = 18, GAP = 3, LABEL_W = 130, PAD = 10;
        const cols = allDays.length;
        const rows = hosts.length;
        const W = LABEL_W + cols * (CELL + GAP) + PAD;
        const H = PAD + 24 + rows * (CELL + GAP) + PAD;

        el.innerHTML = desc + `<canvas id="heatmap-canvas" width="${W}" height="${H}" style="max-width:100%;display:block;"></canvas>
        <div style="display:flex;gap:12px;align-items:center;margin-top:8px;font-size:.72em;color:var(--text-muted);">
            <span>0</span>
            <div style="display:flex;gap:2px;">${[0,.15,.35,.6,.85,1].map(v=>`<span style="display:inline-block;width:14px;height:14px;border-radius:3px;background:rgba(220,53,69,${v===0?0.05:v});"></span>`).join('')}</div>
            <span>${maxVal}+</span>
        </div>`;

        const canvas = document.getElementById('heatmap-canvas');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const dpr = window.devicePixelRatio || 1;
        canvas.width = W * dpr; canvas.height = H * dpr;
        canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
        ctx.scale(dpr, dpr);

        ctx.fillStyle = '#0f0f0f';
        ctx.fillRect(0, 0, W, H);

        // Header: day labels
        ctx.font = '9px monospace';
        ctx.fillStyle = '#666';
        ctx.textAlign = 'center';
        allDays.forEach((day, ci) => {
            const x = LABEL_W + ci * (CELL + GAP) + CELL / 2;
            if (ci % Math.max(1, Math.floor(cols / 8)) === 0)
                ctx.fillText(day.slice(5), x, PAD + 12);
        });

        // Rows: host + cells
        hosts.forEach((host, ri) => {
            const y = PAD + 24 + ri * (CELL + GAP);
            // Label
            ctx.font = '10px monospace';
            ctx.fillStyle = '#4da6ff';
            ctx.textAlign = 'right';
            ctx.fillText(host.length > 14 ? host.slice(0, 13) + '…' : host, LABEL_W - 6, y + CELL - 5);
            // Cells
            allDays.forEach((day, ci) => {
                const v = Number(data[host]?.[day] || 0);
                const intensity = v === 0 ? 0 : Math.min(1, 0.15 + (v / maxVal) * 0.85);
                ctx.fillStyle = v === 0 ? 'rgba(255,255,255,0.04)' : `rgba(220,53,69,${intensity})`;
                const x = LABEL_W + ci * (CELL + GAP);
                ctx.beginPath();
                ctx.roundRect(x, y, CELL, CELL, 3);
                ctx.fill();
                if (v > 0 && CELL > 14) {
                    ctx.fillStyle = intensity > 0.55 ? '#fff' : '#ddd';
                    ctx.font = '8px sans-serif';
                    ctx.textAlign = 'center';
                    ctx.fillText(v > 99 ? '99+' : String(v), x + CELL / 2, y + CELL - 4);
                }
            });
        });
    } catch(e) { el.innerHTML = `<div style="color:var(--error);">Chyba: ${e}</div>`; }
}

async function _toolsGrafLoad() {
    const el = document.getElementById('tools-graf-body');
    if (!el) return;
    el.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>';
    try {
        const pgR = await fetch('/api/plugins/graph').then(r=>r.json()).catch(()=>({nodes:[],edges:[]}));
        const nodes = pgR.nodes || [];
        const edges = pgR.edges || [];
        el.innerHTML = '<canvas id="graf-dep-canvas" style="width:100%;display:block;"></canvas>';
        _drawDepGraph(nodes, edges);
    } catch(e) { el.innerHTML = `<div style="color:var(--error);">Chyba: ${e}</div>`; }
}

async function _toolsConfigDiffLoad() {
    const el = document.getElementById('tools-configdiff-body');
    if (!el) return;
    // 333: Load config history for snapshot diff selector
    let histHtml = '';
    try {
        const hr = await fetch('/api/config/history');
        const hd = await hr.json();
        const hist = hd.history || [];
        if (hist.length >= 2) {
            const opts = hist.map(h => `<option value="${h.id}">#${h.id} ${(h.timestamp||'').slice(0,16)} ${h.hash?.slice(0,6)||''}</option>`).join('');
            histHtml = `<div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap;">
                <select id="diff-from" style="padding:4px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:4px;font-size:.82em;">${opts}</select>
                <span style="color:var(--text-muted);">→</span>
                <select id="diff-to" style="padding:4px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:4px;font-size:.82em;">${opts}</select>
                <button onclick="_showSnapshotDiff()" style="padding:4px 10px;background:transparent;border:1px solid var(--accent);color:var(--accent);border-radius:4px;cursor:pointer;font-size:.82em;">Diff snapshotů</button>
            </div>`;
        }
    } catch {}
    el.innerHTML = histHtml + '<div id="diff-result"><i class="fa-solid fa-spinner fa-spin"></i></div>';
    const renderDiff = (diff) => {
        const lines = (diff||'').split('\n').map(l => {
            const c = l.startsWith('+') ? '#4caf50' : l.startsWith('-') ? '#f87171' : l.startsWith('@') ? '#ffc107' : 'var(--text-muted)';
            return `<div style="color:${c};font-family:monospace;font-size:.75em;white-space:pre;">${_escape(l)}</div>`;
        }).join('');
        return `<div style="background:rgba(0,0,0,.2);border:1px solid var(--border);border-radius:4px;padding:10px;max-height:360px;overflow-y:auto;">${lines}</div>`;
    };
    try {
        const r = await fetch('/api/config/diff');
        const d = await r.json();
        const result = document.getElementById('diff-result');
        if (result) result.innerHTML = d.has_diff ? renderDiff(d.diff) : '<div style="color:var(--success);padding:16px;"><i class="fa-solid fa-check-circle"></i> Config je identický s příkladem.</div>';
    } catch(e) { const r = document.getElementById('diff-result'); if (r) r.innerHTML = `<div style="color:var(--error);">Chyba: ${_escape(e.message)}</div>`; }
}

async function _showSnapshotDiff() {
    const from = document.getElementById('diff-from')?.value;
    const to   = document.getElementById('diff-to')?.value;
    const result = document.getElementById('diff-result');
    if (!from || !to || from === to) { if (result) result.innerHTML = '<span style="color:var(--error);">Vyber dvě různé verze.</span>'; return; }
    if (result) result.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
    try {
        const r = await fetch(`/api/config/history/diff?from=${from}&to=${to}`);
        const d = await r.json();
        const lines = (d.diff||'').split('\n').map(l => {
            const c = l.startsWith('+') ? '#4caf50' : l.startsWith('-') ? '#f87171' : l.startsWith('@') ? '#ffc107' : 'var(--text-muted)';
            return `<div style="color:${c};font-family:monospace;font-size:.75em;white-space:pre;">${_escape(l)}</div>`;
        }).join('');
        if (result) result.innerHTML = d.has_diff
            ? `<div style="background:rgba(0,0,0,.2);border:1px solid var(--border);border-radius:4px;padding:10px;max-height:360px;overflow-y:auto;">${lines}</div>`
            : '<div style="color:var(--success);padding:8px;"><i class="fa-solid fa-check-circle"></i> Snapshoty jsou identické.</div>';
    } catch(e) { if (result) result.innerHTML = `<span style="color:var(--error);">Chyba: ${_escape(e.message)}</span>`; }
}

function _drawDepGraph(nodes, edges) {
    const cvs = document.getElementById('graf-dep-canvas');
    if (!cvs) return;

    // Collect unique items per column
    const logSet = new Set(), plugSet = new Set(), chanSet = new Set();
    edges.forEach(e => {
        if (e.from?.startsWith('log:')) logSet.add(e.from.replace('log:', ''));
        if (e.to?.startsWith('channel:')) chanSet.add(e.to.replace('channel:', ''));
    });
    nodes.filter(n => n.type === 'plugin').forEach(n => plugSet.add(n.id));

    const logs = [...logSet], plugs = [...plugSet], chans = [...chanSet];

    const ROW_H = 32, PAD = 16, COL_W = 200, GAP = 80;
    const rows = Math.max(logs.length, plugs.length, chans.length, 1);
    const W = COL_W * 3 + GAP * 2 + PAD * 2;
    const H = rows * ROW_H + PAD * 2 + 24;
    const dpr = window.devicePixelRatio || 1;
    cvs.width = W * dpr; cvs.height = H * dpr;
    cvs.style.width = W + 'px'; cvs.style.height = H + 'px';
    const ctx = cvs.getContext('2d');
    ctx.scale(dpr, dpr);

    const colX = [PAD, PAD + COL_W + GAP, PAD + (COL_W + GAP) * 2];
    const colColor = ['#28a745', '#0078d4', '#fd7e14'];
    const colLabel = ['Log zdroj', 'Plugin', 'Kanál'];
    const colItems = [logs, plugs, chans];
    const nodePos = [{}, {}, {}]; // colIdx → label → {x,y}

    // Column headers
    ctx.font = 'bold 11px monospace';
    colItems.forEach((items, ci) => {
        ctx.fillStyle = colColor[ci];
        ctx.fillText(colLabel[ci], colX[ci] + 4, PAD - 4);
    });

    // Draw nodes
    colItems.forEach((items, ci) => {
        items.forEach((label, ri) => {
            const x = colX[ci], y = PAD + 20 + ri * ROW_H;
            const bw = COL_W - 8, bh = 24;
            ctx.fillStyle = `rgba(${ci===0?'40,167,69':ci===1?'0,120,212':'253,126,20'},.12)`;
            ctx.strokeStyle = colColor[ci] + '66';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.roundRect(x, y, bw, bh, 4);
            ctx.fill(); ctx.stroke();
            ctx.fillStyle = ci===0?'#7dd399':ci===1?'#4da6ff':'#ffa94d';
            ctx.font = '10px monospace';
            const short = label.length > 22 ? label.slice(-22) : label;
            ctx.fillText(short, x + 6, y + 15);
            nodePos[ci][label] = {x: x + bw, y: y + 12};
        });
    });

    // Draw edges log→plugin
    edges.forEach(e => {
        if (!e.from?.startsWith('log:') || e.to?.startsWith('channel:')) return;
        const logLabel = e.from.replace('log:', '');
        const plugLabel = e.to;
        if (!nodePos[0][logLabel] || !nodePos[1][plugLabel]) return;
        const s = nodePos[0][logLabel], t = {x: colX[1], y: nodePos[1][plugLabel].y};
        ctx.strokeStyle = '#28a74544'; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(s.x, s.y);
        const mx = (s.x + t.x) / 2;
        ctx.bezierCurveTo(mx, s.y, mx, t.y, t.x, t.y);
        ctx.stroke();
    });

    // Draw edges plugin→channel
    edges.forEach(e => {
        if (!e.to?.startsWith('channel:')) return;
        const plugLabel = e.from;
        const chanLabel = e.to.replace('channel:', '');
        if (!nodePos[1][plugLabel] || !nodePos[2][chanLabel]) return;
        const s = {x: colX[1] + COL_W - 8, y: nodePos[1][plugLabel].y};
        const t = {x: colX[2], y: nodePos[2][chanLabel].y};
        ctx.strokeStyle = '#fd7e1444'; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(s.x, s.y);
        const mx = (s.x + t.x) / 2;
        ctx.bezierCurveTo(mx, s.y, mx, t.y, t.x, t.y);
        ctx.stroke();
    });

    if (!logs.length && !plugs.length) {
        ctx.fillStyle = '#666'; ctx.font = '12px sans-serif';
        ctx.fillText('Žádná data ze /api/plugins/graph', PAD, H / 2);
    }
}

async function _depGraphLoad() {
    const cvs = document.getElementById('depgraph-canvas');
    const legend = document.getElementById('depgraph-legend');
    if (!cvs) return;
    cvs.style.display = 'block';

    // Fetch all active issues with depends_on
    let issues = [];
    try {
        const r = await fetch('/api/issues/with_deps');
        const d = await r.json();
        issues = d.issues || [];
    } catch(e) { }

    // Also collect all issues referenced as dependencies
    const allKeys = new Set();
    const depMap = {}; // key → [dep_key, ...]
    const keyInfo = {};

    issues.forEach(i => {
        allKeys.add(i.key);
        keyInfo[i.key] = i;
        const deps = Array.isArray(i.depends_on) ? i.depends_on : [];
        if (deps.length) depMap[i.key] = deps;
        deps.forEach(d => allKeys.add(d));
    });

    if (!allKeys.size) {
        const ctx = cvs.getContext('2d');
        cvs.width = 400; cvs.height = 80;
        cvs.style.width = '100%'; cvs.style.height = '80px';
        ctx.fillStyle = '#666'; ctx.font = '13px sans-serif';
        ctx.fillText('Žádné issues se závislostmi.', 20, 44);
        if (legend) legend.textContent = '';
        return;
    }

    // Layout: force-directed simple grid
    const nodes = [...allKeys].map((k, idx) => ({
        key: k, info: keyInfo[k] || null,
        x: 80 + (idx % 5) * 150, y: 60 + Math.floor(idx / 5) * 90
    }));
    const nodeMap = Object.fromEntries(nodes.map(n => [n.key, n]));

    const W = Math.max(500, nodes.length * 60);
    const H = Math.max(200, Math.ceil(nodes.length / 5) * 100 + 60);
    const dpr = window.devicePixelRatio || 1;
    cvs.width = W * dpr; cvs.height = H * dpr;
    cvs.style.width = W + 'px'; cvs.style.height = H + 'px';
    const ctx = cvs.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);

    const statusColor = {active:'#dc3545', acknowledged:'#ffc107', validating:'#0078d4', resolved:'#28a745'};

    // Draw edges
    ctx.lineWidth = 1.5;
    Object.entries(depMap).forEach(([fromKey, deps]) => {
        const from = nodeMap[fromKey];
        if (!from) return;
        deps.forEach(toKey => {
            const to = nodeMap[toKey];
            if (!to) return;
            ctx.strokeStyle = 'rgba(0,120,212,.45)';
            ctx.beginPath();
            ctx.moveTo(from.x, from.y);
            // Bezier curve
            const mx = (from.x + to.x) / 2, my = (from.y + to.y) / 2 - 20;
            ctx.quadraticCurveTo(mx, my, to.x, to.y);
            ctx.stroke();
            // Arrowhead
            const angle = Math.atan2(to.y - my, to.x - mx);
            ctx.fillStyle = 'rgba(0,120,212,.7)';
            ctx.beginPath();
            ctx.moveTo(to.x, to.y);
            ctx.lineTo(to.x - 9 * Math.cos(angle - 0.4), to.y - 9 * Math.sin(angle - 0.4));
            ctx.lineTo(to.x - 9 * Math.cos(angle + 0.4), to.y - 9 * Math.sin(angle + 0.4));
            ctx.closePath(); ctx.fill();
        });
    });

    // Draw nodes
    nodes.forEach(n => {
        const col = n.info ? (statusColor[n.info.status] || '#888') : '#555';
        const label = n.info ? `${(n.info.host||'?').substring(0,12)}` : n.key.substring(0,10)+'…';
        const plugin = n.info ? (n.info.plugin_name || '').substring(0,10) : '';

        ctx.fillStyle = col + '22';
        ctx.strokeStyle = col;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.roundRect(n.x - 55, n.y - 18, 110, 36, 6);
        ctx.fill(); ctx.stroke();

        ctx.fillStyle = col;
        ctx.font = 'bold 10px monospace';
        ctx.textAlign = 'center';
        ctx.fillText(label, n.x, n.y - 4);
        ctx.fillStyle = '#888';
        ctx.font = '9px monospace';
        ctx.fillText(plugin, n.x, n.y + 10);
    });
    ctx.textAlign = 'left';

    if (legend) legend.textContent = `${allKeys.size} issues • ${Object.values(depMap).flat().length} závislostí`;
}

let _leafletMap = null;

async function _geoMapLoad(forceReload) {
    const container = document.getElementById('geomap-container');
    const legend = document.getElementById('geomap-legend');
    if (!container) return;

    // Load Leaflet CSS + JS once
    if (!document.getElementById('leaflet-css')) {
        const lnk = document.createElement('link');
        lnk.id = 'leaflet-css'; lnk.rel = 'stylesheet';
        lnk.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
        document.head.appendChild(lnk);
    }
    const _initMap = () => {
        const mapDiv = document.createElement('div');
        mapDiv.id = 'leaflet-map-div';
        mapDiv.style.cssText = 'width:100%;height:100%;';
        container.innerHTML = '';
        container.appendChild(mapDiv);

        _leafletMap = L.map('leaflet-map-div', {zoomControl: true}).setView([30, 10], 2);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors',
            maxZoom: 18
        }).addTo(_leafletMap);
        return _leafletMap;
    };

    const _doLoad = async () => {
        if (forceReload && _leafletMap) {
            _leafletMap.eachLayer(l => { if (l instanceof L.Marker) _leafletMap.removeLayer(l); });
        }
        const map = _leafletMap || _initMap();

        try {
            const r = await fetch('/api/agents/geomap');
            const d = await r.json();
            const agents = d.agents || [];
            const placed = [], noGeo = [];

            agents.forEach(ag => {
                if (ag.geo && ag.geo.lat != null) {
                    placed.push(ag);
                    const color = ag.status === 'ONLINE' ? '#107c10' : '#c50f1f';
                    const icon = L.divIcon({
                        className: '',
                        html: `<div style="width:14px;height:14px;border-radius:50%;background:${color};border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.5);"></div>`,
                        iconSize: [14, 14], iconAnchor: [7, 7]
                    });
                    L.marker([ag.geo.lat, ag.geo.lon], {icon})
                        .bindPopup(`<b>${ag.hostname}</b><br>${ag.geo.city||''}, ${ag.geo.country||''}<br>IP: ${ag.ip||'—'}<br>Stav: ${ag.status}`)
                        .addTo(map);
                } else {
                    noGeo.push(ag);
                }
            });

            if (legend) {
                legend.innerHTML = `
                    <span><i class="fa-solid fa-circle" style="color:#107c10;font-size:.7em;"></i> Online (${agents.filter(a=>a.status==='ONLINE').length})</span>
                    <span><i class="fa-solid fa-circle" style="color:#c50f1f;font-size:.7em;"></i> Offline (${agents.filter(a=>a.status!=='ONLINE').length})</span>
                    <span style="color:#555;">Geo: ${placed.length} • Bez geo: ${noGeo.length}${noGeo.length?(' ('+noGeo.map(a=>a.hostname).slice(0,4).join(', ')+(noGeo.length>4?'…':'')+')'):''}</span>`;
            }
        } catch(e) {
            if (legend) legend.textContent = `Chyba: ${e}`;
        }
    };

    if (typeof L === 'undefined') {
        const script = document.createElement('script');
        script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
        script.onload = _doLoad;
        document.head.appendChild(script);
    } else {
        await _doLoad();
    }

    // Invalidate size after render (Leaflet needs this when container was hidden)
    setTimeout(() => { if (_leafletMap) _leafletMap.invalidateSize(); }, 200);
}

async function _toolsTopologyLoad() {
    const el = document.getElementById('tools-topology-body');
    if (!el) return;
    el.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>';
    try {
        const r = await fetch('/api/topology/data');
        const d = await r.json();
        _renderTopologyCanvas(el, d.nodes || [], d.edges || [], d.updated_at);
    } catch(e) { el.innerHTML = `<div style="color:var(--error);">Chyba: ${e}</div>`; }
}

function _renderTopologyCanvas(container, nodes, edges, updatedAt) {
    if (!nodes.length) {
        container.innerHTML = '<div style="color:var(--text-muted);padding:16px;">Žádná topologická data. Přidej agenty nebo manuální linky v config.yaml (topology.manual_links).</div>';
        return;
    }

    // Build adjacency for force-directed layout
    const W = container.clientWidth || 700, H = 420;
    const dpr = window.devicePixelRatio || 1;

    // Assign initial positions — groups in center, agents around them
    const nodeMap = {};
    const groups = nodes.filter(n => n.type === 'group');
    const agentNodes = nodes.filter(n => n.type === 'agent');
    const otherNodes = nodes.filter(n => n.type !== 'group' && n.type !== 'agent');

    const cx = W / 2, cy = H / 2;
    const grpR = Math.min(cx, cy) * 0.5;
    const agR  = Math.min(cx, cy) * 0.85;

    groups.forEach((n, i) => {
        const a = (2 * Math.PI * i) / Math.max(groups.length, 1) - Math.PI / 2;
        n.x = cx + grpR * Math.cos(a);
        n.y = cy + grpR * Math.sin(a);
        n.vx = 0; n.vy = 0;
        nodeMap[n.id] = n;
    });
    // Group agents around their group node
    const agentsByGroup = {};
    agentNodes.forEach(n => {
        const grpId = `__grp_${n.group}`;
        if (!agentsByGroup[grpId]) agentsByGroup[grpId] = [];
        agentsByGroup[grpId].push(n);
    });
    Object.entries(agentsByGroup).forEach(([grpId, ags]) => {
        const grpNode = nodeMap[grpId];
        const r = 80 + ags.length * 10;
        ags.forEach((n, i) => {
            const a = (2 * Math.PI * i) / ags.length + (grpNode ? Math.atan2(grpNode.y - cy, grpNode.x - cx) : 0);
            n.x = (grpNode ? grpNode.x : cx) + r * Math.cos(a);
            n.y = (grpNode ? grpNode.y : cy) + r * Math.sin(a);
            n.vx = 0; n.vy = 0;
            nodeMap[n.id] = n;
        });
    });
    otherNodes.forEach((n, i) => {
        n.x = 60 + (i % 6) * 110; n.y = H - 50;
        n.vx = 0; n.vy = 0;
        nodeMap[n.id] = n;
    });

    // Force-directed simulation (simple, 50 iterations)
    const K = 60; // spring length
    for (let iter = 0; iter < 50; iter++) {
        const allN = nodes.filter(n => nodeMap[n.id]);
        // Repulsion
        for (let i = 0; i < allN.length; i++) {
            for (let j = i + 1; j < allN.length; j++) {
                const a = allN[i], b = allN[j];
                const dx = b.x - a.x, dy = b.y - a.y;
                const dist = Math.sqrt(dx * dx + dy * dy) || 1;
                const f = Math.min(3000 / (dist * dist), 8);
                a.vx -= f * dx / dist; a.vy -= f * dy / dist;
                b.vx += f * dx / dist; b.vy += f * dy / dist;
            }
        }
        // Attraction along edges
        edges.forEach(e => {
            const a = nodeMap[e.from], b = nodeMap[e.to];
            if (!a || !b) return;
            const dx = b.x - a.x, dy = b.y - a.y;
            const dist = Math.sqrt(dx * dx + dy * dy) || 1;
            const f = (dist - K) * 0.05;
            a.vx += f * dx / dist; a.vy += f * dy / dist;
            b.vx -= f * dx / dist; b.vy -= f * dy / dist;
        });
        // Center gravity
        nodes.forEach(n => {
            if (!nodeMap[n.id]) return;
            n.vx += (cx - n.x) * 0.005;
            n.vy += (cy - n.y) * 0.005;
            n.x += n.vx * 0.5; n.y += n.vy * 0.5;
            n.vx *= 0.7; n.vy *= 0.7;
            n.x = Math.max(55, Math.min(W - 55, n.x));
            n.y = Math.max(30, Math.min(H - 25, n.y));
        });
    }

    // Render
    const cvs = document.createElement('canvas');
    cvs.width = W * dpr; cvs.height = H * dpr;
    cvs.style.cssText = `width:${W}px;height:${H}px;display:block;border:1px solid var(--border);border-radius:4px;background:#0e0e0e;`;
    const ctx = cvs.getContext('2d');
    ctx.scale(dpr, dpr);

    const nodeColor = n => {
        if (n.type === 'group') return '#0078d4';
        if (n.type === 'manual') return '#6f42c1';
        if (n.type === 'snmp') return '#fd7e14';
        return n.status === 'ONLINE' ? '#107c10' : n.status === 'UNKNOWN' ? '#555' : '#c50f1f';
    };
    const edgeColor = src => src === 'manual' ? '#6f42c1' : src === 'snmp_cdp' ? '#fd7e14' : src === 'snmp_lldp' ? '#ffc107' : 'rgba(0,120,212,.35)';

    // Draw edges
    edges.forEach(e => {
        const a = nodeMap[e.from], b = nodeMap[e.to];
        if (!a || !b) return;
        ctx.strokeStyle = edgeColor(e.source);
        ctx.lineWidth = e.source === 'manual' ? 2 : 1;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
        if (e.label) {
            ctx.fillStyle = '#666'; ctx.font = '8px monospace'; ctx.textAlign = 'center';
            ctx.fillText(e.label.substring(0, 12), (a.x + b.x) / 2, (a.y + b.y) / 2 - 3);
        }
    });

    // Draw nodes
    nodes.forEach(n => {
        if (!nodeMap[n.id]) return;
        const col = nodeColor(n);
        const r = n.type === 'group' ? 18 : 12;
        ctx.fillStyle = col + '22';
        ctx.strokeStyle = col;
        ctx.lineWidth = n.type === 'group' ? 2 : 1.5;
        ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
        // Icon
        ctx.fillStyle = col;
        ctx.font = `${n.type === 'group' ? 11 : 9}px monospace`;
        ctx.textAlign = 'center';
        const icon = n.type === 'group' ? '⬡' : n.type === 'manual' ? '◆' : '●';
        ctx.fillText(icon, n.x, n.y + 4);
        // Label
        ctx.fillStyle = '#ccc'; ctx.font = '9px sans-serif'; ctx.textAlign = 'center';
        const lbl = n.label.length > 14 ? n.label.substring(0, 13) + '…' : n.label;
        ctx.fillText(lbl, n.x, n.y + r + 11);
        if (n.ip) { ctx.fillStyle = '#555'; ctx.font = '8px monospace'; ctx.fillText(n.ip, n.x, n.y + r + 20); }
    });
    ctx.textAlign = 'left';

    // Legend
    const legend = document.createElement('div');
    legend.style.cssText = 'font-size:.73em;color:var(--text-muted);margin-top:6px;display:flex;flex-wrap:wrap;gap:10px;';
    legend.innerHTML = [
        ['#107c10','● Agent ONLINE'], ['#c50f1f','● Agent OFFLINE'],
        ['#0078d4','⬡ Skupina'], ['#6f42c1','◆ Manuální'],
        ['#fd7e14','◆ SNMP/CDP'], ['#ffc107','◆ SNMP/LLDP'],
    ].map(([c,l]) => `<span><i style="color:${c};margin-right:3px;">${l.charAt(0)}</i>${l.substring(1)}</span>`).join('');

    const info = document.createElement('div');
    info.style.cssText = 'font-size:.72em;color:#555;margin-top:3px;';
    info.textContent = `${nodes.length} uzlů • ${edges.length} hran${updatedAt ? ' • ' + updatedAt.substring(0,16) + ' UTC' : ''}`;

    container.innerHTML = '';
    container.appendChild(cvs);
    container.appendChild(legend);
    container.appendChild(info);

    // Reload button
    const reloadBtn = document.createElement('button');
    reloadBtn.style.cssText = 'position:absolute;top:6px;right:6px;background:transparent;border:1px solid var(--border);color:var(--text-muted);padding:3px 8px;border-radius:4px;cursor:pointer;font-size:.75em;';
    reloadBtn.innerHTML = '<i class="fa-solid fa-rotate"></i>';
    reloadBtn.onclick = () => { _toolsTabLoaded.delete('topology'); _toolsTopologyLoad(); };
    container.style.position = 'relative';
    container.appendChild(reloadBtn);
}

async function _toolsChangelogLoad() {
    const el = document.getElementById('tools-changelog-body');
    if (!el) return;
    el.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>';
    try {
        const r = await fetch('/api/changelog?limit=30');
        const d = await r.json();
        const commits = d.commits || [];
        el.innerHTML = commits.map(c => `<div style="padding:7px 0;border-bottom:1px solid var(--border);font-size:.83em;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <code style="color:var(--accent);font-size:.85em;">${_escape(c.short)}</code>
                <span style="color:var(--text-muted);font-size:.8em;">${_escape(c.when)}</span>
            </div>
            <div style="color:var(--text-main);margin-top:2px;">${_escape(c.subject)}</div>
        </div>`).join('') || '<div style="color:var(--text-muted);">Žádné záznamy.</div>';
    } catch(e) { el.innerHTML = `<div style="color:var(--error);">Chyba: ${e}</div>`; }
}

async function _toolsAiTrendLoad() {
    const el = document.getElementById('tools-ai-trend-body');
    if (!el) return;
    const days = document.getElementById('trend-days-sel')?.value || 7;
    el.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i> AI analyzuje trendy…</div>';
    _toolsTabLoaded.delete('ai_trend'); // allow reload
    try {
        const r = await fetch('/api/analyze/trend_report', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({days: parseInt(days)})});
        const d = await r.json();
        el.innerHTML = d.reply || `<div style="color:var(--error);">${d.error||'?'}</div>`;
    } catch(e) { el.innerHTML = `<div style="color:var(--error);">Chyba: ${e}</div>`; }
}

async function _loadCompare() {
    const metric = document.getElementById('cmp-metric')?.value.trim();
    const bLen = parseInt(document.getElementById('cmp-b-len')?.value || 24);
    const bEnd = parseInt(document.getElementById('cmp-b-end')?.value || 48);
    const cLen = parseInt(document.getElementById('cmp-c-len')?.value || 24);
    const el = document.getElementById('cmp-result');
    if (!metric || !el) return;
    el.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
    try {
        const r = await fetch('/api/telemetry/compare', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({metric, baseline_hours: bEnd, baseline_len: bLen, current_hours: 0, current_len: cLen}),
        });
        const d = await r.json();
        if (d.error) { el.innerHTML = `<span style="color:var(--error);">${_escape(d.error)}</span>`; return; }
        const arrow = d.pct > 0 ? '↑' : d.pct < 0 ? '↓' : '→';
        const col = d.pct > 10 ? 'var(--error)' : d.pct < -10 ? 'var(--success)' : 'var(--text-muted)';
        el.innerHTML = `
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:6px;">
                <div style="padding:8px;background:rgba(255,255,255,.03);border-radius:4px;text-align:center;">
                    <div style="font-size:.72em;color:var(--text-muted);">Baseline (A)</div>
                    <div style="font-size:1.1em;font-weight:700;">${d.baseline.avg ?? '—'}</div>
                    <div style="font-size:.72em;color:var(--text-muted);">min ${d.baseline.min??'—'} / max ${d.baseline.max??'—'}</div>
                </div>
                <div style="padding:8px;background:rgba(255,255,255,.03);border-radius:4px;text-align:center;">
                    <div style="font-size:.72em;color:var(--text-muted);">Aktuální (B)</div>
                    <div style="font-size:1.1em;font-weight:700;">${d.current.avg ?? '—'}</div>
                    <div style="font-size:.72em;color:var(--text-muted);">min ${d.current.min??'—'} / max ${d.current.max??'—'}</div>
                </div>
            </div>
            ${d.pct !== null ? `<div style="text-align:center;font-size:1em;color:${col};font-weight:700;">${arrow} ${Math.abs(d.pct)}% oproti baseline</div>` : ''}`;
    } catch(e) {
        el.innerHTML = `<span style="color:var(--error);">Chyba: ${_escape(e.message)}</span>`;
    }
}

async function _loadCapacityForecast() {
    const el = document.getElementById('cap-forecast');
    const days = document.getElementById('cap-days-sel')?.value || 3;
    if (!el) return;
    el.style.display = 'block';
    el.innerHTML = '<div style="text-align:center;padding:12px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i> Počítám trendy…</div>';
    try {
        const r = await fetch(`/api/predictions/capacity?days=${days}`);
        const d = await r.json();
        const preds = d.predictions || [];
        if (!preds.length) {
            el.innerHTML = '<div style="color:var(--text-muted);font-size:.82em;padding:8px;">Žádná kapacitní data za zvolené období.</div>';
            return;
        }
        const statusColor = {critical:'var(--error,#dc3545)', warning:'var(--warning,#fa8231)', ok:'var(--success,#28a745)'};
        el.innerHTML = `<div style="font-size:.78em;color:var(--accent);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;font-weight:700;">
            <i class="fa-solid fa-chart-line"></i> Kapacitní předpověď (linear regression, ${days} dny dat)
        </div>` + preds.filter(p => p.ttc_hours !== null || p.change_per_h !== 0).map(p => {
            const col = statusColor[p.status] || '#aaa';
            const ttcStr = p.ttc_hours != null
                ? (p.ttc_hours < 24 ? `${p.ttc_hours}h` : `${(p.ttc_hours/24).toFixed(1)} dní`)
                : '—';
            const arrow = p.change_per_h > 0 ? '↑' : p.change_per_h < 0 ? '↓' : '→';
            return `<div style="display:flex;align-items:center;gap:10px;padding:5px 8px;margin-bottom:3px;background:rgba(255,255,255,.02);border-radius:4px;border-left:3px solid ${col};">
                <span style="flex:1;font-size:.82em;font-family:monospace;color:var(--text-main);">${_escape(p.category)}/${_escape(p.metric)}</span>
                <span style="font-size:.8em;color:var(--text-muted);">aktuálně: <b>${p.current}</b></span>
                <span style="font-size:.8em;color:${p.change_per_h>0?'var(--error)':'var(--success)'};">${arrow} ${Math.abs(p.change_per_h)}/h</span>
                ${p.ttc_hours != null ? `<span style="font-size:.8em;color:${col};font-weight:600;">TTL: ${ttcStr}</span>` : ''}
            </div>`;
        }).join('');
    } catch(e) {
        el.innerHTML = `<div style="color:var(--error);font-size:.82em;">Chyba: ${_escape(e.message)}</div>`;
    }
}

async function _loadCapacityPlan() {
    const body = document.getElementById('cap-body');
    const btn  = document.getElementById('cap-run-btn');
    const days = parseInt(document.getElementById('cap-days-sel')?.value || 7);
    if (!body) return;
    body.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin fa-lg"></i><br>AI analyzuje telemetrii…</div>';
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Analyzuji…'; }
    try {
        const r = await fetch('/api/reports/capacity_plan', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({days}),
        });
        const d = await r.json();
        if (d.error) { body.innerHTML = `<div style="color:var(--error);padding:16px;">${_escape(d.error)}</div>`; return; }
        if (!d.report) { body.innerHTML = `<div style="color:var(--text-muted);padding:16px;">${_escape(d.message || 'Žádná data.')}</div>`; return; }

        const priorityColor = {high: 'var(--error,#dc3545)', medium: 'var(--warning,#fa8231)', low: 'var(--success,#28a745)'};
        const blocks = d.blocks || [];
        const blocksHtml = blocks.length ? blocks.map(b => {
            const pri = (b.priority || 'medium').toLowerCase();
            const col = priorityColor[pri] || '#aaa';
            return `<div style="border-left:3px solid ${col};padding:10px 14px;margin-bottom:8px;background:rgba(255,255,255,.02);border-radius:0 6px 6px 0;">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                    <b style="font-family:monospace;color:var(--accent);">${_escape(b.host||'?')}</b>
                    <span style="font-size:.72em;padding:1px 6px;border-radius:8px;background:${col}22;color:${col};font-weight:700;text-transform:uppercase;">${_escape(pri)}</span>
                </div>
                <div style="font-size:.83em;color:var(--error);margin-bottom:3px;"><i class="fa-solid fa-triangle-exclamation"></i> ${_escape(b.problem||'')}</div>
                <div style="font-size:.83em;color:var(--text-main);"><i class="fa-solid fa-arrow-right" style="color:var(--success);"></i> ${_escape(b.recommendation||'')}</div>
            </div>`;
        }).join('') : '';

        body.innerHTML = `
            <div style="font-size:.78em;color:var(--text-muted);margin-bottom:12px;">
                Analyzováno ${d.hosts_analyzed} hostů za ${d.days} dní.
            </div>
            ${blocksHtml}
            <details style="margin-top:12px;">
                <summary style="cursor:pointer;font-size:.8em;color:var(--text-muted);">Celý AI výstup</summary>
                <pre style="font-size:.78em;color:var(--text-muted);white-space:pre-wrap;margin-top:8px;padding:10px;background:var(--panel);border-radius:4px;">${_escape(d.report)}</pre>
            </details>`;
    } catch(e) {
        body.innerHTML = `<div style="color:var(--error);padding:16px;">Chyba: ${_escape(e.message)}</div>`;
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Spustit AI analýzu'; }
    }
}

async function _toolsPatternsLoad() {
    const el = document.getElementById('tools-patterns-body');
    if (!el) return;
    el.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>';
    try {
        const [pr, logR] = await Promise.all([
            fetch('/api/patterns').then(r=>r.json()).catch(()=>({patterns:[]})),
            fetch('/api/logs').then(r=>r.json()).catch(()=>({logs:[]})),
        ]);
        const patterns = pr.patterns || [];
        const logs = (logR.logs||[]).map(l=>l.name||l).filter(Boolean);
        const channelOpts = ['infra','security','agent','root'].map(c=>`<option value="${c}">${c}</option>`).join('');
        const patRows = patterns.length
            ? patterns.map(p => `<tr style="border-bottom:1px solid var(--border);">
                <td style="padding:6px 8px;"><span style="color:${p.enabled?'var(--success)':'var(--text-muted)'};">●</span></td>
                <td style="padding:6px 8px;font-weight:600;font-size:.83em;">${_escape(p.name)}</td>
                <td style="padding:6px 8px;max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"><code style="color:var(--accent);font-size:.8em;">${_escape(p.pattern)}</code></td>
                <td style="padding:6px 8px;font-size:.8em;color:var(--text-muted);">${_escape(p.channel||'')}</td>
                <td style="padding:6px 8px;text-align:center;">
                    <i class="fa-solid fa-toggle-${p.enabled?'on':'off'}" style="cursor:pointer;color:${p.enabled?'var(--accent)':'var(--text-muted)'};margin-right:8px;" onclick="_ptToggle(${p.id})"></i>
                    <i class="fa-solid fa-trash" style="cursor:pointer;color:var(--error);" onclick="_ptDelete(${p.id})"></i>
                </td>
            </tr>`).join('')
            : `<tr><td colspan="5" style="padding:14px;text-align:center;color:var(--text-muted);font-size:.85em;">Žádné vlastní patterny.</td></tr>`;
        el.innerHTML = `
        <div style="margin-bottom:14px;padding:12px;background:var(--panel);border:1px solid var(--border);border-radius:6px;">
            <div style="font-size:.78em;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--accent);margin-bottom:10px;"><i class="fa-solid fa-plus"></i> Nový pattern</div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;">
                <div style="flex:1;min-width:120px;"><label style="display:block;font-size:.75em;color:var(--text-muted);margin-bottom:3px;">Název</label>
                    <input id="pt-name" type="text" placeholder="disk_full" style="width:100%;padding:7px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:4px;font-size:.83em;box-sizing:border-box;"></div>
                <div style="flex:2;min-width:180px;"><label style="display:block;font-size:.75em;color:var(--text-muted);margin-bottom:3px;">Regex pattern</label>
                    <input id="pt-pattern" type="text" placeholder="disk.*full|no space" style="width:100%;padding:7px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:4px;font-family:monospace;font-size:.83em;box-sizing:border-box;"></div>
                <div style="min-width:100px;"><label style="display:block;font-size:.75em;color:var(--text-muted);margin-bottom:3px;">Kanál</label>
                    <select id="pt-channel" style="width:100%;padding:7px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:4px;font-size:.83em;">${channelOpts}</select></div>
                <div style="min-width:90px;"><label style="display:block;font-size:.75em;color:var(--text-muted);margin-bottom:3px;">Závažnost</label>
                    <select id="pt-severity" style="width:100%;padding:7px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:4px;font-size:.83em;">
                        <option value="low">low</option><option value="medium" selected>medium</option><option value="high">high</option><option value="critical">critical</option></select></div>
                <div><label style="display:block;font-size:.75em;color:transparent;margin-bottom:3px;">-</label>
                    <button onclick="_ptAdd()" style="padding:7px 16px;background:var(--accent);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.83em;white-space:nowrap;"><i class="fa-solid fa-plus"></i> Přidat</button></div>
            </div>
            <div id="pt-test-area" style="margin-top:8px;display:flex;gap:8px;align-items:center;">
                <input id="pt-test-input" type="text" placeholder="Testovací řádek logu..." style="flex:1;padding:6px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:4px;font-size:.8em;font-family:monospace;">
                <button onclick="_ptTest()" style="padding:6px 12px;background:transparent;border:1px solid var(--border);color:var(--text-muted);border-radius:4px;cursor:pointer;font-size:.8em;"><i class="fa-solid fa-vial"></i> Test</button>
                <span id="pt-test-result" style="font-size:.8em;"></span>
            </div>
        </div>
        <table style="width:100%;border-collapse:collapse;font-size:.85em;">
            <thead><tr style="border-bottom:2px solid var(--border);color:var(--text-muted);font-size:.8em;">
                <th style="padding:5px 8px;width:30px;"></th>
                <th style="padding:5px 8px;text-align:left;">Název</th>
                <th style="padding:5px 8px;text-align:left;">Pattern</th>
                <th style="padding:5px 8px;text-align:left;">Kanál</th>
                <th style="padding:5px 8px;text-align:center;">Akce</th>
            </tr></thead>
            <tbody>${patRows}</tbody>
        </table>`;
    } catch(e) { el.innerHTML = `<div style="color:var(--error);">Chyba: ${e}</div>`; }
}

async function _ptAdd() {
    const name = document.getElementById('pt-name')?.value.trim();
    const pattern = document.getElementById('pt-pattern')?.value.trim();
    const channel = document.getElementById('pt-channel')?.value || 'infra';
    const severity = document.getElementById('pt-severity')?.value || 'medium';
    if (!name || !pattern) { alert('Vyplňte název a pattern.'); return; }
    try {
        const r = await fetch('/api/patterns', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name, pattern, channel, severity, enabled: true})});
        const d = await r.json();
        if (d.status === 'ok') { _toolsTabLoaded.delete('patterns'); _toolsPatternsLoad(); }
        else alert(d.message || 'Chyba');
    } catch(e) { alert(e.message); }
}

async function _ptToggle(id) {
    await fetch(`/api/patterns/${id}/toggle`, {method:'POST'});
    _toolsTabLoaded.delete('patterns'); _toolsPatternsLoad();
}

async function _ptDelete(id) {
    if (!confirm('Smazat pattern?')) return;
    await fetch(`/api/patterns/${id}`, {method:'DELETE'});
    _toolsTabLoaded.delete('patterns'); _toolsPatternsLoad();
}

function _ptTest() {
    const line = document.getElementById('pt-test-input')?.value || '';
    const pattern = document.getElementById('pt-pattern')?.value || '';
    const res = document.getElementById('pt-test-result');
    if (!pattern || !line) { res.innerHTML = ''; return; }
    try {
        const rx = new RegExp(pattern, 'i');
        const match = rx.test(line);
        res.innerHTML = match
            ? `<span style="color:var(--success);"><i class="fa-solid fa-check"></i> Shoda</span>`
            : `<span style="color:var(--error);"><i class="fa-solid fa-xmark"></i> Neshoda</span>`;
    } catch(e) { res.innerHTML = `<span style="color:var(--error);">Chyba regex: ${e.message}</span>`; }
}

async function _toolsSrovnatLoad() {
    const el = document.getElementById('tools-srovnat-body');
    if (!el) return;
    try {
        const r = await fetch('/api/agents/list');
        const d = await r.json();
        const agents = (d.agents || []).filter(a => !a.category || a.category === 'agent').map(a => a.hostname);
        const opts = agents.map(h => `<option value="${_escape(h)}">${_escape(h)}</option>`).join('');
        el.innerHTML = `
        <div style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap;margin-bottom:14px;padding:12px;background:var(--panel);border:1px solid var(--border);border-radius:6px;">
            <div style="flex:1;min-width:140px;"><label style="display:block;font-size:.78em;color:var(--text-muted);margin-bottom:4px;">Agent A</label>
                <select id="tcmp-a" style="width:100%;padding:7px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:4px;font-size:.85em;">${opts}</select></div>
            <div style="flex:1;min-width:140px;"><label style="display:block;font-size:.78em;color:var(--text-muted);margin-bottom:4px;">Agent B</label>
                <select id="tcmp-b" style="width:100%;padding:7px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:4px;font-size:.85em;">${opts}</select></div>
            <div style="min-width:90px;"><label style="display:block;font-size:.78em;color:var(--text-muted);margin-bottom:4px;">Dní</label>
                <select id="tcmp-days" style="width:100%;padding:7px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:4px;font-size:.85em;">
                    <option value="1">1</option><option value="3" selected>3</option><option value="7">7</option></select></div>
            <button onclick="_runInlineCompare()" style="padding:7px 18px;background:var(--accent);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.85em;"><i class="fa-solid fa-code-compare"></i> Srovnat</button>
        </div>
        <div id="tcmp-result"></div>`;
        if (agents.length > 1) document.getElementById('tcmp-b').selectedIndex = 1;
    } catch(e) { el.innerHTML = `<div style="color:var(--error);">Chyba: ${e}</div>`; }
}

async function _runInlineCompare() {
    const a = document.getElementById('tcmp-a')?.value;
    const b = document.getElementById('tcmp-b')?.value;
    const days = document.getElementById('tcmp-days')?.value || 3;
    const res = document.getElementById('tcmp-result');
    if (!a || !b || a === b) { if(res) res.innerHTML='<div style="color:var(--error);padding:10px;">Vyberte dva různé agenty.</div>'; return; }
    res.innerHTML = '<div style="text-align:center;padding:30px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i></div>';
    try {
        const r = await fetch(`/api/agents/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}&days=${days}`);
        const d = await r.json();
        const common = d.common_metrics || [];
        if (!common.length) { res.innerHTML='<div style="color:var(--text-muted);padding:20px;">Žádné společné metriky.</div>'; return; }
        const chartData = common.slice(0,6).map((metric,idx) => ({
            metric,
            cid: `tcmp_c_${idx}`,
            da: (d.data[a]?.[metric]||[]).slice(-48),
            db: (d.data[b]?.[metric]||[]).slice(-48),
        }));
        res.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px;">${
            chartData.map(c=>`<div style="background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:12px;">
                <div style="font-size:.75em;color:var(--text-muted);margin-bottom:6px;font-weight:600;">${_escape(c.metric)}</div>
                <canvas id="${c.cid}" height="80"></canvas>
            </div>`).join('')
        }</div>`;
        if (window.Chart) {
            chartData.forEach(c => {
                const ctx = document.getElementById(c.cid);
                if (!ctx) return;
                const labels = c.da.map(p=>(p.ts||'').slice(11,16));
                new Chart(ctx, {type:'line', data:{labels, datasets:[
                    {label:a, data:c.da.map(p=>p.v), borderColor:'#0078d4', borderWidth:1.5, pointRadius:0, fill:false, tension:0.2},
                    {label:b, data:c.db.map(p=>p.v), borderColor:'#28a745', borderWidth:1.5, pointRadius:0, fill:false, tension:0.2, borderDash:[4,2]}
                ]}, options:{animation:false, plugins:{legend:{labels:{color:'#aaa',font:{size:9}}}}, scales:{x:{display:false},y:{ticks:{color:'#aaa',font:{size:9},maxTicksLimit:3}}}}});
            });
        }
    } catch(e) { res.innerHTML=`<div style="color:var(--error);">Chyba: ${e}</div>`; }
}

// Redirect old standalone modal openers to the unified tabs modal
// Unified tools modal helpers
function openPluginStatsModalInline(inline = false) {
    if (!inline) { openToolsModal('plugin_stats'); return; }
    const el = document.getElementById('plugin-stats-content');
    if (!el) return;
    el.innerHTML = `<div style="text-align:center; padding:20px; color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>`;
    fetch('/api/plugins/stats').then(r => r.json()).then(d => {
        const stats = d.stats || [];
        if (!stats.length) { el.innerHTML = `<div style="color:var(--text-muted); padding:16px; text-align:center;">${t('no_data')}</div>`; return; }
        const maxTotal = Math.max(1, ...stats.map(s => s.total));
        const isAdmin = window.currentRole === 'admin' || window.currentRole === 'superadmin';
        el.innerHTML = `<table style="width:100%; border-collapse:collapse; font-size:0.87em;">
            <thead><tr style="color:var(--text-muted); font-size:0.78em; text-transform:uppercase; letter-spacing:.5px;">
                <th style="text-align:left; padding:6px 8px;">${t('plugin_col')}</th>
                <th style="text-align:center; padding:6px 8px;">${t('today_col')}</th>
                <th style="text-align:center; padding:6px 8px;">Aktivní</th>
                <th style="text-align:center; padding:6px 8px;">Vyřešeno 30d</th>
                <th style="text-align:left; padding:6px 8px; min-width:100px;">Četnost</th>
                <th style="text-align:center; padding:6px 8px;" title="Notifikace (HA/MQTT) při novém issue"><i class="fa-solid fa-bell"></i> Notif</th>
                <th style="text-align:left; padding:6px 8px;">${t('last_seen_col')}</th>
            </tr></thead><tbody>
            ${stats.map(s => {
                const barW = Math.round((s.total / maxTotal) * 100);
                const barColor = s.active > 0 ? 'var(--error)' : '#4da6ff';
                const notifyOn = s.notify !== false;
                const notifyBtn = isAdmin
                    ? `<button onclick="_togglePluginNotify('${_escape(s.plugin)}', ${!notifyOn})"
                          title="${notifyOn ? 'Vypnout notifikace pro tento detektor' : 'Zapnout notifikace'}"
                          style="background:none;border:none;cursor:pointer;padding:2px 6px;font-size:1em;color:${notifyOn?'var(--accent)':'var(--text-muted)'};"
                          ><i class="fa-solid ${notifyOn?'fa-bell':'fa-bell-slash'}"></i></button>`
                    : `<i class="fa-solid ${notifyOn?'fa-bell':'fa-bell-slash'}" style="color:${notifyOn?'var(--accent)':'var(--text-muted)'}; font-size:.9em;"></i>`;
                return `<tr style="border-top:1px solid var(--border); opacity:${s.enabled!==false?1:0.45};">
                    <td style="padding:8px; font-weight:600; max-width:160px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${_escape(s.plugin)}">${_escape(s.plugin)}</td>
                    <td style="padding:8px; text-align:center; color:${s.today>0?'var(--error)':'var(--text-muted)'};">${s.today}</td>
                    <td style="padding:8px; text-align:center; color:${s.active>0?'var(--error)':'var(--text-muted)'}; font-weight:${s.active>0?'700':'400'};">${s.active}</td>
                    <td style="padding:8px; text-align:center; color:var(--text-muted);">${s.resolved_30d||0}</td>
                    <td style="padding:8px;">
                        <div style="display:flex;align-items:center;gap:6px;">
                            <div style="flex:1;height:6px;background:rgba(255,255,255,0.05);border-radius:3px;overflow:hidden;">
                                <div style="width:${barW}%;height:100%;background:${barColor};border-radius:3px;"></div>
                            </div>
                            <span style="color:var(--text-muted);font-size:0.8em;width:28px;text-align:right;">${s.total}</span>
                        </div>
                    </td>
                    <td style="padding:8px; text-align:center;">${notifyBtn}</td>
                    <td style="padding:8px; color:var(--text-muted); font-size:0.82em;">${s.last_seen ? s.last_seen.slice(0,16).replace('T',' ') : '-'}</td>
                </tr>`;
            }).join('')}
            </tbody></table>
            <div style="margin-top:10px;font-size:.75em;color:var(--text-muted);padding:6px 8px;border-top:1px solid var(--border);">
                <i class="fa-solid fa-bell" style="color:var(--accent);"></i> Notif = HA + MQTT notifikace při vzniku nového issue z tohoto detektoru
            </div>`;
    }).catch(() => { el.innerHTML = `<div style="color:var(--error); padding:16px;">${t('data_load_failed')}</div>`; });
}

async function _togglePluginNotify(plugin, notify) {
    try {
        const r = await fetch('/api/plugins/toggle_notify', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({plugin, notify})
        });
        const d = await r.json();
        if (d.status === 'ok') openPluginStatsModalInline(true); // refresh
    } catch(e) { console.error('toggle_notify:', e); }
}

// ─── System Info Modal ────────────────────────────────────────────────────────

async function openSysInfoModal() {
    document.getElementById('sysinfo-modal').style.display = 'flex';
    await loadSysInfo();
}

function closeSysInfoModal() {
    document.getElementById('sysinfo-modal').style.display = 'none';
}

async function loadSysInfo() {
    const el = document.getElementById('sysinfo-content');
    el.innerHTML = `<div style="text-align:center; padding:30px; color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i></div>`;
    try {
        const r = await fetch('/api/sys_info');
        const d = await r.json();
        el.innerHTML = d.html || `<div style="color:var(--error);">${t('data_load_failed')}</div>`;
    } catch(e) {
        el.innerHTML = `<div style="color:var(--error); padding:16px;">${t('data_load_failed')}</div>`;
    }
}

// ─── Ignored Issues Modal ─────────────────────────────────────────────────────

async function openIgnoredModal() {
    document.getElementById('ignored-modal').style.display = 'flex';
    await loadIgnoredList();
}

function closeIgnoredModal() {
    document.getElementById('ignored-modal').style.display = 'none';
}

async function loadIgnoredList() {
    const el = document.getElementById('ignored-content');
    el.innerHTML = `<div style="text-align:center; padding:20px; color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>`;
    try {
        const r = await fetch('/api/ignored');
        const d = await r.json();
        const items = d.ignored || [];
        if (!items.length) {
            el.innerHTML = `<div style="color:var(--text-muted); text-align:center; padding:24px;">${t('ignored_empty')}</div>`;
            return;
        }
        el.innerHTML = items.map(item => `
            <div style="display:flex; align-items:center; gap:10px; padding:10px 12px; margin-bottom:6px; background:var(--panel); border:1px solid var(--border); border-radius:6px;">
                <i class="fa-solid fa-eye-slash" style="color:var(--text-muted); flex-shrink:0;"></i>
                <span style="flex:1; font-size:0.85em; word-break:break-all; color:var(--text-main);">${_escape(item.key)}</span>
                <button onclick="unignoreItem('${item.key_b64}')" style="background:transparent; border:1px solid var(--border); color:var(--accent); padding:4px 10px; border-radius:4px; cursor:pointer; font-size:0.8em; flex-shrink:0;">
                    <i class="fa-solid fa-eye"></i> ${t('unignore_btn')}
                </button>
            </div>`).join('');
    } catch(e) {
        el.innerHTML = `<div style="color:var(--error); padding:16px;">${t('data_load_failed')}</div>`;
    }
}

async function unignoreItem(kb64) {
    try {
        await fetch(`/api/ignored/${kb64}`, { method: 'DELETE' });
        await loadIgnoredList();
        updateStatus();
    } catch(e) { console.error(e); }
}

// ─── RAG Info Modal ───────────────────────────────────────────────────────────

async function openRagModal() {
    document.getElementById('rag-modal').style.display = 'flex';
    _ragLoadFiles();
    const el = document.getElementById('rag-info-content');
    el.innerHTML = `<div style="text-align:center; padding:20px; color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>`;
    try {
        const r = await fetch('/api/rag/info');
        const d = await r.json();
        const isVector = (d.provider || '').toLowerCase().includes('chroma') || (d.chunks > 0);
        const ragMode  = isVector ? 'VECTOR' : 'TEXT';
        const ragColor = isVector ? '#4da6ff' : '#e88cbe';
        const ragIcon  = isVector ? 'fa-solid fa-brain' : 'fa-solid fa-font';
        const docs     = d.docs ?? 0;
        const chunks   = d.chunks ?? 0;
        const maxDocs  = Math.max(docs, 50);
        const docsPct  = Math.min(100, Math.round(docs / maxDocs * 100));
        el.innerHTML = `
            <div style="display:grid; gap:8px;">
                <div style="display:flex; align-items:center; justify-content:space-between; padding:10px 14px; background:var(--panel); border-radius:8px; border:1px solid var(--border);">
                    <span style="color:var(--text-muted); font-size:0.82em; display:flex; align-items:center; gap:6px;"><i class="fa-solid fa-circle-info" style="color:var(--accent);"></i> Režim</span>
                    <span style="font-weight:700; color:${ragColor}; font-size:1em;"><i class="${ragIcon}" style="margin-right:5px;"></i>${ragMode}</span>
                </div>
                ${_ragRow('fa-layer-group', t('rag_provider'), d.provider || '-')}
                ${_ragRow('fa-microchip', t('rag_model'), d.model || '-')}
                <div style="padding:10px 14px; background:var(--panel); border-radius:8px; border:1px solid var(--border); display:grid; gap:6px;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="color:var(--text-muted); font-size:0.82em; display:flex; align-items:center; gap:6px;"><i class="fa-solid fa-file-lines" style="color:var(--accent);"></i> ${t('rag_docs')}</span>
                        <span style="font-size:0.88em; font-weight:600;">${docs} <span style="color:var(--text-muted); font-weight:normal; font-size:.9em;">docs / ${chunks} chunks</span></span>
                    </div>
                    <div style="height:4px; background:var(--border); border-radius:2px; overflow:hidden;">
                        <div style="height:100%; width:${docsPct}%; background:${ragColor}; border-radius:2px; transition:width .5s;"></div>
                    </div>
                </div>
                ${_ragRow('fa-folder-open', 'KB soubor', d.kb_file || '-')}
                ${_ragRow('fa-database', 'ChromaDB', d.chroma_path || '-')}
            </div>`;
    } catch(e) {
        el.innerHTML = `<div style="color:var(--error); padding:16px;">${t('data_load_failed')}</div>`;
    }
}

function _ragRow(icon, label, value) {
    return `<div style="display:flex; justify-content:space-between; gap:12px; padding:8px 14px; background:var(--panel); border-radius:8px; border:1px solid var(--border); align-items:center;">
        <span style="color:var(--text-muted); font-size:0.82em; flex-shrink:0; display:flex; align-items:center; gap:6px;"><i class="fa-solid ${_escape(icon)}" style="color:var(--accent);"></i>${label}</span>
        <span style="font-size:0.85em; text-align:right; word-break:break-all;">${_escape(value)}</span>
    </div>`;
}

async function _ragLoadFiles() {
    const el = document.getElementById('rag-files-list');
    if (!el) return;
    el.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Načítám…';
    try {
        const r = await fetch('/api/kb/files');
        const d = await r.json();
        const files = d.files || [];
        if (!files.length) { el.innerHTML = '<span style="color:var(--text-muted);">Žádné soubory v KB.</span>'; return; }
        el.innerHTML = files.map(f => `<div style="display:flex; align-items:center; gap:8px; padding:5px 0; border-bottom:1px solid rgba(255,255,255,.04);">
            <i class="fa-solid fa-file-lines" style="color:var(--accent); font-size:.9em; flex-shrink:0;"></i>
            <span style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${_escape(f.name)}</span>
            <span style="color:#555; font-size:.72em; flex-shrink:0;">${_escape(f.dir||'')}</span>
            <span style="color:var(--text-muted); font-size:.72em; font-family:monospace; flex-shrink:0;">${_escape(f.size_str||'')}</span>
        </div>`).join('');
    } catch(e) { el.innerHTML = `<span style="color:var(--error);">${e.message}</span>`; }
}

function closeRagModal() { document.getElementById('rag-modal').style.display = 'none'; }

// ─── Queue Details Modal ──────────────────────────────────────────────────────

async function openQueueModal() {
    document.getElementById('queue-modal').style.display = 'flex';
    await loadQueueDetails();
}

function closeQueueModal() { document.getElementById('queue-modal').style.display = 'none'; }

async function loadQueueDetails() {
    const el = document.getElementById('queue-detail-content');
    el.innerHTML = `<div style="text-align:center; padding:20px; color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>`;
    try {
        const r = await fetch('/api/queue/details');
        const d = await r.json();
        const _esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

        const isCS = (localStorage.getItem('sentinel_lang') || 'cs') === 'cs';
        const lbl = (cs, en) => isCS ? cs : en;

        // Stat cards
        const stats = [
            { icon:'fa-hourglass-half', color:'var(--accent)',   cs:'AI fronta',        en:'AI Queue',        val: d.pending ?? 0,             desc: isCS ? 'Dotazy čekající na zpracování LLM' : 'Requests waiting for LLM processing' },
            { icon:'fa-microchip',      color:'#a855f7',         cs:'Pracovníci',        en:'Workers',         val: d.workers ?? 0,              desc: isCS ? 'Počet vláken pro AI zpracování' : 'AI processing thread count' },
            { icon:'fa-bolt',           color:'var(--success)',  cs:'Latence AI',        en:'AI Latency',      val: d.ai_latency ?? 'N/A',       desc: isCS ? 'Průměrná doba odpovědi AI' : 'Average AI response time' },
            { icon:'fa-chart-bar',      color:'#ffc107',         cs:'Požadavků celkem',  en:'Total Requests',  val: d.ai_requests_total ?? 0,    desc: isCS ? 'Celkový počet AI dotazů od startu' : 'Total AI requests since startup' },
            { icon:'fa-triangle-exclamation', color:'var(--error)', cs:'Chyby AI',       en:'AI Errors',       val: d.ai_errors_total ?? 0,      desc: isCS ? 'Počet chybných AI odpovědí' : 'Failed AI responses count' },
        ];
        const statsHtml = `<div style="display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:10px; margin-bottom:18px;">` +
            stats.map(s => `<div style="background:var(--panel); border:1px solid var(--border); border-radius:6px; padding:10px 12px;">
                <div style="display:flex; align-items:center; gap:6px; margin-bottom:6px;">
                    <i class="fa-solid ${s.icon}" style="color:${s.color}; font-size:.9em;"></i>
                    <span style="font-size:.75em; color:var(--text-muted); text-transform:uppercase; letter-spacing:.04em;">${isCS ? s.cs : s.en}</span>
                </div>
                <div style="font-size:1.3em; font-weight:700; color:${s.color};">${_esc(String(s.val))}</div>
                <div style="font-size:.7em; color:var(--text-muted); margin-top:4px; line-height:1.3;">${s.desc}</div>
            </div>`).join('') + `</div>`;

        // Requests table
        const reqs = d.requests || [];
        const emptyMsg = isCS ? 'Fronta je prázdná — žádné čekající požadavky' : 'Queue is empty — no pending requests';
        const reqRows = reqs.length === 0
            ? `<tr><td colspan="5" style="text-align:center; color:var(--text-muted); padding:16px; font-style:italic;">${emptyMsg}</td></tr>`
            : reqs.map((req, i) => {
                const sc = req.status === 'processing' ? '#ffc107' : 'var(--text-muted)';
                const si = req.status === 'processing' ? 'fa-spinner fa-spin' : 'fa-clock';
                const time = req.created_at ? req.created_at.replace('T',' ').substring(0,16) : '—';
                return `<tr style="border-bottom:1px solid var(--border);">
                    <td style="padding:6px 8px; color:var(--text-muted); font-size:.85em;">${i+1}</td>
                    <td style="padding:6px 8px;"><span style="background:rgba(0,120,212,.15); color:#7cb9f0; border-radius:3px; padding:1px 6px; font-size:.8em;">${_esc(req.channel || '—')}</span></td>
                    <td style="padding:6px 8px; font-family:monospace; font-size:.82em;">${_esc(req.host || '—')}</td>
                    <td style="padding:6px 8px;"><i class="fa-solid ${si}" style="color:${sc}; margin-right:4px; font-size:.8em;"></i><span style="color:${sc}; font-size:.82em;">${_esc(req.status)}</span></td>
                    <td style="padding:6px 8px; color:var(--text-muted); font-size:.78em;">${time}</td>
                </tr>`;
            }).join('');

        el.innerHTML = statsHtml + `
            <div style="font-size:.8em; font-weight:600; color:var(--text-muted); text-transform:uppercase; letter-spacing:.05em; margin-bottom:8px;">
                ${lbl('Položky ve frontě', 'Queue Items')}
                <span style="font-weight:400; color:var(--text-muted); margin-left:6px;">(${reqs.length})</span>
            </div>
            <div style="overflow-x:auto; border:1px solid var(--border); border-radius:6px;">
            <table style="width:100%; border-collapse:collapse; font-size:.88em;">
                <thead><tr style="background:var(--panel);">
                    <th style="padding:7px 8px; text-align:left; color:var(--text-muted); font-weight:500; font-size:.8em;">#</th>
                    <th style="padding:7px 8px; text-align:left; color:var(--text-muted); font-weight:500; font-size:.8em;">${lbl('Kanál','Channel')}</th>
                    <th style="padding:7px 8px; text-align:left; color:var(--text-muted); font-weight:500; font-size:.8em;">${lbl('Host','Host')}</th>
                    <th style="padding:7px 8px; text-align:left; color:var(--text-muted); font-weight:500; font-size:.8em;">${lbl('Stav','Status')}</th>
                    <th style="padding:7px 8px; text-align:left; color:var(--text-muted); font-weight:500; font-size:.8em;">${lbl('Čas','Time')}</th>
                </tr></thead>
                <tbody>${reqRows}</tbody>
            </table>
            </div>`;
    } catch(e) {
        el.innerHTML = `<div style="color:var(--error); padding:16px;">${t('data_load_failed')}</div>`;
    }
}

// ─── Connection Status Modal ──────────────────────────────────────────────────

let _connRefreshInterval = null;

// 21: Sarkastický vtip o infrastruktuře po kliknutí na logo
async function _sentinelLogoJoke() {
    const ch = document.getElementById('chat-history');
    if (!ch) return;
    const bubble = document.createElement('div');
    bubble.style.cssText = 'align-self:center;max-width:85%;background:rgba(0,120,212,0.07);border:1px solid rgba(0,120,212,0.25);border-radius:12px;padding:14px 18px;font-size:.9em;color:var(--text-muted);font-style:italic;line-height:1.6;text-align:center;margin:4px 0;animation:fadeIn .4s ease;';
    const _jokeLang = localStorage.getItem('sentinel_lang') || 'cs';
    bubble.innerHTML = '<i class="fa-solid fa-spinner fa-spin" style="margin-right:6px;font-size:.85em;"></i>' + (_jokeLang === 'en' ? 'generating joke…' : 'generuji vtip…');
    ch.appendChild(bubble);
    ch.scrollTop = ch.scrollHeight;
    try {
        const r = await fetch('/api/analyze/infra_joke', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({lang: _jokeLang})});
        if (!r.ok) { const t = await r.text(); console.error('joke API error', r.status, t.slice(0,200)); throw new Error(r.status); }
        const d = await r.json();
        bubble.style.color = 'var(--text-main)';
        bubble.textContent = d.joke || '...';
        ch.scrollTop = ch.scrollHeight;
    } catch(e) {
        console.error('joke fetch failed:', e);
        const fallbacks = _jokeLang === 'en' ? [
            'Infrastructure is fine. Probably.',
            'Restart fixes 90% of problems. The other 10% need a second restart.',
            'Monitoring reports everything OK. Monitoring lies.',
            'Backup exists. Nobody has tested restore yet.',
            'Uptime 99.9% — that 0.1% was always Friday afternoon.',
            'Have you tried turning it off and on again? No? Why not.',
        ] : [
            'Infrastruktura funguje. Nejspíš.',
            'Restart vyřeší 90 % problémů. Zbylých 10 % vyřeší druhý restart.',
            'Server je jako manžel — nejlépe funguje, když ho ignoruješ.',
            'Monitoring hlásí vše v pořádku. Monitoring lže.',
            'Backup existuje. Restore ještě nikdo nezkoušel.',
            'Uptime 99,9 % — těch 0,1 % bylo vždy v pátek odpoledne.',
        ];
        bubble.textContent = fallbacks[Math.floor(Math.random() * fallbacks.length)];
    }
}

function openConnectionModal() {
    document.getElementById('connection-modal').style.display = 'flex';
    loadConnectionStatus();
    if (_connRefreshInterval) clearInterval(_connRefreshInterval);
    _connRefreshInterval = setInterval(loadConnectionStatus, 30000);
}

function closeConnectionModal() {
    document.getElementById('connection-modal').style.display = 'none';
    if (_connRefreshInterval) { clearInterval(_connRefreshInterval); _connRefreshInterval = null; }
}

async function loadConnectionStatus() {
    const body = document.getElementById('connection-modal-body');
    if (!body.innerHTML || body.innerHTML.includes('fa-spinner'))
        body.innerHTML = `<div style="text-align:center; padding:30px; color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i></div>`;
    try {
        const r = await fetch('/api/connection/status');
        const d = await r.json();

        const sv = d.server || {};
        const st = d.stats  || {};
        const ai = d.ai     || {};
        const ig = d.integrations || {};

        // uptime_seconds is in server, not stats
        const upSecs  = sv.uptime_seconds || 0;
        const upDays  = Math.floor(upSecs / 86400);
        const upHours = Math.floor((upSecs % 86400) / 3600);
        const upMins  = Math.floor((upSecs % 3600) / 60);
        const uptimeFmt = upDays > 0 ? `${upDays}d ${upHours}h ${upMins}m` : `${upHours}h ${upMins}m`;

        const dbKb = st.db_size_kb ?? 0;
        const dbFmt = dbKb >= 1024 ? `${(dbKb/1024).toFixed(1)} MB` : `${dbKb} KB`;

        const row = (icon, label, value, valueColor) =>
            `<tr style="border-bottom:1px solid var(--border);">
                <td style="padding:7px 0; color:var(--text-muted); width:44%; font-size:.87rem;"><i class="fa-solid fa-${icon}" style="width:16px; margin-right:6px; opacity:.55;"></i>${label}</td>
                <td style="padding:7px 0; font-size:.87rem; font-weight:600; color:${valueColor||'var(--text-main)'};">${value}</td>
             </tr>`;

        const section = (title) =>
            `<tr><td colspan="2" style="padding:12px 0 3px; font-size:.72rem; text-transform:uppercase; letter-spacing:.07em; color:var(--accent); font-weight:700;">${title}</td></tr>`;

        const intRow = (name, icon, cfg) => {
            const color = cfg.enabled ? (cfg.connected !== false ? 'var(--success)' : 'var(--warning)') : 'var(--text-muted)';
            const txt   = cfg.enabled ? (cfg.connected !== false ? t('connected_status') : t('not_connected_status')) : t('disabled_status');
            return row(icon, name, `<span style="color:${color};">${txt}</span>`, '');
        };

        // Uptime highlight card
        const uptimeCard = `<div style="display:flex;gap:8px;margin-bottom:12px;">
            <div style="flex:1;background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:10px 12px;text-align:center;">
                <div style="font-size:1.3rem;font-weight:700;color:var(--accent);">${uptimeFmt}</div>
                <div style="font-size:.72rem;color:var(--text-muted);margin-top:2px;text-transform:uppercase;letter-spacing:.05em;">${t('conn_uptime')}</div>
            </div>
            <div style="flex:1;background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:10px 12px;text-align:center;">
                <div style="font-size:1.3rem;font-weight:700;color:var(--text-main);">${st.active_issues ?? 0}</div>
                <div style="font-size:.72rem;color:var(--text-muted);margin-top:2px;text-transform:uppercase;letter-spacing:.05em;">Aktivní issues</div>
            </div>
            <div style="flex:1;background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:10px 12px;text-align:center;">
                <div style="font-size:1.3rem;font-weight:700;color:var(--text-main);">${dbFmt}</div>
                <div style="font-size:.72rem;color:var(--text-muted);margin-top:2px;text-transform:uppercase;letter-spacing:.05em;">${t('conn_db_size')}</div>
            </div>
        </div>`;

        body.innerHTML = uptimeCard + `<table style="width:100%; border-collapse:collapse;">
            ${section(t('conn_section_server'))}
            ${row('server', t('conn_hostname'), sv.hostname || '?')}
            ${row('tag', t('conn_version'), `<span style="color:var(--accent);">v${sv.version || '?'}</span> <span style="color:var(--text-muted);font-size:.8rem;font-weight:400;">${sv.instance_name || ''}</span>`, '')}
            ${row('plug', t('conn_listen'), `${sv.host}:${sv.port}`)}
            ${row('users', t('conn_ws_clients'), String(st.ws_clients ?? 0))}
            ${row('cube', t('conn_ai_model'), (ai.model || '?') + (ai.hailo_enabled ? ' <span style="color:#f59e0b;font-size:.78em;font-weight:700;">NPU</span>' : ''), 'var(--accent)')}
            ${row('circle-nodes', 'AI backend', ai.backend || '?')}
            ${row('robot', 'AI requests', `${st.ai_requests ?? 0} <span style="color:var(--text-muted);font-size:.8em;font-weight:400;">chyby: ${st.ai_errors ?? 0}</span>`)}
            ${row('stopwatch', 'Avg latence', st.avg_latency_s ? `${st.avg_latency_s}s` : '—')}

            ${section(t('conn_section_integrations'))}
            ${intRow('MQTT', 'network-wired', ig.mqtt || {})}
            ${intRow('Home Assistant', 'house-signal', ig.homeassistant || {})}
            ${intRow('MS Teams', 'brands fa-microsoft', ig.teams || {})}
            ${intRow('Slack', 'brands fa-slack', ig.slack || {})}
            ${intRow('ntfy', 'bell', ig.ntfy || {})}
            ${intRow('Gotify', 'paper-plane', ig.gotify || {})}
            ${intRow('Matrix', 'comment', ig.matrix || {})}
            ${intRow('SMTP Email', 'envelope', ig.smtp || {})}
        </table>
        <div style="text-align:right;margin-top:8px;font-size:.72rem;color:var(--text-muted);"><i class="fa-solid fa-rotate" style="margin-right:4px;"></i>Aktualizace každých 30 s</div>`;
    } catch(e) {
        body.innerHTML = `<div style="color:var(--error); padding:20px;">${t('data_load_failed')}: ${e.message}</div>`;
    }
}

// ─── History Modal ────────────────────────────────────────────────────────────

async function openHistoryModal() {
    document.getElementById('history-modal').style.display = 'flex';
    const el = document.getElementById('history-content');
    if (el.dataset.loaded) return;
    el.innerHTML = `<div style="text-align:center; padding:30px; color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i></div>`;
    try {
        const r = await fetch('/api/history');
        const d = await r.json();
        el.dataset.loaded = '1';
        el.innerHTML = _renderMarkdown(d.content || '');
    } catch(e) {
        el.innerHTML = `<div style="color:var(--error); padding:16px;">${t('data_load_failed')}</div>`;
    }
}

function closeHistoryModal() { document.getElementById('history-modal').style.display = 'none'; }

function _renderMarkdown(text) {
    return text
        .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
        .replace(/^### (.+)$/gm, '<h3 style="color:var(--accent); margin:18px 0 6px; font-size:1em;">$1</h3>')
        .replace(/^## (.+)$/gm, '<h2 style="color:var(--text-main); margin:24px 0 8px; font-size:1.1em; border-bottom:1px solid var(--border); padding-bottom:4px;">$1</h2>')
        .replace(/^# (.+)$/gm, '<h1 style="color:var(--text-main); margin:0 0 16px; font-size:1.25em;">$1</h1>')
        .replace(/^\- (.+)$/gm, '<li style="margin:3px 0; color:var(--text-muted);">$1</li>')
        .replace(/`([^`]+)`/g, '<code style="background:var(--panel); padding:1px 5px; border-radius:3px; font-size:0.88em;">$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\n{2,}/g, '</p><p style="margin:6px 0;">')
        .replace(/\n/g, '<br>');
}

// ─── Role Management Modal ────────────────────────────────────────────────────

async function openRoleModal() {
    document.getElementById('role-modal').style.display = 'flex';
    const el = document.getElementById('role-modal-content');
    const role = (window.currentUsername || '').length > 0 ? null : null;
    el.innerHTML = `<div style="text-align:center; padding:20px; color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>`;
    try {
        const r = await fetch('/api/users/roles');
        if (r.status === 403) {
            el.innerHTML = `<div style="text-align:center; padding:24px; color:var(--text-muted);">
                <i class="fa-solid fa-lock" style="font-size:2em; margin-bottom:12px; display:block; color:var(--warning);"></i>
                <p style="font-size:0.95em;">${t('role_contact_admin')}</p>
            </div>`;
            return;
        }
        const d = await r.json();
        const users = d.users || [];
        const roles = ['viewer', 'operator', 'admin', 'superadmin'];
        el.innerHTML = `
            <div style="margin-bottom:16px; padding:12px 14px; background:var(--panel); border-radius:6px; border:1px solid var(--border);">
                <div style="font-size:0.8em; color:var(--text-muted); margin-bottom:10px; text-transform:uppercase; letter-spacing:.5px;">${t('role_add_user')}</div>
                <div style="display:flex; gap:8px; flex-wrap:wrap;">
                    <input type="text" id="role-new-user" placeholder="${t('role_username_ph')}" style="flex:1; min-width:120px; padding:7px 10px; background:var(--input-bg); color:var(--text-main); border:1px solid var(--border); border-radius:4px; font-size:0.88em;">
                    <select id="role-new-role" style="padding:7px 10px; background:var(--input-bg); color:var(--text-main); border:1px solid var(--border); border-radius:4px; font-size:0.88em;">
                        ${roles.map(r => `<option value="${r}">${r}</option>`).join('')}
                    </select>
                    <button onclick="addUserRole()" style="background:var(--accent); color:#fff; border:none; padding:7px 14px; border-radius:4px; cursor:pointer; font-size:0.85em;"><i class="fa-solid fa-plus"></i></button>
                </div>
                <div id="role-add-msg" style="font-size:0.82em; margin-top:6px; min-height:16px;"></div>
            </div>
            <div style="display:flex; flex-direction:column; gap:6px;">
                ${users.map(u => `
                    <div style="display:flex; align-items:center; gap:8px; padding:8px 12px; background:var(--panel); border:1px solid var(--border); border-radius:6px;">
                        <i class="fa-solid fa-user" style="color:var(--text-muted); flex-shrink:0;"></i>
                        <span style="flex:1; font-size:0.88em; font-weight:600;">${_escape(u.username)}</span>
                        <span style="font-size:0.78em; color:var(--text-muted);">${_escape(u.source)}</span>
                        <span style="font-size:0.82em; padding:2px 8px; border-radius:10px; background:rgba(99,102,241,0.15); color:var(--accent);">${_escape(u.role)}</span>
                        ${u.source === 'db' ? `<button onclick="deleteUserRole('${_escape(u.username)}')" style="background:transparent; border:none; color:var(--error); cursor:pointer; font-size:0.85em; padding:2px 6px;"><i class="fa-solid fa-trash"></i></button>` : ''}
                    </div>`).join('')}
            </div>`;
    } catch(e) {
        el.innerHTML = `<div style="color:var(--error); padding:16px;">${t('data_load_failed')}</div>`;
    }
}

function closeRoleModal() { document.getElementById('role-modal').style.display = 'none'; }

async function addUserRole() {
    const username = document.getElementById('role-new-user')?.value.trim();
    const role = document.getElementById('role-new-role')?.value;
    const msg = document.getElementById('role-add-msg');
    if (!username) { msg.textContent = t('role_username_required'); msg.style.color = 'var(--error)'; return; }
    try {
        const r = await fetch('/api/users/roles', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ username, role })
        });
        const d = await r.json();
        if (d.status === 'ok') { msg.textContent = t('role_saved'); msg.style.color = 'var(--success)'; openRoleModal(); }
        else { msg.textContent = d.error || t('error_generic'); msg.style.color = 'var(--error)'; }
    } catch(e) { msg.textContent = t('error_generic'); msg.style.color = 'var(--error)'; }
}

async function deleteUserRole(username) {
    try {
        await fetch(`/api/users/roles/${encodeURIComponent(username)}`, { method: 'DELETE' });
        openRoleModal();
    } catch(e) { console.error(e); }
}

// ─── Integration Toggle Modal ─────────────────────────────────────────────────

const _integrationMeta = {
    teams: { label: 'MS Teams', icon: 'fa-brands fa-microsoft' },
    homeassistant: { label: 'Home Assistant', icon: 'fa-solid fa-house-signal' },
    mqtt: { label: 'MQTT Broker', icon: 'fa-solid fa-network-wired' },
    webhook: { label: 'Webhook', icon: 'fa-solid fa-globe' },
};

let _currentIntegration = null;

async function openIntegrationModal(name) {
    _currentIntegration = name;
    const meta = _integrationMeta[name] || { label: name, icon: 'fa-solid fa-plug' };
    document.getElementById('integration-modal-title').innerHTML =
        `<i class="${meta.icon}" style="color:var(--accent);"></i> ${meta.label}`;
    document.getElementById('integration-modal').style.display = 'flex';
    const el = document.getElementById('integration-modal-content');
    el.innerHTML = `<div style="text-align:center;padding:20px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>`;

    let details = null;
    try {
        const r = await fetch(`/api/integrations/${name}/status`);
        details = await r.json();
    } catch(e) { /* show toggle-only fallback below */ }

    const isAdmin = window.currentRole === 'admin' || window.currentRole === 'superadmin';
    const toggleBtn = isAdmin ? `
        <div style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap;">
            <button onclick="toggleIntegration('${name}')" style="flex:1;min-width:120px;max-width:180px;background:var(--accent);color:#fff;border:none;padding:8px 0;border-radius:4px;cursor:pointer;font-size:0.88em;">
                <i class="fa-solid fa-power-off"></i> ${t('integration_toggle_btn')}
            </button>
            <button onclick="testIntegration('${name}')" id="integration-test-btn" style="flex:1;min-width:100px;max-width:140px;background:transparent;border:1px solid var(--success,#28a745);color:var(--success,#28a745);padding:8px 0;border-radius:4px;cursor:pointer;font-size:0.88em;">
                <i class="fa-solid fa-paper-plane"></i> Test
            </button>
        </div>
        <div id="integration-toggle-msg" style="margin-top:8px;font-size:0.82em;min-height:18px;text-align:center;"></div>` : '';

    if (!details || details.error) {
        el.innerHTML = `<div style="text-align:center;padding:20px;">${toggleBtn}</div>`;
        return;
    }

    const statusDot = (ok) => `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${ok ? 'var(--success)' : 'var(--text-muted)'};margin-right:6px;"></span>`;
    const yesNo = (v) => v ? `<span style="color:var(--success)">${t('yes')}</span>` : `<span style="color:var(--text-muted)">${t('no')}</span>`;

    const TR = (label, val) =>
        `<tr style="border-bottom:1px solid var(--border);">
            <td style="padding:8px 6px;color:var(--text-muted);width:45%;">${label}</td>
            <td style="padding:8px 6px;">${val}</td>
        </tr>`;

    let rows = '';
    if (name === 'mqtt') {
        const st = details.enabled ? (details.connected ? t('int_connected') : t('int_disconnected')) : t('disabled_status');
        rows = TR(t('int_status'), statusDot(details.enabled && details.connected) + st)
             + TR(t('conn_listen'), `${details.host}:${details.port}`)
             + TR(t('int_user'), details.user || '—')
             + TR(t('int_topic_prefix'), details.topic_prefix);
    } else if (name === 'homeassistant') {
        rows = TR(t('int_status'), statusDot(details.enabled) + (details.enabled ? t('enabled') : t('disabled_status')))
             + TR('URL', `<span style="word-break:break-all;">${details.url || '—'}</span>`)
             + TR(t('int_notify_service'), details.notify_service || '—')
             + TR(t('int_token'), yesNo(details.token_configured));
    } else if (name === 'teams') {
        rows = TR(t('int_status'), statusDot(details.enabled) + (details.enabled ? t('enabled') : t('disabled_status')))
             + TR(t('int_channels'), details.channels_count)
             + TR(t('int_channel_names'), details.channels.length ? details.channels.join(', ') : '—');
    } else if (name === 'webhook') {
        rows = TR(t('int_status'), statusDot(details.enabled) + (details.enabled ? t('enabled') : t('disabled_status')))
             + TR('URL', `<span style="word-break:break-all;">${details.url || '—'}</span>`)
             + TR(t('int_secret'), yesNo(details.secret_configured));
    }

    let configForm = '';
    if (isAdmin && (name === 'mqtt' || name === 'homeassistant')) {
        const _inp = (id,label,val,type,ph) => `<div style="margin-bottom:8px;"><label style="display:block;font-size:.78em;color:var(--text-muted);margin-bottom:2px;">${label}</label><input id="cfg-${id}" type="${type||'text'}" value="${(val!==undefined&&val!==null)?String(val).replace(/"/g,'&quot;'):''}" placeholder="${ph||''}" autocomplete="off" style="width:100%;padding:6px;background:var(--input-bg,#1e1e1e);color:var(--text-main);border:1px solid var(--border);border-radius:4px;font-size:.85em;box-sizing:border-box;"></div>`;
        let _f = '';
        if (name === 'mqtt') {
            _f = _inp('mqtt_host','Host',details.host) + _inp('mqtt_port','Port',details.port,'number') + _inp('mqtt_user','User',details.user) + _inp('mqtt_pass','Heslo','','password','(pr\u00e1zdn\u00e9 = beze zm\u011bny)') + _inp('mqtt_topic_prefix','Topic prefix',details.topic_prefix);
        } else {
            _f = _inp('ha_url','URL',details.url,'text','http://homeassistant:8123') + _inp('ha_notify_service','Notify service',details.notify_service,'text','mobile_app_x') + _inp('ha_token','Token','','password','(pr\u00e1zdn\u00e9 = beze zm\u011bny)');
        }
        configForm = `<details style="margin-top:10px;"><summary style="cursor:pointer;color:var(--accent);font-size:.85em;"><i class="fa-solid fa-gear"></i> Konfigurovat</summary><div style="margin-top:8px;">${_f}<button onclick="saveIntegrationConfig('${name}')" style="width:100%;background:var(--accent);color:#fff;border:none;padding:8px;border-radius:4px;cursor:pointer;font-size:.85em;"><i class="fa-solid fa-floppy-disk"></i> Ulo\u017eit</button><div id="integration-cfg-msg" style="margin-top:6px;font-size:.8em;min-height:16px;text-align:center;"></div></div></details>`;
    }
    el.innerHTML = `
        <table style="width:100%;border-collapse:collapse;font-size:0.9em;margin-bottom:${isAdmin ? '18' : '4'}px;">
            ${rows}
        </table>
        ${configForm}
        <div style="text-align:center;margin-top:10px;">${toggleBtn}</div>`;
}

function closeIntegrationModal() {
    document.getElementById('integration-modal').style.display = 'none';
    _currentIntegration = null;
}

async function saveIntegrationConfig(name) {
    const msg = document.getElementById('integration-cfg-msg');
    const v = id => { const e = document.getElementById('cfg-' + id); return e ? e.value.trim() : ''; };
    const payload = {};
    if (name === 'mqtt') {
        payload['mqtt.host'] = v('mqtt_host');
        payload['mqtt.port'] = v('mqtt_port') || '1883';
        payload['mqtt.user'] = v('mqtt_user');
        payload['mqtt.topic_prefix'] = v('mqtt_topic_prefix') || 'sentinel';
        const p = v('mqtt_pass'); if (p) payload['mqtt.pass'] = p;   // prázdné nepřepisuje
    } else if (name === 'homeassistant') {
        payload['homeassistant.url'] = v('ha_url');
        payload['homeassistant.notify_service'] = v('ha_notify_service');
        const tok = v('ha_token'); if (tok) payload['homeassistant.token'] = tok;  // prázdné nepřepisuje
    }
    if (msg) { msg.textContent = '\u23f3 Ukl\u00e1d\u00e1m\u2026'; msg.style.color = 'var(--text-muted)'; }
    try {
        const r = await fetch('/api/config/update', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
        const d = await r.json().catch(() => ({}));
        if (r.ok && (d.status === 'ok' || d.status === undefined)) {
            if (msg) { msg.textContent = '\u2705 Ulo\u017eeno a aplikov\u00e1no'; msg.style.color = 'var(--success)'; }
        } else {
            if (msg) { msg.textContent = '\u26a0\ufe0f ' + (d.message || 'chyba ukl\u00e1d\u00e1n\u00ed'); msg.style.color = 'var(--error)'; }
        }
    } catch (e) {
        if (msg) { msg.textContent = '\u26a0\ufe0f ' + e; msg.style.color = 'var(--error)'; }
    }
}

// ── Notifications & Integrations Modal ──────────────────────────────────────
let _notiTab = null;

function openNotificationsModal(tab) {
    document.getElementById('notifications-modal').style.display = 'flex';
    switchNotiTab(tab || 'mqtt');
}

function switchNotiTab(name) {
    _notiTab = name;
    document.querySelectorAll('[id^="ntab-"]').forEach(b => {
        if (b.id !== 'ntab-content') b.classList.toggle('active', b.id === `ntab-${name}`);
    });
    _loadNotiTab(name);
}

async function _loadNotiTab(name) {
    const el = document.getElementById('ntab-content');
    if (!el) return;
    el.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>';
    try {
        const r = await fetch(`/api/integrations/${name}/status`);
        const d = await r.json();
        const isAdmin = window.currentRole === 'admin' || window.currentRole === 'superadmin';

        const enabledBadge = d.enabled
            ? `<span style="color:var(--success);font-weight:600;"><i class="fa-solid fa-circle" style="font-size:.6em;vertical-align:middle;"></i> Aktivní</span>`
            : `<span style="color:var(--text-muted);"><i class="fa-regular fa-circle" style="font-size:.6em;vertical-align:middle;"></i> Vypnuto</span>`;
        const toggleBtn = isAdmin
            ? `<button onclick="_notiToggle('${name}')" style="padding:4px 12px;background:${d.enabled?'rgba(220,53,69,.15)':'rgba(40,167,69,.15)'};border:1px solid ${d.enabled?'rgba(220,53,69,.4)':'rgba(40,167,69,.4)'};color:${d.enabled?'#f87171':'var(--success)'};border-radius:4px;cursor:pointer;font-size:.82em;">${d.enabled?'Vypnout':'Zapnout'}</button>`
            : '';

        // Helper: status table row
        const SR = (label, val) => `<tr><td style="padding:4px 0;color:var(--text-muted);width:40%;">${label}</td><td>${val}</td></tr>`;
        let statusTable = '';
        if (name === 'mqtt') {
            statusTable = SR('Připojeno', d.connected ? '<span style="color:var(--success);">✓ Ano</span>' : '<span style="color:var(--error);">✗ Ne</span>')
                        + SR('Broker', `${_escape(d.host||'—')}:${d.port||1883}`)
                        + SR('Topic prefix', `<code>${_escape(d.topic_prefix||'sentinel')}</code>`)
                        + (d.user ? SR('Uživatel', _escape(d.user)) : '');
        } else if (name === 'homeassistant') {
            statusTable = SR('URL', _escape(d.url||'—'))
                        + SR('Notify service', `<code>${_escape(d.notify_service||'—')}</code>`)
                        + SR('Token', d.token_configured ? '✓ Nastaven' : '<span style="color:var(--error);">✗ Chybí</span>');
        } else if (name === 'teams') {
            statusTable = SR('Webhooky', `${d.channels_count||0} kanál(ů)`)
                        + SR('Kanály', (d.channels||[]).join(', ')||'—');
        } else if (name === 'webhook') {
            statusTable = SR('URL', d.url ? `<code style="font-size:.82em;word-break:break-all;">${_escape(d.url)}</code>` : '<span style="color:var(--text-muted);">—</span>')
                        + SR('HMAC Secret', d.secret_configured ? '✓ Nastaven' : '<span style="color:var(--text-muted);">✗ Nenastaveno</span>');
        } else if (name === 'slack') {
            statusTable = SR('Webhook', d.webhook_configured ? '✓ Nastaven' : '<span style="color:var(--error);">✗ Chybí</span>')
                        + SR('Kanál', _escape(d.channel||'—'));
        } else if (name === 'pagerduty') {
            statusTable = SR('Routing Key', d.routing_key_configured ? '✓ Nastaven' : '<span style="color:var(--error);">✗ Chybí</span>');
        }

        // Config form (admin only)
        let configForm = '';
        if (isAdmin) {
            const inp = (id, label, val, type, ph) =>
                `<div style="margin-bottom:9px;">
                    <label style="display:block;font-size:.76em;color:var(--text-muted);margin-bottom:3px;text-transform:uppercase;letter-spacing:.04em;">${label}</label>
                    <input id="ncfg-${id}" type="${type||'text'}" value="${(val!==null&&val!==undefined)?String(val).replace(/"/g,'&quot;'):''}"
                        placeholder="${ph||''}" autocomplete="${type==='password'?'new-password':'off'}"
                        style="width:100%;padding:7px 9px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:4px;font-size:.85em;box-sizing:border-box;">
                </div>`;
            const chk = (id, label, checked) =>
                `<label style="display:flex;align-items:center;gap:8px;margin-bottom:12px;cursor:pointer;font-size:.88em;">
                    <input type="checkbox" id="ncfg-${id}" ${checked?'checked':''} style="accent-color:var(--accent);width:15px;height:15px;">
                    ${label}
                </label>`;
            const row2 = (a, b) => `<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">${a}${b}</div>`;

            let fields = '';
            if (name === 'mqtt') {
                fields = chk('mqtt-enabled','Povoleno', d.enabled)
                       + row2(inp('mqtt-host','Broker host', d.host), inp('mqtt-port','Port', d.port||1883, 'number'))
                       + row2(inp('mqtt-user','Uživatel', d.user||''), inp('mqtt-pass','Heslo','','password','(prázdné = beze změny)'))
                       + inp('mqtt-topic','Topic prefix', d.topic_prefix||'sentinel');
            } else if (name === 'homeassistant') {
                fields = chk('ha-enabled','Povoleno', d.enabled)
                       + inp('ha-url','URL', d.url||'', 'text', 'http://homeassistant:8123')
                       + inp('ha-notify','Notify service', d.notify_service||'', 'text', 'mobile_app_x')
                       + inp('ha-token','Token (Long-Lived Access Token)', '', 'password', '(prázdné = beze změny)');
            } else if (name === 'teams') {
                fields = chk('teams-enabled','Povoleno', d.enabled)
                       + inp('teams-webhook','Webhook URL (general)', d.general_webhook||'', 'text', 'https://...');
            } else if (name === 'webhook') {
                fields = chk('wh-enabled','Povoleno', d.enabled)
                       + inp('wh-url','Webhook URL', d.url_full||d.url||'', 'text', 'https://hooks.example.com/sentinel')
                       + inp('wh-secret','HMAC Secret', '', 'password', '(prázdné = beze změny)');
            } else if (name === 'slack') {
                fields = chk('slack-enabled','Povoleno', d.enabled)
                       + inp('slack-webhook','Webhook URL', d.webhook_url||'', 'text', 'https://hooks.slack.com/services/...')
                       + inp('slack-channel','Kanál (volitelné)', d.channel||'', 'text', '#alerts');
            } else if (name === 'pagerduty') {
                fields = chk('pd-enabled','Povoleno', d.enabled)
                       + inp('pd-key','Routing Key (Integration Key)', '', 'password', '(prázdné = beze změny)');
            }

            configForm = `<div style="margin-top:16px;padding-top:14px;border-top:1px solid var(--border);">
                <div style="font-size:.72rem;text-transform:uppercase;letter-spacing:.07em;color:var(--accent);margin-bottom:12px;font-weight:700;"><i class="fa-solid fa-gear"></i> Konfigurace</div>
                ${fields}
                <div style="display:flex;gap:8px;margin-top:10px;">
                    <button onclick="_notiSave('${name}')" style="flex:1;padding:8px;background:var(--accent);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.85em;font-weight:600;"><i class="fa-solid fa-floppy-disk"></i> Uložit</button>
                    <button onclick="_notiTest('${name}')" style="padding:8px 16px;background:transparent;border:1px solid var(--border);color:var(--text-muted);border-radius:4px;cursor:pointer;font-size:.85em;"><i class="fa-solid fa-flask"></i> Test</button>
                </div>
                <div id="noti-save-result" style="margin-top:8px;font-size:.82em;min-height:16px;text-align:center;"></div>
                <div id="noti-test-result" style="margin-top:4px;font-size:.82em;min-height:16px;text-align:center;"></div>
            </div>`;
        }

        el.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                <div style="font-size:.92em;">${enabledBadge}</div>
                <div>${toggleBtn}</div>
            </div>
            <table style="width:100%;font-size:.85em;border-collapse:collapse;">${statusTable}</table>
            ${configForm}`;
    } catch(e) {
        el.innerHTML = `<div style="color:var(--error);">Chyba: ${_escape(e.message)}</div>`;
    }
}

async function _notiSave(name) {
    const v = id => { const e = document.getElementById('ncfg-' + id); return e ? (e.type === 'checkbox' ? e.checked : e.value.trim()) : undefined; };
    const res = document.getElementById('noti-save-result');
    if (res) { res.style.color = 'var(--text-muted)'; res.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Ukládám…'; }

    let payload = {};
    if (name === 'mqtt') {
        payload = { enabled: v('mqtt-enabled'), host: v('mqtt-host'), port: parseInt(v('mqtt-port'))||1883, user: v('mqtt-user'), topic_prefix: v('mqtt-topic') };
        const p = v('mqtt-pass'); if (p) payload.pass = p;
    } else if (name === 'homeassistant') {
        payload = { enabled: v('ha-enabled'), url: v('ha-url'), notify_service: v('ha-notify') };
        const t = v('ha-token'); if (t) payload.token = t;
    } else if (name === 'teams') {
        payload = { enabled: v('teams-enabled'), webhook_url: v('teams-webhook') };
    } else if (name === 'webhook') {
        payload = { enabled: v('wh-enabled'), url: v('wh-url') };
        const s = v('wh-secret'); if (s) payload.secret = s;
    } else if (name === 'slack') {
        payload = { enabled: v('slack-enabled'), webhook_url: v('slack-webhook'), channel: v('slack-channel') };
    } else if (name === 'pagerduty') {
        payload = { enabled: v('pd-enabled') };
        const k = v('pd-key'); if (k) payload.routing_key = k;
    }

    try {
        const r = await fetch(`/api/integrations/${name}/save`, {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
        });
        const d = await r.json();
        if (res) {
            res.style.color = d.status === 'ok' ? 'var(--success)' : (d.status === 'warning' ? 'var(--warning)' : 'var(--error)');
            res.innerHTML = d.status === 'ok' ? '✅ Uloženo' : `⚠ ${d.message || d.error || 'Chyba'}`;
        }
        if (d.status === 'ok') setTimeout(() => _loadNotiTab(name), 900);
    } catch(e) {
        if (res) { res.style.color = 'var(--error)'; res.innerHTML = `⚠ ${e}`; }
    }
}

async function _notiToggle(name) {
    await fetch(`/api/integrations/${name}/toggle`, {method:'POST'});
    _loadNotiTab(name);
}

async function _notiTest(name) {
    const res = document.getElementById('noti-test-result');
    if (res) res.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Testuji…';
    try {
        const r = await fetch(`/api/integrations/${name}/test`, {method:'POST'});
        const d = await r.json();
        if (res) {
            res.style.color = d.status === 'ok' ? 'var(--success)' : 'var(--error)';
            res.innerHTML = d.status === 'ok'
                ? `<i class="fa-solid fa-check"></i> ${_escape(d.reply||'OK')}`
                : `<i class="fa-solid fa-xmark"></i> ${_escape(d.reply||d.error||'Chyba')}`;
        }
    } catch(e) { if (res) { res.style.color='var(--error)'; res.innerHTML=String(e); } }
}

// Zpětná kompatibilita — původní openIntegrationModal přesměruje na nový modal
function _openIntegrationModalCompat(name) {
    openNotificationsModal(name);
}

async function toggleIntegration(name) {
    const msg = document.getElementById('integration-toggle-msg');
    msg.textContent = '...'; msg.style.color = 'var(--text-muted)';
    try {
        const r = await fetch(`/api/integrations/${name}/toggle`, { method: 'POST' });
        const d = await r.json();
        if (d.status === 'ok') {
            // Refresh modal content so status dot + label reflect new state
            await openIntegrationModal(name);
            const msgRefreshed = document.getElementById('integration-toggle-msg');
            if (msgRefreshed) {
                msgRefreshed.textContent = t('integration_toggled', {state: d.enabled ? t('enabled') : t('disabled')});
                msgRefreshed.style.color = d.enabled ? 'var(--success)' : 'var(--text-muted)';
            }
        } else {
            msg.textContent = d.error || t('error_generic');
            msg.style.color = 'var(--error)';
        }
    } catch(e) {
        msg.textContent = t('error_generic'); msg.style.color = 'var(--error)';
    }
}

async function testIntegration(name) {
    const msg = document.getElementById('integration-toggle-msg');
    const btn = document.getElementById('integration-test-btn');
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Odesílám…'; }
    msg.textContent = ''; msg.style.color = 'var(--text-muted)';
    try {
        const r = await fetch(`/api/integrations/${name}/test`, { method: 'POST' });
        const d = await r.json();
        if (d.status === 'ok') {
            msg.textContent = `✅ ${d.reply || 'Odesláno'}`;
            msg.style.color = 'var(--success,#28a745)';
        } else {
            msg.textContent = `❌ ${d.reply || d.error || 'Chyba'}`;
            msg.style.color = 'var(--error,#dc3545)';
        }
    } catch(e) {
        msg.textContent = '❌ Chyba sítě'; msg.style.color = 'var(--error,#dc3545)';
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Test'; }
    }
}

// ─── Token Display Modal (agent registration) ─────────────────────────────────

function showTokenModal(hostname, token) {
    document.getElementById('token-modal-hostname').textContent = hostname;
    document.getElementById('token-modal-value').textContent = token;
    document.getElementById('token-display-modal').style.display = 'flex';
    // 155: Generate QR code with agent config payload
    const qrEl = document.getElementById('token-modal-qr');
    if (qrEl) {
        qrEl.innerHTML = '';
        requestAnimationFrame(() => {
            if (typeof QRCode !== 'undefined') {
                const ingestUrl = window.location.origin + '/api/v1/agent/ingest';
                const payload = JSON.stringify({hostname, token, ingest_url: ingestUrl});
                try {
                    new QRCode(qrEl, {text: payload, width: 148, height: 148, colorDark: '#000', colorLight: '#fff', correctLevel: QRCode.CorrectLevel.M});
                } catch(e) {
                    qrEl.innerHTML = '<div style="font-size:.72em;color:#555;padding:8px;text-align:center;">QR nelze generovat</div>';
                }
            } else {
                qrEl.innerHTML = '<div style="font-size:.72em;color:#555;padding:8px;text-align:center;">QR knihovna není načtena</div>';
            }
        });
    }
}

function closeTokenModal() {
    document.getElementById('token-display-modal').style.display = 'none';
    document.getElementById('token-modal-value').textContent = '';
    const qrEl = document.getElementById('token-modal-qr');
    if (qrEl) qrEl.innerHTML = '';
}

async function copyAgentToken() {
    const val = document.getElementById('token-modal-value').textContent;
    const btn = document.getElementById('token-copy-btn');
    await safeCopyText(val);
    btn.innerHTML = `<i class="fa-solid fa-check"></i> ${t('token_modal_copied')}`;
    btn.style.background = 'var(--success)';
    setTimeout(() => {
        btn.innerHTML = `<i class="fa-solid fa-copy"></i> ${t('token_modal_copy')}`;
        btn.style.background = '';
    }, 2000);
}

// ─── Hailo AI HAT 2+ model switcher ──────────────────────────────────────────

async function setHailoModel(model) {
    const sel = document.getElementById('hailo-model-sel');
    if (sel) sel.disabled = true;
    try {
        const r = await fetch('/api/hailo-ollama/model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model })
        });
        const d = await r.json();
        if (d.status !== 'ok') {
            console.error('Hailo model switch failed:', d.message);
            alert(t('model_switch_error', {msg: d.message || 'unknown'}));
        }
    } catch (e) {
        console.error('setHailoModel error:', e);
    } finally {
        if (sel) sel.disabled = false;
    }
}

// ─── Suppress Rules ──────────────────────────────────────────────────────────

async function _supLoad() {
    const el = document.getElementById('sup-list');
    if (!el) return;
    el.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i>`;
    try {
        const r = await fetch('/api/suppress/rules');
        const d = await r.json();
        const rules = d.rules || [];
        if (!rules.length) {
            el.innerHTML = `<div style="color:var(--text-muted);padding:16px 0;">Žádná pravidla suprese.</div>`;
            return;
        }
        el.innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:.85em;">
            <thead><tr style="border-bottom:1px solid var(--border);color:var(--text-muted);">
                <th style="padding:6px 8px;text-align:left;">Host</th>
                <th style="padding:6px 8px;text-align:left;">Plugin</th>
                <th style="padding:6px 8px;text-align:left;">Důvod</th>
                <th style="padding:6px 8px;text-align:left;">Přidal</th>
                <th style="padding:6px 8px;text-align:left;">Vyprší</th>
                <th style="padding:6px 8px;"></th>
            </tr></thead>
            <tbody>${rules.map(r => `
            <tr style="border-bottom:1px solid var(--border);">
                <td style="padding:6px 8px;"><code>${_escape(r.host_pattern)}</code></td>
                <td style="padding:6px 8px;"><code>${_escape(r.plugin_pattern)}</code></td>
                <td style="padding:6px 8px;color:var(--text-muted);">${_escape(r.reason||'—')}</td>
                <td style="padding:6px 8px;color:var(--text-muted);">${_escape(r.created_by||'—')}</td>
                <td style="padding:6px 8px;color:var(--text-muted);">${r.expires_at ? r.expires_at.slice(0,16) : '∞'}</td>
                <td style="padding:6px 8px;text-align:right;">
                    <button onclick="_supDelete(${r.id})" style="padding:3px 8px;background:transparent;border:1px solid var(--error);color:var(--error);border-radius:3px;cursor:pointer;font-size:.8em;">
                        <i class="fa-solid fa-trash"></i>
                    </button>
                </td>
            </tr>`).join('')}</tbody>
        </table>`;
    } catch(e) {
        el.innerHTML = `<div style="color:var(--error);">Chyba: ${_escape(e.message)}</div>`;
    }
}

async function _supAdd() {
    const host = document.getElementById('sup-host')?.value.trim() || '*';
    const plugin = document.getElementById('sup-plugin')?.value.trim();
    const reason = document.getElementById('sup-reason')?.value.trim() || '';
    if (!plugin) { alert('Zadej plugin pattern (např. SEC_UPDATE nebo *)'); return; }
    try {
        const r = await fetch('/api/suppress/rules', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({host_pattern: host, plugin_pattern: plugin, reason})
        });
        const d = await r.json();
        if (d.status === 'ok') {
            document.getElementById('sup-plugin').value = '';
            document.getElementById('sup-reason').value = '';
            _supLoad();
            _toolsTabLoaded.delete('suppress');
            _toolsTabLoaded.add('suppress');
        } else {
            alert('Chyba: ' + (d.error || 'unknown'));
        }
    } catch(e) { alert('Chyba: ' + e.message); }
}

async function _supDelete(id) {
    if (!confirm('Smazat toto pravidlo suprese?')) return;
    try {
        const r = await fetch(`/api/suppress/rules/${id}`, {method: 'DELETE'});
        const d = await r.json();
        if (d.status === 'ok') _supLoad();
        else alert('Chyba: ' + (d.error || 'unknown'));
    } catch(e) { alert('Chyba: ' + e.message); }
}

// ── Keyboard Shortcuts Overlay (002) ─────────────────────────────────────────
const _SHORTCUTS = [
    { key: '?',      desc: 'Zobrazit přehled zkratek' },
    { key: 'Esc',    desc: 'Zavřít modal / overlay' },
    { key: 'r',      desc: 'Obnovit status (refresh)' },
    { key: 's',      desc: 'Otevřít Settings modal' },
    { key: 'a',      desc: 'Otevřít Tools modal (AI+Export)' },
    { key: 'n',      desc: 'Přejít na chat input' },
    { key: '1',      desc: 'Otevřít INFRA issues' },
    { key: '2',      desc: 'Otevřít AGENT issues' },
    { key: '3',      desc: 'Otevřít SECURITY issues' },
    { key: '4',      desc: 'Otevřít ROOT issues' },
    { key: 'F',      desc: 'Přejít na Live Tail (log tail)' },
    { key: 'F11',    desc: 'Fullscreen pro Live Tail' },
    { key: 'Alt+F',  desc: 'Focus na filter v issues modalu' },
    { key: 'Alt+A',  desc: 'Bulk Acknowledge vybraných issues' },
    { key: 'Alt+E',  desc: 'CSV Export vybraných issues' },
    { key: 'Ctrl+K', desc: 'Globální vyhledávání (issues, agenti, wiki)' },
];

function openShortcutsOverlay() {
    const existing = document.getElementById('shortcuts-overlay');
    if (existing) { existing.remove(); return; }
    const rows = _SHORTCUTS.map(s =>
        `<tr><td style="padding:6px 14px 6px 0;"><kbd style="background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);border-radius:4px;padding:2px 8px;font-family:monospace;font-size:.9em;">${s.key}</kbd></td><td style="padding:6px 0;color:var(--text-main);font-size:.88em;">${s.desc}</td></tr>`
    ).join('');
    const el = document.createElement('div');
    el.id = 'shortcuts-overlay';
    el.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:9999;background:var(--modal-bg,var(--panel));border:1px solid var(--border);border-radius:10px;padding:20px 24px;min-width:360px;box-shadow:0 8px 40px rgba(0,0,0,.5);';
    el.innerHTML = `<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
        <b style="color:var(--text-main);font-size:1em;">⌨ Klávesové zkratky</b>
        <span onclick="this.closest('#shortcuts-overlay').remove()" style="cursor:pointer;color:var(--text-muted);font-size:1.2em;">✕</span>
    </div>
    <table style="border-collapse:collapse;width:100%;">${rows}</table>
    <div style="margin-top:12px;font-size:.75em;color:var(--text-muted);text-align:center;">Stiskni <kbd style="background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);border-radius:3px;padding:1px 6px;">?</kbd> nebo <kbd style="background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);border-radius:3px;padding:1px 6px;">Esc</kbd> pro zavření</div>`;
    document.body.appendChild(el);
}

// 308: Přidat ARIA atributy všem modal overlayům při inicializaci
(function _addAriaToModals() {
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        const modal = overlay.querySelector('.modal');
        if (modal) {
            modal.setAttribute('role', 'dialog');
            modal.setAttribute('aria-modal', 'true');
            const header = modal.querySelector('.modal-header span, .modal-header h2, .modal-header');
            if (header) modal.setAttribute('aria-labelledby', header.id || (header.id = `mh_${Math.random().toString(36).slice(2,7)}`));
        }
    });
})();

document.addEventListener('keydown', (e) => {
    const tag = (document.activeElement?.tagName || '').toLowerCase();
    const inInput = tag === 'input' || tag === 'textarea' || tag === 'select' || document.activeElement?.isContentEditable;

    // 132: Alt+F → focus filter v issues modalu (funguje i v inputu)
    if (e.altKey && e.key === 'f') {
        const modal = document.getElementById('dedicated-issues-modal');
        if (modal && modal.style.display === 'flex') {
            e.preventDefault();
            const fi = document.getElementById('issues-filter-input');
            if (fi) { fi.focus(); fi.select(); }
        }
        return;
    }

    // 376: Ctrl+K → global search
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        _openGlobalSearch();
        return;
    }
    if (e.key === 'Escape') {
        const overlay = document.getElementById('shortcuts-overlay');
        if (overlay) { overlay.remove(); return; }
        const openModal = document.querySelector('.modal[style*="flex"], .modal[style*="block"]');
        if (openModal) openModal.style.display = 'none';
        return;
    }
    if (inInput) return;
    switch(e.key) {
        case '?': openShortcutsOverlay(); break;
        case 'r': if (typeof updateStatus === 'function') updateStatus(); break;
        case 's': if (typeof openSettings === 'function') openSettings(); break;
        case 'a': if (typeof openToolsModal === 'function') openToolsModal(); break;
        case 'n': document.getElementById('user-input')?.focus(); break;
        case '1': if (typeof openIssuesModal === 'function') openIssuesModal('infra'); break;
        case '2': if (typeof openIssuesModal === 'function') openIssuesModal('agent'); break;
        case '3': if (typeof openIssuesModal === 'function') openIssuesModal('security'); break;
        case '4': if (typeof openIssuesModal === 'function') openIssuesModal('root'); break;
        case 'F': document.querySelector('[onclick*="tail"]')?.click(); break;
        case 'F11': e.preventDefault(); _ltToggleFullscreen(); break;
    }
});

// ── 219: Internal wiki ────────────────────────────────────────────────────────
let _wikiCurrentSlug = null;
const _isAdmin = () => window.currentRole === 'admin' || window.currentRole === 'superadmin';

async function _wikiLoad() {
    const listEl = document.getElementById('wiki-list');
    const contentEl = document.getElementById('wiki-content');
    if (!listEl) return;
    listEl.innerHTML = '<div style="color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>';
    try {
        const r = await fetch('/api/wiki');
        const d = await r.json();
        const pages = d.pages || [];
        if (!pages.length) {
            listEl.innerHTML = `<div style="color:var(--text-muted);font-size:.83em;padding:8px 0;">Žádné stránky.<br>Vytvořte první kliknutím na + Nová stránka.</div>`;
            return;
        }
        listEl.innerHTML = pages.map(p =>
            `<div onclick="_wikiOpen('${_escape(p.slug)}')" style="padding:7px 8px;cursor:pointer;border-radius:4px;font-size:.85em;margin-bottom:2px;background:${_wikiCurrentSlug===p.slug?'rgba(77,166,255,.15)':'transparent'};border-left:2px solid ${_wikiCurrentSlug===p.slug?'var(--accent)':'transparent'};">
                <div style="font-weight:600;">${_escape(p.title)}</div>
                <div style="font-size:.72em;color:var(--text-muted);">${(p.updated_at||'').slice(0,10)} · ${_escape(p.updated_by||'')}</div>
             </div>`
        ).join('');
        if (!_wikiCurrentSlug && pages.length) _wikiOpen(pages[0].slug);
    } catch(e) { listEl.innerHTML = `<span style="color:var(--error);">Chyba: ${e}</span>`; }
}

async function _wikiOpen(slug) {
    _wikiCurrentSlug = slug;
    const contentEl = document.getElementById('wiki-content');
    if (!contentEl) return;
    contentEl.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>';
    const r = await fetch(`/api/wiki/${encodeURIComponent(slug)}`);
    const d = await r.json();
    if (d.error) { contentEl.innerHTML = `<span style="color:var(--error);">${d.error}</span>`; return; }
    const md = _renderMarkdown(d.content || '');
    const editBtn = _isAdmin()
        ? `<button onclick="_wikiEdit('${_escape(slug)}')" style="padding:3px 10px;background:transparent;border:1px solid var(--border);color:var(--text-muted);border-radius:4px;cursor:pointer;font-size:.78em;"><i class="fa-solid fa-pen"></i> Upravit</button>
           <button onclick="_wikiDelete('${_escape(slug)}')" style="padding:3px 8px;background:transparent;border:1px solid rgba(220,53,69,.4);color:#f87171;border-radius:4px;cursor:pointer;font-size:.78em;"><i class="fa-solid fa-trash"></i></button>`
        : '';
    contentEl.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;">
        <h2 style="margin:0;font-size:1.1em;">${_escape(d.title)}</h2>
        <div style="display:flex;gap:6px;">${editBtn}</div>
    </div>
    <div style="font-size:.83em;color:var(--text-muted);margin-bottom:12px;">${(d.updated_at||'').slice(0,16)} · ${_escape(d.updated_by||'')}</div>
    <div style="line-height:1.6;">${md}</div>`;
    _wikiLoad(); // refresh list to highlight current
}

function _wikiNewPage() {
    _wikiEditForm('', '', '');
}

function _wikiEdit(slug) {
    fetch(`/api/wiki/${encodeURIComponent(slug)}`).then(r=>r.json()).then(d => {
        _wikiEditForm(d.slug||'', d.title||'', d.content||'');
    });
}

function _wikiEditForm(slug, title, content) {
    const contentEl = document.getElementById('wiki-content');
    if (!contentEl) return;
    contentEl.innerHTML = `
        <div style="display:grid;gap:8px;">
            <input id="wiki-edit-title" value="${_escape(title)}" placeholder="Název stránky" style="padding:7px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:4px;font-size:.9em;">
            <input id="wiki-edit-slug" value="${_escape(slug)}" placeholder="slug (např. my-page)" style="padding:7px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:4px;font-size:.85em;font-family:monospace;" ${slug?'readonly':''}>
            <textarea id="wiki-edit-content" rows="14" placeholder="Obsah v Markdown…" style="padding:7px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:4px;font-size:.84em;resize:vertical;font-family:monospace;">${_escape(content)}</textarea>
            <div style="display:flex;gap:8px;">
                <button onclick="_wikiSave()" style="padding:6px 16px;background:var(--accent);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.85em;"><i class="fa-solid fa-floppy-disk"></i> Uložit</button>
                <button onclick="_wikiLoad()" style="padding:6px 14px;background:transparent;border:1px solid var(--border);color:var(--text-muted);border-radius:4px;cursor:pointer;font-size:.85em;">Zrušit</button>
                <span id="wiki-save-msg" style="font-size:.8em;align-self:center;"></span>
            </div>
        </div>`;
    // Auto-generate slug from title if new
    if (!slug) {
        document.getElementById('wiki-edit-title').addEventListener('input', e => {
            const slugEl = document.getElementById('wiki-edit-slug');
            if (slugEl && !slugEl.value) slugEl.value = e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
        });
    }
}

async function _wikiSave() {
    const title = document.getElementById('wiki-edit-title')?.value.trim();
    const slug = document.getElementById('wiki-edit-slug')?.value.trim();
    const content = document.getElementById('wiki-edit-content')?.value || '';
    const msg = document.getElementById('wiki-save-msg');
    if (!title || !slug) { if(msg){msg.style.color='var(--error)';msg.textContent='Vyplňte název a slug.';} return; }
    try {
        const r = await fetch('/api/wiki', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({title, slug, content})});
        const d = await r.json();
        if (d.status === 'ok') { _wikiCurrentSlug = slug; _wikiLoad(); _wikiOpen(slug); }
        else if (msg) { msg.style.color='var(--error)'; msg.textContent = d.error || 'Chyba'; }
    } catch(e) { if(msg){msg.style.color='var(--error)';msg.textContent=String(e);} }
}

async function _wikiDelete(slug) {
    if (!confirm(`Smazat wiki stránku "${slug}"?`)) return;
    await fetch(`/api/wiki/${encodeURIComponent(slug)}`, {method:'DELETE'});
    _wikiCurrentSlug = null;
    _wikiLoad();
    const contentEl = document.getElementById('wiki-content');
    if (contentEl) contentEl.innerHTML = '';
}

// M2-4: About modal — přesunuto z inline scriptu v index.html
function openAboutModal() {
    const modal = document.getElementById('about-modal');
    if (modal) { modal.style.display = 'flex'; }
    // Reset flag aby se log vždy přenačetl při otevření
    _jokeLogLoaded = false;
}
function closeAboutModal() {
    const modal = document.getElementById('about-modal');
    if (modal) modal.style.display = 'none';
}
function closeAboutModalOutside(event) {
    const modal = document.getElementById('about-modal');
    if (event.target === modal) modal.style.display = 'none';
}
let _jokeLogLoaded = false;
async function _loadJokeLog() {
    if (_jokeLogLoaded) return;
    _jokeLogLoaded = true;
    const body = document.getElementById('joke-log-body');
    if (!body) return;
    try {
        const r = await fetch('/api/analyze/infra_joke_log');
        const d = await r.json();
        const log = d.log || [];
        if (!log.length) {
            body.innerHTML = '<span style="color:var(--text-muted);font-style:italic;">Zatím žádné vtipy. Dvouklikni na logo.</span>';
            return;
        }
        body.innerHTML = log.map(e =>
            `<div style="background:rgba(255,255,255,.03);border:1px solid var(--border);border-radius:4px;padding:6px 10px;">
                <span style="color:var(--text-muted);font-size:.75em;margin-right:8px;">${e.ts}</span>
                <span style="font-style:italic;color:var(--text-main);">${e.joke}</span>
            </div>`
        ).join('');
    } catch(e) {
        body.innerHTML = '<span style="color:var(--error);">Chyba načítání.</span>';
    }
}

// 266: Export chatu do Markdown
function exportChatToMarkdown() {
    const msgs = document.querySelectorAll('#chat-history .message');
    if (!msgs.length) { alert('Chat je prázdný.'); return; }
    const lines = [`# Sentinel Chat Export\n_${new Date().toLocaleString('cs-CZ')}_\n`];
    msgs.forEach(m => {
        const isUser = m.classList.contains('user');
        const prefix = isUser ? '**Ty:** ' : '**Sentinel:** ';
        lines.push(prefix + m.innerText.trim());
    });
    const blob = new Blob([lines.join('\n\n')], {type: 'text/markdown'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `sentinel_chat_${new Date().toISOString().slice(0,10)}.md`;
    a.click();
}

// 267: Dashboard live clock
(function _initDashClock() {
    function _tick() {
        const el = document.getElementById('dash-live-clock');
        if (el) {
            const n = new Date();
            el.textContent = n.toLocaleTimeString('cs-CZ') + ' · ' + n.toLocaleDateString('cs-CZ');
        }
    }
    setInterval(_tick, 1000);
    document.addEventListener('DOMContentLoaded', _tick);
})();

// 280: Agent deployment helper — vygeneruje one-liner install příkaz
async function _showDeployHelper(hostname) {
    try {
        const r = await fetch('/api/agents/register', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({hostname})
        });
        const d = await r.json();
        if (d.status !== 'ok') { alert('Chyba registrace: ' + (d.message || '')); return; }
        const token = d.token;
        const host = window.location.hostname + ':' + (window.location.port || '80');
        const cmd = `curl -fsSL http://${host}/install-agent.sh | bash -s -- --token ${token} --host ${hostname}`;
        const box = document.createElement('div');
        box.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:20px;z-index:9999;max-width:600px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,.6);';
        box.innerHTML = `<div style="font-weight:700;margin-bottom:10px;"><i class="fa-solid fa-terminal" style="color:var(--accent);margin-right:6px;"></i>Deploy command pro <b>${_escape(hostname)}</b></div>
            <code style="display:block;background:#111;padding:10px;border-radius:4px;font-size:.82em;word-break:break-all;color:#50fa7b;">${_escape(cmd)}</code>
            <div style="display:flex;gap:8px;margin-top:12px;justify-content:flex-end;">
                <button onclick="navigator.clipboard.writeText('${cmd.replace(/'/g,"\\'")}').then(()=>alert('Zkopírováno!'))" style="padding:6px 14px;background:var(--accent);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.85em;"><i class="fa-solid fa-copy"></i> Kopírovat</button>
                <button onclick="this.closest('div').remove()" style="padding:6px 14px;background:transparent;border:1px solid var(--border);color:var(--text-muted);border-radius:4px;cursor:pointer;font-size:.85em;">Zavřít</button>
            </div>`;
        document.body.appendChild(box);
    } catch(e) { alert('Chyba: ' + e); }
}
