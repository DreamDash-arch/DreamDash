#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""梦幻跑跑 · DreamDash 局域网联机主机

零依赖（只用 Python 3 标准库）：
  * 托管静态页面（index.html / assets/*）
  * 提供最小 WebSocket 服务，按房间码把主机与客机互相中继消息
  * 启动后打印所有可用的局域网地址，客机用浏览器打开即可加入

用法：
  python3 server.py                # 默认 0.0.0.0:8000
  python3 server.py --port 9000
"""

import argparse
import base64
import hashlib
import json
import os
import socket
import struct
import sys
import threading
import time
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_PAYLOAD = 256 * 1024
ROOM_TTL = 30 * 60
ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

ROOMS = {}
ROOMS_LOCK = threading.Lock()
VERSION = "dev"
LAN_URLS = []
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def short_version():
    """index.html 的内容指纹，用来确认两端拿到的是同一份代码。"""
    try:
        with open(os.path.join(ROOT_DIR, "index.html"), "rb") as fh:
            return hashlib.sha1(fh.read()).hexdigest()[:10]
    except OSError:
        return "unknown"


def detect_lan_ips():
    ips = []
    # 1) UDP 连接外网地址，拿到默认出口网卡 IP（不会真的发包）
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.3)
        sock.connect(("8.8.8.8", 80))
        ips.append(sock.getsockname()[0])
        sock.close()
    except OSError:
        pass
    # 2) 枚举本机所有 IPv4
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    usable = [ip for ip in ips if ip and not ip.startswith("127.")]
    usable.sort(key=ip_rank)
    return usable


def ip_rank(ip):
    """把最常见的家用/办公网段排在前面，虚拟网卡（Docker 等）排后面。"""
    if ip.startswith("192.168."):
        return 0
    if ip.startswith("10."):
        return 1
    if ip.startswith("172."):
        try:
            if 16 <= int(ip.split(".")[1]) <= 31:
                return 5
        except (ValueError, IndexError):
            pass
        return 2
    if ip.startswith("169.254."):
        return 9
    return 3


def new_room_code():
    while True:
        code = "".join(ROOM_ALPHABET[b % len(ROOM_ALPHABET)] for b in os.urandom(4))
        with ROOMS_LOCK:
            if code not in ROOMS:
                return code


# --------------------------------------------------------------------------- #
# WebSocket 连接
# --------------------------------------------------------------------------- #
class WsConn:
    def __init__(self, rfile, wfile):
        self.rfile = rfile
        self.wfile = wfile
        self.alive = True
        self.lock = threading.Lock()

    # -- 发送 -------------------------------------------------------------- #
    def _write_frame(self, opcode, payload):
        header = bytearray([0x80 | opcode])
        size = len(payload)
        if size < 126:
            header.append(size)
        elif size < 65536:
            header.append(126)
            header += struct.pack(">H", size)
        else:
            header.append(127)
            header += struct.pack(">Q", size)
        with self.lock:
            if not self.alive:
                return
            try:
                self.wfile.write(bytes(header) + payload)
                self.wfile.flush()
            except Exception:
                self.alive = False

    def send_text(self, text):
        self._write_frame(0x1, text.encode("utf-8"))

    def send_json(self, obj):
        self.send_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))

    def send_pong(self, payload):
        self._write_frame(0xA, payload)

    def close(self, code=1000):
        if not self.alive:
            return
        self._write_frame(0x8, struct.pack(">H", code))
        self.alive = False

    # -- 接收 -------------------------------------------------------------- #
    def recv_frame(self):
        try:
            head = self.rfile.read(2)
            if not head or len(head) < 2:
                return None
            b1, b2 = head[0], head[1]
            opcode = b1 & 0x0F
            masked = b2 & 0x80
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self.rfile.read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self.rfile.read(8))[0]
            if length > MAX_PAYLOAD:
                return None
            mask = self.rfile.read(4) if masked else None
            payload = self.rfile.read(length) if length else b""
            if len(payload) < length:
                return None
            if mask:
                payload = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
            return opcode, payload
        except Exception:
            return None


# --------------------------------------------------------------------------- #
# 房间
# --------------------------------------------------------------------------- #
def peer_of(room, role):
    with ROOMS_LOCK:
        entry = ROOMS.get(room)
        if not entry:
            return None
        peer = entry.get("guest") if role == "host" else entry.get("host")
        return peer if (peer and peer.alive) else None


def drop_room(room):
    with ROOMS_LOCK:
        ROOMS.pop(room, None)


def sweep_rooms():
    while True:
        time.sleep(60)
        now = time.time()
        stale = []
        with ROOMS_LOCK:
            for code, entry in list(ROOMS.items()):
                if now - entry.get("last", now) > ROOM_TTL:
                    stale.append(ROOMS.pop(code))
        for entry in stale:
            for role in ("host", "guest"):
                conn = entry.get(role)
                if conn and conn.alive:
                    conn.send_json({"t": "error", "message": "房间超时已关闭"})
                    conn.close()


def serve_connection(conn, role, room):
    if role not in ("host", "guest"):
        conn.send_json({"t": "error", "message": "bad role"})
        return
    if not room:
        conn.send_json({"t": "error", "message": "缺少房间码"})
        return

    peer = None
    if role == "host":
        with ROOMS_LOCK:
            entry = ROOMS.setdefault(room, {"host": None, "guest": None, "last": time.time()})
            old = entry.get("host")
            entry["host"] = conn
            entry["last"] = time.time()
        if old and old.alive:
            old.send_json({"t": "error", "message": "房主已在别处连接"})
            old.close()
    else:
        with ROOMS_LOCK:
            entry = ROOMS.get(room)
            if not entry or not entry.get("host") or not entry["host"].alive:
                conn.send_json({"t": "error", "message": "房间不存在或房主已离开"})
                return
            old = entry.get("guest")
            entry["guest"] = conn
            entry["last"] = time.time()
        if old and old.alive:
            old.send_json({"t": "error", "message": "你已在别处加入"})
            old.close()

    conn.send_json({
        "t": "welcome",
        "role": role,
        "room": room,
        "version": VERSION,
        "urls": LAN_URLS,
    })
    peer = peer_of(room, role)
    if peer:
        peer.send_json({"t": "peer-joined", "role": role})

    try:
        while conn.alive:
            frame = conn.recv_frame()
            if frame is None:
                break
            opcode, payload = frame
            if opcode == 0x8:
                break
            if opcode == 0x9:
                conn.send_pong(payload)
                continue
            if opcode == 0xA:
                continue
            if opcode not in (0x1, 0x0):
                continue
            peer = peer_of(room, role)
            if peer:
                peer.send_text(payload.decode("utf-8", "ignore"))
                with ROOMS_LOCK:
                    if room in ROOMS:
                        ROOMS[room]["last"] = time.time()
    except Exception:
        pass
    finally:
        conn.alive = False
        peer = peer_of(room, role)
        with ROOMS_LOCK:
            entry = ROOMS.get(room)
            if entry:
                if entry.get(role) is conn:
                    entry[role] = None
                empty = not entry.get("host") and not entry.get("guest")
                if empty:
                    ROOMS.pop(room, None)
        if peer and peer.alive:
            peer.send_json({"t": "peer-left", "role": role})
            if role == "host":
                peer.close()


# --------------------------------------------------------------------------- #
# HTTP 处理
# --------------------------------------------------------------------------- #
class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT_DIR, **kwargs)

    def log_message(self, fmt, *args):
        if os.environ.get("DREAMDASH_VERBOSE"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def end_headers(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
        super().end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/ws":
            return self.handle_websocket(parsed)
        if parsed.path == "/version":
            body = json.dumps({"server": "local", "version": VERSION, "urls": LAN_URLS}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    # -- WebSocket 握手 ---------------------------------------------------- #
    def handle_websocket(self, parsed):
        key = self.headers.get("Sec-WebSocket-Key")
        upgrade = (self.headers.get("Upgrade") or "").lower()
        if not key or upgrade != "websocket":
            self.send_error(400, "Expected WebSocket upgrade")
            return
        accept = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode("utf-8")).digest()
        ).decode("ascii")
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()

        params = urllib.parse.parse_qs(parsed.query)
        role = (params.get("role") or [""])[0]
        room = ((params.get("room") or [""])[0] or "").strip().upper()
        if role == "host" and not room:
            room = new_room_code()

        conn = WsConn(self.rfile, self.wfile)
        try:
            serve_connection(conn, role, room)
        finally:
            conn.alive = False
        self.close_connection = True


def main():
    global VERSION, LAN_URLS
    parser = argparse.ArgumentParser(description="DreamDash 局域网联机主机")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        os.environ["DREAMDASH_VERBOSE"] = "1"

    VERSION = short_version()
    ips = detect_lan_ips()
    LAN_URLS = ["http://%s:%d/" % (ip, args.port) for ip in ips]

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True

    print("=" * 58)
    print("  DreamDash · 局域网联机主机已启动")
    print("=" * 58)
    print("  本机访问：   http://127.0.0.1:%d/" % args.port)
    for url in LAN_URLS:
        print("  局域网访问： %s" % url)
    print("  代码版本：   %s" % VERSION)
    print("-" * 58)
    print("  房主：浏览器打开上面的地址 → 局域网联机 → 创建房间")
    print("  客机：用房主页面显示的链接（带 ?room=XXXX）打开即可")
    print("  按 Ctrl+C 结束")
    print("=" * 58)

    threading.Thread(target=sweep_rooms, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
