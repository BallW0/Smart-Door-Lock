const API_BASE = 'http://localhost:3000/api';

let state = {
    logs: [],
    system: {},
    filter: 'all'
};

let eventSource = null;


document.addEventListener('DOMContentLoaded', () => {
    setupNavigation();
    setupFilters();
    connectSSE();
    updateClock();
    setupFaceRegistration();
    setInterval(updateClock, 1000);

    loadSystemStatus();
    loadLogs();
});

function updateClock() {
    const now = new Date();
    const h = String(now.getHours()).padStart(2, '0');
    const m = String(now.getMinutes()).padStart(2, '0');
    const s = String(now.getSeconds()).padStart(2, '0');
    const el = document.getElementById('currentTime');
    if (el) el.textContent = `${h}:${m}:${s}`;
}

function setupNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', e => {
            e.preventDefault();
            const target = item.dataset.target;

            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            item.classList.add('active');

            document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
            document.getElementById(target).classList.add('active');

            const titles = {
                dashboard: ['Dashboard', 'Pantau status pintu secara real-time'],
                logs: ['Riwayat Akses', 'Seluruh log akses masuk dan ditolak'],
                'face-registration': ['Registrasi Wajah', 'Daftarkan wajah baru menggunakan kamera']
            };
            document.getElementById('pageTitle').textContent = titles[target][0];
            document.getElementById('pageSubtitle').textContent = titles[target][1];

            if (target === 'logs') loadLogs();
        });
    });
}


function connectSSE() {
    if (eventSource) eventSource.close();
    eventSource = new EventSource(`${API_BASE}/events`);

    eventSource.onmessage = e => {
        const event = JSON.parse(e.data);
        handleSSEEvent(event);
    };

    eventSource.onopen = () => {
        setConnStatus(true);
    };

    eventSource.onerror = () => {
        setConnStatus(false);
        console.warn('SSE disconnected. Reconnecting...');
        setTimeout(connectSSE, 5000);
    };
}


function handleSSEEvent(event) {
    if (event.type === 'system') {
        state.system = event.data;
        updateDoorUI();
    } else if (event.type === 'access_logs') {
        // Real-time update: prepend new log to dashboard activity
        const logsArr = Object.values(event.data || {})
            .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
        renderRecentActivity(logsArr.slice(0, 5));

        // Also reload full table if on logs page
        if (document.getElementById('logs').classList.contains('active')) {
            loadLogs();
        }

        // Refresh stats
        loadLogs(false); // silent refresh for stats
    } else if (event.type === 'connected') {
        setConnStatus(true);
    }
}

// ── System Status ─────────────────────────────────────────────
async function loadSystemStatus() {
    try {
        const res = await fetch(`${API_BASE}/system/status`);
        state.system = await res.json();
        updateDoorUI();
    } catch (err) {
        console.error('Failed to load system status:', err);
    }
}

function updateDoorUI() {
    const sys      = state.system;
    const wrap     = document.getElementById('doorIconWrap');
    const statusTx = document.getElementById('doorStatusText');
    const metaTx   = document.getElementById('doorMeta');
    const faceBadge= document.getElementById('faceBadge');
    const faceText = document.getElementById('faceStatusText');

    if (!wrap || !statusTx) return;

    const isUnlocked = sys.door_status === 'unlocked';

    if (isUnlocked) {
        wrap.classList.add('unlocked');
        statusTx.classList.add('unlocked');
        statusTx.textContent = 'TERBUKA';
    } else {
        wrap.classList.remove('unlocked');
        statusTx.classList.remove('unlocked');
        statusTx.textContent = 'TERKUNCI';
    }

    if (sys.last_activity) {
        metaTx.textContent = 'Terakhir diperbarui: ' + formatTime(sys.last_activity);
    }

    if (sys.face_recognized) {
        faceBadge.classList.add('recognized');
        faceText.textContent = 'Wajah Terdeteksi';
        setTimeout(() => {
            faceBadge.classList.remove('recognized');
            faceText.textContent = 'Menunggu Wajah';
        }, 15000);
    }
}

// ── Logs ──────────────────────────────────────────────────────
async function loadLogs(renderTable = true) {
    try {
        const res = await fetch(`${API_BASE}/logs?limit=100`);
        const data = await res.json();
        state.logs = data;
        updateStats(data);
        renderRecentActivity(data.slice(0, 5));
        if (renderTable) renderLogsTable();
    } catch (err) {
        console.error('Failed to load logs:', err);
    }
}

function updateStats(logs) {
    const today = new Date().toDateString();
    const granted = logs.filter(l => l.status === 'granted').length;
    const denied  = logs.filter(l => l.status === 'denied').length;
    const todayCount = logs.filter(l => new Date(l.timestamp).toDateString() === today).length;

    document.getElementById('statTotalLogs').textContent = logs.length;
    document.getElementById('statGranted').textContent   = granted;
    document.getElementById('statDenied').textContent    = denied;
    document.getElementById('statToday').textContent     = todayCount;
}

function renderRecentActivity(logs) {
    const feed = document.getElementById('activityFeed');
    if (!feed) return;

    if (!logs || logs.length === 0) {
        feed.innerHTML = '<div class="empty-state">Belum ada aktivitas</div>';
        return;
    }

    feed.innerHTML = logs.map(log => {
        const isFace   = log.method === 'face';
        const isGranted= log.status === 'granted';
        const icon = isFace ? '👤' : '⌨️';
        const methodLabel = isFace ? 'Face Recognition' : 'Keypad PIN';
        const statusCls   = isGranted ? 'status-granted' : 'status-denied';
        const statusLabel = isGranted ? 'Diberikan' : 'Ditolak';

        return `
        <div class="activity-item">
            <div class="activity-icon ${isFace ? 'face' : 'keypad'}">${icon}</div>
            <div class="activity-details">
                <div class="activity-user">${log.user || 'Tidak Dikenal'}</div>
                <div class="activity-sub">${methodLabel}</div>
            </div>
            <div class="activity-right">
                <div><span class="status-badge ${statusCls}">${statusLabel}</span></div>
                <div class="activity-time">${formatTime(log.timestamp)}</div>
            </div>
        </div>`;
    }).join('');
}

function renderLogsTable() {
    const tbody = document.getElementById('logsTableBody');
    if (!tbody) return;

    const filtered = state.filter === 'all'
        ? state.logs
        : state.logs.filter(l => l.status === state.filter);

    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-state">Tidak ada data</td></tr>';
        return;
    }

    tbody.innerHTML = filtered.map(log => {
        const isFace    = log.method === 'face';
        const isGranted = log.status === 'granted';
        const methodLabel = isFace ? 'Face Recognition' : 'Keypad PIN';
        const methodCls   = isFace ? 'method-face' : 'method-keypad';
        const methodIcon  = isFace ? '👤' : '⌨️';
        const statusCls   = isGranted ? 'status-granted' : 'status-denied';
        const statusLabel = isGranted ? 'Diberikan' : 'Ditolak';

        return `<tr>
            <td style="font-variant-numeric:tabular-nums; color:var(--text-secondary)">${formatTime(log.timestamp)}</td>
            <td><span class="method-badge ${methodCls}">${methodIcon} ${methodLabel}</span></td>
            <td style="font-weight:600">${log.user || '—'}</td>
            <td><span class="status-badge ${statusCls}">${statusLabel}</span></td>
            <td style="color:var(--text-muted)">${log.details || '—'}</td>
        </tr>`;
    }).join('');
}

// ── Filter Buttons ────────────────────────────────────────────
function setupFilters() {
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.filter = btn.dataset.filter;
            renderLogsTable();
        });
    });
}

// ── Clear Logs ────────────────────────────────────────────────
async function clearLogs() {
    if (!confirm('Hapus seluruh log akses secara permanen?')) return;
    try {
        await fetch(`${API_BASE}/logs/clear`, { method: 'DELETE' });
        state.logs = [];
        updateStats([]);
        renderRecentActivity([]);
        renderLogsTable();
        showToast('Semua log berhasil dihapus', 'success');
    } catch (err) {
        showToast('Gagal menghapus log', 'error');
    }
}

// ── Helpers ───────────────────────────────────────────────────
function formatTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    return d.toLocaleString('id-ID', {
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => { if (toast.parentElement) toast.remove(); }, 3500);
}

// ==========================================
// Face Registration Logic
// ==========================================
let videoStream = null;
let capturedImages = [];

function setupFaceRegistration() {
    const btnStart = document.getElementById('btnStartCamera');
    const btnRegister = document.getElementById('btnRegisterFace');
    const inputName = document.getElementById('faceName');

    if (!btnStart) return;

    btnStart.addEventListener('click', async () => {
        if (!videoStream) {
            await startCamera();
            btnStart.textContent = 'Matikan Kamera';
            btnStart.classList.replace('btn-primary', 'btn-danger');
            checkFormValid();
        } else {
            stopCamera();
            btnStart.textContent = 'Nyalakan Kamera';
            btnStart.classList.replace('btn-danger', 'btn-primary');
            btnRegister.disabled = true;
        }
    });

    inputName.addEventListener('input', checkFormValid);

    btnRegister.addEventListener('click', async () => {
        const name = inputName.value.trim();
        if (!name || !videoStream) return;
        
        btnRegister.disabled = true;
        btnRegister.textContent = 'Merekam...';
        await captureFrames(name);
    });
}

function checkFormValid() {
    const name = document.getElementById('faceName').value.trim();
    const btnRegister = document.getElementById('btnRegisterFace');
    btnRegister.disabled = !(name.length > 0 && videoStream !== null);
}

async function startCamera() {
    try {
        videoStream = await navigator.mediaDevices.getUserMedia({ video: true });
        const video = document.getElementById('webcamVideo');
        video.srcObject = videoStream;
    } catch (err) {
        console.error("Camera error:", err);
        showToast("Gagal mengakses kamera. Pastikan izin diberikan.", "error");
    }
}

function stopCamera() {
    if (videoStream) {
        videoStream.getTracks().forEach(track => track.stop());
        videoStream = null;
    }
    const video = document.getElementById('webcamVideo');
    if (video) video.srcObject = null;
}

async function captureFrames(name) {
    const video = document.getElementById('webcamVideo');
    const canvas = document.getElementById('webcamCanvas');
    const ctx = canvas.getContext('2d');
    const overlay = document.getElementById('captureOverlay');
    const countSpan = document.getElementById('captureCount');
    
    // Match canvas to video size
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;

    capturedImages = [];
    overlay.style.display = 'flex';
    
    // Capture 30 frames
    for (let i = 0; i < 30; i++) {
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        const base64Img = canvas.toDataURL('image/jpeg', 0.8);
        capturedImages.push(base64Img);
        
        countSpan.textContent = i + 1;
        // Small delay between captures
        await new Promise(r => setTimeout(r, 150));
    }

    overlay.style.display = 'none';
    document.getElementById('btnRegisterFace').textContent = 'Mengirim Data...';

    // Send to API
    try {
        const res = await fetch(`${API_BASE}/faces/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name, images: capturedImages })
        });
        const data = await res.json();
        
        if (data.success) {
            showToast(data.message, 'success');
            document.getElementById('faceName').value = '';
            stopCamera();
            
            const btnStart = document.getElementById('btnStartCamera');
            btnStart.textContent = 'Nyalakan Kamera';
            btnStart.classList.replace('btn-danger', 'btn-primary');
        } else {
            showToast(data.error || "Gagal menyimpan wajah", 'error');
        }
    } catch (err) {
        console.error(err);
        showToast("Terjadi kesalahan jaringan", 'error');
    } finally {
        document.getElementById('btnRegisterFace').textContent = 'Mulai Rekam Wajah (30 Frame)';
        checkFormValid();
    }
}

