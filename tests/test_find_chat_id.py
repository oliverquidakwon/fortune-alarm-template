# -*- coding: utf-8 -*-
"""find_chat_id — 텔레그램 API를 가짜로 바꿔 끼우고 돈다(네트워크 없음)."""
import find_chat_id as F


def _upd(cid: int, name: str) -> dict:
    return {"message": {"chat": {"id": cid, "type": "private", "first_name": name}}}


def _fake_api(monkeypatch, updates, webhook=""):
    def fake_call(token, method):
        if method == "getWebhookInfo":
            return {"ok": True, "result": {"url": webhook}}
        if method == "getUpdates":
            return {"ok": True, "result": updates}
        raise AssertionError(method)

    monkeypatch.setattr(F, "_call", fake_call)
    monkeypatch.setattr(F, "_load_env", lambda *a, **k: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")


def test_first_time_lists_my_chat_and_says_which_secret(monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    _fake_api(monkeypatch, [_upd(1001, "하늘")])
    assert F.main([]) == 0
    out = capsys.readouterr().out
    assert "1001" in out and "TELEGRAM_CHAT_ID" in out


def test_new_family_chat_points_to_fortune_chat_ids(monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1001")
    _fake_api(monkeypatch, [_upd(1001, "하늘"), _upd(2002, "바다")])
    assert F.main([]) == 0
    out = capsys.readouterr().out
    assert "2002" in out and "FORTUNE_CHAT_IDS" in out


def test_print_fresh_gives_the_single_new_id(monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1001")
    _fake_api(monkeypatch, [_upd(1001, "하늘"), _upd(2002, "바다")])
    assert F.main(["--print-fresh"]) == 0
    assert capsys.readouterr().out.strip() == "2002"


def test_print_fresh_refuses_when_ambiguous(monkeypatch, capsys):
    """두 사람이 동시에 말을 걸었으면 누구 id인지 특정할 수 없다 — 잘못된 id를 내주지 않는다."""
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1001")
    _fake_api(monkeypatch, [_upd(2002, "바다"), _upd(3003, "구름")])
    assert F.main(["--print-fresh"]) == 1
    assert capsys.readouterr().out == ""


def test_no_messages_yet(monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    _fake_api(monkeypatch, [])
    assert F.main([]) == 0
    assert "/start" in capsys.readouterr().out


def test_no_token_exits_1(monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr(F, "_load_env", lambda *a, **k: None)
    assert F.main([]) == 1
    assert "TELEGRAM_BOT_TOKEN" in capsys.readouterr().err


def test_env_is_read_only_from_this_folder(tmp_path, monkeypatch):
    """자기 폴더의 .env만 읽는다 — 위 폴더에 있는 엉뚱한 토큰을 집지 않게."""
    here = tmp_path / "repo"
    here.mkdir()
    (tmp_path / ".env").write_text("TELEGRAM_BOT_TOKEN=from-parent\n", encoding="utf-8")
    monkeypatch.setattr(F, "HERE", str(here))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    F._load_env()
    import os
    assert os.environ.get("TELEGRAM_BOT_TOKEN") is None
    (here / ".env").write_text("TELEGRAM_BOT_TOKEN=from-here\n", encoding="utf-8")
    F._load_env()
    assert os.environ.get("TELEGRAM_BOT_TOKEN") == "from-here"
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
