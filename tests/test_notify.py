"""notify.py must inform without ever interfering: right payload, right
topic, emoji-safe, and absolutely never an exception into a trading run."""

import notify


class _Recorder:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def post(self, url, data=None, params=None, timeout=None):
        if self.fail:
            raise ConnectionError("ntfy is down")
        self.calls.append({"url": url, "data": data, "params": params, "timeout": timeout})
        class R:
            status_code = 200
        return R()


def test_send_posts_title_and_message(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(notify, "requests", rec)
    ok = notify.send("Filled SPY", "SPY base_breakout filled at 755.49", tags=["chart"])
    assert ok is True
    call = rec.calls[0]
    assert call["url"].startswith("https://ntfy.sh/")
    assert call["data"] == b"SPY base_breakout filled at 755.49"
    assert call["params"]["title"] == "Filled SPY"
    assert call["params"]["tags"] == "chart"
    assert call["timeout"] is not None


def test_emoji_title_survives(monkeypatch):
    # HTTP headers are latin-1; emoji in a header kills the request. Title
    # must travel as a UTF-8 URL param instead (found live, 2026-07-10).
    rec = _Recorder()
    monkeypatch.setattr(notify, "requests", rec)
    assert notify.send("Bot connected 🎉", "party on") is True
    assert rec.calls[0]["params"]["title"] == "Bot connected 🎉"


def test_send_never_raises_when_ntfy_is_down(monkeypatch):
    monkeypatch.setattr(notify, "requests", _Recorder(fail=True))
    assert notify.send("t", "m") is False  # swallowed, reported via return


def test_topic_env_override(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(notify, "requests", rec)
    monkeypatch.setenv("NTFY_TOPIC", "secret-topic-xyz")
    notify.send("t", "m")
    assert rec.calls[0]["url"] == "https://ntfy.sh/secret-topic-xyz"
