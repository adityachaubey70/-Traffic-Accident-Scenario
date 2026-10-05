// Browser side: forms, GPS, camera/mic, offline queue. All rules are enforced again in app.py.
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let me = null, dev = null, photos = [], audio = null, tt;

const toast = m => { const t = $('#toast'); t.textContent = m; t.classList.add('show'); clearTimeout(tt); tt = setTimeout(() => t.classList.remove('show'), 3500); };
const online = () => navigator.onLine && !$('#sim').checked;
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : Date.now() + '-' + Math.random().toString(36).slice(2));
const getQ = () => { try { return JSON.parse(localStorage.getItem('tas_queue') || '[]'); } catch { return []; } };
const setQ = q => { try { localStorage.setItem('tas_queue', JSON.stringify(q)); } catch { toast('Browser storage full'); } };

async function api(url, opt = {}) {
  try {
    const r = await fetch(url, opt);
    let d = {}; try { d = await r.json(); } catch {}
    return { ok: r.ok, status: r.status, d };
  } catch { return { ok: false, status: 0, net: true, d: {} }; }
}
const post = (url, body) => api(url, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {}) });

/* ---- login ---- */
$('#loginBtn').onclick = async () => {
  const r = await post('/api/login', { username: $('#u').value.trim(), password: $('#p').value });
  r.ok ? start(r.d) : toast(r.d.error || 'Login failed');
};
$('#out').onclick = async () => { await post('/api/logout'); location.reload(); };
function start(u) {
  me = u; $('#login').hidden = true; $('#app').hidden = false; $('#bar').hidden = false;
  $('#me').textContent = u.user + ' (' + u.role + ')'; setNow(); refresh(); flush();
}
document.querySelectorAll('nav button').forEach(b => b.onclick = () => {
  document.querySelectorAll('nav button').forEach(x => x.classList.toggle('on', x === b));
  ['rep', 'list', 'aud'].forEach(s => $('#' + s).hidden = s !== b.dataset.t);
  refresh();
});

/* ---- capture helpers ---- */
$('#gpsBtn').onclick = () => {
  if (!navigator.geolocation) return toast('GPS not supported. Enter coordinates manually.');
  navigator.geolocation.getCurrentPosition(p => {
    dev = { lat: p.coords.latitude, lng: p.coords.longitude };
    $('#lat').value = dev.lat.toFixed(5); $('#lng').value = dev.lng.toFixed(5); toast('Location captured');
  }, () => { dev = null; toast('GPS is off or denied. Enter coordinates manually.'); }, { timeout: 8000 });
};
$('#demoBtn').onclick = () => { $('#lat').value = '28.6139'; $('#lng').value = '77.2090'; };
const comp = f => new Promise((ok, no) => {   // compress photo before upload
  const u = URL.createObjectURL(f), i = new Image();
  i.onload = () => {
    const k = Math.min(1, 800 / Math.max(i.width, i.height)), c = document.createElement('canvas');
    c.width = i.width * k; c.height = i.height * k; c.getContext('2d').drawImage(i, 0, 0, c.width, c.height);
    URL.revokeObjectURL(u); ok(c.toDataURL('image/jpeg', .6));
  };
  i.onerror = () => no(); i.src = u;
});
$('#ph').onchange = async e => {
  for (const f of e.target.files) {
    if (!f.type.startsWith('image/')) { toast('Rejected: ' + f.name + ' is not an image'); continue; }
    if (photos.length >= 2) { toast('Maximum 2 photos'); break; }
    try { photos.push(await comp(f)); } catch { toast('Rejected: ' + f.name + ' is not a valid image'); }
  }
  e.target.value = ''; prev();
};
function prev() {
  $('#pv').innerHTML = photos.map(s => `<img src="${s}" alt="Accident photo">`).join('') + (audio ? `<audio controls src="${audio}"></audio>` : '');
}
$('#rb').onclick = async () => {
  try {
    const s = await navigator.mediaDevices.getUserMedia({ audio: true }), m = new MediaRecorder(s), ch = [], b = $('#rb');
    m.ondataavailable = e => ch.push(e.data);
    m.onstop = () => {
      s.getTracks().forEach(t => t.stop());
      const fr = new FileReader();
      fr.onload = () => { audio = fr.result; b.textContent = '🎤 Re-record 10 s note'; b.disabled = false; prev(); };
      fr.readAsDataURL(new Blob(ch, { type: m.mimeType }));
    };
    m.start(); let n = 10; b.disabled = true; b.textContent = 'Recording... 10s';
    const t = setInterval(() => { n--; if (n <= 0) { clearInterval(t); m.stop(); } else b.textContent = 'Recording... ' + n + 's'; }, 1000);
  } catch { toast('Microphone unavailable or permission denied'); }
};
function setNow() { const n = new Date(); n.setMinutes(n.getMinutes() - n.getTimezoneOffset()); $('#when').value = n.toISOString().slice(0, 16); }

/* ---- send / offline queue ---- */
async function send(item) {
  if (!online()) return { net: true };
  const fd = new FormData();
  ['cid', 'when', 'lat', 'lng', 'severity', 'description', 'device_lat', 'device_lng', 'confirm_far']
    .forEach(k => item[k] != null && fd.append(k, item[k]));
  for (const [i, u] of item.photos.entries()) fd.append('photos', await (await fetch(u)).blob(), `p${i}.jpg`);
  if (item.audio) fd.append('audio', await (await fetch(item.audio)).blob(), 'note.webm');
  return api('/api/reports', { method: 'POST', body: fd });
}
$('#submitBtn').onclick = async () => {
  const when = $('#when').value, lat = parseFloat($('#lat').value), lng = parseFloat($('#lng').value);
  if (!when || new Date(when) > new Date()) return toast('Invalid date');
  if (isNaN(lat) || isNaN(lng)) return toast('Location required. Turn GPS on or enter coordinates.');
  const item = { cid: uid(), when: new Date(when).toISOString(), lat, lng, severity: $('#sev').value,
    description: $('#desc').value.trim(), device_lat: dev ? dev.lat : null, device_lng: dev ? dev.lng : null,
    photos: photos.slice(), audio };
  let r = await send(item);
  if (r.status === 409 && r.d.warning) {
    if (!confirm(r.d.warning + ' Submit anyway?')) return;
    item.confirm_far = '1'; r = await send(item);
  }
  if (r.net) { setQ([...getQ(), item]); toast('Saved offline. Will auto-sync when online.'); }
  else if (r.ok) toast(r.d.merged ? `Merged into incident #${r.d.id}` : `Reported: incident #${r.d.id}`);
  else return toast(r.d.error || 'Submit failed');
  ['#lat', '#lng', '#desc'].forEach(i => $(i).value = ''); photos = []; audio = null; setNow(); prev(); refresh();
};
async function flush() {
  if (!online() || !me) return;
  const q = getQ(); let n = 0;
  while (q.length) {
    let r = await send(q[0]);
    if (r.status === 409) { q[0].confirm_far = '1'; r = await send(q[0]); }  // flagged as suspicious on the server
    if (r.net || r.status === 401) break;                                    // keep it queued, try again later
    if (r.ok) n++; else toast('Dropped invalid queued report: ' + (r.d.error || r.status));
    q.shift(); setQ(q);
  }
  if (n) toast(n + ' offline report(s) synced');
  refresh();
}
$('#sim').onchange = () => { refresh(); flush(); };
addEventListener('online', flush); addEventListener('offline', refresh);

/* ---- lists ---- */
const card = r => `<article class="card"><div class="row"><b>#${r.id}</b><span class="b ${r.severity === 'High' ? 'hi' : ''}">${esc(r.severity)}</span><span class="b">${esc(r.status)}</span>${r.suspicious ? '<span class="b hi">Suspicious</span>' : ''}</div>
<p class="mu">${new Date(r.happened).toLocaleString()} · ${r.lat.toFixed(5)}, ${r.lng.toFixed(5)} · ${r.reporters.length} reporter(s): ${esc(r.reporters.map(p => p.name).join(', '))}</p>
<p>${esc(r.description) || '<i>No description</i>'}</p>
<div class="pv">${r.photos.map(n => `<img src="/uploads/${esc(n)}" alt="Accident photo">`).join('')}${r.audio.map(n => `<audio controls src="/uploads/${esc(n)}"></audio>`).join('')}</div>
${r.alerts.map(x => `<p class="mu">🚨 ${esc(x)}</p>`).join('')}
<div class="row"><button onclick="approve(${r.id})">Approve</button><button class="dg" onclick="del(${r.id})">Delete</button></div></article>`;
async function refresh() {
  $('#net').textContent = online() ? 'Online' : 'Offline';
  if (!me) return;
  const r = await api('/api/reports');
  if (r.ok) $('#list').innerHTML = (getQ().length ? `<p class="warn">${getQ().length} report(s) waiting to sync</p>` : '') + (r.d.map(card).join('') || '<p class="mu">No reports to show.</p>');
  if (me.role !== 'admin') { $('#aud').innerHTML = '<p class="mu">Audit log is visible to Admin only.</p>'; return; }
  const a = await api('/api/audit');
  if (a.ok) $('#aud').innerHTML = `<div class="tw card"><table><tr><th>Time (UTC)</th><th>Who</th><th>Role</th><th>Action</th><th>Ref</th><th>Note</th></tr>${a.d.map(e => `<tr><td>${esc(e.ts)}</td><td>${esc(e.who)}</td><td>${esc(e.role)}</td><td>${esc(e.action)}</td><td>${esc(e.ref)}</td><td>${esc(e.note)}</td></tr>`).join('')}</table></div><p class="mu">Append-only: database triggers block edits and deletes of log rows.</p>`;
}
async function act(url, method, okMsg) { const r = await api(url, { method }); toast(r.ok ? okMsg : (r.d.error || 'Failed')); refresh(); }
const approve = id => act(`/api/reports/${id}/approve`, 'POST', 'Approved');
const del = id => confirm('Delete report #' + id + '? The audit log keeps the record.') && act(`/api/reports/${id}`, 'DELETE', 'Deleted');

api('/api/me').then(r => r.ok && start(r.d));
