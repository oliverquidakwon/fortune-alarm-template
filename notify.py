# -*- coding: utf-8 -*-
"""텔레그램 발송 — 표준 라이브러리만 쓴다.

재시도: 텔레그램 API가 몇 분 동안 읽기 타임아웃·504 Gateway Timeout을 돌려주는 날이 있다. 그런 날 첫 호출에서
죽지 않도록 일시 오류(타임아웃·연결 오류·5xx·408·429)는 RETRY_DELAYS 간격으로 다시 보내되 청크당
RETRY_BUDGET_S 안에서만 기다리고, 소진하면 False를 돌려준다 — 호출부는 state를 적지 않고 실패로 끝낸다
(워크플로가 실패 알림을 보낸다). 거절(400류: HTML 파싱 거절 등)은 parse_mode가 있으면 plain text로 1회 폴백,
없으면 그 청크만 건너뛰고 나머지를 보낸 뒤 False. 설정 오류(URL에 못 쓰는 토큰, 인증서 검증 실패)는 재시도해도
같으므로 예외로 올린다. 읽기 타임아웃 뒤의 재시도는 드물게 같은 메시지를 두 번 보낼 수 있는데,
하루치 발송이 통째로 빠지는 쪽보다 낫다.
"""
import http.client
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request

RETRY_DELAYS = (15, 45, 90)   # 초 — 첫 시도 뒤 재시도 간격
TIMEOUT_S = 20                # 소켓 연산(연결·TLS·읽기)별 제한 — 시도 1회가 이보다 몇 배 걸릴 수 있다
RETRY_AFTER_CAP_S = 120       # 429 retry_after 상한
RETRY_BUDGET_S = 200          # 청크당 재시도 총 예산(벽시계) — 남은 예산보다 긴 대기는 하지 않고 포기한다.
                              # 청크당 최악을 예산 + 마지막 시도 한 번으로 묶는다
_sleep = time.sleep           # 테스트에서 바꿔 끼운다
_clock = time.monotonic

_MD_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_MD_UNDER = re.compile(r"__(.+?)__", re.S)
_MD_HEADER = re.compile(r"^#{1,6} +", re.M)


def _sanitize(text: str) -> str:
    """LLM 마크다운 잔재 제거 — parse_mode=HTML에선 **굵게**가 별표 그대로 노출된다.
    여러 번 거쳐도 결과가 같다(멱등)."""
    text = _MD_BOLD.sub(r"\1", text)
    text = _MD_UNDER.sub(r"\1", text)
    text = _MD_HEADER.sub("", text)
    return text.replace("`", "")


def send_telegram(text: str, parse_mode: str | None = "HTML",
                  chat_id_env: str = "TELEGRAM_CHAT_ID",
                  chat_id: str | None = None) -> bool:
    text = _sanitize(text)
    # 붙여 넣은 시크릿에 딸려 온 앞뒤 공백·줄바꿈을 지운다 — 남으면 URL 오류 문장에 토큰 전체가 실린다
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = str(chat_id or os.environ.get(chat_id_env) or "").strip()
    if not token or not chat_id:
        raise RuntimeError(
            f"TELEGRAM_BOT_TOKEN / {chat_id_env} 환경변수가 필요합니다.")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    ok = True
    for chunk in _split(text):
        payload = {"chat_id": chat_id, "text": chunk}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        outcome = _send_with_retry(url, payload)
        if outcome == "ok":
            continue
        if outcome.startswith("reject:"):
            reason = outcome[7:]
            print(f"[telegram] 거절 {reason} — {_hint(reason)}", file=sys.stderr)
            if not _maybe_format_problem(reason):
                return False  # 토큰·chat id·차단 문제 — 서식을 바꿔 다시 보내도, 다음 청크도 같다
            if parse_mode:
                # HTML 파싱 오류 → plain text로 1회 폴백
                # chat_id_env를 반드시 함께 넘긴다 — 누락 시 폴백이 기본 수신자에게 간다
                return send_telegram(text, parse_mode=None,
                                     chat_id_env=chat_id_env, chat_id=chat_id)
            ok = False        # 종전 동작: 거절된 청크는 건너뛰고 나머지 청크는 보낸다
            continue
        return False          # 일시 오류 소진 — 텔레그램이 안 받는 상태라 나머지 청크도 보내지 않는다
    return ok


def _send_with_retry(url: str, payload: dict) -> str:
    """청크 1개를 보낸다. 'ok' / 'reject:<사유>'(재시도 없이 거절) / 'retry:<사유>'(재시도 소진·예산 초과)."""
    attempts = len(RETRY_DELAYS) + 1
    started = _clock()
    outcome, retry_after = "retry:시도 없음", 0
    for i in range(attempts):
        outcome, retry_after = _post(url, payload)
        if outcome == "ok" or outcome.startswith("reject:"):
            return outcome
        if i == attempts - 1:
            break
        delay = min(max(RETRY_DELAYS[i], retry_after), RETRY_AFTER_CAP_S)
        elapsed = _clock() - started
        if elapsed + delay > RETRY_BUDGET_S:
            print(f"[telegram] 발송 포기 — 재시도 예산 {RETRY_BUDGET_S}초 초과 "
                  f"(경과 {elapsed:.0f}초 + 대기 {delay}초, 마지막: {outcome[6:]})", file=sys.stderr)
            return outcome
        print(f"[telegram] 일시 오류 {outcome[6:]} — {delay}초 뒤 재시도 ({i + 2}/{attempts})", file=sys.stderr)
        _sleep(delay)
    print(f"[telegram] 발송 포기 — {attempts}회 모두 실패 (마지막: {outcome[6:]})", file=sys.stderr)
    return outcome


def _is_transient(code: int) -> bool:
    return code in (408, 429) or code >= 500


def _post(url: str, payload: dict) -> tuple[str, int]:
    """1회 전송. (결과, 429의 retry_after 초) — 결과는 'ok' / 'retry:<사유>' / 'reject:<사유>'.
    설정 오류(InvalidURL·인증서 검증 실패)는 재시도 대상이 아니라 예외로 올린다."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json; charset=utf-8"}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            r.read()
        return "ok", 0
    except http.client.InvalidURL:
        # 토큰 가운데에 공백·줄바꿈이 낀 경우 — 기다려도 같다. 원래 예외 문장에는 URL(=토큰)이 통째로 실리므로
        # 그 문장을 버리고(from None — 트레이스백에도 안 남는다) 토큰 없는 문장으로 다시 던진다
        raise RuntimeError("TELEGRAM_BOT_TOKEN 값에 URL에 쓸 수 없는 글자(공백·줄바꿈 등)가 있습니다 — "
                           "시크릿을 다시 넣어 주세요") from None
    except urllib.error.HTTPError as e:
        if _is_transient(e.code):
            return f"retry:HTTP {e.code}", _retry_after(e)
        return f"reject:HTTP {e.code}{_description(e)}", 0
    except (OSError, http.client.HTTPException) as e:
        # 읽기 타임아웃(TimeoutError)·연결 거부·DNS(URLError)·끊긴 응답(RemoteDisconnected·IncompleteRead) 전부 여기
        if isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
            raise         # 인증서 검증 실패는 환경 문제 — 재시도해도 같다
        return f"retry:{type(e).__name__}", 0


def _description(e: urllib.error.HTTPError) -> str:
    """거절 응답 본문의 description(예: 'Bad Request: chat not found') → ': …'. 없거나 못 읽으면 ''.
    토큰 꼴은 혹시 실려 와도 가린다(텔레그램 description에는 보통 없다)."""
    try:
        desc = str(json.loads(e.read().decode("utf-8", "replace")).get("description") or "")
    except Exception:  # noqa: BLE001 — 본문이 없거나 JSON이 아니면 사유 없이 코드만 남긴다
        return ""
    desc = re.sub(r"\d{6,}:[A-Za-z0-9_-]{10,}", "<토큰 가림>", desc)[:200]
    return f": {desc}" if desc else ""


def _maybe_format_problem(reason: str) -> bool:
    """서식(HTML) 문제일 수 있는 거절인지 — 사유가 없으면(옛 동작과 같게) 그럴 수 있다고 본다."""
    r = reason.lower()
    return ": " not in reason or "parse" in r or "entit" in r


def _hint(reason: str) -> str:
    """거절 사유 → 고칠 곳(학생이 발송 스텝 기록만 보고도 알 수 있게)."""
    r = reason.lower()
    if r.startswith("http 401") or r.startswith("http 404"):
        return "봇 토큰(TELEGRAM_BOT_TOKEN)이 틀렸습니다 — BotFather가 준 토큰을 시크릿에 다시 넣어 주세요"
    if "chat not found" in r:
        return "chat id가 틀렸거나 받는 사람이 내 봇에서 시작(/start)을 누르지 않았습니다"
    if r.startswith("http 403"):
        return "받는 사람이 봇을 차단했거나 아직 내 봇에서 시작(/start)을 누르지 않았습니다"
    if "parse" in r or "entit" in r:
        return "메시지 서식(HTML)을 읽지 못했습니다 — 서식 없이 다시 보냅니다"
    return "텔레그램이 이 메시지를 받지 않았습니다"


def _retry_after(e: urllib.error.HTTPError) -> int:
    """429 응답 본문의 parameters.retry_after(초). 없거나 못 읽으면 0."""
    try:
        body = json.loads(e.read().decode("utf-8", "replace"))
        return int(body.get("parameters", {}).get("retry_after", 0))
    except Exception:  # noqa: BLE001 — 본문이 없거나 JSON이 아니면 기본 간격으로 간다
        return 0


def _split(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    out, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            if cur:
                out.append(cur)
            cur = line
        else:
            cur = (cur + "\n" + line) if cur else line
    if cur:
        out.append(cur)
    return out
