"""Phone notifications via ntfy.sh — free, no account, no signup.

Subscribe once in the ntfy app (or web) to the topic below and the bots
ping you: fills, closes, nightly summaries, failures, promotion flags.

The topic is committed in a public repo, so it's visible — worst case a
stranger sees fake-money trade pings or posts noise to it. If that ever
happens, set the NTFY_TOPIC env var (e.g. a GitHub Actions secret) and the
committed default is ignored; no code change needed.

A notification must NEVER break a trading run: send() swallows every
exception and reports success/failure via its return value only.
"""

from __future__ import annotations

import os

import requests

DEFAULT_TOPIC = "prop-trader-abhi-1a1c6d67741009ef"
TIMEOUT = 5


def topic() -> str:
    return os.environ.get("NTFY_TOPIC", DEFAULT_TOPIC)


def send(title: str, message: str, priority: str = "default",
         tags: list[str] | None = None) -> bool:
    """Push one notification. Returns True on success, False on any failure —
    never raises.

    Title/tags travel as URL params, not headers: HTTP headers are latin-1
    only and an emoji in a header silently kills the request. Params are
    UTF-8 URL-encoded, so emoji everywhere is fine (found live, 2026-07-10).
    """
    try:
        params = {"title": title, "priority": priority}
        if tags:
            params["tags"] = ",".join(tags)
        requests.post(f"https://ntfy.sh/{topic()}", data=message.encode(),
                      params=params, timeout=TIMEOUT)
        return True
    except Exception as e:
        print(f"(notification skipped: {e})")
        return False
