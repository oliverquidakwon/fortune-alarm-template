# -*- coding: utf-8 -*-
"""notify 회귀 테스트 — 네트워크 없이 돈다.

① 마크다운 sanitize (굵게 별표가 텔레그램에 그대로 보이지 않게)
② 일시 오류 재시도 (텔레그램 API가 몇 분간 504·읽기 타임아웃을 돌려줄 때 첫 호출에 죽지 않게)
③ 받는 사람 격리 (지정한 chat id로만 보내고, 폴백 재발송도 그 id를 물고 간다)
"""
import http.client
import io
import json
import ssl
import urllib.error

import pytest

import notify as N


def test_sanitize_strips_bold():
    assert N._sanitize("오늘은 **지금 손에 쥔 것**을 보세요.") == "오늘은 지금 손에 쥔 것을 보세요."


def test_sanitize_strips_underline_and_backtick():
    assert N._sanitize("__밑줄__과 `코드`") == "밑줄과 코드"


def test_sanitize_strips_line_headers():
    assert N._sanitize("# 제목\n본문\n## 소제목") == "제목\n본문\n소제목"


def test_sanitize_multiline_bold():
    assert N._sanitize("**두 줄에\n걸친 강조**") == "두 줄에\n걸친 강조"


def test_sanitize_preserves_normal_message():
    msg = "7월 5일 일요일\n\n【오늘의 사주】\n에너지가 안으로 모이는 흐름이에요."
    assert N._sanitize(msg) == msg


def test_sanitize_idempotent():
    once = N._sanitize("**강조** 그리고 __밑줄__")
    assert N._sanitize(once) == once


# ── _split ───────────────────────────────────────────────────
def test_split_short_passthrough():
    assert N._split("짧은 메시지") == ["짧은 메시지"]


def test_split_long_by_lines():
    text = "\n".join("가" * 100 for _ in range(50))   # 각 줄 100자 × 50줄
    chunks = N._split(text, limit=1000)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)
    assert "\n".join(chunks) == text


# ── 재시도 ───────────────────────────────────────────────────
LONG_TEXT = "\n".join("가" * 100 for _ in range(50))      # 4000자 상한 → 2청크


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b'{"ok":true}'


def _http(code: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api.telegram.org/x", code, "err", hdrs=None, fp=io.BytesIO(body))


@pytest.fixture
def wire(monkeypatch):
    """가짜 urlopen — queue를 순서대로 소비한다(예외 객체면 raise, 그 밖엔 성공). 보낸 payload·timeout·sleep을
    기록하고, 가짜 벽시계는 sleep만큼만 간다(실제로 기다리지 않는다)."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-secret")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    rec = {"calls": [], "urls": [], "timeouts": [], "sleeps": [], "queue": [], "t": 0.0}

    def fake_urlopen(req, timeout=None):
        rec["urls"].append(req.full_url)
        rec["calls"].append(json.loads(req.data.decode("utf-8")))
        rec["timeouts"].append(timeout)
        item = rec["queue"].pop(0) if rec["queue"] else "ok"
        if callable(item) and not isinstance(item, BaseException):
            item = item()        # 시도 자체가 시계를 미는 경우(느린 실패)를 흉내 낸다
        if isinstance(item, BaseException):
            raise item
        return _Resp()

    def fake_sleep(s):
        rec["sleeps"].append(s)
        rec["t"] += s

    monkeypatch.setattr(N.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(N, "_sleep", fake_sleep)
    monkeypatch.setattr(N, "_clock", lambda: rec["t"])
    return rec


def test_timeout_then_success_retries_once(wire):
    wire["queue"][:] = [TimeoutError("The read operation timed out")]
    assert N.send_telegram("본문") is True
    assert len(wire["calls"]) == 2
    assert wire["sleeps"] == [N.RETRY_DELAYS[0]]


def test_every_attempt_carries_the_socket_timeout(wire):
    """timeout 인자가 빠지면 연결이 무한정 매달린다."""
    wire["queue"][:] = [TimeoutError()]
    N.send_telegram("본문")
    assert wire["timeouts"] == [N.TIMEOUT_S, N.TIMEOUT_S]


def test_gateway_timeout_504_twice_then_success(wire):
    wire["queue"][:] = [_http(504), _http(504)]
    assert N.send_telegram("본문") is True
    assert len(wire["calls"]) == 3
    assert wire["sleeps"] == list(N.RETRY_DELAYS[:2])


def test_any_5xx_is_transient(wire):
    wire["queue"][:] = [_http(521), _http(599)]
    assert N.send_telegram("본문") is True
    assert len(wire["calls"]) == 3


def test_all_attempts_exhausted_returns_false_without_raising(wire, capsys):
    wire["queue"][:] = [TimeoutError()] * (len(N.RETRY_DELAYS) + 1)
    assert N.send_telegram("본문") is False
    assert len(wire["calls"]) == len(N.RETRY_DELAYS) + 1
    assert wire["sleeps"] == list(N.RETRY_DELAYS)
    err = capsys.readouterr().err
    assert "발송 포기" in err
    assert "tok-secret" not in err, "로그에 토큰(URL)이 찍히면 안 된다"


def test_connection_errors_are_transient(wire):
    wire["queue"][:] = [urllib.error.URLError("dns"), ConnectionResetError(), http.client.RemoteDisconnected("x")]
    assert N.send_telegram("본문") is True
    assert len(wire["calls"]) == 4


def test_http_exception_without_oserror_is_transient(wire):
    """IncompleteRead는 HTTPException이지 OSError가 아니다 — 그 분기를 지우면 전파돼 실행이 죽는다."""
    wire["queue"][:] = [http.client.IncompleteRead(b"")]
    assert N.send_telegram("본문") is True
    assert len(wire["calls"]) == 2


def test_non_network_exception_propagates(wire):
    """except를 Exception으로 넓히면 코드 결함(ValueError 등)까지 재시도로 삼킨다."""
    wire["queue"][:] = [ValueError("bug")]
    with pytest.raises(ValueError):
        N.send_telegram("본문")
    assert wire["sleeps"] == []


def test_invalid_url_is_a_config_error_not_retried(wire):
    wire["queue"][:] = [http.client.InvalidURL("URL can't contain control characters")]
    with pytest.raises(RuntimeError) as e:
        N.send_telegram("본문")
    assert "TELEGRAM_BOT_TOKEN" in str(e.value)
    assert len(wire["calls"]) == 1 and wire["sleeps"] == []


# ── 시크릿이 오류 문장으로 새지 않게 ───────────────────────────
FAKE_TOKEN = "1234" + "56789:" + "AbCd" * 9          # 지어낸 토큰(이어 붙여 만든다)


def _no_network(*a, **k):
    raise OSError("시험 중 네트워크 차단")


def test_token_and_chat_id_are_stripped_before_use(wire, monkeypatch):
    """시크릿을 붙여 넣을 때 딸려 온 앞뒤 공백·줄바꿈은 지운다 — 그대로 URL에 넣으면 토큰이 오류 문장에 실린다."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", " " + FAKE_TOKEN + "\n")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", " 123\n")
    assert N.send_telegram("본문") is True
    assert wire["urls"] == [f"https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage"]
    assert wire["calls"][0]["chat_id"] == "123"


def test_token_that_cannot_go_in_a_url_fails_without_showing_it(monkeypatch):
    """토큰 가운데에 줄바꿈이 끼면(앞뒤를 지워도 남는다) 실제 urllib가 InvalidURL을 내고, 그 문장에는 URL 전체가 실린다.
    네트워크 없이 그 경로를 그대로 타서, 올라오는 예외와 트레이스백 어디에도 토큰 글자가 없는지 본다."""
    import socket
    import traceback

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_TOKEN[:20] + "\n" + FAKE_TOKEN[20:] + "\n")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr(socket, "create_connection", _no_network)
    monkeypatch.setattr(N, "_sleep", lambda s: None)
    with pytest.raises(RuntimeError) as e:
        N.send_telegram("본문")
    shown = "".join(traceback.format_exception(e.value))
    assert "TELEGRAM_BOT_TOKEN" in shown
    for part in (FAKE_TOKEN[:20], FAKE_TOKEN[20:], "api.telegram.org/bot"):
        assert part not in shown


def test_certificate_failure_is_not_retried(wire):
    wire["queue"][:] = [urllib.error.URLError(ssl.SSLCertVerificationError("bad cert"))]
    with pytest.raises(urllib.error.URLError):
        N.send_telegram("본문")
    assert len(wire["calls"]) == 1 and wire["sleeps"] == []


def test_bad_request_falls_back_to_plain_text_without_retry(wire):
    """400(HTML 파싱 거절)은 일시 오류가 아니다 — 기다리지 않고 plain text로 1회 폴백."""
    wire["queue"][:] = [_http(400)]
    assert N.send_telegram("본문", parse_mode="HTML") is True
    assert len(wire["calls"]) == 2
    assert wire["calls"][0].get("parse_mode") == "HTML"
    assert "parse_mode" not in wire["calls"][1]
    assert wire["sleeps"] == []


def _tg_error(code: int, description: str):
    return _http(code, json.dumps({"ok": False, "error_code": code, "description": description}).encode())


def test_rejection_reason_and_a_hint_are_logged_without_the_token(wire, capsys):
    """텔레그램이 거절하면 코드·사유와 고칠 곳을 로그에 남긴다 — 학생이 보는 발송 스텝 기록에 이유가 있어야 한다.
    서식 문제가 아닌 거절(토큰·chat id·차단)은 plain으로 다시 보내 봐야 같으니 거기서 멈춘다."""
    cases = [(401, "Unauthorized", "봇 토큰"), (404, "Not Found", "봇 토큰"),
             (400, "Bad Request: chat not found", "/start"), (403, "Forbidden: bot was blocked by the user", "차단")]
    for code, desc, hint in cases:
        wire["queue"][:] = [_tg_error(code, desc)]
        wire["calls"].clear()
        assert N.send_telegram("본문") is False
        err = capsys.readouterr().err
        assert f"HTTP {code}" in err and desc in err and hint in err, (code, err)
        assert "tok-secret" not in err
        assert len(wire["calls"]) == 1, code                # plain 폴백 없이 멈춘다


def test_html_parse_rejection_still_falls_back_to_plain(wire, capsys):
    wire["queue"][:] = [_tg_error(400, "Bad Request: can't parse entities: unsupported start tag")]
    assert N.send_telegram("본문") is True
    assert len(wire["calls"]) == 2 and "parse_mode" not in wire["calls"][1]
    assert "HTTP 400" in capsys.readouterr().err


def test_bad_request_in_plain_mode_is_final(wire):
    wire["queue"][:] = [_http(400)]
    assert N.send_telegram("본문", parse_mode=None) is False
    assert len(wire["calls"]) == 1
    assert wire["sleeps"] == []


def test_plain_mode_rejected_chunk_is_skipped_and_the_rest_still_goes(wire):
    """plain 모드에서 한 청크가 거절되면 그 청크만 건너뛰고 나머지는 보낸 뒤 False."""
    wire["queue"][:] = [_http(400)]
    assert N.send_telegram(LONG_TEXT, parse_mode=None) is False
    assert len(wire["calls"]) == len(N._split(LONG_TEXT)) == 2
    assert wire["sleeps"] == []


def test_exhausted_chunk_stops_the_remaining_chunks(wire):
    """일시 오류 소진은 거절과 다르다 — 텔레그램이 안 받는 상태라 뒤 청크로 시간을 더 쓰지 않는다."""
    wire["queue"][:] = [TimeoutError()] * (len(N.RETRY_DELAYS) + 1)
    assert N.send_telegram(LONG_TEXT, parse_mode=None) is False
    assert len(wire["calls"]) == len(N.RETRY_DELAYS) + 1


def test_429_honours_retry_after_above_default_gap(wire):
    wire["queue"][:] = [_http(429, b'{"ok":false,"parameters":{"retry_after":60}}')]
    assert N.send_telegram("본문") is True
    assert wire["sleeps"] == [60]


def test_429_retry_after_below_default_gap_keeps_the_gap(wire):
    wire["queue"][:] = [_http(429, b'{"ok":false,"parameters":{"retry_after":7}}')]
    assert N.send_telegram("본문") is True
    assert wire["sleeps"] == [N.RETRY_DELAYS[0]]


def test_429_huge_retry_after_is_capped_then_budget_stops_it(wire):
    """retry_after를 상한으로 자르고, 남은 예산보다 긴 대기는 하지 않는다."""
    flood = lambda: _http(429, b'{"ok":false,"parameters":{"retry_after":9999}}')  # noqa: E731
    wire["queue"][:] = [flood(), flood(), flood(), "ok"]
    assert N.send_telegram("본문") is False
    assert wire["sleeps"] == [N.RETRY_AFTER_CAP_S]
    assert len(wire["calls"]) == 2
    assert sum(wire["sleeps"]) <= N.RETRY_BUDGET_S


def test_budget_counts_slow_attempts_too(wire):
    """시도 자체가 오래 걸려도(연결·TLS·읽기 각각 제한) 예산은 벽시계로 센다."""
    def slow_timeout():
        wire["t"] += 60     # 시도 1회가 60초 매달렸다
        return TimeoutError()
    wire["queue"][:] = [slow_timeout] * 4
    assert N.send_telegram("본문") is False
    assert wire["sleeps"] == [N.RETRY_DELAYS[0], N.RETRY_DELAYS[1]]
    assert len(wire["calls"]) == 3


def test_each_chunk_retries_independently(wire):
    wire["queue"][:] = ["ok", TimeoutError()]
    assert N.send_telegram(LONG_TEXT, parse_mode=None) is True
    assert len(wire["calls"]) == 3
    assert wire["calls"][1]["text"] == wire["calls"][2]["text"], "재시도는 실패한 그 청크를 다시 보낸다"
    assert wire["calls"][0]["text"] != wire["calls"][1]["text"]


def test_retry_budget_is_bounded():
    """청크당 최악 = 재시도 예산 + 마지막 시도(연결·TLS·읽기 제한 3배) — 5분 안에 끝나거나 포기한다."""
    worst_chunk = N.RETRY_BUDGET_S + 3 * N.TIMEOUT_S
    assert worst_chunk <= 300
    assert sum(N.RETRY_DELAYS) <= N.RETRY_BUDGET_S, "정상 재시도 경로(일시 오류 4회)가 예산 안에 들어야 한다"
    assert N.RETRY_AFTER_CAP_S < N.RETRY_BUDGET_S


# ── 받는 사람 격리 ──────────────────────────────────────────
def test_send_goes_to_the_given_chat_id(wire):
    assert N.send_telegram("본문", chat_id="2002")
    assert [m["chat_id"] for m in wire["calls"]] == ["2002"]


def test_plain_fallback_keeps_the_given_chat_id(wire):
    """HTML 거절 → plain 재발송. chat id를 안 물고 가면 남의 운세가 기본 수신자(나)에게 간다."""
    wire["queue"][:] = [_http(400)]
    assert N.send_telegram("본문", chat_id="2002")
    assert [m["chat_id"] for m in wire["calls"]] == ["2002", "2002"]
