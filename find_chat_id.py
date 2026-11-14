# -*- coding: utf-8 -*-
"""
텔레그램 chat id 찾기 — 처음 설정할 때, 그리고 가족·친구를 추가할 때 한 번씩 쓴다.

  python find_chat_id.py                 # 내 봇에게 말을 건 대화 목록(chat id · 이름)
  python find_chat_id.py --print-fresh   # 내 id(TELEGRAM_CHAT_ID)를 뺀 대화가 정확히 1건일 때 그 id만 출력
                                         # (0건·2건 이상이면 stderr로 알리고 종료 코드 1)

먼저 텔레그램에서 내 봇을 열고 시작(/start)을 누르거나 아무 말이나 한 번 보낸다. 텔레그램 봇은
먼저 말을 걸 수 없어서, 보낸 메시지가 없으면 여기에 아무것도 잡히지 않는다. 보낸 뒤 24시간 안에
실행한다(그 뒤엔 업데이트가 만료돼 다시 보내야 한다).

토큰: 이 폴더의 .env에 TELEGRAM_BOT_TOKEN=... 한 줄(.env는 git에 올라가지 않는다), 또는 환경변수.
토큰은 출력하지 않는다. 표준 라이브러리만 쓰므로 pip 설치 전에도 돈다.

찾은 값은 GitHub 저장소 Settings → Secrets and variables → Actions에 넣는다:
  내 chat id → TELEGRAM_CHAT_ID / 가족·친구 → FORTUNE_CHAT_IDS (ADDING_A_RECIPIENT.md)
"""
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.telegram.org/bot{token}/{method}"

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_env(fname: str = ".env") -> None:
    """이 폴더의 .env만 읽는다(run_daily._load_env와 같은 동작). 이미 있는 환경변수는 덮지 않는다."""
    p = os.path.join(HERE, fname)
    if not os.path.exists(p):
        return
    with open(p, encoding="utf-8") as f:
        for raw in f:
            s = raw.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _call(token: str, method: str) -> dict:
    req = urllib.request.Request(API.format(token=token, method=method))
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):      # 한글 윈도의 cp949 콘솔·파이프에서 못 쓰는 글자(—)는 ?로 — 죽지 않는다
        if hasattr(s, "reconfigure"):
            s.reconfigure(errors="replace")
    argv = sys.argv[1:] if argv is None else argv
    # 자동화에서 쓰는 모드 — stdout에는 id 하나만, 나머지 안내는 stderr로.
    quiet = "--print-fresh" in argv

    def say(*a):
        print(*a, file=sys.stderr if quiet else sys.stdout)

    _load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN이 없습니다. 이 폴더의 .env에 한 줄 넣고 다시 실행하세요:\n"
              "  TELEGRAM_BOT_TOKEN=<@BotFather가 준 토큰>", file=sys.stderr)
        return 1

    try:
        hook = _call(token, "getWebhookInfo").get("result", {})
    except urllib.error.HTTPError as e:
        print(f"봇 인증 실패 ({e.code}) — 토큰을 확인하세요", file=sys.stderr)
        return 1
    if hook.get("url"):
        # 웹훅이 걸려 있으면 getUpdates를 쓸 수 없다. 이 템플릿은 웹훅을 쓰지 않는다.
        print("웹훅이 설정돼 있어 getUpdates를 쓸 수 없습니다 — @BotFather 봇이 아닌 다른 도구가 "
              "이 봇에 웹훅을 걸었는지 확인하세요.", file=sys.stderr)
        return 1

    res = _call(token, "getUpdates").get("result", [])
    known = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    chats = {}
    for up in res:
        msg = up.get("message") or up.get("edited_message") or {}
        chat = msg.get("chat")
        if chat:
            chats[str(chat["id"])] = chat

    fresh = [c for c in chats if c != known]

    if not chats:
        say("대기 중인 대화가 없습니다.\n"
            "  · 텔레그램에서 내 봇을 열고 시작(/start)을 누르거나 아무 말이나 보내세요\n"
            "  · 보낸 지 24시간이 지났으면 업데이트가 만료됐으니 한 번 더 보내세요")
        return 1 if quiet else 0

    say(f"대화 {len(chats)}건:\n")
    for cid, chat in chats.items():
        name = " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
        uname = f"@{chat['username']}" if chat.get("username") else ""
        mine = "  <- 내 것(TELEGRAM_CHAT_ID)" if cid == known else ""
        say(f"  {cid:<16} {chat.get('type', '?'):<8} {name} {uname}{mine}")

    if quiet:
        # 오배송 방지 — 후보가 정확히 1건일 때만 id를 내준다.
        if len(fresh) != 1:
            say(f"\n내 것을 뺀 대화가 {len(fresh)}건이라 특정할 수 없습니다. 목록을 보고 직접 고르세요.")
            return 1
        print(fresh[0])
        return 0

    if not known:
        say("\n이름을 보고 내 대화의 id를 GitHub 시크릿 TELEGRAM_CHAT_ID에 넣으세요.")
    elif len(fresh) == 1:
        say(f"\n가족·친구의 id라면 GitHub 시크릿 FORTUNE_CHAT_IDS에 넣으세요 — "
            f'예: {{"<me.yaml의 chat 칸 이름>": "{fresh[0]}"}} (ADDING_A_RECIPIENT.md)')
    elif not fresh:
        say("\n내 대화만 잡혔습니다 — 상대가 아직 봇에 시작(/start)을 누르지 않았습니다.")
    else:
        say("\n여러 대화가 잡혔습니다 — 이름을 보고 한 명씩 FORTUNE_CHAT_IDS에 넣으세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
