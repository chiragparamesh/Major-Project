// Escape any server/user-supplied text before it goes into innerHTML.
function esc(value) {
    return String(value === undefined || value === null ? '' : value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// MLBFD — User Portal Core Logic
// Handles all SPA tab switching, API calls, form flows, and UI state management.

// ─────────────────────────────────────────────────────────────
// GLOBAL STATE
// ─────────────────────────────────────────────────────────────
let userToken = localStorage.getItem('mlbfd_token') || localStorage.getItem('token');
let userId = localStorage.getItem('mlbfd_user_id');
if (userToken && !localStorage.getItem('mlbfd_token')) {
    localStorage.setItem('mlbfd_token', userToken);
}
let currentCoords = { lat: 12.9716, lon: 77.5946, accuracy_m: 50, source: 'gps', area_name: 'Bengaluru' };
let activeTxnId = null;
let riskPreviewTimeout = null;
let enteredPin = '';
let pinActionContext = ''; // 'TRANSFER' or 'CHECK_BALANCE'
let pendingTransferPayload = null;

// ─────────────────────────────────────────────────────────────
// TOAST NOTIFICATION SYSTEM
// ─────────────────────────────────────────────────────────────
function showToast(message, type = 'info', duration = 4000) {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    const iconMap = {
        success: 'fa-circle-check',
        error: 'fa-circle-exclamation',
        warning: 'fa-triangle-exclamation',
        info: 'fa-circle-info'
    };

    toast.innerHTML = `
        <i class="fa-solid ${iconMap[type] || iconMap.info}"></i>
        <span>${message}</span>
        <button class="toast-close" onclick="this.parentElement.remove()">
            <i class="fa-solid fa-xmark"></i>
        </button>
    `;

    container.appendChild(toast);

    // Animate in
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            toast.classList.add('toast-visible');
        });
    });

    // Auto-dismiss
    const timer = setTimeout(() => {
        toast.classList.remove('toast-visible');
        setTimeout(() => toast.remove(), 350);
    }, duration);

    toast.querySelector('.toast-close').addEventListener('click', () => clearTimeout(timer));
}

// Custom confirm dialog (replaces native confirm())
function showConfirm(message, onConfirm) {
    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';
    overlay.innerHTML = `
        <div class="confirm-card">
            <div class="confirm-icon"><i class="fa-solid fa-triangle-exclamation"></i></div>
            <p class="confirm-message">${message}</p>
            <div class="confirm-actions">
                <button class="btn btn-secondary confirm-cancel">Cancel</button>
                <button class="btn btn-danger confirm-ok">Confirm</button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);
    requestAnimationFrame(() => requestAnimationFrame(() => overlay.classList.add('confirm-visible')));

    const cleanup = () => {
        overlay.classList.remove('confirm-visible');
        setTimeout(() => overlay.remove(), 300);
    };

    overlay.querySelector('.confirm-cancel').addEventListener('click', cleanup);
    overlay.querySelector('.confirm-ok').addEventListener('click', () => {
        cleanup();
        onConfirm();
    });
    overlay.addEventListener('click', (e) => { if (e.target === overlay) cleanup(); });
}

// ─────────────────────────────────────────────────────────────
// AUTH GUARD — defined before use
// ─────────────────────────────────────────────────────────────
function handleLogout() {
    localStorage.removeItem('mlbfd_token');
    localStorage.removeItem('mlbfd_user_id');
    localStorage.removeItem('mlbfd_refresh_token');
    localStorage.removeItem('mlbfd_upi_id');
    localStorage.removeItem('token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user_upi');
    window.location.href = '/user/login';
}

// Guard: redirect to login if not authenticated
if (!userToken || !userId) {
    handleLogout();
}

// ─────────────────────────────────────────────────────────────
// AUTH-AWARE FETCH
// Flask-JWT-Extended answers a missing token with 401, an EXPIRED token
// with 401 and a MALFORMED token with 422. Only 401 was handled before, so a
// stale token left the dashboard rendered but every API call dead. Refresh
// once with the stored refresh token, then fall back to a clean re-login.
// ─────────────────────────────────────────────────────────────
const _rawFetch = window.fetch.bind(window);
let _refreshInFlight = null;

function refreshAccessToken() {
    const rt = localStorage.getItem('mlbfd_refresh_token');
    if (!rt) return Promise.resolve(null);
    if (!_refreshInFlight) {
        _refreshInFlight = _rawFetch('/api/refresh', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${rt}` }
        }).then(async (r) => {
            if (!r.ok) return null;
            const data = await r.json().catch(() => ({}));
            if (data && data.access_token) {
                localStorage.setItem('mlbfd_token', data.access_token);
                userToken = data.access_token;
                return data.access_token;
            }
            return null;
        }).catch(() => null).finally(() => { _refreshInFlight = null; });
    }
    return _refreshInFlight;
}

window.fetch = async function (input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    const res = await _rawFetch(input, init);
    const isApi = url.indexOf('/api/') === 0;
    if (!isApi || url.indexOf('/api/refresh') === 0 || url.indexOf('/api/login') === 0) {
        return res;
    }
    if (res.status !== 401 && res.status !== 422) return res;

    const fresh = await refreshAccessToken();
    if (!fresh) {
        handleLogout();
        return res;
    }
    const retryInit = Object.assign({}, init || {});
    retryInit.headers = Object.assign({}, (init && init.headers) || {}, {
        'Authorization': `Bearer ${fresh}`
    });
    return _rawFetch(input, retryInit);
};

// ─────────────────────────────────────────────────────────────
// PAGE INIT
// ─────────────────────────────────────────────────────────────
window.onload = function () {
    // Null guard on userId
    if (!userId) {
        handleLogout();
        return;
    }

    // Set header display names
    const namePart = userId.includes('@') ? userId.split('@')[0] : userId;
    document.getElementById('header-user-id').innerText = namePart;
    document.getElementById('profile-user-id').innerText = userId;
    document.getElementById('user-initials').innerText = namePart.charAt(0).toUpperCase();

    // Theme: restore saved preference
    const savedTheme = localStorage.getItem('mlbfd_theme');
    if (savedTheme === 'light') {
        document.body.classList.add('light-theme');
        const icon = document.querySelector('#theme-btn i');
        if (icon) icon.className = 'fa-solid fa-sun';
    }

    // Theme toggle handler
    const themeBtn = document.getElementById('theme-btn');
    if (themeBtn) {
        themeBtn.addEventListener('click', () => {
            document.body.classList.toggle('light-theme');
            const icon = themeBtn.querySelector('i');
            const isLight = document.body.classList.contains('light-theme');
            icon.className = isLight ? 'fa-solid fa-sun' : 'fa-solid fa-moon';
            localStorage.setItem('mlbfd_theme', isLight ? 'light' : 'dark');
        });
    }

    // Location for the transaction (Part 16): native GPS inside the Android app, browser GPS elsewhere.
    detectLocation(false);
    const scanBtn = document.getElementById('btn-scan-qr');
    if (scanBtn && IN_APP) scanBtn.style.display = 'flex';

    refreshDashboardData();
    setInterval(refreshDashboardData, 15000);
};

// ─────────────────────────────────────────────────────────────
// TAB SWITCHING (SPA)
// ─────────────────────────────────────────────────────────────
function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
    document.querySelectorAll('.menu-item').forEach(item => item.classList.remove('active'));

    const tabEl = document.getElementById(`tab-${tabId}`);
    const menuEl = document.getElementById(`menu-${tabId}`);
    if (tabEl) tabEl.style.display = 'block';
    if (menuEl) menuEl.classList.add('active');

    // Tab-specific data loading
    if (tabId === 'overview') refreshDashboardData();
    else if (tabId === 'history') loadHistoryFeed();
    else if (tabId === 'trusted') loadTrustedPayees();
    else if (tabId === 'settings') loadUserSettings();
    else if (tabId === 'receive') {
        const myUpiInput = document.getElementById('receive-my-upi');
        if (myUpiInput) myUpiInput.value = userId;
        generateReceiveQr();
    }
}

// ─────────────────────────────────────────────────────────────
// DASHBOARD DATA — BALANCE + RECENT TRANSACTIONS
// ─────────────────────────────────────────────────────────────
async function refreshDashboardData() {
    try {
        const balanceRes = await fetch(`/api/balance/${userId}`, {
            headers: { 'Authorization': `Bearer ${userToken}` }
        });

        if (balanceRes.status === 401) {
            handleLogout();
            return;
        }

        const balanceData = await balanceRes.json();
        if (balanceData.success) {
            const balStr = '₹' + balanceData.balance.toLocaleString('en-IN', { minimumFractionDigits: 2 });
            const balEl = document.getElementById('overview-balance');
            if (balEl && balEl.innerText === '••••••') {
                // Keep masked — only update if already revealed
            } else if (balEl) {
                balEl.innerText = balStr;
            }
        }

        const txnRes = await fetch(`/api/transactions/${userId}`, {
            headers: { 'Authorization': `Bearer ${userToken}` }
        });
        const txnData = await txnRes.json();

        if (txnData.success) {
            const countEl = document.getElementById('overview-txns-count');
            if (countEl) countEl.innerText = txnData.transactions.length;
            displayOverviewTransactions(txnData.transactions.slice(0, 5));
        }
    } catch (err) {
        console.error('Dashboard load error:', err);
    }
}

// ─────────────────────────────────────────────────────────────
// OVERVIEW TABLE
// ─────────────────────────────────────────────────────────────
function displayOverviewTransactions(txns) {
    const tbody = document.getElementById('overview-txns-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (!txns || txns.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="table-empty">No transactions recorded yet.</td></tr>`;
        return;
    }

    txns.forEach(t => {
        const statusClass = getStatusClass(t.status);
        const direction = t.sender_upi === userId ? 'SENT' : 'RECEIVED';
        const displayParty = direction === 'SENT' ? t.receiver_upi : t.sender_upi;
        const displayAmt = (direction === 'SENT' ? '− ₹' : '+ ₹') + t.amount.toLocaleString('en-IN', { minimumFractionDigits: 2 });
        const amtClass = direction === 'SENT' ? 'amt-debit' : 'amt-credit';
        const partyLabel = displayParty.length > 20 ? displayParty.slice(0, 20) + '…' : displayParty;

        const row = document.createElement('tr');
        row.innerHTML = `
            <td>
                <div class="party-cell">
                    <i class="fa-solid ${direction === 'SENT' ? 'fa-arrow-up-right text-danger' : 'fa-arrow-down-left text-success'}"></i>
                    <strong title="${displayParty}">${partyLabel}</strong>
                </div>
            </td>
            <td class="${amtClass}">${displayAmt}</td>
            <td>${renderRiskBar(t.risk_score)}</td>
            <td><span class="verdict-tag ${statusClass}">${formatStatus(t.status)}</span></td>
            <td class="text-muted">${formatDate(t.created_at)}</td>
        `;
        tbody.appendChild(row);
    });
}

// ─────────────────────────────────────────────────────────────
// TRANSACTION HISTORY
// ─────────────────────────────────────────────────────────────
async function loadHistoryFeed() {
    const tbody = document.getElementById('history-table-body');
    if (tbody) tbody.innerHTML = `<tr><td colspan="8" class="table-empty table-loading"><span class="skeleton-line"></span></td></tr>`;

    try {
        const res = await fetch(`/api/transactions/${userId}`, {
            headers: { 'Authorization': `Bearer ${userToken}` }
        });
        const data = await res.json();
        if (data.success) {
            window.allTransactions = data.transactions;
            displayHistoryTable(data.transactions);
        }
    } catch (err) {
        console.error('Failed to load history:', err);
        if (tbody) tbody.innerHTML = `<tr><td colspan="8" class="table-empty text-danger">Failed to load transactions. Check connection.</td></tr>`;
    }
}

function displayHistoryTable(txns) {
    const tbody = document.getElementById('history-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (!txns || txns.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="table-empty">No records found for the selected filter.</td></tr>`;
        return;
    }

    txns.forEach(t => {
        const statusClass = getStatusClass(t.status);
        const direction = t.sender_upi === userId ? 'SENT' : 'RECEIVED';
        const displayAmt = (direction === 'SENT' ? '− ₹' : '+ ₹') + t.amount.toLocaleString('en-IN', { minimumFractionDigits: 2 });
        const amtClass = direction === 'SENT' ? 'amt-debit' : 'amt-credit';

        const row = document.createElement('tr');
        row.innerHTML = `
            <td><strong class="txn-id-text">${esc(t.txn_id)}</strong></td>
            <td title="${esc(t.sender_upi)}">${truncate(t.sender_upi, 18)}</td>
            <td title="${esc(t.receiver_upi)}">${truncate(t.receiver_upi, 18)}</td>
            <td class="${amtClass}">${displayAmt}</td>
            <td><strong>${t.risk_score.toFixed(1)}%</strong></td>
            <td><span class="verdict-tag ${statusClass}">${formatStatus(t.status)}</span></td>
            <td class="text-muted">${new Date(t.created_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })}</td>
            <td>
                <button class="btn btn-sm btn-secondary" onclick="openFeedbackDrawer('${esc(t.txn_id)}')">
                    <i class="fa-solid fa-flag"></i> Report
                </button>
            </td>
        `;

        const drawerRow = document.createElement('tr');
        drawerRow.id = `feedback-drawer-${esc(t.txn_id)}`;
        drawerRow.style.display = 'none';
        drawerRow.innerHTML = `
            <td colspan="8" class="feedback-drawer-cell">
                <div class="feedback-drawer">
                    <h4>Submit Feedback for this Transaction</h4>
                    <p>Help retrain our models by flagging whether this was actually fraudulent or a false positive.</p>
                    <div class="feedback-options">
                        <label class="radio-label">
                            <input type="radio" name="fb-${esc(t.txn_id)}" id="fb-fraud-${esc(t.txn_id)}" value="true" ${t.is_fraud ? 'checked' : ''}>
                            <span class="radio-dot"></span>
                            <span>Confirmed Fraud</span>
                        </label>
                        <label class="radio-label">
                            <input type="radio" name="fb-${esc(t.txn_id)}" id="fb-safe-${esc(t.txn_id)}" value="false" ${!t.is_fraud ? 'checked' : ''}>
                            <span class="radio-dot"></span>
                            <span>Safe / False Alarm</span>
                        </label>
                    </div>
                    <input type="text" id="fb-text-${esc(t.txn_id)}" placeholder="Additional details (optional)..." class="feedback-text-input">
                    <div class="feedback-btns">
                        <button class="btn btn-primary btn-sm" onclick="submitFeedback('${esc(t.txn_id)}', ${t.risk_score})">
                            <i class="fa-solid fa-paper-plane"></i> Submit Feedback
                        </button>
                        <button class="btn btn-secondary btn-sm" onclick="closeFeedbackDrawer('${esc(t.txn_id)}')">Cancel</button>
                    </div>
                </div>
            </td>
        `;

        tbody.appendChild(row);
        tbody.appendChild(drawerRow);
    });
}

function openFeedbackDrawer(txnId) {
    document.querySelectorAll('[id^="feedback-drawer-"]').forEach(d => d.style.display = 'none');
    const drawer = document.getElementById(`feedback-drawer-${txnId}`);
    if (drawer) drawer.style.display = 'table-row';
}

function closeFeedbackDrawer(txnId) {
    const drawer = document.getElementById(`feedback-drawer-${txnId}`);
    if (drawer) drawer.style.display = 'none';
}

async function submitFeedback(txnId, riskScore) {
    const isFraudRadio = document.getElementById(`fb-fraud-${txnId}`);
    const isFraud = isFraudRadio ? isFraudRadio.checked : false;
    const textEl = document.getElementById(`fb-text-${txnId}`);
    const text = textEl ? textEl.value.trim() : '';
    const predictedFraud = riskScore >= 60.0;

    try {
        const res = await fetch('/api/feedback', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${userToken}`
            },
            body: JSON.stringify({ txn_id: txnId, is_fraud: isFraud, predicted_fraud: predictedFraud, feedback_text: text })
        });
        const data = await res.json();
        if (data.success) {
            showToast('Feedback submitted. Thank you for helping improve detection accuracy!', 'success');
            closeFeedbackDrawer(txnId);
        } else {
            showToast('Feedback error: ' + data.message, 'error');
        }
    } catch (err) {
        showToast('Network error submitting feedback.', 'error');
    }
}

function filterHistoryTable() {
    const filterValue = document.getElementById('history-filter')?.value;
    if (!window.allTransactions) return;

    let filtered = window.allTransactions;
    if (filterValue === 'SENT') filtered = filtered.filter(t => t.sender_upi === userId);
    else if (filterValue === 'RECEIVED') filtered = filtered.filter(t => t.receiver_upi === userId);
    else if (filterValue === 'BLOCKED') filtered = filtered.filter(t => t.status === 'BLOCKED');

    displayHistoryTable(filtered);
}

// ─────────────────────────────────────────────────────────────
// SEND MONEY — RISK PREVIEW (DEBOUNCED)
// ─────────────────────────────────────────────────────────────
function toggleQrField() {
    const isChecked = document.getElementById('txn-qr-simulate')?.checked;
    const qrGroup = document.getElementById('qr-input-group');
    if (qrGroup) qrGroup.style.display = isChecked ? 'flex' : 'none';
    if (!isChecked) {
        const qrInput = document.getElementById('txn-qr-code');
        if (qrInput) qrInput.value = '';
    }
    triggerRiskPreview();
}

let payeeLookupTimeout = null;

function handlePayeeLookupDebounced() {
    clearTimeout(payeeLookupTimeout);
    payeeLookupTimeout = setTimeout(performPayeeLookup, 350);
}

async function performPayeeLookup() {
    const receiverInput = document.getElementById('txn-receiver');
    const lookupCard = document.getElementById('payee-lookup-card');
    const lookupError = document.getElementById('payee-lookup-error');
    const lookupErrorMsg = document.getElementById('payee-lookup-error-msg');
    const cardName = document.getElementById('payee-card-name');
    const cardUpi = document.getElementById('payee-card-upi');

    if (!receiverInput) return;
    const q = receiverInput.value.trim();

    if (!q || q.length < 3) {
        if (lookupCard) lookupCard.style.display = 'none';
        if (lookupError) lookupError.style.display = 'none';
        resetRiskPreviewUI();
        return;
    }

    try {
        const token = localStorage.getItem('mlbfd_token') || userToken;
        const res = await fetch(`/api/lookup_payee?q=${encodeURIComponent(q)}`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        const data = await res.json();
        if (res.ok && data.success && data.registered) {
            if (lookupError) lookupError.style.display = 'none';
            if (lookupCard) {
                if (cardName) cardName.innerText = data.masked_name;
                if (cardUpi) cardUpi.innerText = data.masked_upi;
                lookupCard.style.display = 'block';
            }
            triggerRiskPreview();
        } else {
            if (lookupCard) lookupCard.style.display = 'none';
            if (lookupError) {
                if (lookupErrorMsg) lookupErrorMsg.innerText = data.message || "This user is not registered on MLBFD";
                lookupError.style.display = 'flex';
            }
            resetRiskPreviewUI();
        }
    } catch (e) {
        console.error("Payee lookup error:", e);
    }
}

function triggerRiskPreviewDebounced() {
    clearTimeout(riskPreviewTimeout);
    riskPreviewTimeout = setTimeout(triggerRiskPreview, 350);
}

async function triggerRiskPreview() {
    const receiverInput = document.getElementById('txn-receiver');
    const amountInput = document.getElementById('txn-amount');
    if (!receiverInput || !amountInput) return;

    const receiver_upi = receiverInput.value.trim();
    const amountVal = parseFloat(amountInput.value);

    if (!receiver_upi || isNaN(amountVal) || amountVal <= 0) {
        resetRiskPreviewUI();
        return;
    }

    const qrCheck = document.getElementById('txn-qr-simulate')?.checked;
    const qrInput = document.getElementById('txn-qr-code');

    const payload = {
        receiver_upi,
        sender_upi: userId,
        amount: amountVal,
        mcc_code: '0000',
        biometric_failed: false,
        qr_code: qrCheck ? (qrInput?.value.trim() || '') : '',
        latitude: currentCoords.lat,
        longitude: currentCoords.lon,
        device_id: (typeof localStorage !== 'undefined' && localStorage.getItem('mlbfd_device_id')) || 'web_browser_device'
    };

    try {
        const res = await fetch('/api/predict-secure', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${userToken}`
            },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!data.success === false) updateRiskPreviewUI(data);
    } catch (err) {
        // Silent fail for preview — not critical
    }
}

function resetRiskPreviewUI() {
    const verdictEl = document.getElementById('risk-gauge-verdict');
    const percentEl = document.getElementById('risk-gauge-percent');
    const fillEl = document.getElementById('risk-gauge-fill');
    const listEl = document.getElementById('risk-warnings-list');

    if (verdictEl) { verdictEl.innerText = 'SAFE'; verdictEl.style.color = 'var(--color-success)'; }
    if (percentEl) percentEl.innerText = '0.0%';
    if (fillEl) { fillEl.style.width = '0%'; fillEl.style.backgroundColor = 'var(--color-success)'; }
    if (listEl) listEl.innerHTML = `<li class="safe-marker"><i class="fa-solid fa-circle-check"></i> Standard parameters. Ready to pay.</li>`;
    const reasonTextEl = document.getElementById('plain-language-reason-text');
    if (reasonTextEl) reasonTextEl.innerText = "Standard parameters. Ready to pay.";

    for (let i = 1; i <= 7; i++) {
        const scoreEl = document.getElementById(`layer-score-${i}`);
        const fillEl2 = document.getElementById(`layer-fill-${i}`);
        if (scoreEl) scoreEl.innerText = '0%';
        if (fillEl2) fillEl2.style.width = '0%';
    }
}

function updateRiskPreviewUI(data) {
    const verdictSpan = document.getElementById('risk-gauge-verdict');
    const percentH4 = document.getElementById('risk-gauge-percent');
    const fillBar = document.getElementById('risk-gauge-fill');

    const colorMap = {
        'APPROVED': 'var(--color-success)',
        'COMPLETED': 'var(--color-success)',
        'APPROVED_WITH_WARNING': 'var(--color-warning)',
        'REQUIRES_2FA': 'var(--color-info)',
        'PENDING': 'var(--color-warning)',
        'CANCELLED': 'var(--text-muted)',
        'BLOCKED': 'var(--color-danger)'
    };
    const labelMap = {
        'APPROVED': 'SAFE',
        'COMPLETED': 'COMPLETED',
        'APPROVED_WITH_WARNING': 'CAUTION',
        'REQUIRES_2FA': 'REQUIRES 2FA',
        'PENDING': 'PENDING 2FA',
        'CANCELLED': 'CANCELLED',
        'BLOCKED': 'HIGH RISK'
    };

    const color = colorMap[data.status] || 'var(--color-success)';
    const label = labelMap[data.status] || 'SAFE';

    if (verdictSpan) { verdictSpan.innerText = label; verdictSpan.style.color = color; }
    if (percentH4) percentH4.innerText = `${data.risk_score.toFixed(1)}%`;
    if (fillBar) { fillBar.style.width = `${data.risk_score}%`; fillBar.style.backgroundColor = color; }

    const list = document.getElementById('risk-warnings-list');
    if (list) {
        list.innerHTML = '';
        if (!data.flags || data.flags.length === 0) {
            list.innerHTML = `<li class="safe-marker"><i class="fa-solid fa-circle-check"></i> No alerts flagged. Secure score.</li>`;
        } else {
            data.flags.forEach(f => {
                const li = document.createElement('li');
                li.className = data.status === 'BLOCKED' ? 'danger-marker' : 'warn-marker';
                li.innerHTML = `<i class="fa-solid ${data.status === 'BLOCKED' ? 'fa-ban' : 'fa-triangle-exclamation'}"></i> ${esc(f)}`;
                list.appendChild(li);
            });
        }
    }

    const reasonTextEl = document.getElementById('plain-language-reason-text');
    if (reasonTextEl) {
        reasonTextEl.innerText = data.plain_language_reason || (data.top_reasons && data.top_reasons.length > 0 ? data.top_reasons.join('; ') : 'Standard account baseline profile.');
    }

    // Layer scores: API returns values already in 0-100 range (not 0-1)
    const layers = data.layers || {};
    const keyMap = ['behavioral', 'velocity', 'flow', 'payee', 'compromise', 'amount', 'website_trust'];

    for (let i = 1; i <= 7; i++) {
        const key = keyMap[i - 1];
        const raw = layers[key] || 0;
        // Values come as 0-100 from the API
        const scoreVal = raw;
        const scoreEl = document.getElementById(`layer-score-${i}`);
        const fillEl = document.getElementById(`layer-fill-${i}`);
        if (scoreEl) scoreEl.innerText = `${scoreVal.toFixed(0)}%`;
        if (fillEl) {
            fillEl.style.width = `${Math.min(scoreVal, 100)}%`;
            fillEl.style.backgroundColor = scoreVal > 70 ? 'var(--color-danger)' : scoreVal > 40 ? 'var(--color-warning)' : 'var(--color-brand)';
        }
    }
}

// ─────────────────────────────────────────────────────────────
// EXECUTE TRANSFER (opens UPI PIN modal)
// ─────────────────────────────────────────────────────────────
async function executeTransfer(e) {
    e.preventDefault();

    const receiverInput = document.getElementById('txn-receiver');
    const amountInput = document.getElementById('txn-amount');
    if (!receiverInput || !amountInput) return;

    const receiver_upi = receiverInput.value.trim();
    const amount = parseFloat(amountInput.value);

    if (!receiver_upi || isNaN(amount) || amount <= 0) return;

    // Pre-flight balance check
    try {
        const balRes = await fetch(`/api/balance/${userId}`, {
            headers: { 'Authorization': `Bearer ${userToken}` }
        });
        const balData = await balRes.json();
        if (balData.success && parseFloat(balData.balance) < amount) {
            showToast('Insufficient virtual balance for this transfer.', 'error');
            return;
        }
    } catch {
        // Non-critical — proceed anyway
    }

    const qrCheck = document.getElementById('txn-qr-simulate')?.checked;
    const qrInput = document.getElementById('txn-qr-code');

    pendingTransferPayload = {
        receiver: receiver_upi,
        receiver_upi,
        sender_upi: userId,
        amount,
        mcc_code: '0000',
        biometric_failed: false,
        qr_code: qrCheck ? (qrInput?.value.trim() || '') : '',
        latitude: currentCoords.lat,
        longitude: currentCoords.lon,
        accuracy_m: currentCoords.accuracy_m,
        source: currentCoords.source,
        device_id: (typeof localStorage !== 'undefined' && localStorage.getItem('mlbfd_device_id')) || 'web_browser_device'
    };

    enteredPin = '';
    pinActionContext = 'TRANSFER';
    updatePinDots();

    const receiverDisplay = document.getElementById('upi-pin-receiver-display');
    const amountDisplay = document.getElementById('upi-pin-amount-display');
    if (receiverDisplay) receiverDisplay.innerText = receiver_upi;
    if (amountDisplay) amountDisplay.innerText = '₹' + amount.toLocaleString('en-IN', { minimumFractionDigits: 2 });

    const txDetails = document.getElementById('upi-pin-tx-details');
    if (txDetails) txDetails.style.display = 'grid';

    const pinModal = document.getElementById('upi-pin-modal');
    if (pinModal) pinModal.style.display = 'flex';
}

async function submitTransferWithPin(pin) {
    if (!pendingTransferPayload) return;
    pendingTransferPayload.pin = pin;
    pendingTransferPayload.payment_pin = pin;

    try {
        const res = await fetch('/api/transfer', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${userToken}`
            },
            body: JSON.stringify(pendingTransferPayload)
        });

        // Handle HTTP-level errors properly
        if (!res.ok && res.status !== 200) {
            let errMsg = 'Transfer failed.';
            try {
                const errData = await res.json();
                errMsg = errData.message || errMsg;
            } catch {}
            showToast(errMsg, 'error');
            closeUpiPinModal();
            return;
        }

        const data = await res.json();

        if (data.success === false) {
            showToast('Transfer blocked: ' + data.message, 'error');
            closeUpiPinModal();
            return;
        }

        closeUpiPinModal();

        if (data.status === 'REQUIRES_2FA') {
            activeTxnId = data.txn_id;
            const emailInput = document.getElementById('otp-email-input');
            const telegramInput = document.getElementById('otp-telegram-input');
            const otpError = document.getElementById('otp-error');
            if (emailInput) emailInput.value = '';
            if (telegramInput) telegramInput.value = '';
            if (otpError) otpError.style.display = 'none';
            const otpModal = document.getElementById('otp-modal');
            if (otpModal) otpModal.style.display = 'flex';
            if (window.MLBFDOtp) {
                MLBFDOtp.render(document.getElementById('txn-delivery'), data.delivery, {
                    purpose: 'TRANSACTION', txnId: data.txn_id,
                    headers: () => ({ 'Authorization': `Bearer ${localStorage.getItem('mlbfd_token')}` })
                });
            }
        } else {
            showResultCard(data);
        }
    } catch (err) {
        console.error('Transfer network error:', err);
        showToast('Transaction failed due to a network error. Please try again.', 'error');
        closeUpiPinModal();
    }
}

function showResultCard(data) {
    const modal = document.getElementById('result-modal');
    const icon = document.getElementById('result-modal-icon');
    const title = document.getElementById('result-modal-title');
    const message = document.getElementById('result-modal-message');
    const scoreVal = document.getElementById('result-breakdown-score');
    const fillBar = document.getElementById('result-breakdown-fill');
    const reasonsList = document.getElementById('result-breakdown-reasons-list');
    if (!modal) return;

    if (reasonsList) reasonsList.innerHTML = '';

    if (data.status === 'BLOCKED') {
        if (icon) icon.className = 'fa-solid fa-shield-xmark modal-icon text-danger';
        if (title) { title.innerText = 'Transaction Blocked'; title.className = 'text-danger'; }
        if (message) message.innerText = 'The 7-layer ML engine flagged this payment as high-probability fraud and blocked it.';
        if (fillBar) fillBar.style.backgroundColor = 'var(--color-danger)';
    } else {
        if (icon) icon.className = 'fa-solid fa-circle-check modal-icon text-success';
        const isWarning = data.status === 'APPROVED_WITH_WARNING';
        if (title) {
            title.innerText = isWarning ? 'Transfer Sent with Warnings' : 'Transfer Successful';
            title.className = isWarning ? 'text-warning' : 'text-success';
        }
        if (message) message.innerText = 'Your payment was authorized and virtual balances have been updated.';
        if (fillBar) fillBar.style.backgroundColor = isWarning ? 'var(--color-warning)' : 'var(--color-success)';
    }

    if (scoreVal) scoreVal.innerText = `${(data.risk_score || 0).toFixed(1)}%`;
    if (fillBar) fillBar.style.width = `${data.risk_score || 0}%`;

    const flags = data.flags || [];
    if (reasonsList) {
        if (flags.length === 0) {
            reasonsList.innerHTML = `<li>Safe behavioral patterns. Standard verification limits applied.</li>`;
        } else {
            flags.forEach(f => { reasonsList.innerHTML += `<li>${esc(f)}</li>`; });
        }
    }

    modal.style.display = 'flex';

    // Clear send form
    const txnReceiver = document.getElementById('txn-receiver');
    const txnAmount = document.getElementById('txn-amount');
    const txnQrSim = document.getElementById('txn-qr-simulate');
    const txnQrCode = document.getElementById('txn-qr-code');
    const qrGroup = document.getElementById('qr-input-group');
    if (txnReceiver) txnReceiver.value = '';
    if (txnAmount) txnAmount.value = '';
    if (txnQrSim) txnQrSim.checked = false;
    if (txnQrCode) txnQrCode.value = '';
    if (qrGroup) qrGroup.style.display = 'none';
    resetRiskPreviewUI();
    refreshDashboardData();
}

function closeResultModal() {
    const modal = document.getElementById('result-modal');
    if (modal) modal.style.display = 'none';
}

function closeOtpModal() {
    const modal = document.getElementById('otp-modal');
    if (modal) modal.style.display = 'none';
    activeTxnId = null;
    refreshDashboardData();
}

// ─────────────────────────────────────────────────────────────
// OTP VERIFICATION
// ─────────────────────────────────────────────────────────────
async function verifyOtpPayment(e) {
    e.preventDefault();
    const emailInput = document.getElementById('otp-email-input');
    const telegramInput = document.getElementById('otp-telegram-input');
    const errorDiv = document.getElementById('otp-error');
    const submitBtn = document.getElementById('otp-submit-btn');

    if (errorDiv) errorDiv.style.display = 'none';
    const email_code = emailInput ? emailInput.value.trim() : '';
    const telegram_code = telegramInput ? telegramInput.value.trim() : '';

    if (!email_code || email_code.length !== 6 || !telegram_code || telegram_code.length !== 6 || !activeTxnId) {
        if (errorDiv) errorDiv.style.display = 'flex';
        const errMsg = document.getElementById('otp-error-msg');
        if (errMsg) errMsg.innerText = 'Please enter valid 6-digit codes for both Email and Telegram.';
        return;
    }

    if (submitBtn) { submitBtn.disabled = true; submitBtn.innerText = 'Verifying...'; }

    try {
        const res = await fetch('/api/otp/verify', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${userToken}`
            },
            body: JSON.stringify({ txn_id: activeTxnId, email_code, telegram_code })
        });
        const data = await res.json();

        if (data.success) {
            closeOtpModal();
            showResultCard({
                status: 'COMPLETED',
                risk_score: 65.0,
                flags: ['Transaction authenticated via Dual-Channel 2FA (Email + Telegram verified).']
            });
        } else {
            if (errorDiv) errorDiv.style.display = 'flex';
            const errMsg = document.getElementById('otp-error-msg');
            if (errMsg) errMsg.innerText = data.message || 'Invalid or expired security code.';
            if (submitBtn) { submitBtn.disabled = false; submitBtn.innerText = 'Verify & Complete Transfer'; }

            if (data.account_frozen) {
                showToast('SECURITY LOCKOUT: Account frozen due to multiple security failures.', 'error');
                setTimeout(() => { handleLogout(); }, 3500);
            }
        }
    } catch (err) {
        if (errorDiv) errorDiv.style.display = 'flex';
        const errMsg = document.getElementById('otp-error-msg');
        if (errMsg) errMsg.innerText = 'Network failure. Please retry.';
        if (submitBtn) { submitBtn.disabled = false; submitBtn.innerText = 'Verify & Complete Transfer'; }
    }
}

// ─────────────────────────────────────────────────────────────
// TRUSTED PAYEES
// ─────────────────────────────────────────────────────────────
async function loadTrustedPayees() {
    try {
        const res = await fetch(`/api/trusted-payees/${userId}`, {
            headers: { 'Authorization': `Bearer ${userToken}` }
        });
        const data = await res.json();
        if (data.success) displayTrustedPayees(data.trusted_payees);
    } catch (err) {
        console.error('Payee load failed:', err);
    }
}

function displayTrustedPayees(payees) {
    const tbody = document.getElementById('trusted-payees-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (!payees || payees.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="table-empty">No trusted payees added yet.</td></tr>`;
        return;
    }

    payees.forEach(p => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td><strong>${esc(p.nickname || '—')}</strong></td>
            <td><code>${esc(p.payee_upi)}</code></td>
            <td>${p.txn_count}</td>
            <td>₹${p.total_amount.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</td>
            <td>
                <button class="btn btn-sm btn-danger-outline" onclick="deleteTrustedPayee(${p.id})">
                    <i class="fa-solid fa-trash-can"></i> Remove
                </button>
            </td>
        `;
        tbody.appendChild(row);
    });
}

async function addTrustedPayee(e) {
    e.preventDefault();
    const upiInput = document.getElementById('payee-upi');
    const nickInput = document.getElementById('payee-nickname');
    if (!upiInput || !nickInput) return;

    const payee_upi = upiInput.value.trim();
    const nickname = nickInput.value.trim();
    if (!payee_upi || !nickname) return;

    try {
        const res = await fetch('/api/trusted-payees/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${userToken}` },
            body: JSON.stringify({ payee_upi, nickname })
        });
        const data = await res.json();
        if (data.success) {
            upiInput.value = '';
            nickInput.value = '';
            showToast(`${nickname} added to trusted payees.`, 'success');
            loadTrustedPayees();
        } else {
            showToast('Failed to add payee: ' + data.message, 'error');
        }
    } catch {
        showToast('Network error. Please try again.', 'error');
    }
}

function deleteTrustedPayee(id) {
    showConfirm('Remove this payee from your trusted whitelist?', async () => {
        try {
            const res = await fetch(`/api/trusted-payees/${id}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${userToken}` }
            });
            const data = await res.json();
            if (data.success) {
                showToast('Payee removed from trusted list.', 'success');
                loadTrustedPayees();
            } else {
                showToast('Error: ' + data.message, 'error');
            }
        } catch {
            showToast('Network error removing payee.', 'error');
        }
    });
}

// ─────────────────────────────────────────────────────────────
// SAFETY CENTER
// ─────────────────────────────────────────────────────────────
async function checkDomainReputation(e) {
    e.preventDefault();
    const domainInput = document.getElementById('safety-domain');
    if (!domainInput) return;
    const domain = domainInput.value.trim().replace(/^https?:\/\//i, '').split('/')[0];
    if (!domain) return;

    try {
        // encode: free text such as "my name" must not break the URL path
        const res = await fetch(`/api/website-check/${encodeURIComponent(domain)}`, {
            headers: { 'Authorization': `Bearer ${userToken}` }
        });
        const data = await res.json();
        if (data.success) displayDomainResult(data);
        else showToast('Error checking website: ' + data.message, 'error');
    } catch {
        showToast('Failed to connect to safety checker.', 'error');
    }
}

function displayDomainResult(data) {
    const card = document.getElementById('domain-result');
    const nameEl = document.getElementById('result-domain-name');
    const verdictEl = document.getElementById('result-domain-verdict');
    const scoreFill = document.getElementById('result-domain-score-fill');
    const scoreEl = document.getElementById('result-domain-score');
    const reasonsList = document.getElementById('result-domain-reasons');
    if (!card) return;

    if (nameEl) nameEl.innerText = data.domain;
    // Verdicts from the API: TRUSTED, SAFE, CAUTION, SUSPICIOUS, FRAUD, INVALID, UNKNOWN.
    // (Before, anything except SAFE/SUSPICIOUS was painted red "blocked", even TRUSTED.)
    const tone = { TRUSTED: 'approved', SAFE: 'approved', CAUTION: 'warning', SUSPICIOUS: 'warning',
                   INVALID: 'warning', UNKNOWN: 'warning', FRAUD: 'blocked' }[data.verdict] || 'warning';
    const toneColor = { approved: 'var(--color-success)', warning: 'var(--color-warning)', blocked: 'var(--color-danger)' }[tone];
    if (verdictEl) {
        verdictEl.innerText = data.verdict;
        verdictEl.className = `verdict-tag ${tone}`;
    }
    // The number is a RISK score (0 = no known threat, 100 = dangerous), not a trust score.
    const risk = Number(data.trust_score) || 0;
    if (scoreFill) { scoreFill.style.backgroundColor = toneColor; scoreFill.style.width = `${Math.min(100, Math.max(0, risk))}%`; }
    if (scoreEl) scoreEl.innerText = `${risk.toFixed(0)}/100`;
    if (reasonsList) {
        reasonsList.innerHTML = '';
        (data.reasons || []).forEach(r => { reasonsList.innerHTML += `<li>${esc(r)}</li>`; });
        if (data.note) reasonsList.innerHTML += `<li style="opacity:.8"><em>${esc(data.note)}</em></li>`;
    }
    card.style.display = 'block';
}

async function submitScamReport(e) {
    e.preventDefault();
    const upiInput = document.getElementById('scam-upi-input');
    const descInput = document.getElementById('scam-description');
    if (!upiInput || !descInput) return;

    const scam_upi = upiInput.value.trim();
    const description = descInput.value.trim();
    if (!scam_upi || !description) return;

    try {
        const res = await fetch('/api/report-scam', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${userToken}` },
            body: JSON.stringify({ scam_upi, description })
        });
        const data = await res.json();
        if (data.success) {
            showToast('Scam report filed. Admin will review the reported wallet.', 'success');
            upiInput.value = '';
            descInput.value = '';
        } else {
            showToast('Failed to submit report: ' + data.message, 'error');
        }
    } catch {
        showToast('Network error. Could not submit report.', 'error');
    }
}

// ─────────────────────────────────────────────────────────────
// UPI PIN KEYPAD
// ─────────────────────────────────────────────────────────────
const UPI_PIN_LENGTH = 6;  // payment PINs are 6 digits (backend validate_pin)

function pressPinKey(digit) {
    if (enteredPin.length < UPI_PIN_LENGTH) {
        enteredPin += digit;
        updatePinDots();
    }
}

function clearPinKey() {
    if (enteredPin.length > 0) {
        enteredPin = enteredPin.slice(0, -1);
        updatePinDots();
    }
}

function updatePinDots() {
    for (let i = 1; i <= UPI_PIN_LENGTH; i++) {
        const dot = document.getElementById(`pin-dot-${i}`);
        if (dot) {
            dot.classList.toggle('active', i <= enteredPin.length);
        }
    }
}

function closeUpiPinModal() {
    const modal = document.getElementById('upi-pin-modal');
    if (modal) modal.style.display = 'none';
    enteredPin = '';
    pinActionContext = '';
    updatePinDots();
}

async function submitPinKey() {
    if (enteredPin.length !== UPI_PIN_LENGTH) {
        showToast('Please enter your complete 6-digit UPI PIN.', 'warning');
        return;
    }
    const pin = enteredPin;
    enteredPin = '';
    updatePinDots();

    if (pinActionContext === 'TRANSFER') submitTransferWithPin(pin);
    else if (pinActionContext === 'CHECK_BALANCE') submitBalanceCheckWithPin(pin);
}

function triggerCheckBalanceSecured() {
    enteredPin = '';
    pinActionContext = 'CHECK_BALANCE';
    updatePinDots();

    const receiverDisplay = document.getElementById('upi-pin-receiver-display');
    const amountDisplay = document.getElementById('upi-pin-amount-display');
    if (receiverDisplay) receiverDisplay.innerText = 'VIRTUAL ACCOUNT BALANCE';
    if (amountDisplay) amountDisplay.innerText = 'Authentication Required';

    const modal = document.getElementById('upi-pin-modal');
    if (modal) modal.style.display = 'flex';
}

async function submitBalanceCheckWithPin(pin) {
    try {
        const res = await fetch('/api/user/balance-secured', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${userToken}` },
            body: JSON.stringify({ pin })
        });
        const data = await res.json();

        if (data.success) {
            closeUpiPinModal();
            const balStr = '₹' + data.balance.toLocaleString('en-IN', { minimumFractionDigits: 2 });
            const balEl = document.getElementById('overview-balance');
            const eyeIcon = document.getElementById('balance-eye-icon');
            if (balEl) { balEl.innerText = balStr; balEl.style.letterSpacing = 'normal'; }
            if (eyeIcon) eyeIcon.className = 'fa-solid fa-eye-slash';

            // Auto-mask after 7 seconds
            setTimeout(() => {
                if (balEl) { balEl.innerText = '••••••'; balEl.style.letterSpacing = '2px'; }
                if (eyeIcon) eyeIcon.className = 'fa-solid fa-eye';
            }, 7000);
        } else {
            showToast('Verification failed: ' + data.message, 'error');
            closeUpiPinModal();
        }
    } catch {
        showToast('Failed to verify balance. Check connection.', 'error');
        closeUpiPinModal();
    }
}

// ─────────────────────────────────────────────────────────────
// SETTINGS
// ─────────────────────────────────────────────────────────────
async function loadUserSettings() {
    try {
        const res = await fetch('/api/user/settings', {
            headers: { 'Authorization': `Bearer ${userToken}` }
        });
        const data = await res.json();
        if (data.success) {
            const limitEl = document.getElementById('settings-daily-limit');
            if (limitEl) limitEl.value = data.daily_limit;
        }
    } catch (err) {
        console.error('Settings load failed:', err);
    }
}

async function updateUserSettings(e) {
    e.preventDefault();
    const limitInput = document.getElementById('settings-daily-limit');
    const errorDiv = document.getElementById('settings-error');
    const successDiv = document.getElementById('settings-success');
    if (!limitInput) return;

    if (errorDiv) errorDiv.style.display = 'none';
    if (successDiv) successDiv.style.display = 'none';

    const daily_limit = parseFloat(limitInput.value);
    if (isNaN(daily_limit) || daily_limit <= 0) return;

    try {
        const res = await fetch('/api/user/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${userToken}` },
            body: JSON.stringify({ daily_limit })
        });
        const data = await res.json();
        if (data.success) {
            if (successDiv) successDiv.style.display = 'flex';
            limitInput.value = data.daily_limit;
            setTimeout(() => { if (successDiv) successDiv.style.display = 'none'; }, 3000);
            showToast('Daily limit updated successfully.', 'success');
        } else {
            if (errorDiv) errorDiv.style.display = 'flex';
            const errMsg = document.getElementById('settings-error-msg');
            if (errMsg) errMsg.innerText = data.message;
        }
    } catch {
        if (errorDiv) errorDiv.style.display = 'flex';
        const errMsg = document.getElementById('settings-error-msg');
        if (errMsg) errMsg.innerText = 'Network error. Please try again.';
    }
}

function generateReceiveQr() {
    const amountInput = document.getElementById('receive-amount');
    const noteInput = document.getElementById('receive-note');
    const linkText = document.getElementById('receive-qr-link-text');
    const qrImg = document.getElementById('receive-qr-img');
    if (!userId) return;

    let upiLink = `upi://pay?pa=${encodeURIComponent(userId)}&pn=MLBFD%20User&cu=INR`;
    if (amountInput?.value.trim()) upiLink += `&am=${amountInput.value.trim()}`;
    if (noteInput?.value.trim()) upiLink += `&tn=${encodeURIComponent(noteInput.value.trim())}`;

    if (linkText) linkText.innerText = upiLink;
    if (qrImg) qrImg.src = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(upiLink)}`;
}

function copyUpiQrLink() {
    const linkText = document.getElementById('receive-qr-link-text')?.innerText;
    if (!linkText) return;
    copyTextToClipboard(linkText).then(() => {
        showToast('UPI payment link copied to clipboard!', 'success');
    }).catch(() => {
        showToast('Failed to copy. Please copy manually.', 'warning');
    });
}

// navigator.clipboard exists only on HTTPS or localhost. On http://<laptop-ip>:5000 (phones on the
// same Wi-Fi) it is undefined, so fall back to the older selection + execCommand('copy') method.
function copyTextToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(text);
    }
    return new Promise((resolve, reject) => {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0;';
        document.body.appendChild(ta);
        ta.select();
        ta.setSelectionRange(0, text.length);
        let ok = false;
        try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
        document.body.removeChild(ta);
        ok ? resolve() : reject(new Error('copy not supported'));
    });
}

function parseUpiQrLink() {
    const parseInput = document.getElementById('txn-qr-parse');
    if (!parseInput) return;
    const rawLink = parseInput.value.trim();
    if (!rawLink || !rawLink.includes('upi://pay?')) return;

    try {
        const params = new URLSearchParams(rawLink.split('?')[1]);
        const payee = params.get('pa');
        const amount = params.get('am');

        const receiverInput = document.getElementById('txn-receiver');
        const amountInput = document.getElementById('txn-amount');
        if (payee && receiverInput) receiverInput.value = payee;
        if (amount && amountInput) amountInput.value = amount;

        parseInput.value = '';
        triggerRiskPreview();

        if (receiverInput) {
            receiverInput.style.borderColor = 'var(--color-success)';
            setTimeout(() => { receiverInput.style.borderColor = ''; }, 1000);
        }
    } catch (err) {
        console.error('UPI link parse failed:', err);
    }
}

// ─────────────────────────────────────────────────────────────
// HELPER UTILITIES
// ─────────────────────────────────────────────────────────────
function getStatusClass(status) {
    const map = {
        'APPROVED': 'approved',
        'COMPLETED': 'completed',
        'APPROVED_WITH_WARNING': 'warning',
        'REQUIRES_2FA': 'requires_2fa',
        'PENDING': 'pending',
        'CANCELLED': 'cancelled',
        'BLOCKED': 'blocked'
    };
    return map[status] || 'approved';
}

function formatStatus(status) {
    return (status || '').replace(/_/g, ' ');
}

function formatDate(isoStr) {
    return new Date(isoStr).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' });
}

function truncate(str, maxLen) {
    if (!str) return '';
    return str.length > maxLen ? str.slice(0, maxLen) + '…' : str;
}

function renderRiskBar(score) {
    const color = score > 70 ? 'var(--color-danger)' : score > 40 ? 'var(--color-warning)' : 'var(--color-success)';
    return `
        <div class="risk-bar-inline">
            <div class="risk-bar-track">
                <div class="risk-bar-fill" style="width:${score}%; background:${color};"></div>
            </div>
            <span>${score.toFixed(0)}%</span>
        </div>`;
}

// ─────────────────────────────────────────────────────────────
// PIN MANAGEMENT HANDLERS (Change PIN)
// ─────────────────────────────────────────────────────────────
async function handlePinChangeInitiate(e) {
    e.preventDefault();
    const pinType = document.getElementById('pin-type').value;
    const currentPin = document.getElementById('pin-current').value.trim();
    const newPin = document.getElementById('pin-new').value.trim();
    const confirmPin = document.getElementById('pin-confirm').value.trim();
    const errDiv = document.getElementById('change-pin-error');
    const errMsg = document.getElementById('change-pin-error-msg');
    const successDiv = document.getElementById('change-pin-success');
    const successMsg = document.getElementById('change-pin-success-msg');
    const otpSection = document.getElementById('pin-change-otp-section');
    const initiateBtn = document.getElementById('btn-initiate-pin-change');

    errDiv.style.display = 'none';
    successDiv.style.display = 'none';

    if (newPin !== confirmPin) {
        errMsg.innerText = "New PIN and confirm PIN do not match.";
        errDiv.style.display = 'flex';
        return;
    }
    if (newPin.length !== 6 || !/^\d{6}$/.test(newPin)) {
        errMsg.innerText = "New PIN must be exactly 6 numeric digits.";
        errDiv.style.display = 'flex';
        return;
    }

    initiateBtn.disabled = true;
    initiateBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Verifying Current PIN...';

    try {
        const token = localStorage.getItem('mlbfd_token');
        const res = await fetch('/api/pin/change', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                pin_type: pinType,
                current_pin: currentPin,
                new_pin: newPin
            })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            successMsg.innerText = data.message || "Current PIN verified. OTPs dispatched.";
            successDiv.style.display = 'flex';
            otpSection.style.display = 'block';
            if (window.MLBFDOtp) {
                MLBFDOtp.render(document.getElementById('pin-delivery'), data.delivery, {
                    purpose: 'PIN_CHANGE',
                    headers: () => ({ 'Authorization': `Bearer ${localStorage.getItem('mlbfd_token')}` })
                });
            }
            document.getElementById('pin-current').disabled = true;
            document.getElementById('pin-new').disabled = true;
            document.getElementById('pin-confirm').disabled = true;
            document.getElementById('pin-type').disabled = true;
            initiateBtn.style.display = 'none';
        } else {
            errMsg.innerText = data.message || "Failed to verify current PIN.";
            errDiv.style.display = 'flex';
            initiateBtn.disabled = false;
            initiateBtn.innerHTML = '<i class="fa-solid fa-arrows-rotate"></i> Verify Current PIN & Send OTPs';
        }
    } catch (err) {
        errMsg.innerText = "Network error. Please try again.";
        errDiv.style.display = 'flex';
        initiateBtn.disabled = false;
        initiateBtn.innerHTML = '<i class="fa-solid fa-arrows-rotate"></i> Verify Current PIN & Send OTPs';
    }
}

async function handlePinChangeConfirm(e) {
    e.preventDefault();
    const emailOtp = document.getElementById('pin-change-email-otp').value.trim();
    const telegramOtp = document.getElementById('pin-change-telegram-otp').value.trim();
    const errDiv = document.getElementById('change-pin-error');
    const errMsg = document.getElementById('change-pin-error-msg');
    const successDiv = document.getElementById('change-pin-success');
    const successMsg = document.getElementById('change-pin-success-msg');
    const confirmBtn = document.getElementById('btn-confirm-pin-change');

    errDiv.style.display = 'none';
    confirmBtn.disabled = true;
    confirmBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Updating PIN...';

    try {
        const token = localStorage.getItem('mlbfd_token');
        const res = await fetch('/api/pin/change/confirm', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                email_code: emailOtp,
                telegram_code: telegramOtp
            })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            successMsg.innerText = data.message || "PIN changed successfully!";
            successDiv.style.display = 'flex';
            document.getElementById('pin-change-otp-section').style.display = 'none';
            document.getElementById('change-pin-form').reset();
            document.getElementById('pin-current').disabled = false;
            document.getElementById('pin-new').disabled = false;
            document.getElementById('pin-confirm').disabled = false;
            document.getElementById('pin-type').disabled = false;
            const initiateBtn = document.getElementById('btn-initiate-pin-change');
            initiateBtn.style.display = 'flex';
            initiateBtn.disabled = false;
            initiateBtn.innerHTML = '<i class="fa-solid fa-arrows-rotate"></i> Verify Current PIN & Send OTPs';
        } else {
            errMsg.innerText = data.message || "Invalid OTP codes.";
            errDiv.style.display = 'flex';
            confirmBtn.disabled = false;
            confirmBtn.innerHTML = '<i class="fa-solid fa-check"></i> Confirm & Update PIN';
        }
    } catch (err) {
        errMsg.innerText = "Network error. Please try again.";
        errDiv.style.display = 'flex';
        confirmBtn.disabled = false;
        confirmBtn.innerHTML = '<i class="fa-solid fa-check"></i> Confirm & Update PIN';
    }
}

// ─────────────────────────────────────────────────────────────
// ACCURATE LOCATION & MAP PICKER (PART 16)
// ─────────────────────────────────────────────────────────────
let leafletMapInstance = null;
let mapMarker = null;

function updateLocationCardUI() {
    const areaEl = document.getElementById('loc-area-display');
    const accEl = document.getElementById('loc-accuracy-display');
    if (areaEl) areaEl.innerText = currentCoords.source === 'default' ? 'Location not detected' : (currentCoords.area_name || 'Unknown area');
    if (accEl) {
        const srcText = currentCoords.source === 'manual_pin' ? 'Manual Pin' : (currentCoords.source === 'gps' ? 'GPS' : 'Default (not detected: tap Detect)');
        accEl.innerText = `Source: ${srcText} (Accuracy: ~${currentCoords.accuracy_m}m)`;
    }
}

async function fetchAreaName(lat, lon) {
    try {
        const res = await fetch(`/api/reverse_geocode?lat=${lat}&lon=${lon}`);
        if (res.ok) {
            const data = await res.json();
            return data.area_name || `${Number(lat).toFixed(4)}, ${Number(lon).toFixed(4)}`;
        }
    } catch (e) {
        console.error("Reverse geocoding error:", e);
    }
    return `${Number(lat).toFixed(4)}, ${Number(lon).toFixed(4)}`;
}

function openMapModal() {
    const modal = document.getElementById('map-modal');
    if (!modal) return;
    modal.style.display = 'flex';

    setTimeout(() => {
        if (!leafletMapInstance && window.L) {
            leafletMapInstance = L.map('leaflet-map').setView([currentCoords.lat, currentCoords.lon], 14);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19,
                attribution: '© OpenStreetMap contributors'
            }).addTo(leafletMapInstance);

            mapMarker = L.marker([currentCoords.lat, currentCoords.lon], { draggable: true }).addTo(leafletMapInstance);

            mapMarker.on('dragend', async function() {
                const pos = mapMarker.getLatLng();
                const area = await fetchAreaName(pos.lat, pos.lng);
                const modalArea = document.getElementById('modal-area-name');
                if (modalArea) modalArea.innerText = area;
            });

            leafletMapInstance.on('click', async function(e) {
                mapMarker.setLatLng(e.latlng);
                const area = await fetchAreaName(e.latlng.lat, e.latlng.lng);
                const modalArea = document.getElementById('modal-area-name');
                if (modalArea) modalArea.innerText = area;
            });
        } else if (leafletMapInstance) {
            leafletMapInstance.invalidateSize();
            leafletMapInstance.setView([currentCoords.lat, currentCoords.lon], 14);
            if (mapMarker) mapMarker.setLatLng([currentCoords.lat, currentCoords.lon]);
        }
        const modalArea = document.getElementById('modal-area-name');
        if (modalArea) modalArea.innerText = currentCoords.area_name || 'Rajajinagar, Bengaluru';
    }, 150);
}

function closeMapModal() {
    const modal = document.getElementById('map-modal');
    if (modal) modal.style.display = 'none';
}

function setPresetLocation(lat, lon, name) {
    if (mapMarker && leafletMapInstance) {
        mapMarker.setLatLng([lat, lon]);
        leafletMapInstance.setView([lat, lon], 15);
        const modalArea = document.getElementById('modal-area-name');
        if (modalArea) modalArea.innerText = name;
    }
}

function confirmManualPinLocation() {
    if (mapMarker) {
        const pos = mapMarker.getLatLng();
        const modalArea = document.getElementById('modal-area-name');
        const area = modalArea ? modalArea.innerText : 'Rajajinagar, Bengaluru';
        currentCoords.lat = pos.lat;
        currentCoords.lon = pos.lng;
        currentCoords.accuracy_m = 10;
        currentCoords.source = 'manual_pin';
        currentCoords.area_name = area;
        updateLocationCardUI();
    }
    closeMapModal();
}



// ─────────────────────────────────────────────────────────────
// DEMO BALANCE RESET
// ─────────────────────────────────────────────────────────────
async function handleResetBalance() {
    showConfirm("Are you sure you want to reset your virtual balance to ₹100,000?", async () => {
        try {
            const res = await fetch('/api/account/reset_balance', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${userToken}`
                },
                body: JSON.stringify({ user_id: userId })
            });
            const data = await res.json();
            if (data.success) {
                showToast(data.message || 'Balance reset to ₹100,000.', 'success');
                refreshDashboardData();
            } else {
                showToast(data.message || 'Could not reset balance.', 'error');
            }
        } catch (e) {
            showToast('Network error resetting balance.', 'error');
        }
    });
}


// ─────────────────────────────────────────────────────────────
// FORGOT PAYMENT PIN (works while logged in; email + Telegram codes + security answer)
// Uses /api/pin/forgot/start | verify | reset with pin_type "payment".
// ─────────────────────────────────────────────────────────────
let fppResetToken = '';
const FPP_LABELS = { 'fpp-btn-1': 'Send codes', 'fpp-btn-2': 'Verify codes', 'fpp-btn-3': 'Set new PIN' };

function fppShowError(msg) {
    const box = document.getElementById('fpp-error');
    document.getElementById('fpp-error-msg').innerText = msg;
    box.style.display = 'flex';
}

function fppSetBusy(id, busy) {
    const b = document.getElementById(id);
    if (!b) return;
    b.disabled = busy;
    b.innerText = busy ? 'Please wait…' : FPP_LABELS[id];
}

function fppResetState() {
    fppResetToken = '';
    ['fpp-email-code', 'fpp-telegram-code', 'fpp-answer', 'fpp-new-pin', 'fpp-confirm-pin'].forEach(id => {
        const i = document.getElementById(id);
        if (i) i.value = '';
    });
    Object.keys(FPP_LABELS).forEach(id => fppSetBusy(id, false));
    document.getElementById('fpp-error').style.display = 'none';
    const d = document.getElementById('fpp-delivery');
    d.textContent = '';
    d.style.display = 'none';
    document.getElementById('fpp-step-1').style.display = 'block';
    document.getElementById('fpp-step-2').style.display = 'none';
    document.getElementById('fpp-step-3').style.display = 'none';
}

function openForgotPaymentPin(e) {
    if (e && e.preventDefault) e.preventDefault();
    if (typeof closeUpiPinModal === 'function') closeUpiPinModal();   // leave the keypad if it was open
    fppResetState();
    document.getElementById('forgot-payment-modal').style.display = 'flex';
}

function closeForgotPaymentPin() {
    document.getElementById('forgot-payment-modal').style.display = 'none';
    fppResetState();
}

async function fppSendCodes() {
    document.getElementById('fpp-error').style.display = 'none';
    fppSetBusy('fpp-btn-1', true);
    try {
        const res = await fetch('/api/pin/forgot/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.success === false) {
            fppShowError(data.message || 'Could not send the codes. Please try again.');
            fppSetBusy('fpp-btn-1', false);
            return;
        }
        document.getElementById('fpp-step-1').style.display = 'none';
        document.getElementById('fpp-step-2').style.display = 'block';
        if (window.MLBFDOtp && data.delivery) {
            MLBFDOtp.render(document.getElementById('fpp-delivery'), data.delivery, { purpose: 'PIN_RESET', userId: userId });
        }
        document.getElementById('fpp-email-code').focus();
    } catch (err) {
        fppShowError('Network error. Please try again.');
        fppSetBusy('fpp-btn-1', false);
    }
}

async function fppVerifyCodes(e) {
    e.preventDefault();
    document.getElementById('fpp-error').style.display = 'none';
    const emailCode = document.getElementById('fpp-email-code').value.trim();
    const telegramCode = document.getElementById('fpp-telegram-code').value.trim();
    if (!/^\d{6}$/.test(emailCode) || !/^\d{6}$/.test(telegramCode)) {
        fppShowError('Enter both 6-digit codes (email and Telegram).');
        return;
    }
    fppSetBusy('fpp-btn-2', true);
    try {
        const res = await fetch('/api/pin/forgot/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, email_code: emailCode, telegram_code: telegramCode })
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok && data.success) {
            fppResetToken = data.reset_token;
            document.getElementById('fpp-question').innerText = data.security_question || 'Security question';
            document.getElementById('fpp-step-2').style.display = 'none';
            document.getElementById('fpp-step-3').style.display = 'block';
            document.getElementById('fpp-answer').focus();
        } else {
            fppShowError(data.message || 'Invalid or expired codes.');
        }
    } catch (err) {
        fppShowError('Network error. Please try again.');
    }
    fppSetBusy('fpp-btn-2', false);
}

async function fppResetPin(e) {
    e.preventDefault();
    document.getElementById('fpp-error').style.display = 'none';
    const answer = document.getElementById('fpp-answer').value.trim();
    const newPin = document.getElementById('fpp-new-pin').value.trim();
    const confirmPin = document.getElementById('fpp-confirm-pin').value.trim();
    if (!answer) { fppShowError('Please answer your security question.'); return; }
    if (!/^\d{6}$/.test(newPin)) { fppShowError('The PIN must be exactly 6 digits.'); return; }
    if (newPin !== confirmPin) { fppShowError('The two PIN entries do not match.'); return; }
    fppSetBusy('fpp-btn-3', true);
    let deviceId = localStorage.getItem('mlbfd_device_id') || '';
    try {
        const res = await fetch('/api/pin/forgot/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Device-ID': deviceId },
            body: JSON.stringify({ reset_token: fppResetToken, security_answer: answer, new_pin: newPin,
                                   pin_type: 'payment', device_id: deviceId })
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok && data.success) {
            // A reset signs every session out on the server; keep THIS one alive with the fresh tokens.
            if (data.access_token) {
                localStorage.setItem('mlbfd_token', data.access_token);
                userToken = data.access_token;
            }
            if (data.refresh_token) localStorage.setItem('mlbfd_refresh_token', data.refresh_token);
            if (data.user_id) { localStorage.setItem('mlbfd_user_id', data.user_id); userId = data.user_id; }
            closeForgotPaymentPin();
            showToast('Payment PIN changed. Payments are limited to Rs 10,000 per transaction for the next 24 hours.', 'success', 7000);
        } else {
            fppShowError(data.message || 'Could not reset the PIN.');
            fppSetBusy('fpp-btn-3', false);
        }
    } catch (err) {
        fppShowError('Network error. Please try again.');
        fppSetBusy('fpp-btn-3', false);
    }
}

// ─────────────────────────────────────────────────────────────
// NATIVE APP BRIDGE (MLBFD Android app)
// Inside the app's web view the browser's own camera/location are blocked on http://<laptop-ip>:5000
// (not a secure origin), so the app provides them natively through window.MLBFDApp and calls back
// into window.mlbfdNative.*. In a normal browser everything falls back to standard web APIs.
// ─────────────────────────────────────────────────────────────
const IN_APP = typeof window.MLBFDApp !== 'undefined';
const _pendingLocation = [];

window.mlbfdNative = {
    onLocation(res) {
        const resolve = _pendingLocation.shift();
        if (resolve) resolve(res || { ok: false, error: 'No location returned' });
    },
    onQr(text) { handleScannedQr(text); }
};

function appRequestLocation() {
    return new Promise((resolve) => {
        _pendingLocation.push(resolve);
        try {
            window.MLBFDApp.postMessage(JSON.stringify({ type: 'get_location' }));
        } catch (e) {
            _pendingLocation.pop();
            resolve({ ok: false, error: 'App bridge unavailable' });
            return;
        }
        setTimeout(() => {
            const i = _pendingLocation.indexOf(resolve);
            if (i >= 0) { _pendingLocation.splice(i, 1); resolve({ ok: false, error: 'Timed out waiting for the phone location' }); }
        }, 30000);
    });
}

function browserRequestLocation() {
    return new Promise((resolve) => {
        if (!navigator.geolocation) { resolve({ ok: false, error: 'Location is not available in this browser' }); return; }
        navigator.geolocation.getCurrentPosition(
            (p) => resolve({ ok: true, lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy }),
            (e) => resolve({ ok: false, error: e && e.message ? e.message : 'Location permission denied' }),
            { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
        );
    });
}

async function detectLocation(userClicked) {
    const areaEl = document.getElementById('loc-area-display');
    if (areaEl) areaEl.innerText = 'Detecting area...';
    const res = IN_APP ? await appRequestLocation() : await browserRequestLocation();
    if (res && res.ok) {
        currentCoords.lat = res.lat;
        currentCoords.lon = res.lon;
        currentCoords.accuracy_m = Math.round(res.accuracy || 50);
        currentCoords.source = 'gps';
        currentCoords.area_name = await fetchAreaName(res.lat, res.lon);
        updateLocationCardUI();
        if (userClicked) showToast('Location updated', 'success');
    } else {
        currentCoords.source = 'default';
        updateLocationCardUI();
        if (userClicked) showToast((res && res.error) || 'Could not detect your location', 'warning', 6000);
    }
}

function scanUpiQr() {
    if (!IN_APP) {
        showToast('QR scanning works in the MLBFD app. Paste a UPI link instead.', 'info');
        return;
    }
    try {
        window.MLBFDApp.postMessage(JSON.stringify({ type: 'scan_qr' }));
    } catch (e) {
        showToast('Could not open the camera', 'error');
    }
}

function handleScannedQr(text) {
    const t = String(text || '').trim();
    const parseInput = document.getElementById('txn-qr-parse');
    const receiverInput = document.getElementById('txn-receiver');
    if (/^upi:\/\/pay\?/i.test(t)) {
        if (parseInput) {
            parseInput.value = t.replace(/^upi:\/\/pay\?/i, 'upi://pay?');
            parseUpiQrLink();
        }
        showToast('QR scanned: payee details filled in', 'success');
    } else if (/^[A-Za-z0-9._\-]{2,}@[A-Za-z0-9.\-]{2,}$/.test(t)) {
        if (receiverInput) receiverInput.value = t;
        if (typeof triggerRiskPreview === 'function') triggerRiskPreview();
        showToast('QR scanned: payee filled in', 'success');
    } else {
        showToast('That QR code is not a UPI payment code', 'warning', 6000);
    }
}
