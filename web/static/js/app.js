/* OPI Music Player - Frontend */
'use strict';

const API = '/api';

// ────────── HTTP ──────────

async function api(method, path, body) {
  const opt = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opt.body = JSON.stringify(body);
  let resp;
  try {
    resp = await fetch(API + path, opt);
  } catch (e) {
    toast('网络错误: ' + e.message, 'error');
    throw e;
  }
  let data;
  try { data = await resp.json(); } catch { data = { code: -1, msg: 'invalid json' }; }
  if (data.code !== 0) {
    toast(data.msg || '请求失败', 'error');
    const err = new Error(data.msg);
    err.code = data.code;
    throw err;
  }
  return data.data;
}

// ────────── 工具 ──────────

function $(id) { return document.getElementById(id); }
function el(tag, attrs = {}, children = []) {
  const e = document.createElement(tag);
  for (const k in attrs) {
    if (k === 'class') e.className = attrs[k];
    else if (k === 'html') e.innerHTML = attrs[k];
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), attrs[k]);
    else e.setAttribute(k, attrs[k]);
  }
  for (const c of [].concat(children)) {
    if (c == null) continue;
    e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return e;
}
function toast(msg, kind = 'ok') {
  const t = $('toast');
  t.className = 'toast ' + kind;
  t.textContent = msg;
  t.hidden = false;
  setTimeout(() => (t.hidden = true), 2400);
}

// ────────── 状态轮询 ──────────

let pollTimer = null;
async function refreshStatus() {
  try {
    const s = await api('GET', '/status');
    const stateEl = $('state');
    stateEl.textContent = s.player;
    stateEl.className = 'state ' + s.player;
    const now = s.current ? (s.current.title || s.current.url) : '无播放';
    $('now').textContent = now;
    $('volume').value = s.volume;
    $('volume-value').textContent = s.volume;
  } catch {}
}
function startPolling() {
  refreshStatus();
  pollTimer = setInterval(refreshStatus, 3000);
}

// ────────── 控制按钮 ──────────

$('btn-pause').addEventListener('click', () => api('POST', '/player/pause').then(refreshStatus));
$('btn-resume').addEventListener('click', () => api('POST', '/player/play').then(refreshStatus));
$('btn-stop').addEventListener('click', () => api('POST', '/player/stop').then(refreshStatus));
$('btn-next').addEventListener('click', () => api('POST', '/player/next').then(refreshStatus));
$('btn-prev').addEventListener('click', () => api('POST', '/player/prev').then(refreshStatus));
let volDebounce = null;
$('volume').addEventListener('input', (e) => {
  $('volume-value').textContent = e.target.value;
  clearTimeout(volDebounce);
  volDebounce = setTimeout(() => {
    api('POST', '/player/volume', { value: parseInt(e.target.value, 10) }).catch(() => {});
  }, 200);
});

// ────────── 音乐源列表 ──────────

async function loadSources() {
  const list = await api('GET', '/sources');
  renderSources(list);
}

function renderSources(items) {
  const box = $('source-list');
  box.innerHTML = '';
  if (items.length === 0) {
    box.appendChild(el('div', { class: 'meta' }, '暂无音乐源，点击右上角"新增"添加。'));
    return;
  }
  for (const it of items) {
    const card = el('div', { class: 'source-card' + (it.enabled ? '' : ' disabled') }, [
      el('div', { class: 'name' }, [
        el('span', { class: 'badge' }, it.type),
        ' ' + it.name,
      ]),
      el('div', { class: 'meta' }, it.target),
      el('div', { class: 'kw' }, it.keywords.map((k) => el('span', {}, k))),
      el('div', { class: 'meta' }, it.description || ''),
      el('div', { class: 'actions' }, [
        el('button', { class: 'btn small primary', onclick: () => playSource(it) }, '▶ 播放'),
        el('button', { class: 'btn small', onclick: () => openEdit(it) }, '✏ 编辑'),
        el('button', { class: 'btn small danger', onclick: () => deleteSource(it) }, '🗑 删除'),
      ]),
    ]);
    box.appendChild(card);
  }
}

async function playSource(it) {
  try {
    await api('POST', '/player/play/' + it.id, { shuffle: it.shuffle });
    toast('已开始播放: ' + it.name);
    refreshStatus();
  } catch {}
}

async function deleteSource(it) {
  if (!confirm('确定要删除音乐源 "' + it.name + '" 吗？')) return;
  await api('DELETE', '/sources/' + it.id);
  toast('已删除');
  loadSources();
}

// ────────── 新增 / 编辑 ──────────

$('btn-new').addEventListener('click', () => openEdit(null));
$('modal-close').addEventListener('click', closeModal);
$('btn-cancel').addEventListener('click', closeModal);

function openEdit(it) {
  $('modal-title').textContent = it ? '编辑音乐源' : '新增音乐源';
  $('f-id').value = it ? it.id : '';
  $('f-name').value = it ? it.name : '';
  $('f-type').value = it ? it.type : 'local';
  $('f-target').value = it ? it.target : '';
  $('f-keywords').value = it ? it.keywords.join(',') : '';
  $('f-description').value = it ? it.description : '';
  $('f-enabled').checked = it ? it.enabled : true;
  $('f-recursive').checked = it ? it.recursive : true;
  $('f-shuffle').checked = it ? it.shuffle : false;
  $('f-format').value = it ? (it.format_filter || []).join(',') : 'mp3,wav,flac,m4a,ogg';
  updateTargetHint();
  $('modal').hidden = false;
}
function closeModal() {
  $('modal').hidden = true;
}
$('f-type').addEventListener('change', updateTargetHint);
function updateTargetHint() {
  const t = $('f-type').value;
  $('f-target-label').firstChild.nodeValue =
    t === 'stream' ? '流 URL ' : t === 'playlist' ? 'M3U/PLS 路径或 URL ' : '本地目录路径 ';
}
$('source-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const id = $('f-id').value;
  const payload = {
    name: $('f-name').value.trim(),
    type: $('f-type').value,
    target: $('f-target').value.trim(),
    keywords: $('f-keywords').value.split(',').map((s) => s.trim()).filter(Boolean),
    description: $('f-description').value.trim(),
    enabled: $('f-enabled').checked,
    recursive: $('f-recursive').checked,
    shuffle: $('f-shuffle').checked,
    format_filter: $('f-format').value.split(',').map((s) => s.trim().toLowerCase()).filter(Boolean),
  };
  if (payload.keywords.length === 0) {
    toast('请至少填写一个语音关键字', 'error');
    return;
  }
  try {
    if (id) {
      await api('PUT', '/sources/' + id, payload);
      toast('已更新');
    } else {
      await api('POST', '/sources', payload);
      toast('已新增');
    }
    closeModal();
    loadSources();
  } catch {}
});

// ────────── 日志 ──────────

async function refreshLogs() {
  try {
    const d = await api('GET', '/logs?lines=200');
    $('logs').textContent = (d.lines || []).join('\n');
  } catch {}
}
setInterval(refreshLogs, 5000);

// ────────── 启动 ──────────

loadSources().then(startPolling).catch(startPolling);
