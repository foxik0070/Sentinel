// --- DEDICATED ISSUES MODAL MANAGER ---
let dedicatedIssuesInterval = null;
let currentOpenChannel = null;

async function openIssuesModal(channel) {
    currentOpenChannel = channel;
    const modal = document.getElementById('dedicated-issues-modal');
    const titleEl = document.getElementById('dedicated-modal-title');
    
    if (channel === 'root_audit') { 
        openRootAudit(); 
        if (window.innerWidth <= 768 && document.getElementById('tools-panel').style.left === '0px') { 
            toggleMobileMenu(); 
        } 
        return; 
    }

    modal.style.display = 'flex';
    if (channel === 'agent') titleEl.innerHTML = `<i class='fa-solid fa-server' style='color:var(--accent)'></i> ${t('issues_title_agent')}`;
    if (channel === 'root') titleEl.innerHTML = `<i class='fa-solid fa-user-secret' style='color:#ffc107'></i> ${t('issues_title_root')}`;
    if (channel === 'security') titleEl.innerHTML = `<i class='fa-solid fa-shield-halved' style='color:var(--error)'></i> ${t('issues_title_security')}`;
    if (channel === 'infra') titleEl.innerHTML = `<i class='fa-solid fa-file-lines' style='color:var(--accent)'></i> ${t('issues_title_infra')}`;

    // Sync notify bell button
    _syncChannelNotifyBtn(channel);

    // Load and refresh every 3 seconds
    refreshModalIssuesContent(false);
    if (dedicatedIssuesInterval) clearInterval(dedicatedIssuesInterval);
    dedicatedIssuesInterval = setInterval(() => refreshModalIssuesContent(true), 3000);
}

async function deleteAllInChannel() {
    if (!currentOpenChannel) return;
    if (!confirm(`Smazat všechny záznamy v kategorii '${currentOpenChannel}'?`)) return;
    try {
        const res = await fetch(`/api/issues/delete_all/${currentOpenChannel}`, {method: 'POST'});
        const d = await res.json();
        if (d.status === 'ok') {
            refreshModalIssuesContent(false);
        } else {
            alert(t('api_comm_error') + ' ' + (d.message || ''));
        }
    } catch(e) { alert(t('api_error')); }
}

function closeIssuesModal() {
    document.getElementById('dedicated-issues-modal').style.display = 'none';
    if (dedicatedIssuesInterval) clearInterval(dedicatedIssuesInterval);
    currentOpenChannel = null;
    if (_bulkMode) { _bulkMode = false; _bulkSelected.clear(); }
    _showSnoozed = false;
    const fi = document.getElementById('issues-filter-input');
    if (fi) fi.value = '';
    const bar = document.getElementById('bulk-action-bar');
    if (bar) bar.style.display = 'none';
    const sd = document.getElementById('snooze-dropdown');
    if (sd) sd.remove();
}

async function refreshModalIssuesContent(isAuto = false) {
    if (!currentOpenChannel) return;
    const bodyEl = document.getElementById('dedicated-modal-body');

    // Nepřepisovat pokud uživatel pracuje (focus v inputu, picker otevřen, drag aktivní)
    if (isAuto) {
        // Input nebo textarea v těle modalu má focus nebo neprázdný obsah
        const focusedInput = bodyEl && bodyEl.contains(document.activeElement) && ['INPUT','TEXTAREA'].includes(document.activeElement.tagName);
        const anyInputWithText = bodyEl && [...bodyEl.querySelectorAll('input[type="text"],input:not([type]),textarea')].some(el => el.value.trim().length > 0);
        // Otevřený picker (label color, tag) nebo dropdown
        const openPicker = bodyEl && bodyEl.querySelector('[id^="lc-picker-"][style*="flex"], [id^="snooze-dropdown"]');
        if (focusedInput || anyInputWithText || openPicker) return;
    }

    if (!isAuto) {
        bodyEl.innerHTML = `<div style='text-align:center; padding:30px; color:#666;'><i class='fa-solid fa-spinner fa-spin'></i> ${t('loading_db')}</div>`;
    }
    
    try {
        const snoozeParam = _showSnoozed ? '?snoozed=1' : '';
        const res = await fetch(`/api/modal_issues/${currentOpenChannel}${snoozeParam}`);
        const data = await res.json();
        // Update snooze button label with live count
        const snoozeBtn = document.getElementById('show-snoozed-btn');
        if (snoozeBtn && data.snoozed_count !== undefined) {
            snoozeBtn.title = _showSnoozed
                ? `Skrýt odložené`
                : `Zobraz odložené (${data.snoozed_count})`;
            snoozeBtn.style.display = (data.snoozed_count > 0 || _showSnoozed) ? '' : 'none';
        }
        if (data.html) {
            // Zapamatovat otevřené <details> skupiny před přepsáním HTML
            const openPlugins = new Set();
            bodyEl.querySelectorAll('details[open]').forEach(d => {
                const summary = d.querySelector('summary');
                if (summary) openPlugins.add(summary.textContent.trim().slice(0, 30));
            });
            bodyEl.innerHTML = data.html;
            // Obnovit open stav <details>
            if (openPlugins.size) {
                bodyEl.querySelectorAll('details').forEach(d => {
                    const summary = d.querySelector('summary');
                    if (summary && openPlugins.has(summary.textContent.trim().slice(0, 30))) {
                        d.open = true;
                    }
                });
            }
            // Re-apply filter if active
            const filterVal = document.getElementById('issues-filter-input')?.value || '';
            if (filterVal) filterIssueCards(filterVal);
            // Re-inject checkboxes if bulk mode is on
            if (_bulkMode) {
                _injectBulkCheckboxes();
                const cnt = document.getElementById('bulk-count');
                if (cnt) cnt.textContent = t('selected_count', {count: _bulkSelected.size});
            }
            // Update comment count badges
            loadCommentCounts();
            // 009: Collapsed/expanded cards — klik na hlavičku (ne na tlačítka) toggleuje stav
            bodyEl.querySelectorAll('[data-issue-card]').forEach(card => {
                card.addEventListener('click', (e) => {
                    if (e.target.closest('button,i,a,input,select,.issue-drag-handle')) return;
                    card.classList.toggle('collapsed');
                });
            });
            // 003: Drag & drop reorder via SortableJS
            if (typeof Sortable !== 'undefined') {
                _initIssueSortable(bodyEl);
            }
            // 223: Swipe gestures na mobilu
            _initSwipeGestures(bodyEl);
        }
    } catch (e) {
        if (!isAuto) {
            bodyEl.innerHTML = `<div style='color:var(--error); text-align:center; padding:20px;'>${t('api_sentinel_error')}</div>`;
        }
    }
}

let _issueSortables = [];

function _initIssueSortable(container) {
    // Destroy previous instances
    _issueSortables.forEach(s => s.destroy());
    _issueSortables = [];

    // Sort top-level flat cards directly in container
    const flatCards = [...container.children].filter(el => el.dataset.issueCard);
    if (flatCards.length > 1) {
        _issueSortables.push(Sortable.create(container, {
            handle: '.issue-drag-handle',
            animation: 150,
            filter: 'details',
            onEnd: _saveIssueOrder,
        }));
    }
    // Sort cards inside <details> groups
    container.querySelectorAll('details > div').forEach(groupDiv => {
        const cards = groupDiv.querySelectorAll('[data-issue-card]');
        if (cards.length > 1) {
            _issueSortables.push(Sortable.create(groupDiv, {
                handle: '.issue-drag-handle',
                animation: 150,
                onEnd: _saveIssueOrder,
            }));
        }
    });
}

async function _saveIssueOrder() {
    const bodyEl = document.getElementById('dedicated-modal-body');
    if (!bodyEl || !currentOpenChannel) return;
    const keys = [...bodyEl.querySelectorAll('[data-issue-key]')].map(el => el.dataset.issueKey);
    try {
        await fetch('/api/issues/reorder', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({channel: currentOpenChannel, order: keys})
        });
    } catch(e) { /* silent */ }
}

let pendingActionsInterval = null;

function openPendingActionsModal() {
    document.getElementById('pending-actions-modal').style.display = 'flex';
    loadPendingActions(false);
    if (pendingActionsInterval) clearInterval(pendingActionsInterval);
    pendingActionsInterval = setInterval(() => loadPendingActions(true), 5000);
}

function closePendingActionsModal() {
    document.getElementById('pending-actions-modal').style.display = 'none';
    if (pendingActionsInterval) clearInterval(pendingActionsInterval);
}

// ---- Browser Push Notifications ----
let _pushEnabled = localStorage.getItem('sentinel_push') === '1';
let _lastAlertCount = -1;

function _initPushBtn() {
    const btn = document.getElementById('notification-btn');
    if (!btn) return;
    if (!('Notification' in window)) { btn.style.display = 'none'; return; }
    _updatePushBtn();
}

function _updatePushBtn() {
    const btn = document.getElementById('notification-btn');
    if (!btn) return;
    if (_pushEnabled && Notification.permission === 'granted') {
        btn.className = 'fa-solid fa-bell icon-btn-header';
        btn.title = 'Notifikace zapnuty — klik pro vypnutí';
        btn.style.color = 'var(--accent)';
    } else {
        btn.className = 'fa-regular fa-bell-slash icon-btn-header';
        btn.title = 'Notifikace vypnuty — klik pro zapnutí';
        btn.style.color = '';
    }
}

async function toggleNotifications() {
    if (!('Notification' in window)) { alert('Váš prohlížeč nepodporuje push notifikace.'); return; }
    if (_pushEnabled) {
        _pushEnabled = false;
        localStorage.setItem('sentinel_push', '0');
        _updatePushBtn();
        return;
    }
    const perm = await Notification.requestPermission();
    if (perm === 'granted') {
        _pushEnabled = true;
        localStorage.setItem('sentinel_push', '1');
        new Notification('Sentinel Commander', {body: '🔔 Push notifikace zapnuty', icon: '/favicon.ico'});
    } else {
        alert('Přístup k notifikacím byl odmítnut.');
    }
    _updatePushBtn();
}

function _checkPushNotification(d) {
    if (!_pushEnabled || Notification.permission !== 'granted') return;
    const total = (d.issues||0) + (d.agent_issues||0) + (d.security_issues||0);
    if (_lastAlertCount !== -1 && total > _lastAlertCount) {
        const diff = total - _lastAlertCount;
        new Notification('Sentinel — Nový alert', {
            body: `+${diff} nové issue${diff > 1 ? 's' : ''} (celkem ${total})`,
            icon: '/favicon.ico',
            tag: 'sentinel-alert',
            renotify: true
        });
    }
    _lastAlertCount = total;
}

if (document.readyState !== 'loading') _initPushBtn();
else document.addEventListener('DOMContentLoaded', _initPushBtn);

// ---- Issue Re-analyze ----
async function _reanalyzeIssue(kb64) {
    const body = document.getElementById('dedicated-modal-body');
    const existingPanel = document.getElementById('reanalyze-panel');
    if (existingPanel) existingPanel.remove();
    const panel = document.createElement('div');
    panel.id = 'reanalyze-panel';
    panel.style.cssText = 'background:rgba(0,120,212,.07);border:1px solid rgba(0,120,212,.3);border-radius:6px;padding:12px;margin-bottom:10px;font-size:.85em;';
    panel.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> AI re-analyzuje…';
    if (body) body.insertAdjacentElement('afterbegin', panel);
    try {
        const r = await fetch(`/api/issues/${encodeURIComponent(kb64)}/reanalyze`, {method:'POST'});
        const d = await r.json();
        panel.innerHTML = d.reply
            ? `<div style="margin-bottom:6px;font-size:.72em;text-transform:uppercase;color:rgba(0,120,212,.8);"><i class="fa-solid fa-rotate-right"></i> RE-ANALÝZA — ${_escape(d.host||'')} [${_escape(d.plugin||'')}]</div>${d.reply}`
            : `<span style="color:var(--error);">Chyba: ${d.error||'?'}</span>`;
    } catch(e) { panel.innerHTML = `<span style="color:var(--error);">Síťová chyba: ${e}</span>`; }
}

// ---- Config History ----
async function openConfigHistory() {
    const modal = document.getElementById('config-history-modal');
    if (!modal) return;
    modal.style.display = 'flex';
    const list = document.getElementById('config-hist-list');
    const content = document.getElementById('config-hist-content');
    list.innerHTML = '<div style="color:var(--text-muted);font-size:.82em;padding:4px;">Načítám…</div>';
    content.textContent = '';
    try {
        const r = await fetch('/api/config/history');
        const d = await r.json();
        const hist = d.history || [];
        if (!hist.length) {
            list.innerHTML = '<div style="color:var(--text-muted);font-size:.82em;padding:4px;">Žádné snapshoty.<br><small>Upravte config.yaml pro vytvoření prvního.</small></div>';
            return;
        }
        list.innerHTML = hist.map((h, i) => `<div onclick="_loadConfigSnapshot(${h.id})" style="padding:8px;cursor:pointer;border-bottom:1px solid var(--border);font-size:.8em;${i===0?'background:rgba(0,120,212,.1);':''}">
            <div style="color:var(--text-muted);font-size:.75em;">${(h.timestamp||'').slice(0,16).replace('T',' ')}</div>
            <div style="font-family:monospace;font-size:.78em;color:var(--accent);">${h.hash.slice(0,8)}</div>
        </div>`).join('');
        // Načíst první automaticky
        _loadConfigSnapshot(hist[0].id);
    } catch(e) { list.innerHTML = `<div style="color:var(--error);font-size:.82em;">Chyba: ${e}</div>`; }
}

async function _loadConfigSnapshot(id) {
    const content = document.getElementById('config-hist-content');
    content.textContent = 'Načítám…';
    try {
        const r = await fetch(`/api/config/history/${id}`);
        const d = await r.json();
        content.textContent = d.content || d.error || '?';
    } catch(e) { content.textContent = `Chyba: ${e}`; }
}

// ---- Favicon Badge ----
let _faviconCanvas = null, _faviconCtx = null, _faviconImg = null, _faviconEl = null;
function _initFavicon() {
    _faviconEl = document.querySelector("link[rel*='icon']") || document.createElement('link');
    _faviconEl.type = 'image/png'; _faviconEl.rel = 'icon';
    document.head.appendChild(_faviconEl);
    _faviconCanvas = document.createElement('canvas');
    _faviconCanvas.width = 32; _faviconCanvas.height = 32;
    _faviconCtx = _faviconCanvas.getContext('2d');
    _faviconImg = new Image();
    _faviconImg.src = _faviconEl.href || '/favicon.ico';
}
function _updateFaviconBadge(count) {
    if (!_faviconCtx) _initFavicon();
    const ctx = _faviconCtx;
    ctx.clearRect(0, 0, 32, 32);
    // Pozadí
    ctx.fillStyle = '#1a1a2e';
    ctx.beginPath(); ctx.roundRect(0,0,32,32,6); ctx.fill();
    // Shield tvar (fa-shield-halved)
    ctx.beginPath();
    ctx.moveTo(16,2); ctx.lineTo(4,7); ctx.lineTo(4,16);
    ctx.bezierCurveTo(4,23,9,28,16,30);
    ctx.bezierCurveTo(23,28,28,23,28,16);
    ctx.lineTo(28,7); ctx.closePath();
    ctx.fillStyle = count > 0 ? 'rgba(220,53,69,0.3)' : 'rgba(0,120,212,0.25)';
    ctx.fill();
    // Pravá polovina (plnější)
    ctx.beginPath();
    ctx.moveTo(16,2); ctx.lineTo(28,7); ctx.lineTo(28,16);
    ctx.bezierCurveTo(28,23,23,28,16,30); ctx.closePath();
    ctx.fillStyle = count > 0 ? 'rgba(220,53,69,0.7)' : 'rgba(0,120,212,0.7)';
    ctx.fill();
    // Obrys
    ctx.beginPath();
    ctx.moveTo(16,2); ctx.lineTo(4,7); ctx.lineTo(4,16);
    ctx.bezierCurveTo(4,23,9,28,16,30);
    ctx.bezierCurveTo(23,28,28,23,28,16);
    ctx.lineTo(28,7); ctx.closePath();
    ctx.strokeStyle = count > 0 ? '#dc3545' : '#0078d4';
    ctx.lineWidth = 1.5; ctx.stroke();
    if (count > 0) {
        const label = count > 99 ? '99+' : String(count);
        const r = label.length > 1 ? 9 : 7;
        _faviconCtx.fillStyle = '#dc3545';
        _faviconCtx.beginPath();
        _faviconCtx.arc(26, 6, r, 0, 2*Math.PI);
        _faviconCtx.fill();
        _faviconCtx.fillStyle = '#fff';
        _faviconCtx.font = `bold ${label.length > 1 ? 8 : 10}px sans-serif`;
        _faviconCtx.fillText(label, 26, 6);
    }
    try { _faviconEl.href = _faviconCanvas.toDataURL('image/png'); } catch {}
    // Title bar
    document.title = count > 0 ? `(${count}) Sentinel Commander` : 'Sentinel Commander';
}

// ---- Sparklines v topbar ----
let _sparklineData = {}; // metric → [values]
const _SPARKLINE_HOURS = 12;

async function _loadSparklineData() {
    try {
        const r = await fetch('/api/health/history?days=1');
        const d = await r.json();
        const hist = d.history || [];
        if (!hist.length) return;
        // Připravit data pro issues a score
        _sparklineData.issues = hist.slice(-_SPARKLINE_HOURS).map(h => h.issues);
        _sparklineData.score = hist.slice(-_SPARKLINE_HOURS).map(h => h.score);
        _drawSparklines();
    } catch {}
}

function _drawSparkline(canvasId, values, color) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !values || !values.length) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    const max = Math.max(...values, 1);
    const min = Math.min(...values, 0);
    const range = max - min || 1;
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    values.forEach((v, i) => {
        const x = (i / (values.length - 1)) * w;
        const y = h - ((v - min) / range) * (h - 2) - 1;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();
}

function _drawSparklines() {
    if (_sparklineData.issues) _drawSparkline('sparkline-issues', _sparklineData.issues, '#dc3545');
    if (_sparklineData.score) _drawSparkline('sparkline-score', _sparklineData.score, '#4caf50');
}

// ---- RAG Reindex ----
async function reindexRag() {
    const btn = document.getElementById('rag-reindex-btn');
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Indexuji…'; }
    try {
        const r = await fetch('/api/rag/reindex', {method:'POST'});
        const d = await r.json();
        if (d.status === 'ok') {
            // Polling statusu
            const poll = setInterval(async () => {
                const sr = await fetch('/api/rag/status');
                const sd = await sr.json();
                if (btn) btn.innerHTML = `<i class="fa-solid fa-brain"></i> ${sd.status}`;
                if (sd.ready) {
                    clearInterval(poll);
                    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-brain"></i> Re-index KB'; }
                    alert('✓ RAG re-indexace dokončena');
                }
            }, 2000);
        } else {
            alert('Chyba: ' + (d.error || '?'));
        }
    } catch(e) { alert('Chyba: ' + e); }
    finally { if (btn && btn.innerHTML.includes('Indexuji')) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-brain"></i> Re-index KB'; } }
}

// ---- Session Management ----
async function openSessionsModal() {
    const modal = document.getElementById('sessions-modal');
    if (!modal) return;
    modal.style.display = 'flex';
    await _loadSessions();
}
function closeSessionsModal() { document.getElementById('sessions-modal').style.display = 'none'; }
async function _loadSessions() {
    const body = document.getElementById('sessions-body');
    body.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>';
    try {
        const r = await fetch('/api/sessions');
        const d = await r.json();
        const sessions = d.sessions || [];
        if (!sessions.length) { body.innerHTML = '<div style="color:var(--text-muted);text-align:center;padding:20px;">Žádné aktivní sessions.</div>'; return; }
        body.innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:.85em;">
            <thead><tr style="border-bottom:2px solid var(--border);color:var(--text-muted);">
                <th style="padding:6px 8px;text-align:left;">Uživatel</th><th style="padding:6px 8px;">Role</th>
                <th style="padding:6px 8px;">IP</th><th style="padding:6px 8px;">Naposledy</th>
                <th style="padding:6px 8px;">Vytvořena</th><th style="padding:6px 8px;"></th>
            </tr></thead><tbody>` +
            sessions.map(s => `<tr style="border-bottom:1px solid var(--border);${s.is_current?'background:rgba(0,120,212,.08);':''}">
                <td style="padding:6px 8px;font-weight:${s.is_current?700:400};">${_escape(s.username)}${s.is_current?' <span style="color:var(--accent);font-size:.75em;">(tato)</span>':''}</td>
                <td style="padding:6px 8px;text-align:center;"><span style="background:rgba(0,120,212,.15);color:#a3cfff;border-radius:8px;padding:1px 7px;">${s.role}</span></td>
                <td style="padding:6px 8px;font-family:monospace;color:var(--text-muted);">${_escape(s.ip||'?')}</td>
                <td style="padding:6px 8px;color:var(--text-muted);">${(s.last_seen||'').slice(0,16).replace('T',' ')}</td>
                <td style="padding:6px 8px;color:var(--text-muted);">${(s.created_at||'').slice(0,16).replace('T',' ')}</td>
                <td style="padding:6px 8px;">${!s.is_current?`<button onclick="_revokeSession(${s.id})" style="padding:3px 8px;background:rgba(197,15,31,.15);border:1px solid rgba(197,15,31,.4);color:#c50f1f;border-radius:4px;cursor:pointer;font-size:.8em;">Revoke</button>`:'—'}</td>
            </tr>`).join('') + '</tbody></table>';
    } catch(e) { body.innerHTML = `<div style="color:var(--error);">Chyba: ${e}</div>`; }
}
async function _revokeSession(id) {
    if (!confirm('Odhlásit tuto session?')) return;
    const r = await fetch(`/api/sessions/${id}`, {method:'DELETE'});
    const d = await r.json();
    if (d.status === 'ok') await _loadSessions();
    else alert('Chyba: ' + (d.message||'?'));
}

// ---- Bulk Acknowledge ----
async function bulkAcknowledge() {
    const keys = [..._bulkSelected];
    if (!keys.length) { alert('Nevybráno žádné issue.'); return; }
    if (!confirm(`Potvrdit ${keys.length} issues?`)) return;
    const r = await fetch('/api/issues/bulk_acknowledge', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({keys})});
    const d = await r.json();
    _bulkSelected.clear();
    refreshModalIssuesContent(false);
    if (d.acknowledged !== undefined) alert(`✓ Potvrzeno ${d.acknowledged} issues`);
}

// 265: Bulk CSV export vybraných issues
async function bulkExportCsv() {
    const keys = [..._bulkSelected];
    if (!keys.length) { alert('Nejprve vyber issues.'); return; }
    try {
        const r = await fetch('/api/issues/export_csv', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({keys, channel: currentOpenChannel})
        });
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = `sentinel_issues_${new Date().toISOString().slice(0,10)}.csv`;
        a.click(); URL.revokeObjectURL(url);
    } catch(e) { alert('Export selhal: ' + e); }
}

// 268: Alt+A → bulk acknowledge, Alt+E → CSV export
document.addEventListener('keydown', e => {
    if (e.altKey && e.key === 'a' && currentOpenChannel) { e.preventDefault(); bulkAcknowledge(); }
    if (e.altKey && e.key === 'e' && currentOpenChannel) { e.preventDefault(); bulkExportCsv(); }
});

// ---- Issue Assignee ----
async function _openAssignPicker(kb64) {
    document.querySelectorAll('.assign-picker').forEach(el => el.remove());
    let users = [];
    try { const r = await fetch('/api/users/list'); const d = await r.json(); users = d.users || []; } catch {}
    const menu = document.createElement('div');
    menu.className = 'assign-picker';
    menu.style.cssText = 'position:fixed;z-index:9999;background:var(--panel);border:1px solid var(--border);border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,.4);padding:4px 0;min-width:160px;';
    const opts = [{username: '', role: '— Odebrat přiřazení'}].concat(users);
    opts.forEach(u => {
        const item = document.createElement('div');
        item.innerHTML = `<b style="font-size:.85em;">${_escape(u.username||'Odebrat')}</b>${u.role&&u.username?` <span style="font-size:.72em;color:var(--text-muted);">${u.role}</span>`:''}`;
        item.style.cssText = 'padding:7px 14px;cursor:pointer;';
        item.onmouseenter = () => item.style.background = 'rgba(255,255,255,.07)';
        item.onmouseleave = () => item.style.background = '';
        item.onclick = async () => {
            menu.remove();
            await fetch(`/api/issues/${encodeURIComponent(kb64)}/assign`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username: u.username||null})});
            refreshModalIssuesContent && refreshModalIssuesContent(false);
        };
        menu.appendChild(item);
    });
    document.body.appendChild(menu);
    const trigger = document.activeElement;
    if (trigger) { const r = trigger.getBoundingClientRect(); menu.style.left=r.left+'px'; menu.style.top=(r.bottom+4)+'px'; }
    setTimeout(() => document.addEventListener('click', () => menu.remove(), {once:true}), 50);
}

// ---- AI Trend Report ----
async function openAiTrendReport() {
    const modal = document.getElementById('changelog-modal'); // Reuse changelog modal
    if (!modal) return;
    document.querySelector('#changelog-modal .modal-header span').innerHTML = '<i class="fa-solid fa-chart-line" style="color:var(--accent);"></i> AI Trend report';
    modal.style.display = 'flex';
    const body = document.getElementById('changelog-body');
    body.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i><div style="margin-top:8px;">AI analyzuje trendy…</div></div>';
    try {
        const r = await fetch('/api/analyze/trend_report', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({days:7})});
        const d = await r.json();
        body.innerHTML = d.reply || `<div style="color:var(--error);">${d.error||'Chyba'}</div>`;
    } catch(e) { body.innerHTML = `<div style="color:var(--error);">Síťová chyba: ${e}</div>`; }
}

// ---- Triage View ----
async function openTriageView() {
    const body = document.getElementById('dedicated-modal-body');
    if (!body) return;
    body.insertAdjacentHTML('afterbegin', '<div id="triage-panel" style="background:rgba(253,126,20,.06);border:1px solid rgba(253,126,20,.3);border-radius:6px;padding:12px;margin-bottom:10px;"><i class="fa-solid fa-spinner fa-spin"></i> Načítám triage…</div>');
    try {
        const r = await fetch('/api/issues/triage');
        const d = await r.json();
        const issues = d.issues || [];
        const el = document.getElementById('triage-panel');
        if (!el) return;
        const sevColors = {critical:'#ff4500', high:'#fd7e14', medium:'#ffc107', low:'#6c757d'};
        el.innerHTML = `<div style="font-size:.72em;text-transform:uppercase;color:rgba(253,126,20,.8);margin-bottom:10px;letter-spacing:.07em;"><i class="fa-solid fa-fire"></i> TRIAGE — ${issues.length} issues seřazených dle urgence</div>` +
            issues.slice(0, 20).map((iss, idx) => {
                const sc = sevColors[iss.severity] || 'var(--accent)';
                const score = iss.urgency_score || 0;
                return `<div style="display:flex;align-items:center;gap:10px;padding:5px 8px;margin-bottom:3px;background:var(--panel);border-radius:4px;border-left:3px solid ${sc};font-size:.82em;">
                    <span style="min-width:20px;text-align:right;font-weight:700;color:${score>6?'var(--error)':score>3?'#fd7e14':'var(--text-muted)'};">${score}</span>
                    <span style="min-width:60px;color:var(--text-muted);font-size:.75em;">${_escape((iss.channel_type||'?').toUpperCase())}</span>
                    <b style="min-width:80px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_escape(iss.host||'?')}</b>
                    <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-muted);">${_escape((iss.last_line||'').slice(0,80))}</span>
                </div>`;
            }).join('');
    } catch(e) {
        const el = document.getElementById('triage-panel');
        if (el) el.innerHTML = `<span style="color:var(--error);">Chyba: ${e}</span>`;
    }
}

// ---- Issue Acknowledge ----
async function _ackIssue(kb64) {
    await fetch(`/api/issues/${encodeURIComponent(kb64)}/acknowledge`, {method:'POST'});
    refreshModalIssuesContent && refreshModalIssuesContent(false);
}
async function _unackIssue(kb64) {
    await fetch(`/api/issues/${encodeURIComponent(kb64)}/unacknowledge`, {method:'POST'});
    refreshModalIssuesContent && refreshModalIssuesContent(false);
}

// ---- Issue Timeline ----
async function openIssueTimeline(kb64) {
    document.getElementById('comments-modal').style.display = 'flex';
    _commentsKey = kb64;
    if (currentOpenChannel) _pushBreadcrumb('comments-modal', 'Issues', () => openIssuesModal(currentOpenChannel));
    try {
        const raw = atob(kb64);
        document.getElementById('comments-issue-key').textContent = raw;
    } catch {}
    const thread = document.getElementById('comments-thread');
    thread.innerHTML = `<div style="text-align:center;padding:16px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>`;
    try {
        const r = await fetch(`/api/issues/${encodeURIComponent(kb64)}/timeline`);
        const d = await r.json();
        const events = d.timeline || [];
        if (!events.length) { thread.innerHTML = `<div style="text-align:center;padding:20px;color:var(--text-muted);">Žádné události.</div>`; return; }
        const icons = {comment:'fa-comment', auto_remediation:'fa-robot', action:'fa-bolt', acknowledged:'fa-check-double', tag:'fa-tag'};
        const colors = {comment:'var(--accent)', auto_remediation:'#a855f7', action:'#0078d4', acknowledged:'#f0ad4e', tag:'#6c757d'};
        thread.innerHTML = `<div style="position:relative;padding-left:20px;border-left:2px solid var(--border);margin-left:8px;">` +
            events.map(ev => {
                const ic = icons[ev.type] || 'fa-circle';
                const cl = colors[ev.type] || 'var(--text-muted)';
                const ts = (ev.at||'').slice(0,16).replace('T',' ');
                return `<div style="margin-bottom:14px;position:relative;">
                    <div style="position:absolute;left:-26px;top:2px;width:12px;height:12px;border-radius:50%;background:${cl};border:2px solid var(--bg);"></div>
                    <div style="font-size:.75em;color:var(--text-muted);">${ts} · <b>${_escape(ev.actor||'?')}</b></div>
                    <div style="font-size:.85em;margin-top:2px;"><i class="fa-solid ${ic}" style="color:${cl};margin-right:5px;"></i>${_escape(ev.detail||'')}</div>
                </div>`;
            }).join('') + `</div>`;
    } catch { thread.innerHTML = `<div style="color:var(--error);padding:12px;">Chyba načítání.</div>`; }
}

// ---- Dashboard Widget Layout ----
const _SYS_SECTION_CATS = ['Hardware', 'Network', 'Security & Agents', 'AI Engine', 'Database & Runtime', 'Detektory'];
const _DASH_LS_KEY = 'sentinel_dash_hidden';

function _dashGetHidden() {
    try { return JSON.parse(localStorage.getItem(_DASH_LS_KEY) || '[]'); } catch { return []; }
}
function _dashSetHidden(list) {
    localStorage.setItem(_DASH_LS_KEY, JSON.stringify(list));
}
function _dashApply() {
    const hidden = _dashGetHidden();
    document.querySelectorAll('.sys-section').forEach(sec => {
        const title = sec.querySelector('.sys-section-title')?.textContent?.trim() || '';
        const match = _SYS_SECTION_CATS.find(w => title.includes(w));
        if (match) sec.style.display = hidden.includes(match) ? 'none' : '';
    });
}
function _dashToggle(widget) {
    const hidden = _dashGetHidden();
    const idx = hidden.indexOf(widget);
    if (idx >= 0) hidden.splice(idx, 1); else hidden.push(widget);
    _dashSetHidden(hidden);
    _dashApply();
}
function openDashLayout() {
    const hidden = _dashGetHidden();
    let menu = document.getElementById('dash-layout-menu');
    if (menu) { menu.remove(); return; }
    menu = document.createElement('div');
    menu.id = 'dash-layout-menu';
    menu.style.cssText = 'position:fixed;z-index:9999;background:var(--panel);border:1px solid var(--border);border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.4);padding:8px 0;min-width:200px;top:50%;left:50%;transform:translate(-50%,-50%);';
    menu.innerHTML = `<div style="padding:6px 14px 10px;font-size:.78em;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);border-bottom:1px solid var(--border);margin-bottom:4px;">Viditelné sekce sys monitoru</div>` +
        _SYS_SECTION_CATS.map(w => `<div onclick="_dashToggle('${w}')" style="padding:7px 14px;cursor:pointer;display:flex;align-items:center;gap:8px;font-size:.85em;"
            onmouseenter="this.style.background='rgba(255,255,255,.06)'" onmouseleave="this.style.background=''">
            <i class="fa-solid fa-${hidden.includes(w)?'eye-slash':'eye'}" style="color:${hidden.includes(w)?'var(--text-muted)':'var(--success)'};min-width:14px;"></i>
            ${w}
        </div>`).join('') +
        `<div style="border-top:1px solid var(--border);margin-top:4px;padding:6px 14px;"><button onclick="document.getElementById('dash-layout-menu').remove()" style="width:100%;padding:4px;background:transparent;border:1px solid var(--border);border-radius:4px;cursor:pointer;font-size:.82em;">Zavřít</button></div>`;
    document.body.appendChild(menu);
    setTimeout(() => document.addEventListener('click', e => { if (!menu.contains(e.target)) menu.remove(); }, {once:true}), 100);
}
// Auto-apply on sys monitor load (defer-safe)
(function() {
    function _initSysMonObs() {
        const obs = new MutationObserver(() => _dashApply());
        const target = document.getElementById('sys-monitor-content');
        if (target) obs.observe(target, {childList:true, subtree:true});
    }
    if (document.readyState !== 'loading') _initSysMonObs();
    else document.addEventListener('DOMContentLoaded', _initSysMonObs);
})();

// ---- Health History ----
let _healthChart = null;
async function openHealthHistory() {
    document.getElementById('health-history-modal').style.display = 'flex';
    await loadHealthHistory(7);
}
async function loadHealthHistory(days) {
    try {
        const r = await fetch(`/api/health/history?days=${days}`);
        const d = await r.json();
        const hist = d.history || [];
        const labels = hist.map(h => h.ts.slice(5,16).replace('T',' '));
        const scores = hist.map(h => h.score);
        const issues = hist.map(h => h.issues);
        if (_healthChart) { _healthChart.destroy(); _healthChart = null; }
        const ctx = document.getElementById('health-chart');
        if (!ctx || !window.Chart) return;
        _healthChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    {label: 'Health Score', data: scores, borderColor: 'var(--success)', borderWidth: 2, pointRadius: 0, fill: false, yAxisID: 'y'},
                    {label: 'Issues', data: issues, borderColor: 'var(--error)', borderWidth: 1.5, pointRadius: 0, fill: true, backgroundColor: 'rgba(220,53,69,.08)', yAxisID: 'y2'}
                ]
            },
            options: {
                animation: false, responsive: true,
                plugins: {legend: {display: true, labels: {font: {size: 11}}}},
                scales: {
                    x: {ticks: {maxTicksLimit: 10, font: {size: 9}}},
                    y: {min: 0, max: 100, position: 'left', title: {display: true, text: 'Score', font: {size: 9}}},
                    y2: {min: 0, position: 'right', grid: {drawOnChartArea: false}, title: {display: true, text: 'Issues', font: {size: 9}}}
                }
            }
        });
        if (hist.length) {
            const avg = Math.round(scores.reduce((a,b)=>a+b,0)/scores.length);
            const min = Math.min(...scores), max = Math.max(...scores);
            document.getElementById('health-stats').innerHTML =
                `<span>Průměr: <b>${avg}</b></span><span>Min: <b style="color:var(--error);">${min}</b></span><span>Max: <b style="color:var(--success);">${max}</b></span><span>Vzorků: <b>${hist.length}</b></span>`;
        }
    } catch(e) { console.error('health history', e); }
}

// ---- SSH Execute Modal ----
function openSshModal(host) {
    const modal = document.getElementById('ssh-modal');
    if (!modal) return;
    document.getElementById('ssh-modal-host').textContent = host || '';
    document.getElementById('ssh-host-input').value = host || '';
    document.getElementById('ssh-cmd-input').value = '';
    document.getElementById('ssh-output').style.display = 'none';
    document.getElementById('ssh-output').textContent = '';
    modal.style.display = 'flex';
    setTimeout(() => document.getElementById('ssh-cmd-input').focus(), 100);
    // Načti allowed commands
    _sshLoadAllowedCmds();
}

async function _sshLoadAllowedCmds() {
    const el = document.getElementById('ssh-allowed-cmds');
    if (!el) return;
    try {
        const r = await fetch('/api/v1/allowed-commands');
        const d = await r.json();
        const rules = d.rules || [];
        if (!rules.length) {
            el.innerHTML = '<span style="color:var(--text-muted);">Žádné allowed commands — přidejte přes Settings → Allowed Commands.</span>';
            return;
        }
        el.innerHTML = '<span style="color:var(--text-muted);display:block;margin-bottom:4px;">Povolené příkazy (kliknutím vložit):</span>' +
            rules.map(r => `<span onclick="document.getElementById('ssh-cmd-input').value='${r.pattern.replace(/'/g,"\\'")}';"
                style="display:inline-block;background:rgba(0,120,212,.15);color:var(--accent);border:1px solid rgba(0,120,212,.3);border-radius:4px;
                       padding:2px 8px;margin:2px;cursor:pointer;font-family:monospace;font-size:.8em;"
                title="${r.description || r.pattern}">${_escape(r.pattern)}</span>`
            ).join('');
    } catch(e) {
        el.innerHTML = '<span style="color:var(--text-muted);">Chyba načtení allowlistu.</span>';
    }
}
function closeSshModal() { document.getElementById('ssh-modal').style.display = 'none'; }
async function runSshModal() {
    const host = document.getElementById('ssh-host-input').value.trim();
    const cmd = document.getElementById('ssh-cmd-input').value.trim();
    const out = document.getElementById('ssh-output');
    const btn = document.getElementById('ssh-run-btn');
    if (!host || !cmd) { out.style.display='block'; out.textContent='Zadejte host a příkaz.'; return; }
    btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
    out.style.display = 'block';
    out.textContent = `▶ ${host}: ${cmd}\n${'─'.repeat(40)}\n`;
    // SSE streaming (046) — výstup přichází průběžně
    try {
        const resp = await fetch('/api/ssh/stream', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({host, command: cmd})
        });
        if (!resp.ok) {
            const d = await resp.json().catch(() => ({}));
            out.textContent += `✗ CHYBA: ${d.error || resp.status}`;
            return;
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        while (true) {
            const {done, value} = await reader.read();
            if (done) break;
            buf += decoder.decode(value, {stream: true});
            const lines = buf.split('\n');
            buf = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data:')) continue;
                try {
                    const ev = JSON.parse(line.slice(5).trim());
                    if (ev.line !== undefined) out.textContent += ev.line + '\n';
                    if (ev.done) {
                        out.textContent += ev.rc === 0 ? '─'.repeat(40) + '\n✓ Exit 0\n'
                                                       : '─'.repeat(40) + `\n✗ Exit ${ev.rc}\n`;
                    }
                    out.scrollTop = out.scrollHeight;
                } catch(_) {}
            }
        }
    } catch(e) { out.textContent += `Síťová chyba: ${e}`; }
    finally { btn.disabled=false; btn.innerHTML='<i class="fa-solid fa-play"></i> Spustit'; }
}

// ---- Topology Map ----
async function openTopology() {
    const modal = document.getElementById('topology-modal');
    const body = document.getElementById('topology-body');
    modal.style.display = 'flex';
    body.innerHTML = '<div style="text-align:center;padding:30px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i></div>';
    try {
        const r = await fetch('/api/agents/health');
        const d = await r.json();
        const agents = d.agents || [];
        // Group by agent_group
        const groups = {};
        agents.forEach(a => { const g = a.agent_group || '(bez skupiny)'; if (!groups[g]) groups[g] = []; groups[g].push(a); });
        const statusColor = a => {
            if (a.maintenance_until && new Date(a.maintenance_until) > new Date()) return '#fa8231';
            return a.status === 'ONLINE' ? 'var(--success)' : 'var(--error)';
        };
        body.innerHTML = Object.entries(groups).map(([grp, ags]) => {
            const cards = ags.map(a => {
                const sc = statusColor(a);
                const lag = a.last_data_lag_ms != null ? `<div style="font-size:.65em;color:var(--text-muted);">${Math.round(a.last_data_lag_ms/1000)}s lag</div>` : '';
                return `<div onclick="document.getElementById('topology-modal').style.display='none'; openAgentDetailModal('${_escape(a.hostname)}')"
                    style="cursor:pointer;padding:10px 12px;background:var(--panel);border:1px solid var(--border);border-left:3px solid ${sc};border-radius:6px;min-width:140px;transition:transform .15s;"
                    onmouseenter="this.style.transform='translateY(-2px)'" onmouseleave="this.style.transform=''">
                    <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
                        <div style="width:8px;height:8px;border-radius:50%;background:${sc};${a.status==='ONLINE'?'box-shadow:0 0 5px '+sc:''}"></div>
                        <b style="font-size:.85em;">${_escape(a.hostname)}</b>
                    </div>
                    <div style="font-size:.7em;color:var(--text-muted);">${a.alerts_24h > 0 ? '<span style="color:var(--error);">⚠ '+a.alerts_24h+' alertů (24h)</span>' : '✓ OK'}</div>
                    ${lag}
                    ${a.agent_version ? `<div style="font-size:.62em;color:var(--text-muted);font-family:monospace;">${_escape(a.agent_version.slice(0,8))}</div>` : ''}
                </div>`;
            }).join('');
            return `<div style="margin-bottom:20px;">
                <div style="font-size:.75em;text-transform:uppercase;letter-spacing:.07em;color:var(--accent);margin-bottom:10px;display:flex;align-items:center;gap:8px;">
                    <i class="fa-solid fa-layer-group"></i> ${_escape(grp)} <span style="color:var(--text-muted);font-weight:400;">(${ags.length})</span>
                </div>
                <div style="display:flex;flex-wrap:wrap;gap:10px;">${cards}</div>
            </div>`;
        }).join('');
    } catch(e) { body.innerHTML = `<div style="color:var(--error);">Chyba: ${e}</div>`; }
}

// ---- Changelog ----
async function openChangelog() {
    const modal = document.getElementById('changelog-modal');
    const body = document.getElementById('changelog-body');
    modal.style.display = 'flex';
    body.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>';
    try {
        const r = await fetch('/api/changelog?limit=40');
        const d = await r.json();
        const commits = d.commits || [];
        if (!commits.length) { body.innerHTML = '<div style="color:var(--text-muted);padding:20px;text-align:center;">Žádná git history.</div>'; return; }
        const typeIcon = s => {
            if (s.startsWith('feat')) return {ic:'fa-star', cl:'#a855f7'};
            if (s.startsWith('fix')) return {ic:'fa-bug', cl:'var(--error)'};
            if (s.startsWith('chore')) return {ic:'fa-wrench', cl:'var(--text-muted)'};
            if (s.startsWith('docs')) return {ic:'fa-book', cl:'#0078d4'};
            return {ic:'fa-circle', cl:'var(--text-muted)'};
        };
        body.innerHTML = commits.map(c => {
            const {ic, cl} = typeIcon(c.subject);
            return `<div style="display:flex;gap:10px;padding:8px 4px;border-bottom:1px solid var(--border);align-items:flex-start;">
                <i class="fa-solid ${ic}" style="color:${cl};margin-top:3px;min-width:14px;"></i>
                <div style="flex:1;min-width:0;">
                    <div style="font-size:.88em;">${_escape(c.subject)}</div>
                    <div style="font-size:.72em;color:var(--text-muted);">${_escape(c.when)} · <code style="color:var(--accent);">${c.short}</code></div>
                </div>
            </div>`;
        }).join('');
    } catch(e) { body.innerHTML = `<div style="color:var(--error);">Chyba: ${e}</div>`; }
}

// 137: Issue fullscreen detail overlay
let _ifsKey = null;
async function _openIssueFullscreen(kb64) {
    _ifsKey = kb64;
    const modal = document.getElementById('issue-fullscreen-modal');
    if (!modal) return;
    modal.style.display = 'flex';
    document.addEventListener('keydown', _ifsEscHandler);

    // Reset
    document.getElementById('ifs-title').textContent = 'Načítám…';
    document.getElementById('ifs-body').innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
    document.getElementById('ifs-timeline').innerHTML = '';
    document.getElementById('ifs-ai').textContent = 'Kliknutím spusť AI analýzu…';
    document.getElementById('ifs-similar').textContent = '—';

    try {
        // Load issue detail
        const [issR, commR] = await Promise.all([
            fetch('/api/v1/issues').then(r=>r.json()).catch(()=>({issues:[]})),
            fetch(`/api/issues/${kb64}/comments`).then(r=>r.json()).catch(()=>({comments:[]})),
        ]);
        const key = atob(kb64);
        const issue = (issR.issues||[]).find(i=>i.key===key) || {};
        const host = issue.host || '?';
        const plugin = issue.plugin_name || '?';
        const msg = issue.last_line || '—';
        const ts = issue.last_seen ? new Date(issue.last_seen).toLocaleString('cs-CZ') : '—';
        const sev = issue.severity || '';

        document.getElementById('ifs-title').innerHTML =
            `<span style="font-family:monospace;">${_escape(host)}</span> / <span style="color:var(--text-muted);">${_escape(plugin)}</span>` +
            (sev ? ` <span style="font-size:.78em;padding:1px 7px;border-radius:8px;background:rgba(255,255,255,.1);">${_escape(sev)}</span>` : '');

        document.getElementById('ifs-body').innerHTML = `
            <div style="margin-bottom:12px;display:flex;gap:12px;flex-wrap:wrap;font-size:.82em;color:var(--text-muted);">
                <span><i class="fa-solid fa-server"></i> ${_escape(host)}</span>
                <span><i class="fa-solid fa-plug"></i> ${_escape(plugin)}</span>
                <span><i class="fa-solid fa-clock"></i> ${_escape(ts)}</span>
                ${issue.status ? `<span style="color:var(--accent);">● ${_escape(issue.status)}</span>` : ''}
            </div>
            <div style="background:rgba(255,255,255,.03);border:1px solid var(--border);border-radius:6px;padding:14px;font-family:monospace;font-size:.88em;white-space:pre-wrap;word-break:break-word;line-height:1.6;">${_escape(msg)}</div>
            ${issue.tags?.length ? `<div style="margin-top:10px;">${issue.tags.map(t=>`<span style="display:inline-block;margin:2px;padding:2px 8px;background:rgba(0,120,212,.15);border-radius:10px;font-size:.78em;">#${_escape(t)}</span>`).join('')}</div>` : ''}`;

        // Timeline/comments
        const comms = commR.comments || [];
        document.getElementById('ifs-timeline').innerHTML = comms.length
            ? comms.map(c=>`<div style="padding:8px 0;border-bottom:1px solid var(--border);font-size:.82em;">
                <span style="color:var(--accent);font-weight:600;">${_escape(c.author||'?')}</span>
                <span style="color:var(--text-muted);margin-left:6px;font-size:.85em;">${c.created_at||''}</span>
                <div style="margin-top:4px;color:var(--text-main);">${_escape(c.text||'')}</div>
              </div>`).join('')
            : '<span style="color:var(--text-muted);font-size:.82em;">Žádné komentáře.</span>';

        // Inline comment form
        document.getElementById('ifs-timeline').innerHTML += `
            <div style="margin-top:12px;display:flex;gap:6px;">
                <input id="ifs-comment-inp" type="text" placeholder="Přidat komentář…"
                    style="flex:1;padding:5px 8px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:4px;font-size:.82em;"
                    onkeydown="if(event.key==='Enter')_ifsAddComment()">
                <button onclick="_ifsAddComment()" style="padding:5px 10px;background:var(--accent);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.82em;">Přidat</button>
            </div>`;

        // Similar incidents
        _ifsLoadSimilar(kb64);
    } catch(e) {
        document.getElementById('ifs-body').innerHTML = `<span style="color:var(--error);">Chyba: ${_escape(e.message)}</span>`;
    }
}

async function _ifsLoadSimilar(kb64) {
    try {
        const r = await fetch(`/api/issues/${kb64}/similar`);
        const d = await r.json();
        const el = document.getElementById('ifs-similar');
        const items = d.similar || [];
        el.innerHTML = items.length
            ? items.slice(0,5).map(s=>`<div style="padding:5px 0;border-bottom:1px solid var(--border);font-size:.8em;"><b style="color:var(--text-muted);">${_escape(s.host||'?')}</b>: ${_escape((s.last_line||'').slice(0,80))}</div>`).join('')
            : '<span style="color:var(--text-muted);">Žádné podobné.</span>';
    } catch(e) {}
}

async function _ifsRunAi() {
    const el = document.getElementById('ifs-ai');
    el.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> AI analyzuje…';
    try {
        const r = await fetch(`/api/issues/${_ifsKey}/analyze`, {method:'POST', headers:{'Content-Type':'application/json'}});
        const d = await r.json();
        el.innerHTML = _mdRender ? _mdRender(d.reply||d.error||'?') : (d.reply||d.error||'?');
    } catch(e) {
        el.innerHTML = `<span style="color:var(--error);">Chyba: ${_escape(e.message)}</span>`;
    }
}

async function _ifsAddComment() {
    const inp = document.getElementById('ifs-comment-inp');
    if (!inp || !inp.value.trim() || !_ifsKey) return;
    await fetch(`/api/issues/${_ifsKey}/comments`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({text: inp.value.trim()})});
    inp.value = '';
    await _openIssueFullscreen(_ifsKey);
}

function _closeIssueFullscreen() {
    const modal = document.getElementById('issue-fullscreen-modal');
    if (modal) modal.style.display = 'none';
    document.removeEventListener('keydown', _ifsEscHandler);
    _ifsKey = null;
}

function _ifsEscHandler(e) { if (e.key === 'Escape') _closeIssueFullscreen(); }

// 223: Mobilní swipe na issue kartách (swipe right = acknowledge, swipe left = delete)
function _initSwipeGestures(container) {
    if (!container || window.innerWidth > 850) return;
    container.querySelectorAll('[data-issue-card]').forEach(card => {
        if (card.dataset.swipeInit) return;
        card.dataset.swipeInit = '1';
        let startX = 0, startY = 0, dx = 0;
        card.addEventListener('touchstart', e => {
            startX = e.touches[0].clientX;
            startY = e.touches[0].clientY;
            dx = 0;
        }, {passive: true});
        card.addEventListener('touchmove', e => {
            dx = e.touches[0].clientX - startX;
            const dy = Math.abs(e.touches[0].clientY - startY);
            if (Math.abs(dx) > dy && Math.abs(dx) > 10) {
                card.style.transform = `translateX(${dx * 0.5}px)`;
                card.style.opacity = String(1 - Math.min(Math.abs(dx) / 200, 0.4));
            }
        }, {passive: true});
        card.addEventListener('touchend', async () => {
            card.style.transform = '';
            card.style.opacity = '';
            const kb64 = card.dataset.issueKey;
            if (!kb64) return;
            if (dx > 80) {
                // Swipe right → acknowledge
                card.style.border = '1px solid var(--success)';
                await fetch(`/api/issues/${kb64}/acknowledge`, {method:'POST'});
                setTimeout(() => refreshModalIssuesContent(false), 400);
            } else if (dx < -80) {
                // Swipe left → delete (s potvrzením)
                if (confirm('Smazat tento záznam?')) {
                    card.style.border = '1px solid var(--error)';
                    await fetch(`/api/issues/delete`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({key_b64: kb64})});
                    setTimeout(() => refreshModalIssuesContent(false), 400);
                }
            }
        });
    });
}

// 226: Virtual scroll — načíst další stránku issues
async function _loadMoreIssues(channel, offset) {
    const bodyEl = document.getElementById('dedicated-modal-body');
    // Odstraň tlačítko "Načíst více"
    const btn = bodyEl?.querySelector('button[onclick*="_loadMoreIssues"]')?.closest('div');
    if (btn) btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin" style="color:var(--accent);"></i>';
    try {
        const snoozeParam = _showSnoozed ? '&snoozed=1' : '';
        const r = await fetch(`/api/modal_issues/${channel}?offset=${offset}${snoozeParam}`);
        const d = await r.json();
        if (d.html && bodyEl) {
            // Nahraď tlačítko novým obsahem
            if (btn) {
                const tmp = document.createElement('div');
                tmp.innerHTML = d.html;
                btn.replaceWith(...tmp.childNodes);
            }
        }
    } catch(e) {
        if (btn) btn.innerHTML = `<span style="color:var(--error);font-size:.82em;">Chyba: ${_escape(String(e))}</span>`;
    }
}

// 168: Auto-cluster correlation
async function _autoClusterAnalyze() {
    const btn = document.getElementById('auto-cluster-btn');
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>'; }
    const body = document.getElementById('dedicated-modal-body');

    const placeholder = document.createElement('div');
    placeholder.id = 'auto-cluster-result';
    placeholder.style.cssText = 'background:rgba(16,185,129,.07);border:1px solid rgba(16,185,129,.3);border-radius:6px;padding:12px;margin-bottom:10px;font-size:.85em;';
    placeholder.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Analyzuji clustery…';
    if (body) body.insertAdjacentElement('afterbegin', placeholder);

    try {
        const r = await fetch('/api/analyze/auto_clusters', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({channel: currentOpenChannel, window_min: 30, use_ai: true}),
        });
        const d = await r.json();
        const clusters = d.clusters || [];
        const el = document.getElementById('auto-cluster-result');
        if (!el) return;

        if (!clusters.length) {
            el.innerHTML = `<div style="color:var(--text-muted);">${d.message || 'Žádné korelované clustery nalezeny (okno: 30 min).'}</div>`;
            return;
        }

        const typeIcon = {plugin: 'fa-plug', host: 'fa-server'};
        el.innerHTML = `<div style="margin-bottom:8px;font-size:.72em;text-transform:uppercase;color:rgba(16,185,129,.8);letter-spacing:.07em;">
            <i class="fa-solid fa-object-group"></i> Auto-clustery — ${clusters.length} skupin (okno: ${d.window_min} min)
        </div>` + clusters.map(c => {
            const icon = typeIcon[c.type] || 'fa-layer-group';
            const issues = c.issues || [];
            return `<div style="border-left:3px solid #10b981;padding:8px 10px;margin-bottom:6px;background:rgba(255,255,255,.02);border-radius:0 4px 4px 0;">
                <div style="font-weight:600;font-size:.85em;margin-bottom:3px;">
                    <i class="fa-solid ${icon}" style="color:#10b981;margin-right:4px;"></i>${_escape(c.label)}
                </div>
                ${c.ai_summary ? `<div style="font-size:.78em;color:#a3e8d0;margin-bottom:4px;"><i class="fa-solid fa-lightbulb"></i> ${_escape(c.ai_summary)}</div>` : ''}
                <div style="font-size:.76em;color:var(--text-muted);">
                    ${issues.slice(0, 5).map(i =>
                        `<span style="display:inline-block;margin:1px 3px 1px 0;padding:1px 6px;background:rgba(255,255,255,.06);border-radius:3px;">${_escape(i.host || i.plugin || '?')}: ${_escape((i.last_line||'').slice(0,60))}</span>`
                    ).join('')}${issues.length > 5 ? `<span style="color:var(--text-muted);">+${issues.length-5} dalších</span>` : ''}
                </div>
            </div>`;
        }).join('');
    } catch(e) {
        const el = document.getElementById('auto-cluster-result');
        if (el) el.innerHTML = `<span style="color:var(--error);">Chyba: ${_escape(e.message)}</span>`;
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-object-group"></i> Clustery'; }
    }
}

// ---- Pattern Editor ----
async function openPatternEditor() {
    document.getElementById('pattern-modal').style.display = 'flex';
    await _loadPatterns();
}
async function _loadPatterns() {
    const list = document.getElementById('pattern-list');
    list.innerHTML = '<div style="color:var(--text-muted);font-size:.82em;">Načítám…</div>';
    try {
        const r = await fetch('/api/patterns');
        const d = await r.json();
        const pats = d.patterns || [];
        if (!pats.length) { list.innerHTML = '<div style="color:var(--text-muted);font-size:.82em;">Žádné custom patterns.</div>'; return; }
        list.innerHTML = pats.map(p => `<div style="display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--border);font-size:.82em;">
            <span style="min-width:10px;color:${p.enabled?'var(--success)':'var(--text-muted)'};" title="${p.enabled?'Aktivní':'Vypnuto'}">●</span>
            <b style="min-width:100px;">${_escape(p.name)}</b>
            <code style="flex:1;font-size:.8em;color:var(--accent);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_escape(p.pattern)}</code>
            <span style="color:var(--text-muted);min-width:60px;">${_escape(p.channel)}</span>
            <i class="fa-solid fa-toggle-${p.enabled?'on':'off'}" style="cursor:pointer;color:var(--accent);" onclick="_togglePattern(${p.id})"></i>
            <i class="fa-solid fa-trash" style="cursor:pointer;color:var(--error);" onclick="_deletePattern(${p.id})"></i>
        </div>`).join('');
    } catch { list.innerHTML = '<div style="color:var(--error);">Chyba</div>'; }
}
async function _addPattern() {
    const name = document.getElementById('pat-name').value.trim();
    const plugin = document.getElementById('pat-plugin').value.trim();
    const pattern = document.getElementById('pat-pattern').value.trim();
    const channel = document.getElementById('pat-channel').value;
    const msg = document.getElementById('pat-msg');
    if (!name||!plugin||!pattern) { msg.textContent = 'Vyplňte všechna pole'; return; }
    const r = await fetch('/api/patterns', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name,plugin,pattern,channel})});
    const d = await r.json();
    if (d.status==='ok') { msg.textContent=''; ['pat-name','pat-plugin','pat-pattern'].forEach(id=>document.getElementById(id).value=''); await _loadPatterns(); }
    else msg.textContent = d.status || d.error || 'Chyba';
}
async function _togglePattern(id) { await fetch(`/api/patterns/${id}/toggle`, {method:'POST'}); await _loadPatterns(); }
async function _deletePattern(id) { if (!confirm('Smazat pattern?')) return; await fetch(`/api/patterns/${id}`, {method:'DELETE'}); await _loadPatterns(); }
async function _testPattern() {
    const pat = document.getElementById('pat-pattern').value || document.getElementById('pat-test-text').dataset.lastPat || '';
    const text = document.getElementById('pat-test-text').value;
    const res = document.getElementById('pat-test-result');
    if (!pat||!text) { res.textContent='Zadejte pattern a text'; return; }
    const r = await fetch('/api/patterns/test', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({pattern:pat,text})});
    const d = await r.json();
    if (d.error) res.innerHTML = `<span style="color:var(--error);">✗ Neplatný regex: ${_escape(d.error)}</span>`;
    else if (d.match) res.innerHTML = `<span style="color:var(--success);">✓ MATCH${d.groups.length?' — skupiny: '+d.groups.map(g=>`<code>${_escape(g)}</code>`).join(', '):''}</span>`;
    else res.innerHTML = '<span style="color:var(--text-muted);">✗ Žádná shoda</span>';
}

// 158: AI pattern suggestion
async function _suggestPatterns() {
    const btn = document.getElementById('pat-suggest-btn');
    const panel = document.getElementById('pat-suggestions');
    if (!btn || !panel) return;
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Analyzuji…';
    panel.style.display = 'none';
    panel.innerHTML = '';
    try {
        const r = await fetch('/api/patterns/suggest', {method: 'POST', headers: {'Content-Type': 'application/json'}});
        const d = await r.json();
        if (d.error) { panel.style.display='flex'; panel.innerHTML=`<span style="color:var(--error);font-size:.82em;">${_escape(d.error)}</span>`; return; }
        const suggestions = d.suggestions || [];
        if (!suggestions.length) {
            panel.style.display = 'flex';
            panel.innerHTML = `<span style="color:var(--text-muted);font-size:.82em;">${d.message || 'Žádné návrhy.'}</span>`;
            return;
        }
        panel.style.display = 'flex';
        panel.innerHTML = suggestions.map((s, i) => `
            <div style="background:var(--panel);border:1px solid var(--border);border-radius:5px;padding:10px 12px;">
                <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px;margin-bottom:6px;">
                    <div>
                        <b style="font-size:.85em;">${_escape(s.name || '?')}</b>
                        <span style="margin-left:6px;font-size:.75em;color:var(--text-muted);">plugin: ${_escape(s.plugin||'?')} | kanál: ${_escape(s.channel||'agent')}</span>
                    </div>
                    <button onclick="_applySuggestion(${i})" style="padding:3px 9px;font-size:.78em;background:var(--accent);color:#fff;border:none;border-radius:3px;cursor:pointer;white-space:nowrap;">
                        <i class="fa-solid fa-plus"></i> Přidat
                    </button>
                </div>
                <code style="display:block;font-size:.8em;color:var(--accent);word-break:break-all;margin-bottom:4px;">${_escape(s.pattern||'')}</code>
                ${s.reason ? `<div style="font-size:.75em;color:var(--text-muted);">${_escape(s.reason)}</div>` : ''}
            </div>`).join('');
        // Store suggestions for _applySuggestion
        window._lastSuggestions = suggestions;
    } catch(e) {
        panel.style.display = 'flex';
        panel.innerHTML = `<span style="color:var(--error);font-size:.82em;">Chyba: ${_escape(e.message)}</span>`;
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-lightbulb"></i> Navrhnout';
    }
}

async function _applySuggestion(index) {
    const s = (window._lastSuggestions || [])[index];
    if (!s) return;
    const r = await fetch('/api/patterns', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: s.name, plugin: s.plugin, pattern: s.pattern, channel: s.channel || 'agent'}),
    });
    const d = await r.json();
    if (d.status === 'ok') {
        await _loadPatterns();
        // Highlight added pattern in suggestion panel
        const btns = document.querySelectorAll('#pat-suggestions button');
        if (btns[index]) { btns[index].textContent = '✓ Přidáno'; btns[index].disabled = true; btns[index].style.background = 'var(--success)'; }
    } else {
        alert(d.error || 'Chyba při přidávání patternu.');
    }
}

// ---- System Errors Modal ----
async function openSystemErrorsModal() {
    const modal = document.getElementById('system-errors-modal');
    const body = document.getElementById('system-errors-body');
    modal.style.display = 'flex';
    body.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>';
    try {
        const r = await fetch('/api/system/errors?limit=100');
        const d = await r.json();
        const errs = d.errors || [];
        if (!errs.length) { body.innerHTML = '<div style="color:var(--success);text-align:center;padding:20px;"><i class="fa-solid fa-check-circle"></i> Žádné chyby.</div>'; return; }
        const lvlColor = {ERROR:'var(--error)', CRITICAL:'#ff4500', WARNING:'var(--warning)'};
        body.innerHTML = errs.map(e => {
            const cl = lvlColor[e.level] || 'var(--text-muted)';
            return `<div style="margin-bottom:8px;padding:8px 10px;border:1px solid var(--border);border-left:3px solid ${cl};border-radius:4px;background:var(--panel);">
                <div style="font-size:.75em;color:var(--text-muted);">${(e.timestamp||'').slice(0,16).replace('T',' ')} · <span style="color:${cl};font-weight:700;">${e.level}</span> · ${_escape(e.source||'')}</div>
                <div style="margin-top:3px;font-size:.82em;">${_escape(e.message||'')}</div>
            </div>`;
        }).join('');
    } catch { body.innerHTML = '<div style="color:var(--error);">Chyba načítání.</div>'; }
}
function closeSystemErrorsModal() { document.getElementById('system-errors-modal').style.display = 'none'; }

// ---- Comment Templates ----
let _templatesPanelOpen = false;

async function _loadCommentTemplates() {
    try {
        const r = await fetch('/api/comments/templates');
        const d = await r.json();
        return d.templates || [];
    } catch { return []; }
}

async function _showTemplatesPicker() {
    const tpls = await _loadCommentTemplates();
    const inp = document.getElementById('comments-input');
    if (!inp) return;
    // Odstraň existující picker
    document.querySelectorAll('.tpl-picker').forEach(el => el.remove());
    if (!tpls.length) { alert('Žádné šablony. Přidejte je přes API nebo Tools.'); return; }
    const menu = document.createElement('div');
    menu.className = 'tpl-picker';
    menu.style.cssText = 'position:fixed;z-index:9999;background:var(--panel);border:1px solid var(--border);border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,.4);padding:4px 0;min-width:220px;max-height:240px;overflow-y:auto;';
    tpls.forEach(t => {
        const item = document.createElement('div');
        item.innerHTML = `<b style="font-size:.85em;">${_escape(t.name)}</b><div style="font-size:.75em;color:var(--text-muted);margin-top:2px;">${_escape(t.text.slice(0,60))}${t.text.length>60?'…':''}</div>`;
        item.style.cssText = 'padding:8px 14px;cursor:pointer;';
        item.onmouseenter = () => item.style.background = 'rgba(255,255,255,0.07)';
        item.onmouseleave = () => item.style.background = '';
        item.onclick = () => { inp.value = t.text; inp.focus(); menu.remove(); };
        menu.appendChild(item);
    });
    document.body.appendChild(menu);
    const r = inp.getBoundingClientRect();
    menu.style.left = r.left + 'px';
    menu.style.top = (r.top - menu.offsetHeight - 4) + 'px';
    setTimeout(() => document.addEventListener('click', () => menu.remove(), {once: true}), 50);
}

// ---- Host Heatmap ----
async function openHostHeatmap() {
    document.getElementById('host-heatmap-modal').style.display = 'flex';
    await loadHostHeatmap(7);
}
async function loadHostHeatmap(days) {
    const body = document.getElementById('host-heatmap-body');
    body.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>';
    try {
        const r = await fetch(`/api/alerts/host_heatmap?days=${days}`);
        const d = await r.json();
        const data = d.data || [];
        if (!data.length) { body.innerHTML = '<div style="color:var(--text-muted);text-align:center;padding:20px;">Žádná data.</div>'; return; }
        // Pivot: hosts × days
        const hosts = [...new Set(data.map(x=>x.host))].sort();
        const days_set = [...new Set(data.map(x=>x.day))].sort();
        const lookup = {};
        data.forEach(x => { lookup[`${x.host}|${x.day}`] = x.count; });
        const maxVal = Math.max(...data.map(x=>x.count), 1);
        const heatColor = (cnt) => {
            if (!cnt) return 'rgba(255,255,255,0.03)';
            const ratio = Math.min(cnt / maxVal, 1);
            const r = Math.round(40 + ratio * 180), g = Math.round(180 - ratio * 150), b = 40;
            return `rgb(${r},${g},${b})`;
        };
        let html = `<table style="border-collapse:collapse;font-size:.75em;width:100%;">
            <tr><th style="padding:4px 8px;color:var(--text-muted);text-align:left;">Host</th>
            ${days_set.map(d=>`<th style="padding:4px 3px;color:var(--text-muted);text-align:center;min-width:32px;">${d.slice(5)}</th>`).join('')}
            <th style="padding:4px 8px;color:var(--text-muted);">Σ</th></tr>`;
        hosts.forEach(h => {
            const total = days_set.reduce((s,d)=>s+(lookup[`${h}|${d}`]||0),0);
            html += `<tr><td style="padding:4px 8px;white-space:nowrap;">${_escape(h)}</td>
                ${days_set.map(day=>{const cnt=lookup[`${h}|${day}`]||0;return `<td title="${cnt} alertů · ${day}" style="padding:3px;text-align:center;"><div style="width:28px;height:22px;background:${heatColor(cnt)};border-radius:3px;margin:0 auto;display:flex;align-items:center;justify-content:center;font-size:.8em;color:${cnt>maxVal*.5?'#fff':'var(--text-muted)'};">${cnt||''}</div></td>`;}).join('')}
                <td style="padding:4px 8px;font-weight:700;color:${total>0?'var(--error)':'var(--text-muted)'};">${total}</td></tr>`;
        });
        html += '</table>';
        body.innerHTML = html;
    } catch(e) { body.innerHTML = `<div style="color:var(--error);">Chyba: ${e}</div>`; }
}

// ---- Plugin Dependency Graph ----
async function openPluginGraph() {
    const modal = document.getElementById('plugin-graph-modal');
    const body = document.getElementById('plugin-graph-body');
    modal.style.display = 'flex';
    body.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>';
    try {
        const r = await fetch('/api/plugins/graph');
        const d = await r.json();
        const nodes = d.nodes || [], edges = d.edges || [];
        const logs = nodes.filter(n=>n.type==='log');
        const plugins = nodes.filter(n=>n.type==='plugin');
        const channels = nodes.filter(n=>n.type==='channel');
        const typeColor = {log:'rgba(0,120,212,.15)', plugin:'rgba(168,85,247,.15)', channel:'rgba(220,53,69,.12)'};
        const typeBorder = {log:'rgba(0,120,212,.4)', plugin:'rgba(168,85,247,.4)', channel:'rgba(220,53,69,.35)'};
        const typeLbl = {log:'Log', plugin:'Plugin', channel:'Kanál'};
        const col = (type) => `background:${typeColor[type]||'rgba(255,255,255,.05)'};border:1px solid ${typeBorder[type]||'var(--border)'};`;
        const nodeHtml = (n) => `<div style="${col(n.type)} border-radius:6px;padding:4px 10px;font-size:.8em;display:inline-block;margin:3px;white-space:nowrap;" title="${n.type}">
            <span style="font-size:.7em;color:var(--text-muted);">${typeLbl[n.type]||n.type}</span><br>${_escape(n.label||n.id.replace('log:','').replace('channel:',''))}
        </div>`;
        let html = `<div style="display:grid;grid-template-columns:1fr auto 1fr auto 1fr;gap:10px;align-items:start;">
            <div><div style="font-size:.72em;text-transform:uppercase;color:var(--text-muted);margin-bottom:8px;">Log soubory</div>${logs.map(nodeHtml).join('')}</div>
            <div style="display:flex;flex-direction:column;justify-content:center;height:100%;padding-top:30px;color:var(--text-muted);font-size:1.2em;">→</div>
            <div><div style="font-size:.72em;text-transform:uppercase;color:var(--text-muted);margin-bottom:8px;">Pluginy</div>${plugins.map(nodeHtml).join('')}</div>
            <div style="display:flex;flex-direction:column;justify-content:center;height:100%;padding-top:30px;color:var(--text-muted);font-size:1.2em;">→</div>
            <div><div style="font-size:.72em;text-transform:uppercase;color:var(--text-muted);margin-bottom:8px;">Kanály</div>${channels.map(nodeHtml).join('')}</div>
        </div>
        <div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--border);">
            <div style="font-size:.72em;text-transform:uppercase;color:var(--text-muted);margin-bottom:8px;">Přehled propojení (${edges.length} hran)</div>
            <div style="font-size:.8em;display:flex;flex-wrap:wrap;gap:6px;">
                ${edges.map(e=>`<span style="background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:4px;padding:2px 8px;">${_escape(e.from)} → ${_escape(e.to)}</span>`).join('')}
            </div>
        </div>`;
        body.innerHTML = html;
    } catch(e) { body.innerHTML = `<div style="color:var(--error);">Chyba: ${e}</div>`; }
}

// ---- Config Diff ----
async function openConfigDiff() {
    const modal = document.getElementById('config-diff-modal');
    const body = document.getElementById('config-diff-body');
    modal.style.display = 'flex';
    body.textContent = 'Načítám…';
    try {
        const r = await fetch('/api/config/diff');
        const d = await r.json();
        if (d.error) { body.textContent = 'Chyba: ' + d.error; return; }
        if (!d.has_diff) { body.innerHTML = '<div style="color:var(--success);text-align:center;padding:20px;font-family:sans-serif;"><i class="fa-solid fa-check-circle"></i> Config je aktuální — žádné rozdíly.</div>'; return; }
        // Barevný diff
        const lines = (d.diff||'').split('\n');
        body.innerHTML = lines.map(l => {
            let color = 'var(--text-main)';
            if (l.startsWith('+')) color = '#4caf50';
            else if (l.startsWith('-')) color = '#f44336';
            else if (l.startsWith('@@')) color = '#2196f3';
            return `<span style="color:${color};display:block;">${_escape(l)}</span>`;
        }).join('');
    } catch(e) { body.textContent = 'Chyba: ' + e; }
}

// ---- Plugin Hot-reload ----
async function reloadPlugins() {
    const btn = document.activeElement;
    if (btn) btn.disabled = true;
    try {
        const r = await fetch('/api/plugins/reload', {method:'POST'});
        const d = await r.json();
        if (d.status === 'ok') alert(`✓ Načteno ${d.count} pluginů:\n${(d.loaded||[]).map(p=>p.name).join(', ')}`);
        else alert('Chyba: ' + (d.message||'?'));
    } catch (e) { alert('Síťová chyba: ' + e); }
    finally { if (btn) btn.disabled = false; }
}

// ---- Issue Severity Picker ----
const _SEV_OPTS = [
    {v:'critical', label:'🔴 CRITICAL', color:'#ff4500'},
    {v:'high',     label:'🟠 HIGH',     color:'#fd7e14'},
    {v:'medium',   label:'🟡 MEDIUM',   color:'#ffc107'},
    {v:'low',      label:'⚪ LOW',      color:'#6c757d'},
    {v:'',         label:'— Zrušit',   color:'var(--text-muted)'},
];

function _setSeverity(kb64, triggerEl) {
    // Popup mini-menu pod triggerem
    document.querySelectorAll('.sev-picker').forEach(el => el.remove());
    const menu = document.createElement('div');
    menu.className = 'sev-picker';
    menu.style.cssText = 'position:fixed; z-index:9999; background:var(--panel); border:1px solid var(--border); border-radius:6px; box-shadow:0 4px 16px rgba(0,0,0,.4); padding:4px 0; min-width:140px;';
    _SEV_OPTS.forEach(opt => {
        const item = document.createElement('div');
        item.textContent = opt.label;
        item.style.cssText = `padding:7px 14px; cursor:pointer; font-size:0.85em; color:${opt.color};`;
        item.onmouseenter = () => item.style.background = 'rgba(255,255,255,0.07)';
        item.onmouseleave = () => item.style.background = '';
        item.onclick = async () => {
            menu.remove();
            await fetch(`/api/issues/${encodeURIComponent(kb64)}/severity`, {
                method: 'POST', headers: {'Content-Type':'application/json'},
                body: JSON.stringify({severity: opt.v})
            });
            refreshModalIssuesContent && refreshModalIssuesContent(false);
        };
        menu.appendChild(item);
    });
    document.body.appendChild(menu);
    const r = triggerEl.getBoundingClientRect();
    menu.style.left = r.left + 'px';
    menu.style.top = (r.bottom + 4) + 'px';
    setTimeout(() => document.addEventListener('click', () => menu.remove(), {once: true}), 50);
}

// ---- Issue Tags ----
let _tagModalKey = null;

async function _openTagModal(kb64) {
    _tagModalKey = kb64;
    document.getElementById('tag-modal').style.display = 'flex';
    if (currentOpenChannel) _pushBreadcrumb('tag-modal', 'Issues', () => openIssuesModal(currentOpenChannel));
    document.getElementById('tag-input').value = '';
    document.getElementById('tag-msg').textContent = '';
    await _loadTagModal(kb64);
}

function closeTagModal() {
    document.getElementById('tag-modal').style.display = 'none';
    _tagModalKey = null;
    _clearBreadcrumb('tag-modal');
}

async function _loadTagModal(kb64) {
    const list = document.getElementById('tag-list');
    list.innerHTML = '<span style="color:var(--text-muted); font-size:0.85em;">Načítám…</span>';
    try {
        const r = await fetch(`/api/issues/${encodeURIComponent(kb64)}/tags`);
        const d = await r.json();
        const tags = d.tags || [];
        if (!tags.length) {
            list.innerHTML = '<span style="color:var(--text-muted); font-size:0.82em;">Žádné tagy</span>';
            return;
        }
        list.innerHTML = tags.map(t =>
            `<span style="background:rgba(0,120,212,0.2); color:#a3cfff; border:1px solid rgba(0,120,212,0.3); border-radius:10px; font-size:0.82em; padding:2px 9px; display:inline-flex; align-items:center; gap:5px;">
                #${_escape(t.tag)}
                <i class="fa-solid fa-xmark" style="cursor:pointer; font-size:0.75em;" onclick="deleteTag(${t.id}, '${kb64}')"></i>
            </span>`
        ).join('');
    } catch {
        list.innerHTML = '<span style="color:var(--error); font-size:0.82em;">Chyba načítání</span>';
    }
}

async function addTagFromModal() {
    if (!_tagModalKey) return;
    const inp = document.getElementById('tag-input');
    const msg = document.getElementById('tag-msg');
    const tag = inp.value.trim();
    if (!tag) { msg.textContent = 'Tag nesmí být prázdný'; return; }
    msg.textContent = '';
    try {
        const r = await fetch(`/api/issues/${encodeURIComponent(_tagModalKey)}/tags`, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({tag})
        });
        if (r.ok) { inp.value = ''; await _loadTagModal(_tagModalKey); refreshModalIssuesContent(false); }
        else msg.textContent = 'Chyba přidání tagu';
    } catch { msg.textContent = 'Síťová chyba'; }
}

async function deleteTag(id, kb64) {
    try {
        await fetch(`/api/issues/tags/${id}`, {method: 'DELETE'});
        await _loadTagModal(kb64);
        refreshModalIssuesContent(false);
    } catch {}
}

function _filterByTag(tag) {
    const inp = document.getElementById('issues-filter-input');
    if (inp) { inp.value = '#' + tag; filterIssueCards('#' + tag); }
}

// ---- Batch AI Analysis ----
async function _batchAiAnalyze() {
    const btn = document.getElementById('batch-ai-btn');
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Analyzuji…'; }
    const body = document.getElementById('dedicated-modal-body');
    const placeholder = document.createElement('div');
    placeholder.id = 'batch-ai-result';
    placeholder.style.cssText = 'background:rgba(168,85,247,.08);border:1px solid rgba(168,85,247,.3);border-radius:6px;padding:12px;margin-bottom:10px;font-size:.85em;';
    placeholder.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> AI analyzuje…';
    if (body) body.insertAdjacentElement('afterbegin', placeholder);

    const chLabel = {'infra':'Infrastruktura','agent':'Agenti','security':'Security','root':'Root'}[currentOpenChannel] || 'Všechny';
    // Thinking bubble v chatu — viditelné i po zavření modalu
    const thinking = typeof _addThinkingBubble === 'function' ? _addThinkingBubble() : null;
    appendMessage(`<i class="fa-solid fa-robot" style="color:#a855f7;"></i> <b>AI Souhrn</b> — kategorie: <b>${chLabel}</b>…`, 'user');

    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 180000);
    try {
        const r = await fetch('/api/analyze/active_issues', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({channel: currentOpenChannel}),
            signal: ctrl.signal
        });
        const d = await r.json();
        const reply = d.reply || d.error || '?';
        if (thinking) thinking.remove();
        const el = document.getElementById('batch-ai-result');
        if (el) el.innerHTML = `<div style="margin-bottom:6px;font-size:.72em;text-transform:uppercase;color:rgba(168,85,247,.8);letter-spacing:.07em;"><i class="fa-solid fa-robot"></i> AI Souhrn — ${chLabel}</div>${reply}`;
        appendMessage(reply, 'bot');
    } catch (e) {
        if (thinking) thinking.remove();
        const el = document.getElementById('batch-ai-result');
        if (e.name === 'AbortError') {
            if (el) el.innerHTML = `<span style="color:var(--text-muted);font-size:.82em;"><i class="fa-solid fa-clock"></i> AI analýza trvá déle než obvykle. Zkuste znovu.</span>`;
        } else {
            if (el) el.innerHTML = `<span style="color:var(--error);font-size:.82em;">Chyba: ${_escape(String(e))}</span>`;
        }
    } finally {
        clearTimeout(timer);
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-robot"></i> AI Souhrn'; }
    }
}

async function _correlateAiAnalyze() {
    const btn = document.getElementById('correlate-ai-btn');
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>'; }
    const body = document.getElementById('dedicated-modal-body');
    const placeholder = document.createElement('div');
    placeholder.id = 'correlate-ai-result';
    placeholder.style.cssText = 'background:rgba(0,120,212,.08);border:1px solid rgba(0,120,212,.3);border-radius:6px;padding:12px;margin-bottom:10px;font-size:.85em;';
    placeholder.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Korelace…';
    if (body) body.insertAdjacentElement('afterbegin', placeholder);

    const chLabel = {'infra':'Infrastruktura','agent':'Agenti','security':'Security','root':'Root'}[currentOpenChannel] || 'Všechny';
    const thinking = typeof _addThinkingBubble === 'function' ? _addThinkingBubble() : null;
    appendMessage(`<i class="fa-solid fa-link" style="color:#0078d4;"></i> <b>AI Korelace</b> — kategorie: <b>${chLabel}</b>…`, 'user');

    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 180000);
    try {
        const r = await fetch('/api/analyze/correlate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({channel: currentOpenChannel}),
            signal: ctrl.signal
        });
        const d = await r.json();
        const reply = d.reply || d.error || '?';
        if (thinking) thinking.remove();
        const el = document.getElementById('correlate-ai-result');
        if (el) el.innerHTML = `<div style="margin-bottom:6px;font-size:.72em;text-transform:uppercase;color:rgba(0,120,212,.8);letter-spacing:.07em;"><i class="fa-solid fa-link"></i> AI Korelace — ${chLabel}</div>${reply}`;
        appendMessage(reply, 'bot');
    } catch(e) {
        if (thinking) thinking.remove();
        const el = document.getElementById('correlate-ai-result');
        if (e.name === 'AbortError') {
            if (el) el.innerHTML = `<span style="color:var(--text-muted);font-size:.82em;"><i class="fa-solid fa-clock"></i> AI analýza trvá déle než obvykle. Zkuste znovu.</span>`;
        } else {
            if (el) el.innerHTML = `<span style="color:var(--error);font-size:.82em;">Chyba: ${_escape(String(e))}</span>`;
        }
    } finally {
        clearTimeout(timer);
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-link"></i> Korelace'; }
    }
}

// ---- Action Audit Log Modal ----
let _auditData = [];

async function openActionAuditModal() {
    document.getElementById('action-audit-modal').style.display = 'flex';
    await loadActionAuditLog();
}

function closeActionAuditModal() {
    document.getElementById('action-audit-modal').style.display = 'none';
}

async function loadActionAuditLog() {
    const body = document.getElementById('audit-log-body');
    body.innerHTML = `<div style="text-align:center; padding:20px; color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>`;
    try {
        const r = await fetch('/api/actions/audit_log?limit=200');
        const d = await r.json();
        _auditData = d.audit || [];
        _renderAuditLog(_auditData);
    } catch (e) {
        body.innerHTML = `<div style="color:var(--error); padding:16px;">Chyba načítání: ${e}</div>`;
    }
}

function _renderAuditLog(rows) {
    const body = document.getElementById('audit-log-body');
    if (!rows.length) {
        body.innerHTML = `<div style="text-align:center; padding:30px; color:var(--text-muted);">Žádné záznamy.</div>`;
        return;
    }
    const eventColors = { approved: 'var(--success)', executed: '#0078d4', rejected: 'var(--error)', expired: 'var(--text-muted)', reviewed: '#fa8231' };
    body.innerHTML = rows.map(r => {
        const col = eventColors[r.event] || 'var(--text-muted)';
        const ts = r.at ? r.at.slice(0, 16).replace('T', ' ') : '-';
        const cmd = r.command ? `<code style="font-size:0.8em; color:var(--accent);">${_escape(r.command)}</code>` : '';
        const risk = r.risk_score != null ? `<span style="color:${r.risk_score > 60 ? 'var(--error)' : 'var(--warning)'}; font-size:0.78em;"> risk:${r.risk_score}</span>` : '';
        const node = r.node ? `<span style="color:var(--text-muted); font-size:0.8em;">${_escape(r.node)}</span>` : '';
        return `<div style="display:flex; gap:10px; padding:8px 10px; margin-bottom:4px; background:var(--panel); border:1px solid var(--border); border-left:3px solid ${col}; border-radius:4px; align-items:flex-start; font-size:0.85em;" data-audit-row>
            <div style="min-width:100px; color:var(--text-muted);">${ts}</div>
            <div style="min-width:70px; font-weight:700; color:${col};">${r.event || '-'}</div>
            <div style="min-width:80px; color:var(--text-muted);">${_escape(r.actor || '-')}</div>
            <div style="flex:1; min-width:0;">${node} ${cmd}${risk}</div>
            <div style="min-width:44px; text-align:right; color:var(--text-muted); font-size:0.75em;">#${r.action_id}</div>
        </div>`;
    }).join('');
}

function _auditFilter(q) {
    const lq = q.toLowerCase();
    const filtered = lq ? _auditData.filter(r =>
        (r.command || '').toLowerCase().includes(lq) ||
        (r.actor || '').toLowerCase().includes(lq) ||
        (r.event || '').toLowerCase().includes(lq) ||
        (r.node || '').toLowerCase().includes(lq)
    ) : _auditData;
    _renderAuditLog(filtered);
}

// ---- Autofix Modal ----
let _autofixHtml = '';

function openAutofixModal(b64Payload) {
    _autofixHtml = '';
    document.getElementById('autofix-tochat-btn').style.display = 'none';
    document.getElementById('autofix-modal-body').innerHTML = `
        <div style="text-align:center; padding:32px 20px;">
            <i class="fa-solid fa-spinner fa-spin" style="font-size:2em; color:#a855f7; display:block; margin-bottom:14px;"></i>
            <div style="color:var(--text-muted,#888); font-size:0.92em;">AI is analyzing the issue…</div>
        </div>`;
    document.getElementById('autofix-modal').style.display = 'flex';
    _runAutofix(b64Payload);
}

function closeAutofixModal() {
    document.getElementById('autofix-modal').style.display = 'none';
}

async function _runAutofix(b64Payload) {
    try {
        const decoded = atob(b64Payload);
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: 'autofix_text ' + decoded }),
        });
        const d = await res.json();
        _autofixHtml = d.reply || '<span style="color:var(--error,#dc3545)">No response from AI.</span>';
        document.getElementById('autofix-modal-body').innerHTML = `<div style="padding:4px 2px;">${_autofixHtml}</div>`;
        document.getElementById('autofix-tochat-btn').style.display = '';
    } catch (e) {
        document.getElementById('autofix-modal-body').innerHTML =
            `<div style="color:var(--error,#dc3545); padding:16px;">Connection error: ${_escape(String(e))}</div>`;
    }
}

function sendAutofixToChat() {
    if (_autofixHtml) appendMessage(_autofixHtml, 'ai');
}

function _riskBadge(score) {
    let color = 'var(--success)', label = 'safe';
    if (score >= 70) { color = 'var(--error)'; label = 'block'; }
    else if (score >= 30) { color = '#ffc107'; label = 'review'; }
    return `<span style="display:inline-block; min-width:56px; padding:3px 6px; border-radius:4px; background:${color}; color:#000; font-weight:bold; text-align:center;">${score} ${label}</span>`;
}

function _escape(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

async function loadPendingActions(isAutoRefresh = false) {
    const tbody = document.getElementById('pending-actions-tbody');
    const empty = document.getElementById('pending-actions-empty');
    const table = document.getElementById('pending-actions-table');
    if (!isAutoRefresh) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:20px; color:#666;"><i class="fa-solid fa-spinner fa-spin"></i> ${t('loading')}</td></tr>`;
    }
    try {
        const res = await fetch('/api/v1/actions?status=pending&mode=dry_run');
        const data = await res.json();
        const list = data.actions || [];
        if (list.length === 0) {
            tbody.innerHTML = '';
            empty.style.display = 'block';
            table.style.display = 'none';
            return;
        }
        empty.style.display = 'none';
        table.style.display = '';
        const isViewer = (window.currentRole === 'viewer');
        list.forEach(a => { _actionCache[a.id] = a; });
        tbody.innerHTML = list.map(a => {
            const reasons = (a.risk_reasons || []).map(_escape).join(', ');
            const dry = a.dry_run_output ? `<tr><td colspan="${isViewer ? 5 : 6}" style="padding:0 8px 8px;"><div style="padding:6px; background:rgba(255,255,255,0.04); border-left:2px solid var(--accent); font-family:monospace; font-size:0.78em; white-space:pre-wrap;">${_escape(a.dry_run_output)}</div></td></tr>` : '';
            const editRowId = `edit-row-${a.id}`;
            const reanalyzeSource = a.raw_line || a.reason || '';
            const reanalyzeB64 = btoa(unescape(encodeURIComponent(reanalyzeSource)));
            const _abtn = (onclick, color, icon, title) =>
                `<button onclick="${onclick}" title="${title}" style="width:32px;height:32px;display:inline-flex;align-items:center;justify-content:center;background:transparent;border:1px solid ${color};color:${color};border-radius:4px;cursor:pointer;flex-shrink:0;"><i class="${icon}"></i></button>`;
            const actionsBtns = isViewer ? '' : `
                    <td style="padding:8px;">
                        <div style="display:flex;flex-wrap:wrap;gap:4px;justify-content:flex-end;">
                        ${_abtn(`executePendingAction(${a.id})`, 'var(--success)', 'fa-solid fa-play', t('execute_title'))}
                        ${_abtn(`toggleEditCmd(${a.id})`, '#a855f7', 'fa-solid fa-pen', t('edit_command_title'))}
                        ${_abtn(`openAutofixModal('${reanalyzeB64}')`, '#888', 'fa-solid fa-rotate', t('reanalyze_title'))}
                        ${_abtn(`reviewPendingAction(${a.id})`, 'var(--success)', 'fa-solid fa-eye', t('mark_reviewed_title'))}
                        ${_abtn(`deletePendingAction(${a.id})`, 'var(--error)', 'fa-solid fa-trash', t('delete_btn'))}
                        </div>
                    </td>`;
            return `
                <tr style="border-bottom:${dry ? 'none' : '1px solid var(--border)'}; vertical-align:top;">
                    <td style="padding:8px; color:#888;">${a.id}</td>
                    <td style="padding:8px;"><b>${_escape(a.node)}</b><br><small style="opacity:0.6;">${_escape(a.cluster)}</small></td>
                    <td style="padding:8px; max-width:220px;">
                        <code style="background:rgba(255,255,255,0.05); padding:2px 5px; border-radius:3px; word-break:break-all;">${_escape(a.command)}</code>
                        ${isViewer ? '' : `<div id="${editRowId}" style="display:none; margin-top:5px;">
                            <input id="editcmd-${a.id}" value="${_escape(a.command)}" style="width:calc(100% - 58px); background:var(--code-bg,#1a1a1a); color:var(--code-text,#e0e0e0); border:1px solid var(--border,#444); border-radius:3px; padding:4px 6px; font-family:monospace; font-size:0.85em;">
                            <button onclick="saveActionCmd(${a.id})" style="background:#6f42c1; color:white; border:none; padding:4px 8px; border-radius:3px; cursor:pointer; margin-left:3px; font-size:0.82em;">Save</button>
                        </div>`}
                    </td>
                    <td style="padding:8px; max-width:200px;">${_escape(a.reason)}${reasons ? `<br><small style="color:#ffc107;">${reasons}</small>` : ''}</td>
                    <td style="padding:8px; text-align:center;">${_riskBadge(a.risk_score || 0)}</td>
                    ${actionsBtns}
                </tr>${dry}`;
        }).join('');
    } catch (e) {
        if (!isAutoRefresh) {
            tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:20px; color:var(--error);">${t('load_error_detail', {msg: _escape(e.message || e)})}</td></tr>`;
        }
    }
}

async function reviewPendingAction(aid) {
    try {
        const res = await fetch(`/api/v1/actions/${aid}/review`, { method: 'POST' });
        if (!res.ok) {
            const j = await res.json().catch(() => ({}));
            alert(j.reply || `HTTP ${res.status}`);
            return;
        }
        loadPendingActions(true);
    } catch (e) { alert('Network error: ' + e); }
}

async function rejectPendingAction(aid) {
    if (!confirm(t('confirm_reject_proposal', {id: aid}))) return;
    try {
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: `reject ${aid}` }),
        });
        if (!res.ok) { alert(`HTTP ${res.status}`); return; }
        loadPendingActions(true);
    } catch (e) { alert('Network error: ' + e); }
}

const _actionCache = {};
let _pendingExecuteId = null;

function executePendingAction(aid) {
    _pendingExecuteId = aid;
    const a = _actionCache[aid] || {};
    document.getElementById('aem-command').textContent = a.command || String(aid);
    document.getElementById('aem-node').textContent    = a.node    || '—';
    document.getElementById('aem-cluster').textContent = a.cluster || '—';
    document.getElementById('aem-reason').textContent  = a.reason  || '—';
    document.getElementById('aem-risk').innerHTML      = _riskBadge(a.risk_score || 0);
    const outEl = document.getElementById('aem-output');
    outEl.style.display = 'none';
    outEl.textContent = '';
    const btn = document.getElementById('aem-confirm-btn');
    btn.disabled = false;
    btn.innerHTML = '<i class="fa-solid fa-play"></i> Spustit';
    document.getElementById('action-execute-modal').style.display = 'flex';
}

function cancelActionExecute() {
    document.getElementById('action-execute-modal').style.display = 'none';
    _pendingExecuteId = null;
}

async function confirmActionExecute() {
    if (!_pendingExecuteId) return;
    const aid = _pendingExecuteId;
    const btn = document.getElementById('aem-confirm-btn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Spouštím…';
    try {
        const res = await fetch(`/api/v1/actions/${aid}/execute`, { method: 'POST' });
        const d = await res.json();
        const outEl = document.getElementById('aem-output');
        if (d.output) {
            outEl.textContent = d.output;
            outEl.style.display = 'block';
        }
        if (d.status === 'ok') {
            outEl.textContent = (d.output && d.output.trim()) ? d.output : '✅ Příkaz proveden úspěšně (exit 0, bez textového výstupu).';
            outEl.style.color = '';
            outEl.style.display = 'block';
            btn.innerHTML = '<i class="fa-solid fa-check"></i> Hotovo';
            btn.disabled = true;
            loadPendingActions(true);
        } else {
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-play"></i> Spustit';
            outEl.style.color = 'var(--error,#dc3545)';
            outEl.style.display = 'block';
            loadPendingActions(true);
        }
    } catch (e) {
        cancelActionExecute();
        alert(t('settings_network_error') + ' ' + e);
    }
}

async function deletePendingAction(aid) {
    if (!confirm(t('confirm_delete_action', {id: aid}))) return;
    try {
        const res = await fetch(`/api/v1/actions/${aid}/delete`, { method: 'POST' });
        const d = await res.json();
        if (d.status === 'ok') loadPendingActions(true);
        else alert(t('delete_failed'));
    } catch (e) { alert(t('settings_network_error') + ' ' + e); }
}

function toggleEditCmd(aid) {
    const row = document.getElementById(`edit-row-${aid}`);
    if (row) row.style.display = row.style.display === 'none' ? 'block' : 'none';
}

async function saveActionCmd(aid) {
    const inp = document.getElementById(`editcmd-${aid}`);
    if (!inp) return;
    const cmd = inp.value.trim();
    if (!cmd) return;
    try {
        const res = await fetch(`/api/v1/actions/${aid}/update-command`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: cmd }),
        });
        const d = await res.json();
        if (d.status === 'ok') loadPendingActions(true);
        else alert('Update failed.');
    } catch (e) { alert('Network error: ' + e); }
}

// ---- Allowed Commands Modal ----

let allowedCmdsInterval = null;

function openAllowedCmdsModal() {
    document.getElementById('allowed-cmds-modal').style.display = 'flex';
    loadAllowedCmds();
}

function closeAllowedCmdsModal() {
    document.getElementById('allowed-cmds-modal').style.display = 'none';
}

async function loadAllowedCmds() {
    const tbody = document.getElementById('allowed-cmds-tbody');
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:12px;color:var(--text-muted,#888);"><i class="fa-solid fa-spinner fa-spin"></i></td></tr>';
    try {
        const res = await fetch('/api/v1/allowed-commands');
        const d = await res.json();
        const rules = d.rules || [];
        if (!rules.length) {
            tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-muted,#888);padding:14px;">${t('no_rules_yet')}</td></tr>`;
            return;
        }
        tbody.innerHTML = rules.map(r => `
            <tr style="border-bottom:1px solid var(--border,#333); vertical-align:middle;">
                <td style="padding:7px 8px;"><code style="font-size:0.85em;">${_escape(r.pattern)}</code></td>
                <td style="padding:7px 8px;">${_escape(r.description || '')}</td>
                <td style="padding:7px 8px; text-align:center;">${r.auto_execute ? '<span style="color:var(--success,#28a745);">✅ Yes</span>' : '<span style="color:var(--text-muted,#888);">—</span>'}</td>
                <td style="padding:7px 8px; text-align:center;">${r.risk_max}</td>
                <td style="padding:7px 8px; font-size:0.82em; color:var(--text-muted,#888);">${_escape(r.note || '')}</td>
                <td style="padding:7px 8px; white-space:nowrap;">
                    <button onclick="toggleRuleAuto(${r.id}, ${r.auto_execute ? 0 : 1})" style="background:transparent;border:1px solid var(--border,#444);color:var(--text-main,#ccc);border-radius:3px;padding:3px 8px;cursor:pointer;font-size:0.8em;">${r.auto_execute ? 'Disable' : 'Enable'} auto</button>
                    <button onclick="deleteAllowedCmd(${r.id})" style="background:transparent;border:1px solid var(--error,#dc3545);color:var(--error,#dc3545);border-radius:3px;padding:3px 8px;cursor:pointer;font-size:0.8em;margin-left:4px;">${t('rule_delete_btn')}</button>
                </td>
            </tr>`).join('');
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="6" style="color:var(--error,#dc3545);padding:12px;">${t('rules_load_error', {msg: _escape(String(e))})}</td></tr>`;
    }
}

async function addAllowedCmd() {
    const pattern = document.getElementById('new-ac-pattern').value.trim();
    const desc = document.getElementById('new-ac-desc').value.trim();
    const autoExec = document.getElementById('new-ac-auto').checked;
    const riskMax = parseInt(document.getElementById('new-ac-risk').value) || 30;
    const note = document.getElementById('new-ac-note').value.trim();
    if (!pattern) { alert('Pattern is required.'); return; }
    try {
        const res = await fetch('/api/v1/allowed-commands', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pattern, description: desc, auto_execute: autoExec, risk_max: riskMax, note }),
        });
        const d = await res.json();
        if (d.status === 'ok') {
            document.getElementById('new-ac-pattern').value = '';
            document.getElementById('new-ac-desc').value = '';
            document.getElementById('new-ac-note').value = '';
            document.getElementById('new-ac-auto').checked = false;
            document.getElementById('new-ac-risk').value = '30';
            loadAllowedCmds();
        } else {
            alert(d.reply || 'Failed to add rule.');
        }
    } catch (e) { alert('Network error: ' + e); }
}

async function deleteAllowedCmd(id) {
    if (!confirm(t('confirm_delete_rule'))) return;
    try {
        const res = await fetch(`/api/v1/allowed-commands/${id}`, { method: 'DELETE' });
        const d = await res.json();
        if (d.status === 'ok') loadAllowedCmds();
    } catch (e) { alert('Network error: ' + e); }
}

async function toggleRuleAuto(id, newVal) {
    try {
        const res = await fetch(`/api/v1/allowed-commands/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ auto_execute: !!newVal }),
        });
        const d = await res.json();
        if (d.status === 'ok') loadAllowedCmds();
    } catch (e) { alert('Network error: ' + e); }
}

let clientRefreshInterval = null;

function openClientModal() {
    document.getElementById('client-modal').style.display = 'flex';
    loadClientList(false);
    if (clientRefreshInterval) clearInterval(clientRefreshInterval);
    clientRefreshInterval = setInterval(() => loadClientList(true), 5000);
}

function closeClientModal() {
    document.getElementById('client-modal').style.display = 'none';
    if (clientRefreshInterval) clearInterval(clientRefreshInterval);
}

async function loadClientList(isAutoRefresh = false) {
    const tbody = document.getElementById('client-table-body');
    if (!isAutoRefresh) tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:20px; color:#666;"><i class="fa-solid fa-spinner fa-spin"></i> ${t('checking_clients')}</td></tr>`;
    
    try {
        const res = await fetch('/api/metrics');
        const data = await res.json();
        const clients = data.system?.active_clients || [];
        
        if(clients.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:20px; color:#666;">${t('no_clients')}</td></tr>`;
            return;
        }
        
        let newHtml = '';
        clients.forEach(c => {
            const isMobile = c.user.includes(" (Mobil)");
            const cleanClientUser = c.user.replace(" (Mobil)", "").trim();
            const deviceIcon = isMobile
                ? `<i class="fa-solid fa-mobile-screen-button" title="${t('mobile_device')}" style="margin-right:6px;"></i>`
                : `<i class="fa-solid fa-desktop" title="${t('desktop_device')}" style="margin-right:6px;"></i>`;
            const isLocal = c.ip && (c.ip.startsWith('192.168.') || c.ip.startsWith('10.') || c.ip.startsWith('172.') || c.ip === '127.0.0.1');
            const ipLabel = isLocal ? `${c.ip} <span style="color:var(--text-muted);font-size:.78em;">(lokální síť)</span>` : `<span style="font-family:monospace;">${c.ip}</span>`;

            let chatIconHtml = "";
            if (c.device_id !== window.currentClientIP) {
                chatIconHtml = `<i class="fa-solid fa-comments" style="color:var(--accent); cursor:pointer; margin-right:10px; font-size:1.25em; transition: 0.2s;" onmouseover="this.style.opacity='0.7'" onmouseout="this.style.opacity='1'" title="${t('direct_chat_device')}" onclick="closeClientModal(); openDirectChat('${cleanClientUser}', '${c.device_id}')"></i>`;
            }

            newHtml += `
                <tr style="border-bottom:1px solid var(--border);">
                    <td style="padding:10px; font-weight:bold; color:var(--accent);">${deviceIcon} ${cleanClientUser}</td>
                    <td style="padding:10px; color:#aaa; font-size:.88em;">${ipLabel}</td>
                    <td style="padding:10px; color:#aaa; font-size:.85em;">
                        ${c.connected_since}<br>
                        <small style="color:#666;">${t('last_ping', {time: c.last_seen})}</small>
                    </td>
                    <td style="padding:10px; text-align:center; display:flex; align-items:center; justify-content:center; gap:4px; height:60px; border-bottom:none;">
                        ${chatIconHtml}
                        <span style="color:var(--success); font-weight:bold;">● ONLINE</span>
                    </td>
                </tr>
            `;
        });
        tbody.innerHTML = newHtml;

    } catch(e) {
        if (!isAutoRefresh) tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:20px; color:var(--error);">${t('api_comm_error')}</td></tr>`;
    }
}

async function updateClientIndicatorColor() {
    try {
        const res = await fetch('/api/metrics');
        const data = await res.json();
        const count = (data.system?.active_clients || []).length;
        const indEl = document.getElementById('client-status-indicator');
        
        if (indEl) {
            if (count > 0) {
                indEl.className = 'badge badge-client active'; 
                indEl.querySelector('span').innerText = ` ${count}`;
            } else {
                indEl.className = 'badge badge-client'; 
                indEl.querySelector('span').innerText = ' 0';
            }
        }
    } catch (e) {
        console.error("Failed to fetch client counts:", e);
    }
}

setInterval(updateClientIndicatorColor, 5000);
updateClientIndicatorColor();

// 251: Cache pro agent badge — nezatěžovat API při každém tiku pokud se stav nezměnil
let _agentBadgeCache = null, _agentBadgeLastFetch = 0;
async function updateAgentsMgrBadge() {
    const el = document.getElementById('agents-mgr-indicator');
    if (!el) return;
    try {
        const now = Date.now();
        // Fetch jen každých 10s (max), nebo pokud jsou viditelné změny
        if (!_agentBadgeCache || now - _agentBadgeLastFetch > 10000) {
            const res = await fetch('/api/agents/list');
            const data = await res.json();
            if (data.status !== 'ok') return;
            _agentBadgeCache = data.agents || [];
            _agentBadgeLastFetch = now;
        }
        const agents = _agentBadgeCache.filter(a => a.category !== 'hw' && a.category !== 'alert');
        const total = agents.length;
        const online = agents.filter(a => a.status === 'ONLINE').length;
        el.querySelector('span').innerText = ` ${online}/${total}`;
        const monitored = agents.filter(a => !a.ignore_offline);
        const monOnline = monitored.filter(a => a.status === 'ONLINE').length;
        if (total === 0) { el.className = 'badge badge-agents'; }
        else if (monOnline === monitored.length) { el.className = 'badge badge-agents online'; }
        else if (monOnline > 0) { el.className = 'badge badge-agents partial'; }
        else { el.className = 'badge badge-agents offline'; }
    } catch (e) { console.error("Failed to fetch agent counts:", e); }
}

setInterval(updateAgentsMgrBadge, 10000);
updateAgentsMgrBadge();

// ==========================================================================
// P2P CHAT ENGINE (DEVICE-TO-DEVICE)
// ==========================================================================
let currentDirectChatTargetIP = null;
let currentDirectChatTargetName = null;

function openDirectChat(targetUser, targetIP) {
    currentDirectChatTargetName = targetUser.replace(" (Mobil)", "").trim();
    currentDirectChatTargetIP = targetIP;
    
    document.getElementById('direct-chat-target-title').innerText = `${currentDirectChatTargetName} (${targetIP})`;
    document.getElementById('direct-chat-body').innerHTML = `<div style="color:var(--text-muted); text-align:center; font-size:0.8em; padding:5px; border-bottom:1px dashed var(--border); margin-bottom:5px;">${t('p2p_chat_notice')}</div>`;
    document.getElementById('direct-chat-modal').style.display = 'flex';
    setTimeout(() => document.getElementById('direct-chat-input').focus(), 100);
}

function closeDirectChatModal() {
    document.getElementById('direct-chat-modal').style.display = 'none';
    currentDirectChatTargetIP = null;
    currentDirectChatTargetName = null;
}

function sendDirectMessageClick() {
    const inputEl = document.getElementById('direct-chat-input');
    const text = inputEl.value.trim();
    if (!text || !currentDirectChatTargetIP) return;

    socket.emit('send_private_msg', {
        target: currentDirectChatTargetIP,       
        sender: window.currentUsername,          
        sender_ip: window.currentClientIP,       
        message: text
    });

    appendDirectBubble(text, 'user', currentDirectChatTargetName);
    inputEl.value = '';
}

const chatInput = document.getElementById('direct-chat-input');
if (chatInput) {
    chatInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendDirectMessageClick();
    });
}

function appendDirectBubble(text, sender, senderName) {
    const bodyEl = document.getElementById('direct-chat-body');
    if (!bodyEl) return;
    
    const div = document.createElement('div');
    div.style.maxWidth = '85%';
    div.style.padding = '8px 12px';
    div.style.borderRadius = '6px';
    div.style.fontSize = '0.9em';
    div.style.lineHeight = '1.4';
    div.style.wordBreak = 'break-word';
    div.style.marginBottom = '8px';
    
    if (sender === 'user') {
        div.style.alignSelf = 'flex-end';
        div.style.background = 'var(--msg-user)';
        div.style.color = 'var(--msg-user-text)';
        div.style.borderBottomRightRadius = '2px';
    } else {
        div.style.alignSelf = 'flex-start';
        div.style.background = 'var(--card-bg)';
        div.style.border = '1px solid var(--border)';
        div.style.color = 'var(--text-main)';
        div.style.borderBottomLeftRadius = '2px';
        div.innerHTML = `<small style="display:block; font-size:0.7em; color:var(--text-muted); margin-bottom:4px;">${senderName}</small>`;
    }
    
    div.appendChild(document.createTextNode(text));
    bodyEl.appendChild(div);
    setTimeout(() => { bodyEl.scrollTop = bodyEl.scrollHeight; }, 50);
}

socket.on('receive_private_msg', (data) => {
    if (!currentDirectChatTargetIP || currentDirectChatTargetIP !== data.sender_ip) {
        openDirectChat(data.sender, data.sender_ip);
        try {
            const audio = new Audio("https://actions.google.com/sounds/v1/alarms/beep_short.ogg");
            audio.volume = 1.0;
            audio.play().catch(() => {});
        } catch(e) {}
    }
    appendDirectBubble(data.message, 'bot', data.sender);
});

let _rootAuditData = [];

function _fmtDuration(startStr, endStr) {
    try {
        const start = new Date(startStr).getTime();
        const end = endStr ? new Date(endStr).getTime() : Date.now();
        const secs = Math.round((end - start) / 1000);
        if (secs < 0) return '—';
        if (secs < 60) return `${secs}s`;
        if (secs < 3600) return `${Math.floor(secs/60)}m ${secs%60}s`;
        return `${Math.floor(secs/3600)}h ${Math.floor((secs%3600)/60)}m`;
    } catch { return '—'; }
}

function openRootAudit() {
    const modal = document.getElementById('root-audit-modal');
    if (modal) modal.style.display = 'flex';

    const tbody  = document.getElementById('root-audit-tbody');
    const emptyEl = document.getElementById('root-audit-empty');
    const activeOnly = document.getElementById('root-active-only')?.checked || false;

    if (!_rootAuditData.length) {
        tbody.innerHTML = `<tr><td colspan="6" style="padding:30px; text-align:center; color:#666;"><i class="fa-solid fa-spinner fa-spin"></i></td></tr>`;
    }

    fetch('/api/root_audit')
        .then(r => r.json())
        .then(data => {
            _rootAuditData = data || [];
            _renderRootAudit(activeOnly);
        })
        .catch(err => {
            console.error(t('root_audit_load_error'), err);
            tbody.innerHTML = `<tr><td colspan="6" style="padding:20px; text-align:center; color:var(--error);"><i class="fa-solid fa-circle-exclamation"></i> ${t('load_error')}</td></tr>`;
        });
}

function _renderRootAudit(activeOnly) {
    const tbody   = document.getElementById('root-audit-tbody');
    const emptyEl = document.getElementById('root-audit-empty');
    const statsEl = document.getElementById('root-audit-stats');

    const data = activeOnly ? _rootAuditData.filter(r => r.is_active) : _rootAuditData;
    const activeCount = _rootAuditData.filter(r => r.is_active).length;
    if (statsEl) statsEl.textContent = t('root_audit_stats', {active: activeCount, total: _rootAuditData.length});

    if (!data.length) {
        tbody.innerHTML = '';
        if (emptyEl) emptyEl.style.display = 'block';
        return;
    }
    if (emptyEl) emptyEl.style.display = 'none';

    tbody.innerHTML = data.map(r => {
        const activeBg = r.is_active ? 'background:rgba(255,193,7,0.05);' : '';
        const statusBadge = r.is_active
            ? `<span style="display:inline-flex;align-items:center;gap:5px;background:rgba(255,193,7,0.15);color:#ffc107;font-weight:bold;padding:3px 8px;border-radius:4px;border:1px solid rgba(255,193,7,0.4);font-size:0.85em;"><i class="fa-solid fa-plug"></i> ${t('root_active_badge')}</span>`
            : `<span style="display:inline-flex;align-items:center;gap:5px;color:var(--offline);font-size:0.85em;"><i class="fa-solid fa-power-off"></i> ${t('disconnected')}</span>`;
        const duration = _fmtDuration(r.connected_at, r.disconnected_at);
        return `
            <tr style="border-bottom:1px solid var(--border); ${activeBg}">
                <td style="padding:10px 14px; font-weight:bold; color:var(--text-main);">${_escape(r.server)}</td>
                <td style="padding:10px 14px; font-family:monospace; color:var(--text-muted);">root</td>
                <td style="padding:10px 14px; font-family:monospace; color:#aaa; font-size:0.9em;">${_escape(r.ip)}</td>
                <td style="padding:10px 14px; font-size:0.85em; color:var(--text-muted);">${new Date(r.connected_at).toLocaleString()}</td>
                <td style="padding:10px 14px;">${statusBadge}</td>
                <td style="padding:10px 14px; font-size:0.85em; color:${r.is_active ? 'var(--warning)' : 'var(--text-muted)'}; font-family:monospace;">${duration}</td>
            </tr>`;
    }).join('');
}

function exportRootAuditCSV() {
    if (!_rootAuditData.length) return;
    const cols = ['server','ip','connected_at','disconnected_at','is_active','duration'];
    const rows = [cols.join(',')].concat(_rootAuditData.map(r => [
        r.server, r.ip, r.connected_at || '', r.disconnected_at || '',
        r.is_active ? '1' : '0',
        _fmtDuration(r.connected_at, r.disconnected_at)
    ].map(v => `"${String(v).replace(/"/g,'""')}"`).join(',')));
    const blob = new Blob([rows.join('\n')], {type: 'text/csv'});
    const a = Object.assign(document.createElement('a'), {href: URL.createObjectURL(blob), download: 'root_audit.csv'});
    a.click(); URL.revokeObjectURL(a.href);
}

function closeRootAudit() {
    const modal = document.getElementById('root-audit-modal');
    if (modal) modal.style.display = 'none';
}

function closeRootAuditOutside(event) {
    const modal = document.getElementById('root-audit-modal');
    if (event.target === modal) {
        closeRootAudit();
    }
}


// ── Issue Dependencies Modal ──────────────────────────────────────────────
let _depCurrentKey = null;

function _openDependsModal(kb64) {
    _depCurrentKey = kb64;
    const modal = document.getElementById('depends-modal');
    if (!modal) return;
    document.getElementById('depends-current').innerHTML = '<span style="color:var(--text-muted);font-size:0.85em;">Načítám…</span>';
    document.getElementById('depends-blocked-by').innerHTML = '';
    document.getElementById('depends-add-msg').textContent = '';
    document.getElementById('depends-add-input').value = '';
    modal.style.display = 'flex';

    const isAdmin = window.currentRole === 'admin' || window.currentRole === 'superadmin';
    document.getElementById('depends-add-section').style.display = isAdmin ? 'block' : 'none';

    fetch(`/api/issues/${kb64}/depends`)
        .then(r => r.json())
        .then(data => {
            const deps = data.depends_on || [];
            let html = `<div style="font-size:0.85em; color:var(--text-muted); margin-bottom:6px; font-weight:600;">Závisí na (${deps.length}):</div>`;
            if (!deps.length) {
                html += '<div style="font-size:0.85em; color:var(--text-muted);">— žádné závislosti</div>';
            } else {
                html += deps.map(d => `
                    <div style="display:flex; align-items:center; justify-content:space-between; padding:6px 10px; background:rgba(253,126,20,.08); border:1px solid rgba(253,126,20,.25); border-radius:6px; margin-bottom:4px;">
                        <div>
                            <span style="font-size:0.88em; color:var(--text-main); font-weight:600;">${d.host || '?'}</span>
                            <span style="font-size:0.8em; color:var(--text-muted); margin-left:8px;">${(d.last_line||'').substring(0,60)}</span>
                            <span style="font-size:0.75em; background:${d.status==='resolved'?'rgba(40,167,69,.2)':'rgba(220,53,69,.2)'}; color:${d.status==='resolved'?'#28a745':'#dc3545'}; border-radius:8px; padding:1px 6px; margin-left:6px;">${d.status||'?'}</span>
                        </div>
                        ${isAdmin ? `<button onclick="_depRemove('${d.key_b64}')" style="background:none; border:none; color:var(--error); cursor:pointer; font-size:1em; padding:2px 6px;" title="Odebrat"><i class="fa-solid fa-xmark"></i></button>` : ''}
                    </div>`).join('');
            }
            document.getElementById('depends-current').innerHTML = html;
        })
        .catch(() => {
            document.getElementById('depends-current').innerHTML = '<span style="color:var(--error);">Chyba načítání</span>';
        });

    fetch(`/api/issues/${kb64}/blocked_by`)
        .then(r => r.json())
        .then(data => {
            const bl = data.blocked_by || [];
            if (!bl.length) { document.getElementById('depends-blocked-by').innerHTML = ''; return; }
            let html = `<div style="font-size:0.85em; color:var(--text-muted); margin-bottom:6px; font-weight:600;">Blokuje (${bl.length}):</div>`;
            html += bl.map(d => `
                <div style="padding:6px 10px; background:rgba(220,53,69,.07); border:1px solid rgba(220,53,69,.2); border-radius:6px; margin-bottom:4px; font-size:0.85em;">
                    <b>${d.host||'?'}</b>: <span style="color:var(--text-muted);">${(d.last_line||'').substring(0,60)}</span>
                </div>`).join('');
            document.getElementById('depends-blocked-by').innerHTML = html;
        })
        .catch(() => {});
}

function closeDependsModal() {
    const modal = document.getElementById('depends-modal');
    if (modal) modal.style.display = 'none';
    _depCurrentKey = null;
}

function _depAdd() {
    const inp = document.getElementById('depends-add-input');
    const msg = document.getElementById('depends-add-msg');
    const val = (inp.value || '').trim();
    if (!val || !_depCurrentKey) return;
    msg.textContent = 'Přidávám…';
    msg.style.color = 'var(--text-muted)';
    fetch(`/api/issues/${_depCurrentKey}/depends`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({depends_on_key: val})
    }).then(r => r.json()).then(data => {
        if (data.status === 'ok') {
            msg.textContent = 'Přidáno.';
            msg.style.color = 'var(--success, #28a745)';
            inp.value = '';
            _openDependsModal(_depCurrentKey);
        } else {
            msg.textContent = data.error || 'Chyba';
            msg.style.color = 'var(--error)';
        }
    }).catch(() => { msg.textContent = 'Síťová chyba'; msg.style.color = 'var(--error)'; });
}

function _depRemove(depKeyB64) {
    if (!_depCurrentKey) return;
    fetch(`/api/issues/${_depCurrentKey}/depends`, {
        method: 'DELETE',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({depends_on_key: depKeyB64})
    }).then(r => r.json()).then(data => {
        if (data.status === 'ok') _openDependsModal(_depCurrentKey);
    }).catch(() => {});
}

// ── Toast helper ─────────────────────────────────────────────────────────
// 393: Toast queue — max 3 visible, stack
const _toastStack = [];
function _showToast(msg, type) {
    // Remove oldest if already 3 visible
    while (_toastStack.length >= 3) {
        const old = _toastStack.shift();
        old?.remove();
    }
    const colors = {success:'rgba(16,124,16,.92)', error:'rgba(197,15,31,.92)', info:'rgba(0,100,180,.92)', warning:'rgba(180,100,0,.92)'};
    const borders = {success:'#2a9d2a', error:'#c50f1f', info:'#0064b4', warning:'#b46400'};
    const t = document.createElement('div');
    t.style.cssText = `position:fixed;right:20px;z-index:99999;padding:9px 16px;border-radius:6px;font-size:.87em;max-width:320px;box-shadow:0 4px 14px rgba(0,0,0,.4);transition:opacity .3s;pointer-events:none;background:${colors[type]||colors.info};color:#fff;border:1px solid ${borders[type]||borders.info};`;
    t.textContent = msg;
    // Stack from bottom
    const bottom = 20 + _toastStack.length * 52;
    t.style.bottom = bottom + 'px';
    document.body.appendChild(t);
    _toastStack.push(t);
    setTimeout(() => {
        t.style.opacity = '0';
        setTimeout(() => {
            t.remove();
            const idx = _toastStack.indexOf(t);
            if (idx >= 0) _toastStack.splice(idx, 1);
        }, 350);
    }, 3200);
}

// ── False Positive (057) ──────────────────────────────────────────────────
async function _markFalsePositive(kb64) {
    if (!confirm('Označit jako false positive? Podobné budoucí issues budou automaticky potlačeny.')) return;
    try {
        const r = await fetch(`/api/issues/${kb64}/false_positive`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({})});
        const d = await r.json();
        if (d.status === 'ok') {
            _showToast(`✓ FP přidán: ${d.plugin} / ${(d.msg_pattern||'').substring(0,50)}`, 'success');
        } else {
            _showToast(d.error || 'Chyba', 'error');
        }
    } catch(e) { _showToast('Síťová chyba', 'error'); }
}

async function _fpLoadList() {
    const el = document.getElementById('fp-list-body');
    if (!el) return;
    el.innerHTML = '<div style="color:var(--text-muted);font-size:.83em;padding:10px;"><i class="fa-solid fa-spinner fa-spin"></i> Načítám…</div>';
    try {
        const r = await fetch('/api/false_positives');
        const d = await r.json();
        const patterns = d.patterns || [];
        if (!patterns.length) { el.innerHTML = '<div style="color:var(--text-muted);font-size:.83em;padding:10px;">Žádné FP vzory.</div>'; return; }
        el.innerHTML = patterns.map(p => `
            <div style="display:flex; align-items:flex-start; gap:8px; padding:7px 10px; border-bottom:1px solid rgba(255,255,255,.04); font-size:.83em;">
                <div style="flex:1; min-width:0;">
                    <div><span style="background:rgba(253,126,20,.15); color:#fd7e14; border-radius:3px; padding:1px 5px; font-size:.85em;">${_escape(p.plugin_name)}</span>
                    <span style="color:var(--text-muted); font-size:.8em; margin-left:6px;">host: <code>${_escape(p.host_pattern)}</code></span>
                    <span style="color:var(--text-muted); font-size:.75em; margin-left:8px;">${p.hit_count} potlačení</span></div>
                    <div style="color:var(--text-muted); font-size:.8em; margin-top:2px; word-break:break-all;"><code>${_escape((p.msg_pattern||'').substring(0,100))}</code></div>
                    <div style="color:#555; font-size:.75em; margin-top:2px;">${p.created_by} • ${(p.created_at||'').substring(0,16)}</div>
                </div>
                <button onclick="_fpDelete(${p.id})" style="background:none;border:none;color:var(--error);cursor:pointer;font-size:1em;padding:4px;" title="Smazat"><i class="fa-solid fa-trash"></i></button>
            </div>`).join('');
    } catch(e) { el.innerHTML = `<div style="color:var(--error);font-size:.83em;padding:10px;">Chyba: ${e}</div>`; }
}

async function _fpDelete(id) {
    if (!confirm('Smazat FP vzor?')) return;
    await fetch(`/api/false_positives/${id}`, {method: 'DELETE'});
    _fpLoadList();
}

// ── Similar Incidents (059) ───────────────────────────────────────────────
async function _openSimilarModal(kb64) {
    let modal = document.getElementById('similar-modal');
    if (!modal) return;
    modal.style.display = 'flex';
    const body = document.getElementById('similar-body');
    body.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i> Hledám podobné incidenty…</div>';
    try {
        const r = await fetch(`/api/issues/${kb64}/similar`);
        const d = await r.json();
        const items = d.similar || [];
        if (!items.length) {
            body.innerHTML = '<div style="color:var(--text-muted);padding:16px;font-size:.87em;">Žádné podobné historické incidenty nenalezeny.</div>';
            return;
        }
        body.innerHTML = items.map(s => `
            <div style="padding:8px 12px; border-bottom:1px solid rgba(255,255,255,.05); display:flex; align-items:flex-start; gap:10px;">
                <div style="flex-shrink:0; width:42px; text-align:center; padding-top:2px;">
                    <div style="font-size:1em; font-weight:700; color:${s.similarity>0.6?'var(--accent)':s.similarity>0.4?'#fd7e14':'var(--text-muted)'};">${Math.round(s.similarity*100)}%</div>
                    <div style="font-size:.65em; color:var(--text-muted);">shoda</div>
                </div>
                <div style="flex:1; min-width:0;">
                    <div style="font-size:.85em;"><b>${_escape(s.host||'?')}</b> <span style="color:var(--text-muted);font-size:.85em;">${_escape(s.plugin_name||'')}</span></div>
                    <div style="font-size:.8em; color:var(--text-muted); word-break:break-word;">${_escape(s.last_line||'')}</div>
                    <div style="font-size:.72em; color:#555; margin-top:2px;">Vyřešeno: ${(s.resolved_at||'').substring(0,16)}</div>
                </div>
            </div>`).join('');
    } catch(e) {
        body.innerHTML = `<div style="color:var(--error);padding:12px;">Chyba: ${e}</div>`;
    }
}

function _closeSimilarModal() {
    const m = document.getElementById('similar-modal');
    if (m) m.style.display = 'none';
}

// ---- Notify Settings Modal ----
function openNotifySettingsModal() {
    document.getElementById('notify-settings-modal').style.display = 'flex';
    _loadNotifySettingsBody();
}

function closeNotifySettingsModal() {
    document.getElementById('notify-settings-modal').style.display = 'none';
}

async function _syncChannelNotifyBtn(channel) {
    const btn = document.getElementById('channel-notify-btn');
    if (!btn || !channel) return;
    try {
        const r = await fetch('/api/channels/notify');
        const d = await r.json();
        const on = d[channel] !== false;
        btn.title = `Notifikace ${on ? 'ZAPNUTY' : 'VYPNUTY'} — otevřít nastavení`;
        btn.style.color = on ? 'var(--accent)' : 'var(--text-muted)';
        btn.style.borderColor = on ? 'var(--accent)' : 'var(--border)';
        btn.innerHTML = `<i class="fa-solid ${on ? 'fa-bell' : 'fa-bell-slash'}"></i>`;
    } catch(e) { /* ignore */ }
}

async function _loadNotifySettingsBody() {
    const body = document.getElementById('notify-settings-body');
    if (!body) return;
    body.innerHTML = '<div style="text-align:center;color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i></div>';
    try {
        const r = await fetch('/api/channels/notify');
        const d = await r.json();
        const intg = d._integrations || {};

        const chLabels = {infra:'Infrastruktura', agent:'Agenti', security:'Security', root:'Root'};
        const intLabels = {mqtt:'MQTT', homeassistant:'Home Assistant', teams:'MS Teams', webhook:'Webhook', slack:'Slack', pagerduty:'PagerDuty'};
        const intIcons  = {mqtt:'fa-network-wired', homeassistant:'fa-house-signal', teams:'fa-brands fa-microsoft', webhook:'fa-webhook', slack:'fa-brands fa-slack', pagerduty:'fa-pager'};

        const isAdmin = window.currentRole === 'admin' || window.currentRole === 'superadmin';

        const togRow = (label, icon, on, clickFn) => {
            const btnStyle = `padding:3px 10px;border-radius:12px;border:1px solid ${on?'var(--accent)':'var(--border)'};background:${on?'rgba(77,166,255,.15)':'transparent'};color:${on?'var(--accent)':'var(--text-muted)'};cursor:${isAdmin?'pointer':'default'};font-size:.78em;font-weight:600;min-width:52px;`;
            const btn = isAdmin
                ? `<button onclick="${clickFn}" style="${btnStyle}">${on?'ON':'OFF'}</button>`
                : `<span style="${btnStyle}display:inline-block;text-align:center;">${on?'ON':'OFF'}</span>`;
            return `<div style="display:flex;align-items:center;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--border);">
                <span style="font-size:.86em;display:flex;align-items:center;gap:7px;">
                    <i class="fa-solid ${icon}" style="width:14px;color:var(--text-muted);opacity:.7;"></i>${label}
                </span>${btn}</div>`;
        };

        let chRows = '';
        for (const [ch, label] of Object.entries(chLabels)) {
            chRows += togRow(label, 'fa-layer-group', d[ch] !== false, `_toggleChNotify('${ch}')`);
        }
        let intRows = '';
        for (const [k, label] of Object.entries(intLabels)) {
            intRows += togRow(label, intIcons[k], !!intg[k], `_toggleIntegNotify('${k}')`);
        }

        body.innerHTML = `
            <div style="font-size:.7rem;text-transform:uppercase;letter-spacing:.07em;color:var(--accent);margin-bottom:6px;font-weight:700;">Kanály — přijímat notifikace</div>
            ${chRows}
            <div style="font-size:.7rem;text-transform:uppercase;letter-spacing:.07em;color:var(--accent);margin:14px 0 6px;font-weight:700;">Integrace — odesílat přes</div>
            ${intRows}`;
    } catch(e) {
        body.innerHTML = `<span style="color:var(--error);">Chyba: ${e}</span>`;
    }
}

async function _toggleChNotify(channel) {
    await fetch(`/api/channels/${channel}/notify/toggle`, {method:'POST'});
    _loadNotifySettingsBody();
    _syncChannelNotifyBtn(currentOpenChannel);
}

async function _toggleIntegNotify(name) {
    await fetch(`/api/integrations/${name}/toggle`, {method:'POST'});
    _loadNotifySettingsBody();
}

// 131: Inline komentáře v issue kartách
function _icToggle(kb64) {
    const el = document.getElementById(`ic-${kb64}`);
    if (!el) return;
    const visible = el.style.display !== 'none';
    el.style.display = visible ? 'none' : '';
    if (!visible) setTimeout(() => document.getElementById(`ic-inp-${kb64}`)?.focus(), 50);
}
function _icHide(kb64) {
    const el = document.getElementById(`ic-${kb64}`);
    if (el) el.style.display = 'none';
}
async function _icSubmit(kb64) {
    const inp = document.getElementById(`ic-inp-${kb64}`);
    const msg = document.getElementById(`ic-msg-${kb64}`);
    if (!inp) return;
    const text = inp.value.trim();
    if (!text) return;
    try {
        const r = await fetch(`/api/issues/${kb64}/comments`, {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text})
        });
        const d = await r.json();
        if (d.status === 'ok') {
            inp.value = '';
            if (msg) { msg.style.color = 'var(--success)'; msg.textContent = '✓ Komentář přidán'; setTimeout(() => { if(msg) msg.textContent=''; _icHide(kb64); }, 1500); }
        } else {
            if (msg) { msg.style.color = 'var(--error)'; msg.textContent = d.error || 'Chyba'; }
        }
    } catch(e) {
        if (msg) { msg.style.color = 'var(--error)'; msg.textContent = String(e); }
    }
}

// 136: Barevné štítky issues
function _lcToggle(kb64) {
    const el = document.getElementById(`lc-picker-${kb64}`);
    if (!el) return;
    // Zavři všechny ostatní pickery
    document.querySelectorAll('[id^="lc-picker-"]').forEach(p => { if (p.id !== `lc-picker-${kb64}`) p.style.display = 'none'; });
    const vis = el.style.display === 'flex';
    el.style.display = vis ? 'none' : 'flex';
}
async function _lcSet(kb64, color) {
    const el = document.getElementById(`lc-picker-${kb64}`);
    if (el) el.style.display = 'none';
    try {
        await fetch(`/api/issues/${kb64}/label_color`, {
            method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({color})
        });
        refreshModalIssuesContent(false);
    } catch(e) { console.error('label_color:', e); }
}
// Zavři picker kliknutím mimo
document.addEventListener('click', e => {
    if (!e.target.closest('[id^="lc-picker-"]') && !e.target.closest('[id^="lc-dot-"]')) {
        document.querySelectorAll('[id^="lc-picker-"]').forEach(p => p.style.display = 'none');
    }
});
