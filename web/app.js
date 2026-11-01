'use strict';
// Crewroom window. Column 1: projects. Column 2: the project's room, channels and requests. Column 3: conversation.

const $ = (sel) => document.querySelector(sel);
const ICON = (name) => `assets/icon-${name}.png`;
const OPEN = ['held', 'asked', 'queued', 'working'];
const state = {
  members: {}, requests: new Map(), messages: [], last: 0,
  projects: [], sessions: [], project: load('project', null), reqFilter: load('reqFilter', 'open'),
  view: { type: 'room' }, to: 'team', transcriptSig: '', ready: false, cleared: {}, showOlder: new Set(),
};

marked.setOptions({ gfm: true, breaks: false });

// ---------- small helpers ----------
function load(key, fallback) { try { return JSON.parse(localStorage.getItem('tc.' + key)) ?? fallback; } catch { return fallback; } }
function save(key, value) { try { localStorage.setItem('tc.' + key, JSON.stringify(value)); } catch { /* private mode */ } }
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) node.append(c instanceof Node ? c : String(c));
  return node;
}
async function api(path, body) {
  const opts = body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {};
  const res = await fetch('/api/' + path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
function toast(text, error) {
  const box = $('#toasts');
  const t = el('div', { class: 'toast' + (error ? ' error' : '') }, text);
  box.append(t);
  // Open dialogs sit in the browser's top layer, above everything else on the page. The toast box is a popover, which
  // lives in that layer too; showing it again puts it on top of whatever dialog is open now.
  if (box.showPopover) { if (box.matches(':popover-open')) box.hidePopover(); box.showPopover(); }
  setTimeout(() => { t.remove(); if (!box.children.length && box.hidePopover && box.matches(':popover-open')) box.hidePopover(); }, error ? 6000 : 3200);
}
async function act(body, okText) {
  try { const r = await api('open', body); toast(okText || r.message); } catch (e) { toast(e.message, true); }
}
const member = (id) => state.members[id] || { name: id, role: '', color: '#888' };
const projectOf = (key) => state.projects.find((p) => p.key === key);
const APP_IDS = ['antigravity', 'cursor', 'claude', 'codex'];  // longest first: ids are "<app>" or "<app>-<name>"
const APP_NAMES = { claude: 'Claude', codex: 'Codex', cursor: 'Cursor', antigravity: 'Antigravity' };
const appOf = (id) => member(id).app || APP_IDS.find((a) => String(id) === a || String(id).startsWith(a + '-')) || 'human';
const appInfo = (app) => (setupInfo && (setupInfo.apps || []).find((a) => a.id === app)) || { id: app, name: APP_NAMES[app] || app, shell: app !== 'codex', liveNotes: app === 'claude' || app === 'codex' };
const teamOf = (key) => (key && state.teams && state.teams[key]) || ['claude', 'codex'];
const CHANNEL = { general: 'General', discussion: 'Discussion' };
const tint = (hue) => (hue ? `filter:hue-rotate(${hue}deg)` : null);
function dotFor(id) { return el('span', { class: 'dot ' + appOf(id), style: tint(member(id).hue) }); }
function avatar(id, small, hue) {
  const m = member(id);
  if (m.avatar) return el('img', { class: 'avatar' + (small ? ' sm' : ''), src: m.avatar, alt: m.name, title: m.name, style: tint(hue ?? m.hue) });
  return el('div', { class: 'avatar' + (small ? ' sm' : ''), style: `background:${m.color}`, title: m.name }, m.name[0]);
}
function btn(icon, label, onclick, extra = '') {
  return el('button', { class: 'btn ' + extra, type: 'button', onclick }, icon ? el('img', { src: ICON(icon), alt: '' }) : null, label);
}
const time = (ts) => ts ? new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
function day(ts) {
  const d = new Date(ts), today = new Date(), y = new Date();
  y.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return 'Today';
  if (d.toDateString() === y.toDateString()) return 'Yesterday';
  return d.toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' });
}
function ago(seconds) {
  const s = Date.now() / 1000 - seconds;
  return s < 60 ? 'now' : s < 3600 ? Math.floor(s / 60) + 'm ago' : s < 86400 ? Math.floor(s / 3600) + 'h ago' : Math.floor(s / 86400) + 'd ago';
}
const size = (n) => n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : n > 1024 ? Math.round(n / 1024) + ' KB' : n + ' B';
const STATUS = { held: 'Waiting for you', asked: 'Asked', queued: 'Queued', working: 'Working', done: 'Done', failed: 'Failed', cancelled: 'Cancelled' };
const pill = (s) => el('span', { class: 'pill ' + s }, STATUS[s] || s);

function markdown(text, base) {
  const box = el('div', { class: 'md' });
  box.innerHTML = DOMPurify.sanitize(marked.parse(text || ''), { USE_PROFILES: { html: true } });
  box.querySelectorAll('a').forEach((a) => {
    const href = a.getAttribute('href') || '';
    if (/^(https?:|mailto:)/i.test(href)) { a.target = '_blank'; a.rel = 'noopener noreferrer'; return; }
    if (href.startsWith('#')) return;
    // Links to local files open in File Explorer (only inside your project folders).
    pathLink(a, decodeURIComponent(href.replace(/^file:\/\/\/?/i, '')), base);
  });
  // `film/index.html`, `renders/t0.25.png`, `C:\...\NOTES.md`: file paths in messages are clickable too.
  box.querySelectorAll(':not(pre) > code').forEach((code) => {
    const t = code.textContent.trim();
    if (looksLikePath(t)) { code.classList.add('path-link'); pathLink(code, t, base); }
  });
  highlightMentions(box);
  box.querySelectorAll('pre code').forEach((code) => {
    try { hljs.highlightElement(code); } catch { /* unknown language */ }
    const copy = el('button', { class: 'copy', type: 'button' }, 'Copy');
    copy.onclick = () => { navigator.clipboard.writeText(code.innerText); copy.textContent = 'Copied'; setTimeout(() => (copy.textContent = 'Copy'), 1200); };
    code.parentElement.append(copy);
  });
  return box;
}

function highlightMentions(box) {
  const names = Object.values(state.members || {}).map((m) => m.name).filter(Boolean).sort((a, b) => b.length - a.length);
  if (!names.length) return;
  const re = new RegExp('(^|[^\\w@])@(' + names.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')(?![\\w-])', 'gi');
  const walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT, { acceptNode: (n) => n.parentElement.closest('code,pre,a') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT });
  const nodes = [];
  while (walker.nextNode()) if (walker.currentNode.nodeValue.includes('@')) nodes.push(walker.currentNode);
  for (const n of nodes) {
    const parts = [], s = n.nodeValue;
    let last = 0;
    for (const m of s.matchAll(re)) {
      const at = m.index + m[1].length;
      parts.push(s.slice(last, at), el('span', { class: 'mention' }, '@' + m[2]));
      last = at + 1 + m[2].length;
    }
    if (!parts.length) continue;
    parts.push(s.slice(last));
    n.replaceWith(...parts.filter((x) => x !== ''));
  }
}
function looksLikePath(t) {
  if (!t || t.length > 260 || /[<>|"*?\n]/.test(t) || /^(https?:|--?\w|npm |npx |python |git )/i.test(t)) return false;
  if (/^[a-z]:\\/i.test(t)) return true;
  if (/\s/.test(t)) return false;
  return /[\\/]/.test(t) || /^[\w.@-]+\.[a-z0-9]{1,6}$/i.test(t) && !/^\d+(\.\d+)+$/.test(t);
}
function pathLink(node, href, base) {
  node.title = 'Click: show in folder · Right-click: more';
  const go = (mode) => base ? act({ action: 'link', href, base, mode }) : toast('No folder known for this message', true);
  node.addEventListener('click', (e) => { e.preventDefault(); go('reveal'); });
  node.addEventListener('contextmenu', (e) => contextMenu(e, [
    ['Show in folder', () => go('reveal')],
    ['Open', () => go('open')],
    ['Copy full path', async () => {
      if (!base) return toast('No folder known for this message', true);
      try { const r = await api('open', { action: 'link', href, base, mode: 'path' }); await navigator.clipboard.writeText(r.message); toast('Path copied'); }
      catch (err) { toast(err.message, true); }
    }],
  ]));
}
function contextMenu(e, items) {
  e.preventDefault();
  closeMenu();
  const menu = el('div', { class: 'ctx-menu', id: 'ctx-menu', role: 'menu' }, items.map(([label, fn]) =>
    el('button', { type: 'button', role: 'menuitem', onclick: () => { closeMenu(); fn(); } }, label)));
  document.body.append(menu);
  const { innerWidth: w, innerHeight: h } = window, r = menu.getBoundingClientRect();
  menu.style.left = Math.min(e.clientX, w - r.width - 8) + 'px';
  menu.style.top = Math.min(e.clientY, h - r.height - 8) + 'px';
  menu.querySelector('button').focus();
}
function closeMenu() { document.getElementById('ctx-menu')?.remove(); }
document.addEventListener('click', (e) => { if (!e.target.closest('#ctx-menu')) closeMenu(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenu(); });
window.addEventListener('blur', closeMenu);
const fileMenu = (f) => (e) => contextMenu(e, [
  ['Open', () => act({ action: 'open-file', id: f.id })],
  ['Show in folder', () => act({ action: 'reveal-file', id: f.id })],
  ['Download', () => download(f)],
]);

// ---------- images & files ----------
function openImage(src, file) {
  const lb = $('#lightbox');
  lb.querySelector('img').src = src;
  $('#lightbox-bar').replaceChildren(...(file ? [
    btn('open-app', 'Open', () => act({ action: 'open-file', id: file.id })),
    btn('reveal', 'Show in folder', () => act({ action: 'reveal-file', id: file.id })),
    btn('download', 'Download', () => download(file)),
  ] : []));
  lb.hidden = false;
}
$('#lightbox').addEventListener('click', (e) => { if (!e.target.closest('.lightbox-bar')) $('#lightbox').hidden = true; });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') $('#lightbox').hidden = true; });
function download(f) {
  const a = el('a', { href: `/api/file/${f.id}?download=1`, download: f.name });
  document.body.append(a); a.click(); a.remove();
}
function gallery(items) {
  if (!items.length) return null;
  return el('div', { class: 'gallery' + (items.length === 1 ? ' single' : '') }, items.map((it) =>
    el('figure', { oncontextmenu: it.file ? fileMenu(it.file) : null }, el('img', { src: it.src, loading: 'lazy', alt: it.file ? it.file.name : '', onclick: () => openImage(it.src, it.file) }),
      it.file ? el('figcaption', { title: it.file.name }, it.file.name) : null)));
}
function attachments(files) {
  if (!files || !files.length) return [];
  const images = files.filter((f) => f.mime.startsWith('image/'));
  const others = files.filter((f) => !f.mime.startsWith('image/'));
  const out = [gallery(images.map((f) => ({ src: '/api/file/' + f.id, file: f })))];
  if (others.length) {
    out.push(el('div', { class: 'files' }, others.map((f) => el('div', { class: 'file', oncontextmenu: fileMenu(f) },
      el('div', { class: 'file-icon' }, (f.name.split('.').pop() || 'file').slice(0, 4).toUpperCase()),
      el('div', { style: 'min-width:0;flex:1' }, el('div', { class: 'file-name', title: f.name }, f.name), el('span', { class: 'file-size' }, size(f.size))),
      el('div', { class: 'file-actions' },
        el('button', { class: 'mini', type: 'button', title: 'Open', onclick: () => act({ action: 'open-file', id: f.id }) }, el('img', { src: ICON('open-app'), alt: 'Open' })),
        el('button', { class: 'mini', type: 'button', title: 'Show in folder', onclick: () => act({ action: 'reveal-file', id: f.id }) }, el('img', { src: ICON('reveal'), alt: 'Show in folder' })),
        el('button', { class: 'mini', type: 'button', title: 'Download', onclick: () => download(f) }, el('img', { src: ICON('download'), alt: 'Download' })))))));
  }
  return out.filter(Boolean);
}

// ---------- column 1: projects ----------
function openCount(key) { return [...state.requests.values()].filter((r) => OPEN.includes(r.status) && (!key || r.project === key)).length; }
function renderProjects() {
  $('#all-open').textContent = openCount() || '';
  $('#nav-all').classList.toggle('active', !state.project);
  $('#projects').replaceChildren(...(state.projects.length ? state.projects.map((p) => {
    const open = openCount(p.key);
    const meta = [p.requests && `${p.requests} request${p.requests > 1 ? 's' : ''}`, p.chats && `${p.chats} chat${p.chats > 1 ? 's' : ''}`].filter(Boolean).join(' · ');
    return el('button', { class: 'rail-item' + (p.virtual ? ' virtual' : '') + (state.project === p.key ? ' active' : ''), title: p.root || p.name,
      onclick: () => selectProject(p.key) },
    el('img', { src: ICON('folder'), alt: '' }),
    el('span', { class: 'rail-name' }, p.name, el('span', { class: 'rail-meta' }, meta)),
    el('span', { class: 'badge' }, open ? String(open) : ''));
  }) : [el('div', { class: 'empty' }, 'Loading projects…')]));
}
function renderTeam() {
  const busy = new Set([...state.requests.values()].filter((r) => r.status === 'working').map((r) => r.recipient));
  // Anyone with open work here shows too, even if they aren't on the project's saved team (e.g. plain "cursor").
  const active = [...state.requests.values()].filter((r) => OPEN.includes(r.status) && (!state.project || r.project === state.project))
    .map((r) => r.recipient).filter((id) => appOf(id) !== 'human');
  const ids = ['human', ...new Set([...teamOf(state.project), ...active])];
  $('#team').replaceChildren(...ids.map((id) => [id, member(id)]).map(([id, m]) => el('div', { class: 'member', title: m.role },
    avatar(id, true), el('b', {}, m.name),
    id === 'human' ? null : el('span', { class: 'presence' + (busy.has(id) ? ' busy' : '') }, busy.has(id) ? 'working' : 'free'))));
}
function selectProject(key) {
  state.project = key; save('project', key); renderTeam();
  show({ type: 'room' });
}
$('#nav-all').onclick = () => selectProject(null);

// ---------- column 2: project panel ----------
function renderPanel() {
  const p = projectOf(state.project);
  $('#p-title').replaceChildren(el('img', { src: ICON(p ? 'folder' : 'team-room'), alt: '', style: 'width:20px;height:20px' }), p ? p.name : 'All activity');
  $('#p-path').textContent = p ? (p.root || 'Chats without a single project folder') : 'Every project, newest first';
  $('#p-actions').replaceChildren(...(p ? [
    p.root ? btn('folder', 'Open folder', () => act({ action: 'folder', path: p.root })) : null,
    btn('retry', 'Start fresh', () => startFresh(p)),
  ].filter(Boolean) : []));
  renderTeamCard(p);
  $('#p-room').classList.toggle('active', state.view.type === 'room');
  $('#p-room').querySelector('.row-hint').textContent = p ? 'everything in this project' : 'everything, all projects';
  document.querySelectorAll('.row.chan').forEach((b) => b.classList.toggle('active', state.view.type === 'channel' && state.view.channel === b.dataset.channel));

  // Requests
  document.querySelectorAll('#req-filter button').forEach((b) => b.classList.toggle('on', b.dataset.f === state.reqFilter));
  let reqs = [...state.requests.values()].filter((r) => (!state.project || r.project === state.project) && !requestHidden(r));
  if (state.reqFilter === 'open') reqs = reqs.filter((r) => OPEN.includes(r.status));
  $('#requests').replaceChildren(...(reqs.length ? reqs.map((r) => el('button', {
    class: 'row' + (state.view.type === 'request' && state.view.id === r.id ? ' active' : ''), onclick: () => show({ type: 'request', id: r.id }) },
  dotFor(r.recipient), el('span', { class: 'row-title', title: r.title }, r.title), pill(r.status),
  el('span', { class: 'row-meta' }, `${member(r.sender).name} → ${member(r.recipient).name}`, state.project ? '' : ` · ${(projectOf(r.project) || {}).name || ''}`)))
    : [el('div', { class: 'empty' }, state.reqFilter === 'open' ? 'No open requests. Ask a teammate below.' : 'No requests yet.')]));

}
document.querySelectorAll('#req-filter button').forEach((b) => b.addEventListener('click', () => {
  state.reqFilter = b.dataset.f; save('reqFilter', state.reqFilter); renderPanel();
}));
$('#p-room').onclick = () => show({ type: 'room' });
document.querySelectorAll('.row.chan').forEach((b) => { b.onclick = () => show({ type: 'channel', channel: b.dataset.channel }); });

// ---------- column 3: mailbox feed ----------
function isOld(created, key) {
  const c = state.cleared[key];
  return !!c && created < c && !state.showOlder.has(key);
}
const requestHidden = (r) => !OPEN.includes(r.status) && isOld(r.created, r.project);
function messageProject(m) { return m.request_id ? (state.requests.get(m.request_id) || {}).project : m.project; }
function messageNode(m, inRoom) {
  const req = m.request_id ? state.requests.get(m.request_id) : null;
  const who = member(m.sender);
  const base = req ? req.cwd : (projectOf(m.project) || {}).root;
  const where = !state.project && inRoom && messageProject(m) ? (projectOf(messageProject(m)) || {}).name : null;
  const head = el('div', { class: 'msg-head' }, el('span', { class: 'msg-name' }, who.name),
    el('span', { class: 'msg-time' }, time(m.created)), where ? el('span', { class: 'msg-where' }, '· ' + where) : null);

  if (m.kind === 'request' && req) {
    const card = el('div', { class: 'request-card', title: 'Open this request', onclick: (e) => { if (!e.target.closest('a,button,figure')) show({ type: 'request', id: req.id }); } },
      el('div', { class: 'rc-top' }, el('span', {}, `Request for ${member(req.recipient).name}`), pill(req.status),
        req.status === 'held' ? el('span', { class: 'held-actions' },
          btn('send', 'Send', (e) => { e.stopPropagation(); release(req); }, 'primary'),
          btn('cancel', 'Dismiss', (e) => { e.stopPropagation(); cancel(req, true); }, 'danger')) : null),
      el('div', { class: 'rc-title' }, req.title),
      req.cwd ? el('div', { class: 'rc-folder' }, req.cwd) : null,
      m.body && m.body !== req.title ? markdown(m.body, base) : null,
      ...attachments(m.files));
    return el('div', { class: 'msg ' + m.sender }, avatar(m.sender), el('div', { class: 'msg-body' }, head, card));
  }
  if (['working', 'queued', 'cancelled'].includes(m.kind) || (m.kind === 'note' && !m.files.length)) {
    return el('div', { class: 'status-line' }, avatar(m.sender, true),
      el('span', {}, m.kind === 'working' ? `${who.name} started ` : m.kind === 'cancelled' ? `${who.name} cancelled ` : `${who.name}: ${m.body.replace(/[*`_]/g, '')} `,
        m.kind !== 'note' && req ? el('b', {}, req.title) : null),
      el('span', { class: 'msg-time' }, time(m.created)));
  }
  const bubble = el('div', { class: 'bubble' + (m.kind === 'done' ? ' done-card' : m.kind === 'failed' ? ' failed-card' : '') });
  if (req && (inRoom || m.kind === 'done' || m.kind === 'failed')) {
    const link = el('a', { href: '#', onclick: (e) => { e.preventDefault(); show({ type: 'request', id: req.id }); } }, req.title);
    bubble.append(el('div', { class: 'kind' },
      m.kind === 'done' ? [el('img', { class: 'done-icon', src: ICON('done'), alt: '' }), 'Finished · ', link]
        : m.kind === 'failed' ? ['✕ Could not finish · ', link] : ['Re: ', link]));
  }
  if (m.body) bubble.append(markdown(m.body, base));
  bubble.append(...attachments(m.files));
  return el('div', { class: 'msg ' + m.sender }, avatar(m.sender), el('div', { class: 'msg-body' }, head, bubble));
}
function renderFeed(stick) {
  const feed = $('#feed');
  const atBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80;
  const v = state.view;
  const inProject = (m) => (!state.project || messageProject(m) === state.project) && !isOld(m.created, messageProject(m));
  const list = v.type === 'request' ? state.messages.filter((m) => m.request_id === v.id)
    : v.type === 'channel' ? state.messages.filter((m) => inProject(m) && !m.request_id && (m.channel || 'general') === v.channel)
    : state.messages.filter(inProject);
  const nodes = [];
  const key = state.project;
  if (v.type !== 'request' && key && state.cleared[key]) {
    const older = state.messages.filter((m) => messageProject(m) === key && m.created < state.cleared[key]).length;
    const showing = state.showOlder.has(key);
    nodes.push(el('div', { class: 'fresh-mark' }, el('img', { src: ICON('retry'), alt: '' }),
      `Started fresh ${day(state.cleared[key]).toLowerCase()} at ${time(state.cleared[key])}.`,
      older ? el('button', { type: 'button', class: 'link-btn', onclick: () => {
        showing ? state.showOlder.delete(key) : state.showOlder.add(key); renderPanel(); renderFeed();
      } }, showing ? 'Hide older messages' : `Show ${older} older message${older > 1 ? 's' : ''}`) : null));
  }
  const elsewhere = key && v.type !== 'request' ? state.messages.filter((m) => messageProject(m) !== key).length : 0;
  if (key && v.type !== 'request') {  // say plainly that this is filtered, so a quiet project never looks like a broken app
    nodes.push(el('div', { class: 'filter-bar' }, el('span', {}, `Showing only ${(projectOf(key) || {}).name || 'this project'}.`),
      elsewhere ? el('span', {}, `${elsewhere} message${elsewhere > 1 ? 's' : ''} in other projects.`) : null,
      el('button', { type: 'button', class: 'link-btn', onclick: () => selectProject(null) }, 'Show all activity')));
  }
  let lastDay = '';
  for (const m of list) {
    const d = day(m.created);
    if (d !== lastDay) { nodes.push(el('div', { class: 'day' }, d)); lastDay = d; }
    nodes.push(messageNode(m, v.type !== 'request'));
  }
  if (!list.length) nodes.push(el('div', { class: 'empty', style: 'text-align:center;padding:0 0 60px' },
    el('img', { class: 'empty-art', src: 'assets/empty-state.png', alt: '' }),
    v.type === 'channel' ? `No messages in #${CHANNEL[v.channel]} yet. Say hi below — agents can post here with \`team say --channel ${v.channel}\`.`
      : 'Nothing here yet. Ask a teammate for something below, or tell Claude or Codex to use the team-chat skill.'));
  $('#feed-inner').replaceChildren(...nodes);
  if (stick || atBottom) feed.scrollTop = feed.scrollHeight;
}

// ---------- column 3: a request's work log ----------
// What a member said and did while working on a request, read from Crewroom's own log (not from the agent's app).
const STEP_ICON = { say: 'team-room', tool: 'open-app', image: 'reveal', error: 'cancel' };
async function loadWorkLog(stick) {
  const v = state.view;
  if (v.type !== 'log') return;
  const r = state.requests.get(v.id);
  if (!stick && r && !OPEN.includes(r.status) && state.transcriptSig.startsWith('done:')) return;  // finished: nothing new
  try {
    const steps = await api(`worklog?id=${encodeURIComponent(v.id)}`);
    if (state.view !== v) return;
    const sig = (r && !OPEN.includes(r.status) ? 'done:' : '') + steps.length + ':' + JSON.stringify(steps.at(-1) || '').length;
    if (sig === state.transcriptSig && !stick) return;
    state.transcriptSig = sig;
    const feed = $('#feed');
    const atBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80;
    const who = r ? r.recipient : 'human';
    const nodes = steps.map((s) => s.kind === 'say'
      ? el('div', { class: 'msg ' + appOf(who) }, avatar(who, true), el('div', { class: 'msg-body' }, el('div', { class: 'bubble' }, markdown(s.text, r && r.cwd))))
      : el('div', { class: 'log-step ' + s.kind }, el('img', { src: ICON(STEP_ICON[s.kind] || 'open-app'), alt: '' }),
          el('span', { class: 'log-what' }, s.text), s.detail ? el('code', { class: 'log-detail', title: s.detail }, s.detail) : null));
    if (!steps.length) nodes.push(el('div', { class: 'empty' }, r && OPEN.includes(r.status) ? 'Nothing logged yet. Steps appear here as the member works.' : 'No work was logged for this request.'));
    $('#feed-inner').replaceChildren(...nodes);
    if (stick || atBottom) feed.scrollTop = feed.scrollHeight;
  } catch (e) {
    $('#feed-inner').replaceChildren(el('div', { class: 'empty' }, 'Could not read the work log: ' + e.message));
  }
}

// ---------- views ----------
function headerFor(view) {
  const actions = [];
  const p = projectOf(state.project);
  if (view.type === 'channel') {
    $('#title').textContent = `# ${CHANNEL[view.channel]}${p ? ' · ' + p.name : ''}`;
    $('#subtitle').textContent = view.channel === 'general' ? 'Updates and results for everyone. Free — no agent tokens are used here.'
      : 'Talk ideas through. Free — agents only spend tokens when you ask them for work.';
  } else if (view.type === 'room') {
    $('#title').textContent = p ? `${p.name} · Activity` : 'All activity';
    $('#subtitle').textContent = p ? 'Everything the team said, asked and delivered in this project' : 'Everything your team says, asks and delivers';
  } else if (view.type === 'request') {
    const r = state.requests.get(view.id);
    $('#title').textContent = r ? r.title : 'Request';
    $('#subtitle').replaceChildren(...(r ? [`${member(r.sender).name} asked ${member(r.recipient).name}`, pill(r.status)] : []));
    if (r) {
      if (r.status === 'held') {
        actions.push(btn('send', 'Send', () => release(r), 'primary'));
        actions.push(btn('cancel', 'Dismiss', () => cancel(r, true), 'danger'));
      } else if (OPEN.includes(r.status)) actions.push(btn('cancel', 'Cancel', () => cancel(r), 'danger'));
      else actions.push(btn('retry', 'Try again', () => retry(r)));
      if (r.status !== 'asked' && r.status !== 'held' && appOf(r.recipient) !== 'human')
        actions.push(btn('app-chats', 'Work log', () => show({ type: 'log', id: r.id })));
      if (r.cwd) actions.push(btn('folder', 'Open folder', () => act({ action: 'folder', path: r.cwd })));
    }
  } else if (view.type === 'log') {
    const r = state.requests.get(view.id);
    $('#title').textContent = r ? `Work log · ${r.title}` : 'Work log';
    $('#subtitle').replaceChildren(...(r ? [`What ${member(r.recipient).name} did on this request`, pill(r.status)] : []));
    actions.push(btn('requests', 'Back to the request', () => show({ type: 'request', id: view.id })));
  }
  $('#header-actions').replaceChildren(...actions);
}
async function release(r) {
  try { await api('release', { id: r.id }); toast(`Sent to ${member(r.recipient).name}`); await poll(); show(state.view); } catch (e) { toast(e.message, true); }
}
async function cancel(r, dismiss) {
  if (!dismiss && !confirm(`Cancel "${r.title}"? Files may be left half-changed.`)) return;
  try { await api('cancel', { id: r.id }); toast('Cancelling…'); await poll(); show(state.view); } catch (e) { toast(e.message, true); }
}
async function retry(r) {
  try { const n = await api('retry', { id: r.id }); toast('Sent again'); await poll(); show({ type: 'request', id: n.id }); } catch (e) { toast(e.message, true); }
}
function show(view) {
  state.view = view;
  state.transcriptSig = '';
  const log = view.type === 'log';
  $('#banner').hidden = !log;
  if (log) $('#banner').textContent = 'From Crewroom’s own log of this request: the member’s messages and every step it took. It updates while the member works.';
  $('#composer').hidden = log;
  headerFor(view);  // may add to the banner
  updateComposer();
  renderProjects();
  renderPanel();
  if (log) { $('#feed-inner').replaceChildren(el('div', { class: 'empty' }, 'Loading…')); loadWorkLog(true); }
  else renderFeed(true);
}

// ---------- composer ----------
const text = $('#text');
function renderTo() {
  const ids = teamOf(state.project);
  if (state.to !== 'team' && !ids.includes(state.to)) state.to = 'team';
  $('#to').replaceChildren(el('button', { type: 'button', 'data-to': 'team', class: state.to === 'team' ? 'on' : '' },
    state.view.type === 'channel' ? `# ${CHANNEL[state.view.channel]}` : 'Team'),
  ...ids.map((id) => el('button', { type: 'button', 'data-to': id, class: state.to === id ? 'on' : '', title: member(id).role || '' },
    dotFor(id), 'Ask ' + member(id).name)));
}
function updateComposer() {
  renderTo();
  const inRequest = state.view.type === 'request';
  const asking = !inRequest && state.to !== 'team';
  $('#composer-top').hidden = inRequest;
  $('#ask-fields').hidden = !asking;
  $('#run-wrap').hidden = !asking;
  document.querySelectorAll('#to button').forEach((b) => b.classList.toggle('on', b.dataset.to === state.to));
  const p = projectOf(state.project);
  if (asking && !$('#req-cwd').dataset.touched) $('#req-cwd').value = (p && p.root) || '';
  text.placeholder = inRequest ? 'Reply on this request…' : asking ? `Details for ${member(state.to).name} (optional — Markdown works)`
    : `Message ${state.view.type === 'channel' ? '#' + CHANNEL[state.view.channel] : 'the team'}${p ? ' · ' + p.name : ''}…  (Enter to send · Shift+Enter for a new line)`;
  $('#hint').textContent = asking ? `${member(state.to).name} works on this in its ongoing ${p ? p.name + ' ' : ''}chat and posts the result here.` : '';
}
$('#to').addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  state.to = b.dataset.to; updateComposer(); (state.to === 'team' ? text : $('#req-title')).focus();
});
$('#req-cwd').addEventListener('input', () => { $('#req-cwd').dataset.touched = '1'; });
text.addEventListener('input', () => { text.style.height = 'auto'; text.style.height = Math.min(text.scrollHeight, 220) + 'px'; });
text.addEventListener('keydown', (e) => {
  if (mentionKey(e)) return;
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#composer').requestSubmit(); }
});
// ---------- @mentions: tag a member; a busy one reads it mid-run, a free one gets it as a new request ----------
const pop = $('#mention-pop');
let picks = [], pick = 0;
const busy = (id) => [...state.requests.values()].find((r) => r.recipient === id && r.status === 'working' && (!state.project || r.project === state.project));
function mentionQuery() {
  if (state.view.type === 'request' || state.to !== 'team') return null;
  const m = text.value.slice(0, text.selectionStart).match(/(^|\s)@([\w-]*(?: [\w-]*)?)$/);
  return m ? m[2] : null;
}
function showMentions() {
  const q = mentionQuery();
  const ids = teamOf(state.project);
  picks = q === null ? [] : ids.filter((id) => {
    const n = member(id).name.toLowerCase(), s = q.toLowerCase();
    return n.startsWith(s) || id.toLowerCase().startsWith(s) || n.split(' ').some((w) => w.startsWith(s));
  });
  pop.hidden = !picks.length;
  if (!picks.length) return;
  pick = Math.min(pick, picks.length - 1);
  pop.replaceChildren(...picks.map((id, i) => {
    const job = busy(id);
    return el('button', { type: 'button', role: 'option', class: i === pick ? 'on' : '', 'aria-selected': i === pick ? 'true' : 'false',
      onmousedown: (e) => { e.preventDefault(); insertMention(id); } },
      avatar(id, true), el('span', { class: 'mp-name' }, member(id).name),
      el('span', { class: 'mp-state' + (job ? ' busy' : '') }, job ? (appInfo(appOf(id)).liveNotes ? 'working · reads your note mid-run' : 'working · gets your note right after') : (state.manual?.[state.project] || []).includes(id) ? 'works in its own app · waits in its inbox' : 'free · starts a new request'));
  }));
}
function insertMention(id) {
  const caret = text.selectionStart, before = text.value.slice(0, caret).replace(/@[\w-]*(?: [\w-]*)?$/, ''), after = text.value.slice(caret);
  const tag = '@' + member(id).name + ' ';
  text.value = before + tag + after.replace(/^\s+/, '');
  text.selectionStart = text.selectionEnd = before.length + tag.length;
  pop.hidden = true; picks = [];
  text.focus();
}
function mentionKey(e) {
  if (pop.hidden || !picks.length) return false;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { pick = (pick + (e.key === 'ArrowDown' ? 1 : picks.length - 1)) % picks.length; showMentions(); }
  else if (e.key === 'Enter' || e.key === 'Tab') insertMention(picks[pick]);
  else if (e.key === 'Escape') pop.hidden = true;
  else return false;
  e.preventDefault();
  return true;
}
text.addEventListener('input', showMentions);
text.addEventListener('click', showMentions);
text.addEventListener('blur', () => setTimeout(() => { pop.hidden = true; }, 120));
$('#req-title').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); $('#composer').requestSubmit(); } });
$('#composer').addEventListener('submit', async (e) => {
  e.preventDefault();
  askNotify();
  const body = text.value.trim();
  const send = $('.send');
  send.disabled = true;
  try {
    if (state.view.type === 'request') {
      if (!body) return;
      const sent = await api('say', { body, requestId: state.view.id });
      if (sent.note === 'live') toast(`${member(state.requests.get(state.view.id).recipient).name} reads this mid-run and adapts`);
      if (sent.note === 'after') toast(`${member(state.requests.get(state.view.id).recipient).name} gets this right after the current job`);
      else if (sent.note === 'start') toast('Added to the request before it starts');
    } else if (state.to === 'team') {
      if (!body) return;
      const sent = await api('say', { body, project: state.project, channel: state.view.type === 'channel' ? state.view.channel : 'general' });
      if (sent.routedTo) toast(`${member(sent.routedTo).name} is reading your message`);
      for (const m of sent.mentions || []) {
        const n = member(m.id).name;
        toast(m.how === 'live' ? `${n} is working: reads your note mid-run and adapts`
          : m.how === 'after' ? `${n} is working: gets your note right after this job`
          : m.how === 'inbox' ? `${n} works in its own app: waiting in its inbox` : `${n} is on it: new request started`);
      }
    } else {
      const title = $('#req-title').value.trim() || body.split('\n')[0].slice(0, 120);
      if (!title) { $('#req-title').focus(); toast('Write what you need first', true); return; }
      const req = await api('ask', { to: state.to, title, body, run: $('#run').checked, cwd: $('#req-cwd').value.trim() });
      $('#req-title').value = '';
      delete $('#req-cwd').dataset.touched;
      toast(`Sent to ${member(state.to).name}`);
      await poll();
      if (req.project !== undefined) state.project = req.project;
      show({ type: 'request', id: req.id });
    }
    text.value = ''; text.style.height = 'auto';
    await poll(true);
  } catch (err) {
    toast(err.message, true);
  } finally { send.disabled = false; }
});

// ---------- notifications ----------
function askNotify() { if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission(); }
function notifyDone(r) {
  const label = r.status === 'done' ? 'finished' : 'could not finish';
  toast(`${member(r.recipient).name} ${label}: ${r.title}`, r.status !== 'done');
  if (document.hidden) document.title = `● ${member(r.recipient).name} ${label} · Crewroom`;
  if ('Notification' in window && Notification.permission === 'granted' && document.hidden) {
    const n = new Notification(`${member(r.recipient).name} ${label}`, { body: r.title, icon: 'assets/logo-mark.png' });
    n.onclick = () => { window.focus(); show({ type: 'request', id: r.id }); };
  }
}
window.addEventListener('focus', () => { document.title = 'Crewroom'; });

// ---------- data ----------
async function poll(stick) {
  const data = await api('state?after=' + state.last);
  state.members = data.members;
  state.teams = data.teams || {};
  state.manual = data.manual || {};
  state.cleared = data.cleared || {};
  let changed = false;
  for (const r of data.requests) {
    const before = state.requests.get(r.id);
    if (!before || before.status !== r.status || before.worker_session !== r.worker_session) changed = true;
    if (state.ready && before && before.status !== r.status && (r.status === 'done' || r.status === 'failed')) notifyDone(r);
    state.requests.set(r.id, r);
  }
  state.ready = true;
  const grew = data.messages.length > 0;
  state.messages.push(...data.messages);
  state.last = data.last;
  renderTeam();
  if (changed || grew) { renderProjects(); renderPanel(); if (state.view.type === 'request') headerFor(state.view); }
  if (state.view.type !== 'chat' && (grew || stick || changed)) renderFeed(stick);
}
async function loadSessions() {
  try {
    const data = await api('sessions');
    state.sessions = data.sessions;
    state.projects = data.projects;
    if (state.project && !projectOf(state.project)) state.project = null;
    renderProjects(); renderPanel();
    if (state.view.type === 'room') headerFor(state.view);
  } catch { /* server restarting */ }
}

// ---------- start fresh ----------
function choose(title, textBody, options) {
  return new Promise((resolve) => {
    const dlg = $('#choice');
    $('#choice-title').textContent = title;
    $('#choice-text').replaceChildren(...[].concat(textBody).map((t) => el('p', {}, t)));
    $('#choice-buttons').replaceChildren(...options.map((o) => el('button', { type: 'button', class: 'btn ' + (o.cls || ''),
      onclick: () => { dlg.close(); resolve(o.value); } }, o.label)));
    dlg.onclose = () => resolve(null);
    dlg.showModal();
  });
}
async function startFresh(p) {
  const pick = await choose(`Start fresh in “${p.name}”?`, [
    'Start fresh: older messages and finished requests are hidden (you can show them again), and every team member starts a new chat next time — no old context, fewer tokens.',
    'Delete history: permanently removes this project’s Crewroom messages and requests. Your project files and the chats inside the Claude and Codex apps are not touched.',
  ], [
    { label: 'Cancel', value: null },
    { label: 'Delete history…', value: 'delete', cls: 'danger' },
    { label: 'Start fresh', value: 'fresh', cls: 'primary' },
  ]);
  if (!pick) return;
  if (pick === 'delete' && !confirm(`Permanently delete all Crewroom messages and requests for “${p.name}”? This cannot be undone.`)) return;
  try {
    await api('projects/clear', { key: p.key, mode: pick });
    state.showOlder.delete(p.key);
    if (pick === 'delete') {  // drop the removed messages from the window too
      state.messages = []; state.last = 0;
      for (const [id, r] of state.requests) if (r.project === p.key) state.requests.delete(id);
    }
    await poll(true);
    await loadSessions(true);
    show({ type: 'room' });
    toast(pick === 'fresh' ? 'Fresh start — new chats for every member from now on' : 'History deleted');
  } catch (e) { toast(e.message, true); }
}

// ---------- team setup (per project) ----------
const settingsCache = new Map();
async function projectSettings(key, fresh) {
  if (!fresh && settingsCache.has(key)) return settingsCache.get(key);
  const data = await api('project?key=' + encodeURIComponent(key)).catch(() => ({}));
  settingsCache.set(key, data && data.settings ? data : null);
  return settingsCache.get(key);
}
async function renderTeamCard(p) {
  const card = $('#p-team');
  if (!p || !p.root) { card.hidden = true; return; }
  const saved = await projectSettings(p.key);
  if (state.project !== p.key) return;
  card.hidden = false;
  if (!saved) {
    card.replaceChildren(el('div', { class: 'muted', style: 'font-size:12px' }, 'No team roles yet for this project.'),
      btn('team-room', 'Set up the team', () => openProjectDialog({ existing: p.root, name: p.name })));
    return;
  }
  const st = saved.settings;
  const open = load('teamOpen', false);
  if (!open) {  // compact: one row of faces; click to see roles
    card.replaceChildren(
      el('button', { type: 'button', class: 'team-faces', title: 'Show roles', onclick: () => { save('teamOpen', true); renderTeamCard(p); } },
        ...(st.members || []).map((m) => el('span', { class: 'face', title: `${m.name}: ${(m.roles || []).join('; ')}` }, avatar(m.id, true, m.hue), m.name)),
        el('span', { class: 'face more' }, `▾ roles`)),
      el('div', { class: 'team-actions' }, btn('team-room', 'Edit team', () => openProjectDialog({ edit: saved })),
        st.coordinator ? el('span', { class: 'muted', style: 'font-size:11px' }, `Coordinator: ${member(st.coordinator).name}`) : null));
    return;
  }
  const line = (id, name, model, jobs, hue) => el('div', { class: 'team-line' }, avatar(id, true, hue),
    el('div', {}, el('b', {}, name, model ? el('span', { class: 'model' }, ` · ${model}`) : ''),
      el('ul', { class: 'jobs' }, jobs.filter(Boolean).map((j) => el('li', { title: j }, j.split(' — ')[0])))));
  card.replaceChildren(...(st.members || []).map((m) => line(m.id, m.name, m.model, m.roles || [], m.hue)),
  line('human', 'You', '', [st.humanRole || 'Lead']),
  ...(st.coordinator ? [el('div', { class: 'muted', style: 'font-size:11px' }, `Coordinator: ${member(st.coordinator).name} — reads your channel messages and routes work`)] : []),
  el('div', { class: 'muted', style: 'font-size:11px' }, (st.freshEvery ?? 6) ? `Fresh agent chat every ${st.freshEvery ?? 6} requests` : 'Agent chats never restart'),
  el('div', { class: 'team-actions' }, btn('team-room', 'Edit team', () => openProjectDialog({ edit: saved })),
    el('button', { type: 'button', class: 'link-btn', onclick: () => { save('teamOpen', false); renderTeamCard(p); } }, 'Hide roles')));
}

let setupInfo = null;
// The New project / Edit team wizard. The team lives in `draft` (not in the page) until you press Create or Save.
const draft = { step: 1, mode: 'new', members: [], editing: null, shared: { codex: new Set(), claude: new Set() } };
const ROLE_TITLE = (r) => r.split(' — ')[0];

async function openProjectDialog(opts = {}) {
  const dlg = $('#project-dialog');
  $('#dlg-err').textContent = '';
  if (!dlg.open) dlg.showModal();
  if (!setupInfo) {
    $('#dlg-save').disabled = $('#dlg-next').disabled = true;
    try { setupInfo = await api('setup-info'); } catch (e) { $('#dlg-err').textContent = e.message; return; }
    $('#dlg-save').disabled = $('#dlg-next').disabled = false;
  }
  const edit = opts.edit || null;
  const st = edit ? edit.settings : {};
  draft.editing = edit;
  draft.members = (st.members || ['claude', 'codex'].map((app) => ({ app, name: APP_NAMES[app], ...setupInfo.defaults[app] })))
    .map((m) => ({ ...m, roles: [...(m.roles || [])], hue: m.hue ?? 0 }));
  draft.shared = { codex: new Set((st.shared || {}).codex || []), claude: new Set((st.shared || {}).claude || []) };
  $('#dlg-title').textContent = edit ? `Team for ${edit.name}` : 'New project';
  $('#dlg-sub').textContent = edit ? edit.root : 'Pick a folder, hire your team, then set the rules. You can change the team later.';
  $('#steps-bar li[data-step="1"]').hidden = !!edit;
  setMode(opts.existing ? 'existing' : 'new');
  $('#f-name').value = opts.name && !opts.existing ? opts.name : '';
  $('#f-parent').value = setupInfo.desktop;
  $('#f-existing').value = opts.existing || '';
  $('#f-existing-name').value = opts.existing ? (opts.name || folderName(opts.existing)) : '';
  $('#f-human').value = st.humanRole || setupInfo.humanRole;
  $('#f-fresh').value = st.freshEvery ?? setupInfo.freshEvery;
  draft.roles = { coordinator: st.coordinator || '', referee: st.referee || '', supervisor: st.supervisor || '' };
  renderTeamRows();
  countShared();
  goStep(edit || opts.existing ? 2 : 1);
}
const folderName = (p) => String(p).replace(/[\\/]+$/, '').split(/[\\/]/).pop() || '';

// ---- steps ----
function goStep(n) {
  draft.step = n;
  document.querySelectorAll('#project-dialog .step').forEach((s) => { s.hidden = Number(s.dataset.step) !== n; });
  document.querySelectorAll('#steps-bar li').forEach((li) => {
    const s = Number(li.dataset.step);
    li.classList.toggle('on', s === n);
    li.classList.toggle('done', s < n);
  });
  const first = draft.editing ? 2 : 1;
  $('#dlg-back').hidden = n === first;
  $('#dlg-next').hidden = n === 3;
  $('#dlg-next').textContent = n === 1 ? 'Next: team' : 'Next: rules';
  $('#dlg-next').classList.toggle('primary', n === 1);  // step 2 also has Create, which is the main button there
  $('#dlg-save').hidden = n === 1;
  $('#dlg-save').textContent = draft.editing ? 'Save team' : 'Create project';
  $('#dlg-err').textContent = '';
  if (n === 3) refreshRoles();
  if (n === 1) updateWhere();
  ($('#project-dialog .step:not([hidden]) input, #project-dialog .step:not([hidden]) button') || $('#dlg-next')).focus();
}
function stepError(n) {
  if (n === 1) {
    if (draft.mode === 'new') {
      const name = $('#f-name').value.trim();
      if (!name) return 'Give the project a name';
      if (/[<>:"/\\|?*]/.test(name)) return 'A project name can’t contain < > : " / \\ | ? *';
      if (!$('#f-parent').value.trim()) return 'Choose where to make the folder';
    } else if (!$('#f-existing').value.trim()) return 'Choose the project’s folder';
  }
  if (n >= 2) {
    if (!draft.members.length) return 'Add at least one member';
    const bad = draft.members.find((m) => !m.name.trim() || !m.roles.length);
    if (bad) return bad.name.trim() ? `Give ${bad.name} at least one role (Edit)` : 'Every member needs a name';
    const ids = draft.members.map((m) => memberId(m.app, m.name));
    const dup = ids.find((id, i) => ids.indexOf(id) !== i);
    if (dup) return 'Two members have the same name; rename one';
  }
  return '';
}
$('#dlg-next').onclick = () => {
  const err = stepError(draft.step);
  if (err) { $('#dlg-err').textContent = err; return; }
  goStep(draft.step + 1);
};
$('#dlg-back').onclick = () => goStep(draft.step - 1);
document.querySelectorAll('#steps-bar li').forEach((li) => li.addEventListener('click', () => {
  const to = Number(li.dataset.step);
  if (to === draft.step || li.hidden) return;
  for (let s = draft.step; s < to; s++) { const err = stepError(s); if (err) { $('#dlg-err').textContent = err; return; } }
  goStep(to);
}));

// ---- step 1: where ----
function setMode(m) {
  draft.mode = m;
  document.querySelectorAll('#dlg-mode button').forEach((b) => b.classList.toggle('on', b.dataset.m === m));
  $('#mode-new').hidden = m !== 'new';
  $('#mode-existing').hidden = m !== 'existing';
  updateWhere();
}
function updateWhere() {
  const sep = String($('#f-parent').value).includes('/') ? '/' : '\\';
  $('#where-preview').textContent = draft.mode === 'new'
    ? ($('#f-name').value.trim() ? `Crewroom will make the folder ${$('#f-parent').value.replace(/[\\/]+$/, '')}${sep}${$('#f-name').value.trim()}` : '')
    : ($('#f-existing').value.trim() ? `The team will work in ${$('#f-existing').value.trim()}` : '');
}
document.querySelectorAll('#dlg-mode button').forEach((b) => b.addEventListener('click', () => setMode(b.dataset.m)));
['#f-name', '#f-parent', '#f-existing'].forEach((s) => $(s).addEventListener('input', updateWhere));
$('#f-existing').addEventListener('change', () => { if (!$('#f-existing-name').value.trim()) $('#f-existing-name').value = folderName($('#f-existing').value); });
async function browse(input, title, after) {
  const btn = document.activeElement;
  if (btn) btn.disabled = true;
  toast('Opening your folder picker…');
  try {
    const r = await api('pick-folder', { start: input.value.trim(), title });
    if (r.path) { input.value = r.path; after && after(r.path); updateWhere(); }
  } catch (e) { toast(e.message, true); } finally { if (btn) btn.disabled = false; }
}
$('#pick-parent').onclick = () => browse($('#f-parent'), 'Where should Crewroom make the project folder?');
$('#pick-existing').onclick = () => browse($('#f-existing'), 'Choose the project folder', (p) => { $('#f-existing-name').value = folderName(p); });

// ---- step 2: the team table ----
const modelName = (m) => ((setupInfo.models[m.app] || []).find((x) => x.id === (m.model || '')) || {}).name || m.model || 'Default';
function renderTeamRows() {
  const rows = draft.members.map((m, i) => el('tr', {},
    el('td', {}, el('div', { class: 'who' }, avatar(m.app, true, m.hue), el('b', {}, m.name),
      m.manual ? el('span', { class: 'tag', title: 'Works in its own app' }, 'OWN APP') : null,
      m.shell ? el('span', { class: 'tag', title: 'Can run commands' }, 'CMD') : null)),
    el('td', {}, el('span', { class: 'dot ' + m.app }), ' ', APP_NAMES[m.app] || m.app),
    el('td', { class: 'model-cell', title: modelName(m) }, modelName(m)),
    el('td', {}, el('div', { class: 'role-chips' }, m.roles.length ? m.roles.slice(0, 3).map((r) => el('span', { class: 'chip-role on ' + m.app, title: r }, ROLE_TITLE(r)))
      .concat(m.roles.length > 3 ? [el('span', { class: 'muted' }, `+${m.roles.length - 3}`)] : []) : [el('span', { class: 'dlg-err' }, 'needs a role')])),
    el('td', { class: 'row-actions' }, el('button', { type: 'button', class: 'btn', onclick: () => openMember(i) }, 'Edit'),
      el('button', { type: 'button', class: 'btn danger', title: 'Remove', onclick: () => {
        if (draft.members.length < 2) return toast('Keep at least one member', true);
        draft.members.splice(i, 1); renderTeamRows();
      } }, '✕'))));
  $('#team-rows').replaceChildren(...rows);
  const per = Object.keys(APP_NAMES).map((a) => [APP_NAMES[a], draft.members.filter((m) => m.app === a).length]).filter(([, n]) => n);
  $('#member-count').textContent = `· ${draft.members.length} member${draft.members.length === 1 ? '' : 's'}` +
    (per.length ? ` (${per.map(([n, c]) => `${c} ${n}`).join(', ')})` : '');
}
function memberId(app, name) {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 30);
  return !slug || slug === app ? app : `${app}-${slug}`;
}
function freeHue(app, except = -1) {
  const used = new Set(draft.members.filter((m, i) => m.app === app && i !== except).map((m) => Number(m.hue || 0)));
  return (setupInfo.hues || [0]).find((h) => !used.has(h)) ?? 0;  // the first member of an agent keeps its true colours
}
$('#add-member').onclick = () => openMember(-1);

// ---- the member pop-up (add and edit) ----
let editingMember = -1;
let memberDraft = null;
function openMember(i) {
  editingMember = i;
  memberDraft = i >= 0 ? { ...draft.members[i], roles: [...draft.members[i].roles] } : { app: 'claude', name: '', model: '', roles: [], hue: 0 };
  $('#m-title').textContent = i >= 0 ? `Edit ${memberDraft.name}` : 'Add a member';
  $('#m-sub').textContent = i >= 0 ? 'Change anything; it applies when you save the team.' : 'Pick the agent, give it a name and a model. Roles and the rest can wait.';
  $('#m-save').textContent = i >= 0 ? 'Save member' : 'Add member';
  $('#m-err').textContent = '';
  $('#m-more').open = i >= 0;
  $('#m-apps').hidden = i >= 0;
  if (i < 0) pickApp(firstFoundApp(), true); else fillMember();
  $('#member-dialog').showModal();
  $('#m-name').focus();
}
const firstFoundApp = () => ((setupInfo.apps || []).find((a) => a.found) || { id: 'claude' }).id;
function pickApp(app, fresh) {
  memberDraft.app = app;
  if (fresh || !memberDraft.roles.length) memberDraft.roles = [...((setupInfo.defaults[app] || {}).roles || [])];
  const n = draft.members.filter((m) => m.app === app).length;
  if (fresh || !memberDraft.name || Object.values(APP_NAMES).some((b) => memberDraft.name.startsWith(b))) memberDraft.name = n ? `${APP_NAMES[app]} ${n + 1}` : APP_NAMES[app];
  memberDraft.model = '';
  memberDraft.hue = freeHue(app);
  memberDraft.shell = false;
  fillMember();
}
function fillMember() {
  const m = memberDraft;
  const info = appInfo(m.app);
  $('#m-apps').replaceChildren(...(setupInfo.apps || []).map((a) => el('button', { type: 'button',
    class: 'agent-tile ' + a.id + (a.id === m.app ? ' on' : '') + (a.found ? '' : ' missing'), onclick: () => pickApp(a.id, true) },
    avatar(a.id), el('b', {}, a.name), el('small', {}, a.blurb), a.found ? null : el('em', {}, 'not installed'))));
  $('#m-pic').src = member(m.app).avatar || 'assets/icon-team-room.png';
  $('#m-name').value = m.name;
  $('#m-model').replaceChildren(...(setupInfo.models[m.app] || [{ id: '', name: 'Default' }]).map((x) => el('option', { value: x.id, selected: x.id === (m.model || '') }, x.name)));
  $('#m-install').hidden = info.found !== false;
  $('#m-install').textContent = info.found === false ? `${info.name} isn't installed on this computer yet. ${info.install || ''}` : '';
  $('#m-roles').replaceChildren(...setupInfo.presets.map((t) => el('button', { type: 'button', class: 'chip-role ' + m.app + (m.roles.includes(t) ? ' on' : ''),
    title: t.split(' — ')[1] || t, onclick: (e) => { e.currentTarget.classList.toggle('on'); } }, ROLE_TITLE(t))));
  $('#m-own').value = m.roles.filter((r) => !setupInfo.presets.includes(r)).join('\n');
  $('#m-shades').replaceChildren(...(setupInfo.hues || [0]).map((h) => el('button', { type: 'button', class: 'shade' + (h === Number(m.hue || 0) ? ' on' : ''),
    title: h ? `Shade ${h}°` : 'True colours', onclick: (e) => {
      memberDraft.hue = h;
      $('#m-shades').querySelectorAll('.shade').forEach((b) => b.classList.toggle('on', b === e.currentTarget));
    } }, el('img', { src: member(m.app).avatar || '', alt: '', style: tint(h) }))));
  $('#m-manual').checked = !!m.manual;
  $('#m-shell-row').hidden = !info.shell;
  $('#m-shell').checked = !!m.shell;
  $('#m-notes').textContent = info.liveNotes === false ? `Notes you send while ${info.name} works reach it right after it finishes (as a follow-up).` : '';
}
function saveMember() {
  const m = memberDraft;
  m.name = $('#m-name').value.trim();
  m.model = $('#m-model').value;
  m.roles = [...$('#m-roles').querySelectorAll('.chip-role.on')].map((b) => setupInfo.presets.find((t) => ROLE_TITLE(t) === b.textContent))
    .concat($('#m-own').value.split('\n').map((x) => x.trim()).filter(Boolean));
  m.manual = $('#m-manual').checked;
  m.shell = appInfo(m.app).shell && $('#m-shell').checked;
  if (!m.name) { $('#m-err').textContent = 'Give the member a name'; return; }
  if (!m.roles.length) { $('#m-more').open = true; $('#m-err').textContent = 'Pick at least one role'; return; }
  const id = memberId(m.app, m.name);
  if (draft.members.some((o, i) => i !== editingMember && memberId(o.app, o.name) === id)) { $('#m-err').textContent = 'Another member already has this name'; return; }
  if (editingMember >= 0) draft.members[editingMember] = m; else draft.members.push(m);
  $('#member-dialog').close();
  renderTeamRows();
}
$('#m-save').onclick = saveMember;
$('#m-name').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); saveMember(); } });
$('#m-close').onclick = $('#m-cancel').onclick = () => $('#member-dialog').close();

// ---- step 3: rules and shared skills ----
function refreshRoles() {
  const options = draft.members.map((m) => [memberId(m.app, m.name), `${m.name} (${APP_NAMES[m.app] || m.app})`]);
  for (const [key, none] of [['coordinator', 'None — I route work myself'], ['referee', 'None — long chains wait for my OK'],
                             ['supervisor', 'None — Crewroom only restarts and retries']]) {
    const sel = $('#f-' + key);
    const value = options.some(([id]) => id === draft.roles[key]) ? draft.roles[key] : '';
    sel.replaceChildren(el('option', { value: '' }, none), ...options.map(([id, label]) => el('option', { value: id, selected: id === value }, label)));
    sel.onchange = () => { draft.roles[key] = sel.value; };
  }
}
function countShared() {
  const a = draft.shared.codex.size, b = draft.shared.claude.size;
  $('#share-count').textContent = a + b ? `· ${a} to Codex, ${b} to Claude` : '· none';
}
$('#open-skills').onclick = () => {
  for (const target of ['codex', 'claude']) {
    const source = target === 'codex' ? 'claude' : 'codex';
    $('#share-' + target).replaceChildren(...setupInfo.skills[source].filter((sk) => sk.name !== 'team-chat').map((sk) =>
      el('label', { class: 'skill', title: sk.description, 'data-name': sk.name.toLowerCase() + ' ' + sk.description.toLowerCase() },
        el('input', { type: 'checkbox', value: sk.name, checked: draft.shared[target].has(sk.name),
          onchange: (e) => { e.target.checked ? draft.shared[target].add(sk.name) : draft.shared[target].delete(sk.name); countShared(); } }),
        el('b', {}, sk.name), el('small', {}, sk.description || ''))));
  }
  document.querySelectorAll('.share-search').forEach((i) => { i.value = ''; });
  $('#skills-dialog').showModal();
};
document.querySelectorAll('.share-search').forEach((input) => input.addEventListener('input', () => {
  const q = input.value.trim().toLowerCase();
  document.querySelectorAll(`#share-${input.dataset.for} .skill`).forEach((row) => { row.hidden = q && !row.dataset.name.includes(q); });
}));
$('#skills-close').onclick = $('#skills-done').onclick = () => $('#skills-dialog').close();

// ---- create / save ----
$('#new-project').onclick = () => openProjectDialog();
$('#dlg-close').onclick = $('#dlg-cancel').onclick = () => $('#project-dialog').close();
$('#project-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  for (let s = draft.editing ? 2 : 1; s <= 2; s++) {
    const err = stepError(s);
    if (err) { goStep(s); $('#dlg-err').textContent = err; return; }
  }
  if (draft.step === 3) for (const k of ['coordinator', 'referee', 'supervisor']) draft.roles[k] = $('#f-' + k).value;
  const members = draft.members.map(({ app, name, roles, model, hue, manual, shell }) => ({ app, name: name.trim(), roles, model, hue, manual: !!manual, shell: !!shell }));
  const ids = new Set(members.map((m) => memberId(m.app, m.name)));
  const pick = (k) => (ids.has(draft.roles[k]) ? draft.roles[k] : '');
  const team = { members, humanRole: $('#f-human').value.trim(), freshEvery: Number($('#f-fresh').value || 0),
    coordinator: pick('coordinator'), referee: pick('referee'), supervisor: pick('supervisor') };
  const share = { codex: [...draft.shared.codex], claude: [...draft.shared.claude] };
  const body = draft.editing ? { key: draft.editing.key, ...team, share }
    : { ...team, share, linkFiles: $('#f-link').checked,
      ...(draft.mode === 'new' ? { name: $('#f-name').value.trim(), parent: $('#f-parent').value.trim() }
        : { existing: $('#f-existing').value.trim(), name: $('#f-existing-name').value.trim() }) };
  $('#dlg-save').disabled = true;
  try {
    const made = await api(draft.editing ? 'projects/update' : 'projects', body);
    settingsCache.set(made.key, made);
    $('#project-dialog').close();
    toast(draft.editing ? 'Team saved' : `Project “${made.name}” is ready`);
    await loadSessions(true);
    selectProject(made.key);
  } catch (err) {
    $('#dlg-err').textContent = err.message;
  } finally { $('#dlg-save').disabled = false; }
});

// ---------- which Crewroom is this ----------
let about = null;
async function loadAbout() {
  try { about = await api('ping'); } catch { return; }
  if (about.dev && !loadAbout.watching) {  // dev copy: reload by itself when the window's files change
    loadAbout.watching = true;
    setInterval(async () => {
      try { const p = await api('ping'); if (p.stamp && p.stamp !== about.stamp) location.reload(); } catch { /* restarting */ }
    }, 1500);
  }
  const other = about.installedRoot && about.installedRoot !== about.root;
  const b = $('#about');
  b.replaceChildren(el('b', {}, `Crewroom ${about.version}`), el('br'), el('span', { class: 'running-dot' }),
    other ? 'Running · not the installed copy' : 'Running · click to stop');
  b.classList.toggle('warn', !!other);
}
$('#about').onclick = async () => {
  if (!about) return;
  const other = about.installedRoot && about.installedRoot !== about.root;
  const pick = await choose(`Crewroom ${about.version}`, [
    el('span', {}, 'Running from: ', el('span', { class: 'about-path' }, about.root)),
    about.installedRoot ? el('span', {}, `Installed (${about.installedVersion}): `, el('span', { class: 'about-path' }, about.installedRoot))
      : 'Installed: no install record. Run the installer in the folder you want to keep.',
    other ? 'This window is not the installed copy. Open Crewroom from its shortcut to use the installed one.' : null,
    el('span', {}, 'Your data: ', el('span', { class: 'about-path' }, about.data)),
    `To uninstall: ${about.uninstall}. Your data is kept.`,
    'Stop Crewroom closes this server. Requests already running keep going; open Crewroom again to see them.',
    about.system === 'windows' ? 'Closing the window does not stop Crewroom: it keeps running in the notification area (by the clock) so your team can finish. Right-click its icon there to stop it.'
      : 'Closing the window does not stop Crewroom: it keeps running in the background so your team can finish.',
  ].filter(Boolean), [{ label: 'Setup check', value: 'setup' },
    about.installer && about.installer !== 'setup' ? { label: 'Uninstall…', value: 'uninstall', cls: 'danger' } : null,
    { label: 'Stop Crewroom', value: 'stop', cls: 'danger' }, { label: 'Close', value: null, cls: 'primary' }].filter(Boolean));
  if (pick === 'setup') return showWelcome();
  if (pick === 'uninstall') return uninstall();
  if (pick !== 'stop') return;
  try { await api('shutdown', {}); } catch { /* it closed before answering */ }
  document.body.replaceChildren(el('div', { class: 'empty', style: 'margin:20vh auto;text-align:center;font-size:15px' },
    'Crewroom is stopped. Open it again from its shortcut whenever you like. You can close this window.'));
};

async function uninstall() {
  const sure = await choose('Uninstall Crewroom?', [
    'This removes the team skill from Claude and Codex and stops Crewroom.',
    `Your chats are kept in ${about.data}. Delete that folder yourself if you don't want them.`,
  ], [{ label: 'Cancel', value: null }, { label: 'Uninstall', value: 'yes', cls: 'danger' }]);
  if (sure !== 'yes') return;
  let r;
  try { r = await api('uninstall', {}); } catch (e) { toast(e.message, true); return; }
  const last = r.mac ? 'Last step: drag Crewroom from your Applications folder to the Trash.'
    : r.removedFolder ? 'The program is removed too.' : `You can now delete the Crewroom folder: ${about.root}`;
  document.body.replaceChildren(el('div', { class: 'empty', style: 'margin:20vh auto;max-width:560px;text-align:center;font-size:15px;line-height:1.6' },
    el('b', {}, 'Crewroom is uninstalled.'), el('br'), 'The team skill is removed and Crewroom has stopped. ' + last, el('br'),
    `Your chats are still in ${about.data}. You can close this window.`));
}

// ---------- first run: what Crewroom is, and is this computer ready ----------
async function showWelcome() {
  const dlg = $('#welcome');
  $('#welcome-body').replaceChildren(el('div', { class: 'empty' }, 'Checking this computer…'));
  if (!dlg.open) dlg.showModal();
  let c;
  try { c = await api('setup-check'); } catch { $('#welcome-body').replaceChildren(el('p', {}, 'Could not reach the Crewroom server.')); return; }
  const row = (ok, title, hint) => el('div', { class: 'check' }, el('span', { class: 'check-mark ' + (ok ? 'ok' : 'no') }, ok ? '✓' : '!'),
    el('div', {}, title, ok ? null : el('small', {}, hint)));
  const agents = !!(c.claude || c.codex || Object.values(c.agents || {}).some((a) => a.found));
  $('#welcome-body').replaceChildren(
    el('section', {}, el('h3', {}, 'How it works'), el('ol', { class: 'how' },
      el('li', {}, el('b', {}, 'You lead. '), 'Make a project (a folder) and pick your crew: Claude and Codex members, each with a role.'),
      el('li', {}, el('b', {}, 'They work in their own apps. '), 'Claude Code and Codex do the real work, using your own plans, and hand tasks to each other with the team skill.'),
      el('li', {}, el('b', {}, 'Everything lands here. '), 'Requests, replies, files and images show up in this window as they happen.'))),
    el('section', {}, el('h3', {}, 'This computer'), el('div', { class: 'checks' },
      row(!!c.claude, c.claude ? 'Claude Code is installed' : 'Claude Code was not found',
        'Install the Claude app (claude.ai/download), open it once and switch to the Code tab. Or install Claude Code.'),
      row(!!c.codex, c.codex ? 'Codex is installed' : 'Codex was not found', 'Install the Codex app (chatgpt.com/codex) or the Codex CLI and sign in.'),
      row(c.skills.claude && c.skills.codex, c.skills.claude && c.skills.codex ? 'The team skill is set up for Claude and Codex'
        : 'The team skill is not set up', 'Run the Crewroom installer again: it sets this up for both apps.'),
      ...Object.values(c.agents || {}).filter((a) => a.optional).map((a) => row(a.found, a.found ? `${a.name} is installed (optional)` : `${a.name} is not installed (optional)`,
        `${a.install} Then: ${a.login}`)),
      agents ? null : el('p', {}, 'Crewroom needs at least one of Claude Code, Codex, Cursor or Antigravity. Install one, then press Check again.')),
      el('p', { class: 'muted', style: 'font-size:12.5px;margin:0' }, 'Step-by-step install and sign-in for every agent: ',
        el('a', { href: 'https://github.com/Karthus3560/crewroom/blob/main/AGENTS-SETUP.md', target: '_blank', rel: 'noopener' }, 'the agent setup guide'), '.'),
      el('div', {}, el('button', { type: 'button', class: 'link-btn', onclick: () => showWelcome() }, 'Check again'))),
    el('section', {}, el('h3', {}, 'Try it'), el('div', { class: 'try' },
      'Open a ', el('b', {}, 'new'), ' chat in Claude or Codex (chats that were already open don’t know the skill yet) and say: ',
      el('i', {}, '“ask Codex to make one app icon and tell me when it’s done.”'), ' Or write in #general here.')),
    el('section', {}, el('h3', {}, 'Closing the window'), el('p', {}, c.tray
      ? 'Crewroom keeps running in the notification area, by the clock, so your team can finish their work. Its icon shows what is going on; right-click it to stop Crewroom.'
      : 'Crewroom keeps running in the background so your team can finish their work. Click the version in the bottom-left corner of this window to see it or stop it.')));
}
async function finishWelcome(createProject) {
  $('#welcome').close();
  try { await api('onboarded', {}); } catch { /* shown again next time */ }
  if (createProject) openProjectDialog();
}
$('#welcome-go').onclick = () => finishWelcome(true);
$('#welcome-later').onclick = () => finishWelcome(false);
$('#welcome-x').onclick = () => finishWelcome(false);

(async function start() {
  loadAbout();
  api('setup-check').then((c) => { if (!c.onboarded) showWelcome(); }).catch(() => {});
  try { await poll(true); } catch (e) { toast('Crewroom server is not running', true); }
  await loadSessions();
  show({ type: 'room' });
  setInterval(() => poll().catch(() => {}), 2000);
  setInterval(loadSessions, 15000);
  setInterval(() => loadWorkLog(false), 4000);
})();
