// 231: CSRF — globální fetch wrapper přidá X-CSRF-Token ke všem state-changing requestům
(function() {
    function _getCsrfToken() {
        const m = document.querySelector('meta[name="csrf-token"]');
        if (m && m.content) return m.content;
        const c = document.cookie.split(';').find(s => s.trim().startsWith('csrf_token='));
        return c ? c.trim().split('=')[1] : '';
    }
    const _origFetch = window.fetch;
    window.fetch = function(url, opts = {}) {
        const method = (opts.method || 'GET').toUpperCase();
        if (['POST','PUT','DELETE','PATCH'].includes(method)) {
            const token = _getCsrfToken();
            if (token) {
                opts.headers = Object.assign({'X-CSRF-Token': token}, opts.headers || {});
            }
        }
        return _origFetch(url, opts);
    };
})();

console.time('[Sentinel] socket-connect');
const socket = io({
    transports: ['polling', 'websocket'],
    upgrade: true,
    reconnection: true,
    reconnectionAttempts: 15,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 15000,
    randomizationFactor: 0.3,
    timeout: 10000,
});

// --- MODAL Z-INDEX MANAGER ---
// Každý nový modal dostane vyšší z-index → vždy v popředí
let _modalZBase = 1000;
const _modalZSet = new WeakMap(); // el → poslední z-index který jsme nastavili (prevence smyčky)

(function _patchModalZIndex() {
    const obs = new MutationObserver(mutations => {
        mutations.forEach(m => {
            if (m.type !== 'attributes' || m.attributeName !== 'style') return;
            const el = m.target;
            if (!el.classList.contains('modal-overlay')) return;
            if (el.style.display !== 'flex') return;
            const currentZ = parseInt(el.style.zIndex) || 0;
            // Pokud jsme tento z-index nastavili sami, ignoruj (prevence nekonečné smyčky)
            if (_modalZSet.get(el) === currentZ) return;
            _modalZBase += 10;
            _modalZSet.set(el, _modalZBase);
            el.style.zIndex = _modalZBase;
        });
    });
    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('.modal-overlay').forEach(el => {
            obs.observe(el, {attributes: true, attributeFilter: ['style']});
        });
    });
})();

// --- GLOBAL STATE ---
// 010: Channel colors (loaded from server, fallback defaults)
window._channelColors = {
    SECURITY: '#dc3545', INFRA: '#17a2b8', ICINGA: '#17a2b8',
    ROOT: '#ffc107', LOGIN: '#6f42c1', AGENT: '#0078d4'
};
fetch('/api/channel-colors').then(r=>r.json()).then(d=>{
    if (d.colors) Object.assign(window._channelColors, d.colors);
}).catch(()=>{});
function _chColor(channel) {
    return window._channelColors[(channel||'').toUpperCase()] || '#aaa';
}

let notificationsEnabled = false;
let lastIssueCount = -1;
let activeNotification = null; 
let titleInterval = null;
let originalTitle = document.title;

const chatHistory = document.getElementById('chat-history');
const input = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const timerDisplay = document.getElementById('request-timer');

let currentActionId = null;
let isProcessing = false;
let timerInterval = null;

let chartInstance = null;
window.predictionData = {}; 

// Agent Management state
let agentRefreshInterval = null;

// ── Modal Breadcrumb System ──────────────────────────────────────────────────
let _breadcrumbStack = [];

function _pushBreadcrumb(modalId, parentLabel, backFn) {
    const overlay = document.getElementById(modalId);
    if (!overlay) return;
    const modal = overlay.querySelector('.modal');
    if (!modal) return;
    // Remove any existing breadcrumb in this modal
    modal.querySelectorAll('.modal-breadcrumb').forEach(el => el.remove());
    _breadcrumbStack = _breadcrumbStack.filter(b => b.modalId !== modalId);
    _breadcrumbStack.push({modalId, parentLabel, backFn});
    const bc = document.createElement('div');
    bc.className = 'modal-breadcrumb';
    bc.style.cssText = 'padding:5px 14px; background:rgba(0,0,0,.15); font-size:.78em; color:var(--text-muted); cursor:pointer; border-bottom:1px solid var(--border); display:flex; align-items:center; user-select:none;';
    bc.innerHTML = `<i class="fa-solid fa-chevron-left" style="margin-right:6px; font-size:.85em;"></i>${parentLabel}`;
    bc.onclick = () => {
        overlay.style.display = 'none';
        modal.querySelectorAll('.modal-breadcrumb').forEach(el => el.remove());
        _breadcrumbStack = _breadcrumbStack.filter(b => b.modalId !== modalId);
        backFn();
    };
    modal.insertBefore(bc, modal.firstChild);
}

function _clearBreadcrumb(modalId) {
    const overlay = document.getElementById(modalId);
    if (overlay) overlay.querySelector('.modal')?.querySelectorAll('.modal-breadcrumb').forEach(el => el.remove());
    _breadcrumbStack = _breadcrumbStack.filter(b => b.modalId !== modalId);
}

// Hoisted — used before their original declaration sites
let _showSnoozed = false;
let _commentsKey = null;
let _bulkMode = false;
const _bulkSelected = new Set();
let _liveTailES = null;

window.onload = () => {
    printWelcomeMessage();
    // 001: Sync theme from server (overrides localStorage if server has different value)
    fetch('/api/user/theme').then(r=>r.json()).then(d=>{
        if (d.theme) {
            const serverLight = d.theme === 'light';
            const localLight = document.body.classList.contains('light-mode');
            if (serverLight !== localLight) {
                document.body.classList.toggle('light-mode', serverLight);
                localStorage.setItem('sentinel-theme', d.theme);
            }
        }
    }).catch(()=>{});
    
    const savedState = localStorage.getItem('sentinel_notifications');
    if (savedState === 'true') {
        if ("Notification" in window && Notification.permission === "granted") {
            notificationsEnabled = true;
            updateNotificationIconUI(true);
            console.log("Notifications restored: ON");
        } else {
            localStorage.setItem('sentinel_notifications', 'false');
            console.log("Notifications restored: OFF (Missing permission)");
        }
    }
    // 262: Zobraz co je nové od posledního přihlášení
    _checkChangesSinceLogin();
    // 270: Obnov zvukový stav
    const soundBtn = document.getElementById('alert-sound-btn');
    if (soundBtn && _alertSoundEnabled) {
        soundBtn.style.color = 'var(--accent)';
        soundBtn.title = 'Zvuk alertu zapnut';
        soundBtn.className = soundBtn.className.replace('fa-volume-xmark', 'fa-volume-high');
    }
};

async function _checkChangesSinceLogin() {
    try {
        const r = await fetch('/api/analytics/changes_since_login');
        const d = await r.json();
        if (!d.since) return;
        const total = (d.new_count || 0) + (d.resolved_count || 0);
        if (total === 0) return;
        const ch = document.getElementById('chat-history');
        if (!ch) return;
        const bubble = document.createElement('div');
        bubble.style.cssText = 'align-self:center;background:rgba(0,120,212,.08);border:1px solid rgba(0,120,212,.25);border-radius:8px;padding:10px 16px;font-size:.82em;color:var(--text-muted);text-align:center;margin:4px 0;max-width:90%;';
        const since = d.since ? new Date(d.since).toLocaleString('cs-CZ') : '';
        bubble.innerHTML = `Od posledního přihlášení (${since}): <b style="color:var(--error)">+${d.new_count} nových</b> · <b style="color:var(--success)">${d.resolved_count} vyřešených</b> issues`;
        ch.appendChild(bubble);
        ch.scrollTop = ch.scrollHeight;
    } catch(e) { /* silent */ }
}

function updateNotificationIconUI(enabled) {
    const btn = document.getElementById('notification-btn');
    if (!btn) return;
    
    if (enabled) {
        btn.className = 'fa-solid fa-bell icon-btn-header';
        btn.title = t('notifications_on_title');
        btn.style.color = "var(--accent)";
    } else {
        btn.className = 'fa-solid fa-bell-slash icon-btn-header';
        btn.title = t('notifications_off_title');
        btn.classList.remove('notification-active');
        btn.style.color = "";
    }
}

// 20: Obohacení dotazu o aktuální stav issues při LIVE prefixu
async function _enrichWithLiveContext(text) {
    const cleanText = text.replace(/^\[?LIVE\]?\s+/i, '').trim();
    try {
        const r = await fetch('/api/v1/issues');
        const d = await r.json();
        const issues = (d.issues || []).slice(0, 30);
        if (!issues.length) return cleanText;
        const summary = issues.map(i =>
            `[${(i.channel_type||'?').toUpperCase()}] ${i.host||'?'} / ${i.plugin_name||'?'}: ${(i.last_line||'').slice(0,100)}`
        ).join('\n');
        return `[LIVE KONTEXT — ${issues.length} aktivních issues]\n${summary}\n\nDotaz: ${cleanText}`;
    } catch(e) {
        return cleanText;
    }
}

function getWelcomeHTML() {
    return `
        <div class="message bot">
            <div style="font-size:1.15em; font-weight:bold; margin-bottom:8px; display:flex; align-items:center; gap:8px;">
                <i class="fa-solid fa-shield-halved" style="color:var(--accent)"></i> Sentinel Commander
            </div>
            <div style="line-height:1.6; color:var(--text-muted); font-size:0.92em;">
                ${t('welcome_intro')}
            </div>
            <div style="margin-top:10px; font-size:.8em; color:var(--text-muted); border-top:1px solid var(--border); padding-top:8px;">
                <div style="margin-bottom:4px; color:var(--accent); font-size:.9em; font-weight:600;">Rychlé příkazy:</div>
                <div style="display:flex;flex-direction:column;gap:3px;">
                    <div>${t('welcome_cmd_status')}</div>
                    <div>${t('welcome_cmd_pending')}</div>
                    <div>${t('welcome_cmd_sys')}</div>
                    <div>${t('welcome_cmd_analyze')}</div>
                    <div style="color:#f59e0b;">${t('welcome_cmd_live')}</div>
                </div>
            </div>
        </div>`;
}

function printWelcomeMessage() {
    const div = document.createElement('div');
    div.innerHTML = getWelcomeHTML();
    chatHistory.appendChild(div);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

function toggleStatus(headerEl) {
    const wrapper = headerEl.closest('.status-wrapper');
    if (wrapper.classList.contains('minimized')) {
        document.querySelectorAll('.status-wrapper:not(.minimized)').forEach(el => {
            if (el !== wrapper) el.classList.add('minimized');
        });
    }
    wrapper.classList.toggle('minimized');
}

async function shareIssue(text, btnElement) {
    const showSuccess = () => {
        const icon = btnElement.querySelector('i');
        const originalClass = icon.className;
        icon.className = 'fa-solid fa-check';
        icon.style.color = '#107c10';
        setTimeout(() => {
            icon.className = originalClass;
            icon.style.color = '';
        }, 1500);
    };

    if (navigator.clipboard && window.isSecureContext) {
        try {
            await navigator.clipboard.writeText(text);
            showSuccess();
            return;
        } catch (err) {
            console.warn('Clipboard API failed, trying fallback...', err);
        }
    }

    // execCommand fallback (deprecated but still works in some contexts)
    try {
        const textArea = document.createElement("textarea");
        textArea.value = text;
        textArea.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0;";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        const successful = document.execCommand('copy');
        document.body.removeChild(textArea);
        if (successful) { showSuccess(); return; }
    } catch (_) {}

    // Last resort: show text in a modal for manual copy
    _showCopyFallbackModal(text);
}

function _showCopyFallbackModal(text) {
    let m = document.getElementById('copy-fallback-modal');
    if (!m) {
        m = document.createElement('div');
        m.id = 'copy-fallback-modal';
        m.style.cssText = 'display:none;position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:9999;align-items:center;justify-content:center;';
        m.innerHTML = `<div style="background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:20px;max-width:560px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.4);">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                <span style="font-weight:bold;color:var(--accent);">Zkopírujte ručně (Ctrl+C)</span>
                <i class="fa-solid fa-times" style="cursor:pointer;color:var(--text-muted);" onclick="document.getElementById('copy-fallback-modal').style.display='none';"></i>
            </div>
            <textarea id="copy-fallback-text" style="width:100%;height:80px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:4px;padding:8px;font-size:0.85em;resize:vertical;" readonly></textarea>
            <div style="text-align:right;margin-top:10px;">
                <button onclick="document.getElementById('copy-fallback-modal').style.display='none';" style="padding:6px 16px;background:transparent;border:1px solid var(--border);color:var(--text-muted);border-radius:4px;cursor:pointer;">Zavřít</button>
            </div>
        </div>`;
        m.addEventListener('click', e => { if (e.target === m) m.style.display = 'none'; });
        document.body.appendChild(m);
    }
    document.getElementById('copy-fallback-text').value = text;
    m.style.display = 'flex';
    setTimeout(() => { const ta = document.getElementById('copy-fallback-text'); ta.focus(); ta.select(); }, 50);
}

async function safeCopyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
        try { await navigator.clipboard.writeText(text); return; } catch (_) {}
    }
    try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0;';
        document.body.appendChild(ta);
        ta.focus(); ta.select();
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        if (ok) return;
    } catch (_) {}
    _showCopyFallbackModal(text);
}

function clearConsole() {
    chatHistory.innerHTML = '';
    printWelcomeMessage();
    console.log("Console cleared.");
}

function startTimer(duration = 600) {
    let timeLeft = duration;
    timerDisplay.style.display = 'inline-block';
    timerDisplay.style.color = '#ffc107';
    timerDisplay.innerText = `${timeLeft}s`;
    
    if (timerInterval) clearInterval(timerInterval);
    
    timerInterval = setInterval(() => {
        timeLeft--;
        timerDisplay.innerText = `${timeLeft}s`;
        if (timeLeft < 30) timerDisplay.style.color = '#ff4444';
        if (timeLeft <= 0) {
            clearInterval(timerInterval);
            timerDisplay.innerText = t('timeout_label');
        }
    }, 1000);
}

function stopTimer() {
    if (timerInterval) clearInterval(timerInterval);
    timerDisplay.style.display = 'none';
}

// --- SOCKETS ---
let _wsWasConnected = false;

// 140: Multi-tab sync — ostatní záložky dostanou status_update i bez vlastního WebSocket eventu
const _bc = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('sentinel_status') : null;
if (_bc) {
    _bc.onmessage = (e) => {
        if (e.data === 'status_update' && typeof updateStatus === 'function') updateStatus();
    };
}

socket.on('connect', () => {
    console.timeEnd('[Sentinel] socket-connect');
    const b = document.getElementById('online-badge');
    b.classList.remove('offline');
    b.innerHTML = `<i class="fa-solid fa-signal"></i> <span>${t('online_status')}</span>`;

    if (window.currentClientIP) {
        socket.emit('join_private', { room_id: window.currentClientIP, user: window.currentUsername });
    }

    if (_wsWasConnected) {
        // Reconnect — refresh all data immediately
        updateStatus();
        // Restart live tail SSE if modal is open but SSE was closed
        const ltModal = document.getElementById('live-tail-modal');
        const ltFile  = document.getElementById('live-tail-fname');
        if (ltModal && ltModal.style.display === 'flex' && ltFile && ltFile.textContent && !_liveTailES) {
            openLiveTail(ltFile.textContent);
        }
    }
    _wsWasConnected = true;
});

socket.on('disconnect', (reason) => {
    const b = document.getElementById('online-badge');
    b.classList.add('offline');
    b.innerHTML = `<i class="fa-solid fa-ban"></i> <span>${t('offline_status')}</span>`;
    // Transport closed by server — Socket.IO will auto-reconnect
});

socket.on('reconnect_attempt', (attempt) => {
    const b = document.getElementById('online-badge');
    b.classList.add('offline');
    b.innerHTML = `<i class="fa-solid fa-rotate fa-spin"></i> <span>Reconnecting ${attempt}/15…</span>`;
});

socket.on('reconnect_failed', () => {
    const b = document.getElementById('online-badge');
    b.classList.add('offline');
    b.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> <span>Spojení ztraceno — <a href="javascript:location.reload()" style="color:var(--accent);">Reload</a></span>`;
});

socket.on('connect_error', (err) => {
    const b = document.getElementById('online-badge');
    if (!socket.connected) {
        b.classList.add('offline');
        b.innerHTML = `<i class="fa-solid fa-ban"></i> <span>${t('offline_status')}</span>`;
    }
});
socket.on('new_alert', (payload) => {
    updateStatus();
    _bc?.postMessage('status_update');
    if (payload && payload.type === 'new_action') {
        const modal = document.getElementById('pending-actions-modal');
        if (modal && modal.style.display === 'flex') loadPendingActions(true);
    }
});

socket.on('issue_resolved', () => {
    updateStatus();
    _bc?.postMessage('status_update');
});

function toggleTheme() {
    const isLight = document.body.classList.toggle('light-mode');
    const val = isLight ? 'light' : 'dark';
    localStorage.setItem('sentinel-theme', val);
    document.documentElement.classList.remove('light-mode-pre');
    // 001: persist to server per-user
    fetch('/api/user/theme', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({theme: val})}).catch(()=>{});
}

(function _applyStoredTheme() {
    if (localStorage.getItem('sentinel-theme') === 'light') {
        document.body.classList.add('light-mode');
    }
    document.documentElement.classList.remove('light-mode-pre');
})();

// 138+24: Převede AI markdown výstup na HTML
function _processCodeBlocks(html) {
    return html.replace(/```(\w*)<br>([\s\S]*?)```/g, (_, lang, code) => {
        const cls = lang ? ` class="language-${lang}"` : '';
        const cleaned = code.replace(/<br\s*\/?>/gi, '\n').replace(/&amp;/g,'&').replace(/&lt;/g,'<').replace(/&gt;/g,'>');
        return `<pre style="margin:6px 0;border-radius:6px;overflow:auto;"><code${cls}>${cleaned.replace(/</g,'&lt;').replace(/>/g,'&gt;')}</code></pre>`;
    });
}

function _mdRender(text) {
    // 24: Render markdown formatting in AI responses
    let h = text;
    // code blocks first (protected from further processing)
    h = _processCodeBlocks(h);
    // headings
    h = h.replace(/(?:^|<br>)(#{1,3}) (.+?)(?=<br>|$)/g, (_, hashes, content) => {
        const lvl = hashes.length;
        const sz = lvl === 1 ? '1.05em' : lvl === 2 ? '.95em' : '.88em';
        return `<br><span style="font-weight:700;font-size:${sz};color:var(--accent);display:block;margin:6px 0 2px;">${content}</span>`;
    });
    // inline code
    h = h.replace(/`([^`]+)`/g, '<code style="background:rgba(255,255,255,.08);padding:1px 5px;border-radius:3px;font-family:monospace;font-size:.88em;">$1</code>');
    // bold
    h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // italic
    h = h.replace(/\*([^*\n]+?)\*/g, '<em>$1</em>');
    // bullet list lines: "- text" or "* text" after <br>
    h = h.replace(/(?:<br>)([-*]) (.+?)(?=<br>|$)/g, '<br><span style="display:inline-block;margin-left:10px;">• $2</span>');
    return h;
}

function appendMessage(text, sender) {
    const div = document.createElement('div');
    div.className = `message ${sender}`;
    div.innerHTML = sender === 'bot' ? _mdRender(text) : text;
    chatHistory.appendChild(div);
    if (sender === 'bot' && typeof hljs !== 'undefined') {
        div.querySelectorAll('pre code').forEach(el => hljs.highlightElement(el));
    }
    requestAnimationFrame(() => { chatHistory.scrollTop = chatHistory.scrollHeight; });
}

// 139: Zkopírovat poslední odpověď AI
async function copyLastReply() {
    const msgs = chatHistory.querySelectorAll('.message.bot');
    if (!msgs.length) return;
    const last = msgs[msgs.length - 1];
    const text = (last.innerText || last.textContent || '').trim();
    await safeCopyText(text);
    const btn = document.getElementById('copy-reply-btn');
    if (btn) {
        btn.innerHTML = '<i class="fa-solid fa-check" style="color:var(--success);"></i>';
        setTimeout(() => { btn.innerHTML = '<i class="fa-solid fa-copy"></i>'; }, 1500);
    }
}

function _addThinkingBubble() {
    const div = document.createElement('div');
    div.id = 'thinking-bubble';
    div.className = 'message bot';
    div.innerHTML = `<div class="thinking-bubble">
        <i class="fa-solid fa-shield-halved" style="color:var(--accent); font-size:1.1em; flex-shrink:0;"></i>
        <div class="thinking-dots"><span></span><span></span><span></span></div>
    </div>`;
    chatHistory.appendChild(div);
    chatHistory.scrollTop = chatHistory.scrollHeight;
    return div;
}

async function sendMessage(forceAllow = false) {
    let text = input.value.trim();
    if (!text) return;

    // 20: LIVE tag — přidá aktuální issues jako kontext do dotazu
    if (/^\[?LIVE\]?\s+/i.test(text)) {
        text = await _enrichWithLiveContext(text);
    }

    const isAutofix = text.startsWith('autofix_');
    const isSilentCmd = text.startsWith('ignore_') || text.startsWith('unignore_') || text.startsWith('delete_');
    const isNonBlocking = ['stav', 'status', 'pending', 'clear file'].includes(text.toLowerCase()) ||
                          isSilentCmd || text.startsWith('autofix_key');

    // Commands that don't use AI streaming
    const isCommand = isNonBlocking || isAutofix ||
        text.startsWith('approve ') || text.startsWith('reject ') ||
        text.startsWith('confirm_approve') || text.startsWith('save_action ') ||
        text === 'delete_all_issues';

    if (isProcessing && !isNonBlocking && !forceAllow) return;

    if (!isNonBlocking) {
        isProcessing = true;
        input.disabled = true;
        sendBtn.disabled = true;
        sendBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
        startTimer(600);
    }

    if (!isAutofix && !isSilentCmd) {
        appendMessage(text.replace(/</g, "&lt;"), 'user');
    }

    let thinkingEl = null;
    if (!isNonBlocking) {
        thinkingEl = _addThinkingBubble();
    }

    input.value = '';

    try {
        if (!isCommand) {
            // ── Real AI query → streaming SSE ──────────────────────────────
            await _sendStreaming(text, thinkingEl);
            thinkingEl = null;
        } else {
            // ── Command → regular JSON response ────────────────────────────
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ message: text })
            });
            if (response.status === 401) { location.reload(); return; }
            const data = await response.json();

            if (thinkingEl) { thinkingEl.remove(); thinkingEl = null; }

            if (data.silent) {
                updateStatus();
                refreshModalIfOpen();
                return;
            }
            if (data.confirm_required) showModal(data.action_id, data.cluster, data.command);
            else if (data.reply) appendMessage(data.reply, 'bot');
            if (data.file_cleared) resetFileUI();
        }

        updateStatus();

    } catch (error) {
        if (thinkingEl) thinkingEl.remove();
        if (!isNonBlocking) appendMessage(t('comm_error'), 'bot');
    } finally {
        if (!isNonBlocking) {
            isProcessing = false;
            input.disabled = false;
            sendBtn.disabled = false;
            sendBtn.innerHTML = '<i class="fa-solid fa-paper-plane"></i>';
            stopTimer();
            input.focus();
        }
    }
}

async function _sendStreaming(text, thinkingEl) {
    let botDiv = null;
    let contentEl = null;
    let accumulated = '';

    try {
        const response = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message: text })
        });
        if (response.status === 401) { location.reload(); return; }
        if (!response.ok) {
            // Fall back to regular /api/chat if stream endpoint fails
            const data = await response.json().catch(() => ({}));
            if (thinkingEl) thinkingEl.remove();
            if (data.reply) appendMessage(data.reply, 'bot');
            return;
        }

        if (thinkingEl) { thinkingEl.remove(); thinkingEl = null; }

        // Create streaming bot message div
        botDiv = document.createElement('div');
        botDiv.className = 'message bot';
        contentEl = document.createElement('span');
        contentEl.className = 'streaming-content';
        botDiv.appendChild(contentEl);
        chatHistory.appendChild(botDiv);

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n');
            buffer = lines.pop(); // keep incomplete last line

            for (const line of lines) {
                if (!line.startsWith('data:')) continue;
                const raw = line.slice(5).trim();
                if (!raw || raw === '[DONE]') continue;
                try {
                    const ev = JSON.parse(raw);
                    if (ev.token) {
                        accumulated += ev.token;
                        contentEl.innerHTML = _formatStreamOutput(accumulated);
                        chatHistory.scrollTop = chatHistory.scrollHeight;
                    }
                    if (ev.done) {
                        const dur = ev.duration ? ` <span style="font-size:0.72em; color:var(--text-muted);">(${ev.duration}s)</span>` : '';
                        botDiv.innerHTML = `<b style="color:var(--accent);"><i class="fa-solid fa-shield-halved" style="font-size:0.9em;"></i> Sentinel${dur}:</b><br>${_formatStreamOutput(accumulated)}`;
                        reader.cancel().catch(() => {});
                        return;
                    }
                } catch(e) {}
            }
        }

        if (!accumulated) {
            botDiv.innerHTML = `<span style="color:var(--text-muted);">${t('comm_error')}</span>`;
        }

    } catch(e) {
        if (thinkingEl) thinkingEl.remove();
        if (botDiv) botDiv.innerHTML = `<span style="color:var(--error);">${t('comm_error')}</span>`;
        else appendMessage(t('comm_error'), 'bot');
    }
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

function _formatStreamOutput(text) {
    return text
        .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/`([^`]+)`/g, '<code style="background:var(--panel);padding:1px 4px;border-radius:3px;font-size:.9em;">$1</code>')
        .replace(/\n/g, '<br>');
}

function refreshModalIfOpen() {
    if (document.getElementById('dedicated-issues-modal')?.style.display === 'flex') {
        refreshModalIssuesContent?.();
    }
}

input.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendMessage(); });
function sendCmd(cmd, force = false) { input.value = cmd; sendMessage(force); }
function triggerAction(cmd) { input.value = cmd; sendMessage(true); }

async function analyzeFile(group, filename, isBulk = false) {
    if (isProcessing && !isBulk) return;
    if (!isBulk) {
       isProcessing = true; 
       input.disabled = true; 
       sendBtn.disabled = true;
       sendBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
       startTimer(600);
    }
    
    appendMessage(t('starting_analysis', {filename}), 'user');
    const thinkingEl = _addThinkingBubble();
    try {
        const response = await fetch('/api/analyze_single_file', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ group: group, file: filename })
        });
        const data = await response.json();
        thinkingEl.remove();
        appendMessage(data.reply, 'bot');
    } catch (e) { thinkingEl.remove(); appendMessage(t('analyze_error'), 'bot'); }
    finally { 
        if (!isBulk) {
            isProcessing = false; 
            input.disabled = false; 
            sendBtn.disabled = false; 
            sendBtn.innerHTML = '<i class="fa-solid fa-paper-plane"></i>'; 
            stopTimer(); 
        }
    }
}

async function analyzeGroup(groupName, mode = 'separate') {
    if (isProcessing) { alert(t('operation_in_progress')); return; }
    
    if (mode === 'complex') {
        isProcessing = true;
        input.disabled = true;
        sendBtn.disabled = true;
        sendBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
        startTimer(600); 

        appendMessage(t('starting_complex_analysis', {group: groupName}), 'user');
        const thinkingElC = _addThinkingBubble();
        try {
            const response = await fetch('/api/analyze_group_complex', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ group: groupName })
            });
            const data = await response.json();
            thinkingElC.remove();
            appendMessage(data.reply, 'bot');
        } catch (e) {
            thinkingElC.remove();
            appendMessage(t('group_analyze_error', {group: groupName}), 'bot');
        } finally {
            isProcessing = false;
            input.disabled = false;
            sendBtn.disabled = false;
            sendBtn.innerHTML = '<i class="fa-solid fa-paper-plane"></i>';
            stopTimer();
        }
        return;
    }

    const files = window.logGroupsData[groupName];
    if (!files) return;
    
    appendMessage(t('starting_seq_analysis', {group: groupName, count: files.length}), 'user');
    
    isProcessing = true;
    input.disabled = true; 
    sendBtn.disabled = true;
    sendBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
    startTimer(600 * files.length);

    for (const file of files) { 
        await analyzeFile(groupName, file, true); 
        await new Promise(r => setTimeout(r, 800)); 
    }
    
    isProcessing = false; 
    input.disabled = false; 
    sendBtn.disabled = false; 
    sendBtn.innerHTML = '<i class="fa-solid fa-paper-plane"></i>';
    stopTimer();
}

async function selectLogContext(filename) {
    try {
        const res = await fetch('/api/set_active_log', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ filename: filename })
        });
        const data = await res.json();
        if(data.status === 'ok') {
            document.getElementById('fname-text').innerText = `${data.filename} (${data.lines} ${t('lines_count')})`;
            document.getElementById('file-name-display').style.display = 'block';
            appendMessage(t('context_set', {filename: data.filename}), 'bot');
        }
    } catch(e) { alert(t('connection_error')); }
}

function showModal(id, cluster, cmd) {
    currentActionId = id;
    document.getElementById('modal-cluster').innerText = cluster;
    document.getElementById('modal-cmd').innerText = cmd;
    document.getElementById('confirm-modal').style.display = 'flex';
}
function closeModal() { document.getElementById('confirm-modal').style.display = 'none'; }
function confirmAction() { if (currentActionId) { input.value = `confirm_approve ${currentActionId}`; sendMessage(); closeModal(); } }

async function handleFileUpload(inputElem) {
    if (inputElem.files.length > 0) {
        const formData = new FormData(); formData.append('file', inputElem.files[0]);
        try {
            const res = await fetch('/api/upload_file', { method: 'POST', body: formData });
            const d = await res.json();
            if (d.status === 'ok') {
                document.getElementById('fname-text').innerText = inputElem.files[0].name;
                document.getElementById('file-name-display').style.display = 'block';
            }
        } catch (e) { alert("Upload error"); }
    }
}
function clearFile() { input.value = 'clear file'; sendMessage(); }
function resetFileUI() { document.getElementById('file-name-display').style.display = 'none'; document.getElementById('file-upload').value = ''; }

let _currentLogFilename = '';
let _currentLogContent  = '';
let _logWrap = true;

async function openLogViewer() { document.getElementById('log-modal').style.display = 'flex'; await loadLogList(); }
function closeLogModal() { document.getElementById('log-modal').style.display = 'none'; }
function _logToggleFileList() {
    const list = document.getElementById('log-file-list');
    if (list) list.classList.toggle('mobile-open');
}

async function loadLogList() {
    const listEl = document.getElementById('log-file-list');
    listEl.innerHTML = t('loading_dots');
    const res = await fetch('/api/logs/list');
    const data = await res.json();
    if (data.files) {
        listEl.innerHTML = '';
        data.files.forEach(f => {
            const item = document.createElement('div');
            item.className = 'log-item';
            item.style.cssText = 'display:flex; align-items:center; gap:4px; padding:0;';

            const nameDiv = document.createElement('div');
            nameDiv.style.cssText = 'flex:1; padding:8px; cursor:pointer;';
            nameDiv.innerHTML = `<b>${_escape(f.name)}</b><div class="log-meta">${_escape(f.size)} | ${_escape(f.mtime)}</div>`;
            nameDiv.onclick = () => loadLogContent(f.name, item);

            const liveBtn = document.createElement('i');
            liveBtn.className = 'fa-solid fa-satellite-dish';
            liveBtn.title = t('live_tail_btn');
            liveBtn.style.cssText = 'padding:10px 8px; color:var(--accent); opacity:0.5; cursor:pointer; font-size:0.8em; flex-shrink:0;';
            liveBtn.onmouseover = () => { liveBtn.style.opacity = '1'; };
            liveBtn.onmouseout  = () => { liveBtn.style.opacity = '0.5'; };
            liveBtn.onclick = (e) => { e.stopPropagation(); openLiveTail(f.name); };

            item.appendChild(nameDiv);
            item.appendChild(liveBtn);
            listEl.appendChild(item);
        });
    }
}

async function loadLogContent(filename, elem) {
    document.querySelectorAll('.log-item').forEach(e => e.classList.remove('active'));
    elem.classList.add('active');
    _currentLogFilename = filename;
    // Na mobilu zavřít file list overlay po výběru
    const list = document.getElementById('log-file-list');
    if (list) list.classList.remove('mobile-open');
    const contentEl = document.getElementById('log-file-content');
    contentEl.innerHTML = `<div style="color:var(--text-muted); padding:20px;">${t('reading_file')}</div>`;
    const res = await fetch('/api/logs/view', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ filename: filename })
    });
    const data = await res.json();
    _currentLogContent = data.content || '';
    _logRenderContent(_currentLogContent);
    contentEl.scrollTop = contentEl.scrollHeight;
}

function _logRenderContent(text) {
    const contentEl = document.getElementById('log-file-content');
    const q = (document.getElementById('log-search')?.value || '').toLowerCase();
    const lvl = (document.getElementById('log-level-filter')?.value || '').toLowerCase();
    const lines = text.split('\n');
    let visible = 0;
    const html = lines.map(line => {
        const tl = line.toLowerCase();
        let color = '';
        if (/\b(error|critical|crit|emerg|alert|fatal)\b/.test(tl)) color = '#f87171';
        else if (/\b(warn|warning)\b/.test(tl)) color = '#ffc107';
        let esc = _escape(line) || '&nbsp;';
        if (q && tl.includes(q)) {
            const re = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
            esc = esc.replace(re, m => `<mark>${m}</mark>`);
        }
        const qHide = q && !tl.includes(q);
        const lvlHide = lvl && !tl.includes(lvl);
        const hide = qHide || lvlHide;
        if (!hide) visible++;
        const styleVal = [color ? `color:${color}` : '', hide ? 'display:none' : ''].filter(Boolean).join(';');
        return `<div class="log-line"${styleVal ? ` style="${styleVal}"` : ''}>${esc}</div>`;
    }).join('');
    contentEl.innerHTML = html;
    contentEl.style.whiteSpace = _logWrap ? 'pre-wrap' : 'pre';
    const cnt = document.getElementById('log-line-count');
    if (cnt) cnt.textContent = (q || lvl) ? `${visible}/${lines.length}` : `${lines.length} řádků`;
}

function _logSearch(q) {
    if (!_currentLogContent) return;
    _logRenderContent(_currentLogContent);
}

function _logTail() {
    const el = document.getElementById('log-file-content');
    if (el) el.scrollTop = el.scrollHeight;
}

function _logCopy() {
    if (!_currentLogContent) return;
    const q = (document.getElementById('log-search')?.value || '').toLowerCase();
    const lvl = (document.getElementById('log-level-filter')?.value || '').toLowerCase();
    let text = _currentLogContent;
    if (q || lvl) {
        text = text.split('\n').filter(l => {
            const tl = l.toLowerCase();
            return (!q || tl.includes(q)) && (!lvl || tl.includes(lvl));
        }).join('\n');
    }
    navigator.clipboard?.writeText(text).then(() => {
        const btn = document.getElementById('log-copy-btn');
        if (btn) { btn.style.color = 'var(--success)'; setTimeout(() => btn.style.color = '', 1500); }
    });
}

function _logWrapToggle() {
    _logWrap = !_logWrap;
    const btn = document.getElementById('log-wrap-btn');
    if (btn) btn.style.color = _logWrap ? 'var(--accent)' : '';
    const el = document.getElementById('log-file-content');
    if (el) el.style.whiteSpace = _logWrap ? 'pre-wrap' : 'pre';
}

function _logDownload() {
    if (!_currentLogContent) return;
    const q = (document.getElementById('log-search')?.value || '').toLowerCase();
    const text = q
        ? _currentLogContent.split('\n').filter(l => l.toLowerCase().includes(q)).join('\n')
        : _currentLogContent;
    const a = document.createElement('a');
    a.href = 'data:text/plain;charset=utf-8,' + encodeURIComponent(text);
    a.download = _currentLogFilename || 'log.txt';
    a.click();
}

let _detPatterns = [];

function _logToggleDetector() {
    const panel = document.getElementById('log-detector-panel');
    const btn   = document.getElementById('log-det-toggle-btn');
    if (!panel) return;
    const open = panel.style.display === 'none';
    panel.style.display = open ? 'flex' : 'none';
    if (btn) btn.style.color = open ? 'var(--accent)' : 'var(--text-muted)';
    if (open) {
        _logDetectorReload();
        setTimeout(() => {
            const ta = document.getElementById('log-det-input');
            if (ta && !ta.value.trim() && _currentLogContent)
                ta.value = _currentLogContent.slice(0, 4000);
            const lbl = document.getElementById('log-det-file-label');
            const fname = document.getElementById('log-file-title')?.textContent?.trim() || '';
            if (lbl) lbl.textContent = fname ? fname : '';
        }, 100);
    }
}

async function _logDetectorReload() {
    const el = document.getElementById('log-det-patterns');
    if (!el) return;
    el.innerHTML = '<i class="fa-solid fa-spinner fa-spin" style="color:var(--text-muted); padding:8px;"></i>';
    try {
        const r = await fetch('/api/patterns');
        const d = await r.json();
        _detPatterns = d.patterns || [];
        _renderDetPatterns();
    } catch(e) {
        el.innerHTML = `<span style="color:var(--error); font-size:.75em; padding:6px;">Chyba: ${_escape(String(e))}</span>`;
    }
}

function _renderDetPatterns() {
    const el = document.getElementById('log-det-patterns');
    if (!el) return;
    if (!_detPatterns.length) {
        el.innerHTML = '<span style="color:var(--text-muted); font-size:.75em; padding:6px;">— žádné patterns —</span>';
        return;
    }
    el.innerHTML = _detPatterns.map((p, i) =>
        `<div style="display:flex; align-items:center; gap:4px; padding:3px 6px; border-bottom:1px solid var(--border);" data-pid="${p.id}">
            <input type="checkbox" ${p.enabled ? 'checked' : ''} onchange="_detToggle(${p.id}, this.checked)" style="accent-color:var(--accent); cursor:pointer; flex-shrink:0;">
            <span style="flex:1; font-size:.75em; font-family:monospace; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; cursor:pointer;" title="${_escape(p.pattern)}" onclick="_detEditInline(${i})">${_escape(p.name || p.pattern)}</span>
            <i class="fa-solid fa-trash" style="font-size:.7em; color:var(--text-muted); cursor:pointer; opacity:.5;" onmouseover="this.style.opacity=1" onmouseout="this.style.opacity=.5" onclick="_detDelete(${p.id})"></i>
        </div>`
    ).join('');
}

async function _detToggle(pid, enabled) {
    await fetch(`/api/patterns/${pid}/toggle`, {method:'POST'});
    const p = _detPatterns.find(x => x.id === pid);
    if (p) p.enabled = enabled;
}

async function _detDelete(pid) {
    if (!confirm('Smazat pattern?')) return;
    await fetch(`/api/patterns/${pid}`, {method:'DELETE'});
    await _logDetectorReload();
}

function _detEditInline(idx) {
    const p = _detPatterns[idx];
    if (!p) return;
    const name    = prompt('Název:', p.name || '');
    if (name === null) return;
    const pattern = prompt('Regex pattern:', p.pattern);
    if (!pattern) return;
    fetch('/api/patterns', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({name, pattern})
    }).then(() => {
        fetch(`/api/patterns/${p.id}`, {method:'DELETE'}).then(() => _logDetectorReload());
    });
}

function _logDetectorAddPattern() {
    const el = document.getElementById('log-det-patterns');
    if (!el) return;
    // Inline formulář nahoře v seznamu
    const existing = el.querySelector('.det-add-form');
    if (existing) { existing.remove(); return; }
    const form = document.createElement('div');
    form.className = 'det-add-form';
    form.style.cssText = 'padding:6px; background:rgba(0,120,212,.08); border:1px solid var(--accent); border-radius:4px; margin-bottom:4px;';
    form.innerHTML = `
        <input id="det-new-name" placeholder="Název patternu" style="width:100%;box-sizing:border-box;padding:3px 6px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:3px;font-size:.78em;margin-bottom:4px;">
        <input id="det-new-regex" placeholder="Regex (např. Failed .* from (\\d+\\.\\d+))" style="width:100%;box-sizing:border-box;padding:3px 6px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:3px;font-size:.75em;font-family:monospace;margin-bottom:4px;">
        <div style="display:flex;gap:4px;">
            <button onclick="_detAddSubmit()" style="flex:1;padding:3px;background:var(--accent);color:#fff;border:none;border-radius:3px;cursor:pointer;font-size:.75em;">Přidat</button>
            <button onclick="document.querySelector('.det-add-form').remove()" style="padding:3px 8px;background:transparent;border:1px solid var(--border);color:var(--text-muted);border-radius:3px;cursor:pointer;font-size:.75em;">×</button>
        </div>`;
    el.insertBefore(form, el.firstChild);
    el.querySelector('#det-new-name')?.focus();
}
async function _detAddSubmit() {
    const name    = document.getElementById('det-new-name')?.value.trim();
    const pattern = document.getElementById('det-new-regex')?.value.trim();
    if (!name || !pattern) return;
    await fetch('/api/patterns', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({name, pattern})
    });
    document.querySelector('.det-add-form')?.remove();
    await _logDetectorReload();
}

function _logDetectorFromFile() {
    const ta = document.getElementById('log-det-input');
    if (ta && _currentLogContent) ta.value = _currentLogContent.slice(0, 8000);
}

async function _logDetectorRun() {
    const ta  = document.getElementById('log-det-input');
    const out = document.getElementById('log-det-results');
    if (!ta || !out) return;
    const lines = ta.value.split('\n').filter(l => l.trim());
    if (!lines.length) { out.innerHTML = '<span style="color:var(--text-muted)">— žádné řádky —</span>'; return; }

    out.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';

    const activePatterns = _detPatterns.filter(p => {
        const cb = document.querySelector(`[data-pid="${p.id}"] input[type=checkbox]`);
        return cb ? cb.checked : p.enabled;
    });

    if (!activePatterns.length) { out.innerHTML = '<span style="color:var(--text-muted)">— žádné aktivní patterns —</span>'; return; }

    const results = [];
    for (const line of lines) {
        for (const pat of activePatterns) {
            try {
                const m = new RegExp(pat.pattern).exec(line);
                if (m) results.push({ name: pat.name || pat.pattern, line, match: m[0] });
            } catch(_) {}
        }
    }

    if (!results.length) {
        out.innerHTML = `<span style="color:var(--success)"><i class="fa-solid fa-check"></i> Žádný match (${activePatterns.length} patterns, ${lines.length} řádků)</span>`;
    } else {
        out.innerHTML = results.map(r =>
            `<div style="margin-bottom:5px; border-left:2px solid var(--accent); padding-left:6px;">` +
            `<div style="color:var(--accent); font-size:.72em; margin-bottom:1px;">${_escape(r.name)}</div>` +
            `<div style="color:var(--text-main); word-break:break-all;">${_escape(r.line)}</div>` +
            `<div style="color:#ffc107; font-size:.72em;">↳ <b>${_escape(r.match)}</b></div>` +
            `</div>`
        ).join('') + `<div style="color:var(--text-muted); margin-top:6px; font-size:.72em; border-top:1px solid var(--border); padding-top:4px;">${results.length} zachycení / ${lines.length} řádků / ${activePatterns.length} patterns</div>`;
    }
}

let _predShowHidden = false;

async function openPredictions() {
    document.getElementById('pred-modal').style.display = 'flex';
    await _loadPredictions();
}

async function _loadPredictions() {
    const content = document.getElementById('pred-content');
    content.innerHTML = `<div style="text-align:center; padding:20px; color:#888;">${t('loading_telemetry')} <i class="fa-solid fa-spinner fa-spin"></i></div>`;

    try {
        const res = await fetch('/api/predictions' + (_predShowHidden ? '?show_hidden=1' : ''));
        const json = await res.json();
        window.predictionData = {};

        let html = '';
        if (json.data_age_warning) {
            html += `<div style="padding:7px 12px; margin-bottom:10px; background:rgba(253,126,20,.1); border:1px solid rgba(253,126,20,.3); border-radius:4px; font-size:.8em; color:#fd7e14;"><i class="fa-solid fa-triangle-exclamation"></i> ${_escape(json.data_age_warning)}</div>`;
        }
        if(json.data.length === 0) {
            html += `<div style="padding:20px; text-align:center; color:#888;">${t('no_data_yet')}</div>`;
        } else {
            const grouped = {};
            json.data.forEach(item => {
                if(!grouped[item.category]) grouped[item.category] = [];
                grouped[item.category].push(item);
                window.predictionData[item.metric] = item.history; 
            });
            
            for (const [cat, items] of Object.entries(grouped)) {
                html += `<div class="metric-cat-header">${cat}</div>`;
                
                const priority = { 'CRITICAL': 0, 'WARNING': 1, 'PREDICTION': 2, 'OK': 3 };
                items.sort((a, b) => (priority[a.status] || 3) - (priority[b.status] || 3));

                const alerts = items.filter(i => i.status !== 'OK');
                const oks = items.filter(i => i.status === 'OK');

                const renderCard = (item) => {
                    let statusClass = 'OK';
                    let icon = '<i class="fa-solid fa-check" style="color:var(--success)"></i>';
                    let color = '#fff';

                    if(item.status === 'CRITICAL') {
                        statusClass = 'CRITICAL';
                        icon = '<i class="fa-solid fa-fire-flame-curved" style="color:var(--error)"></i>';
                        color = '#ff4444';
                    } else if(item.status === 'WARNING') {
                        statusClass = 'WARNING';
                        icon = '<i class="fa-solid fa-triangle-exclamation" style="color:var(--warning)"></i>';
                        color = '#ffc107';
                    } else if(item.status === 'PREDICTION') {
                        statusClass = 'PREDICTION';
                        icon = '<i class="fa-solid fa-wand-magic-sparkles" style="color:var(--prediction)"></i>';
                        color = '#17a2b8';
                    }

                    const last = item.history[item.history.length-1];
                    const prev = item.history.length > 1 ? item.history[item.history.length-2] : last;
                    const trendArrow = last > prev ? '↗' : (last < prev ? '↘' : '→');
                    const metricEsc = _escape(item.metric);
                    const metricB64 = btoa(unescape(encodeURIComponent(item.metric)));
                    const eyeIcon = item.hidden
                        ? '<i class="fa-solid fa-eye" style="color:var(--accent)"></i>'
                        : '<i class="fa-regular fa-eye-slash" style="color:var(--text-muted)"></i>';
                    const hideBtn = (window.currentRole === 'admin' || window.currentRole === 'superadmin')
                        ? `<button onclick="event.stopPropagation();_toggleHiddenSensor('${metricB64}')"
                            title="${item.hidden ? 'Zobrazit senzor' : 'Skrýt senzor'}"
                            style="background:transparent;border:none;cursor:pointer;padding:2px 6px;margin-left:6px;">${eyeIcon}</button>`
                        : '';

                    return `
                    <div class="metric-card ${statusClass}${item.hidden ? ' hidden-sensor' : ''}" onclick="openGraphModal('${metricEsc}')"
                         style="${item.hidden ? 'opacity:0.5;' : ''}">
                        <div style="flex:1;">
                            <div class="metric-name">${metricEsc}</div>
                            <div class="metric-msg">${icon} ${item.message}</div>
                        </div>
                        <div style="display:flex;align-items:center;gap:8px;">
                            <div style="text-align:right;">
                                <div class="metric-val" style="color:${color}">
                                    ${item.value} <span class="trend-arrow" style="color:#666">${trendArrow}</span>
                                </div>
                                <div style="font-size:0.7em; opacity:0.5;">Trend 24h</div>
                            </div>
                            ${hideBtn}
                        </div>
                    </div>`;
                };

                alerts.forEach(item => { html += renderCard(item); });

                if (oks.length > 0) {
                    html += `<details class="ok-metrics"><summary>Zobrazit stabilní metriky (${oks.length})</summary>`;
                    oks.forEach(item => { html += renderCard(item); });
                    html += `</details>`;
                }
            }

            // Sekce skrytých senzorů
            const hiddenCount = json.hidden_count || 0;
            if (hiddenCount > 0 && !_predShowHidden) {
                html += `<div style="margin-top:16px;padding:10px 14px;background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:6px;display:flex;justify-content:space-between;align-items:center;">
                    <span style="color:var(--text-muted);font-size:0.88em;"><i class="fa-regular fa-eye-slash"></i> ${hiddenCount} skrytých senzorů</span>
                    <button onclick="_predShowHidden=true;_loadPredictions()" style="background:transparent;border:1px solid var(--border);color:var(--text-muted);padding:3px 10px;border-radius:4px;cursor:pointer;font-size:0.82em;">Zobrazit</button>
                </div>`;
            } else if (_predShowHidden && hiddenCount > 0) {
                html += `<div style="margin-top:12px;text-align:right;">
                    <button onclick="_predShowHidden=false;_loadPredictions()" style="background:transparent;border:1px solid var(--border);color:var(--text-muted);padding:3px 10px;border-radius:4px;cursor:pointer;font-size:0.82em;">Skrýt skryté</button>
                    <button onclick="_resetHiddenSensors()" style="background:rgba(197,15,31,0.1);border:1px solid rgba(197,15,31,0.3);color:#c50f1f;padding:3px 10px;border-radius:4px;cursor:pointer;font-size:0.82em;margin-left:6px;">Zobrazit vše (reset)</button>
                </div>`;
            }
        }
        content.innerHTML = html;
    } catch(e) {
        console.error(e);
        content.innerHTML = `<div style="color:var(--error); padding:20px; text-align:center;">${t('load_error')}</div>`;
    }
}

function closePredModal() { document.getElementById('pred-modal').style.display = 'none'; _predShowHidden = false; }

async function _toggleHiddenSensor(metricB64) {
    const metric = decodeURIComponent(escape(atob(metricB64)));
    await fetch('/api/predictions/toggle_hidden', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({metric})
    });
    _loadPredictions();
}

async function _resetHiddenSensors() {
    await fetch('/api/predictions/reset_hidden', {method: 'POST'});
    _predShowHidden = false;
    _loadPredictions();
}

let _currentGraphMetric = null;

function openGraphModal(metricName) {
    const history = window.predictionData[metricName];
    if (!history || history.length === 0) return;
    _currentGraphMetric = metricName;

    document.getElementById('graph-metric-name').innerText = metricName;
    document.getElementById('graph-modal').style.display = 'flex';
    // 068: Naplň compare select dostupnými metrikami
    const sel = document.getElementById('graph-compare-select');
    if (sel) {
        const metrics = Object.keys(window.predictionData || {}).filter(m => m !== metricName);
        sel.innerHTML = '<option value="">— vyberte metriku —</option>' +
            metrics.map(m => `<option value="${_escape(m)}">${_escape(m)}</option>`).join('');
    }
    document.getElementById('graph-compare-area').style.display = 'none';

    const ctx = document.getElementById('metricChart').getContext('2d');
    if (chartInstance) { chartInstance.destroy(); }

    const labels = history.map((_, i) => `${i - history.length + 1}`); 
    let predData = new Array(history.length).fill(null);
    
    if (history.length >= 2) {
        const n = Math.min(12, history.length);
        const subsetY = history.slice(-n);
        const subsetX = Array.from({length: n}, (_, i) => i);
        const sumX = subsetX.reduce((a, b) => a + b, 0);
        const sumY = subsetY.reduce((a, b) => a + b, 0);
        const sumXY = subsetX.reduce((a, i) => a + i * subsetY[i], 0);
        const sumXX = subsetX.reduce((a, i) => a + i * i, 0);
        const slope = (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX);
        const intercept = (sumY - slope * sumX) / n;

        predData[history.length - 1] = history[history.length - 1];
        for (let i = 1; i <= 12; i++) {
            const nextVal = slope * (n - 1 + i) + intercept;
            predData.push(nextVal);
            labels.push(`+${i * 5}m`);
        }
    }

    chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Historie',
                    data: history,
                    borderColor: '#0078d4',
                    backgroundColor: 'rgba(0, 120, 212, 0.1)',
                    borderWidth: 2,
                    tension: 0.2,
                    fill: true
                },
                {
                    label: 'Predikce (Trend)',
                    data: predData,
                    borderColor: '#17a2b8',
                    borderWidth: 2,
                    borderDash: [5, 5],
                    tension: 0,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { display: false },
                y: { grid: { color: '#333' }, ticks: { color: '#aaa' } }
            },
            plugins: { legend: { labels: { color: '#ddd' } } }
        }
    });
}

function closeGraphModal() {
    document.getElementById('graph-modal').style.display = 'none';
    document.getElementById('graph-compare-area').style.display = 'none';
}

function _toggleCompareArea() {
    const area = document.getElementById('graph-compare-area');
    if (!area) return;
    area.style.display = area.style.display === 'none' ? 'block' : 'none';
}

function _compareMetricAdd(metricName) {
    if (!metricName || !chartInstance) return;
    const hist2 = (window.predictionData || {})[metricName];
    if (!hist2) return;
    // Odstraň předchozí compare dataset (index 2+)
    while (chartInstance.data.datasets.length > 2) chartInstance.data.datasets.pop();
    chartInstance.data.datasets.push({
        label: metricName,
        data: hist2.slice(0, chartInstance.data.labels.length),
        borderColor: '#28a745',
        backgroundColor: 'rgba(40,167,69,0.08)',
        borderWidth: 2,
        tension: 0.2,
        yAxisID: 'y2',
    });
    if (!chartInstance.options.scales.y2) {
        chartInstance.options.scales.y2 = {
            position: 'right',
            grid: { drawOnChartArea: false },
            ticks: { color: '#28a745', font: { size: 9 } }
        };
    }
    chartInstance.update();
}

// --- ACTION TIMERS ---
function updateActionTimers() {
    const now = new Date();
    document.querySelectorAll('.action-timer').forEach(el => {
        const createdStr = el.getAttribute('data-created');
        if (!createdStr) return;
        
        const created = new Date(createdStr);
        const expires = new Date(created.getTime() + 15 * 60000); // +15 mins
        const diff = expires - now;

        if (diff <= 0) {
            el.innerText = t('expired');
            el.style.color = "#c50f1f";
            el.style.fontWeight = "bold";
            
            const card = el.closest('.action-card');
            if (card) {
                card.style.opacity = "0.5";
                card.querySelectorAll('button').forEach(b => b.disabled = true);
            }
        } else {
            const m = Math.floor(diff / 60000);
            const s = Math.floor((diff % 60000) / 1000);
            el.innerText = t('expires_in', {time: `${m}:${s.toString().padStart(2, '0')}`});
        }
    });
}
setInterval(updateActionTimers, 1000);

// --- NOTIFICATION LOGIC ---
async function toggleNotifications() {
    const btn = document.getElementById('notification-btn');
    if (!btn) return;

    if (!notificationsEnabled) {
        if (!("Notification" in window)) {
            alert("Tento prohlizec nepodporuje systemove notifikace.");
            return;
        }

        const permission = await Notification.requestPermission();
        
        if (permission === "granted") {
            notificationsEnabled = true;
            localStorage.setItem('sentinel_notifications', 'true'); 
            updateNotificationIconUI(true);
            
            new Notification("Sentinel", { 
                body: "Notifikace aktivovany ✅", 
                icon: "/static/favicon.ico" 
            });
        } else {
            alert("Nemohu zapnout notifikace.\n\nMusite je povolit v nastaveni prohlizece (ikona zamecku vlevo od adresy).");
        }
    } 
    else {
        notificationsEnabled = false;
        localStorage.setItem('sentinel_notifications', 'false');
        updateNotificationIconUI(false);
    }
}

// 270: Zvuk při novém alertu — per-user toggle (localStorage)
let _alertSoundEnabled = localStorage.getItem('sentinel_alert_sound') === '1';
function toggleAlertSound() {
    _alertSoundEnabled = !_alertSoundEnabled;
    localStorage.setItem('sentinel_alert_sound', _alertSoundEnabled ? '1' : '0');
    const btn = document.getElementById('alert-sound-btn');
    if (btn) {
        btn.title = _alertSoundEnabled ? 'Zvuk alertu zapnut' : 'Zvuk alertu vypnut';
        btn.style.color = _alertSoundEnabled ? 'var(--accent)' : '';
    }
}
function _playAlertSound() {
    if (!_alertSoundEnabled) return;
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain); gain.connect(ctx.destination);
        osc.frequency.setValueAtTime(880, ctx.currentTime);
        osc.frequency.setValueAtTime(660, ctx.currentTime + 0.1);
        gain.gain.setValueAtTime(0.3, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
        osc.start(ctx.currentTime); osc.stop(ctx.currentTime + 0.4);
    } catch(e) { /* AudioContext not available */ }
}

function checkNewIssues(currentCount) {
    if (lastIssueCount === -1) {
        lastIssueCount = currentCount;
        if (currentCount > 0 && notificationsEnabled) {
            triggerVisualAlert(currentCount);
        }
        return;
    }

    if (currentCount > lastIssueCount) {
        if (notificationsEnabled) triggerVisualAlert(currentCount);
        _playAlertSound();
    }

    lastIssueCount = currentCount;
}

function triggerVisualAlert(count) {
    const btn = document.getElementById('notification-btn');
    
    if (btn) {
        btn.classList.add('notification-active');
        setTimeout(() => btn.classList.remove('notification-active'), 15000);
    }

    if (!notificationsEnabled) return;

    // 393: Toast queue — max 3 visible, remove oldest if exceeded
    const existingToasts = document.querySelectorAll('.sentinel-toast');
    if (existingToasts.length >= 3) {
        existingToasts[0].remove();
    }

    const toast = document.createElement('div');
    toast.className = 'sentinel-toast';
    toast.innerHTML = `
        <i class="fa-solid fa-triangle-exclamation"></i>
        <div>
            <div style="font-weight:bold; margin-bottom:4px;">Sentinel Alert</div>
            <div style="font-size:0.9em; color:#ccc;">Novy problem!<br>Celkem chyb: <b>${count}</b></div>
        </div>
    `;
    toast.onclick = () => { stopBlinking(); toast.remove(); };
    document.body.appendChild(toast);
    setTimeout(() => { if(document.body.contains(toast)) toast.remove(); }, 10000);

    if (!titleInterval) {
        let state = false;
        titleInterval = setInterval(() => {
            document.title = state ? t('alert_title_warn', {count}) : t('new_error_title');
            state = !state;
        }, 1000);
    }

    try {
        const audio = new Audio("https://actions.google.com/sounds/v1/alarms/beep_short.ogg");
        audio.volume = 1.0; 
        
        const playPromise = audio.play();
        
        if (playPromise !== undefined) {
            playPromise.catch(error => {
                console.log("Zvuk zablokovan prohlizecem. Uzivatel musi nejprve kliknout na stranku.");
            });
        }
    } catch(e) { console.error("Audio error", e); }
}

function stopBlinking() {
    if (titleInterval) {
        clearInterval(titleInterval);
        titleInterval = null;
        document.title = originalTitle;
    }
}

window.addEventListener('focus', stopBlinking);
window.addEventListener('click', stopBlinking);
window.addEventListener('mousemove', () => {
    if (titleInterval) stopBlinking();
});

// --- MAIN STATUS LOOP ---
async function updateStatus() {
    try {
        const _t0 = performance.now();
        const res = await fetch('/api/status_check');
        const d = await res.json();
        const _dt = Math.round(performance.now() - _t0);
        if (_dt > 500) console.warn(`[Sentinel] status_check slow: ${_dt}ms`);

        const mqttIcon = document.getElementById('mqtt-status-icon');
        if (mqttIcon) {
            if (d.mqtt_enabled) {
                if (d.mqtt_connected) {
                    mqttIcon.className = 'badge badge-service active';
                    mqttIcon.title = t('mqtt_connected');
                    mqttIcon.style.color = '';
                    mqttIcon.style.filter = '';
                } else {
                    mqttIcon.className = 'badge badge-service error';
                    mqttIcon.title = t('mqtt_disconnected');
                    mqttIcon.style.color = '';
                    mqttIcon.style.filter = '';
                }
            } else {
                mqttIcon.className = 'badge badge-service inactive';
                mqttIcon.title = t('mqtt_disabled_cfg');
                mqttIcon.style.color = '';
                mqttIcon.style.filter = '';
            }
        }
        
        const ind = document.getElementById('status-indicator');
        const pendingBtn = document.getElementById('pending-actions-btn');
        const ragBadge = document.getElementById('rag-badge');
        const qBadge = document.getElementById('queue-badge');

        if (qBadge) {
            qBadge.style.display = 'flex';
            if (d.queue_depth > 0) {
                qBadge.className = 'badge badge-queue'; 
                qBadge.style.opacity = '1';
                qBadge.innerHTML = `<i class="fa-solid fa-hourglass-half"></i> <span> ${d.queue_depth}</span>`;
            } else {
                qBadge.className = 'badge';
                qBadge.style.background = 'rgba(255, 255, 255, 0.05)';
                qBadge.style.color = '#666';
                qBadge.style.border = '1px solid #444';
                qBadge.style.animation = 'none';
                qBadge.innerHTML = `<i class="fa-regular fa-hourglass"></i> <span> 0</span>`;
            }
        }

        if (ragBadge) {
            if (d.rag_ready) {
                ragBadge.className = 'badge badge-rag ready';
                ragBadge.innerHTML = '<i class="fa-solid fa-brain"></i> <span>Vector</span>';
            } else {
                ragBadge.className = 'badge badge-rag text-only';
                ragBadge.innerHTML = '<i class="fa-solid fa-font"></i> <span>Text</span>';
            }
        }

        // 1. INFRA LOG ISSUES
        if (d.issues > 0) {
            ind.className = 'badge badge-status active';
            ind.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> <span> ${d.issues}</span>`;
        } else {
            ind.className = 'badge badge-status ok'; 
            ind.innerHTML = `<i class="fa-solid fa-check-circle"></i> <span> OK</span>`;
        }

        // 2. AGENTS GENERIC ISSUES
        const agentInd = document.getElementById('agent-status-indicator');
        if(agentInd) {
            if (d.agent_issues > 0) {
                agentInd.style.background = 'var(--error)';
                agentInd.style.color = 'white';
                agentInd.style.border = 'none';
                agentInd.querySelector('span').innerText = ` ${d.agent_issues}`;
            } else {
                agentInd.style.background = 'rgba(255,255,255,0.05)';
                agentInd.style.color = 'var(--success)';
                agentInd.style.border = '1px solid #444';
                agentInd.querySelector('span').innerText = ' OK';
            }
        }

        // 3. ROOT SESSIONS ISSUES
        const rootInd = document.getElementById('root-status-indicator');
        if(rootInd) {
            if (d.root_issues > 0) {
                rootInd.style.background = '#ffc107'; // Orange for root
                rootInd.style.color = '#111';
                rootInd.style.border = 'none';
                rootInd.querySelector('span').innerText = ` ${d.root_issues}`;
            } else {
                rootInd.style.background = 'rgba(255,255,255,0.05)';
                rootInd.style.color = 'var(--success)';
                rootInd.style.border = '1px solid #444';
                rootInd.querySelector('span').innerText = ' OK';
            }
        }

        // 4. SECURITY ISSUES
        const secInd = document.getElementById('security-status-indicator');
        if(secInd) {
            if (d.security_issues > 0) {
                secInd.style.background = 'var(--error)';
                secInd.style.animation = 'pulse 1.5s infinite';
                secInd.style.color = 'white';
                secInd.style.border = 'none';
                secInd.querySelector('span').innerText = ` ${d.security_issues}`;
            } else {
                secInd.style.background = 'rgba(255,255,255,0.05)';
                secInd.style.color = 'var(--success)';
                secInd.style.border = '1px solid #444';
                secInd.style.animation = 'none';
                secInd.querySelector('span').innerText = ' OK';
            }
        }

        if (lastIssueCount !== -1 && d.issues !== lastIssueCount) {
            refreshLastStatusTable();
        }

        // Favicon badge s počtem kritických alertů
        const _totalAlerts = (d.issues||0) + (d.agent_issues||0) + (d.security_issues||0);
        _updateFaviconBadge(_totalAlerts);
        _checkPushNotification(d);  // 007: browser push

        updateSentinelAlertBadge();

        // Accumulate count for Toast alert
        const totalIssues = d.issues + d.agent_issues + d.root_issues + d.security_issues;
        checkNewIssues(totalIssues);

        if (d.pending > 0) {
            if(pendingBtn) {
                pendingBtn.innerHTML = `<i class="fa-solid fa-robot"></i> ${t('actions_ai')} <span style="background:#ffc107;color:#000;border-radius:10px;padding:0 6px;font-size:0.8em;margin-left:4px;">${d.pending}</span>`;
                pendingBtn.classList.add("pending-blink");
            }
        } else {
            if(pendingBtn) {
                pendingBtn.innerHTML = `<i class="fa-solid fa-robot"></i> ${t('actions_ai')}`;
                pendingBtn.classList.remove("pending-blink");
            }
        }

        if (lastIssueCount !== -1 && d.issues !== lastIssueCount) {
            refreshLastStatusTable();
        }

        checkNewIssues(d.issues);

        // Skrýt startup loading bar po prvním úspěšném načtení
        const lb = document.getElementById('startup-loading-bar');
        if (lb) { lb.style.opacity = '0'; setTimeout(() => lb.remove(), 500); }

    } catch (e) { console.error("Status update failed:", e); }
}

async function refreshLastStatusTable() {
    const wrappers = document.querySelectorAll('.status-wrapper');
    
    if (wrappers.length === 0) return; 

    const lastWrapper = wrappers[wrappers.length - 1];

    try {
        const res = await fetch('/api/get_status_html');
        const data = await res.json();
        
        if (data.html) {
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = data.html;
            const newWrapper = tempDiv.firstChild;

            if (lastWrapper.classList.contains('minimized')) {
                newWrapper.classList.add('minimized');
            }

            lastWrapper.replaceWith(newWrapper);
            console.log("Status table updated via Auto-Refresh");
        }
    } catch (e) {
        console.error("Auto-refresh error:", e);
    }
}

setInterval(async () => {
    const monitors = document.querySelectorAll('.sys-monitor-live');
    if (monitors.length === 0) return;

    const newestIndex = monitors.length - 1;

    monitors.forEach((m, index) => {
        const body = m.querySelector('.sys-body');
        
        if (index < newestIndex) {
            if (body && !body.classList.contains('minimized')) {
                body.classList.add('minimized');
            }
            m.classList.remove('sys-monitor-live');
            const title = m.querySelector('.sys-header span');
            if (title) title.innerHTML = `<i class='fa-solid fa-clock-rotate-left'></i> ${t('system_snapshot')}`;
        }
    });

    const activeMonitor = monitors[newestIndex];
    const activeBody = activeMonitor.querySelector('.sys-body');

    if (activeBody && activeBody.classList.contains('minimized')) return;

    try {
        const res = await fetch('/api/sys_monitor_html');
        if (res.ok) {
            const data = await res.json();
            if (data.html && activeBody) {
                activeBody.innerHTML = data.html;
                _dashApply();
            }
        }
    } catch (e) {
        console.error("Sys monitor refresh failed:", e);
    }
}, 3000);

// 255: WebSocket heartbeat watchdog — force reconnect pokud 45s žádná zpráva
let _wsLastMsg = Date.now();
socket.onAny(() => { _wsLastMsg = Date.now(); });
setInterval(() => {
    if (Date.now() - _wsLastMsg > 45000) {
        console.warn('[Sentinel] WS silent >45s, reconnecting…');
        socket.disconnect();
        socket.connect();
        _wsLastMsg = Date.now();
    }
}, 15000);

// Start loop (5s interval)
setInterval(updateStatus, 30000);

// Sparklines — načíst jednou za 5 minut
window.addEventListener('load', () => { if (typeof _loadSparklineData === 'function') _loadSparklineData(); });
setInterval(() => { if (typeof _loadSparklineData === 'function') _loadSparklineData(); }, 300000); 
updateStatus();

// ==========================================================================
// OFF-CANVAS MOBILE MENU LOGIC
// ==========================================================================

function toggleMobileMenu() {
    if (window.innerWidth > 850) return;
    
    const panel = document.getElementById('tools-panel');
    const backdrop = document.getElementById('mobile-backdrop');
    
    if (panel) {
        panel.classList.toggle('open');
    }
    
    if (backdrop && panel) {
        if (panel.classList.contains('open')) {
            backdrop.style.display = 'block';
        } else {
            backdrop.style.display = 'none';
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const mobileTriggerElements = document.querySelectorAll('.tool-btn, .group-action-btn, .file-actions i');
    
    mobileTriggerElements.forEach(btn => {
        btn.addEventListener('click', () => {
            if (window.innerWidth <= 850) {
                toggleMobileMenu();
            }
        });
    });
});

// ==========================================================================
// SENTINEL AGENT MANAGEMENT SYSTEM
// ==========================================================================

function openAgentManager() {
    document.getElementById('sentinel-alert-modal').style.display = 'flex';
    const td = document.getElementById('agent-token-display');
    if (td) td.style.display = 'none';
    const rh = document.getElementById('agent-reg-hostname');
    if (rh) rh.value = '';
    switchSatTab('agents');
    if (agentRefreshInterval) clearInterval(agentRefreshInterval);
    agentRefreshInterval = setInterval(() => loadAgentsList(true), 30000);
}

function closeAgentModal() {
    closeSentinelAlertModal();
}

async function loadAgentsList(isAutoRefresh = false) {
    const tbody = document.getElementById('agent-table-body');
    
    if (!isAutoRefresh) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px; color:#666;"><i class="fa-solid fa-spinner fa-spin"></i> ${t('loading_agents')}</td></tr>`;
    }

    try {
        const res = await fetch('/api/agents/list');
        const data = await res.json();

        if(data.status === 'ok') {
            if(data.agents.length === 0) {
                tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px; color:#666;">${t('no_agents_registered_table')}</td></tr>`;
                return;
            }

            // Filtrovat Satellite zařízení — ta patří do Sentinel Satellites modalu
            const filteredAgents = data.agents.filter(a =>
                a.category !== 'alert' && a.category !== 'hw'
            );

            if (filteredAgents.length === 0) {
                tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px; color:#666;">${t('no_agents_registered_table')}</td></tr>`;
                return;
            }

            let newHtml = '';
            filteredAgents.forEach(agent => {
                const lastSeenDate = new Date(agent.last_seen);
                const formattedTime = lastSeenDate.toLocaleString('cs-CZ');

                let statusColor = 'var(--offline)';
                if(agent.status === 'ONLINE') statusColor = 'var(--success)';

                const ignored = !!agent.ignore_offline;
                const ignoreTitle = ignored ? 'Offline se hlásí (kliknout pro zapnutí hlášení)' : 'Ignorovat offline stav (nekliknout pro výstrahu)';
                const ignoreIcon = ignored
                    ? `<i class="fa-solid fa-bell-slash" style="color:var(--text-muted);" title="${ignoreTitle}"></i>`
                    : `<i class="fa-solid fa-bell" style="color:var(--success);" title="${ignoreTitle}"></i>`;

                // 264: Mini CPU/RAM sparkline v řádku
                const sparkId = `sp-${agent.hostname.replace(/[^a-z0-9]/gi, '-')}`;
                newHtml += `
                    <tr style="border-bottom:1px solid var(--border); ${ignored ? 'opacity:0.65;' : ''} cursor:pointer;"
                        onclick="openDeviceDetailModal('${agent.hostname}', 'agent')">
                        <td style="padding:10px; font-weight:bold;">${agent.hostname}</td>
                        <td style="padding:10px;"><span style="color:${statusColor}; font-weight:bold;">● ${agent.status}</span>${ignored && agent.status !== 'ONLINE' ? ' <span style="font-size:0.75em;color:var(--text-muted);">(ignorováno)</span>' : ''}</td>
                        <td style="padding:10px; font-family:monospace; color:#aaa;">${formattedTime}</td>
                        <td style="padding:6px 10px;" onclick="event.stopPropagation()">
                            <canvas id="${sparkId}-cpu" width="50" height="20" title="CPU 1h" style="vertical-align:middle;opacity:.8;"></canvas>
                            <canvas id="${sparkId}-ram" width="50" height="20" title="RAM 1h" style="vertical-align:middle;opacity:.8;margin-left:2px;"></canvas>
                        </td>
                        <td style="padding:10px; text-align:center;" onclick="event.stopPropagation()">
                            <span style="cursor:pointer;" onclick="toggleAgentIgnoreOffline('${agent.hostname}', ${ignored})">${ignoreIcon}</span>
                        </td>
                        <td style="padding:10px; text-align:center;" onclick="event.stopPropagation()">
                            <i class="fa-solid fa-trash" style="cursor:pointer; color:var(--error);" title="${t('delete_agent_title')}" onclick="deleteAgentSubmit('${agent.hostname}')"></i>
                        </td>
                    </tr>
                `;
            });
            tbody.innerHTML = newHtml;
            // 264: Nakreslit mini CPU/RAM sparklines pro každého agenta
            _drawAgentListSparklines(data.agents || []);
        }
    } catch(e) {
        if (!isAutoRefresh) {
            tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px; color:var(--error);">${t('api_load_error')}</td></tr>`;
        }
    }
}

async function _drawAgentListSparklines(agents) {
    if (!window.Chart) return;
    for (const agent of agents) {
        const id = agent.hostname.replace(/[^a-z0-9]/gi, '-');
        const cpuCanvas = document.getElementById(`sp-${id}-cpu`);
        const ramCanvas = document.getElementById(`sp-${id}-ram`);
        if (!cpuCanvas && !ramCanvas) continue;
        try {
            const r = await fetch(`/api/agents/${encodeURIComponent(agent.hostname)}/telemetry?days=1`);
            const d = await r.json();
            const telem = d.telemetry || [];
            const cpuVals = telem.filter(t => t.metric.includes('cpu')).map(t => t.value).slice(-12);
            const ramVals = telem.filter(t => t.metric.includes('mem') || t.metric.includes('ram')).map(t => t.value).slice(-12);
            const _mini = (canvas, vals, color) => {
                if (!canvas || !vals.length) return;
                if (canvas._chart) { canvas._chart.destroy(); }
                canvas._chart = new Chart(canvas, {
                    type: 'line',
                    data: { labels: vals.map((_,i) => i), datasets: [{ data: vals, borderColor: color, borderWidth: 1.5, pointRadius: 0, fill: false }] },
                    options: { animation: false, plugins: { legend: { display: false } }, scales: { x: { display: false }, y: { display: false } } }
                });
            };
            _mini(cpuCanvas, cpuVals, '#4ade80');
            _mini(ramCanvas, ramVals, '#60a5fa');
        } catch {}
    }
}

async function toggleAgentIgnoreOffline(hostname, currentIgnored) {
    try {
        const res = await fetch('/api/agents/ignore_offline', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ hostname: hostname, ignore: !currentIgnored })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            loadAgentsList(false);
            updateAgentsMgrBadge();
        } else {
            alert(t('api_comm_error') + ' ' + (data.message || ''));
        }
    } catch(e) {
        alert(t('api_comm_error'));
    }
}

async function registerAgentSubmit() {
    const hostnameInput = document.getElementById('agent-reg-hostname');
    const hostname = hostnameInput.value.trim();

    if(!hostname) {
        alert(t('enter_valid_hostname'));
        return;
    }

    try {
        const res = await fetch('/api/agents/register', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ hostname: hostname })
        });
        const data = await res.json();

        if(data.status === 'ok') {
            hostnameInput.value = '';
            showTokenModal(hostname, data.token);
            loadAgentsList(false);
        } else {
            alert(t('register_failed', {msg: data.message || 'Unknown error'}));
        }
    } catch(e) {
        alert(t('api_write_error'));
    }
}

async function deleteAgentSubmit(hostname) {
    if(!confirm(t('confirm_remove_agent', {hostname}))) return;

    try {
        const res = await fetch('/api/agents/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ hostname: hostname })
        });
        const data = await res.json();
        if(data.status === 'ok') {
            loadAgentsList(false);
        } else {
            alert(t('remove_failed'));
        }
    } catch(e) {
        alert(t('api_error'));
    }
}

// ==========================================================================
// SENTINEL-ALERT NETWORK (multi-agent LAN monitor + honeypot)
// ==========================================================================
let saRefreshInterval = null;
let saNetworkData = null;
let saLoadingInProgress = false;

async function fetchSentinelAlertNetwork() {
    try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 5000);
        const res = await fetch('/api/sentinel-alerts/list', { signal: controller.signal });
        clearTimeout(timeout);
        if (!res.ok) {
            console.error('fetchSentinelAlertNetwork failed:', res.status, res.statusText);
            return null;
        }
        const data = await res.json();
        return (data && data.status === 'ok') ? data : null;
    } catch(e) {
        console.error('fetchSentinelAlertNetwork error:', e.message);
        return null;
    }
}

async function updateSentinelAlertBadge() {
    const badge = document.getElementById('sentinel-alert-status-indicator');
    if (!badge) return;
    const span = badge.querySelector('span');

    // Fetch both alert nodes and HW devices
    const [alertData, hwRes] = await Promise.allSettled([
        fetchSentinelAlertNetwork(),
        fetch('/api/sentinel-hw/list', {signal: AbortSignal.timeout(5000)}).then(r => r.json()).catch(() => null)
    ]);

    const alertAgents = (alertData.status === 'fulfilled' && alertData.value?.agents) ? alertData.value.agents : [];
    const hwDevices   = (hwRes.status === 'fulfilled' && hwRes.value?.devices) ? hwRes.value.devices : [];

    const allNodes   = [...alertAgents, ...hwDevices];
    const monitored  = allNodes.filter(n => !n.ignore_offline);
    const monTotal   = monitored.length;
    const online     = monitored.filter(n => n.online).length;
    const displayCnt = allNodes.length;

    if (displayCnt === 0) {
        badge.style.background = 'rgba(255,255,255,0.05)';
        badge.style.color = '#aaa';
        badge.style.border = '1px solid #444';
        badge.style.animation = 'none';
        if (span) span.innerText = ' 0';
    } else {
        if (monTotal === 0 || online === monTotal) {
            badge.style.background = 'rgba(255,255,255,0.05)';
            badge.style.color = 'var(--success)';
            badge.style.border = '1px solid #444';
            badge.style.animation = 'none';
        } else if (online > 0) {
            badge.style.background = 'rgba(255,165,0,0.2)';
            badge.style.color = '#ffa500';
            badge.style.border = '1px solid #ffa500';
            badge.style.animation = 'none';
        } else {
            badge.style.background = 'var(--error)';
            badge.style.color = 'white';
            badge.style.border = 'none';
            badge.style.animation = 'pulse 1.5s infinite';
        }
        if (span) span.innerText = ` ${displayCnt}`;
    }
}

function openSentinelAlertModal() {
    document.getElementById('sentinel-alert-modal').style.display = 'flex';
    switchSatTab('alert');
    if (saRefreshInterval) clearInterval(saRefreshInterval);
    saRefreshInterval = setInterval(loadSentinelAlertAgents, 30000);
}

function closeSentinelAlertModal() {
    document.getElementById('sentinel-alert-modal').style.display = 'none';
    if (saRefreshInterval) { clearInterval(saRefreshInterval); saRefreshInterval = null; }
    if (agentRefreshInterval) { clearInterval(agentRefreshInterval); agentRefreshInterval = null; }
}

async function loadSentinelAlertAgents() {
    const tbody = document.getElementById('sa-agents-tbody');
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px; color:#666;"><i class="fa-solid fa-spinner fa-spin"></i> ${t('loading')}</td></tr>`;
    try {
        const res = await fetch('/api/sentinel-alerts/list');
        const data = await res.json();
        if (!data || data.status !== 'ok') {
            tbody.innerHTML = `<tr><td colspan="5" style="padding:20px; color:var(--error); text-align:center;">${t('api_load_error')}</td></tr>`;
            return;
        }
        if (!data.agents || data.agents.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" style="padding:20px; text-align:center; color:#888;">${t('no_agents_registered')}</td></tr>`;
            return;
        }
        let html = '';
        data.agents.forEach(agent => {
            const statusColor = agent.online ? 'var(--success)' : 'var(--error)';
            const statusTxt = agent.online ? '🟢 Online' : '🔴 Offline';
            const lastSeen = agent.last_seen ? new Date(agent.last_seen).toLocaleString('cs-CZ') : '—';
            const ignored  = !!agent.ignore_offline;
            const bellIcon = ignored
                ? `<i class="fa-solid fa-bell-slash" style="color:var(--text-muted);" title="Offline ignorováno (kliknout pro zapnutí hlášení)"></i>`
                : `<i class="fa-solid fa-bell" style="color:var(--success);" title="Ignorovat offline stav"></i>`;
            const safeUrl = (agent.web_ui_url || '').replace(/'/g, "\\'");
            html += `
                <tr style="border-bottom:1px solid var(--border); ${ignored ? 'opacity:0.65;' : ''}">
                    <td style="padding:10px; font-weight:bold; cursor:pointer;" onclick="openDeviceDetailModal('${agent.hostname}', 'alert', '${safeUrl}')">
                        <i class="fa-solid fa-tower-broadcast" style="color:var(--accent); margin-right:5px;"></i>${agent.hostname}
                    </td>
                    <td style="padding:10px;"><span style="color:${statusColor}; font-weight:bold;">${statusTxt}</span>${ignored && !agent.online ? ' <span style="font-size:0.75em;color:var(--text-muted);">(ignorováno)</span>' : ''}</td>
                    <td style="padding:10px; font-family:monospace; color:#aaa; font-size:0.85em;">${lastSeen}</td>
                    <td style="padding:10px; text-align:center; color:${agent.active_issues > 0 ? 'var(--error)' : 'var(--success)'}; font-weight:bold;">${agent.active_issues}</td>
                    <td style="padding:10px; text-align:center; display:flex; gap:6px; justify-content:center;" onclick="event.stopPropagation()">
                        <span style="cursor:pointer;" onclick="toggleAgentIgnoreOffline('${agent.hostname}', ${ignored}).then(loadSentinelAlertAgents)">${bellIcon}</span>
                        <button onclick="setSAUrl('${agent.hostname}', '${safeUrl}')" style="padding:4px 8px; font-size:0.75em; background:transparent; border:1px solid #666; cursor:pointer;" title="Nastavit URL"><i class="fa-solid fa-link"></i></button>
                        ${agent.has_token ? `<button onclick="revokeTokenSA('${agent.hostname}')" style="padding:4px 8px; font-size:0.75em; background:transparent; border:1px solid #666; cursor:pointer;" title="Zneplatnit token"><i class="fa-solid fa-ban"></i></button>` : ''}
                        <button onclick="deleteAgentSA('${agent.hostname}')" style="padding:4px 8px; font-size:0.75em; background:transparent; border:1px solid var(--error); color:var(--error); cursor:pointer;" title="${t('delete_agent_title')}"><i class="fa-solid fa-trash"></i></button>
                    </td>
                </tr>
            `;
        });
        tbody.innerHTML = html;
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="5" style="padding:20px; color:var(--error); text-align:center;">${t('load_error_detail', {msg: e.message})}</td></tr>`;
    }
}

async function showSACredentials(hostname) {
    const modal = document.getElementById('sa-credentials-modal');
    const urlEl = document.getElementById('sa-cred-url');
    const tokenEl = document.getElementById('sa-cred-token');

    const data = await fetchSentinelAlertNetwork();
    if (data && data.ingest_url) {
        urlEl.innerText = data.ingest_url;
    }

    // Security: tokens are NEVER stored/retrievable after generation
    // Only show if just generated (in registerNewSentinelAlert flow)
    tokenEl.innerText = t('token_shown_once');

    modal.style.display = 'flex';
}

function closeSACredsModal() {
    document.getElementById('sa-credentials-modal').style.display = 'none';
}

function copySAUrl() {
    const el = document.getElementById('sa-cred-url');
    const text = el.innerText.trim();
    if (text && text !== '—') safeCopyText(text);
}

function copySAToken() {
    const el = document.getElementById('sa-cred-token');
    const text = el.innerText.trim();
    if (text && text !== '—' && !text.includes('(')) safeCopyText(text);
}

async function registerNewSentinelAlert() {
    const input    = document.getElementById('sa-new-hostname');
    const urlInput = document.getElementById('sa-new-url');
    const hostname = input.value.trim();
    const web_ui_url = (urlInput?.value || '').trim();
    if (!hostname) { alert(t('enter_valid_hostname')); return; }

    try {
        const res = await fetch('/api/agents/register', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ hostname, web_ui_url, category: 'alert' })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            input.value = '';
            if (urlInput) urlInput.value = '';
            showTokenModal(hostname, data.token);
            loadSentinelAlertAgents();
            updateSentinelAlertBadge();
        } else {
            alert(t('registration_error', {msg: data.message || 'Unknown'}));
        }
    } catch(e) { alert(t('api_error')); }
}

function copyToClipboard(el) {
    const r = document.createRange();
    r.selectNode(el);
    window.getSelection().removeAllRanges();
    window.getSelection().addRange(r);
    try { document.execCommand('copy'); } catch(e) {}
}

async function regenerateTokenSA(hostname) {
    if (!confirm(`Přegenerovat token pro '${hostname}'?`)) return;
    try {
        const res = await fetch('/api/agents/register', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ hostname })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            alert(`✓ Token pro ${hostname}:\n\n${data.token}\n\nVložte do konfigurace. Zobrazí se pouze nyní.`);
            loadSentinelAlertAgents();
            updateSentinelAlertBadge();
        } else {
            alert(t('api_comm_error') + ' ' + (data.message || ''));
        }
    } catch(e) { alert(t('api_error')); }
}

async function revokeTokenSA(hostname) {
    if (!confirm(`Vygenerovat nový token pro '${hostname}'?`)) return;
    try {
        const res = await fetch(`/api/sentinel-alert/${hostname}/revoke-token`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        const data = await res.json();
        if (data.status === 'ok') {
            loadSentinelAlertAgents();
            updateSentinelAlertBadge();
            showTokenModal(hostname, data.token);
        } else {
            alert(t('api_comm_error') + ' ' + (data.message || ''));
        }
    } catch(e) { alert(t('api_error')); }
}

async function deleteAgentSA(hostname) {
    if (!confirm(t('confirm_delete_agent', {hostname}))) return;
    try {
        const res = await fetch('/api/agents/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ hostname })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            loadSentinelAlertAgents();
            updateSentinelAlertBadge();
        } else {
            alert(t('api_comm_error') + ' ' + (data.message || ''));
        }
    } catch(e) { alert(t('api_error')); }
}

async function setSAUrl(hostname, currentUrl) {
    const url = prompt(`URL pro ${hostname}:`, currentUrl || '');
    if (url === null) return;
    try {
        const res = await fetch(`/api/sentinel-alert/${encodeURIComponent(hostname)}/set-url`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ url })
        });
        const d = await res.json();
        if (d.status === 'ok') loadSentinelAlertAgents();
        else alert(t('api_comm_error') + ' ' + (d.message || ''));
    } catch(e) { alert(t('api_error')); }
}

function copySentinelAlertUrl() {
    const el = document.getElementById('sa-ingest-url');
    if (!el) return;
    const text = el.innerText.trim();
    if (!text || text === '—') return;
    safeCopyText(text);
}

