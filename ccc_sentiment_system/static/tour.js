/* Voice Collective & Oversight Dashboard Guided Tour (shared by student_portal.html and dashboard.html).
   CCCTour.configure({ steps, seen, appName, userName, csrf, seenEndpoint, onEnd })
   CCCTour.promptIfFirstTime()  -> asks first-time users whether they want the tour
   CCCTour.start()              -> runs the tour (used by the "Tour" button)                       */
(function () {
    'use strict';
    var cfg = { steps: [], seen: true, appName: 'the portal', userName: '', csrf: '', seenEndpoint: '' };
    var root = null, ring = null, shade = null, card = null, welcome = null;
    var idx = 0, active = false, lastFocus = null, raf = 0, token = 0;
    var reduced = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    var isTouch = !!(('ontouchstart' in window) || (navigator.maxTouchPoints && navigator.maxTouchPoints > 0) || (window.matchMedia && window.matchMedia('(pointer: coarse)').matches));

    function el(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
    function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
    function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

    function isMobileViewport() { return window.innerWidth <= 640; }
    function isDrawerViewport() { return window.innerWidth <= 992; }

    function isVisible(e) {
        if (!e || !e.getBoundingClientRect) return false;
        var r = e.getBoundingClientRect(), cs = window.getComputedStyle(e);
        if (r.width <= 0 || r.height <= 0 || cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) === 0) return false;
        return true;
    }

    function resolveTarget(step) {
        if (!step || !step.target) return null;
        try { return typeof step.target === 'function' ? step.target() : document.querySelector(step.target); } catch (e) { return null; }
    }

    function isFixedOrSticky(e) {
        var cur = e;
        while (cur && cur !== document.body && cur !== document.documentElement) {
            var pos = window.getComputedStyle(cur).position;
            if (pos === 'fixed' || pos === 'sticky') return true;
            cur = cur.parentElement;
        }
        return false;
    }

    async function syncMobileDrawerForTarget(target) {
        var sidebar = document.getElementById('portalSidebar');
        if (!sidebar || !isDrawerViewport()) return;
        var insideSidebar = !!(target && sidebar.contains(target));
        var isOpen = sidebar.classList.contains('drawer-open');

        if (insideSidebar && !isOpen) {
            if (typeof window.openMobileDrawer === 'function') window.openMobileDrawer();
            else sidebar.classList.add('drawer-open');
            await wait(reduced ? 40 : 340);
        } else if (!insideSidebar && isOpen) {
            if (typeof window.closeMobileDrawer === 'function') window.closeMobileDrawer();
            else sidebar.classList.remove('drawer-open');
            await wait(reduced ? 30 : 220);
        }

        if (insideSidebar && target) {
            try {
                var sr = sidebar.getBoundingClientRect();
                var tr = target.getBoundingClientRect();
                if (tr.top < sr.top + 16 || tr.bottom > sr.bottom - 16) {
                    sidebar.scrollTop += (tr.top - sr.top) - Math.max(24, (sr.height - tr.height) / 3);
                }
            } catch (e) { /* ignore */ }
        }
    }

    function scrollHorizontallyIntoView(target) {
        if (!target) return false;
        var scrolled = false;
        var cur = target.parentElement;
        while (cur && cur !== document.body && cur !== document.documentElement) {
            if (cur.scrollWidth > cur.clientWidth + 6) {
                var cs = window.getComputedStyle(cur);
                if (cs.overflowX === 'auto' || cs.overflowX === 'scroll') {
                    var cr = cur.getBoundingClientRect();
                    var tr = target.getBoundingClientRect();
                    var delta = (tr.left + tr.width / 2) - (cr.left + cr.width / 2);
                    if (Math.abs(delta) > 8) {
                        cur.scrollLeft += delta;
                        scrolled = true;
                    }
                }
            }
            cur = cur.parentElement;
        }
        return scrolled;
    }

    async function scrollVerticallyToTarget(target) {
        if (!target || isFixedOrSticky(target)) return;
        var vh = (window.visualViewport && window.visualViewport.height) || window.innerHeight;
        var r = target.getBoundingClientRect();
        var mobile = isMobileViewport();

        if (mobile) {
            var topSafe = Math.max(70, Math.round(vh * 0.11));
            var desiredY = window.pageYOffset + r.top - topSafe;
            var maxScroll = Math.max(0, document.documentElement.scrollHeight - vh);
            desiredY = Math.max(0, Math.min(maxScroll, desiredY));
            if (Math.abs(desiredY - window.pageYOffset) > 12) {
                window.scrollTo({ top: desiredY, behavior: reduced ? 'auto' : 'smooth' });
                await wait(reduced ? 40 : 380);
            }
        } else {
            var inView = r.top >= 76 && r.bottom <= vh - 76;
            if (!inView) {
                try {
                    target.scrollIntoView({ block: r.height > vh * 0.65 ? 'start' : 'center', behavior: reduced ? 'auto' : 'smooth' });
                } catch (e) {
                    window.scrollTo(0, Math.max(0, window.pageYOffset + r.top - 90));
                }
                await wait(reduced ? 40 : 380);
            }
        }
    }

    var seenSent = false;
    function markSeen() {
        try { sessionStorage.setItem('ccc_tour_seen_session', '1'); } catch (e) { /* ignore */ }
        cfg.seen = true;
        if (!cfg.seenEndpoint || seenSent) return;
        seenSent = true;
        try {
            fetch(cfg.seenEndpoint, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': cfg.csrf || '' }, body: '{}' }).catch(function () {});
        } catch (e) { /* the prompt just won't be remembered across devices */ }
    }

    /* ---------- the tour itself ---------- */
    function build() {
        root = el('div', 'ccc-tour');
        shade = el('div', 'ccc-tour-shade');
        ring = el('div', 'ccc-tour-ring');
        card = el('div', 'ccc-tour-card');
        card.setAttribute('role', 'dialog'); card.setAttribute('aria-modal', 'true'); card.setAttribute('aria-labelledby', 'cccTourTitle'); card.setAttribute('aria-describedby', 'cccTourBody');
        card.innerHTML = '<div class="ccc-tour-head"><div class="ccc-tour-step" id="cccTourStep"></div><button type="button" class="ccc-tour-close" id="cccTourClose" aria-label="Close tour" title="Close tour">✕</button></div>' +
            '<h3 class="ccc-tour-title" id="cccTourTitle"></h3><p class="ccc-tour-body" id="cccTourBody" aria-live="polite"></p>' +
            '<div class="ccc-tour-dots" id="cccTourDots"></div>' +
            '<div class="ccc-tour-actions"><button type="button" class="ccc-tour-skip" id="cccTourSkip">Skip tour</button><span class="ccc-tour-spacer"></span>' +
            '<button type="button" class="ccc-tour-btn ccc-tour-back" id="cccTourBack">Back</button><button type="button" class="ccc-tour-btn ccc-tour-next" id="cccTourNext">Next</button></div>';
        root.appendChild(shade); root.appendChild(ring); root.appendChild(card);
        document.body.appendChild(root);

        card.querySelector('#cccTourSkip').addEventListener('click', function () { end(false); });
        card.querySelector('#cccTourClose').addEventListener('click', function () { end(false); });
        card.querySelector('#cccTourBack').addEventListener('click', function () { if (idx > 0) go(idx - 1); });
        card.querySelector('#cccTourNext').addEventListener('click', function () { if (idx >= cfg.steps.length - 1) end(true); else go(idx + 1); });

        // Touch swipe left / right on the tour card for mobile devices
        var touchStartX = 0, touchStartY = 0;
        card.addEventListener('touchstart', function (e) {
            if (!e.touches || e.touches.length !== 1) return;
            touchStartX = e.touches[0].clientX;
            touchStartY = e.touches[0].clientY;
        }, { passive: true });
        card.addEventListener('touchend', function (e) {
            if (!e.changedTouches || e.changedTouches.length !== 1) return;
            var dx = e.changedTouches[0].clientX - touchStartX;
            var dy = e.changedTouches[0].clientY - touchStartY;
            if (Math.abs(dx) > 52 && Math.abs(dx) > Math.abs(dy) * 1.5) {
                if (dx < 0 && idx < cfg.steps.length - 1) go(idx + 1);
                else if (dx > 0 && idx > 0) go(idx - 1);
            }
        }, { passive: true });
    }

    function place(target) {
        var vw = window.innerWidth;
        var vh = (window.visualViewport && window.visualViewport.height) || window.innerHeight;
        var vTop = (window.visualViewport && window.visualViewport.offsetTop) || 0;
        var pad = isMobileViewport() ? 6 : 8;
        var m = isMobileViewport() ? 10 : 12;

        // Reset mobile dock classes before measuring card
        card.classList.remove('ccc-tour-mobile-top', 'ccc-tour-mobile-bottom');

        if (target && isVisible(target)) {
            var r = target.getBoundingClientRect();
            ring.style.opacity = '1';
            shade.style.opacity = '0';

            if (isMobileViewport()) {
                card.style.left = m + 'px';
                card.style.right = m + 'px';
                card.style.width = 'auto';
                var ch = card.offsetHeight || 200;

                // Dock card at the top if target starts in the bottom half of the screen; otherwise dock at the bottom
                var dockTop = (r.top > vh * 0.48) && (r.bottom > vh - ch - m * 2);
                if (dockTop) {
                    card.classList.add('ccc-tour-mobile-top');
                    card.style.top = (vTop + m) + 'px';
                    card.style.bottom = 'auto';
                } else {
                    card.classList.add('ccc-tour-mobile-bottom');
                    card.style.bottom = m + 'px';
                    card.style.top = 'auto';
                }

                // Clamp spotlight ring so it never overlaps the docked tour card or overflows the screen
                var rLeft = Math.max(4, r.left - pad);
                var rRight = Math.min(vw - 4, r.right + pad);
                var rTop = Math.max(dockTop ? (vTop + ch + m + 8) : 6, r.top - pad);
                var maxBottom = dockTop ? (vh - 6) : (vh - ch - m - 8);
                var rBottom = Math.min(maxBottom, r.bottom + pad);
                if (rBottom - rTop < 44) {
                    rBottom = Math.min(vh - 6, rTop + Math.min(r.height + pad * 2, 120));
                }

                ring.style.left = rLeft + 'px';
                ring.style.top = rTop + 'px';
                ring.style.width = Math.max(40, rRight - rLeft) + 'px';
                ring.style.height = Math.max(36, rBottom - rTop) + 'px';
                return;
            }

            // Desktop & Tablet (> 640px)
            card.style.right = 'auto';
            card.style.bottom = 'auto';
            card.style.width = '';
            var cw = card.offsetWidth || 380;
            var dch = card.offsetHeight || 200;

            var dLeft = Math.max(6, r.left - pad);
            var dTop = Math.max(6, r.top - pad);
            var dWidth = Math.min(vw - dLeft - 6, r.width + pad * 2);
            var dHeight = Math.min(vh - dTop - 6, r.height + pad * 2);

            ring.style.left = dLeft + 'px';
            ring.style.top = dTop + 'px';
            ring.style.width = Math.max(36, dWidth) + 'px';
            ring.style.height = Math.max(32, dHeight) + 'px';

            var left = Math.min(Math.max(m, r.left + r.width / 2 - cw / 2), vw - cw - m);
            var top;
            if (r.bottom + pad + 14 + dch <= vh - m) {
                top = r.bottom + pad + 14; // below
            } else if (r.top - pad - 14 - dch >= m) {
                top = r.top - pad - 14 - dch; // above
            } else if (r.right + pad + 14 + cw <= vw - m) {
                left = r.right + pad + 14;
                top = Math.min(Math.max(m, r.top + r.height / 2 - dch / 2), vh - dch - m); // right beside
            } else if (r.left - pad - 14 - cw >= m) {
                left = r.left - pad - 14 - cw;
                top = Math.min(Math.max(m, r.top + r.height / 2 - dch / 2), vh - dch - m); // left beside
            } else {
                left = Math.max(m, vw - cw - m);
                top = Math.max(m, vh - dch - m);
            }
            card.style.left = left + 'px';
            card.style.top = top + 'px';
        } else {
            ring.style.opacity = '0';
            shade.style.opacity = '1';
            if (isMobileViewport()) {
                card.classList.add('ccc-tour-mobile-bottom');
                card.style.left = m + 'px';
                card.style.right = m + 'px';
                card.style.width = 'auto';
                card.style.top = 'auto';
                card.style.bottom = m + 'px';
            } else {
                card.style.right = 'auto';
                card.style.bottom = 'auto';
                card.style.width = '';
                var cw2 = card.offsetWidth || 380;
                var ch2 = card.offsetHeight || 200;
                card.style.left = Math.max(m, (vw - cw2) / 2) + 'px';
                card.style.top = Math.max(m, (vh - ch2) / 2.2) + 'px';
            }
        }
    }

    async function go(i) {
        if (!active) return;
        var my = ++token;
        i = Math.max(0, Math.min(cfg.steps.length - 1, i));
        idx = i;
        var step = cfg.steps[i];

        if (typeof step.before === 'function') {
            try { await step.before(); } catch (e) { /* ignore */ }
        }
        if (my !== token || !active) return;
        await wait(step.delay || 90);

        var target = resolveTarget(step);
        for (var tries = 0; !target && tries < 4 && step.target; tries++) {
            await wait(180);
            if (my !== token || !active) return;
            target = resolveTarget(step);
        }

        // Open or close the mobile sidebar drawer if the target lives inside #portalSidebar
        await syncMobileDrawerForTarget(target);
        if (my !== token || !active) return;

        // Re-check visibility after drawer state is synced
        if (!isVisible(target) && step.fallbackTarget) {
            try {
                target = typeof step.fallbackTarget === 'function' ? step.fallbackTarget() : document.querySelector(step.fallbackTarget);
            } catch (e) { target = null; }
            await syncMobileDrawerForTarget(target);
        }
        if (!isVisible(target)) target = null;

        if (target) {
            var hScrolled = scrollHorizontallyIntoView(target);
            if (hScrolled) await wait(120);
            await scrollVerticallyToTarget(target);
        }
        if (my !== token || !active) return;

        card.querySelector('#cccTourStep').textContent = 'Step ' + (i + 1) + ' of ' + cfg.steps.length;
        card.querySelector('#cccTourTitle').textContent = step.title || '';
        card.querySelector('#cccTourBody').innerHTML = step.body || '';
        card.querySelector('#cccTourDots').innerHTML = cfg.steps.map(function (_, k) {
            return '<i class="' + (k === i ? 'on' : (k < i ? 'done' : '')) + '"></i>';
        }).join('');
        card.querySelector('#cccTourBack').style.visibility = i === 0 ? 'hidden' : 'visible';
        card.querySelector('#cccTourNext').textContent = i === cfg.steps.length - 1 ? 'Finish' : 'Next';
        card.classList.remove('ccc-tour-in');
        void card.offsetWidth;
        card.classList.add('ccc-tour-in');

        place(target);
        card._target = target;

        if (!isTouch) {
            try { card.querySelector('#cccTourNext').focus({ preventScroll: true }); } catch (e) { /* ignore */ }
        }
    }

    function onKey(e) {
        if (!active) return;
        if (e.key === 'Escape') { e.preventDefault(); end(false); }
        else if (e.key === 'ArrowRight') { e.preventDefault(); if (idx < cfg.steps.length - 1) go(idx + 1); }
        else if (e.key === 'ArrowLeft') { e.preventDefault(); if (idx > 0) go(idx - 1); }
        else if (e.key === 'Tab') {
            var f = card.querySelectorAll('button');
            var vis = Array.prototype.filter.call(f, function (b) { return b.style.visibility !== 'hidden'; });
            if (!vis.length) return;
            var first = vis[0], last = vis[vis.length - 1];
            if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
    }

    function reposition() {
        if (!active) return;
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(function () {
            place(card._target && isVisible(card._target) ? card._target : null);
        });
    }

    function start(from) {
        if (active || !cfg.steps.length) return;
        closeWelcome();
        active = true;
        lastFocus = document.activeElement;
        if (!root) build();
        root.style.display = 'block';
        document.addEventListener('keydown', onKey, true);
        window.addEventListener('resize', reposition);
        window.addEventListener('scroll', reposition, true);
        if (window.visualViewport) window.visualViewport.addEventListener('resize', reposition);
        markSeen();
        go(typeof from === 'number' ? from : 0);
    }

    function end(finished) {
        if (!active) return;
        active = false;
        token++;
        document.removeEventListener('keydown', onKey, true);
        window.removeEventListener('resize', reposition);
        window.removeEventListener('scroll', reposition, true);
        if (window.visualViewport) window.visualViewport.removeEventListener('resize', reposition);
        if (root) root.style.display = 'none';
        if (isDrawerViewport() && typeof window.closeMobileDrawer === 'function') {
            try { window.closeMobileDrawer(); } catch (e) { /* ignore */ }
        }
        markSeen();
        try { if (typeof cfg.onEnd === 'function') cfg.onEnd(!!finished); } catch (e) { /* ignore */ }
        if (!isTouch) {
            try { if (lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true }); } catch (e) { /* ignore */ }
        }
    }

    /* ---------- first-time question ---------- */
    function closeWelcome() {
        if (welcome) {
            welcome.remove();
            welcome = null;
            document.removeEventListener('keydown', welcomeKey, true);
        }
    }
    function welcomeKey(e) {
        if (e.key === 'Escape') { e.preventDefault(); markSeen(); closeWelcome(); }
    }
    function promptIfFirstTime() {
        if (cfg.seen || welcome || active) return;
        try { if (sessionStorage.getItem('ccc_tour_seen_session') === '1') return; } catch (e) { /* ignore */ }
        var name = esc(cfg.userName);
        welcome = el('div', 'ccc-tour-welcome');
        welcome.innerHTML = '<div class="ccc-tour-wcard" role="dialog" aria-modal="true" aria-labelledby="cccWelTitle">' +
            '<div class="ccc-tour-wemoji" aria-hidden="true">👋</div>' +
            '<h3 id="cccWelTitle">Welcome' + (name ? ', ' + name : '') + '!</h3>' +
            '<p>First time in ' + esc(cfg.appName) + '? Take a quick interactive tour (about a minute) to see how everything works on your device.</p>' +
            '<p class="ccc-tour-wnote">You can replay it anytime from the <strong>❓ Tour</strong> button at the top.</p>' +
            '<div class="ccc-tour-wactions"><button type="button" class="ccc-tour-btn ccc-tour-next" id="cccWelYes">Show me around</button>' +
            '<button type="button" class="ccc-tour-btn ccc-tour-back" id="cccWelNo">Maybe later</button></div></div>';
        document.body.appendChild(welcome);
        welcome.querySelector('#cccWelYes').addEventListener('click', function () { start(0); });
        welcome.querySelector('#cccWelNo').addEventListener('click', function () { markSeen(); closeWelcome(); });
        document.addEventListener('keydown', welcomeKey, true);
        if (!isTouch) {
            try { welcome.querySelector('#cccWelYes').focus({ preventScroll: true }); } catch (e) { /* ignore */ }
        }
    }

    window.CCCTour = {
        configure: function (o) { for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) cfg[k] = o[k]; },
        start: start,
        end: end,
        promptIfFirstTime: promptIfFirstTime,
        isActive: function () { return active; }
    };
})();
