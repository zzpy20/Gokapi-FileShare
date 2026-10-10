#!/usr/bin/env python3
"""Minimal file-sharing server: read-only listing/download (optionally behind a
shared viewing password), plus an authenticated /admin page for adding files
and creating folders."""
import base64
import hashlib
import hmac
import html
import io
import os
import shutil
import threading
import time
import urllib.parse
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

SHARE_DIR = os.path.abspath(os.environ.get("SHARE_DIR", "/data"))
PORT = int(os.environ.get("PORT", "8000"))
UPLOAD_USER = os.environ.get("UPLOAD_USER", "admin")
UPLOAD_PASS = os.environ.get("UPLOAD_PASS", "")
# Optional shared password visitors must enter before they can open anything.
# Empty = no viewing password (browsing is open to anyone with a link).
VIEW_PASS = os.environ.get("VIEW_PASS", "")
VIEW_COOKIE = "fileshare_view"
VIEW_COOKIE_DAYS = 30
# A top-level folder can carry its own viewing password in this file inside it
# (set from the management page). It replaces VIEW_PASS for that folder.
FOLDER_PASS_FILE = ".fileshare-password"
# A top-level folder can also carry an expiry time (Unix seconds) in this file.
# Once it has passed, the folder and everything in it is deleted automatically.
FOLDER_EXPIRY_FILE = ".fileshare-expires"
SWEEP_SECONDS = 60
# The QR code library (vendored next to this file) is served from this path and
# only fetched by a page when someone first asks for a code.
QR_LIB_PATH = "/.fileshare/qrcode.js"
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "qrcode.min.js"), "rb") as _f:
        QR_LIB = _f.read()
except OSError:
    QR_LIB = b""
THUMB_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
THUMB_MAX_BYTES = 3 * 1024 * 1024  # larger images get the plain icon instead
MESSAGES = {
    "uploaded": ("ok", "已上传 {n} 个文件。"),
    "deleted": ("ok", "已删除。"),
    "renamed": ("ok", "已改名。"),
    "created": ("ok", "文件夹已创建。"),
    "pass_set": ("ok", "文件夹密码已设置。"),
    "pass_cleared": ("ok", "文件夹密码已清除，改用通用密码。" if VIEW_PASS else "文件夹密码已清除。现在知道链接的人无需密码即可打开这个文件夹。"),
    "expiry_set": ("ok", "已设置到期时间，到期后该文件夹会被自动删除。"),
    "expiry_cleared": ("ok", "已取消到期时间。"),
    "exists": ("err", "已有同名的文件或文件夹，未做改动。"),
    "failed": ("err", "操作未完成，请检查名称后重试。"),
}
# Password guessing: after this many wrong tries from one address inside the
# window, every further try from it is refused until the window has passed.
FAIL_LIMIT = 5
FAIL_WINDOW = 600  # seconds
_fails = {}
_fails_lock = threading.Lock()


def locked_for(ip):
    """Seconds this address still has to wait, or 0 if it may try again."""
    now = time.time()
    with _fails_lock:
        recent = [t for t in _fails.get(ip, []) if now - t < FAIL_WINDOW]
        if recent:
            _fails[ip] = recent
        else:
            _fails.pop(ip, None)
        if len(recent) >= FAIL_LIMIT:
            return int(recent[-FAIL_LIMIT] + FAIL_WINDOW - now) + 1
    return 0


def note_failure(ip):
    with _fails_lock:
        _fails.setdefault(ip, []).append(time.time())


def clear_failures(ip):
    with _fails_lock:
        _fails.pop(ip, None)


def folder_password(top):
    """The viewing password set on a top-level folder, or '' if it has none."""
    try:
        with open(os.path.join(SHARE_DIR, top, FOLDER_PASS_FILE), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def folder_expiry(top):
    """Unix time at which a top-level folder expires, or 0 if it never does."""
    try:
        with open(os.path.join(SHARE_DIR, top, FOLDER_EXPIRY_FILE), encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def sweep_expired():
    """Delete top-level folders whose expiry has passed. Runs in the background."""
    while True:
        try:
            for name in os.listdir(SHARE_DIR):
                expires = folder_expiry(name)
                if expires and expires <= time.time():
                    shutil.rmtree(os.path.join(SHARE_DIR, name), ignore_errors=True)
                    print(f"Expired folder removed: {name}", flush=True)
        except OSError:
            pass
        time.sleep(SWEEP_SECONDS)


def unique_path(directory, filename):
    """A path in directory that does not exist yet: name.ext, name (1).ext, ..."""
    target = os.path.join(directory, filename)
    stem, ext = os.path.splitext(filename)
    n = 1
    while os.path.exists(target):
        target = os.path.join(directory, f"{stem} ({n}){ext}")
        n += 1
    return target
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500MB per request

ICONS = {
    ".pdf": "📕", ".doc": "📄", ".docx": "📄", ".xls": "📊", ".xlsx": "📊",
    ".ppt": "📽", ".pptx": "📽", ".zip": "🗜", ".rar": "🗜", ".7z": "🗜",
    ".png": "🖼", ".jpg": "🖼", ".jpeg": "🖼", ".gif": "🖼", ".webp": "🖼",
    ".mp4": "🎬", ".mov": "🎬", ".mkv": "🎬",
    ".mp3": "🎵", ".wav": "🎵", ".m4a": "🎵",
    ".txt": "📝", ".md": "📝",
}

PAGE_STYLE = """
  :root { --ink:#1b2430; --muted:#6b7680; --line:#e2e6e4; --paper:#f6f7f6; --card:#ffffff; --accent:#1c7c82; --accent-soft:#e3f0ef; --on-accent:#ffffff; --danger:#a8452e; --danger-soft:#f7e9e5; }
  @media (prefers-color-scheme: dark) {
    :root { --ink:#e8eeec; --muted:#93a3a2; --line:#2b3639; --paper:#12181c; --card:#1b262a; --accent:#59c4c0; --accent-soft:#1c2f2f; --on-accent:#0d2523; --danger:#f0a08c; --danger-soft:#3a2420; }
  }
  * { box-sizing:border-box; }
  [hidden] { display:none !important; }
  body { margin:0; background:var(--paper); color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",Helvetica,Arial,sans-serif; }
  .wrap { max-width:1120px; margin:0 auto; padding:40px 20px 80px; }
  .topbar { display:flex; flex-wrap:wrap; align-items:baseline; justify-content:space-between; gap:8px 12px; margin-bottom:22px; }
  h1 { font-size:1.35rem; margin:0; word-break:break-all; }
  .upload-link { font-size:.85rem; color:var(--muted); text-decoration:none; white-space:nowrap; }
  .upload-link:hover { color:var(--accent); }
  table { width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
  th { text-align:left; font-size:.75rem; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; padding:12px 16px; border-bottom:1px solid var(--line); }
  td { padding:14px 16px; border-bottom:1px solid var(--line); font-size:.95rem; }
  tr:last-child td { border-bottom:none; }
  tr.parent td { color:var(--muted); }
  td.size, td.mtime { color:var(--muted); white-space:nowrap; font-variant-numeric:tabular-nums; }
  td.name { overflow-wrap:anywhere; }
  td.name a { color:var(--ink); text-decoration:none; }
  td.name a:hover { color:var(--accent); text-decoration:underline; }
  .icon { margin-right:8px; }
  .thumb { width:76px; height:76px; object-fit:cover; border-radius:6px; vertical-align:middle; margin-right:14px; background:var(--accent-soft); }
  a.lb { cursor:zoom-in; }
  /* QR code popup: the card stays white in both themes so the code scans reliably. */
  .qr-overlay { position:fixed; inset:0; z-index:60; display:flex; align-items:center; justify-content:center; padding:16px; background:rgba(8,12,14,.7); }
  .qr-card { width:100%; max-width:340px; background:#ffffff; color:#1b2430; border-radius:12px; padding:20px; text-align:center; }
  .qr-title { font-weight:600; font-size:.95rem; overflow-wrap:anywhere; margin:0 0 4px; }
  .qr-sub { font-size:.78rem; color:#6b7680; margin:0 0 14px; }
  .qr-img { display:block; width:100%; max-width:260px; height:auto; margin:0 auto; image-rendering:pixelated; }
  .qr-url { font-size:.72rem; color:#6b7680; overflow-wrap:anywhere; margin:12px 0 16px; user-select:all; }
  .qr-actions { display:flex; gap:8px; justify-content:center; flex-wrap:wrap; }
  .qr-actions .qr-act { background:#e3f0ef; color:#1c7c82; border:none; border-radius:6px; padding:8px 14px; font-size:.86rem; font-family:inherit; cursor:pointer; text-decoration:none; }
  .qr-actions .qr-act:hover { opacity:.85; }
  .qr-actions .qr-act:focus-visible { outline:2px solid #1c7c82; outline-offset:2px; }
  .qr-err { font-size:.85rem; color:#a8452e; margin:10px 0; }
  /* Image viewer: deliberately dark in both themes, like a photo viewer. */
  .lb-overlay { position:fixed; inset:0; z-index:50; display:flex; flex-direction:column; background:rgba(8,12,14,.94); color:#e8eeec; }
  .lb-top { display:flex; align-items:center; gap:10px; padding:12px 14px; font-size:.9rem; }
  .lb-name { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .lb-count { color:#a3b1b0; white-space:nowrap; font-variant-numeric:tabular-nums; }
  .lb-btn { background:rgba(255,255,255,.14); color:#fff; border:none; border-radius:6px; padding:8px 12px; font-size:.88rem; font-family:inherit; line-height:1.2; cursor:pointer; text-decoration:none; white-space:nowrap; }
  .lb-btn:hover { background:rgba(255,255,255,.24); }
  .lb-btn:focus-visible { outline:2px solid #59c4c0; outline-offset:2px; }
  .lb-stage { position:relative; flex:1; min-height:0; display:flex; align-items:center; justify-content:center; padding:0 72px 18px; }
  .lb-stage img { max-width:100%; max-height:100%; object-fit:contain; border-radius:4px; }
  .lb-nav { position:absolute; top:50%; transform:translateY(-50%); width:46px; height:76px; padding:0; font-size:1.7rem;
    background:rgba(8,12,14,.72); border:1px solid rgba(255,255,255,.35); }
  .lb-nav:hover { background:rgba(8,12,14,.9); }
  .lb-prev { left:10px; }
  .lb-next { right:10px; }
  .meta { display:block; font-size:.78rem; font-weight:400; color:var(--muted); margin-top:3px; }
  .empty { text-align:center; color:var(--muted); padding:32px 16px; }
  footer { text-align:center; color:var(--muted); font-size:.8rem; margin-top:20px; }
  @media (max-width:640px) {
    .wrap { padding:22px 12px 60px; }
    h1 { font-size:1.15rem; }
    th, td { padding:11px 10px; }
    td { font-size:.9rem; }
    .mtime { display:none; }
    td.dl .lbl { display:none; }
    td.dl .btn-mini { padding:6px 9px; }
  }
  .panel { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:22px 24px; margin-bottom:20px; }
  .panel h2 { font-size:1rem; margin:0 0 16px; }
  .panel-head { display:flex; align-items:baseline; justify-content:space-between; gap:12px; margin-bottom:6px; }
  .panel-head h2 { margin:0; }
  .panel-head .count { font-size:.8rem; color:var(--muted); }
  .msg { padding:10px 14px; border-radius:6px; font-size:.88rem; margin-bottom:18px; }
  .msg.ok { background:var(--accent-soft); color:var(--accent); }
  .msg.err { background:var(--danger-soft); color:var(--danger); }
  .btn { display:inline-flex; align-items:center; justify-content:center; gap:6px; border:1px solid transparent; border-radius:6px;
    padding:8px 14px; font-size:.88rem; line-height:1.25; font-family:inherit; cursor:pointer; white-space:nowrap; text-decoration:none; }
  .btn:hover { opacity:.88; }
  .btn:disabled { opacity:.5; cursor:default; }
  .btn-primary { background:var(--accent); color:var(--on-accent); }
  .btn-soft { background:var(--accent-soft); color:var(--accent); }
  .btn-ghost { background:transparent; border-color:var(--line); color:var(--ink); }
  .btn-danger { background:var(--danger-soft); color:var(--danger); }
  .btn-mini {
    background:var(--accent-soft); color:var(--accent); border:none; padding:6px 12px;
    border-radius:4px; font-size:.82rem; cursor:pointer; white-space:nowrap;
  }
  .btn-mini:hover { opacity:.85; }
  .form-block label, .field label { display:block; font-size:.78rem; color:var(--muted); margin-bottom:6px; }
  .text-input { width:100%; min-width:0; padding:8px 10px; border:1px solid var(--line); border-radius:6px;
    background:var(--paper); color:var(--ink); font-size:.9rem; line-height:1.25; font-family:inherit; }
  .text-input:focus { outline:2px solid var(--accent); outline-offset:-1px; }
  .form-block > .text-input { margin-bottom:14px; }
  .group { display:flex; }
  .group .text-input { border-radius:6px 0 0 6px; border-right:none; }
  .group .btn { border-radius:0 6px 6px 0; }
  .hint { font-size:.74rem; color:var(--muted); margin:6px 0 0; }
  .visually-hidden { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); white-space:nowrap; }
  .crumbs { font-size:.9rem; color:var(--muted); margin:-12px 0 20px; overflow-wrap:anywhere; }
  .crumbs a { color:var(--accent); text-decoration:none; }
  .crumbs a:hover { text-decoration:underline; }
  .crumbs strong { color:var(--ink); font-weight:600; }
  .tools { display:grid; grid-template-columns:minmax(0,3fr) minmax(0,2fr); gap:20px; margin-bottom:20px; }
  .tools .panel { margin-bottom:0; }
  .drop-zone { display:block; cursor:pointer; border:2px dashed var(--line); border-radius:8px; padding:26px 14px; text-align:center; color:var(--muted); font-size:.85rem; }
  .drop-zone strong { display:block; color:var(--ink); font-size:.95rem; font-weight:600; margin-bottom:4px; }
  .drop-zone:hover, .drop-zone.over { border-color:var(--accent); background:var(--accent-soft); }
  .chosen { font-size:.85rem; color:var(--muted); margin:12px 0 14px; overflow-wrap:anywhere; }
  .item { padding:14px 0; border-top:1px solid var(--line); }
  .item:last-child { padding-bottom:0; }
  .item-head { display:flex; align-items:center; gap:12px; }
  .item-icon { flex:none; width:56px; height:56px; display:flex; align-items:center; justify-content:center;
    font-size:1.25rem; background:var(--paper); border-radius:6px; overflow:hidden; }
  .item-icon a { display:block; width:100%; height:100%; }
  .item-icon img { width:56px; height:56px; object-fit:cover; display:block; }
  .item-title { flex:1; min-width:0; }
  .item-name { font-weight:600; font-size:.95rem; color:var(--ink); text-decoration:none; overflow-wrap:anywhere; }
  a.item-name:hover { color:var(--accent); text-decoration:underline; }
  .item-meta { display:flex; flex-wrap:wrap; align-items:center; gap:4px 10px; margin-top:4px; font-size:.78rem; color:var(--muted); font-variant-numeric:tabular-nums; }
  .badge { background:var(--accent-soft); color:var(--accent); border-radius:999px; padding:1px 9px; font-size:.72rem; white-space:nowrap; }
  .badge.warn { background:var(--danger-soft); color:var(--danger); }
  .item-actions { display:flex; gap:8px; flex:none; }
  .item-actions form { margin:0; }
  .item-fields { display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:16px 20px;
    margin:14px 0 2px 68px; padding:16px 18px; background:var(--paper); border-radius:8px; }
  .item-fields form { margin:0; }
  .progress { margin-top:14px; }
  .progress-track { height:10px; background:var(--accent-soft); border-radius:5px; overflow:hidden; }
  .progress-fill { height:100%; width:0; background:var(--accent); transition:width .15s linear; }
  .progress-text { display:flex; justify-content:space-between; gap:12px; margin-top:6px; font-size:.85rem; color:var(--muted); font-variant-numeric:tabular-nums; }
  .progress.err .progress-fill { background:var(--danger); }
  .progress.err .progress-text { color:var(--danger); }
  @media (max-width:820px) {
    .tools { grid-template-columns:minmax(0,1fr); }
  }
  @media (max-width:640px) {
    .panel { padding:16px 14px; }
    .thumb { width:56px; height:56px; margin-right:10px; }
    .lb-stage { padding:0 8px 14px; }
    .lb-nav { width:38px; height:60px; font-size:1.4rem; }
    .lb-prev { left:6px; }
    .lb-next { right:6px; }
    .lb-btn .lbl { display:none; }
    .item-head { flex-wrap:wrap; }
    .item-actions { width:100%; padding-left:68px; flex-wrap:wrap; }
    .item-fields { margin-left:0; padding:14px; grid-template-columns:minmax(0,1fr); }
  }
  a.btn-mini { display:inline-block; text-decoration:none; }
  td.dl { text-align:right; white-space:nowrap; }
"""

LIST_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{style}</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <h1>📁 文件分享</h1>
  </div>
  <table>
    <thead><tr><th>文件名</th><th>大小</th><th class="mtime">修改时间</th><th></th></tr></thead>
    <tbody>
{rows}
    </tbody>
  </table>
  <footer>共 {count} 项{expiry_note}</footer>
</div>
{script}
{lightbox}
</body>
</html>"""

PRIVATE_ROOT_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>文件分享</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{style}</style>
</head>
<body>
<div class="wrap">
  <div class="topbar"><h1>📁 文件分享</h1></div>
  <table><tbody>
    <tr><td class="empty">请使用收到的分享链接打开对应的文件夹或文件。</td></tr>
  </tbody></table>
</div>
</body>
</html>"""

LOGIN_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>文件分享</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{style}
  .login {{ max-width:420px; margin:8vh auto 0; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="panel login">
    <h2>{heading}</h2>
    {message}
    <form method="post" action="/login" class="form-block">
      <input type="hidden" name="next" value="{next_attr}">
      <label for="view-password">访问密码</label>
      <input type="text" class="text-input" id="view-password" name="password" autocomplete="off" autocapitalize="off" autofocus required>
      <button type="submit" class="btn btn-primary">进入</button>
    </form>
  </div>
</div>
</body>
</html>"""

# In-page image viewer for the listing: click an image to open it, then flip
# through the folder's images with the buttons, arrow keys or a swipe.
LIGHTBOX_SCRIPT = """<script>
(function () {
  var anchors = [].slice.call(document.querySelectorAll('a.lb'));
  if (!anchors.length) return;
  var items = [], indexByHref = {};
  anchors.forEach(function (a) {
    var href = a.getAttribute('href');
    if (!(href in indexByHref)) { indexByHref[href] = items.length; items.push({ href: href, name: '' }); }
    var text = a.textContent.trim();
    if (text) items[indexByHref[href]].name = text;
  });

  var overlay, img, nameEl, countEl, downloadEl, closeBtn, current = 0, lastFocus = null, touchX = null;

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }
  function build() {
    overlay = el('div', 'lb-overlay');
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', '图片查看');
    var top = el('div', 'lb-top');
    nameEl = el('span', 'lb-name');
    countEl = el('span', 'lb-count');
    downloadEl = el('a', 'lb-btn');
    downloadEl.innerHTML = '⬇<span class="lbl"> 下载</span>';
    downloadEl.setAttribute('download', '');
    closeBtn = el('button', 'lb-btn');
    closeBtn.type = 'button';
    closeBtn.innerHTML = '✕<span class="lbl"> 关闭</span>';
    closeBtn.setAttribute('aria-label', '关闭');
    closeBtn.addEventListener('click', close);
    top.appendChild(nameEl); top.appendChild(countEl); top.appendChild(downloadEl); top.appendChild(closeBtn);
    var stage = el('div', 'lb-stage');
    img = el('img');
    img.alt = '';
    stage.appendChild(img);
    if (items.length > 1) {
      var prev = el('button', 'lb-btn lb-nav lb-prev', '‹');
      prev.type = 'button'; prev.setAttribute('aria-label', '上一张');
      prev.addEventListener('click', function (e) { e.stopPropagation(); show(current - 1); });
      var next = el('button', 'lb-btn lb-nav lb-next', '›');
      next.type = 'button'; next.setAttribute('aria-label', '下一张');
      next.addEventListener('click', function (e) { e.stopPropagation(); show(current + 1); });
      stage.appendChild(prev); stage.appendChild(next);
    }
    // Clicking the dark area around the picture closes the viewer.
    stage.addEventListener('click', function (e) { if (e.target === stage) close(); });
    stage.addEventListener('touchstart', function (e) { touchX = e.changedTouches[0].clientX; }, { passive: true });
    stage.addEventListener('touchend', function (e) {
      if (touchX === null) return;
      var dx = e.changedTouches[0].clientX - touchX;
      touchX = null;
      if (Math.abs(dx) > 50) show(current + (dx < 0 ? 1 : -1));
    }, { passive: true });
    overlay.appendChild(top); overlay.appendChild(stage);
    document.body.appendChild(overlay);
  }
  function show(i) {
    current = (i + items.length) % items.length;
    var item = items[current];
    img.src = item.href;
    nameEl.textContent = item.name;
    countEl.textContent = (current + 1) + ' / ' + items.length;
    downloadEl.href = item.href + '?dl=1';
    // Fetch the neighbours ahead of time so flipping feels instant.
    [current + 1, current - 1].forEach(function (n) {
      if (items.length > 1) new Image().src = items[(n + items.length) % items.length].href;
    });
  }
  function open(i) {
    if (!overlay) build();
    lastFocus = document.activeElement;
    overlay.hidden = false;
    document.body.style.overflow = 'hidden';
    show(i);
    closeBtn.focus();
  }
  function close() {
    overlay.hidden = true;
    img.removeAttribute('src');
    document.body.style.overflow = '';
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  anchors.forEach(function (a) {
    a.addEventListener('click', function (e) {
      // Leave ctrl/cmd/shift/middle clicks alone so "open in new tab" still works.
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button) return;
      e.preventDefault();
      open(indexByHref[a.getAttribute('href')]);
    });
  });
  document.addEventListener('keydown', function (e) {
    if (!overlay || overlay.hidden) return;
    if (e.key === 'Escape') close();
    else if (e.key === 'ArrowLeft') show(current - 1);
    else if (e.key === 'ArrowRight') show(current + 1);
  });
})();
</script>"""

# QR codes are drawn in the visitor's own browser from the link text itself: no
# redirect, and the link is never sent to any outside service.
QR_SCRIPT = """<script>
(function () {
  var buttons = [].slice.call(document.querySelectorAll('.qr-btn'));
  if (!buttons.length) return;
  var LIB = '__QR_LIB_PATH__', loading = null, overlay = null, lastFocus = null;

  function loadLib() {
    if (window.qrcode) return Promise.resolve();
    if (!loading) {
      loading = new Promise(function (resolve, reject) {
        var s = document.createElement('script');
        s.src = LIB;
        s.onload = function () { window.qrcode ? resolve() : reject(); };
        s.onerror = function () { loading = null; reject(); };
        document.head.appendChild(s);
      });
    }
    return loading;
  }
  function draw(url) {
    var qr = window.qrcode(0, 'M');
    qr.addData(url);
    qr.make();
    var n = qr.getModuleCount(), quiet = 4, scale = 8;
    var canvas = document.createElement('canvas');
    canvas.width = canvas.height = (n + quiet * 2) * scale;
    var ctx = canvas.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#000000';
    for (var r = 0; r < n; r++)
      for (var c = 0; c < n; c++)
        if (qr.isDark(r, c)) ctx.fillRect((c + quiet) * scale, (r + quiet) * scale, scale, scale);
    return canvas.toDataURL('image/png');
  }
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }
  function close() {
    if (!overlay) return;
    overlay.remove();
    overlay = null;
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  function open(url, name) {
    close();
    lastFocus = document.activeElement;
    overlay = el('div', 'qr-overlay');
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', '二维码');
    var card = el('div', 'qr-card');
    card.appendChild(el('p', 'qr-title', name));
    card.appendChild(el('p', 'qr-sub', '用手机相机扫码打开'));
    var body = el('div');
    body.appendChild(el('p', 'qr-sub', '正在生成…'));
    card.appendChild(body);
    card.appendChild(el('p', 'qr-url', url));
    var actions = el('div', 'qr-actions');
    var closeBtn = el('button', 'qr-act', '关闭');
    closeBtn.type = 'button';
    closeBtn.addEventListener('click', close);
    actions.appendChild(closeBtn);
    card.appendChild(actions);
    overlay.appendChild(card);
    overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
    document.body.appendChild(overlay);
    closeBtn.focus();
    var mine = overlay;
    loadLib().then(function () {
      if (overlay !== mine) return;
      var src = draw(url);
      var img = el('img', 'qr-img');
      img.alt = '二维码：' + name;
      img.src = src;
      body.textContent = '';
      body.appendChild(img);
      var save = el('a', 'qr-act', '保存图片');
      save.href = src;
      save.setAttribute('download', (name.replace(/[\\/:*?"<>|]+/g, '_') || 'qr') + '-二维码.png');
      actions.insertBefore(save, closeBtn);
    }).catch(function () {
      if (overlay !== mine) return;
      body.textContent = '';
      body.appendChild(el('p', 'qr-err', '二维码生成失败，请直接复制下面的链接。'));
    });
  }
  buttons.forEach(function (btn) {
    btn.addEventListener('click', function () { open(btn.getAttribute('data-qr'), btn.getAttribute('data-name') || ''); });
  });
  document.addEventListener('keydown', function (e) { if (overlay && e.key === 'Escape') close(); });
})();
</script>""".replace("__QR_LIB_PATH__", QR_LIB_PATH)

COPY_SCRIPT = """<script>
function copyLink(url, btn) {
  var original = btn.innerHTML;
  function done(ok) {
    btn.textContent = ok ? '✅ 已复制' : '复制失败';
    setTimeout(function () { btn.innerHTML = original; }, 1500);
  }
  function fallback() {
    var ta = document.createElement('textarea');
    ta.value = url;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    done(ok);
  }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(url).then(function () { done(true); }).catch(fallback);
  } else {
    fallback();
  }
}
</script>"""

# Sends the upload form in the background so the page can show how far it has got.
# Without JavaScript the form still submits the ordinary way.
UPLOAD_SCRIPT = """<script>
(function () {
  var form = document.getElementById('upload-form');
  if (!form || !window.XMLHttpRequest || !window.FormData) return;
  var input = document.getElementById('upload-files');
  var button = document.getElementById('upload-button');
  var box = document.getElementById('upload-progress');
  var fill = document.getElementById('upload-fill');
  var status = document.getElementById('upload-status');
  var percent = document.getElementById('upload-percent');
  var MAX_BYTES = __MAX_BYTES__;

  function size(n) {
    var units = ['B', 'KB', 'MB', 'GB'], i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return (i === 0 ? n : n.toFixed(1)) + units[i];
  }
  function show(text, pct, isError) {
    box.hidden = false;
    box.className = 'progress' + (isError ? ' err' : '');
    status.textContent = text;
    percent.textContent = pct === null ? '' : pct + '%';
    if (pct !== null) fill.style.width = pct + '%';
  }
  function fail(text) {
    show(text, null, true);
    button.disabled = false;
    input.disabled = false;
  }

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    var total = 0;
    for (var i = 0; i < input.files.length; i++) total += input.files[i].size;
    if (!input.files.length) {
      fail('请先选择要上传的文件。');
      return;
    }
    if (total > MAX_BYTES) {
      fail('所选文件共 ' + size(total) + '，超过单次上传上限 ' + size(MAX_BYTES) + '。请分批上传。');
      return;
    }
    var data = new FormData(form);
    var xhr = new XMLHttpRequest();
    xhr.open('POST', form.action);
    xhr.upload.addEventListener('progress', function (e) {
      if (!e.lengthComputable) return;
      var pct = Math.min(99, Math.floor(e.loaded / e.total * 100));
      show('正在上传 ' + size(e.loaded) + ' / ' + size(e.total), pct, false);
    });
    xhr.upload.addEventListener('load', function () {
      show('已发送，等待服务器保存…', 99, false);
    });
    xhr.addEventListener('load', function () {
      if (xhr.status >= 200 && xhr.status < 300) {
        show('上传完成', 100, false);
        window.location.href = xhr.responseURL || window.location.href;
      } else if (xhr.status === 413) {
        fail('文件太大，服务器拒绝了这次上传。');
      } else {
        fail('上传失败（错误 ' + xhr.status + '）。请重试。');
      }
    });
    xhr.addEventListener('error', function () { fail('上传失败：连接中断。请检查网络后重试。'); });
    xhr.addEventListener('abort', function () { fail('上传已取消。'); });
    button.disabled = true;
    show('正在上传 0B / ' + size(total), 0, false);
    xhr.send(data);
    input.disabled = true;
  });

  var chosen = document.getElementById('upload-chosen');
  function showChosen() {
    if (!chosen) return;
    var n = input.files.length, total = 0;
    for (var i = 0; i < n; i++) total += input.files[i].size;
    if (!n) chosen.textContent = '尚未选择文件';
    else if (n === 1) chosen.textContent = '已选择：' + input.files[0].name + '（' + size(total) + '）';
    else chosen.textContent = '已选择 ' + n + ' 个文件，共 ' + size(total);
  }
  input.addEventListener('change', function () { box.hidden = true; showChosen(); });

  // Dropping files on the zone selects them and starts the upload straight away.
  var zone = document.getElementById('drop-zone');
  if (zone) {
    ['dragenter', 'dragover'].forEach(function (name) {
      zone.addEventListener(name, function (e) { e.preventDefault(); zone.classList.add('over'); });
    });
    ['dragleave', 'drop'].forEach(function (name) {
      zone.addEventListener(name, function (e) { e.preventDefault(); zone.classList.remove('over'); });
    });
    zone.addEventListener('drop', function (e) {
      if (input.disabled || !e.dataTransfer || !e.dataTransfer.files.length) return;
      try { input.files = e.dataTransfer.files; } catch (err) { return; }
      showChosen();
      form.dispatchEvent(new Event('submit', { cancelable: true }));
    });
    // A file dropped beside the zone must not make the browser open it.
    ['dragover', 'drop'].forEach(function (name) {
      window.addEventListener(name, function (e) { e.preventDefault(); });
    });
  }
})();
</script>"""

MANAGE_SCRIPT = """<script>
function toggleFields(btn) {
  var el = document.getElementById(btn.getAttribute('aria-controls'));
  if (!el) return;
  el.hidden = !el.hidden;
  btn.setAttribute('aria-expanded', String(!el.hidden));
  if (!el.hidden) {
    var first = el.querySelector('input[type=text], input[type=number]');
    if (first) first.focus();
  }
}
</script>"""

UPLOAD_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>管理文件</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{style}</style>
<noscript><style>.item-fields[hidden] {{ display:grid !important; }}</style></noscript>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <h1>🛠 管理文件</h1>
    <a class="upload-link" href="/{folder_href}">查看访客页面 →</a>
  </div>
  <nav class="crumbs" aria-label="当前位置">{crumbs}</nav>
  {message}
  <div class="tools">
    <div class="panel">
      <h2>上传文件到此文件夹</h2>
      <form method="post" action="/upload" enctype="multipart/form-data" id="upload-form">
        <input type="hidden" name="folder" value="{folder_attr}">
        <label class="drop-zone" id="drop-zone" for="upload-files"><strong>把文件拖到这里</strong>或点击选择文件 · 单次最多 {max_size}</label>
        <input type="file" class="visually-hidden" id="upload-files" name="files" multiple>
        <p class="chosen" id="upload-chosen">尚未选择文件</p>
        <button type="submit" class="btn btn-primary" id="upload-button">上传</button>
      </form>
      <div class="progress" id="upload-progress" hidden>
        <div class="progress-track"><div class="progress-fill" id="upload-fill"></div></div>
        <div class="progress-text"><span id="upload-status"></span><span id="upload-percent"></span></div>
      </div>
    </div>
    <div class="panel">
      <h2>新建文件夹</h2>
      <form method="post" action="/mkdir" class="form-block">
        <input type="hidden" name="folder" value="{folder_attr}">
        <label for="new-folder-name">文件夹名称</label>
        <div class="group">
          <input type="text" class="text-input" id="new-folder-name" name="name" placeholder="例如：合同" required>
          <button type="submit" class="btn btn-primary">创建</button>
        </div>
        {mkdir_hint}
      </form>
    </div>
  </div>
  <div class="panel">
    <div class="panel-head">
      <h2>此文件夹的内容</h2>
      <span class="count">{count_text}</span>
    </div>
{manage_rows}
  </div>
</div>
{script}
{upload_script}
</body>
</html>"""


def human_size(n):
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{int(size)}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def safe_join(base, rel):
    """Join rel onto base, refusing to escape base via .. or absolute paths."""
    rel = (rel or "").strip("/")
    target = os.path.normpath(os.path.join(base, rel)) if rel else base
    if target != base and not target.startswith(base + os.sep):
        raise ValueError("path escapes share directory")
    return target


def get_boundary(content_type):
    for part in content_type.split(";")[1:]:
        part = part.strip()
        if part.startswith("boundary="):
            b = part[len("boundary="):]
            if b.startswith('"') and b.endswith('"'):
                b = b[1:-1]
            return b.encode()
    return None


def parse_multipart(data, boundary):
    """Minimal multipart/form-data parser: returns (fields dict, files list of (name, filename, bytes))."""
    delimiter = b"--" + boundary
    fields = {}
    files = []
    for part in data.split(delimiter):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        header_end = part.find(b"\r\n\r\n")
        if header_end == -1:
            continue
        headers_raw = part[:header_end].decode("utf-8", "replace")
        body = part[header_end + 4:]
        name = None
        filename = None
        for line in headers_raw.split("\r\n"):
            if line.lower().startswith("content-disposition:"):
                for token in line.split(";")[1:]:
                    token = token.strip()
                    if token.startswith('name="') and token.endswith('"'):
                        name = token[6:-1]
                    elif token.startswith('filename="') and token.endswith('"'):
                        filename = token[10:-1]
        if name is None:
            continue
        if filename is not None:
            if filename:
                files.append((name, filename, body))
        else:
            fields.setdefault(name, []).append(body.decode("utf-8", "replace"))
    return fields, files


class ShareHandler(SimpleHTTPRequestHandler):
    server_version = "FileShare/1.1"

    # ---------- public listing (unchanged behaviour) ----------

    def list_directory(self, path):
        try:
            names = os.listdir(path)
        except OSError:
            self.send_error(404, "Not Found")
            return None

        names.sort(key=lambda n: os.path.getmtime(os.path.join(path, n)), reverse=True)

        rows = []
        rel = os.path.relpath(path, self.directory)
        rel = "" if rel == "." else rel
        host = self.headers.get("Host", f"localhost:{PORT}")
        authed = self.is_authed()
        # The top level is not listed for visitors: they can only open a folder or
        # file whose exact link they were given. The logged-in owner still sees it.
        if not rel and not authed:
            return self._respond_html(PRIVATE_ROOT_TEMPLATE.format(style=PAGE_STYLE))
        # Same reason: no "up" link out of a top-level folder for visitors.
        has_parent = bool(rel) and (authed or "/" in rel.replace(os.sep, "/"))
        if has_parent:
            rows.append('    <tr class="parent"><td colspan="4">⬆ <a href="../">上一级目录</a></td></tr>')

        for name in names:
            if name.startswith("."):
                continue
            full = os.path.join(path, name)
            is_dir = os.path.isdir(full)
            display = name + ("/" if is_dir else "")
            link = urllib.parse.quote(name) + ("/" if is_dir else "")
            ext = os.path.splitext(name)[1].lower()
            icon = "📁" if is_dir else ICONS.get(ext, "📄")
            size_str = "—" if is_dir else human_size(os.path.getsize(full))
            mtime = datetime.fromtimestamp(os.path.getmtime(full)).strftime("%Y-%m-%d %H:%M")
            # Clicking the name opens the item in the browser. The buttons copy its
            # direct link (to paste to someone else) and, for files, force a save.
            direct = f"http://{host}/" + urllib.parse.quote((rel + "/" if rel else "") + name) + ("/" if is_dir else "")
            dl_cell = (
                f'<button type="button" class="btn-mini" title="复制直达链接" '
                f'onclick="copyLink(\'{direct}\', this)">🔗<span class="lbl"> 复制链接</span></button>'
                f' <button type="button" class="btn-mini qr-btn" title="二维码" data-qr="{direct}" '
                f'data-name="{html.escape(display, quote=True)}">▦<span class="lbl"> 二维码</span></button>'
            )
            if not is_dir:
                dl_cell += (
                    f' <a class="btn-mini" title="下载" href="{link}?dl=1" download>'
                    f'⬇<span class="lbl"> 下载</span></a>'
                )
            icon_html = f'<span class="icon">{icon}</span>'
            name_attrs = ""
            if not is_dir and ext in THUMB_EXTS:
                # Images open in the in-page viewer; without JavaScript the links
                # still open the file itself.
                name_attrs = ' class="lb"'
                if os.path.getsize(full) <= THUMB_MAX_BYTES:
                    icon_html = (
                        f'<a class="lb" href="{link}" tabindex="-1" aria-hidden="true">'
                        f'<img class="thumb" src="{link}" alt="" loading="lazy"></a>'
                    )
            rows.append(
                f'    <tr><td class="name">{icon_html}'
                f'<a{name_attrs} href="{link}">{html.escape(display)}</a></td>'
                f'<td class="size">{size_str}</td><td class="mtime">{mtime}</td>'
                f'<td class="dl">{dl_cell}</td></tr>'
            )

        count = len(rows) - (1 if has_parent else 0)
        expiry_note = ""
        expires = folder_expiry(rel.replace(os.sep, "/").split("/")[0]) if rel else 0
        if expires:
            expiry_note = " · 此分享将于 " + datetime.fromtimestamp(expires).strftime("%Y-%m-%d %H:%M") + " 到期"
        title = urllib.parse.unquote(self.path) or "/"
        body = LIST_TEMPLATE.format(
            title=html.escape(title),
            style=PAGE_STYLE,
            script=COPY_SCRIPT,
            expiry_note=expiry_note,
            lightbox=LIGHTBOX_SCRIPT + "\n" + QR_SCRIPT,
            rows="\n".join(rows) if rows else '    <tr><td colspan="4" class="empty">暂无文件</td></tr>',
            count=count,
        )
        return self._respond_html(body)

    def _respond_html(self, body_str, status=200):
        encoded = body_str.encode("utf-8", "surrogateescape")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        return io.BytesIO(encoded)

    # ---------- auth ----------

    def is_authed(self):
        expected = "Basic " + base64.b64encode(f"{UPLOAD_USER}:{UPLOAD_PASS}".encode()).decode()
        return self.headers.get("Authorization") == expected

    def rel_parts(self, url_path):
        """Path components of a request, relative to the share directory."""
        fs_path = self.translate_path(urllib.parse.urlparse(url_path).path)
        rel = os.path.relpath(fs_path, SHARE_DIR)
        if rel == "." or rel.startswith(".."):
            return []
        return rel.split(os.sep)

    def is_hidden(self, url_path):
        """Dot-files (including folder password files) are never served."""
        return any(part.startswith(".") for part in self.rel_parts(url_path))

    def scope_for(self, url_path):
        """Which password guards a request: the name of the top-level folder it is
        in when that folder has its own password, otherwise '' (the shared one)."""
        parts = self.rel_parts(url_path)
        if parts and os.path.isdir(os.path.join(SHARE_DIR, parts[0])) and folder_password(parts[0]):
            return parts[0]
        return ""

    @staticmethod
    def scope_password(scope):
        return folder_password(scope) if scope else VIEW_PASS

    @staticmethod
    def scope_cookie(scope):
        if not scope:
            return VIEW_COOKIE
        return VIEW_COOKIE + "_" + hashlib.sha256(scope.encode()).hexdigest()[:12]

    @staticmethod
    def scope_token(scope, password):
        # Changes whenever that password or the admin password changes, which
        # signs out everyone who was using it.
        return hashlib.sha256(f"fileshare-view:{scope}:{password}:{UPLOAD_PASS}".encode()).hexdigest()

    def can_view(self, url_path):
        """True if nothing guards this path, or this request carries the matching
        viewing cookie, or it is the logged-in owner."""
        scope = self.scope_for(url_path)
        password = self.scope_password(scope)
        if not password or self.is_authed():
            return True
        wanted_name = self.scope_cookie(scope)
        wanted_value = self.scope_token(scope, password)
        for part in self.headers.get("Cookie", "").split(";"):
            key, _, value = part.strip().partition("=")
            if key == wanted_name and hmac.compare_digest(value, wanted_value):
                return True
        return False

    @staticmethod
    def safe_next(target):
        """Only ever redirect back into this site."""
        if target.startswith("/") and not target.startswith("//") and "\\" not in target:
            return target
        return "/"

    def serve_login_page(self, next_path, message="", status=200):
        next_path = self.safe_next(next_path)
        scope = self.scope_for(next_path)
        heading = f"🔒 请输入「{html.escape(scope)}」的访问密码" if scope else "🔒 请输入访问密码"
        body = LOGIN_TEMPLATE.format(
            style=PAGE_STYLE,
            heading=heading,
            message=f'<div class="msg err">{message}</div>' if message else "",
            next_attr=html.escape(next_path, quote=True),
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    @staticmethod
    def wait_message(seconds):
        return f"尝试次数过多，请 {max(1, (seconds + 59) // 60)} 分钟后再试。"

    def handle_login(self):
        length = int(self.headers.get("Content-Length", 0))
        if length < 0 or length > 4096:
            self.send_error(400, "Bad Request")
            return
        data = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
        next_path = self.safe_next(data.get("next", ["/"])[0])
        ip = self.client_address[0]
        wait = locked_for(ip)
        if wait:
            self.serve_login_page(next_path, self.wait_message(wait), status=429)
            return
        scope = self.scope_for(next_path)
        expected = self.scope_password(scope)
        if not expected:
            self._redirect(next_path)
            return
        password = data.get("password", [""])[0]
        if not hmac.compare_digest(password.encode(), expected.encode()):
            note_failure(ip)
            wait = locked_for(ip)
            self.serve_login_page(next_path, self.wait_message(wait) if wait else "密码不正确，请重试。", status=403)
            return
        clear_failures(ip)
        self.send_response(303)
        self.send_header("Location", next_path)
        self.send_header(
            "Set-Cookie",
            f"{self.scope_cookie(scope)}={self.scope_token(scope, expected)}; "
            f"Max-Age={VIEW_COOKIE_DAYS * 86400}; Path=/; HttpOnly; SameSite=Lax",
        )
        self.send_header("Content-Length", "0")
        self.end_headers()

    def check_auth(self):
        ip = self.client_address[0]
        wait = locked_for(ip)
        if wait:
            body = f"<h1>{self.wait_message(wait)}</h1>".encode("utf-8")
            self.send_response(429)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return False
        if self.is_authed():
            return True
        if self.headers.get("Authorization"):
            note_failure(ip)
        body = "<h1>需要登录才能上传</h1>".encode("utf-8")
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="upload"')
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    # ---------- routing ----------

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == QR_LIB_PATH and QR_LIB:
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(QR_LIB)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(QR_LIB)
            return
        # The management page lives at /admin. /upload was its old address and
        # still forwards there, so earlier bookmarks keep working.
        if parsed.path == "/upload":
            self._redirect("/admin" + ("?" + parsed.query if parsed.query else ""))
            return
        if parsed.path.rstrip("/") == "/admin":
            if not self.check_auth():
                return
            self.serve_upload_page(parsed)
            return
        if parsed.path == "/login":
            next_path = self.safe_next(urllib.parse.parse_qs(parsed.query).get("next", ["/"])[0])
            if self.can_view(next_path):
                self._redirect(next_path)
            else:
                self.serve_login_page(next_path)
            return
        if self.is_hidden(self.path):
            self.send_error(404, "Not Found")
            return
        if not self.can_view(self.path):
            self._redirect("/login?next=" + urllib.parse.quote(self.path, safe=""))
            return
        # ?dl=1 on a file: send it as an attachment so the browser saves it
        # instead of opening it (the listing's download button uses this).
        self._attachment = None
        if urllib.parse.parse_qs(parsed.query).get("dl") == ["1"]:
            target = self.translate_path(self.path)
            if os.path.isfile(target):
                self._attachment = os.path.basename(target)
        super().do_GET()

    def end_headers(self):
        name = getattr(self, "_attachment", None)
        if name:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(name))
            self._attachment = None
        super().end_headers()

    def do_HEAD(self):
        if self.is_hidden(self.path):
            self.send_error(404, "Not Found")
            return
        if not self.can_view(self.path):
            self.send_error(403, "Forbidden")
            return
        super().do_HEAD()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/login":
            self.handle_login()
            return
        if not self.check_auth():
            return
        if parsed.path == "/upload":
            self.handle_upload()
        elif parsed.path == "/mkdir":
            self.handle_mkdir()
        elif parsed.path == "/delete":
            self.handle_delete()
        elif parsed.path == "/rename":
            self.handle_rename()
        elif parsed.path == "/setpass":
            self.handle_setpass()
        elif parsed.path == "/setexpiry":
            self.handle_setexpiry()
        else:
            self.send_error(404)

    # ---------- upload page + handlers ----------

    def serve_upload_page(self, parsed, message=""):
        qs = urllib.parse.parse_qs(parsed.query)
        folder = qs.get("folder", [""])[0].strip("/")
        code, _, count = qs.get("msg", [""])[0].partition(":")
        if code in MESSAGES:
            kind, text = MESSAGES[code]
            message = f'<div class="msg {kind}">{text.format(n=int(count) if count.isdigit() else 0)}</div>'
        try:
            folder_abs = safe_join(SHARE_DIR, folder)
        except ValueError:
            folder = ""
            folder_abs = SHARE_DIR
        manage_rows, count_text = self._manage_rows(folder_abs, folder)
        body = UPLOAD_TEMPLATE.format(
            style=PAGE_STYLE,
            script=COPY_SCRIPT,
            upload_script=LIGHTBOX_SCRIPT + "\n" + QR_SCRIPT + "\n" + MANAGE_SCRIPT + "\n" + UPLOAD_SCRIPT.replace("__MAX_BYTES__", str(MAX_UPLOAD_BYTES)),
            crumbs=self._crumbs(folder),
            folder_href=urllib.parse.quote(folder) + ("/" if folder else ""),
            folder_attr=html.escape(folder),
            max_size=human_size(MAX_UPLOAD_BYTES).replace(".0", ""),
            mkdir_hint="" if folder else '<p class="hint">顶层文件夹的名称是分享链接的一部分，起一个不容易被猜到的名字。</p>',
            count_text=count_text,
            manage_rows=manage_rows,
            message=message,
        )
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    @staticmethod
    def _crumbs(folder):
        """Breadcrumb for the management page: every level links to its own page."""
        parts = [p for p in folder.split("/") if p]
        if not parts:
            return "<strong>根目录</strong>"
        out = ['<a href="/admin">根目录</a>']
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                out.append(f"<strong>{html.escape(part)}</strong>")
            else:
                target = urllib.parse.quote("/".join(parts[: i + 1]))
                out.append(f'<a href="/admin?folder={target}">{html.escape(part)}</a>')
        return " / ".join(out)

    def _manage_rows(self, folder_abs, folder_rel):
        """The item list of the management page, plus a short count for its header."""
        try:
            names = [n for n in os.listdir(folder_abs) if not n.startswith(".")]
        except OSError:
            return '    <div class="empty">文件夹不存在</div>', ""
        if not names:
            return '    <div class="empty">此文件夹为空，上传文件或新建文件夹后会显示在这里。</div>', "共 0 项"
        names.sort(key=lambda n: os.path.getmtime(os.path.join(folder_abs, n)), reverse=True)
        folder_attr = html.escape(folder_rel, quote=True)
        host = self.headers.get("Host", f"localhost:{PORT}")
        rows = []
        for index, name in enumerate(names):
            full = os.path.join(folder_abs, name)
            is_dir = os.path.isdir(full)
            ext = os.path.splitext(name)[1].lower()
            name_esc = html.escape(name, quote=True)
            sub_rel = (folder_rel + "/" + name) if folder_rel else name
            sub_q = urllib.parse.quote(sub_rel)
            link_url = f"http://{host}/{sub_q}" + ("/" if is_dir else "")
            mtime = datetime.fromtimestamp(os.path.getmtime(full)).strftime("%Y-%m-%d %H:%M")

            icon = "📁" if is_dir else ICONS.get(ext, "📄")
            is_image = not is_dir and ext in THUMB_EXTS
            if is_image and os.path.getsize(full) <= THUMB_MAX_BYTES:
                icon = (
                    f'<a class="lb" href="/{sub_q}" tabindex="-1" aria-hidden="true">'
                    f'<img src="/{sub_q}" alt="" loading="lazy"></a>'
                )
            if is_dir:
                try:
                    inside = len([n for n in os.listdir(full) if not n.startswith(".")])
                except OSError:
                    inside = 0
                title = f'<a class="item-name" href="/admin?folder={sub_q}">{name_esc}</a>'
                meta = [f"文件夹 · {inside} 项", f"修改于 {mtime}"]
            else:
                if is_image:
                    title = f'<a class="item-name lb" href="/{sub_q}">{name_esc}</a>'
                else:
                    title = f'<span class="item-name">{name_esc}</span>'
                meta = [human_size(os.path.getsize(full)), f"修改于 {mtime}"]
            meta_html = "".join(f"<span>{m}</span>" for m in meta)

            fields = f"""
        <form method="post" action="/rename" class="field">
          <input type="hidden" name="folder" value="{folder_attr}">
          <input type="hidden" name="old_name" value="{name_esc}">
          <label for="rename-{index}">改名</label>
          <div class="group">
            <input type="text" class="text-input" id="rename-{index}" name="new_name" value="{name_esc}" required>
            <button type="submit" class="btn btn-soft">保存</button>
          </div>
        </form>"""
            if is_dir and not folder_rel:
                password = folder_password(name)
                if password:
                    meta_html += '<span class="badge">🔒 独立密码</span>'
                elif not VIEW_PASS:
                    meta_html += '<span class="badge warn">🔓 无密码，有链接即可打开</span>'
                expires = folder_expiry(name)
                if expires:
                    left = max(0, expires - time.time()) / 86400
                    when = datetime.fromtimestamp(expires).strftime("%Y-%m-%d %H:%M")
                    meta_html += f'<span class="badge warn">⏳ {when} 自动删除（还剩 {left:.1f} 天）</span>'
                fields += f"""
        <form method="post" action="/setpass" class="field">
          <input type="hidden" name="name" value="{name_esc}">
          <label for="pass-{index}">访问密码</label>
          <div class="group">
            <input type="text" class="text-input" id="pass-{index}" name="password" value="{html.escape(password, quote=True)}" placeholder="未单独设置" autocomplete="off">
            <button type="submit" class="btn btn-soft">保存</button>
          </div>
          <p class="hint">只对这个文件夹有效。{"留空＝使用通用密码。" if VIEW_PASS else "留空＝不设密码，知道链接的人都能打开。"}</p>
        </form>
        <form method="post" action="/setexpiry" class="field">
          <input type="hidden" name="name" value="{name_esc}">
          <label for="days-{index}">几天后自动删除</label>
          <div class="group">
            <input type="number" class="text-input" id="days-{index}" name="days" min="0" max="3650" step="any" placeholder="不过期">
            <button type="submit" class="btn btn-soft">保存</button>
          </div>
          <p class="hint">从现在算起。到期后整个文件夹会被删除，无法恢复。留空或 0＝不过期。</p>
        </form>"""

            rows.append(f"""    <div class="item">
      <div class="item-head">
        <div class="item-icon">{icon}</div>
        <div class="item-title">
          {title}
          <div class="item-meta">{meta_html}</div>
        </div>
        <div class="item-actions">
          <button type="button" class="btn btn-soft" onclick="copyLink('{link_url}', this)">🔗 复制链接</button>
          <button type="button" class="btn btn-soft qr-btn" data-qr="{link_url}" data-name="{name_esc}">▦ 二维码</button>
          <button type="button" class="btn btn-ghost" aria-expanded="false" aria-controls="fields-{index}" onclick="toggleFields(this)">⚙ 设置</button>
          <form method="post" action="/delete" onsubmit="return confirm('确定删除「{name_esc}」吗？此操作无法撤销。');">
            <input type="hidden" name="folder" value="{folder_attr}">
            <input type="hidden" name="name" value="{name_esc}">
            <button type="submit" class="btn btn-danger">删除</button>
          </form>
        </div>
      </div>
      <div class="item-fields" id="fields-{index}" hidden>{fields}
      </div>
    </div>""")
        return "\n".join(rows), f"共 {len(names)} 项"

    def handle_upload(self):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            self.send_error(413, "Payload Too Large")
            return
        content_type = self.headers.get("Content-Type", "")
        boundary = get_boundary(content_type)
        if not boundary:
            self.send_error(400, "Bad Request")
            return
        data = self.rfile.read(length)
        fields, files = parse_multipart(data, boundary)
        folder = fields.get("folder", [""])[0]
        try:
            target_dir = safe_join(SHARE_DIR, folder)
        except ValueError:
            self.send_error(400, "Bad Request")
            return
        os.makedirs(target_dir, exist_ok=True)
        saved = 0
        for _, filename, content in files:
            filename = os.path.basename(filename)
            if not filename or filename.startswith("."):
                continue
            # Never replace an existing file: a second "a.pdf" is saved as "a (1).pdf".
            with open(unique_path(target_dir, filename), "wb") as f:
                f.write(content)
            saved += 1
        self._back_to_manage(folder, f"uploaded:{saved}" if saved else "failed")

    def handle_mkdir(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", "replace")
        data = urllib.parse.parse_qs(raw)
        folder = data.get("folder", [""])[0]
        name = data.get("name", [""])[0].strip()
        try:
            parent = safe_join(SHARE_DIR, folder)
        except ValueError:
            self.send_error(400, "Bad Request")
            return
        if not name or "/" in name or name.startswith("."):
            self._back_to_manage(folder, "failed")
            return
        if os.path.exists(os.path.join(parent, name)):
            self._back_to_manage(folder, "exists")
            return
        os.makedirs(os.path.join(parent, name))
        self._back_to_manage(folder, "created")

    def handle_delete(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", "replace")
        data = urllib.parse.parse_qs(raw)
        folder = data.get("folder", [""])[0]
        name = data.get("name", [""])[0]
        if not name or "/" in name or name in (".", ".."):
            self._back_to_manage(folder, "failed")
            return
        try:
            parent = safe_join(SHARE_DIR, folder)
        except ValueError:
            self.send_error(400, "Bad Request")
            return
        target = os.path.join(parent, name)
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        elif os.path.isfile(target):
            os.remove(target)
        else:
            self._back_to_manage(folder, "failed")
            return
        self._back_to_manage(folder, "deleted")

    def handle_rename(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", "replace")
        data = urllib.parse.parse_qs(raw)
        folder = data.get("folder", [""])[0]
        old_name = data.get("old_name", [""])[0]
        new_name = data.get("new_name", [""])[0].strip()
        try:
            parent = safe_join(SHARE_DIR, folder)
        except ValueError:
            self.send_error(400, "Bad Request")
            return
        invalid = (
            not old_name or not new_name
            or "/" in old_name or "/" in new_name
            or old_name.startswith(".") or new_name.startswith(".")
        )
        if invalid:
            self._back_to_manage(folder, "failed")
            return
        old_path = os.path.join(parent, old_name)
        new_path = os.path.join(parent, new_name)
        if not os.path.exists(old_path):
            self._back_to_manage(folder, "failed")
            return
        if old_name == new_name:
            self._back_to_manage(folder, "renamed")
            return
        if os.path.exists(new_path):
            self._back_to_manage(folder, "exists")
            return
        os.rename(old_path, new_path)
        self._back_to_manage(folder, "renamed")

    def handle_setpass(self):
        """Set or clear (empty value) the viewing password of a top-level folder."""
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", "replace")
        data = urllib.parse.parse_qs(raw, keep_blank_values=True)
        name = data.get("name", [""])[0]
        password = data.get("password", [""])[0].strip()[:200]
        folder = os.path.join(SHARE_DIR, name)
        if not name or "/" in name or name.startswith(".") or not os.path.isdir(folder):
            self.send_error(400, "Bad Request")
            return
        pass_file = os.path.join(folder, FOLDER_PASS_FILE)
        if password:
            with open(pass_file, "w", encoding="utf-8") as f:
                f.write(password + "\n")
        elif os.path.exists(pass_file):
            os.remove(pass_file)
        self._back_to_manage("", "pass_set" if password else "pass_cleared")

    def handle_setexpiry(self):
        """Set (days from now) or clear (empty or 0) the expiry of a top-level folder."""
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", "replace")
        data = urllib.parse.parse_qs(raw, keep_blank_values=True)
        name = data.get("name", [""])[0]
        folder = os.path.join(SHARE_DIR, name)
        if not name or "/" in name or name.startswith(".") or not os.path.isdir(folder):
            self.send_error(400, "Bad Request")
            return
        try:
            days = float(data.get("days", [""])[0].strip() or 0)
        except ValueError:
            self._back_to_manage("", "failed")
            return
        if not 0 <= days <= 3650:
            self._back_to_manage("", "failed")
            return
        expiry_file = os.path.join(folder, FOLDER_EXPIRY_FILE)
        if days > 0:
            with open(expiry_file, "w", encoding="utf-8") as f:
                f.write(str(int(time.time() + days * 86400)) + "\n")
        elif os.path.exists(expiry_file):
            os.remove(expiry_file)
        self._back_to_manage("", "expiry_set" if days > 0 else "expiry_cleared")

    def _back_to_manage(self, folder, msg):
        """Return to the management page of a folder, showing what just happened."""
        self._redirect(f"/admin?folder={urllib.parse.quote(folder.strip('/'))}&msg={msg}")

    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()


def main():
    os.makedirs(SHARE_DIR, exist_ok=True)
    if not UPLOAD_PASS:
        raise SystemExit("UPLOAD_PASS environment variable must be set")
    handler = partial(ShareHandler, directory=SHARE_DIR)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), handler)
    threading.Thread(target=sweep_expired, daemon=True).start()
    print(f"Serving {SHARE_DIR} on port {PORT}; upload user={UPLOAD_USER}; viewing password {'on' if VIEW_PASS else 'off'}")
    server.serve_forever()


if __name__ == "__main__":
    main()
