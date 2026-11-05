/*
 * MLBFD per-channel OTP delivery status + Resend (30 s cooldown per channel).
 * Uses textContent only (no innerHTML with server/user text).
 *
 *   MLBFDOtp.render(container, data.delivery, {purpose, userId, txnId, headers})
 *   MLBFDOtp.pollTelegram(userId, onUpdate)  -> stop()
 */
(function () {
    const COOLDOWN = 30;
    const LABELS = {
        sent: 'sent', dry_run: 'sent (dry-run)', pending: 'sending…',
        failed: 'failed', not_linked: 'not linked'
    };
    const COLORS = {
        sent: 'var(--color-success, #16a34a)', dry_run: 'var(--color-warning, #d97706)',
        pending: 'var(--color-info, #0284c7)', failed: 'var(--color-danger, #dc2626)',
        not_linked: 'var(--color-warning, #d97706)'
    };

    function chip(container, channel, status, opts) {
        const row = document.createElement('div');
        row.className = 'otp-channel-row';
        row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;gap:8px;' +
            'padding:6px 10px;margin:4px 0;border:1px solid var(--border-color,#e5e7eb);border-radius:8px;font-size:13px;';
        row.dataset.channel = channel;

        const label = document.createElement('span');
        const name = channel === 'email' ? 'Email' : 'Telegram';
        label.textContent = name + ': ';
        const st = document.createElement('strong');
        st.textContent = LABELS[status] || status;
        st.style.color = COLORS[status] || 'inherit';
        label.appendChild(st);
        row.appendChild(label);

        if (opts && opts.purpose && opts.allowResend !== false) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'otp-resend-btn';
            btn.style.cssText = 'min-height:36px;padding:4px 12px;border-radius:6px;cursor:pointer;' +
                'border:1px solid var(--border-color,#d1d5db);background:var(--bg-surface,#fff);color:var(--text-primary,#111);';
            row.appendChild(btn);
            startCooldown(btn, status === 'not_linked' ? 0 : COOLDOWN);
            btn.addEventListener('click', () => resend(channel, btn, st, opts));
        }
        container.appendChild(row);
    }

    function startCooldown(btn, seconds) {
        let left = seconds;
        btn.disabled = left > 0;
        const tick = () => {
            if (left <= 0) {
                btn.disabled = false;
                btn.textContent = 'Resend';
                return;
            }
            btn.textContent = 'Resend in ' + left + 's';
            left -= 1;
            btn._timer = setTimeout(tick, 1000);
        };
        clearTimeout(btn._timer);
        tick();
    }

    async function resend(channel, btn, statusEl, opts) {
        btn.disabled = true;
        btn.textContent = 'Sending…';
        const headers = Object.assign({ 'Content-Type': 'application/json' },
            typeof opts.headers === 'function' ? opts.headers() : (opts.headers || {}));
        try {
            const res = await fetch('/api/otp/resend', {
                method: 'POST', headers,
                body: JSON.stringify({ user_id: opts.userId, purpose: opts.purpose, channel, txn_id: opts.txnId || null })
            });
            let data = {};
            try { data = await res.json(); } catch (e) { data = {}; }
            const st = (data.delivery && data.delivery[channel]) || (res.ok ? 'sent' : 'failed');
            statusEl.textContent = (LABELS[st] || st) + (res.ok ? '' : ' — ' + (data.message || ('HTTP ' + res.status)));
            statusEl.style.color = COLORS[st] || 'inherit';
            startCooldown(btn, res.status === 429 || res.ok ? COOLDOWN : 0);
        } catch (e) {
            statusEl.textContent = 'network error';
            statusEl.style.color = COLORS.failed;
            startCooldown(btn, 0);
        }
    }

    function render(container, delivery, opts) {
        if (!container) return;
        container.textContent = '';
        const d = delivery || {};
        ['email', 'telegram'].forEach((ch) => {
            if (d[ch]) chip(container, ch, d[ch], opts || {});
        });
        container.style.display = Object.keys(d).length ? 'block' : 'none';
    }

    function pollTelegram(userId, onUpdate, intervalMs) {
        let stopped = false;
        const started = Date.now();
        async function once() {
            if (stopped) return;
            try {
                const res = await fetch('/api/telegram/status?user_id=' + encodeURIComponent(userId));
                const data = await res.json();
                onUpdate(data);
                if (data.telegram_verified) { stopped = true; return; }
            } catch (e) { /* keep polling */ }
            if (Date.now() - started > 10 * 60 * 1000) { stopped = true; onUpdate({ timeout: true }); return; }
            setTimeout(once, intervalMs || 3000);
        }
        once();
        return { stop: () => { stopped = true; } };
    }

    window.MLBFDOtp = { render, pollTelegram, COOLDOWN };
})();
