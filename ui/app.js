// OpenClaw Timekeeper - web UI controller

const API = '/api';
const POLL_TABS = new Set(['status', 'tasks', 'wakeups']);
const POLL_MS = 2000;

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];

function escHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

async function api(path, opts = {}) {
  const init = {
    headers: { 'Content-Type': 'application/json' },
    method: opts.method || 'GET',
  };
  if (opts.body !== undefined) init.body = JSON.stringify(opts.body);
  const r = await fetch(`${API}${path}`, init);
  if (!r.ok) {
    const text = await r.text().catch(() => '');
    throw new Error(`${r.status} ${text}`);
  }
  return r.json();
}

function fmtSecs(s) {
  if (s == null || isNaN(s)) return '-';
  s = Math.max(0, Math.floor(s));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}

function fmtTime(iso) {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleString();
  } catch { return iso; }
}

function setConn(ok, msg) {
  const el = $('#footer-conn');
  if (ok) {
    el.className = 'conn-ok';
    el.innerHTML = '&#9679; CONNECTED';
  } else {
    el.className = 'conn-err';
    el.innerHTML = `&#9679; ${msg || 'DISCONNECTED'}`;
  }
}

// ─── Tab switching ────────────────────────────────────────
function activateTab(name) {
  $$('nav button').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  $$('.tab').forEach(t => t.classList.toggle('active', t.id === `tab-${name}`));
  RENDERERS[name]?.();
}

$$('nav button').forEach(b => {
  b.addEventListener('click', () => activateTab(b.dataset.tab));
});

// ─── STATUS ───────────────────────────────────────────────
async function renderStatus() {
  let s, t;
  try {
    [s, t] = await Promise.all([api('/status'), api('/time')]);
    setConn(true);
  } catch (e) {
    setConn(false, 'API ERR');
    $('#tab-status').innerHTML = `<div class="panel"><h2>ERROR</h2><pre>${escHtml(e.message)}</pre></div>`;
    return;
  }

  $('#quick-status').innerHTML =
    `<span class="dot ${s.ok ? 'ok' : 'err'}"></span>${escHtml(t.time_24h)} &nbsp; ${escHtml(t.day_of_week)}`;

  $('#tab-status').innerHTML = `
    <div class="panel">
      <h2>SYSTEM</h2>
      <div class="kv">
        <div class="k">Daemon</div><div class="v"><span class="dot ${s.ok ? 'ok' : 'err'}"></span>${s.ok ? 'RUNNING' : 'DOWN'}</div>
        <div class="k">Uptime</div><div class="v">${fmtSecs(s.uptime_seconds)}</div>
        <div class="k">Active tasks</div><div class="v">${s.active_tasks} / ${s.total_tasks} total</div>
        <div class="k">Pending wakeups</div><div class="v">${s.pending_wakeups}</div>
        <div class="k">Telegram</div><div class="v"><span class="dot ${s.telegram_configured ? 'ok' : 'warn'}"></span>${s.telegram_configured ? 'CONFIGURED' : 'NOT CONFIGURED'}</div>
        <div class="k">Timezone</div><div class="v">${escHtml(s.timezone || '-')}</div>
      </div>
    </div>
    <div class="panel">
      <h2>TIME</h2>
      <div class="kv">
        <div class="k">Date</div><div class="v">${escHtml(t.date)}</div>
        <div class="k">Time (24h)</div><div class="v">${escHtml(t.time_24h)}</div>
        <div class="k">Day</div><div class="v">${escHtml(t.day_of_week)}</div>
        <div class="k">Timezone</div><div class="v">${escHtml(t.timezone)}</div>
        <div class="k">ISO</div><div class="v">${escHtml(t.iso)}</div>
        <div class="k">Unix</div><div class="v">${t.unix}</div>
      </div>
    </div>
  `;
}

// ─── TASKS ────────────────────────────────────────────────
async function renderTasks() {
  let data;
  try {
    data = await api('/tasks?status=all');
    setConn(true);
  } catch (e) {
    setConn(false, 'API ERR');
    return;
  }

  const active = data.tasks.filter(t => t.status === 'active');
  const completed = data.tasks.filter(t => t.status === 'completed');

  const taskRow = (t) => {
    const isActive = t.status === 'active';
    return `
      <tr>
        <td><code>${escHtml(t.id)}</code></td>
        <td>${escHtml(t.name)}</td>
        <td>${fmtTime(t.started_at)}</td>
        <td>${fmtSecs(t.elapsed_seconds)}</td>
        <td>${isActive ? fmtSecs(t.seconds_until_ttl) : (t.total_elapsed_seconds != null ? fmtSecs(t.total_elapsed_seconds) : '-')}</td>
        <td>
          ${isActive ? `<button class="action" onclick="hbTask('${t.id}')">HEARTBEAT</button>
          <button class="action primary" onclick="completeTask('${t.id}')">COMPLETE</button>` : ''}
          <button class="action danger" onclick="deleteTask('${t.id}')">DELETE</button>
        </td>
      </tr>
    `;
  };

  $('#tab-tasks').innerHTML = `
    <div class="panel">
      <h2>NEW TASK</h2>
      <div class="row">
        <div>
          <label>Name</label>
          <input id="new-task-name" placeholder="e.g. Refactor auth module">
        </div>
        <div>
          <label>TTL seconds (default 3600)</label>
          <input id="new-task-ttl" type="number" placeholder="3600">
        </div>
      </div>
      <label>Description (optional)</label>
      <input id="new-task-desc" placeholder="Longer description / goal">
      <button class="action primary" onclick="startTask()">START TASK</button>
    </div>

    <div class="panel">
      <h2>ACTIVE (${active.length})</h2>
      ${active.length ? `
        <table>
          <thead><tr><th>ID</th><th>NAME</th><th>STARTED</th><th>ELAPSED</th><th>TTL LEFT</th><th>ACTIONS</th></tr></thead>
          <tbody>${active.map(taskRow).join('')}</tbody>
        </table>
      ` : '<p class="hint">No active tasks.</p>'}
    </div>

    <div class="panel">
      <h2>COMPLETED (${completed.length})</h2>
      ${completed.length ? `
        <table>
          <thead><tr><th>ID</th><th>NAME</th><th>STARTED</th><th>ELAPSED</th><th>TOTAL</th><th>ACTIONS</th></tr></thead>
          <tbody>${completed.map(taskRow).join('')}</tbody>
        </table>
      ` : '<p class="hint">No completed tasks.</p>'}
    </div>
  `;
}

window.startTask = async () => {
  const name = $('#new-task-name').value.trim();
  if (!name) { alert('Name required'); return; }
  const body = { name };
  const desc = $('#new-task-desc').value.trim();
  if (desc) body.description = desc;
  const ttl = parseInt($('#new-task-ttl').value);
  if (ttl > 0) body.ttl_seconds = ttl;
  try {
    await api('/tasks', { method: 'POST', body });
    renderTasks();
  } catch (e) { alert(e.message); }
};

window.hbTask = async (id) => {
  const note = prompt('Progress note (optional):');
  const body = {};
  if (note) body.progress_note = note;
  try {
    await api(`/tasks/${id}/heartbeat`, { method: 'POST', body });
    renderTasks();
  } catch (e) { alert(e.message); }
};

window.completeTask = async (id) => {
  const result = prompt('Result summary (optional):');
  const body = {};
  if (result) body.result = result;
  try {
    await api(`/tasks/${id}/complete`, { method: 'POST', body });
    renderTasks();
  } catch (e) { alert(e.message); }
};

window.deleteTask = async (id) => {
  if (!confirm(`Delete task ${id}?`)) return;
  try {
    await api(`/tasks/${id}`, { method: 'DELETE' });
    renderTasks();
  } catch (e) { alert(e.message); }
};

// ─── WAKEUPS ──────────────────────────────────────────────
async function renderWakeups() {
  let data;
  try {
    data = await api('/wakeups?include_fired=true');
    setConn(true);
  } catch (e) {
    setConn(false, 'API ERR');
    return;
  }

  const pending = data.wakeups.filter(w => !w.fired);
  const fired = data.wakeups.filter(w => w.fired).slice(-30).reverse();

  $('#tab-wakeups').innerHTML = `
    <div class="panel">
      <h2>SCHEDULE WAKEUP</h2>
      <div class="row">
        <div>
          <label>In seconds</label>
          <input id="wk-secs" type="number" min="1" placeholder="60">
        </div>
        <div>
          <label>Bind to task ID (optional)</label>
          <input id="wk-task" placeholder="e.g. ab12cd34">
        </div>
      </div>
      <label>Message (delivered via Telegram)</label>
      <input id="wk-msg" placeholder="e.g. Resume cleanup of auth module">
      <button class="action primary" onclick="schedWakeup()">SCHEDULE</button>
      <p class="hint">Test wakeup: schedule 5s with any message — telegram message should arrive.</p>
    </div>

    <div class="panel">
      <h2>PENDING (${pending.length})</h2>
      ${pending.length ? `
        <table>
          <thead><tr><th>ID</th><th>FIRES IN</th><th>FIRES AT</th><th>MESSAGE</th><th>TASK</th><th>ACTIONS</th></tr></thead>
          <tbody>${pending.map(w => `
            <tr>
              <td><code>${escHtml(w.id)}</code></td>
              <td>${fmtSecs(w.seconds_until_fire)}</td>
              <td>${fmtTime(w.fire_at)}</td>
              <td>${escHtml(w.message)}</td>
              <td>${w.task_id ? `<code>${escHtml(w.task_id)}</code>` : '-'}</td>
              <td><button class="action danger" onclick="cancelWakeup('${w.id}')">CANCEL</button></td>
            </tr>
          `).join('')}</tbody>
        </table>
      ` : '<p class="hint">No pending wakeups.</p>'}
    </div>

    <div class="panel">
      <h2>RECENT FIRED (${fired.length})</h2>
      ${fired.length ? `
        <table>
          <thead><tr><th>ID</th><th>FIRED AT</th><th>MESSAGE</th><th>TELEGRAM</th></tr></thead>
          <tbody>${fired.map(w => `
            <tr>
              <td><code>${escHtml(w.id)}</code></td>
              <td>${fmtTime(w.fired_at)}</td>
              <td>${escHtml(w.message)}</td>
              <td>${w.send_result?.sent
                ? '<span class="dot ok"></span>SENT'
                : `<span class="dot err"></span>${escHtml(w.send_result?.reason || 'FAIL')}`}</td>
            </tr>
          `).join('')}</tbody>
        </table>
      ` : '<p class="hint">No fired wakeups yet.</p>'}
    </div>
  `;
}

window.schedWakeup = async () => {
  const secs = parseInt($('#wk-secs').value);
  const msg = $('#wk-msg').value.trim();
  if (!secs || !msg) { alert('Seconds and message required'); return; }
  const body = { in_seconds: secs, message: msg };
  const tid = $('#wk-task').value.trim();
  if (tid) body.task_id = tid;
  try {
    await api('/wakeups', { method: 'POST', body });
    $('#wk-secs').value = '';
    $('#wk-msg').value = '';
    $('#wk-task').value = '';
    renderWakeups();
  } catch (e) { alert(e.message); }
};

window.cancelWakeup = async (id) => {
  if (!confirm(`Cancel wakeup ${id}?`)) return;
  try {
    await api(`/wakeups/${id}`, { method: 'DELETE' });
    renderWakeups();
  } catch (e) { alert(e.message); }
};

// ─── SETTINGS ─────────────────────────────────────────────
async function renderSettings() {
  let cfg;
  try {
    cfg = await api('/config');
    setConn(true);
  } catch (e) {
    setConn(false, 'API ERR');
    return;
  }

  const fields = Object.entries(cfg).map(([k, v]) => {
    const isNum = typeof v === 'number';
    const isSecret = k.toLowerCase().includes('token');
    const inputType = isNum ? 'number' : (isSecret ? 'password' : 'text');
    return `
      <label>${escHtml(k)}</label>
      <input data-key="${escHtml(k)}" value="${escHtml(v)}" type="${inputType}">
    `;
  }).join('');

  $('#tab-settings').innerHTML = `
    <div class="panel">
      <h2>CONFIG</h2>
      <p class="hint">Saved to ~/.openclaw/timekeeper/config.json. Telegram changes apply immediately on next wakeup tick. Host/port changes require a daemon restart.</p>
      ${fields}
      <button class="action primary" onclick="saveSettings()">SAVE</button>
      <button class="action" onclick="renderSettings()">RELOAD</button>
    </div>
  `;
}

window.saveSettings = async () => {
  const newCfg = {};
  $$('#tab-settings input').forEach(i => {
    const k = i.dataset.key;
    let v = i.value;
    if (i.type === 'number') v = v === '' ? 0 : (parseInt(v) || 0);
    newCfg[k] = v;
  });
  try {
    await api('/config', { method: 'PUT', body: newCfg });
    alert('Saved.');
    renderSettings();
  } catch (e) { alert('Save failed: ' + e.message); }
};

// ─── LOG ──────────────────────────────────────────────────
async function renderLog() {
  let data;
  try {
    data = await api('/history?limit=200');
    setConn(true);
  } catch (e) {
    setConn(false, 'API ERR');
    return;
  }
  const lines = data.events.slice().reverse().map(e => {
    const ts = e.at || '';
    const evt = e.event || '?';
    const rest = { ...e };
    delete rest.at; delete rest.event;
    return `${ts}  [${evt.padEnd(20)}]  ${JSON.stringify(rest)}`;
  });
  $('#tab-log').innerHTML = `
    <div class="panel">
      <h2>EVENT LOG (last ${data.events.length})</h2>
      <button class="action" onclick="renderLog()">REFRESH</button>
      <pre>${lines.length ? escHtml(lines.join('\n')) : '(no events yet)'}</pre>
    </div>
  `;
}

// ─── Renderer registry & poll loop ────────────────────────
const RENDERERS = {
  status: renderStatus,
  tasks: renderTasks,
  wakeups: renderWakeups,
  settings: renderSettings,
  log: renderLog,
};

setInterval(() => {
  const tab = $('nav button.active')?.dataset.tab;
  if (POLL_TABS.has(tab)) RENDERERS[tab]?.();
}, POLL_MS);

activateTab('status');
