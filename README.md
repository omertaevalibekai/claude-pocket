# Claude Pocket

An iPhone widget that shows what your Claude Code sessions are doing: who is
waiting for you, who is still working and for how long, who just finished,
and how much Claude worked today.

```
Claude Code ──hook──▶ your server ◀──every few minutes── Scriptable widget
 (computer)          (tiny Python)                         (iPhone)
```

- **Lock screen**: an inline line ("1 waiting · 2 working"), a rectangular
  widget with the session that needs you and a live timer, a round counter.
- **Home screen**: small, medium and large widgets. Waiting sessions are black
  and orange so you notice them at a glance; when nothing runs, the widget
  shows today's totals and an hourly chart.
- **Tap**: a sheet with every session grouped by state.

No App Store app and no Apple Developer account: the widget runs in
[Scriptable](https://scriptable.app) (free).

## What leaves your computer

Only what the widget shows: the project folder name, the session state, a
short action ("edits funnel.py", "git push origin main") and today's totals.
Commands are cut to their first words and anything that looks like a key,
token or password is dropped before it is sent. Full paths, prompts and
Claude's answers never leave the machine.

Two keys: the computer can only write, the phone can only read.

## Setup

Requirements: Python 3.9+ on the computer and on a small Linux server with a
public IP (an Oracle/AWS/GCP free VM is plenty).

1. **Computer**

   ```
   python pocket.py setup --url https://<server-ip-with-dashes>.sslip.io
   ```

   Creates keys in `~/.claude-pocket`, copies the hook there and adds one
   async command hook per event to `~/.claude/settings.json` (a backup is
   written next to it; other hooks are left alone). Claude Code never waits
   for the hook, and if the server is down nothing breaks.

2. **Server**: allow TCP 443 in the cloud firewall, then

   ```
   SSH_KEY=~/.ssh/your.key ./deploy/deploy.sh user@<server-ip>
   ```

   Installs `server/relay.py` as a systemd service on 127.0.0.1 and Caddy in
   front of it with a free certificate for `<ip-with-dashes>.sslip.io`.
   No package manager runs, so a 1 GB VM stays responsive.

3. **iPhone**

   ```
   python pocket.py widget --copy
   ```

   Paste the script into a new Scriptable script, then add a Scriptable widget
   and pick that script.

`python pocket.py status` shows what the server sees right now;
`python pocket.py uninstall` removes the hook from Claude Code.

## Tests

```
python -m pytest tests
```
