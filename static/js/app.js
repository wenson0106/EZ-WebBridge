/**
 * Nginx Proxy Manager — Frontend Application Logic
 */

// ─── Toast Notifications ─────────────────────────────────

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    let toastIcon = '';
    if (type === 'success') toastIcon = icon('check');
    else if (type === 'error') toastIcon = icon('alertCircle');
    else toastIcon = icon('info');

    toast.innerHTML = `${toastIcon}<span>${escapeHtml(message)}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'toast-out 0.3s ease forwards';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}


// ─── Modal Helpers ───────────────────────────────────────

function openModal(modalId) {
    const overlay = document.getElementById(modalId);
    if (overlay) {
        overlay.classList.add('active');
        document.body.style.overflow = 'hidden';
    }
}

function closeModal(modalId) {
    const overlay = document.getElementById(modalId);
    if (overlay) {
        overlay.classList.remove('active');
        document.body.style.overflow = '';
    }
}

// Close modals on overlay click
document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay')) {
        e.target.classList.remove('active');
        document.body.style.overflow = '';
    }
});

// Close modals on Escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay.active').forEach(m => {
            m.classList.remove('active');
        });
        document.body.style.overflow = '';
    }
});


// ─── Icon Renderer ───────────────────────────────────────

function renderIcons() {
    document.querySelectorAll('[data-icon]').forEach(el => {
        const name = el.getAttribute('data-icon');
        if (Icons[name]) {
            el.innerHTML = Icons[name];
        }
    });
}


// ─── Utilities ───────────────────────────────────────────

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}


// ─── Nginx Status Logic ──────────────────────────────────

async function checkNginxStatus() {
    const container = document.getElementById('nginx-status-container');
    if (!container) return;

    try {
        const resp = await fetch('/api/nginx/status');
        const data = await resp.json();

        let html = '';
        if (!data.installed) {
            html = `
                <div class="nginx-status-indicator">
                    <div class="nginx-dot stopped"></div>
                    <span>Nginx Not Installed</span>
                </div>
                <div class="nginx-controls">
                    <button class="nginx-btn" onclick="installNginx()" title="Download & Install Nginx">
                        ${icon('download')}
                    </button>
                </div>
            `;
        } else {
            const statusClass = data.running ? 'running' : 'stopped';
            const statusText = data.running ? 'Running' : 'Stopped';
            const actionBtn = data.running
                ? `<button class="nginx-btn" onclick="stopNginx()" title="Stop Nginx">${icon('square')}</button>`
                : `<button class="nginx-btn" onclick="startNginx()" title="Start Nginx">${icon('play')}</button>`;

            html = `
                 <div class="nginx-status-indicator">
                    <div class="nginx-dot ${statusClass}"></div>
                    <span>${statusText}</span>
                </div>
                <div class="nginx-controls">
                    ${actionBtn}
                </div>
            `;
        }
        container.innerHTML = `<div class="nginx-status-widget">${html}</div>`;

        // Re-render icons since we injected HTML with icons
        const btns = container.querySelectorAll('.nginx-btn');
        btns.forEach(btn => {
            // Icons are already SVG strings in the HTML injection above, 
            // but if I used a method that needed renderIcons(), I'd call it.
            // here template literal ${icon('...')} works directly.
        });
    } catch (e) {
        console.error('Failed to check nginx status', e);
    }
}

async function installNginx() {
    const btn = document.querySelector('.nginx-status-widget .nginx-btn');
    if (btn) btn.innerHTML = `<div class="spinner" style="width:14px;height:14px;border-width:2px;"></div>`;

    showToast('Downloading Nginx... this may take a minute.', 'info');
    try {
        const resp = await fetch('/api/nginx/install', { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
            showToast('Nginx installed successfully.', 'success');
            checkNginxStatus();
        } else {
            showToast('Install failed: ' + data.message, 'error');
            checkNginxStatus(); // Reset UI
        }
    } catch (e) {
        showToast('Network error during install.', 'error');
        checkNginxStatus();
    }
}

async function startNginx() {
    try {
        const resp = await fetch('/api/nginx/start', { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
            showToast('Nginx started.', 'success');
            checkNginxStatus();
        } else {
            showToast('Start failed: ' + data.message, 'error');
        }
    } catch (e) {
        showToast('Network error.', 'error');
    }
}

async function stopNginx() {
    try {
        const resp = await fetch('/api/nginx/stop', { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
            showToast('Nginx stopped.', 'success');
            checkNginxStatus();
        } else {
            showToast('Stop failed: ' + data.message, 'error');
        }
    } catch (e) {
        showToast('Network error.', 'error');
    }
}

// Start polling
setInterval(checkNginxStatus, 5000);
document.addEventListener('DOMContentLoaded', checkNginxStatus);

