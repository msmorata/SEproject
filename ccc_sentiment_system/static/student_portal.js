// SECURITY FIX: XSS Protection and URL Sanitization
const _E = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => _E[c]);
const safeUrl = u => { try { const x = new URL(u, window.location.origin); return (x.protocol === 'https:' || x.protocol === 'http:') ? x.href : ''; } catch { return ''; } };
const safeImg = u => (/^data:image\/(png|jpe?g|gif|webp);base64,[A-Za-z0-9+/=]+$/.test(u || '') ? u : safeUrl(u));
const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]')?.content || '';

// ==========================================================
// SYSTEM ALERTS & TOAST NOTIFICATIONS
// ==========================================================
const SYS_ALERT_ICONS = {
    error: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    success: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><polyline points="8 12.5 11 15.5 16 9"/></svg>',
    info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>'
};
const SYS_ALERT_TITLES = { error: 'Something went wrong', warning: 'Please check this' };
const _SYS_RE_ERROR = /\b(fail(ed|ure|s)?|error|could not|couldn't|unable|invalid|denied|permission|not allowed|went wrong|unavailable|too long|too large|expired|not found|conflict|duplicate|malformed|time(d)? ?out|try again|too many|busy)\b/i;
const _SYS_RE_WARN = /\b(please|required|must|select|choose|input|enter|missing|locked|cannot|can't)\b/i;
const _SYS_RE_OK = /\b(success(fully)?|added|stored|removed|completed|registered|saved|created|updated|posted|deleted|sent|exported|downloaded)\b/i;

function _sysClassify(msg) {
    if (_SYS_RE_ERROR.test(msg)) return 'error';
    if (_SYS_RE_WARN.test(msg)) return 'warning';
    if (_SYS_RE_OK.test(msg)) return 'success';
    return 'info';
}

let _sysAlertOpen = false, _sysAlertCurrent = null, _sysAlertFocus = null, _sysAlertEls = null;
const _sysAlertQueue = [];

function _sysAlertDom() {
    if (_sysAlertEls) return _sysAlertEls;
    const ov = document.createElement('div');
    ov.className = 'sys-alert-overlay';
    ov.setAttribute('role', 'alertdialog');
    ov.setAttribute('aria-modal', 'true');
    ov.setAttribute('aria-labelledby', 'sysAlertTitle');
    ov.setAttribute('aria-describedby', 'sysAlertMsg');
    ov.innerHTML = '<div class="sys-alert-card"><div class="sys-alert-icon"></div><h3 class="sys-alert-title" id="sysAlertTitle"></h3><p class="sys-alert-msg" id="sysAlertMsg"></p><div class="sys-alert-more"></div><button type="button" class="sys-alert-btn">Got it</button></div>';
    document.body.appendChild(ov);
    _sysAlertEls = { ov, card: ov.firstChild, icon: ov.querySelector('.sys-alert-icon'), title: ov.querySelector('.sys-alert-title'), msg: ov.querySelector('.sys-alert-msg'), more: ov.querySelector('.sys-alert-more'), btn: ov.querySelector('.sys-alert-btn') };
    _sysAlertEls.btn.addEventListener('click', closeSysAlert);
    ov.addEventListener('mousedown', (e) => { if (e.target === ov) closeSysAlert(); });
    ov.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') { e.stopPropagation(); closeSysAlert(); }
        else if (e.key === 'Tab') { e.preventDefault(); _sysAlertEls.btn.focus(); }
    });
    return _sysAlertEls;
}

function _sysAlertMoreLabel() {
    const n = _sysAlertQueue.length;
    return n ? (n === 1 ? '1 more message after this' : n + ' more messages after this') : '';
}

function _sysAlertRender(msg, kind) {
    const d = _sysAlertDom();
    _sysAlertCurrent = { msg, kind };
    d.card.className = 'sys-alert-card type-' + kind;
    d.icon.innerHTML = SYS_ALERT_ICONS[kind];
    d.title.textContent = SYS_ALERT_TITLES[kind];
    d.msg.textContent = msg;
    d.more.textContent = _sysAlertMoreLabel();
    d.ov.style.display = 'flex';
    void d.ov.offsetWidth;
    d.ov.classList.add('is-open');
    _sysAlertOpen = true;
    d.btn.focus();
}

function _sysAlertShow(msg, kind) {
    if (_sysAlertOpen) {
        const same = (a) => a.msg === msg && a.kind === kind;
        if (same(_sysAlertCurrent) || _sysAlertQueue.some(same)) return;
        _sysAlertQueue.push({ msg, kind });
        _sysAlertEls.more.textContent = _sysAlertMoreLabel();
        return;
    }
    _sysAlertFocus = document.activeElement;
    _sysAlertRender(msg, kind);
}

function closeSysAlert() {
    if (!_sysAlertOpen) return;
    const d = _sysAlertEls;
    d.ov.classList.remove('is-open');
    _sysAlertOpen = false;
    if (_sysAlertQueue.length) {
        const next = _sysAlertQueue.shift();
        setTimeout(() => { if (!_sysAlertOpen) _sysAlertRender(next.msg, next.kind); }, 230);
        return;
    }
    setTimeout(() => { if (!_sysAlertOpen) d.ov.style.display = 'none'; }, 220);
    try { if (_sysAlertFocus && _sysAlertFocus.focus) _sysAlertFocus.focus(); } catch (e) {}
}

let _toastTimer;
function _sysToastShow(msg, kind) {
    const t = document.getElementById('toast');
    if (!t) return;
    t.className = 'toast-' + kind;
    t.innerHTML = '<span class="sys-toast-ic">' + SYS_ALERT_ICONS[kind] + '</span><span class="sys-toast-tx"></span>';
    t.querySelector('.sys-toast-tx').textContent = msg;
    t.style.display = 'flex';
    void t.offsetWidth;
    t.classList.add('show');
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => {
        t.classList.remove('show');
        setTimeout(() => { if (!t.classList.contains('show')) t.style.display = 'none'; }, 260);
    }, 3500);
}

function showToast(msg, type) {
    msg = (msg === null || msg === undefined) ? '' : String(msg).trim();
    if (!msg) return;
    const kind = (type === 'error' || type === 'warning' || type === 'success' || type === 'info') ? type : _sysClassify(msg);
    if (kind === 'error' || kind === 'warning') _sysAlertShow(msg, kind);
    else _sysToastShow(msg, kind);
}
window.showToast = showToast;
window.closeSysAlert = closeSysAlert;

// ==========================================================
// THEME TOGGLE, SESSION GUARD, SAFE NETWORK LAYER
// ==========================================================
const THEME_KEY = 'ccc_theme';
function currentTheme() { return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark'; }
function applyTheme(theme, persist = true, notify = true) {
    const t = theme === 'light' ? 'light' : 'dark';
    const changed = currentTheme() !== t;
    document.documentElement.setAttribute('data-theme', t);
    if (persist) { try { localStorage.setItem(THEME_KEY, t); } catch (e) { /* storage blocked */ } }
    const btn = document.getElementById('themeToggle');
    if (btn) {
        const next = t === 'light' ? 'dark' : 'light';
        btn.textContent = t === 'light' ? '\uD83C\uDF19' : '\u2600\uFE0F';
        btn.setAttribute('aria-pressed', String(t === 'light'));
        btn.setAttribute('aria-label', 'Switch to ' + next + ' mode');
        btn.title = 'Switch to ' + next + ' mode';
    }
    if (notify && changed) document.dispatchEvent(new CustomEvent('themechange', { detail: { theme: t } }));
}
function toggleTheme() {
    const root = document.documentElement;
    root.classList.add('theme-anim');
    setTimeout(() => root.classList.remove('theme-anim'), 350);
    applyTheme(currentTheme() === 'light' ? 'dark' : 'light');
}
window.addEventListener('storage', (e) => { if (e.key === THEME_KEY && e.newValue) applyTheme(e.newValue, false); });
applyTheme(currentTheme(), false, false);

// STRICT BROWSER CACHE / BACK BUTTON LOCKOUT
let _redirectingToLogin = false;
function forceLogin(msg) {
    if (_redirectingToLogin) return;
    _redirectingToLogin = true;
    document.documentElement.style.visibility = 'hidden';
    if (msg) showToast(msg, 'warning');
    window.location.replace('/login');
}

// BFCache (Back-Forward Cache) mitigation
async function verifySession() {
    try {
        const r = await fetch('/api/session_ping', { cache: 'no-store', credentials: 'same-origin' });
        if (r.status === 401 || r.redirected) { forceLogin(); return false; }
        return r.ok;
    } catch (e) { return false; }
}

window.addEventListener('pageshow', function (event) {
    const nav = (performance.getEntriesByType && performance.getEntriesByType('navigation')[0]) || null;
    // If the page is loaded from cache (e.g. Back button spam)
    if (event.persisted || (nav && nav.type === 'back_forward')) {
        document.documentElement.style.visibility = 'hidden'; // Immediately hide sensitive data
        verifySession().then(ok => {
            if (ok) {
                document.documentElement.style.visibility = ''; // Safe, show it
            } else if (!_redirectingToLogin) {
                window.location.reload(); // Force a fresh load so the server handles the 401
            }
        });
    }
});

document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') verifySession(); });

function friendlyStatus(s) {
    if (s === 401) return 'Your session has expired. Please sign in again.';
    if (s === 403) return 'You do not have permission to do that.';
    if (s === 404) return 'The requested item was not found.';
    if (s === 413) return 'That upload or post is too large.';
    if (s === 429) return 'Too many requests. Please wait a moment and try again.';
    if (s >= 500) return 'The server ran into a problem. Please try again shortly.';
    return 'The request could not be completed.';
}

async function apiFetch(url, options = {}, timeoutMs = 30000) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    let res;
    try {
        res = await fetch(url, { credentials: 'same-origin', ...options, signal: ctrl.signal });
    } catch (err) {
        const msg = (err && err.name === 'AbortError') ? 'The server took too long to respond. Please try again.' : (navigator.onLine === false ? 'You appear to be offline. Check your connection and try again.' : 'Could not reach the server. Please try again.');
        const e = new Error(msg); e.userMessage = msg; e.network = true; throw e;
    } finally { clearTimeout(timer); }
    const _json = res.json.bind(res);
    res.json = async () => { try { return await _json(); } catch (e) { return { error: friendlyStatus(res.status) }; } };
    if (res.status === 401) forceLogin('Your session has expired. Redirecting to sign in...');
    return res;
}

async function readJson(res, fallback = 'Request failed.') {
    const data = await res.json();
    if (!res.ok) { const e = new Error((data && data.error) || fallback); e.userMessage = e.message; throw e; }
    return data;
}

async function downloadFile(url, fallbackName) {
    showLoader("Preparing download...");
    try {
        const res = await apiFetch(url);
        if (!res.ok) { const d = await res.json(); throw Object.assign(new Error(d.error || 'Download failed.'), { userMessage: d.error || 'Download failed.' }); }
        const blob = await res.blob();
        const m = /filename="?([^";]+)"?/i.exec(res.headers.get('Content-Disposition') || '');
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = m ? m[1] : fallbackName;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    } catch (e) { showToast(e.userMessage || e.message || 'Download failed.', 'error'); } finally { hideLoader(); }
}

window.addEventListener('unhandledrejection', (ev) => {
    console.error('Unhandled promise rejection:', ev.reason);
    try { showToast((ev.reason && ev.reason.userMessage) || 'Something went wrong. Please try again.', 'error'); } catch (e) {}
    ev.preventDefault();
});

// UI/UX OVERHAUL: Shared smooth modal open/close
function openModal(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.style.display = 'flex';
    requestAnimationFrame(() => el.classList.add('modal-open'));
}
function closeModal(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('modal-open');
    setTimeout(() => { if (!el.classList.contains('modal-open')) el.style.display = 'none'; }, 220);
}
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { document.querySelectorAll('.modal-overlay.modal-open').forEach(el => closeModal(el.id)); }
});

// BACK-BUTTON LOCK
// A single sentinel history entry is not enough: a quick burst of Back presses can register twice before the handler re-arms it,
// which dropped people onto the page they signed in from. So we keep a buffer of sentinel entries and top it back up after every Back/Forward.
const _GUARD_DEPTH = 6;
let _guardTop = 0, _guardToastAt = 0, _guardGestureDone = false;
function _guardLevel() { const st = history.state; return (st && st.portalGuard && typeof st.guardLevel === 'number') ? st.guardLevel : -1; }
function _guardFill() {
    try { for (let n = _guardLevel() + 1; n <= _guardTop; n++) history.pushState({ portalGuard: true, guardLevel: n }, document.title, location.href); } catch (e) { /* history API blocked */ }
}
try { history.replaceState({ portalGuard: true, guardLevel: 0 }, document.title, location.href); } catch (e) { /* history API blocked */ }
_guardTop = _GUARD_DEPTH;
_guardFill();
// Browsers skip history entries that a page added before the visitor interacted with it, so add a second set on the first real interaction.
['pointerdown', 'keydown', 'touchstart'].forEach(function (evt) {
    window.addEventListener(evt, function () {
        if (_guardGestureDone || window._loggingOut) return;
        _guardGestureDone = true;
        _guardTop += _GUARD_DEPTH;
        _guardFill();
    }, { passive: true, capture: true });
});
window.addEventListener('popstate', function () {
    if (window._loggingOut) return;
    _guardFill();
    const now = Date.now();
    if (now - _guardToastAt > 2000) {   // a burst of Back presses should produce one notice, not a pile of them
        _guardToastAt = now;
        showToast("Active portal session locked. Please use 'Sign Out' to leave.", 'info');
    }
});

function dismissSplash() {
    const splash = document.getElementById('splashCurtain');
    if (!splash || splash.classList.contains('dissolve')) return;
    splash.classList.add('dissolve');
    setTimeout(() => { splash.style.display = 'none'; }, 900);
}

// The intro now runs by itself: the bar follows the real loading, then the screen fades into the portal. No click needed.
const SPLASH_SEEN_KEY = 'ccc_student_splash_seen';
function _splashProgress(p) { const f = document.querySelector('.splash-loader-fill'); if (f) f.style.transform = `scaleX(${p})`; }
function runSplash(initialLoad) {
    const splash = document.getElementById('splashCurtain');
    if (!splash) return Promise.resolve();
    try {
        if (sessionStorage.getItem(SPLASH_SEEN_KEY) === 'true') { splash.style.display = 'none'; return Promise.resolve(); }   // already shown in this visit: refreshing goes straight in
        sessionStorage.setItem(SPLASH_SEEN_KEY, 'true');
    } catch (e) { /* storage blocked: just show the intro */ }
    const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const MIN_MS = reduced ? 500 : 1900, MAX_MS = 4500, started = performance.now();
    setTimeout(() => _splashProgress(0.3), 150);
    setTimeout(() => _splashProgress(0.6), 800);
    return Promise.race([initialLoad, new Promise(r => setTimeout(r, MAX_MS))]).then(() => new Promise(resolve => {
        _splashProgress(0.92);
        const wait = Math.max(0, MIN_MS - (performance.now() - started));
        setTimeout(() => { _splashProgress(1); setTimeout(() => { dismissSplash(); setTimeout(resolve, 950); }, 450); }, wait);
    }));
}

// Global scope variables
const currentUserRole = window.APP_USER_ROLE || 'Student - Regular';
const currentUserDept = window.APP_USER_DEPT || 'DCI';
const roleLower = currentUserRole.toLowerCase();
const isAuthorizedAnnouncer = roleLower.includes('officer') || roleLower.includes('representative') || roleLower.includes('rep') || roleLower.includes('faculty') || roleLower.includes('misd');

let activeChannel = "ALL";
let activeFormUnderFill = null;
let feedPostsCache = [];
const attachedImages = { town: null, edit: null };
let pendingPostPayload = null;
let allFormsCache = [];
let currentFormTab = 'Available';
let currentFormSearch = "";
let currentFeedSearch = "";

let _loaderTimer;
function showLoader(msg = "Processing Feedback...", timeoutMs = 30000) {
    const textEl = document.getElementById('loaderText');
    if(textEl) textEl.innerText = msg;
    const loaderEl = document.getElementById('loader');
    if(loaderEl) loaderEl.style.display = 'flex';
    clearTimeout(_loaderTimer);
    _loaderTimer = setTimeout(() => { hideLoader(); showToast("The request is taking too long. Please check your connection or try again.", "warning"); }, timeoutMs);
}
function hideLoader() { 
    clearTimeout(_loaderTimer); 
    const loaderEl = document.getElementById('loader');
    if(loaderEl) loaderEl.style.display = 'none'; 
}

function toggleMobileDrawer() {
    const sidebar = document.getElementById('portalSidebar');
    const backdrop = document.getElementById('sidebarDrawerBackdrop');
    if (!sidebar || !backdrop) return;
    const isOpen = sidebar.classList.contains('drawer-open');
    if (isOpen) closeMobileDrawer(); else openMobileDrawer();
}

function openMobileDrawer() {
    const sidebar = document.getElementById('portalSidebar');
    const backdrop = document.getElementById('sidebarDrawerBackdrop');
    if (sidebar) sidebar.classList.add('drawer-open');
    if (backdrop) backdrop.classList.add('active');
}

function closeMobileDrawer() {
    const sidebar = document.getElementById('portalSidebar');
    const backdrop = document.getElementById('sidebarDrawerBackdrop');
    if (sidebar) sidebar.classList.remove('drawer-open');
    if (backdrop) backdrop.classList.remove('active');
}

// ==========================================================
// ANNOUNCEMENT EXPIRATION & DATE PICKERS
// ==========================================================
function _expEls(prefix) {
    return {
        date: document.getElementById(prefix + 'PickerDatePart'),
        time: document.getElementById(prefix + 'PickerTimePart'),
        hidden: document.getElementById(prefix + 'ExpirationDate'),
        badge: document.getElementById(prefix + 'DeadlineFormattedBadge'),
        label: document.getElementById(prefix + 'DeadlineFormattedText')
    };
}

function _openPicker(el) {
    if (!el) return;
    try { if (el.showPicker) { el.showPicker(); return; } } catch (e) {}
    el.focus();
}

function _syncExpiry(prefix) {
    const e = _expEls(prefix);
    if (!e.date || !e.hidden) return;
    if (!e.date.value) {
        e.hidden.value = '';
        if (e.badge) e.badge.style.display = 'none';
        return;
    }
    if (e.time && !e.time.value) e.time.value = '23:59';

    const now = new Date();
    const todayISO = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    if (e.time) {
        if (e.date.value === todayISO) {
            const nowHM = now.toTimeString().slice(0, 5);
            e.time.min = nowHM;
            if (e.time.value < nowHM) e.time.value = nowHM;
        } else {
            e.time.removeAttribute('min');
        }
    }

    const combined = `${e.date.value}T${e.time ? e.time.value : '23:59'}`;
    e.hidden.value = combined;
    e.date.classList.toggle('input-error', e.date.value < todayISO);
    if (e.badge) e.badge.style.display = 'flex';
    if (e.label) e.label.innerText = `Expires: ${formatDeadlineDisplay(combined)}`;
}

function _clearExpiry(prefix) {
    const e = _expEls(prefix);
    if (e.date) { e.date.value = ''; e.date.classList.remove('input-error'); }
    if (e.time) e.time.value = '23:59';
    if (e.hidden) e.hidden.value = '';
    if (e.badge) e.badge.style.display = 'none';
}

function _dateSelected(prefix, val) {
    if (!val) return _clearExpiry(prefix);
    _syncExpiry(prefix);
}

function _setExpiryMin(prefix) {
    const d = document.getElementById(prefix + 'PickerDatePart');
    if (!d) return;
    const now = new Date();
    d.min = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function _validateExpiry(prefix) {
    const e = _expEls(prefix);
    if (!e.hidden || !e.hidden.value) return true;
    const [d, t] = e.hidden.value.split('T');
    const [y, m, day] = d.split('-').map(Number);
    const [hh, mm] = (t || '23:59').split(':').map(Number);
    if (new Date(y, m - 1, day, hh, mm) < new Date()) {
        if (e.date) e.date.classList.add('input-error');
        showToast('Expiration must be a date and time that has not passed yet.', 'warning');
        return false;
    }
    if (e.date) e.date.classList.remove('input-error');
    return true;
}

function _loadExpiryIntoPicker(prefix, stored) {
    _clearExpiry(prefix);
    if (!stored) return;
    const [d, t] = stored.split('T');
    const e = _expEls(prefix);
    if (e.date) e.date.value = d;
    if (e.time) e.time.value = t || '23:59';
    _syncExpiry(prefix);
}

function formatDeadlineDisplay(dStr) {
    if (!dStr || dStr === 'No Expiry' || dStr === 'None') return 'No Expiry';
    try {
        if (dStr.includes('T')) {
            const [datePart, timePart] = dStr.split('T');
            const [yr, mo, da] = datePart.split('-');
            const [hr, mi] = timePart.split(':');
            const d = new Date(yr, mo - 1, da, hr, mi);
            return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) + 
                   ' • ' + d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
        } else if (dStr.includes('-')) {
            const [yr, mo, da] = dStr.split('-');
            const d = new Date(yr, mo - 1, da);
            return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        }
    } catch (e) { return dStr; }
    return dStr;
}

// Aliases for Townhall Compose Modal
function triggerTownCalendarPicker() { _openPicker(document.getElementById('townPickerDatePart')); }
function triggerTownClockPicker()    { _openPicker(document.getElementById('townPickerTimePart')); }
function handleTownDateSelected(v)   { _dateSelected('town', v); }
function syncTownDeadlineValue()     { _syncExpiry('town'); }
function clearTownDeadlineSelection(){ _clearExpiry('town'); }

// Aliases for Edit Modal
function triggerEditCalendarPicker() { _openPicker(document.getElementById('editPickerDatePart')); }
function triggerEditClockPicker()    { _openPicker(document.getElementById('editPickerTimePart')); }
function handleEditDateSelected(v)   { _dateSelected('edit', v); }
function syncEditDeadlineValue()     { _syncExpiry('edit'); }
function clearEditDeadlineSelection(){ _clearExpiry('edit'); }

// Aliases for Survey Form Modal (uses 'picker' without prefix, handled manually)
function triggerCalendarPicker() { _openPicker(document.getElementById('pickerDatePart')); }
function triggerClockPicker()    { _openPicker(document.getElementById('pickerTimePart')); }
function handleDateSelected(v) {
    if (!v) return clearDeadlineSelection();
    const timeInp = document.getElementById('pickerTimePart');
    if (!timeInp.value) timeInp.value = "23:59";
    syncDeadlineValue();
    setTimeout(() => { triggerClockPicker(); }, 250);
}
function syncDeadlineValue() {
    const dateVal = document.getElementById('pickerDatePart').value;
    const timeInp = document.getElementById('pickerTimePart');
    const hidden = document.getElementById('newFormDeadline');
    const badge = document.getElementById('deadlineFormattedBadge');
    const label = document.getElementById('deadlineFormattedText');

    if (!dateVal) { badge.style.display = 'none'; hidden.value = ''; return; }

    const now = new Date();
    const todayISO = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    if (dateVal === todayISO) {
        const nowHM = now.toTimeString().slice(0, 5);
        timeInp.min = nowHM;
        if (timeInp.value && timeInp.value < nowHM) timeInp.value = nowHM;
    } else {
        timeInp.removeAttribute('min');
    }

    const combined = `${dateVal}T${timeInp.value || '23:59'}`;
    hidden.value = combined;
    badge.style.display = 'flex';
    label.innerText = `Cutoff Set: ${formatDeadlineDisplay(combined)}`;
}
function clearDeadlineSelection() {
    document.getElementById('pickerDatePart').value = "";
    document.getElementById('pickerTimePart').value = "23:59";
    document.getElementById('newFormDeadline').value = "";
    document.getElementById('deadlineFormattedBadge').style.display = "none";
}

// ==========================================================
// FORM BUILDER & RENDERING
// ==========================================================
let formBuilderQuestions = [];

function initFormBuilder() {
    formBuilderQuestions = [
        { id: 1, type: "likert", prompt: "How satisfied are you with the pacing and clarity of this subject?", required: true, min_label: "Strongly Disagree", max_label: "Strongly Agree", elaboration_logic: "low", elaboration_prompt: "Please elaborate on what can be improved or what caused this rating:", elaboration_required: true },
        { id: 2, type: "narrative", prompt: "What general comments or suggestions would you like to share?", required: false }
    ];
    renderQuestionsBuilder();
}

function renderQuestionsBuilder() {
    const container = document.getElementById('questionsBuilderContainer');
    if (!container) return;
    container.innerHTML = '';

    formBuilderQuestions.forEach((q, idx) => {
        const card = document.createElement('div');
        card.className = 'q-card-item';
        card.id = `qBuilderCard_${idx}`;

        let typeLabel = '';
        if (q.type === 'narrative') typeLabel = '📝 Open Narrative';
        else if (q.type === 'likert') typeLabel = '⭐ Likert Scale (1 to 5)';
        else if (q.type === 'radio') typeLabel = '🔘 Single Choice';
        else if (q.type === 'checkbox') typeLabel = '☑️ Checkboxes';

        let specificControls = '';
        if (q.type === 'likert') {
            specificControls = `
                <div style="background:rgba(6,12,26,0.65); padding:10px; border-radius:var(--radius-sm); margin-top:8px;">
                    <div style="display:flex; justify-content:space-between; font-size:0.74rem; color:var(--text-muted); margin-bottom:6px;">
                        <span>Low (1): <input type="text" value="${esc(q.min_label || 'Poor')}" onchange="updateQField(${idx}, 'min_label', this.value)" style="background:transparent; border:none; border-bottom:1px solid #475569; color:var(--text-heading); width:90px;"></span>
                        <span>High (5): <input type="text" value="${esc(q.max_label || 'Excellent')}" onchange="updateQField(${idx}, 'max_label', this.value)" style="background:transparent; border:none; border-bottom:1px solid #475569; color:var(--text-heading); width:90px;"></span>
                    </div>
                    
                    <div style="border-top:1px dashed rgba(255,255,255,0.08); padding-top:8px; margin-top:6px;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; flex-wrap:wrap; gap:6px;">
                            <span style="font-size:0.74rem; color:var(--txt-blue); font-weight:700;">🔀 Follow-Up Logic:</span>
                            <select onchange="updateQField(${idx}, 'elaboration_logic', this.value); renderQuestionsBuilder();" class="select-input" style="width:auto; padding:3px 8px; margin-bottom:0; font-size:0.74rem;">
                                <option value="low" ${q.elaboration_logic === 'low' ? 'selected' : ''}>Show on Low (1★ - 2★)</option>
                                <option value="low_mid" ${q.elaboration_logic === 'low_mid' ? 'selected' : ''}>Show on Low & Mid (1★ - 3★)</option>
                                <option value="always" ${q.elaboration_logic === 'always' ? 'selected' : ''}>Always show</option>
                                <option value="none" ${q.elaboration_logic === 'none' ? 'selected' : ''}>None</option>
                            </select>
                        </div>
                        ${q.elaboration_logic !== 'none' ? `
                            <input type="text" value="${esc(q.elaboration_prompt || 'Please elaborate on your response or what could be improved:')}" oninput="updateQField(${idx}, 'elaboration_prompt', this.value)" class="text-input" placeholder="Custom prompt..." style="font-size:0.78rem; margin-bottom:5px;">
                            <label style="font-size:0.72rem; color:var(--txt-soft); display:flex; align-items:center; gap:5px; cursor:pointer;">
                                <input type="checkbox" ${q.elaboration_required ? 'checked' : ''} onchange="updateQField(${idx}, 'elaboration_required', this.checked)">
                                Make mandatory when triggered
                            </label>
                        ` : ''}
                    </div>
                </div>
            `;
        } else if (q.type === 'radio' || q.type === 'checkbox') {
            const optRows = (q.options || ['Option 1', 'Option 2']).map((opt, optIdx) => `
                <div class="option-choice-row">
                    <span style="font-size:0.8rem; color:var(--text-muted);">${q.type === 'radio' ? '○' : '□'}</span>
                    <input type="text" value="${esc(opt)}" onchange="updateQChoice(${idx}, ${optIdx}, this.value)" class="text-input" style="margin-bottom:0; padding:5px 8px; font-size:0.78rem;">
                    <button type="button" onclick="removeQChoice(${idx}, ${optIdx})" style="background:none; border:none; color:var(--txt-red); cursor:pointer; font-weight:bold;">✕</button>
                </div>
            `).join('');

            specificControls = `
                <div style="margin-top:8px;">
                    <div style="font-size:0.72rem; color:var(--text-muted); margin-bottom:4px;">Options List:</div>
                    ${optRows}
                    <button type="button" class="btn-nav" onclick="addQChoice(${idx})" style="font-size:0.7rem; margin-top:4px;">+ Add Choice Option</button>
                </div>
            `;
        }

        card.innerHTML = `
            <div class="q-card-top">
                <div style="display:flex; align-items:center; gap:6px;">
                    <strong style="font-size:0.82rem; color:var(--txt-blue);">Item #${idx + 1}</strong>
                    <span style="font-size:0.72rem; color:var(--text-muted);">${typeLabel}</span>
                </div>
                <div style="display:flex; align-items:center; gap:5px;">
                    <label style="font-size:0.72rem; color:var(--text-muted); display:flex; align-items:center; gap:3px; margin-right:4px; cursor:pointer;">
                        <input type="checkbox" ${q.required ? 'checked' : ''} onchange="toggleQRequired(${idx}, this.checked)">
                        Required
                    </label>
                    <button type="button" class="q-tool-btn" onclick="moveQuestionItem(${idx}, -1)" ${idx === 0 ? 'disabled' : ''}>▲</button>
                    <button type="button" class="q-tool-btn" onclick="moveQuestionItem(${idx}, 1)" ${idx === formBuilderQuestions.length - 1 ? 'disabled' : ''}>▼</button>
                    <button type="button" class="q-tool-btn" onclick="cloneQuestionItem(${idx})">📋</button>
                    <button type="button" class="q-tool-btn" onclick="removeQuestionItem(${idx})" style="color:var(--txt-red);">🗑️</button>
                </div>
            </div>
            <input type="text" id="qPromptInput_${idx}" class="text-input" value="${esc(q.prompt)}" oninput="updateQField(${idx}, 'prompt', this.value)" placeholder="Enter question prompt..." style="margin-bottom:0;">
            ${specificControls}
        `;
        container.appendChild(card);
    });
}

function addQuestionItem(type) {
    const nextId = formBuilderQuestions.length > 0 ? Math.max(...formBuilderQuestions.map(q => q.id || 0)) + 1 : 1;
    const newQ = { id: nextId, type: type, prompt: "", required: true };
    if (type === 'likert') {
        newQ.prompt = "Rate your overall satisfaction:";
        newQ.min_label = "Strongly Disagree";
        newQ.max_label = "Strongly Agree";
        newQ.elaboration_logic = "low";
        newQ.elaboration_prompt = "Please elaborate on what can be improved or what caused this rating:";
        newQ.elaboration_required = true;
    } else if (type === 'radio' || type === 'checkbox') {
        newQ.prompt = "Select an option:";
        newQ.options = ["Option 1", "Option 2"];
    } else {
        newQ.prompt = "Provide your honest constructive narrative feedback:";
    }
    formBuilderQuestions.push(newQ);
    renderQuestionsBuilder();
}

function moveQuestionItem(idx, dir) {
    const target = idx + dir;
    if (target < 0 || target >= formBuilderQuestions.length) return;
    const temp = formBuilderQuestions[idx];
    formBuilderQuestions[idx] = formBuilderQuestions[target];
    formBuilderQuestions[target] = temp;
    renderQuestionsBuilder();
}

function cloneQuestionItem(idx) {
    const original = formBuilderQuestions[idx];
    const cloned = JSON.parse(JSON.stringify(original));
    cloned.id = Math.max(...formBuilderQuestions.map(q => q.id || 0)) + 1;
    cloned.prompt = cloned.prompt ? cloned.prompt + " (Copy)" : "New Inquiry";
    formBuilderQuestions.splice(idx + 1, 0, cloned);
    renderQuestionsBuilder();
    showToast("Inquiry duplicated.", 'info');
}

function toggleQRequired(idx, isChecked) { formBuilderQuestions[idx].required = isChecked; }
function removeQuestionItem(idx) {
    if (formBuilderQuestions.length <= 1) return showToast("A survey must have at least one question.", 'warning');
    formBuilderQuestions.splice(idx, 1);
    renderQuestionsBuilder();
}
function updateQField(qIdx, key, val) { formBuilderQuestions[qIdx][key] = val; }
function addQChoice(qIdx) {
    if (!formBuilderQuestions[qIdx].options) formBuilderQuestions[qIdx].options = [];
    formBuilderQuestions[qIdx].options.push(`Option ${formBuilderQuestions[qIdx].options.length + 1}`);
    renderQuestionsBuilder();
}
function updateQChoice(qIdx, optIdx, val) { formBuilderQuestions[qIdx].options[optIdx] = val; }
function removeQChoice(qIdx, optIdx) {
    if (formBuilderQuestions[qIdx].options.length <= 2) return showToast("Multiple choice questions require at least 2 options.", 'warning');
    formBuilderQuestions[qIdx].options.splice(optIdx, 1);
    renderQuestionsBuilder();
}

function openCreateFormModal() {
    editingFormId = null; editingOriginalDeadline = '';
    _setSurveyModalMode(false, false, 0);
    resetThemeEditor(null, '');
    const themePanel = document.getElementById('themePanel'); if (themePanel) themePanel.open = false;
    document.getElementById('newFormTitle').value = '';
    document.getElementById('newFormDesc').value = '';
    document.getElementById('newFormSubject').value = '';
    document.getElementById('newFormSection').value = 'ALL';
    document.getElementById('newFormMax').value = '0';
    clearDeadlineSelection();
    initFormBuilder();

    const dateInput = document.getElementById('pickerDatePart');
    const now = new Date();
    dateInput.min = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);

    clearFormBuilderWarnings();
    openModal('createFormModal');
}
function closeCreateFormModal() { editingFormId = null; closeModal('createFormModal'); }

function clearFormBuilderWarnings() {
    document.getElementById('newFormTitle').classList.remove('input-error');
    document.getElementById('pickerDatePart').classList.remove('input-error');
    formBuilderQuestions.forEach((_, idx) => {
        const card = document.getElementById(`qBuilderCard_${idx}`);
        if (card) card.classList.remove('q-card-error');
    });
    const banner = document.getElementById('formBuilderWarnings');
    banner.style.display = 'none';
    banner.innerHTML = '';
}

function showFormBuilderWarnings(errors) {
    const banner = document.getElementById('formBuilderWarnings');
    banner.innerHTML = `⚠️ Please fix the following before publishing:<ul>${errors.map(e => `<li>${esc(e)}</li>`).join('')}</ul>`;
    banner.style.display = 'block';
    banner.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function openStudentPreview() {
    const title = document.getElementById('newFormTitle').value.trim() || 'Untitled Community Survey';
    const desc = document.getElementById('newFormDesc').value.trim() || 'No context description provided.';
    const subject = document.getElementById('newFormSubject').value.trim() || 'General';
    const section = document.getElementById('newFormSection').value.trim() || 'ALL';
    const deadline = document.getElementById('newFormDeadline').value || 'No Expiry';

    applyFormTheme(document.getElementById('previewFormCard'), document.getElementById('previewFormBanner'), themeState, _currentHeaderImage());
    document.getElementById('prevTitle').innerText = title;
    document.getElementById('prevDesc').innerText = desc;
    document.getElementById('prevMetaLine').innerText = `Target Section: ${section} • Subject: ${subject} • Deadline: ${formatDeadlineDisplay(deadline)}`;

    const renderContainer = document.getElementById('previewQuestionsRender');
    renderContainer.innerHTML = '';

    if (formBuilderQuestions.length === 0) {
        renderContainer.innerHTML = '<div style="color:var(--text-muted); font-size:0.85rem;">No inquiries defined yet.</div>';
    } else {
        formBuilderQuestions.forEach((q, idx) => {
            const qDiv = document.createElement('div');
            qDiv.className = 'fill-q-card';

            let inputControls = '';
            const qType = q.type || 'narrative';

            if (qType === 'narrative' || qType === 'text') {
                inputControls = `<textarea class="textarea-input" placeholder="Type response here (Preview Mode)..." style="margin-bottom:0;"></textarea>`;
            } else if (qType === 'likert') {
                const logic = q.elaboration_logic || (q.allow_explanation ? 'always' : 'low');
                const promptText = q.elaboration_prompt || 'Please elaborate on your response:';
                inputControls = `
                    <div class="likert-pills-row" id="prevLikertRow_${idx}">
                        ${[1, 2, 3, 4, 5].map(num => `<div class="likert-btn-pill" onclick="pickPrevLikert(${idx}, ${num}, '${logic}')">${num}</div>`).join('')}
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:0.72rem; color:var(--text-muted); margin-bottom:8px;">
                        <span>1 = ${esc(q.min_label || 'Poor')}</span>
                        <span>5 = ${esc(q.max_label || 'Excellent')}</span>
                    </div>
                    <div class="conditional-elaboration-box" id="prevCondBox_${idx}" style="${logic === 'always' ? 'display:block;' : 'display:none;'}">
                        <label style="display:block; font-size:0.74rem; color:var(--txt-gold); font-weight:700; margin-bottom:4px;">
                            💬 ${esc(promptText)} ${q.elaboration_required ? '<span style="color:var(--txt-red-strong);">*</span>' : ''}
                        </label>
                        <textarea class="textarea-input" placeholder="Write feedback here (Preview Mode)..." style="height:55px; margin-bottom:0;"></textarea>
                    </div>
                `;
            } else if (qType === 'radio') {
                inputControls = (q.options || []).map(opt => `
                    <label style="display:flex; align-items:center; gap:8px; margin-bottom:6px; font-size:0.86rem; color:var(--txt-soft); cursor:pointer;">
                        <input type="radio" name="prev_radio_${idx}"> ${esc(opt)}
                    </label>
                `).join('');
            } else if (qType === 'checkbox') {
                inputControls = (q.options || []).map(opt => `
                    <label style="display:flex; align-items:center; gap:8px; margin-bottom:6px; font-size:0.86rem; color:var(--txt-soft); cursor:pointer;">
                        <input type="checkbox"> ${esc(opt)}
                    </label>
                `).join('');
            }

            qDiv.innerHTML = `
                <label style="display:block; font-size:0.86rem; font-weight:700; color:var(--text-heading); margin-bottom:6px;">
                    ${idx + 1}. ${esc(q.prompt || 'Untitled Inquiry')} ${q.required ? '<span style="color:var(--txt-red-strong);">*</span>' : ''}
                </label>
                ${inputControls}
            `;
            renderContainer.appendChild(qDiv);
        });
    }
    openModal('previewFormModal');
}

function closeStudentPreview() { closeModal('previewFormModal'); }

function pickPrevLikert(qIdx, num, logic) {
    const row = document.getElementById(`prevLikertRow_${qIdx}`);
    if (!row) return;
    row.querySelectorAll('.likert-btn-pill').forEach((pill, idx) => {
        if (idx + 1 === num) pill.classList.add('active');
        else pill.classList.remove('active');
    });
    const condBox = document.getElementById(`prevCondBox_${qIdx}`);
    if (!condBox) return;

    let shouldShow = logic === 'always' || (logic === 'low' && num <= 2) || (logic === 'low_mid' && num <= 3);
    condBox.style.display = shouldShow ? 'block' : 'none';
}

async function submitCreateForm() {
    clearFormBuilderWarnings();
    const errors = [];

    const titleEl = document.getElementById('newFormTitle');
    const title = titleEl.value.trim();
    if (!title) { titleEl.classList.add('input-error'); errors.push('Missing Initiative Title'); }

    const qLocked = !!(editingFormId && questionsLocked);
    const deadline_date = document.getElementById('newFormDeadline').value;
    if (deadline_date && !(editingFormId && deadline_date === editingOriginalDeadline)) {
        const [d, t] = deadline_date.split('T');
        const [y, m, day] = d.split('-').map(Number);
        const [hh, mm] = (t || '23:59').split(':').map(Number);
        if (new Date(y, m - 1, day, hh, mm) < new Date()) {
            document.getElementById('pickerDatePart').classList.add('input-error');
            errors.push('Due date must be present or future');
        }
    }

    if (qLocked) {
        /* questions are read-only: this survey already has responses */
    } else if (formBuilderQuestions.length === 0) {
        errors.push('Add at least one survey inquiry');
    } else {
        formBuilderQuestions.forEach((q, idx) => {
            if (!q.prompt || !q.prompt.trim()) {
                const card = document.getElementById(`qBuilderCard_${idx}`);
                if (card) card.classList.add('q-card-error');
                errors.push(`Item #${idx + 1} is missing a question prompt`);
            }
            if ((q.type === 'radio' || q.type === 'checkbox')) {
                const filled = (q.options || []).filter(o => o && o.trim());
                if (filled.length < 2) {
                    const card = document.getElementById(`qBuilderCard_${idx}`);
                    if (card) card.classList.add('q-card-error');
                    errors.push(`Item #${idx + 1} needs at least 2 filled choice options`);
                }
            }
        });
    }

    const hasNLP = formBuilderQuestions.some(q => q.type === 'narrative' || q.allow_explanation || (q.elaboration_logic && q.elaboration_logic !== 'none'));
    if (!qLocked && formBuilderQuestions.length > 0 && !hasNLP) {
        errors.push('Include at least one narrative prompt or Likert explanation box for sentiment evaluation');
    }

    if (errors.length > 0) return showFormBuilderWarnings(errors);

    const description = document.getElementById('newFormDesc').value.trim();
    const form_category = document.getElementById('newFormCategory').value;
    const subject_code = document.getElementById('newFormSubject').value.trim();
    const section_target = document.getElementById('newFormSection').value.trim() || 'ALL';
    const max_responses = parseInt(document.getElementById('newFormMax').value || 0);
    const academic_year = document.getElementById('newFormYear').value;
    const semester = document.getElementById('newFormSem').value;

    const wasEdit = !!editingFormId;
    showLoader(wasEdit ? "Saving your changes..." : "Publishing targeted community survey...");
    try {
        const payload = { title, description, form_category, subject_code, section_target, deadline_date, max_responses, academic_year, semester };
        if (!qLocked) payload.questions = formBuilderQuestions;
        payload.theme = { ...themeState };
        if (headerImageData !== undefined) payload.header_image = headerImageData;
        const res = await apiFetch(wasEdit ? `/api/forms/${editingFormId}/update` : '/api/forms/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok) {
            closeCreateFormModal();
            showToast(wasEdit ? "Survey changes saved." : "Targeted community survey published.", 'success');
            loadAllForms();
            loadMyForms();
            fetchCommunityPulse();
        } else {
            showFormBuilderWarnings([data.error || "Failed to create form. Please review your entries."]);
        }
    } catch (e) {
        showFormBuilderWarnings([e.userMessage || "Server error occurred. Please try again."]);
    } finally { hideLoader(); }
}

function clearQCardError(qid) {
    const card = document.getElementById(`fillQCard_${qid}`);
    if (card) card.classList.remove('q-card-error');
}

async function openFillModal(formId) {
    const target = allFormsCache.find(f => f.id === formId);
    if (!target) return;

    if (target.is_closed) return showToast(`Survey is closed (${target.close_reason}).`, 'warning');

    activeFormUnderFill = target;
    applyFormTheme(document.getElementById('fillFormModalCard'), document.getElementById('fillFormBanner'), target.theme, formHeaderURL(target));
    document.getElementById('fillModalCategory').innerText = target.form_category;
    document.getElementById('fillModalTitle').innerText = target.title;
    document.getElementById('fillModalDesc').innerText = target.description || '';
    document.getElementById('fillModalMeta').innerText = `Target Cohort: ${target.section_target} • Subject: ${target.subject_code} • Author: ${target.created_by_name} • Cutoff: ${formatDeadlineDisplay(target.deadline_date)}`;

    const qList = document.getElementById('fillQuestionsList');
    qList.innerHTML = '';

    target.questions.forEach((q, idx) => {
        const qDiv = document.createElement('div');
        qDiv.className = 'fill-q-card';
        qDiv.id = `fillQCard_${q.id}`;

        let inputControls = '';
        const qType = q.type || 'narrative';

        if (qType === 'narrative' || qType === 'text') {
            inputControls = `<textarea class="textarea-input form-q-ans" data-qid="${q.id}" data-type="narrative" oninput="clearQCardError(${q.id})" placeholder="Write honest feedback in English, Tagalog, or Taglish..."></textarea>`;
        } else if (qType === 'likert') {
            const logic = q.elaboration_logic || (q.allow_explanation ? 'always' : 'low');
            const promptText = q.elaboration_prompt || 'Please elaborate on your response:';
            const isMandatoryWhenTriggered = Boolean(q.elaboration_required);

            inputControls = `
                <div class="likert-pills-row" id="likertRow_${q.id}">
                    ${[1, 2, 3, 4, 5].map(num => `<div class="likert-btn-pill" onclick="pickLikert(${q.id}, ${num}, '${logic}')">${num}</div>`).join('')}
                </div>
                <input type="hidden" class="form-q-ans" data-qid="${q.id}" data-type="likert" id="likertVal_${q.id}">
                <div style="display:flex; justify-content:space-between; font-size:0.7rem; color:var(--text-muted); margin-bottom:6px;">
                    <span>1 = ${esc(q.min_label || 'Poor')}</span>
                    <span>5 = ${esc(q.max_label || 'Excellent')}</span>
                </div>

                <div class="conditional-elaboration-box" id="condBox_${q.id}" data-mandatory="${isMandatoryWhenTriggered}" style="${logic === 'always' ? 'display:block;' : 'display:none;'}">
                    <label style="display:block; font-size:0.74rem; color:var(--txt-gold); font-weight:700; margin-bottom:4px;">
                        💬 ${esc(promptText)} ${isMandatoryWhenTriggered ? '<span style="color:var(--txt-red-strong);" title="Mandatory explanation">*</span>' : ''}
                    </label>
                    <textarea class="textarea-input form-q-exp" data-qid="${q.id}" oninput="clearQCardError(${q.id})" placeholder="Explain what occurred or what can be improved (analyzed by XLM-RoBERTa)..." style="height:60px; margin-bottom:0;"></textarea>
                </div>
            `;
        } else if (qType === 'radio') {
            inputControls = (q.options || []).map(opt => `
                <label style="display:flex; align-items:center; gap:8px; margin-bottom:5px; font-size:0.84rem; color:var(--txt-soft); cursor:pointer;">
                    <input type="radio" name="radio_${q.id}" value="${esc(opt)}" class="form-q-radio" data-qid="${q.id}" onchange="clearQCardError(${q.id})"> ${esc(opt)}
                </label>
            `).join('');
        } else if (qType === 'checkbox') {
            inputControls = (q.options || []).map(opt => `
                <label style="display:flex; align-items:center; gap:8px; margin-bottom:5px; font-size:0.84rem; color:var(--txt-soft); cursor:pointer;">
                    <input type="checkbox" value="${esc(opt)}" class="form-q-check" data-qid="${q.id}" onchange="clearQCardError(${q.id})"> ${esc(opt)}
                </label>
            `).join('');
        }

        qDiv.innerHTML = `
            <label class="q-prompt-title" style="display:block; font-size:0.86rem; font-weight:700; color:var(--text-heading); margin-bottom:6px;">
                ${idx + 1}. ${esc(q.prompt)} ${q.required ? '<span style="color:var(--txt-red-strong);" title="Mandatory inquiry">*</span>' : ''}
            </label>
            ${inputControls}
        `;
        qList.appendChild(qDiv);
    });

    openModal('fillFormModal');
}
function closeFillFormModal() { closeModal('fillFormModal'); }

function pickLikert(qid, num, logic) {
    document.getElementById(`likertVal_${qid}`).value = num;
    clearQCardError(qid);

    const row = document.getElementById(`likertRow_${qid}`);
    row.querySelectorAll('.likert-btn-pill').forEach((pill, idx) => {
        if (idx + 1 === num) pill.classList.add('active');
        else pill.classList.remove('active');
    });

    const condBox = document.getElementById(`condBox_${qid}`);
    if (!condBox) return;

    let shouldShow = logic === 'always' || (logic === 'low' && num <= 2) || (logic === 'low_mid' && num <= 3);
    if (shouldShow) {
        condBox.style.display = 'block';
    } else {
        condBox.style.display = 'none';
        const expInput = condBox.querySelector('.form-q-exp');
        if (expInput) expInput.value = '';
    }
}

async function submitAnswers() {
    if (!activeFormUnderFill) return;
    const answers = [];
    let missingRequired = false;
    let firstMissingCard = null;

    document.querySelectorAll('.fill-q-card').forEach(c => c.classList.remove('q-card-error'));

    activeFormUnderFill.questions.forEach(q => {
        const qid = q.id;
        const qType = q.type || 'narrative';
        const isRequired = Boolean(q.required);
        let answered = false;

        if (qType === 'narrative' || qType === 'text') {
            const el = document.querySelector(`.form-q-ans[data-qid="${qid}"]`);
            const val = el ? el.value.trim() : '';
            if (val) { answers.push({ question_id: qid, type: 'narrative', answer: val, value: val }); answered = true; }
        } else if (qType === 'likert') {
            const elVal = document.getElementById(`likertVal_${qid}`);
            const condBox = document.getElementById(`condBox_${qid}`);
            const expEl = condBox ? condBox.querySelector('.form-q-exp') : null;
            const score = elVal ? elVal.value : '';
            const exp = expEl ? expEl.value.trim() : '';
            const isBoxVisible = condBox && condBox.style.display !== 'none';
            const isMandatoryElaboration = isBoxVisible && condBox.getAttribute('data-mandatory') === 'true';

            if (score) answered = true;
            if (isMandatoryElaboration && !exp) answered = false;

            if (score || exp) answers.push({ question_id: qid, type: 'likert', score: score, value: score, narrative_text: exp });
        } else if (qType === 'radio') {
            const checked = document.querySelector(`input[name="radio_${qid}"]:checked`);
            if (checked) { answers.push({ question_id: qid, type: 'radio', value: checked.value }); answered = true; }
        } else if (qType === 'checkbox') {
            const checkedNodes = document.querySelectorAll(`input.form-q-check[data-qid="${qid}"]:checked`);
            const vals = Array.from(checkedNodes).map(n => n.value);
            if (vals.length > 0) { answers.push({ question_id: qid, type: 'checkbox', value: vals }); answered = true; }
        }

        if (isRequired && !answered) {
            missingRequired = true;
            const card = document.getElementById(`fillQCard_${qid}`);
            if (card) {
                card.classList.add('q-card-error');
                if (!firstMissingCard) firstMissingCard = card;
            }
        }
    });

    if (missingRequired) {
        if (firstMissingCard) {
            firstMissingCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
            const targetInput = firstMissingCard.querySelector('textarea, input[type="radio"], input[type="checkbox"]');
            if (targetInput) targetInput.focus();
        }
        return showToast("Please complete all mandatory inquiries and required elaboration boxes (*).", 'warning');
    }

    if (answers.length === 0) return showToast("Please answer at least one question.", 'warning');

    closeFillFormModal();
    showLoader("Submitting to community ABSA model...");

    try {
        const res = await apiFetch('/api/forms/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
            body: JSON.stringify({ form_id: activeFormUnderFill.id, answers: answers })
        });
        const data = await res.json();
        if (res.ok) {
            showToast("Feedback ingested into community analytics!", 'success');
            loadAllForms();
            fetchCommunityPulse();
        } else {
            showToast(data.error || "Submission failed.", 'error');
        }
    } catch (e) { showToast(e.userMessage || "Server error during submission.", 'error'); } finally { hideLoader(); }
}

async function openSurveyAnalytics(formId) {
    showLoader("Aggregating survey statistics...");
    try {
        const res = await apiFetch(`/api/forms/${formId}/analytics`);
        const data = await readJson(res, "Could not load data.");
        hideLoader();

        if (!res.ok) return showToast(data.error || "Failed to load analytics.", 'error');

        document.getElementById('analyticsModalTitle').innerText = data.title;
        document.getElementById('analyticsModalCohort').innerText = `${data.section_target} (${data.subject_code})`;
        document.getElementById('analyticsTotalCount').innerText = `${data.total_responses} students`;
        document.getElementById('btnExportSurveyCsv').onclick = () => downloadFile(`/api/forms/${formId}/export_csv`, 'survey_export.csv');

        const container = document.getElementById('analyticsQuestionsList');
        container.innerHTML = '';

        if (data.suppressed) {
            container.innerHTML = `<div class="privacy-note">🔒 ${esc(data.privacy_note || 'Results are hidden until more people have responded.')}</div>`;
        } else if (data.total_responses === 0) {
            container.innerHTML = `<div style="text-align:center; padding:35px; color:var(--text-muted); background:rgba(6,12,26,0.5); border-radius:var(--radius-md); border:1px dashed var(--border-subtle);">No student submissions have been recorded yet for this survey.</div>`;
        } else {
            data.questions_analytics.forEach(q => {
                const itemCard = document.createElement('div');
                itemCard.style.cssText = 'background:rgba(6,12,26,0.65); border:1px solid var(--border-subtle); border-radius:var(--radius-md); padding:18px;';

                let statsRender = '';
                if (q.type === 'likert') {
                    statsRender = `
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                            <span style="font-size:1.15rem; font-weight:800; color:var(--txt-gold);">Average Rating: ${q.average_rating} / 5.0</span>
                            <span style="font-size:0.75rem; color:var(--text-muted);">${q.total_answers} Ratings</span>
                        </div>
                        <div style="display:flex; gap:6px; margin-bottom:12px;">
                            ${[1, 2, 3, 4, 5].map(n => `
                                <div style="flex:1; background:rgba(6,12,26,0.85); border-radius:var(--radius-sm); padding:8px 4px; text-align:center; border:1px solid var(--border-subtle);">
                                    <div style="font-size:0.72rem; color:var(--text-muted);">${n} ★</div>
                                    <div style="font-size:0.95rem; font-weight:800; color:var(--text-heading); margin-top:2px;">${q.likert_counts[n] || 0}</div>
                                </div>
                            `).join('')}
                        </div>
                    `;
                } else if (q.type === 'radio' || q.type === 'checkbox') {
                    const choiceKeys = Object.keys(q.choice_counts);
                    if (choiceKeys.length === 0) {
                        statsRender = `<div style="font-size:0.78rem; color:var(--text-muted); font-style:italic;">No choices recorded.</div>`;
                    } else {
                        statsRender = choiceKeys.map(k => {
                            const count = q.choice_counts[k];
                            const pct = q.total_answers > 0 ? Math.round((count / q.total_answers) * 100) : 0;
                            return `
                                <div style="margin-bottom:8px;">
                                    <div style="display:flex; justify-content:space-between; font-size:0.78rem; margin-bottom:3px;">
                                        <span>${esc(k)}</span>
                                        <span><strong>${count}</strong> (${pct}%)</span>
                                    </div>
                                    <div style="width:100%; height:6px; background:rgba(6,12,26,0.85); border-radius:var(--radius-full); overflow:hidden;">
                                        <div style="width:${pct}%; height:100%; background:var(--primary);"></div>
                                    </div>
                                </div>
                            `;
                        }).join('');
                    }
                }

                let narrativeSample = '';
                if (q.narratives && q.narratives.length > 0) {
                    narrativeSample = `
                        <div style="margin-top:12px; border-top:1px dashed var(--border-subtle); padding-top:10px;">
                            <span style="font-size:0.74rem; color:var(--txt-blue); font-weight:700;">Student Narrative Feedback (${q.narratives.length} comments):</span>
                            <div style="max-height:130px; overflow-y:auto; margin-top:8px; display:flex; flex-direction:column; gap:6px;">
                                ${q.narratives.map(t => `
                                    <div style="font-size:0.8rem; background:rgba(6,12,26,0.85); padding:8px 12px; border-radius:var(--radius-sm); color:var(--txt-soft); border:1px solid var(--border-subtle);">"${esc(t)}"</div>
                                `).join('')}
                            </div>
                        </div>
                    `;
                }

                if (q.hidden) {
                    statsRender = `<div class="privacy-note">🔒 Only ${q.total_answers} ${q.total_answers === 1 ? 'person' : 'people'} answered this question, so the answers are hidden to protect them (minimum ${data.min_required}).</div>`;
                    narrativeSample = '';
                }
                itemCard.innerHTML = `
                    <div style="font-size:0.92rem; font-weight:700; color:var(--text-heading); margin-bottom:10px;">
                        ${q.id}. ${esc(q.prompt)}
                    </div>
                    ${statsRender}
                    ${narrativeSample}
                `;
                container.appendChild(itemCard);
            });
        }
        openModal('surveyAnalyticsModal');
    } catch (err) { hideLoader(); showToast(err.userMessage || "Failed to load survey analytics.", 'error'); }
}
function closeSurveyAnalyticsModal() { closeModal('surveyAnalyticsModal'); }

// ==========================================================
// FORM TABS, SEARCH, & EXPIRATIONS
// ==========================================================
function setFormTab(tabName, btn) {
    currentFormTab = tabName;
    document.querySelectorAll('#surveyCategoryTabs .survey-subtab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    renderStudentForms();
}

function onFormSearch(val) {
    currentFormSearch = val.toLowerCase();
    renderStudentForms();
}

function toggleAuthoredSurveys() {
    const paneStudent = document.getElementById('paneStudentSurveys');
    const paneMine = document.getElementById('paneMySurveys');
    const btnToggle = document.getElementById('btnToggleAuthored');

    if (paneStudent.style.display !== 'none') {
        paneStudent.style.display = 'none';
        paneMine.style.display = 'block';
        btnToggle.innerText = '🧾 View Student Forms Feed';
        loadMyForms();
    } else {
        paneStudent.style.display = 'block';
        paneMine.style.display = 'none';
        btnToggle.innerText = '🧾 View Surveys Initiated by You';
    }
}

async function loadAllForms() {
    try {
        const res = await apiFetch('/api/forms');
        allFormsCache = await readJson(res, "Could not load data.");
        renderStudentForms();
        handleSharedSurveyLink();
    } catch (err) {
        console.error("Failed to load forms:", err);
        showToast(err.userMessage || "Could not load the evaluation forms.", 'error');
    }
}

function renderStudentForms() {
    const container = document.getElementById('availableFormsContainer');
    if (!container) return;
    container.innerHTML = '';

    const now = new Date();
    const todayISO = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);

    let filteredForms = allFormsCache.filter(f => {
        if (f.already_submitted) return currentFormTab === 'Completed';
        if (f.is_closed) return currentFormTab === 'Missed';

        if (f.deadline_date && f.deadline_date !== 'No Expiry') {
            const formDateISO = f.deadline_date.split('T')[0];
            if (formDateISO === todayISO) {
                return currentFormTab === 'Due Today';
            }
        }
        return currentFormTab === 'Available';
    });

    if (currentFormSearch) {
        filteredForms = filteredForms.filter(f => 
            (f.title && f.title.toLowerCase().includes(currentFormSearch)) ||
            (f.description && f.description.toLowerCase().includes(currentFormSearch)) ||
            (f.form_category && f.form_category.toLowerCase().includes(currentFormSearch))
        );
    }

    if (filteredForms.length === 0) {
        const msgMap = {
            'Available': "No new surveys available right now.",
            'Due Today': "You have no evaluations expiring today. Great job!",
            'Missed': "You haven't missed any closed surveys.",
            'Completed': "You haven't completed any surveys yet."
        };
        container.innerHTML = `
            <div class="empty-state-box">
                <div class="empty-state-icon">${currentFormTab === 'Completed' ? '✅' : '🗳️'}</div>
                <div class="empty-state-title">${currentFormSearch ? "No search results found" : msgMap[currentFormTab]}</div>
                <div class="empty-state-sub">${currentFormSearch ? "Try adjusting your search keywords." : "Check back later for new institutional initiatives."}</div>
            </div>`;
        return;
    }

    filteredForms.forEach(f => {
        const st = surveyStatus(f, todayISO);
        const card = document.createElement('div');
        card.className = `form-card sv-card sv-${st.key}`;
        card.innerHTML = surveyCardHTML(f, st);
        container.appendChild(card);
    });
}

// ==========================================================
// SURVEY LOOK & FEEL (theme colour, background, header picture, font)
// ==========================================================
const HEADER_PRESETS = {
    ocean: 'linear-gradient(135deg,#0ea5e9,#2563eb)', sunset: 'linear-gradient(135deg,#f59e0b,#ef4444)',
    forest: 'linear-gradient(135deg,#10b981,#065f46)', violet: 'linear-gradient(135deg,#8b5cf6,#4338ca)',
    slate: 'linear-gradient(135deg,#64748b,#1e293b)', rose: 'linear-gradient(135deg,#fb7185,#be185d)'
};
const THEME_ACCENTS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#64748b'];
const THEME_BACKGROUNDS = ['#0b1220', '#1e1b4b', '#052e16', '#3b1d0a', '#f8fafc', '#fef3c7', '#e0f2fe', '#fce7f3'];
const _isHex = (v) => typeof v === 'string' && /^#[0-9a-fA-F]{6}$/.test(v);
function _luminance(hex) { const n = parseInt(hex.slice(1), 16); return (0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255)) / 255; }
function headerCSS(theme, imgUrl) {
    if (imgUrl) return `background-image:url('${imgUrl}');`;
    const g = theme && HEADER_PRESETS[theme.header];
    return g ? `background-image:${g};` : '';
}
function formHeaderURL(f) { return f && f.has_header_image ? `/api/forms/${Number(f.id)}/header?v=${Number((f.theme || {}).hv) || 0}` : ''; }
function surveyBannerHTML(f) {
    const css = headerCSS(f.theme, formHeaderURL(f));
    return css ? `<div class="sv-banner" style="${css}"></div>` : '';
}
// Paints a theme onto a surface (fill modal, preview modal, editor preview). Every value is re-validated before it touches a style.
function applyFormTheme(surface, banner, theme, imgUrl) {
    if (!surface) return;
    theme = theme || {};
    surface.classList.remove('themed', 't-accent', 't-light', 't-dark', 'font-serif', 'font-rounded');
    surface.style.removeProperty('--form-accent'); surface.style.removeProperty('--form-bg');
    const accent = _isHex(theme.accent), bg = _isHex(theme.background);
    const font = theme.font === 'serif' || theme.font === 'rounded' ? theme.font : 'sans';
    if (accent || bg || font !== 'sans') {
        surface.classList.add('themed');
        if (accent) { surface.classList.add('t-accent'); surface.style.setProperty('--form-accent', theme.accent); }
        if (bg) { surface.style.setProperty('--form-bg', theme.background); surface.classList.add(_luminance(theme.background) > 0.6 ? 't-light' : 't-dark'); }
        if (font !== 'sans') surface.classList.add('font-' + font);
    }
    if (banner) {
        const css = headerCSS(theme, imgUrl);
        banner.style.cssText = css;
        banner.style.display = css ? 'block' : 'none';
    }
}

let themeState = { accent: null, background: null, font: 'sans', header: 'none' };
let headerImageData;          // undefined = leave as is · '' = remove · 'data:image/...' = new upload
let headerImageSavedURL = ''; // picture already stored on the server (edit mode)

function resetThemeEditor(theme, savedUrl) {
    theme = theme || {};
    themeState = { accent: _isHex(theme.accent) ? theme.accent : null, background: _isHex(theme.background) ? theme.background : null, font: ['serif', 'rounded'].includes(theme.font) ? theme.font : 'sans', header: HEADER_PRESETS[theme.header] ? theme.header : 'none' };
    headerImageData = undefined;
    headerImageSavedURL = savedUrl || '';
    renderThemeEditor();
}
function _currentHeaderImage() { return headerImageData === undefined ? headerImageSavedURL : headerImageData; }
function renderThemeEditor() {
    const acc = document.getElementById('accentSwatches');
    if (!acc) return;
    acc.innerHTML = `<button type="button" class="swatch swatch-default ${themeState.accent ? '' : 'sel'}" onclick="pickAccent(null)" title="Default colour">Auto</button>` +
        THEME_ACCENTS.map(c => `<button type="button" class="swatch ${themeState.accent === c ? 'sel' : ''}" style="background:${c}" onclick="pickAccent('${c}')" aria-label="Theme colour ${c}"></button>`).join('');
    document.getElementById('bgSwatches').innerHTML = `<button type="button" class="swatch swatch-default ${themeState.background ? '' : 'sel'}" onclick="pickBackground(null)" title="Default background">Auto</button>` +
        THEME_BACKGROUNDS.map(c => `<button type="button" class="swatch ${themeState.background === c ? 'sel' : ''}" style="background:${c}" onclick="pickBackground('${c}')" aria-label="Background ${c}"></button>`).join('');
    const hasImg = !!_currentHeaderImage();
    document.getElementById('headerPresets').innerHTML = `<button type="button" class="hp hp-none ${(!hasImg && themeState.header === 'none') ? 'sel' : ''}" onclick="pickHeaderPreset('none')">None</button>` +
        Object.keys(HEADER_PRESETS).map(k => `<button type="button" class="hp ${(!hasImg && themeState.header === k) ? 'sel' : ''}" style="background-image:${HEADER_PRESETS[k]}" onclick="pickHeaderPreset('${k}')" aria-label="Header style ${k}"></button>`).join('');
    document.getElementById('headerRemoveBtn').style.display = hasImg ? 'inline-flex' : 'none';
    document.getElementById('themeFont').value = themeState.font;
    const custom = themeState.accent || themeState.background || themeState.font !== 'sans' || themeState.header !== 'none' || hasImg;
    document.getElementById('themeSummaryHint').textContent = custom ? 'Custom look' : 'Default look';
    renderThemePreview();
}
function renderThemePreview() {
    const box = document.getElementById('themePreview');
    if (!box) return;
    applyFormTheme(box, document.getElementById('themePreviewBanner'), themeState, _currentHeaderImage());
    const t = document.getElementById('newFormTitle');
    document.getElementById('themePreviewTitle').textContent = (t && t.value.trim()) || 'Your survey title';
}
function pickAccent(c) { themeState.accent = c; renderThemeEditor(); }
function pickBackground(c) { themeState.background = c; renderThemeEditor(); }
function pickHeaderPreset(k) { themeState.header = k; headerImageData = ''; headerImageSavedURL = ''; renderThemeEditor(); }
function onThemeFontChange(v) { themeState.font = v; renderThemeEditor(); }
function removeHeaderImage() { headerImageData = ''; headerImageSavedURL = ''; renderThemeEditor(); }

// Pictures are cropped to a wide banner and compressed in the browser, so uploads stay small and fast for everyone.
async function onHeaderImagePicked(input) {
    const file = input.files && input.files[0];
    input.value = '';
    if (!file) return;
    if (!/^image\/(png|jpeg|webp)$/.test(file.type)) return showToast("Please choose a PNG, JPEG or WebP picture.", 'warning');
    if (file.size > 8 * 1024 * 1024) return showToast("That picture is larger than 8 MB. Please choose a smaller one.", 'warning');
    try {
        const bmp = await createImageBitmap(file);
        const W = 1200, H = 300, canvas = document.createElement('canvas');
        canvas.width = W; canvas.height = H;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, W, H);
        const scale = Math.max(W / bmp.width, H / bmp.height);
        const sw = W / scale, sh = H / scale;
        ctx.drawImage(bmp, (bmp.width - sw) / 2, (bmp.height - sh) / 2, sw, sh, 0, 0, W, H);
        let q = 0.85, data = canvas.toDataURL('image/jpeg', q);
        while (data.length > 420000 && q > 0.4) { q -= 0.1; data = canvas.toDataURL('image/jpeg', q); }
        if (data.length > 420000) return showToast("That picture is too detailed to compress enough. Please try a simpler one.", 'warning');
        headerImageData = data; themeState.header = 'none';
        renderThemeEditor();
    } catch (e) {
        showToast("We couldn't read that picture. Please try another file.", 'error');
    }
}

// ==========================================================
// SURVEY CARDS (redesigned) + SURVEY OWNER TOOLS (edit / delete / share link)
// ==========================================================
function _parseDeadline(d) {
    if (!d || d === 'No Expiry' || d === 'None') return null;
    const dt = d.includes('T') ? new Date(d) : new Date(d + 'T23:59:59');
    return isNaN(dt) ? null : dt;
}
function relativeDeadline(d) {
    const dt = _parseDeadline(d);
    if (!dt) return '';
    const mins = Math.round((dt - new Date()) / 60000);
    if (mins < 0) return 'ended';
    if (mins < 60) return `${Math.max(mins, 1)} min left`;
    if (mins < 60 * 24) return `${Math.floor(mins / 60)}h ${mins % 60}m left`;
    const days = Math.floor(mins / 1440);
    return days <= 14 ? `${days} day${days === 1 ? '' : 's'} left` : '';
}
function surveyStatus(f, todayISO) {
    if (f.already_submitted) return { key: 'done', label: 'Submitted' };
    if (f.is_closed) return { key: 'closed', label: f.close_reason || 'Closed' };
    if (f.deadline_date && f.deadline_date !== 'No Expiry' && f.deadline_date.split('T')[0] === todayISO) return { key: 'due', label: 'Due today' };
    return { key: 'open', label: 'Open' };
}
function surveyChipsHTML(f) {
    return `<span class="sv-chip sv-chip-cat">${esc(f.form_category)}</span>
            <span class="sv-chip sv-chip-sec">Section: ${esc(f.section_target)}</span>
            ${f.subject_code && f.subject_code !== 'N/A' ? `<span class="sv-chip sv-chip-sub">${esc(f.subject_code)}</span>` : ''}`;
}
function surveyQuotaBarHTML(count, max) {
    if (!(max > 0)) return '';
    const pct = Math.min(100, Math.round((count / max) * 100));
    return `<li class="sv-bar-row"><div class="sv-bar" role="progressbar" aria-valuemin="0" aria-valuemax="${max}" aria-valuenow="${count}"><span style="width:${pct}%"></span></div></li>`;
}
function surveyCardHTML(f, st) {
    const rel = relativeDeadline(f.deadline_date);
    const relHTML = (rel && !f.is_closed && !f.already_submitted) ? ` <b class="sv-rel sv-rel-${st.key}">(${esc(rel)})</b>` : '';
    let cta;
    if (st.key === 'done') cta = `<div class="sv-note sv-note-done">✓ You've submitted this evaluation</div>`;
    else if (st.key === 'closed') cta = `<div class="sv-note sv-note-closed">Closed · ${esc(f.close_reason || 'No longer accepting responses')}</div>`;
    else cta = `<button type="button" class="btn-action sv-cta" onclick="openFillModal(${f.id})">Fill Out Evaluation <span aria-hidden="true">→</span></button>`;
    return `
        <div class="sv-body">
            ${surveyBannerHTML(f)}
            <div class="sv-top">
                <div class="sv-chips">${surveyChipsHTML(f)}</div>
                <span class="sv-status sv-status-${st.key}"><i></i>${esc(st.label)}</span>
            </div>
            <div class="form-card-title">${esc(f.title)}</div>
            <p class="sv-desc ${f.description ? '' : 'sv-desc-empty'}">${esc(f.description || 'No description provided.')}</p>
        </div>
        <div class="sv-foot">
            <ul class="sv-meta">
                <li><span class="sv-ic">👤</span><span><strong>${esc(f.created_by_name)}</strong> <em>${esc(f.created_by_role)}</em></span></li>
                <li><span class="sv-ic">⏰</span><span>Closes <strong>${esc(formatDeadlineDisplay(f.deadline_date))}</strong>${relHTML}</span></li>
                <li><span class="sv-ic">📊</span><span><strong>${f.total_submissions}</strong> response${f.total_submissions === 1 ? '' : 's'}${f.max_responses > 0 ? ` of ${f.max_responses}` : ''}</span></li>
                ${surveyQuotaBarHTML(f.total_submissions, f.max_responses)}
            </ul>
            ${cta}
        </div>`;
}

let myFormsCache = [];
let editingFormId = null, editingOriginalDeadline = '', questionsLocked = false;

function _setSurveyModalMode(isEdit, locked, responseCount) {
    questionsLocked = !!(isEdit && locked);
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    set('surveyModalTitle', isEdit ? 'Edit Survey' : 'Create a New Survey');
    set('surveyModalSub', isEdit ? 'Changes apply right away for everyone who opens this survey.' : 'Build targeted multi-format evaluations with ratings, choice prompts, and narrative inquiries for your peers.');
    set('surveySubmitBtn', isEdit ? 'Save Changes' : 'Publish Survey');
    const notice = document.getElementById('questionsLockedNotice');
    if (notice) {
        notice.style.display = questionsLocked ? 'block' : 'none';
        notice.textContent = questionsLocked ? `🔒 The questions are locked because ${responseCount} ${responseCount === 1 ? 'person has' : 'people have'} already responded, and changing them would make the collected answers inconsistent. You can still change the title, description, deadline, section and response limit.` : '';
    }
    const toolbar = document.getElementById('questionToolbar');
    if (toolbar) toolbar.style.display = questionsLocked ? 'none' : 'flex';
    const qc = document.getElementById('questionsBuilderContainer');
    if (qc) qc.classList.toggle('questions-locked', questionsLocked);
}

async function openEditSurvey(id) {
    showLoader("Opening your survey...");
    try {
        const res = await apiFetch(`/api/forms/${id}/manage`);
        const f = await readJson(res, "Could not open this survey for editing.");
        openCreateFormModal();
        editingFormId = f.id;
        editingOriginalDeadline = f.deadline_date || '';
        const val = (elId, v) => { const el = document.getElementById(elId); if (el) el.value = v; };
        val('newFormTitle', f.title); val('newFormDesc', f.description); val('newFormSubject', f.subject_code);
        val('newFormSection', f.section_target); val('newFormMax', String(f.max_responses || 0));
        val('newFormCategory', f.form_category); val('newFormYear', f.academic_year); val('newFormSem', f.semester);
        if (f.deadline_date) {
            const [d, t] = f.deadline_date.split('T');
            document.getElementById('pickerDatePart').value = d;
            document.getElementById('pickerTimePart').value = t || '23:59';
            syncDeadlineValue();
        }
        formBuilderQuestions = JSON.parse(JSON.stringify(f.questions || []));
        renderQuestionsBuilder();
        resetThemeEditor(f.theme, formHeaderURL({ id: f.id, has_header_image: f.has_header_image, theme: f.theme }));
        _setSurveyModalMode(true, f.questions_locked, f.response_count);
    } catch (e) {
        closeModal('createFormModal');
        showToast(e.userMessage || e.message || "Could not open this survey for editing.", 'error');
    } finally { hideLoader(); }
}

async function copySurveyLink(id) {
    const f = myFormsCache.find(x => x.id === id);
    if (!f || !f.share_url) return showToast("This survey has no share link yet. Please refresh and try again.", 'error');
    const url = location.origin + f.share_url;
    let copied = false;
    try { await navigator.clipboard.writeText(url); copied = true; } catch (e) {
        try {
            const ta = document.createElement('textarea');
            ta.value = url; ta.style.position = 'fixed'; ta.style.opacity = '0';
            document.body.appendChild(ta); ta.select();
            copied = document.execCommand('copy');
            document.body.removeChild(ta);
        } catch (e2) { copied = false; }
    }
    if (copied) showToast("Survey link copied. People you send it to will be asked to sign in first.", 'success');
    else window.prompt("Copy this survey link:", url);
}

let deletingFormId = null;
function openDeleteSurvey(id) {
    const f = myFormsCache.find(x => x.id === id);
    if (!f) return;
    deletingFormId = id;
    document.getElementById('deleteSurveyName').textContent = f.title;
    document.getElementById('deleteSurveyCount').textContent = f.response_count;
    document.getElementById('deleteSurveyPurge').checked = false;
    openModal('deleteSurveyModal');
}
function closeDeleteSurvey() { deletingFormId = null; closeModal('deleteSurveyModal'); }
async function confirmDeleteSurvey() {
    if (!deletingFormId) return;
    const id = deletingFormId;
    const purge = document.getElementById('deleteSurveyPurge').checked;
    showLoader("Deleting survey...");
    try {
        const res = await apiFetch(`/api/forms/${id}/delete`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN }, body: JSON.stringify({ purge }) });
        const data = await res.json();
        if (!res.ok) throw Object.assign(new Error(data.error || "Could not delete the survey."), { userMessage: data.error });
        closeDeleteSurvey();
        showToast(purge ? "Survey deleted and its responses erased." : "Survey deleted. It is hidden from everyone.", 'success');
        loadAllForms(); loadMyForms(); fetchCommunityPulse();
    } catch (e) {
        showToast(e.userMessage || e.message || "Could not delete the survey.", 'error');
    } finally { hideLoader(); }
}

// A shared link (/s/<token>) lands here as ?survey=<id> and opens that survey straight away.
function handleSharedSurveyLink() {
    const params = new URLSearchParams(location.search);
    const sv = params.get('survey');
    if (!sv) return;
    params.delete('survey');
    try { history.replaceState(history.state, '', location.pathname + (params.toString() ? '?' + params : '')); } catch (e) { /* ignore */ }
    switchPortalTab('surveys');
    if (sv === 'unavailable') return showToast("This survey link is no longer available. It may have been deleted by its creator.", 'warning');
    const f = allFormsCache.find(x => x.id === parseInt(sv, 10));
    if (!f) return showToast("We couldn't find that survey. It may have been deleted.", 'warning');
    if (f.already_submitted) return showToast("You've already submitted this survey. Thank you!", 'info');
    if (f.is_closed) return showToast(`This survey is closed (${f.close_reason}).`, 'warning');
    openFillModal(f.id);
}

const myFormsView = { q: '', status: 'all', sort: 'newest' };

async function loadMyForms() {
    try {
        const res = await apiFetch('/api/forms/my_forms');
        myFormsCache = await readJson(res, "Could not load data.");
        renderMyForms();
    } catch (e) {
        console.error("Failed to load authored forms:", e);
        showToast(e.userMessage || "Could not load your published forms.", 'error');
    }
}
function onMyFormsSearch(v) { myFormsView.q = (v || '').trim().toLowerCase(); renderMyForms(); }
function onMyFormsSort(v) { myFormsView.sort = v; renderMyForms(); }
function setMyFormsStatus(s) { myFormsView.status = s; renderMyForms(); }
function clearMyFormsFilters() {
    myFormsView.q = ''; myFormsView.status = 'all';
    const input = document.getElementById('myFormsSearch'); if (input) input.value = '';
    renderMyForms();
}
function myFormCardHTML(f, st, rel) {
    return `
                <div class="sv-body">
                    ${surveyBannerHTML(f)}
                    <div class="sv-top">
                        <div class="sv-chips">${surveyChipsHTML(f)}</div>
                        <span class="sv-status sv-status-${st.key}"><i></i>${esc(st.label)}</span>
                    </div>
                    <div class="form-card-title">${esc(f.title)}</div>
                    <div class="sv-bignum"><strong>${f.response_count}</strong><span>response${f.response_count === 1 ? '' : 's'} collected${f.max_responses > 0 ? ` of ${f.max_responses}` : ''}</span></div>
                    ${surveyQuotaBarHTML(f.response_count, f.max_responses) ? `<ul class="sv-meta sv-meta-tight">${surveyQuotaBarHTML(f.response_count, f.max_responses)}</ul>` : ''}
                </div>
                <div class="sv-foot">
                    <ul class="sv-meta">
                        <li><span class="sv-ic">⏰</span><span>Closes <strong>${esc(formatDeadlineDisplay(f.deadline_date))}</strong>${rel && !f.is_closed ? ` <b class="sv-rel sv-rel-${st.key}">(${esc(rel)})</b>` : ''}</span></li>
                        <li><span class="sv-ic">🗓️</span><span>${esc(f.academic_year)} — ${esc(f.semester)} &bull; Created ${esc(f.created_at)}</span></li>
                    </ul>
                    <button type="button" class="btn-action sv-cta" onclick="openSurveyAnalytics(${f.id})">📊 View Analytics</button>
                    <div class="sv-actions">
                        <button type="button" class="sv-act" onclick="openEditSurvey(${f.id})" title="Edit this survey">✏️ Edit</button>
                        <button type="button" class="sv-act" onclick="copySurveyLink(${f.id})" title="Copy a link you can share">🔗 Copy link</button>
                        <button type="button" class="sv-act" onclick="downloadFile('/api/forms/${f.id}/export_csv', 'survey_export.csv')" title="Download responses as CSV">📥 Export</button>
                        <button type="button" class="sv-act sv-act-danger" onclick="openDeleteSurvey(${f.id})" title="Delete this survey">🗑️ Delete</button>
                    </div>
                </div>
            `;
}
function renderMyForms() {
    const container = document.getElementById('myFormsContainer');
    if (!container) return;
    const all = myFormsCache || [];
    const open = all.filter(f => !f.is_closed).length;
    const setText = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    setText('mfCountAll', all.length); setText('mfCountOpen', open); setText('mfCountClosed', all.length - open);
    const totalResponses = all.reduce((n, f) => n + (f.response_count || 0), 0);
    setText('myFormsSummary', all.length ? `${all.length} survey${all.length === 1 ? '' : 's'} · ${totalResponses} response${totalResponses === 1 ? '' : 's'} collected` : '');
    document.querySelectorAll('#myFormsChips .mf-chip').forEach(c => c.classList.toggle('active', c.dataset.status === myFormsView.status));
    const toolbar = document.querySelector('.my-surveys-toolbar'), chips = document.getElementById('myFormsChips');
    if (toolbar) toolbar.style.display = all.length ? '' : 'none';
    if (chips) chips.style.display = all.length ? '' : 'none';

    if (all.length === 0) {
        container.innerHTML = `
            <div class="empty-state-box">
                <div class="empty-state-icon">🧾</div>
                <div class="empty-state-title">You haven't published any surveys yet</div>
                <div class="empty-state-sub">Use "+ Create Formal Survey" above to launch your first community evaluation.</div>
            </div>`;
        return;
    }
    const q = myFormsView.q;
    let list = all.filter(f => {
        if (myFormsView.status === 'open' && f.is_closed) return false;
        if (myFormsView.status === 'closed' && !f.is_closed) return false;
        if (!q) return true;
        return [f.title, f.description, f.form_category, f.section_target, f.subject_code, f.academic_year, f.semester].some(v => (v || '').toLowerCase().includes(q));
    });
    const deadlineKey = (f) => { const d = _parseDeadline(f.deadline_date); return d ? d.getTime() : Infinity; };
    if (myFormsView.sort === 'responses') list.sort((a, b) => b.response_count - a.response_count || b.id - a.id);
    else if (myFormsView.sort === 'closing') list.sort((a, b) => (a.is_closed - b.is_closed) || (deadlineKey(a) - deadlineKey(b)) || b.id - a.id);
    else if (myFormsView.sort === 'az') list.sort((a, b) => a.title.localeCompare(b.title));
    else list.sort((a, b) => b.id - a.id);

    if (list.length === 0) {
        container.innerHTML = `
            <div class="empty-state-box">
                <div class="empty-state-icon">🔎</div>
                <div class="empty-state-title">No surveys match your search</div>
                <div class="empty-state-sub">Try different words or <button type="button" class="link-btn" onclick="clearMyFormsFilters()">clear the search and filters</button>.</div>
            </div>`;
        return;
    }
    const todayISO = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    container.innerHTML = '';
    list.forEach(f => {
        const st = surveyStatus({ ...f, already_submitted: false }, todayISO);
        const rel = relativeDeadline(f.deadline_date);
        const card = document.createElement('div');
        card.className = `form-card sv-card sv-${st.key}`;
        card.innerHTML = myFormCardHTML(f, st, rel);
        container.appendChild(card);
    });
}

function onFeedSearch(val) {
    currentFeedSearch = val.toLowerCase();
    renderTownHallFeed();
}

// Department Community Pulse (the live tally card at the top of the portal)
async function fetchCommunityPulse() {
    try {
        const res = await apiFetch('/api/community_pulse');
        const d = await readJson(res, "Could not load the community pulse.");
        const setText = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
        const setWidth = (id, pct) => { const el = document.getElementById(id); if (el) el.style.width = (Number(pct) || 0) + '%'; };
        setText('pulseTotalVoices', d.total_voices);
        setText('pulsePosPercent', (d.positive_percent || 0) + '%');
        setText('pulseNegPercent', (d.negative_percent || 0) + '%');
        setText('pulseActiveForms', d.active_initiatives);
        setWidth('meterPos', d.positive_percent);
        setWidth('meterNeu', d.neutral_percent);
        setWidth('meterNeg', d.negative_percent);
        setText('txtPos', d.positive_count);
        setText('txtNeu', d.neutral_count);
        setText('txtNeg', d.negative_count);
    } catch (err) {
        // Background refresh of a summary card: log it, but never pop an error over a successful action (e.g. a post that just went through).
        console.error("Failed to load community pulse:", err);
    }
}

async function fetchTownHallFeed() {
    try {
        const res = await apiFetch(`/api/community_feed?channel=${activeChannel}`);
        feedPostsCache = await readJson(res, "Could not load data.");
        renderTownHallFeed();
    } catch (err) {
        console.error("Failed to load feed:", err);
        showToast(err.userMessage || "Could not load the community feed.", 'error');
    }
}

function renderTownHallFeed() {
    const container = document.getElementById('townhallFeedContainer');
    if (!container) return;
    container.innerHTML = '';

    const now = new Date();

    let filteredPosts = feedPostsCache.filter(p => {
        if (p.is_announcement && p.action_note && p.action_note.startsWith('EXP:')) {
            const expDateStr = p.action_note.split('EXP:')[1].split('|')[0];
            if (expDateStr) {
                const expDate = new Date(expDateStr.includes('T') ? expDateStr : expDateStr + "T23:59:59");
                if (expDate < now) return false;
            }
        }

        if (currentFeedSearch) {
            return (p.content && p.content.toLowerCase().includes(currentFeedSearch)) ||
                   (p.category && p.category.toLowerCase().includes(currentFeedSearch)) ||
                   (p.author_name && p.author_name.toLowerCase().includes(currentFeedSearch));
        }
        return true;
    });

    if (filteredPosts.length === 0) {
        container.innerHTML = `<div style="text-align:center; color:var(--text-muted); padding:35px; background:var(--bg-card); border-radius:var(--radius-md); border:1px dashed var(--border-subtle);">${currentFeedSearch ? "No discussions match your search." : "No posts found in this channel yet."}</div>`;
        return;
    }

    filteredPosts.forEach(p => {
        const postCard = document.createElement('div');
        postCard.className = `post-card ${p.is_announcement ? 'is-pinned-announcement' : ''}`;

        let statusClass = 'status-open';
        if (p.status === 'Under Review') statusClass = 'status-review';
        else if (p.status === 'Action Taken') statusClass = 'status-resolved';

        let displayActionNote = p.action_note || "";
        if (displayActionNote.startsWith("EXP:")) {
            const parts = displayActionNote.split('|');
            displayActionNote = parts.length > 1 ? parts.slice(1).join('|') : "";
        }

        let resolutionHTML = '';
        if (displayActionNote) {
            resolutionHTML = `
                <div class="resolution-box ${p.status === 'Under Review' ? 'under-review' : ''}">
                    <div class="resolution-header-row">
                        <div>
                            <strong>${p.status === 'Action Taken' ? '🟢 Official Action Taken' : '🟡 Review in Progress'}</strong>
                            <span style="font-size:0.72rem; color:var(--text-muted); margin-left:6px;">by ${esc(p.action_by || 'Faculty')}</span>
                        </div>
                        <div class="resolution-reaction-bar">
                            <span style="font-size:0.68rem; color:var(--text-muted); margin-right:2px;">Reaction:</span>
                            <button class="btn-res-react ${p.user_resolution_vote === 1 ? 'active-up' : ''}" onclick="voteResolution(${p.id}, 1)">👍 ${p.resolution_upvotes}</button>
                            <button class="btn-res-react ${p.user_resolution_vote === -1 ? 'active-down' : ''}" onclick="voteResolution(${p.id}, -1)">👎 ${p.resolution_downvotes}</button>
                        </div>
                    </div>
                    <div style="color:var(--text-heading); line-height:1.4; margin-top:4px;">${esc(displayActionNote)}</div>
                </div>
            `;
        }

        const scoreColorClass = p.score > 0 ? 'positive' : (p.score < 0 ? 'negative' : '');
        const pinHeaderHTML = p.is_announcement ? `
            <div style="display:flex; align-items:center; gap:6px; color:var(--txt-gold); font-size:0.75rem; font-weight:800; margin-bottom:6px;">
                <span>📌 OFFICIAL CAMPUS BROADCAST</span>
                <span style="color:var(--text-muted); font-weight:normal;">&bull; By <strong>${esc(p.author_name || 'Elected Officer')}</strong> (${esc(p.author_role)})</span>
            </div>
        ` : '';

        const mediaImageHTML = p.image_url ? `<div class="post-media-container"><img src="${esc(safeImg(p.image_url))}" alt="Post media attachment" class="post-media-img" onerror="this.parentElement.style.display='none';"></div>` : '';
        const mediaLinkHTML = p.link_url ? `<div><a href="${esc(safeUrl(p.link_url))}" target="_blank" rel="noopener noreferrer" class="post-link-card"><span>🔗</span><span>${esc(p.link_url)}</span></a></div>` : '';

        postCard.innerHTML = `
            <div class="vote-column">
                <button class="btn-vote ${p.user_vote === 1 ? 'voted-up' : ''}" onclick="votePost(${p.id}, 1)">▲</button>
                <div class="vote-score ${scoreColorClass}">${p.score}</div>
                <button class="btn-vote ${p.user_vote === -1 ? 'voted-down' : ''}" onclick="votePost(${p.id}, -1)">▼</button>
                <span style="font-size:0.56rem; color:var(--text-muted); text-align:center; margin-top:2px;">Consensus</span>
            </div>
            <div class="post-content-area">
                ${pinHeaderHTML}
                <div class="post-header">
                    <span class="post-channel-tag">${p.target_channel === 'ALL' ? 'Campus-Wide' : esc(p.target_channel)}</span>
                    <span class="post-anon-tag">${p.is_announcement ? `📢 ${esc(p.author_name || 'Verified Leader')}` : `👤 Verified Student`}</span>
                    <span class="post-cat-badge">${esc(p.category)}</span>
                    <span class="badge-status-pill ${statusClass}">${esc(p.status)}</span>
                    ${p.is_edited ? '<span style="font-size:0.7rem; color:var(--text-muted); font-style:italic;">(Edited)</span>' : ''}
                    <span style="font-size:0.72rem; color:var(--text-muted); margin-left:auto;">${esc(p.created_at)}</span>
                </div>
                <div class="post-text">"${esc(p.content)}"</div>
                ${mediaImageHTML}
                ${mediaLinkHTML}
                <div style="display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom:6px;">
                    ${p.is_announcement ? '' : `<span class="post-cat-badge" style="background:rgba(37,99,235,0.15); color:var(--txt-blue);">AI Evaluated: ${esc(p.sentiment)}</span>`}
                    <button type="button" class="comments-toggle-btn" id="commentsBtn_${p.id}" aria-expanded="false" aria-controls="commentsThread_${p.id}" onclick="toggleComments(${p.id})"><span class="ct-ic" aria-hidden="true">💬</span><span class="ct-label" id="commentsLabel_${p.id}">${commentButtonLabel(p.comment_count, false)}</span><span class="ct-caret" aria-hidden="true">▾</span></button>
                    ${p.can_edit ? `<button onclick="openEditModal(${p.id})" style="background:none; border:none; color:var(--txt-blue); font-size:0.75rem; font-weight:700; cursor:pointer; text-decoration:underline;">✏️ Edit Post</button>` : ''}
                    ${isAuthorizedAnnouncer ? `<button onclick="openActionModal(${p.id}, '${esc(p.status)}')" style="background:none; border:none; color:var(--txt-gold); font-size:0.75rem; font-weight:700; cursor:pointer; text-decoration:underline;">✍ Post Resolution</button>` : ''}
                </div>
                ${resolutionHTML}
                <div class="comments-thread-container" id="commentsThread_${p.id}">
                    <div class="ct-head">💬 Discussion</div>
                    <div id="commentsList_${p.id}" style="display:flex; flex-direction:column; gap:8px;"></div>
                    <div class="comment-reply-box">
                        <input type="text" class="comment-input" id="replyInput_${p.id}" maxlength="1000" placeholder="Write a comment…" aria-label="Write a comment" onkeydown="if(event.key==='Enter'){event.preventDefault();submitComment(${p.id});}">
                        <button type="button" class="btn-action ct-reply" onclick="submitComment(${p.id})">Reply</button>
                    </div>
                </div>
            </div>
        `;
        container.appendChild(postCard);
    });
}

async function submitTownHallPost() {
    const content = document.getElementById('townContent').value.trim();
    const category = document.getElementById('townCategory').value;
    const target_channel = document.getElementById('townTargetChannel').value;
    const announcementCheckbox = document.getElementById('townIsAnnouncement');
    const is_announcement = (isAuthorizedAnnouncer && announcementCheckbox) ? announcementCheckbox.checked : false;
    const link_url = document.getElementById('townLinkUrl').value.trim() || null;
    const image_url = attachedImages['town'];
    const inspectToggle = document.getElementById('inspectAiToggle');

    if (!content || content.length < 4) return showToast("Post must be at least 4 characters.", 'warning');

    let action_note = null;
    if (is_announcement) {
        const expDateInput = document.getElementById('townExpirationDate');
        if (expDateInput && expDateInput.value) {
            action_note = "EXP:" + expDateInput.value + "|";
        }
        if (!_validateExpiry('town')) return;
    }

    pendingPostPayload = { content, category, target_channel, is_announcement, image_url, link_url, action_note };

    if (inspectToggle && inspectToggle.checked) {
        showLoader("Running local XLM-RoBERTa AI Analysis...");
        try {
            const res = await apiFetch('/api/inspect_preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
                body: JSON.stringify({ comment: content })
            });
            const data = await res.json();
            hideLoader();

            if (res.ok) {
                document.getElementById('inspectTextCorpus').innerText = `"${data.raw}"`;
                document.getElementById('inspectSentimentVal').innerText = data.sentiment;
                document.getElementById('inspectSentimentVal').style.color = data.sentiment === 'Positive' ? 'var(--txt-green-strong)' : (data.sentiment === 'Negative' ? 'var(--txt-red-strong)' : 'var(--txt-amber-strong)');
                document.getElementById('inspectConfidenceVal').innerText = `${Math.round(data.confidence_score * 100)}%`;

                const clausesContainer = document.getElementById('inspectAspectClauses');
                clausesContainer.innerHTML = '';
                if (data.aspect_breakdown && data.aspect_breakdown.length > 0) {
                    data.aspect_breakdown.forEach(item => {
                        const row = document.createElement('div');
                        row.style.cssText = "background:rgba(255,255,255,0.03); padding:6px 10px; border-radius:6px; border:1px solid rgba(255,255,255,0.05);";
                        row.innerHTML = `<strong>[${item.aspect}]</strong> "${esc(item.clause)}" &bull; <span style="color:${item.polarity === 'Positive' ? 'var(--txt-green)' : (item.polarity === 'Negative' ? 'var(--txt-red)' : 'var(--txt-gold)')};">${item.polarity}</span>`;
                        clausesContainer.appendChild(row);
                    });
                } else {
                    clausesContainer.innerHTML = '<div>No distinct sentiment clauses detected.</div>';
                }

                openModal('aiInspectionModal');
                return;
            }
        } catch (e) { hideLoader(); showToast(e.userMessage || "Could not run the AI preview. Please try again.", 'error'); }
    }

    executePostSubmission(pendingPostPayload);
}

function closeAiInspectionModal() { closeModal('aiInspectionModal'); }

async function confirmAndPublishPost() {
    closeAiInspectionModal();
    if (pendingPostPayload) { executePostSubmission(pendingPostPayload); }
}

async function executePostSubmission(payload) {
    showLoader("Publishing to community feed...");
    try {
        const res = await apiFetch('/api/community_post', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
            body: JSON.stringify(payload)
        });
        if (res.ok) {
            const okData = await res.json().catch(() => ({}));
            document.getElementById('townContent').value = '';
            document.getElementById('townLinkUrl').value = '';
            removeAttachedImage('town');
            const announcementCheckbox = document.getElementById('townIsAnnouncement');
            if (announcementCheckbox) announcementCheckbox.checked = false;
            const inspectToggle = document.getElementById('inspectAiToggle');
            if (inspectToggle) inspectToggle.checked = false;
            _clearExpiry('town');

            showToast(okData.masked ? "Posted. A few words were replaced with asterisks to keep the community respectful." : "Posted successfully!", 'success');
            fetchTownHallFeed();
            fetchCommunityPulse();
        } else {
            const data = await res.json();
            showToast(data.error || "Post failed.", 'error');
        }
    } catch (e) { showToast(e.userMessage || "Server error.", 'error'); } finally { hideLoader(); }
}

function openEditModal(postId) {
    const post = feedPostsCache.find(p => p.id === postId);
    if (!post) return;
    document.getElementById('editPostId').value = postId;
    document.getElementById('editPostContent').value = post.content;
    document.getElementById('editPostCategory').value = post.category;
    document.getElementById('editPostLinkUrl').value = post.link_url || '';
    document.getElementById('editPostIsAnnouncement').value = post.is_announcement ? 'true' : 'false';

    const expContainer = document.getElementById('editExpirationContainer');
    if (post.is_announcement && expContainer) {
        expContainer.style.display = 'block';
        _setExpiryMin('edit');
        if (post.action_note && post.action_note.startsWith('EXP:')) {
            _loadExpiryIntoPicker('edit', post.action_note.split('EXP:')[1].split('|')[0]);
        } else {
            _clearExpiry('edit');
        }
    } else if (expContainer) {
        expContainer.style.display = 'none';
    }

    if (post.image_url) {
        attachedImages['edit'] = post.image_url;
        document.getElementById('editPostImageUrl').value = post.image_url;
        showPreviewBadge('edit', post.image_url, "Attached Image");
    } else { removeAttachedImage('edit'); }
    
    openModal('editPostModal');
}

function closeEditModal() { closeModal('editPostModal'); }

async function submitEditPost() {
    const postId = document.getElementById('editPostId').value;
    const content = document.getElementById('editPostContent').value.trim();
    const category = document.getElementById('editPostCategory').value;
    const link_url = document.getElementById('editPostLinkUrl').value.trim();
    const image_url = attachedImages['edit'];
    const is_ann = document.getElementById('editPostIsAnnouncement').value === 'true';

    if (!content || content.length < 4) return showToast("Post must be at least 4 characters.", 'warning');

    let new_action_note = null;
    if (is_ann) {
        const expDateInput = document.getElementById('editExpirationDate');
        if (expDateInput && expDateInput.value) {
            new_action_note = "EXP:" + expDateInput.value + "|";
        }
        if (!_validateExpiry('edit')) return;
    }

    closeEditModal();
    showLoader("Updating...");
    try {
        const res = await apiFetch(`/api/community_post/${postId}/edit`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
            body: JSON.stringify({ content, category, image_url, link_url, action_note: new_action_note })
        });
        if (res.ok) {
            showToast("Post updated!", 'success');
            fetchTownHallFeed();
        } else {
            const data = await res.json();
            showToast(data.error || "Could not update the post.", 'error');
        }
    } catch (e) { showToast(e.userMessage || "Server error while updating the post.", 'error'); } finally { hideLoader(); }
}

async function votePost(postId, direction) {
    try {
        const res = await apiFetch('/api/community_post/vote', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN }, body: JSON.stringify({ post_id: postId, direction }) });
        if (res.ok) fetchTownHallFeed(); else showToast((await res.json()).error || "Your vote could not be saved.", 'error');
    } catch (e) { showToast(e.userMessage || "Vote error.", 'error'); }
}

async function voteResolution(postId, direction) {
    try {
        const res = await apiFetch('/api/community_post/resolution_vote', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN }, body: JSON.stringify({ post_id: postId, direction }) });
        if (res.ok) fetchTownHallFeed(); else showToast((await res.json()).error || "Your reaction could not be saved.", 'error');
    } catch (e) { showToast(e.userMessage || "Reaction error.", 'error'); }
}

function commentButtonLabel(n, open) {
    if (open) return 'Hide discussion';
    n = Number(n) || 0;
    return n === 0 ? 'Be the first to comment' : `${n} ${n === 1 ? 'comment' : 'comments'} · Join the discussion`;
}
function _syncCommentButton(postId, open, count) {
    const btn = document.getElementById(`commentsBtn_${postId}`);
    const label = document.getElementById(`commentsLabel_${postId}`);
    if (btn) { btn.classList.toggle('is-open', open); btn.setAttribute('aria-expanded', open ? 'true' : 'false'); btn.dataset.count = count; }
    if (label) label.textContent = commentButtonLabel(count, open);
}

async function toggleComments(postId) {
    const thread = document.getElementById(`commentsThread_${postId}`);
    if (!thread) return;
    const btn = document.getElementById(`commentsBtn_${postId}`);
    const known = btn && btn.dataset.count !== undefined ? Number(btn.dataset.count) : 0;
    if (thread.style.display === 'flex') {
        thread.style.display = 'none';
        _syncCommentButton(postId, false, known);
        return;
    }
    thread.style.display = 'flex';
    let comments;
    try {
        const res = await apiFetch(`/api/community_post/${postId}/comments`);
        comments = await res.json();
        if (!res.ok || !Array.isArray(comments)) throw new Error((comments && comments.error) || "Could not load comments.");
    } catch (e) {
        thread.style.display = 'none'; _syncCommentButton(postId, false, known);
        showToast(e.userMessage || e.message || "Could not load comments.", 'error'); return;
    }
    _syncCommentButton(postId, true, comments.length);
    const list = document.getElementById(`commentsList_${postId}`);
    list.innerHTML = (comments.length === 0) ? `<div class="ct-empty">No comments yet. Start the conversation below.</div>` :
        comments.map(c => `
            <div class="comment-item">
                <div style="display:flex; justify-content:space-between; font-size:0.7rem; color:var(--text-muted); margin-bottom:4px;">
                    <strong style="color:var(--txt-blue);">👤 Verified Student</strong>
                    <span>${esc(c.created_at)}</span>
                </div>
                <div style="font-size:0.84rem; color:var(--text-body);">${esc(c.content)}</div>
            </div>
        `).join('');
}

async function submitComment(postId) {
    const input = document.getElementById(`replyInput_${postId}`);
    const content = input.value.trim();
    if (!content) return;
    try {
        const res = await apiFetch(`/api/community_post/${postId}/comments`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN }, body: JSON.stringify({ content }) });
        if (res.ok) {
            input.value = '';
            const thread = document.getElementById(`commentsThread_${postId}`);
            thread.style.display = 'none';
            toggleComments(postId);
        } else { showToast((await res.json()).error || "Your reply could not be posted.", 'error'); }
    } catch (e) { showToast(e.userMessage || "Reply error.", 'error'); }
}

function openActionModal(postId, currentStatus) {
    const post = feedPostsCache.find(p => p.id === postId);
    document.getElementById('actionPostId').value = postId;
    document.getElementById('actionStatusSelect').value = currentStatus === 'Action Taken' ? 'Action Taken' : 'Under Review';
    
    let displayActionNote = post ? (post.action_note || '') : '';
    if (displayActionNote.startsWith('EXP:')) {
        const parts = displayActionNote.split('|');
        displayActionNote = parts.length > 1 ? parts.slice(1).join('|') : '';
    }
    document.getElementById('actionNoteText').value = displayActionNote;
    openModal('actionModal');
}
function closeActionModal() { closeModal('actionModal'); }

async function submitDutyAction() {
    const postId = document.getElementById('actionPostId').value;
    const status = document.getElementById('actionStatusSelect').value;
    let action_note = document.getElementById('actionNoteText').value.trim();
    if (!action_note) return showToast("Please write a resolution note.", 'warning');
    
    const post = feedPostsCache.find(p => p.id == postId);
    if (post && post.action_note && post.action_note.startsWith('EXP:')) {
        const expTag = post.action_note.split('|')[0];
        action_note = expTag + '|' + action_note;
    }

    closeActionModal();
    showLoader("Updating status...");
    try {
        const res = await apiFetch('/api/community_post/status', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN }, body: JSON.stringify({ post_id: postId, status, action_note }) });
        if (res.ok) fetchTownHallFeed(); else showToast((await res.json()).error || "Could not update the status.", 'error');
    } catch (e) { showToast(e.userMessage || "Server error while updating the status.", 'error'); } finally { hideLoader(); }
}

function toggleAnnouncementMode(isAnnouncement) {
    const badge = document.getElementById('composeAnonymityBadge');
    const notice = document.getElementById('composerNoticeText');
    const channelSelect = document.getElementById('townTargetChannel');
    const catSelect = document.getElementById('townCategory');
    const expContainer = document.getElementById('expirationContainer');

    if (isAnnouncement) {
        badge.innerText = `📣 Official Broadcast (${currentUserRole})`;
        badge.style.background = 'rgba(245, 158, 11, 0.15)';
        badge.style.color = 'var(--txt-gold)';
        badge.style.borderColor = 'rgba(245, 158, 11, 0.4)';
        notice.innerText = "Official announcements are highlighted at the top with your verified leadership identity.";
        channelSelect.value = 'ANNOUNCEMENTS';
        catSelect.value = 'Campus Events & Traditions';
        if (expContainer) { expContainer.style.display = 'block'; _setExpiryMin('town'); }
    } else {
        badge.innerText = "🛡️ 100% Anonymous Voice";
        badge.style.background = 'rgba(16, 185, 129, 0.1)';
        badge.style.color = 'var(--txt-green)';
        badge.style.borderColor = 'rgba(16, 185, 129, 0.25)';
        notice.innerText = "Share feedback or report an issue. Peers can upvote (Agree) or downvote (Disagree) to reflect collective community consensus.";
        channelSelect.value = (activeChannel === 'ANNOUNCEMENTS') ? 'ALL' : activeChannel;
        if (expContainer) expContainer.style.display = 'none';
    }
}

function switchPortalTab(tab) {
    const chSection = document.getElementById('sidebarChannelsSection');
    if (tab === 'townhall') {
        document.getElementById('tabTownHall').classList.add('active');
        document.getElementById('tabSurveys').classList.remove('active');
        document.getElementById('sectionTownHall').style.display = 'block';
        document.getElementById('sectionSurveys').style.display = 'none';
        if (chSection) chSection.style.display = 'block';
    } else {
        document.getElementById('tabTownHall').classList.remove('active');
        document.getElementById('tabSurveys').classList.add('active');
        document.getElementById('sectionTownHall').style.display = 'none';
        document.getElementById('sectionSurveys').style.display = 'block';
        if (chSection) chSection.style.display = 'none';
    }
    if (window.innerWidth <= 992) closeMobileDrawer();
}

function switchChannel(channel, btn) {
    activeChannel = channel;
    document.querySelectorAll('.sidebar-nav-btn.channel-chip').forEach(c => {
        c.classList.remove('active');
        c.classList.remove('active-announcement');
    });

    const composeCard = document.getElementById('townhallComposeCard');
    const readOnlyBanner = document.getElementById('announcementsReadBanner');
    const targetSelect = document.getElementById('townTargetChannel');

    // ONLY SHOW ALL, ANNOUNCEMENTS, and DCI
    if (channel === 'ANNOUNCEMENTS') {
        btn.classList.add('active-announcement');
        document.getElementById('currentChannelLabel').innerText = '📣 Campus Events & Announcements';

        if (!isAuthorizedAnnouncer) {
            composeCard.style.display = 'none';
            readOnlyBanner.style.display = 'block';
        } else {
            composeCard.style.display = 'block';
            readOnlyBanner.style.display = 'none';
            if (targetSelect && Array.from(targetSelect.options).some(o => o.value === 'ANNOUNCEMENTS')) {
                targetSelect.value = 'ANNOUNCEMENTS';
            }
            const chk = document.getElementById('townIsAnnouncement');
            if (chk) {
                chk.checked = true;
                toggleAnnouncementMode(true);
            }
        }
    } else {
        btn.classList.add('active');
        document.getElementById('currentChannelLabel').innerText = (channel === 'ALL') ? 'Campus-Wide' : channel + ' Channel';

        composeCard.style.display = 'block';
        readOnlyBanner.style.display = 'none';

        if (targetSelect) targetSelect.value = channel;
        const chk = document.getElementById('townIsAnnouncement');
        if (chk && chk.checked) {
            chk.checked = false;
            toggleAnnouncementMode(false);
        }
    }

    fetchTownHallFeed();
    if (window.innerWidth <= 992) closeMobileDrawer();
}

function setupDropZone(containerId, scope) {
    const container = document.getElementById(containerId);
    if (!container) return;

    ['dragenter', 'dragover'].forEach(eventName => {
        container.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            container.classList.add('dragover');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        container.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            container.classList.remove('dragover');
        }, false);
    });

    container.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files && files.length > 0) processImageFile(files[0], scope);
    }, false);
}

function handleFilePicked(event, scope) {
    const file = event.target.files[0];
    if (file) processImageFile(file, scope);
}

function processImageFile(file, scope) {
    if (!file.type.startsWith('image/')) return showToast("Please select an image file.", 'warning');
    if (file.size > 5 * 1024 * 1024) return showToast("Image must be smaller than 5MB.", 'warning');

    const reader = new FileReader();
    reader.onload = function(e) {
        const base64Data = e.target.result;
        attachedImages[scope] = base64Data;
        const inputEl = document.getElementById(scope === 'town' ? 'townImageUrl' : 'editPostImageUrl');
        if (inputEl) inputEl.value = `[Attached: ${file.name}]`;
        showPreviewBadge(scope, base64Data, file.name);
    };
    reader.readAsDataURL(file);
}

function handleUrlTyped(scope) {
    const inputId = (scope === 'town') ? 'townImageUrl' : 'editPostImageUrl';
    const val = document.getElementById(inputId).value.trim();
    if (val.startsWith('http://') || val.startsWith('https://')) {
        attachedImages[scope] = val;
        showPreviewBadge(scope, val, "Web URL Resource");
    } else if (!val) {
        removeAttachedImage(scope);
    }
}

function showPreviewBadge(scope, src, label) {
    const badge = document.getElementById(`${scope}PreviewBadge`);
    const img = document.getElementById(`${scope}PreviewImg`);
    const name = document.getElementById(`${scope}PreviewName`);
    if (badge && img && name) {
        img.src = src;
        name.innerText = label;
        badge.style.display = 'flex';
    }
}

function removeAttachedImage(scope) {
    attachedImages[scope] = null;
    const inputId = (scope === 'town') ? 'townImageUrl' : 'editPostImageUrl';
    const fileInputId = (scope === 'town') ? 'townFileInput' : 'editFileInput';
    const badge = document.getElementById(`${scope}PreviewBadge`);
    const inputEl = document.getElementById(inputId);
    const fileEl = document.getElementById(fileInputId);
    if (inputEl) inputEl.value = '';
    if (fileEl) fileEl.value = '';
    if (badge) badge.style.display = 'none';
}

function openLogoutModal() { openModal('logoutModal'); }
function closeLogoutModal() { closeModal('logoutModal'); }

let _farewellSlowTimer, _farewellStatusTimer;
const FAREWELL_MIN_MS = 2600;   // long enough to actually read the goodbye
function confirmLogout() {
    if (window._loggingOut) return;
    window._loggingOut = true;            // lets the back-button guard stand down
    const form = document.getElementById('logoutForm');
    if (!form) { window.location.href = '/login'; return; }

    closeLogoutModal();
    const screen = document.getElementById('farewellScreen');
    if (screen) {
        const nameEl = document.getElementById('farewellName');
        if (nameEl && window.APP_USERNAME) nameEl.textContent = window.APP_USERNAME;
        screen.classList.remove('slow');
        screen.style.display = 'flex';
        screen.classList.add('show');
        requestAnimationFrame(() => screen.classList.add('visible'));

        const status = document.getElementById('farewellStatus');
        const steps = ['Isinasara ang iyong session nang ligtas...', 'Nililinis ang device na ito...', 'Salamat sa pakikibahagi! Hanggang sa muli.'];
        let i = 0;
        if (status) status.textContent = steps[0];
        clearInterval(_farewellStatusTimer);
        _farewellStatusTimer = setInterval(() => { i = Math.min(i + 1, steps.length - 1); if (status) status.textContent = steps[i]; }, 1000);

        clearTimeout(_farewellSlowTimer);
        _farewellSlowTimer = setTimeout(() => {
            screen.classList.add('slow');
            if (status) status.textContent = 'Medyo matagal ito. This is taking longer than usual.';
        }, 9000);
    }

    // Really sign out right away, in the background, so the session is closed even if the tab is closed mid-goodbye.
    const started = performance.now();
    const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const minWait = reduced ? 900 : FAREWELL_MIN_MS;
    let signedOut = false;
    fetch(form.action, { method: 'POST', body: new URLSearchParams(new FormData(form)), credentials: 'same-origin', redirect: 'follow' })
        .then(r => { signedOut = r.ok; }).catch(() => { signedOut = false; })
        .then(() => {
            const wait = Math.max(0, minWait - (performance.now() - started));
            setTimeout(() => { if (signedOut) window.location.replace('/login'); else form.submit(); }, wait);
        });
}

function retryLogout() {
    const form = document.getElementById('logoutForm');
    if (form) form.submit();
}

// If the page is restored from the back/forward cache, never leave the farewell screen stuck on top
window.addEventListener('pageshow', (e) => {
    if (!e.persisted) return;
    clearInterval(_farewellStatusTimer); clearTimeout(_farewellSlowTimer);
    const screen = document.getElementById('farewellScreen');
    if (screen) { screen.classList.remove('show', 'visible', 'slow'); screen.style.display = ''; }
    window._loggingOut = false;
});

// Initialize
// ==========================================================
// GUIDED TOUR (first-time question + replay button)
// ==========================================================
function _showSurveyListPane() {
    const mine = document.getElementById('paneMySurveys');
    if (mine && mine.style.display !== 'none') toggleAuthoredSurveys();
}
function _parentOf(id) { const el = document.getElementById(id); return el ? el.parentElement : null; }
function buildStudentTourSteps() {
    const goTownHall = () => { _showSurveyListPane(); switchPortalTab('townhall'); };
    const goSurveys = () => { switchPortalTab('surveys'); _showSurveyListPane(); };
    const steps = [
        { title: "Welcome to your Voice Collective", body: "This is your safe space to share feedback and help improve our campus. There are two main areas: the <strong>Town Hall</strong> for open discussions, and <strong>Formal Surveys</strong> for school evaluations. " + (isAuthorizedAnnouncer ? "As a student leader or faculty member, you also get extra tools to post announcements and create surveys." : "(On a phone? You can also swipe left or right on this card!)") },
        { target: '#pulseSectionTarget', before: goTownHall, title: "Department Pulse", body: "A quick look at how students in our department are feeling right now: how many voices were recorded and the mix of positive, neutral, and negative feedback." },
        { target: '#tabTownHall', before: goTownHall, title: "Town Hall Forum", body: "Open the menu (☰ on phones) to visit the <strong>Town Hall</strong>, where you can read what classmates are talking about and share your own thoughts." },
        { target: '#sidebarChannelsSection', title: "Channels", body: "Switch between <strong>🏛️ Campus-Wide</strong> posts, official <strong>📣 Announcements</strong>, and our own <strong>💻 DCI Channel</strong>." },
        { target: '.sidebar-privacy-box', title: "Your Privacy is Protected", body: "Everything you post or answer is <strong>100% anonymous</strong>. Your name is never shown, and if someone accidentally types a phone number, email, or student ID, the system hides it automatically." },
        { target: () => document.getElementById('townhallComposeCard') || _parentOf('townContent'), before: goTownHall, title: "Share Your Voice", body: "Write your idea, concern, or praise in English, Tagalog, or Taglish, pick a category, and post. You can also tick the preview box before posting to see how the AI reads your message." },
    ];
    if (isAuthorizedAnnouncer) steps.push({ target: () => { const c = document.getElementById('townIsAnnouncement'); return (c && c.closest('div')) || document.getElementById('townhallComposeCard'); }, before: goTownHall, title: "Post Announcements & Updates", body: "As a student leader or faculty member, you can tick <strong>Official Announcement</strong> to pin important news at the top, or post an <strong>Action Taken</strong> update on a student concern." });
    steps.push(
        { target: () => document.querySelector('#townhallFeedContainer .comments-toggle-btn') || document.querySelector('#townhallFeedContainer .post-card') || document.getElementById('townhallFeedContainer'), before: goTownHall, title: "Vote & Join the Conversation", body: "Use the <strong>▲ ▼ arrows</strong> to agree or disagree so important topics rise to the top, and tap <strong>Join the discussion</strong> to read or write anonymous comments." },
        { target: '#feedSearchInput', before: goTownHall, title: "Search Posts", body: "Looking for a specific topic, room, or subject? Type any word here to filter the posts right away." },
        { target: '#tabSurveys', before: goSurveys, title: "Formal Surveys", body: "Switch to <strong>📋 Formal Surveys</strong> to answer official evaluations from your teachers and student officers. Your answers stay completely anonymous." },
        { target: '#surveyCategoryTabs', before: goSurveys, title: "Track Your Surveys", body: "<strong>Available</strong> shows surveys you can answer now. <strong>Due Today</strong> closes tonight, <strong>Missed</strong> shows past deadlines, and <strong>Completed</strong> lists the ones you already finished." },
        { target: '#formSearchInput', before: goSurveys, title: "Find & Answer a Survey", body: "Type a title or subject code to find a survey quickly, then tap <strong>Fill Out Evaluation</strong> to send your ratings and comments." }
    );
    if (isAuthorizedAnnouncer) steps.push(
        { target: '#createSurveyBtn', before: goSurveys, title: "Create a Survey", body: "Build your own survey with star ratings (1 to 5), multiple-choice, and written questions. You can also pick colors, add a header picture, and set a deadline or response limit." },
        { target: '#btnToggleAuthored', before: goSurveys, title: "Manage Your Surveys", body: "Open <strong>Surveys You Created</strong> to edit your survey, copy a share link to send to classmates, view the results, or download the answers as a spreadsheet (CSV)." }
    );
    steps.push(
        { target: '#themeToggle', title: "Light or Dark Mode", body: "Switch between dark and light mode anytime. The portal remembers what you prefer." },
        { target: '.btn-logout', title: "Sign Out Safely", body: "You stay signed in until you tap <strong>Sign Out</strong>, so always sign out when using a shared or computer lab PC." },
        { title: "You're All Set!", body: "Explore at your own pace. You can replay this guide anytime using the <strong>❓ Tour</strong> button at the top." }
    );
    return steps;
}
CCCTour.configure({
    steps: buildStudentTourSteps(),
    seen: !!window.APP_TOUR_SEEN,
    appName: 'the Voice Collective',
    userName: window.APP_USERNAME || '',
    csrf: CSRF_TOKEN,
    seenEndpoint: '/api/tutorial/seen',
    onEnd: () => { try { _showSurveyListPane(); switchPortalTab('townhall'); } catch (e) { /* ignore */ } }
});

document.addEventListener('DOMContentLoaded', () => {
    setupDropZone('townImageDropContainer', 'town');
    setupDropZone('editImageDropContainer', 'edit');
    const titleInput = document.getElementById('newFormTitle');
    if (titleInput) titleInput.addEventListener('input', renderThemePreview);
    const initialLoad = Promise.allSettled([fetchCommunityPulse(), fetchTownHallFeed(), loadAllForms()]);
    runSplash(initialLoad).then(() => setTimeout(() => CCCTour.promptIfFirstTime(), 500));   // ask about the tour only once the intro is gone
});