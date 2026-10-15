"""Claude Pocket server: turns Claude Code hook events into the status the
iPhone widget shows. Runs as a plain service (main() below) or as a Vercel
function (api/pocket.py) with the board kept in Redis.

    POST /event  header X-Pocket-Key: <push key>  body: event from hook/pocket_hook.py
    GET  /state  header X-Pocket-Key: <read key>  -> {"state": {...}, "received": ts}
    GET  /widget.js header X-Pocket-Key: <read key> -> the Scriptable widget, ready to run
    GET  /health                                   -> ok

Standard library only (works on Python 3.9). Listens on 127.0.0.1; a reverse
proxy (Caddy) in front terminates HTTPS. Keys come from POCKET_PUSH_KEY and
POCKET_READ_KEY; sessions and today's totals survive restarts in POCKET_STATE.
"""

from __future__ import annotations

import hmac
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 16 * 1024
WIDGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "widget", "claude-widget.js")
STALE_S = 30 * 60          # a session silent this long is gone (terminal closed without SessionEnd)
DONE_SHOWN_S = 15 * 60     # "just finished" stays on the widget this long
MAX_SESSIONS = 40
STATES = ("think", "wait", "ask", "done", "idle")


class FileStore:
    """Board kept in a JSON file (the plain service)."""

    def __init__(self, path: str) -> None:
        self.path = path

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def save(self, data: dict) -> None:
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            pass


class Board:
    """Sessions and today's totals, updated by events."""

    def __init__(self, store) -> None:
        self.store = FileStore(store) if isinstance(store, str) else store
        self.lock = threading.Lock()
        self.sessions: dict = {}
        self.today = {"day": "", "sessions": [], "commits": 0, "hours": [0] * 24}
        self.received = 0.0
        saved = self.store.load() or {}
        self.sessions = saved.get("sessions") or {}
        self.today = saved.get("today") or self.today
        self.received = float(saved.get("received") or 0)

    # -------------------------------------------------------------- события
    def apply(self, e: dict, now: float | None = None) -> None:
        now = now or time.time()
        tz = int(e.get("tz") or 0)
        with self.lock:
            self._roll(now, tz)
            sid, event = e["sid"], e["event"]
            if event == "SessionEnd":
                self.sessions.pop(sid, None)
                self._save(now)
                return
            s = self.sessions.get(sid)
            if s is None:
                if len(self.sessions) >= MAX_SESSIONS:
                    oldest = min(self.sessions, key=lambda k: self.sessions[k]["updated"])
                    self.sessions.pop(oldest)
                s = self.sessions[sid] = {"name": e.get("project") or "Claude", "state": "idle",
                                          "detail": "", "since": now, "updated": now, "work_from": 0}
            s["updated"] = now
            if e.get("project"):
                s["name"] = e["project"]

            if event == "UserPromptSubmit":
                self._set(s, "think", "думает", now, restart=True)
                if sid not in self.today["sessions"]:
                    self.today["sessions"].append(sid)
            elif event == "PreToolUse":
                self._set(s, "think", e.get("detail") or s["detail"], now)
                if e.get("commit"):
                    self.today["commits"] += 1
            elif event == "PostToolUse":
                if s["state"] != "think":
                    self._set(s, "think", s["detail"], now)
            elif event == "Notification":
                if e.get("kind") == "permission_prompt":
                    # «запускает git push» → «git push»: на виджете и так написано «ждёт»
                    detail = s["detail"][len("запускает "):] if s["detail"].startswith("запускает ") else s["detail"]
                    self._set(s, "wait", detail or "ждёт разрешения", now)
                elif e.get("kind") == "idle_prompt":
                    self._set(s, "ask", "ждёт ответа", now)
            elif event == "Stop":
                if s.get("work_from"):
                    self._add_work(s["work_from"], now, tz)
                    s["work_from"] = 0
                self._set(s, "done", "готово", now)
            self._save(now)

    def _set(self, s: dict, state: str, detail: str, now: float, restart: bool = False) -> None:
        if state != s["state"] or restart:
            s["since"] = now
        if state in ("think", "wait") and not s.get("work_from"):
            s["work_from"] = now
        s["state"], s["detail"] = state, detail[:60]

    def _roll(self, now: float, tz: int) -> None:
        day = time.strftime("%Y-%m-%d", time.gmtime(now + tz))
        if self.today["day"] != day:
            self.today = {"day": day, "sessions": [], "commits": 0, "hours": [0] * 24, "tz": tz}
        self.today["tz"] = tz

    def _add_work(self, start: float, end: float, tz: int) -> None:
        while start < end:
            hour_end = (int((start + tz) // 3600) + 1) * 3600 - tz
            piece = min(end, hour_end) - start
            hour = time.gmtime(start + tz).tm_hour
            self.today["hours"][hour] += round(piece)
            start += piece

    def _save(self, now: float) -> None:
        self.received = now
        self.store.save({"sessions": self.sessions, "today": self.today, "received": now})

    # -------------------------------------------------------------- для виджета
    def state(self, now: float | None = None) -> dict:
        now = now or time.time()
        with self.lock:
            out = []
            for sid, s in list(self.sessions.items()):
                silent = now - s["updated"]
                if silent > STALE_S and s["state"] != "done":
                    continue
                if s["state"] == "done" and now - s["since"] > DONE_SHOWN_S:
                    continue
                if s["state"] == "idle":
                    continue
                out.append({"name": s["name"], "state": s["state"], "detail": s["detail"], "since": round(s["since"])})
            order = {"wait": 0, "ask": 1, "think": 2, "done": 3}
            out.sort(key=lambda x: (order.get(x["state"], 9), x["since"]))
            t = self.today
            return {
                "v": 1,
                "sent": round(now),
                "sessions": out,
                "today": {"sessions": len(t["sessions"]), "commits": t["commits"],
                          "work_s": sum(t["hours"]), "hours": t["hours"]},
            }


def valid_event(e) -> bool:
    return (isinstance(e, dict) and isinstance(e.get("sid"), str) and isinstance(e.get("event"), str)
            and len(e["sid"]) <= 64 and isinstance(e.get("detail", ""), str))


def make_handler(board, push_key: str, read_key: str):
    """board — a Board, or a function returning one per request (serverless: no shared memory)."""
    get_board = board if callable(board) and not isinstance(board, Board) else (lambda: board)

    class Handler(BaseHTTPRequestHandler):
        server_version = "pocket"
        sys_version = ""

        def log_message(self, fmt, *args):         # no addresses or keys in the journal
            pass

        def _reply(self, code: int, body) -> None:
            raw = (json.dumps(body, ensure_ascii=False) if isinstance(body, dict) else body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json" if isinstance(body, dict) else "text/plain")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _key_ok(self, expected: str) -> bool:
            given = self.headers.get("X-Pocket-Key") or ""
            return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())

        def _route(self) -> str:
            path, _, query = self.path.partition("?")
            for part in query.split("&"):                 # Vercel rewrite: /api/pocket?route=state
                if part.startswith("route="):
                    return "/" + part[6:]
            return path

        def _widget(self) -> None:
            """Скрипт виджета с адресом этого сервера и ключом чтения — для установщика на телефоне."""
            try:
                with open(WIDGET, encoding="utf-8") as f:
                    template = f.read()
            except OSError:
                return self._reply(404, {"error": "widget not bundled"})
            host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or ""
            local = host.startswith(("127.", "localhost", "[::1]"))
            proto = self.headers.get("X-Forwarded-Proto") or ("http" if local else "https")
            script = template.replace("__POCKET_URL__", f"{proto}://{host}").replace("__POCKET_KEY__", read_key)
            raw = script.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            route = self._route()
            if route == "/health":
                return self._reply(200, "ok")
            if route not in ("/state", "/widget.js"):
                return self._reply(404, {"error": "not found"})
            if not self._key_ok(read_key):
                return self._reply(403, {"error": "forbidden"})
            if route == "/widget.js":
                return self._widget()
            current = get_board()
            return self._reply(200, {"state": current.state(), "received": current.received})

        def do_POST(self):
            if self._route() != "/event":
                return self._reply(404, {"error": "not found"})
            if not self._key_ok(push_key):
                return self._reply(403, {"error": "forbidden"})
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                return self._reply(413, {"error": "too large"})
            try:
                event = json.loads(self.rfile.read(length))
            except ValueError:
                return self._reply(400, {"error": "bad json"})
            if not valid_event(event):
                return self._reply(400, {"error": "bad event"})
            get_board().apply(event)
            return self._reply(200, {"ok": True})

    return Handler


def main() -> int:
    push_key = os.environ.get("POCKET_PUSH_KEY", "")
    read_key = os.environ.get("POCKET_READ_KEY", "")
    if len(push_key) < 16 or len(read_key) < 16:
        print("POCKET_PUSH_KEY and POCKET_READ_KEY must be set (16+ chars)", file=sys.stderr)
        return 2
    board = Board(os.environ.get("POCKET_STATE", "/var/lib/claude-pocket/state.json"))
    host = os.environ.get("POCKET_HOST", "127.0.0.1")
    port = int(os.environ.get("POCKET_PORT", "8787"))
    server = ThreadingHTTPServer((host, port), make_handler(board, push_key, read_key))
    server.daemon_threads = True
    print(f"claude pocket on {host}:{port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
