import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "server"), str(ROOT / "hook")]

import pocket  # noqa: E402
import pocket_hook  # noqa: E402
import relay  # noqa: E402

T0 = 1_800_000_000.0          # фиксированное время для расчётов
TZ = 5 * 3600                 # Алматы


def ev(event, sid="a", project="shepot", **extra):
    return {"sid": sid, "event": event, "project": project, "ts": T0, "tz": TZ, **extra}


# ------------------------------------------------------------------ хук

def test_hook_sanitises_commands():
    assert pocket_hook.action("Bash", {"command": "git push origin main"}) == "запускает git push origin main"
    assert pocket_hook.action("Bash", {"command": "curl -H Authorization: Bearer x"}) == "запускает curl -H"
    assert pocket_hook.action("Bash", {"command": "export OPENAI_API_KEY=sk-proj-1"}) == "запускает export"
    assert pocket_hook.action("Edit", {"file_path": "C:/Users/x/AI Projects/app/funnel.py"}) == "правит funnel.py"
    assert pocket_hook.action("Grep", {"pattern": "def main"}) == "ищет def main"


def test_hook_compact_event():
    payload = {"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": "C:/Users/x/Desktop/AI Projects/Stable",
               "tool_name": "Bash", "tool_input": {"command": "git commit -m 'fix' && echo ghp_abcdefghijklmnop1234567890"}}
    out = pocket_hook.compact(payload)
    assert out["project"] == "Stable" and out["commit"] is True
    text = json.dumps(out, ensure_ascii=False)
    assert "ghp_" not in text and "AI Projects" not in text
    assert pocket_hook.compact({**payload, "agent_id": "sub"}) is None


# ------------------------------------------------------------------ сервер: состояние

def board(tmp_path):
    return relay.Board(str(tmp_path / "state.json"))


def test_permission_flow(tmp_path):
    b = board(tmp_path)
    b.apply(ev("UserPromptSubmit"), T0)
    b.apply(ev("PreToolUse", detail="запускает git push origin main"), T0 + 5)
    b.apply(ev("Notification", kind="permission_prompt"), T0 + 6)
    s = b.state(T0 + 10)["sessions"][0]
    assert (s["state"], s["detail"], s["since"]) == ("wait", "git push origin main", T0 + 6)
    b.apply(ev("PostToolUse", detail="запускает git push origin main"), T0 + 30)
    assert b.state(T0 + 31)["sessions"][0]["state"] == "think"


def test_order_stale_and_done(tmp_path):
    b = board(tmp_path)
    b.apply(ev("UserPromptSubmit", sid="a", project="Stable"), T0)
    b.apply(ev("UserPromptSubmit", sid="b", project="shepot"), T0)
    b.apply(ev("Notification", sid="b", project="shepot", kind="idle_prompt"), T0 + 1)
    b.apply(ev("UserPromptSubmit", sid="c", project="whoop"), T0)
    b.apply(ev("Stop", sid="c", project="whoop"), T0 + 600)
    names = [(s["name"], s["state"]) for s in b.state(T0 + 601)["sessions"]]
    assert names == [("shepot", "ask"), ("Stable", "think"), ("whoop", "done")]
    later = [s["name"] for s in b.state(T0 + 600 + relay.DONE_SHOWN_S + 1)["sessions"]]
    assert "whoop" not in later
    assert b.state(T0 + relay.STALE_S + 700)["sessions"] == []          # закрыли терминал без SessionEnd
    b.apply(ev("SessionEnd", sid="a"), T0 + 2)
    assert "a" not in b.sessions


def test_today_hours_in_local_time(tmp_path):
    b = board(tmp_path)
    start = T0 - (T0 + TZ) % 3600 + 50 * 60          # хх:50 по местному
    b.apply(ev("UserPromptSubmit"), start)
    b.apply(ev("PreToolUse", detail="запускает git commit -m x", commit=True), start + 60)
    b.apply(ev("Stop"), start + 20 * 60)
    today = b.state(start + 21 * 60)["today"]
    hour = int(((start + TZ) % 86400) // 3600)
    assert today["hours"][hour] == 600 and today["hours"][(hour + 1) % 24] == 600
    assert today["sessions"] == 1 and today["commits"] == 1 and today["work_s"] == 1200
    again = relay.Board(str(tmp_path / "state.json"))              # переживает перезапуск
    assert again.today["commits"] == 1


# ------------------------------------------------------------------ сервер: HTTP

@pytest.fixture()
def server(tmp_path):
    b = board(tmp_path)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), relay.make_handler(b, "p" * 20, "r" * 20))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", b
    srv.shutdown()


def call(url, key=None, body=None):
    req = urllib.request.Request(url, data=body, method="POST" if body is not None else "GET",
                                 headers={"X-Pocket-Key": key} if key else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as reply:
            raw = reply.read()
            return reply.status, (json.loads(raw) if raw.startswith(b"{") else raw.decode())
    except urllib.error.HTTPError as exc:
        return exc.code, None


def test_http_keys(server):
    base, _ = server
    body = json.dumps(ev("UserPromptSubmit")).encode()
    assert call(base + "/health") == (200, "ok")
    assert call(base + "/event", "wrong", body)[0] == 403
    assert call(base + "/event", "r" * 20, body)[0] == 403          # ключ телефона не пишет
    assert call(base + "/event", "p" * 20, body)[0] == 200
    assert call(base + "/state", "p" * 20)[0] == 403                # ключ компьютера не читает
    code, data = call(base + "/state", "r" * 20)
    assert code == 200 and data["state"]["sessions"][0]["name"] == "shepot"
    assert call(base + "/event", "p" * 20, b'{"sid": 1}')[0] == 400
    assert call(base + "/event", "p" * 20, b"x" * (20 * 1024))[0] == 413


def test_hook_process_reaches_server(server, tmp_path):
    base, b = server
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.json").write_text(json.dumps({"url": base, "push_key": "p" * 20}))
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "real", "cwd": "C:/x/claude-pocket"}
    run = subprocess.run([sys.executable, str(ROOT / "hook" / "pocket_hook.py")], input=json.dumps(payload),
                         text=True, capture_output=True, timeout=20, env={**os.environ, "CLAUDE_POCKET_HOME": str(home)})
    assert run.returncode == 0 and run.stdout == "" and run.stderr == ""
    assert b.sessions["real"]["name"] == "claude-pocket"


def test_hook_never_fails_without_server(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.json").write_text(json.dumps({"url": "http://127.0.0.1:9", "push_key": "x"}))
    run = subprocess.run([sys.executable, str(ROOT / "hook" / "pocket_hook.py")], input="{not json",
                         text=True, capture_output=True, timeout=20, env={**os.environ, "CLAUDE_POCKET_HOME": str(home)})
    assert run.returncode == 0 and run.stdout == ""


# ------------------------------------------------------------------ настройка

def test_install_keeps_other_hooks(tmp_path, monkeypatch):
    monkeypatch.setattr(pocket, "HOME", tmp_path / "pocket")
    settings = tmp_path / "settings.json"
    other = {"type": "http", "url": "http://127.0.0.1:47821/claude/Stop"}
    settings.write_text(json.dumps({"model": "opus", "hooks": {"Stop": [{"hooks": [other]}]}}))
    pocket.install_hooks(settings)
    pocket.install_hooks(settings)                                   # повторно — без дублей
    data = json.loads(settings.read_text())
    assert data["model"] == "opus"
    assert len(data["hooks"]["Stop"]) == 2 and data["hooks"]["Stop"][0]["hooks"][0] == other
    ours = data["hooks"]["PreToolUse"][0]["hooks"][0]
    assert ours["async"] is True and ours["type"] == "command" and "pocket_hook.py" in ours["command"]
    assert any(p.name.startswith("settings.json.pocket-backup-") for p in tmp_path.iterdir())
    assert pocket.uninstall_hooks(settings) is True
    data = json.loads(settings.read_text())
    assert data["hooks"] == {"Stop": [{"hooks": [other]}]}


def test_widget_script_has_read_key_only(tmp_path, monkeypatch):
    monkeypatch.setattr(pocket, "HOME", tmp_path)
    script = pocket.widget_script("https://example.test/")
    k = pocket.keys()
    assert 'const URL_BASE = "https://example.test";' in script
    assert k["read"] in script and k["push"] not in script and "__POCKET" not in script
