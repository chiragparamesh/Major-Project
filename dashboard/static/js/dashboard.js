// Escape any server/user-supplied text before it goes into innerHTML.
function esc(value) {
    return String(value === undefined || value === null ? '' : value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/**
 * MLBFD - Admin Web Dashboard Main Controller
 * Author: Chirag (@chirag4455)
 * Repository: https://github.com/chirag4455/UPI-Fraud-Detection
 */

// Global Configuration
const API_BASE = '/admin/api';

// Format Helpers
function formatCurrency(amount) {
    return new Intl.NumberFormat('en-IN', {
        style: 'currency',
        currency: 'INR',
        minimumFractionDigits: 2
    }).format(amount);
}

function formatDate(isoString) {
    if (!isoString || isoString === 'Never') return 'Never';
    return new Date(isoString).toLocaleString('en-IN', {
        dateStyle: 'medium',
        timeStyle: 'short',
        timeZone: 'Asia/Kolkata'  // API timestamps are UTC ("...Z")
    });
}

// Global UI Notifications
function showNotification(message, type = 'info') {
    const notifContainer = document.getElementById('notification-container') || createNotificationContainer();
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type} animate-slide-in`;
    toast.innerHTML = `
        <div class="toast-content">
            <i class="fa-solid ${getNotificationIcon(type)}"></i>
            <span>${message}</span>
        </div>
        <button class="toast-close" onclick="this.parentElement.remove()">&times;</button>
    `;
    
    notifContainer.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
}

function getNotificationIcon(type) {
    switch(type) {
        case 'success': return 'fa-circle-check';
        case 'danger': return 'fa-circle-exclamation';
        case 'warning': return 'fa-triangle-exclamation';
        default: return 'fa-circle-info';
    }
}

function createNotificationContainer() {
    const container = document.createElement('div');
    container.id = 'notification-container';
    container.style.position = 'fixed';
    container.style.top = '24px';
    container.style.right = '24px';
    container.style.zIndex = '9999';
    container.style.display = 'flex';
    container.style.flexDirection = 'column';
    container.style.gap = '12px';
    document.body.appendChild(container);
    return container;
}

// User Profile Actions
async function toggleUserLockState(userId, currentLockState) {
    const endpoint = `${API_BASE}/users/${userId}/toggle-lock`;
    try {
        const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lock: !currentLockState })
        });
        const result = await res.json();
        
        if (result.success) {
            showNotification(result.message, 'success');
            // Proactively refresh users view if it exists on current page
            if (typeof loadUsersList === 'function') {
                loadUsersList();
            }
        } else {
            showNotification(result.message || 'Operation failed', 'danger');
        }
    } catch (err) {
        console.error("Lock/Unlock toggle failed:", err);
        showNotification("Failed to toggle user lock status", 'danger');
    }
}

// Compliance and Export
function exportNPCIFraudReport() {
    showNotification("Generating NPCI Compliance Report...", "info");
    window.location.href = `${API_BASE}/compliance/npci-export`;
}

// Global Event Handlers
document.addEventListener('DOMContentLoaded', () => {
    // Add export button binding if available
    const exportBtn = document.getElementById('btn-export-npci');
    if (exportBtn) {
        exportBtn.addEventListener('click', exportNPCIFraudReport);
    }
});
