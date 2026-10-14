"""Claude Pocket — set up this computer.

    python pocket.py setup [--url https://…]   keys, hook, Claude Code settings
    python pocket.py widget [--copy]           Scriptable script with the read key
    python pocket.py status                    is the server up, what it shows now
    python pocket.py uninstall                 remove the hook from Claude Code

Everything local lives in ~/.claude-pocket (keys.json, config.json, the hook
copy). Claude Code's ~/.claude/settings.json gets one async command hook per
event; other hooks are left alone and a backup is written next to it.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOME = Path(os.environ.get("CLAUDE_POCKET_HOME") or Path.home() / ".claude-pocket")
SETTINGS = Path(os.environ.get("CLAUDE_SETTINGS") or Path.home() / ".claude" / "settings.json")
EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Notification", "Stop", "SessionEnd")
MARK = "pocket_hook.py"


# ------------------------------------------------------------------ ключи и конфиг

def keys() -> dict:
    path = HOME / "keys.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("push") and data.get("read"):
            return data
    except (OSError, ValueError):
        pass
    data = {"push": secrets.token_urlsafe(24), "read": secrets.token_urlsafe(24)}
    HOME.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def config() -> dict:
    try:
        return json.loads((HOME / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_config(url: str) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    (HOME / "config.json").write_text(
        json.dumps({"url": url.rstrip("/"), "push_key": keys()["push"]}, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ хуки Claude Code

def hook_command() -> str:
    script = (HOME / "pocket_hook.py").as_posix()
    python = Path(sys.executable).as_posix()
    return f'"{python}" "{script}"'


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8") or "{}")


def _is_ours(group: dict) -> bool:
    return any(MARK in str(h.get("command", "")) for h in group.get("hooks", []))


def _strip(data: dict) -> dict:
    hooks = data.get("hooks") or {}
    for event in list(hooks):
        kept = [g for g in hooks[event] if not _is_ours(g)]
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if hooks:
        data["hooks"] = hooks
    else:
        data.pop("hooks", None)
    return data


def _save_settings(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(f"settings.json.pocket-backup-{time.strftime('%Y%m%d-%H%M%S')}"))
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def install_hooks(path: Path = SETTINGS) -> None:
    data = _strip(_load(path))
    hooks = data.setdefault("hooks", {})
    for event in EVENTS:
        hooks.setdefault(event, []).append({"hooks": [{
            "type": "command", "command": hook_command(), "async": True, "timeout": 10,
        }]})
    _save_settings(data, path)


def uninstall_hooks(path: Path = SETTINGS) -> bool:
    if not path.exists():
        return False
    data = _load(path)
    had = any(_is_ours(g) for groups in (data.get("hooks") or {}).values() for g in groups)
    if had:
        _save_settings(_strip(data), path)
    return had


# ------------------------------------------------------------------ виджет

def widget_script(url: str) -> str:
    template = (ROOT / "widget" / "claude-widget.js").read_text(encoding="utf-8")
    return template.replace("__POCKET_URL__", url.rstrip("/")).replace("__POCKET_KEY__", keys()["read"])


def copy_to_clipboard(path: Path) -> bool:
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                        f"Get-Content -Raw -Encoding UTF8 -LiteralPath '{path}' | Set-Clipboard"],
                       check=True, capture_output=True, timeout=15)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


# ------------------------------------------------------------------ команды

def cmd_setup(args) -> int:
    url = (args.url or config().get("url") or "").rstrip("/")
    if not url.startswith("https://"):
        print("Укажите адрес сервера: python pocket.py setup --url https://<ip-через-дефисы>.sslip.io")
        return 2
    keys()
    write_config(url)
    shutil.copy2(ROOT / "hook" / "pocket_hook.py", HOME / "pocket_hook.py")
    install_hooks()
    print(f"Ключи и настройки: {HOME}")
    print(f"Хук подключён к Claude Code ({SETTINGS}); резервная копия лежит рядом.")
    print(f"Сервер: {url}")
    print("Новые сессии Claude Code видны сразу, уже открытые — после перезапуска.")
    print("Дальше: выкатить сервер (deploy/deploy.sh) и python pocket.py widget --copy")
    return 0


def cmd_widget(args) -> int:
    url = config().get("url")
    if not url:
        print("Сначала python pocket.py setup --url …")
        return 2
    out = HOME / "claude-widget.js"
    HOME.mkdir(parents=True, exist_ok=True)
    out.write_text(widget_script(url), encoding="utf-8")
    print(f"Скрипт для Scriptable: {out}")
    if args.copy:
        print("Скопирован в буфер обмена." if copy_to_clipboard(out) else "В буфер скопировать не вышло.")
    return 0


def cmd_status(_args) -> int:
    url = config().get("url")
    if not url:
        print("Сначала python pocket.py setup --url …")
        return 2
    try:
        with urllib.request.urlopen(url + "/health", timeout=8) as reply:
            print(f"{url}: {reply.read().decode()}")
        req = urllib.request.Request(url + "/state", headers={"X-Pocket-Key": keys()["read"]})
        with urllib.request.urlopen(req, timeout=8) as reply:
            data = json.loads(reply.read())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"{url}: не отвечает ({getattr(exc, 'reason', exc)})")
        return 1
    state = data.get("state") or {}
    for s in state.get("sessions") or []:
        print(f"  {s['name']:<24} {s['state']:<6} {s['detail']}")
    if not state.get("sessions"):
        print("  сессий сейчас нет")
    today = state.get("today") or {}
    print(f"  сегодня: {today.get('sessions', 0)} сессий, {today.get('commits', 0)} коммитов, "
          f"{round((today.get('work_s') or 0) / 60)} мин работы")
    return 0


def cmd_uninstall(_args) -> int:
    print("Хук убран из Claude Code." if uninstall_hooks() else "Хука в настройках Claude Code нет.")
    return 0


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Claude Pocket")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("setup")
    p.add_argument("--url")
    p = sub.add_parser("widget")
    p.add_argument("--copy", action="store_true")
    sub.add_parser("status")
    sub.add_parser("uninstall")
    args = parser.parse_args(argv)
    return {"setup": cmd_setup, "widget": cmd_widget, "status": cmd_status, "uninstall": cmd_uninstall}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
