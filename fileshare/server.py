#!/usr/bin/env python3
"""Minimal file-sharing server: public read-only listing/download, plus an
authenticated /upload page for adding files and creating folders."""
import base64
import html
import io
import os
import shutil
import urllib.parse
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

SHARE_DIR = os.path.abspath(os.environ.get("SHARE_DIR", "/data"))
PORT = int(os.environ.get("PORT", "8000"))
UPLOAD_USER = os.environ.get("UPLOAD_USER", "admin")
UPLOAD_PASS = os.environ.get("UPLOAD_PASS", "")
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
  :root { --ink:#1b2430; --muted:#6b7680; --line:#e2e6e4; --paper:#f6f7f6; --card:#ffffff; --accent:#1c7c82; --accent-soft:#e3f0ef; }
  @media (prefers-color-scheme: dark) {
    :root { --ink:#e8eeec; --muted:#93a3a2; --line:#2b3639; --paper:#12181c; --card:#1b262a; --accent:#59c4c0; --accent-soft:#1c2f2f; }
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--paper); color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",Helvetica,Arial,sans-serif; }
  .wrap { max-width:720px; margin:0 auto; padding:40px 20px 80px; }
  .topbar { display:flex; align-items:baseline; justify-content:space-between; gap:12px; margin-bottom:22px; }
  h1 { font-size:1.35rem; margin:0; word-break:break-all; }
  .upload-link { font-size:.85rem; color:var(--muted); text-decoration:none; white-space:nowrap; }
  .upload-link:hover { color:var(--accent); }
  table { width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
  th { text-align:left; font-size:.75rem; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; padding:12px 16px; border-bottom:1px solid var(--line); }
  td { padding:14px 16px; border-bottom:1px solid var(--line); font-size:.95rem; }
  tr:last-child td { border-bottom:none; }
  tr.parent td { color:var(--muted); }
  td.size, td.mtime { color:var(--muted); white-space:nowrap; font-variant-numeric:tabular-nums; }
  td.name a { color:var(--ink); text-decoration:none; }
  td.name a:hover { color:var(--accent); text-decoration:underline; }
  .icon { margin-right:8px; }
  .empty { text-align:center; color:var(--muted); padding:32px 16px; }
  footer { text-align:center; color:var(--muted); font-size:.8rem; margin-top:20px; }
  @media (max-width:480px) { td.mtime { display:none; } }
  .panel { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:20px 22px; margin-bottom:20px; }
  .panel h2 { font-size:1rem; margin:0 0 14px; }
  .panel label { display:block; font-size:.85rem; color:var(--muted); margin-bottom:6px; }
  .panel input[type=text], .panel input[type=file] {
    width:100%; padding:9px 10px; border:1px solid var(--line); border-radius:5px;
    background:var(--paper); color:var(--ink); font-size:.92rem; margin-bottom:14px;
  }
  .panel button {
    background:var(--accent); color:#fff; border:none; padding:9px 18px;
    border-radius:5px; font-size:.9rem; cursor:pointer;
  }
  .panel button:hover { opacity:.9; }
  .msg { padding:10px 14px; border-radius:6px; font-size:.88rem; margin-bottom:18px; }
  .msg.ok { background:var(--accent-soft); color:var(--accent); }
  .msg.err { background:#f7e9e5; color:#a8452e; }
  .manage-row td { vertical-align:middle; }
  .manage-row .name a { color:var(--ink); text-decoration:none; }
  .manage-row .name a:hover { color:var(--accent); text-decoration:underline; }
  .actions { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
  .actions form { display:flex; gap:6px; align-items:center; margin:0; }
  .rename-input {
    width:120px; padding:6px 8px; border:1px solid var(--line); border-radius:4px;
    background:var(--paper); color:var(--ink); font-size:.85rem; margin:0;
  }
  .btn-mini {
    background:var(--accent-soft); color:var(--accent); border:none; padding:6px 12px;
    border-radius:4px; font-size:.82rem; cursor:pointer; white-space:nowrap;
  }
  .btn-mini:hover { opacity:.85; }
  .btn-mini.btn-danger { background:#f7e9e5; color:#a8452e; }
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
    <a class="upload-link" href="/upload?folder={folder_q}">📤 上传 / 新建文件夹</a>
  </div>
  <table>
    <thead><tr><th>文件名</th><th>大小</th><th>修改时间</th></tr></thead>
    <tbody>
{rows}
    </tbody>
  </table>
  <footer>共 {count} 项</footer>
</div>
</body>
</html>"""

UPLOAD_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>上传文件</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{style}</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <h1>📤 上传到 /{folder_display}</h1>
    <a class="upload-link" href="/{folder_href}">← 返回列表</a>
  </div>
  {message}
  <div class="panel">
    <h2>当前文件夹内容</h2>
    <table>
      <thead><tr><th>名称</th><th>操作</th></tr></thead>
      <tbody>
{manage_rows}
      </tbody>
    </table>
  </div>
  <div class="panel">
    <h2>上传文件</h2>
    <form method="post" action="/upload" enctype="multipart/form-data">
      <input type="hidden" name="folder" value="{folder_attr}">
      <label>选择一个或多个文件</label>
      <input type="file" name="files" multiple required>
      <button type="submit">上传</button>
    </form>
  </div>
  <div class="panel">
    <h2>新建文件夹</h2>
    <form method="post" action="/mkdir">
      <input type="hidden" name="folder" value="{folder_attr}">
      <label>文件夹名称</label>
      <input type="text" name="name" placeholder="例如：合同" required>
      <button type="submit">创建</button>
    </form>
  </div>
</div>
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
        if rel:
            rows.append('    <tr class="parent"><td colspan="3">⬆ <a href="../">上一级目录</a></td></tr>')

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
            rows.append(
                f'    <tr><td class="name"><span class="icon">{icon}</span>'
                f'<a href="{link}">{html.escape(display)}</a></td>'
                f'<td class="size">{size_str}</td><td class="mtime">{mtime}</td></tr>'
            )

        count = len(rows) - (1 if rel else 0)
        title = urllib.parse.unquote(self.path) or "/"
        body = LIST_TEMPLATE.format(
            title=html.escape(title),
            style=PAGE_STYLE,
            folder_q=urllib.parse.quote(rel),
            rows="\n".join(rows) if rows else '    <tr><td colspan="3" class="empty">暂无文件</td></tr>',
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

    def check_auth(self):
        expected = "Basic " + base64.b64encode(f"{UPLOAD_USER}:{UPLOAD_PASS}".encode()).decode()
        if self.headers.get("Authorization") == expected:
            return True
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
        if parsed.path == "/upload":
            if not self.check_auth():
                return
            self.serve_upload_page(parsed)
            return
        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
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
        else:
            self.send_error(404)

    # ---------- upload page + handlers ----------

    def serve_upload_page(self, parsed, message=""):
        qs = urllib.parse.parse_qs(parsed.query)
        folder = qs.get("folder", [""])[0].strip("/")
        try:
            folder_abs = safe_join(SHARE_DIR, folder)
        except ValueError:
            folder = ""
            folder_abs = SHARE_DIR
        body = UPLOAD_TEMPLATE.format(
            style=PAGE_STYLE,
            folder_display=html.escape(folder) if folder else "",
            folder_href=urllib.parse.quote(folder) + ("/" if folder else ""),
            folder_attr=html.escape(folder),
            manage_rows=self._manage_rows(folder_abs, folder),
            message=message,
        )
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _manage_rows(self, folder_abs, folder_rel):
        try:
            names = [n for n in os.listdir(folder_abs) if not n.startswith(".")]
        except OSError:
            return '    <tr><td colspan="2" class="empty">文件夹不存在</td></tr>'
        if not names:
            return '    <tr><td colspan="2" class="empty">此文件夹为空</td></tr>'
        names.sort(key=lambda n: os.path.getmtime(os.path.join(folder_abs, n)), reverse=True)
        folder_attr = html.escape(folder_rel)
        rows = []
        for name in names:
            full = os.path.join(folder_abs, name)
            is_dir = os.path.isdir(full)
            ext = os.path.splitext(name)[1].lower()
            icon = "📁" if is_dir else ICONS.get(ext, "📄")
            name_esc = html.escape(name)
            sub_rel = (folder_rel + "/" + name) if folder_rel else name
            if is_dir:
                name_cell = f'<a href="/upload?folder={urllib.parse.quote(sub_rel)}">{icon} {name_esc}</a>'
            else:
                name_cell = f'{icon} {name_esc}'
            rows.append(f"""    <tr class="manage-row">
      <td class="name">{name_cell}</td>
      <td class="actions">
        <form method="post" action="/rename">
          <input type="hidden" name="folder" value="{folder_attr}">
          <input type="hidden" name="old_name" value="{name_esc}">
          <input type="text" name="new_name" value="{name_esc}" class="rename-input">
          <button type="submit" class="btn-mini">改名</button>
        </form>
        <form method="post" action="/delete" onsubmit="return confirm('确定删除「{name_esc}」吗？此操作无法撤销。');">
          <input type="hidden" name="folder" value="{folder_attr}">
          <input type="hidden" name="name" value="{name_esc}">
          <button type="submit" class="btn-mini btn-danger">删除</button>
        </form>
      </td>
    </tr>""")
        return "\n".join(rows)

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
            if not filename:
                continue
            with open(os.path.join(target_dir, filename), "wb") as f:
                f.write(content)
            saved += 1
        self._redirect_to_folder(folder, ok=saved > 0)

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
        if not name or "/" in name or name in (".", ".."):
            self._redirect(f"/upload?folder={urllib.parse.quote(folder)}")
            return
        os.makedirs(os.path.join(parent, name), exist_ok=True)
        self._redirect_to_folder(folder, ok=True)

    def handle_delete(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", "replace")
        data = urllib.parse.parse_qs(raw)
        folder = data.get("folder", [""])[0]
        name = data.get("name", [""])[0]
        if not name or "/" in name or name in (".", ".."):
            self._redirect_to_folder(folder, ok=False)
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
        self._redirect_to_folder(folder, ok=True)

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
            or old_name in (".", "..") or new_name in (".", "..")
        )
        if invalid:
            self._redirect_to_folder(folder, ok=False)
            return
        old_path = os.path.join(parent, old_name)
        new_path = os.path.join(parent, new_name)
        if os.path.exists(old_path) and not os.path.exists(new_path):
            os.rename(old_path, new_path)
        self._redirect_to_folder(folder, ok=True)

    def _redirect_to_folder(self, folder, ok):
        location = "/" + urllib.parse.quote(folder) + ("/" if folder else "")
        self._redirect(location)

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
    print(f"Serving {SHARE_DIR} on port {PORT}; upload user={UPLOAD_USER}")
    server.serve_forever()


if __name__ == "__main__":
    main()
