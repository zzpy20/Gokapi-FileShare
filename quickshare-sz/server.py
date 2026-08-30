#!/usr/bin/env python3
"""Filesystem-backed quickshare clone: token-gated upload -> random-id public link.
No listing, no database -- the directory named by the random id is the index."""
import json
import mimetypes
import os
import re
import secrets
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATA_DIR = os.path.abspath(os.environ.get("DATA_DIR", "/data"))
PORT = int(os.environ.get("PORT", "8000"))
UPLOAD_TOKEN = os.environ.get("UPLOAD_TOKEN", "")
MAX_UPLOAD_BYTES = 500 * 1024 * 1024

ID_RE = re.compile(r"^[0-9a-f]{12}$")

UPLOAD_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>快速分享</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { --ink:#1b2430; --muted:#6b7680; --line:#e2e6e4; --paper:#f6f7f6; --card:#ffffff; --accent:#1c7c82; }
  @media (prefers-color-scheme: dark) {
    :root { --ink:#e8eeec; --muted:#93a3a2; --line:#2b3639; --paper:#12181c; --card:#1b262a; --accent:#59c4c0; }
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--paper); color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif; }
  .wrap { max-width:440px; margin:0 auto; padding:64px 20px; }
  h1 { font-size:1.4rem; margin:0 0 24px; }
  .panel { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:22px; }
  label { display:block; font-size:.85rem; color:var(--muted); margin-bottom:6px; }
  input[type=password], input[type=file] {
    width:100%; padding:9px 10px; border:1px solid var(--line); border-radius:5px;
    background:var(--paper); color:var(--ink); font-size:.92rem; margin-bottom:16px;
  }
  button { background:var(--accent); color:#fff; border:none; padding:10px 20px;
    border-radius:5px; font-size:.92rem; cursor:pointer; width:100%; }
  button:hover { opacity:.9; }
  button:disabled { opacity:.5; cursor:default; }
  #result { margin-top:18px; padding:14px; border-radius:6px; background:#e3f0ef; display:none; word-break:break-all; font-size:.9rem; }
  #result div { margin-bottom:8px; }
  #result div:last-child { margin-bottom:0; }
  #result a { color:var(--accent); }
  #err { margin-top:14px; padding:10px 14px; border-radius:6px; background:#f7e9e5; color:#a8452e; display:none; font-size:.88rem; }
</style>
</head>
<body>
<div class="wrap">
  <h1>⚡ 快速分享</h1>
  <div class="panel">
    <label for="token">上传密钥</label>
    <input type="password" id="token" placeholder="输入密钥">
    <label for="file">选择文件（可多选）</label>
    <input type="file" id="file" multiple>
    <button id="btn" onclick="doUpload()">上传并获取链接</button>
    <div id="result"></div>
    <div id="err"></div>
  </div>
</div>
<script>
  const tokenInput = document.getElementById('token');
  const saved = localStorage.getItem('upload_token');
  if (saved) tokenInput.value = saved;

  async function doUpload() {
    const token = tokenInput.value.trim();
    const fileInput = document.getElementById('file');
    const btn = document.getElementById('btn');
    const result = document.getElementById('result');
    const err = document.getElementById('err');
    result.style.display = 'none';
    err.style.display = 'none';
    if (!token) { err.textContent = '请输入密钥'; err.style.display = 'block'; return; }
    if (!fileInput.files.length) { err.textContent = '请选择文件'; err.style.display = 'block'; return; }
    localStorage.setItem('upload_token', token);
    btn.disabled = true; btn.textContent = '上传中...';
    try {
      const fd = new FormData();
      for (const f of fileInput.files) fd.append('file', f);
      const res = await fetch('/upload', { method: 'POST', headers: { 'x-upload-token': token }, body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || '上传失败');
      const links = data.results.map(r =>
        '<div>' + r.filename + '：<a href="' + window.location.origin + r.url + '" target="_blank">' +
        window.location.origin + r.url + '</a></div>'
      ).join('');
      result.innerHTML = links;
      result.style.display = 'block';
    } catch (e) {
      err.textContent = e.message;
      err.style.display = 'block';
    } finally {
      btn.disabled = false; btn.textContent = '上传并获取链接';
    }
  }
</script>
</body>
</html>"""


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


class Handler(BaseHTTPRequestHandler):
    server_version = "QuickShare/1.0"

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self._html(UPLOAD_PAGE)
        elif parsed.path.startswith("/f/"):
            self.serve_file(parsed.path)
        elif parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/upload":
            self.handle_upload()
        else:
            self.send_error(404, "Not Found")

    def _html(self, body_str, status=200):
        encoded = body_str.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _json(self, obj, status=200):
        encoded = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def serve_file(self, path):
        parts = path.split("/", 3)  # ['', 'f', '<id>', '<filename>']
        if len(parts) != 4:
            self.send_error(404, "Not Found")
            return
        _, _, file_id, filename = parts
        filename = urllib.parse.unquote(filename)
        if not ID_RE.match(file_id) or "/" in filename or filename in (".", ".."):
            self.send_error(404, "Not Found")
            return
        full = os.path.join(DATA_DIR, file_id, filename)
        if not os.path.isfile(full):
            self.send_error(404, "Not Found")
            return
        ctype, _ = mimetypes.guess_type(filename)
        ctype = ctype or "application/octet-stream"
        size = os.path.getsize(full)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f'inline; filename="{filename}"')
        self.end_headers()
        with open(full, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def handle_upload(self):
        if not UPLOAD_TOKEN or self.headers.get("x-upload-token") != UPLOAD_TOKEN:
            self._json({"error": "无效密钥"}, status=401)
            return
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            self._json({"error": "文件太大或为空"}, status=413)
            return
        content_type = self.headers.get("Content-Type", "")
        boundary = get_boundary(content_type)
        if not boundary:
            self._json({"error": "请求格式错误"}, status=400)
            return
        data = self.rfile.read(length)
        _, files = parse_multipart(data, boundary)
        if not files:
            self._json({"error": "未找到文件"}, status=400)
            return
        results = []
        for _, filename, content in files:
            filename = os.path.basename(filename)
            if not filename:
                continue
            file_id = secrets.token_hex(6)  # 12 hex chars, independent per file
            target_dir = os.path.join(DATA_DIR, file_id)
            os.makedirs(target_dir, exist_ok=True)
            with open(os.path.join(target_dir, filename), "wb") as f:
                f.write(content)
            url = f"/f/{file_id}/{urllib.parse.quote(filename)}"
            results.append({"filename": filename, "url": url})
        if not results:
            self._json({"error": "文件名无效"}, status=400)
            return
        self._json({"results": results})


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not UPLOAD_TOKEN:
        raise SystemExit("UPLOAD_TOKEN environment variable must be set")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"QuickShare serving {DATA_DIR} on port {PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
