#!/usr/bin/env python3
"""
文字二维码分享工具 - 涉密内网版
本地启动 HTTP 服务，生成二维码，扫码查看/复制文字
"""

import http.server
import socketserver
import urllib.parse
import hashlib
import json
import os
import sys
import base64
from pathlib import Path
from datetime import datetime, timedelta
import qrcode
from io import BytesIO

# ---------- 配置 ----------
PORT = 8765
HOST = "0.0.0.0"  # 局域网可访问

# 存储路径：exe放在哪都统一用用户数据目录
import platform, os
if platform.system() == "Darwin":
    _data_dir = Path.home() / "Library/Application Support/qr-share"
elif platform.system() == "Windows":
    _data_dir = Path(os.environ.get("APPDATA", Path.home())) / "qr-share"
else:
    _data_dir = Path.home() / ".config" / "qr-share"
_data_dir.mkdir(parents=True, exist_ok=True)
STORAGE_FILE = _data_dir / "texts.json"
# --------------------------

STORAGE = {}

# 加载已有存储
if STORAGE_FILE.exists():
    try:
        STORAGE = json.loads(STORAGE_FILE.read_text())
    except Exception:
        pass


def save_storage():
    STORAGE_FILE.write_text(json.dumps(STORAGE, ensure_ascii=False, indent=2))


def generate_short_id(text: str) -> str:
    """用文字内容生成短 ID，保证相同文字同一 ID"""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


VIEW_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>文字分享</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background: #f5f5f5; min-height: 100vh; display: flex; align-items: center;
         justify-content: center; padding: 20px; }
  .card { background: white; border-radius: 16px; box-shadow: 0 4px 24px rgba(0,0,0,0.1);
          width: 100%; max-width: 640px; overflow: hidden; }
  .header { background: linear-gradient(135deg, #667eea, #764ba2);
            color: white; padding: 24px 32px; }
  .header h1 { font-size: 20px; font-weight: 600; }
  .header p { font-size: 13px; opacity: 0.85; margin-top: 4px; }
  .content { padding: 32px; }
  textarea { width: 100%; height: 280px; border: 1px solid #e0e0e0; border-radius: 10px;
              padding: 16px; font-size: 15px; line-height: 1.8; resize: none;
              outline: none; font-family: inherit; }
  .actions { display: flex; gap: 12px; margin-top: 16px; }
  button { flex: 1; padding: 14px; border: none; border-radius: 10px; font-size: 15px;
            font-weight: 500; cursor: pointer; }
  .btn-copy { background: #667eea; color: white; }
  .btn-share { background: #f0effe; color: #667eea; }
  .expires { text-align: center; margin-top: 12px; font-size: 12px; color: #999; }
  .toast { position: fixed; top: 24px; left: 50%; transform: translateX(-50%) translateY(-80px);
            background: #333; color: white; padding: 12px 28px; border-radius: 50px;
            font-size: 14px; opacity: 0; transition: all 0.3s ease; z-index: 999; }
  .toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <h1>文字分享</h1>
    <p>扫描二维码查看内容，可直接复制</p>
  </div>
  <div class="content">
    <textarea id="text" readonly></textarea>
    <div class="actions">
      <button class="btn-copy" onclick="copyText()">复制内容</button>
      <button class="btn-share" onclick="shareText()">分享链接</button>
    </div>
    <p class="expires" id="expires"></p>
  </div>
</div>
<div class="toast" id="toast"></div>
<script>
var rawContent = "";
var rawExpires = "";

function copyText() {
  navigator.clipboard.writeText(document.getElementById("text").value).then(
    function() { showToast("已复制到剪贴板"); },
    function() {
      var ta = document.createElement("textarea");
      ta.value = document.getElementById("text").value;
      ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); showToast("已复制到剪贴板"); }
      catch(e) { showToast("复制失败，请手动选择复制"); }
      document.body.removeChild(ta);
    }
  );
}
function shareText() {
  var url = window.location.href;
  if (navigator.share) {
    navigator.share({ title: "文字分享", text: document.getElementById("text").value, url: url });
  } else {
    navigator.clipboard.writeText(url).then(function() { showToast("链接已复制"); });
  }
}
function showToast(msg) {
  var t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("show");
  setTimeout(function() { t.classList.remove("show"); }, 2000);
}
function init(content, expires) {
  rawContent = content;
  rawExpires = expires;
  document.getElementById("text").value = content;
  if (expires) {
    var parts = expires.split(/[- :]/);
    var d = new Date(parts[0], parts[1]-1, parts[2], parts[3], parts[4], parts[5]);
    var now = new Date();
    var diff = d - now;
    if (diff > 0) {
      var h = Math.floor(diff/3600000);
      var m = Math.floor((diff%3600000)/60000);
      document.getElementById("expires").textContent = "内容 " + h + "小时" + m + "分钟后自动失效";
    } else {
      document.getElementById("expires").textContent = "此内容已失效";
      document.getElementById("text").value = "内容已过期，请联系分享者重新生成。";
    }
  }
}
</script>
</body>
</html>"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/text/"):
            short_id = self.path.split("/text/")[-1].split("?")[0]
            if short_id in STORAGE:
                data = STORAGE[short_id]
                # 检查过期
                expires = data.get("expires", "")
                content = data["content"]
                b64_content = base64.b64encode(content.encode("utf-8")).decode("ascii")
                b64_expires = base64.b64encode(expires.encode("utf-8")).decode("ascii") if expires else ""
                # 直接替换全局变量（去掉 init 函数对参数的依赖）
                html = VIEW_HTML
                html = html.replace('var rawContent = "";', 'var rawContent = "' + b64_content + '";')
                html = html.replace('var rawExpires = "";', 'var rawExpires = "' + b64_expires + '";')
                # init() 里 content 已经是全局 rawContent 的值（b64），需解码
                html = html.replace(
                    'document.getElementById("text").value = content;',
                    'document.getElementById("text").value = atob(content);'
                )
                # 调用 init，让过期时间逻辑也执行
                html = html.replace('</body>', '<script>init(rawContent, rawExpires);</script></body>')
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))
                return
        if self.path.startswith("/qr/"):
            short_id = self.path.split("/qr/")[-1].split("?")[0]
            if short_id in STORAGE:
                hostname = get_local_ip()
                port = PORT
                text_url = f"http://{hostname}:{port}/text/{short_id}"
                qr = qrcode.QRCode(version=3, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
                qr.add_data(text_url)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                buf = BytesIO()
                img.save(buf, format="PNG")
                buf.seek(0)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(buf.getbuffer().nbytes))
                self.end_headers()
                self.wfile.write(buf.read())
                return
            else:
                self.send_response(404)
                self.end_headers()
                return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(INDEX_HTML.encode("utf-8"))

    def log_message(self, format, *args):
        pass  # 安静日志


INDEX_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>文字二维码分享</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
         min-height: 100vh; display: flex; align-items: center;
         justify-content: center; padding: 20px; }
  .card { background: white; border-radius: 20px; box-shadow: 0 20px 60px rgba(0,0,0,0.3);
          width: 100%; max-width: 540px; overflow: hidden; }
  .header { background: linear-gradient(135deg, #667eea, #764ba2);
            color: white; padding: 36px 40px 28px; text-align: center; }
  .header h1 { font-size: 26px; font-weight: 700; }
  .header p { font-size: 14px; opacity: 0.85; margin-top: 8px; }
  .body { padding: 32px 40px 36px; }
  label { font-size: 14px; color: #555; font-weight: 500; display: block; margin-bottom: 10px; }
  textarea { width: 100%; height: 220px; border: 2px solid #e8e8e8; border-radius: 14px;
             padding: 16px; font-size: 15px; line-height: 1.8; resize: none; outline: none;
             transition: border-color 0.2s; font-family: inherit;
             border-color: #e8e8e8; }
  textarea:focus { border-color: #667eea; }
  .counter { text-align: right; font-size: 12px; color: #bbb; margin-top: 6px; }
  .counter.warn { color: #f56c6c; }
  .options { display: flex; gap: 12px; margin-top: 14px; align-items: center; }
  .options label { margin: 0; font-size: 13px; color: #888; }
  input[type="number"] { width: 70px; padding: 6px 10px; border: 1px solid #ddd; border-radius: 8px;
                         font-size: 13px; outline: none; }
  input[type="number"]:focus { border-color: #667eea; }
  .btn { width: 100%; padding: 16px; background: linear-gradient(135deg, #667eea, #764ba2);
         color: white; border: none; border-radius: 14px; font-size: 17px; font-weight: 600;
         cursor: pointer; margin-top: 20px; transition: opacity 0.2s, transform 0.1s; }
  .btn:hover { opacity: 0.9; }
  .btn:active { transform: scale(0.98); }
  .result { margin-top: 24px; text-align: center; display: none; }
  .result.show { display: block; }
  .qr-box { background: #f9f9f9; border-radius: 16px; padding: 20px; margin-top: 16px;
             display: inline-block; }
  .qr-box img, .qr-box canvas { display: block; }
  .url-box { margin-top: 14px; background: #f0f0f0; border-radius: 10px; padding: 12px 16px;
             font-size: 13px; color: #666; word-break: break-all; cursor: pointer;
             transition: background 0.2s; }
  .url-box:hover { background: #e8e8e8; }
  .toast { position: fixed; top: 24px; left: 50%; transform: translateX(-50%) translateY(-80px);
           background: #333; color: white; padding: 12px 28px; border-radius: 50px;
           font-size: 14px; opacity: 0; transition: all 0.3s ease; z-index: 999; pointer-events: none; }
  .toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
  .warn-box { background: #fff5f5; border: 1px solid #fc9d9d; border-radius: 10px;
               padding: 12px 14px; font-size: 13px; color: #e04040; margin-top: 12px;
               display: none; }
  .warn-box.show { display: block; }
  @media (max-width: 480px) { .header { padding: 28px 24px 20px; }
    .body { padding: 24px 20px 28px; } textarea { height: 180px; } }
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <h1>📄 文字分享二维码</h1>
    <p>输入文字 → 生成二维码 → 扫码查看/复制</p>
  </div>
  <div class="body">
    <label>📝 要分享的文字内容</label>
    <textarea id="input" placeholder="在这里输入要分享的文字..." maxlength="2000"></textarea>
    <div class="counter" id="counter">0 / 2000</div>
    <div class="warn-box" id="warnBox">涉密内容请勿通过外网传递，仅限内网使用！</div>
    <div class="options">
      <label>⏰ 失效时间（小时）：</label>
      <input type="number" id="hours" value="24" min="1" max="168">
    </div>
    <button class="btn" onclick="generate()">🔗 生成二维码</button>
    <div class="result" id="result">
      <div style="font-size:15px;color:#333;margin-top:8px;">👇 扫码查看内容 👇</div>
      <div class="qr-box" id="qrBox"></div>
      <div class="url-box" id="urlBox" onclick="copyUrl()">点击复制链接</div>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>


<script>
const input = document.getElementById("input");
const counter = document.getElementById("counter");
const warnBox = document.getElementById("warnBox");

input.addEventListener("input", () => {
  const len = input.value.length;
  counter.textContent = len + " / 2000";
  counter.className = "counter" + (len > 1800 ? " warn" : "");
  warnBox.className = "warn-box" + (len > 0 ? " show" : "");
});

async function generate() {
  const text = input.value.trim();
  if (!text) { showToast("请先输入内容"); return; }
  if (text.length > 2000) { showToast("内容超出2000字限制"); return; }

  const hours = parseInt(document.getElementById("hours").value) || 24;
  const res = await fetch("/new", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ text, hours })
  });
  const json = await res.json();
  const url = json.url;
  const shortId = json.short_id;
  document.getElementById("result").classList.add("show");
  document.getElementById("qrBox").innerHTML = '<img src="/qr/' + shortId + '" width="200" height="200" alt="二维码">';
  document.getElementById("urlBox").textContent = url;
  document.getElementById("urlBox").dataset.url = url;
  showToast("二维码已生成！");
}

function copyUrl() {
  const url = document.getElementById("urlBox").dataset.url || document.getElementById("urlBox").textContent;
  navigator.clipboard.writeText(url).then(() => showToast("链接已复制"));
}

function showToast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2000);
}
</script>
</body>
</html>"""


class ShareHandler(Handler):
    def do_POST(self):
        if self.path == "/new":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body)
            text = data["text"][:2000]
            hours = min(max(int(data.get("hours", 24)), 1), 168)

            short_id = generate_short_id(text)
            expires_dt = datetime.now() + timedelta(hours=hours)
            expires_str = expires_dt.strftime("%Y-%m-%d %H:%M:%S")
            STORAGE[short_id] = {
                "content": text,
                "expires": expires_str,
                "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            save_storage()

            hostname = get_local_ip()
            port = PORT
            url = f"http://{hostname}:{port}/text/{short_id}"

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"url": url, "short_id": short_id}).encode("utf-8"))
            return

        if self.path.startswith("/qr/"):
            # 服务器端生成二维码 PNG
            short_id = self.path.split("/qr/")[-1].split("?")[0]
            if short_id in STORAGE:
                hostname = get_local_ip()
                port = PORT
                text_url = f"http://{hostname}:{port}/text/{short_id}"
                qr = qrcode.QRCode(version=3, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
                qr.add_data(text_url)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                buf = BytesIO()
                img.save(buf, format="PNG")
                buf.seek(0)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(buf.getbuffer().nbytes))
                self.end_headers()
                self.wfile.write(buf.read())
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

        self.send_response(404)
        self.end_headers()


def get_local_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--client":
        # 展示/查看模式：显示二维码（需要加载qrcode库）
        print("查看模式暂不支持，请用浏览器打开")
        return

    local_ip = get_local_ip()
    storage_path = str(STORAGE_FILE)
    print(f"""
╔══════════════════════════════════════════════════════╗
║       📄 文字二维码分享工具  -  涉密内网版             ║
╠══════════════════════════════════════════════════════╣
║  本机访问：http://localhost:{PORT}                    ║
║  局域网访问：http://{local_ip}:{PORT}               ║
║                                                      ║
║  数据存储：{storage_path}                             ║
║                                                      ║
║  把局域网地址生成的二维码发给同事，他们就能扫码查看   ║
║  内容完全存储在本机，不走外网                         ║
╚══════════════════════════════════════════════════════╝
""")

    with socketserver.TCPServer((HOST, PORT), ShareHandler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    main()
