#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地 IPC Bridge（HTTP）
供 AutoCAD C# 插件调用，控制已运行的 Python UI。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional, Dict, Any


class _BridgeHandler(BaseHTTPRequestHandler):
    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _write_json(self, status: int, payload: Dict[str, Any]):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # 避免刷屏
        return

    def do_GET(self):
        server: "AICADBridgeServer" = self.server.bridge_owner  # type: ignore[attr-defined]

        if self.path == "/health":
            self._write_json(200, {"ok": True, "service": "ai-cad-ui-bridge"})
            return

        if self.path.startswith("/last_ai"):
            since = 0
            try:
                if "?" in self.path:
                    query = self.path.split("?", 1)[1]
                    for pair in query.split("&"):
                        if pair.startswith("since="):
                            since = int(pair.split("=", 1)[1] or 0)
                            break
            except Exception:
                since = 0

            payload = {"ok": True, "has_new": False, "seq": since, "message": ""}
            if server.on_get_last_ai:
                data = server.on_get_last_ai(since) or {}
                payload.update(data)
            self._write_json(200, payload)
            return

        self._write_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        server: "AICADBridgeServer" = self.server.bridge_owner  # type: ignore[attr-defined]

        if self.path == "/show":
            if server.on_show:
                server.on_show()
            self._write_json(200, {"ok": True})
            return

        if self.path == "/stop":
            if server.on_stop:
                server.on_stop()
            self._write_json(200, {"ok": True})
            return

        if self.path == "/chat":
            data = self._read_json()
            text = (data.get("text") or "").strip()
            if not text:
                self._write_json(400, {"ok": False, "error": "text_required"})
                return
            message = "请求已提交到 AI，处理中..."
            if server.on_chat:
                ret = server.on_chat(text)
                if isinstance(ret, str) and ret.strip():
                    message = ret.strip()
            self._write_json(200, {"ok": True, "message": message})
            return

        self._write_json(404, {"ok": False, "error": "not_found"})


class AICADBridgeServer:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        on_show: Optional[Callable[[], None]] = None,
        on_stop: Optional[Callable[[], None]] = None,
        on_chat: Optional[Callable[[str], Optional[str]]] = None,
        on_get_last_ai: Optional[Callable[[int], Optional[Dict[str, Any]]]] = None,
    ):
        self.host = host
        self.port = port
        self.on_show = on_show
        self.on_stop = on_stop
        self.on_chat = on_chat
        self.on_get_last_ai = on_get_last_ai

        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._server is not None:
            return
        self._server = ThreadingHTTPServer((self.host, self.port), _BridgeHandler)
        self._server.bridge_owner = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._server is None:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        finally:
            self._server = None
            self._thread = None
