"""Claude Pocket as a Vercel function: the same server/relay.py, with the board
kept in Upstash Redis (REST API, standard library only).

Routes (vercel.json rewrites them here): POST /event, GET /state, GET /health.
Environment: POCKET_PUSH_KEY, POCKET_READ_KEY and the Redis REST credentials
the Upstash integration adds (KV_REST_API_URL / KV_REST_API_TOKEN or
UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN).
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))

import relay  # noqa: E402

KEY = "claude-pocket:board"


class RedisStore:
    def __init__(self) -> None:
        self.url = (os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL") or "").rstrip("/")
        self.token = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN") or ""

    def _call(self, *command):
        request = urllib.request.Request(
            self.url, data=json.dumps(list(command)).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as reply:
            return json.loads(reply.read()).get("result")

    def load(self):
        raw = self._call("GET", KEY)
        return json.loads(raw) if raw else None

    def save(self, data: dict) -> None:
        self._call("SET", KEY, json.dumps(data, ensure_ascii=False))


_Handler = relay.make_handler(
    lambda: relay.Board(RedisStore()),
    os.environ.get("POCKET_PUSH_KEY", ""),
    os.environ.get("POCKET_READ_KEY", ""),
)


class handler(_Handler):          # Vercel ищет в файле класс с этим именем
    pass
