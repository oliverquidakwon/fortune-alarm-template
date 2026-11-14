# -*- coding: utf-8 -*-
"""
매일 운세 알림 — 메인 오케스트레이터.

  python run_daily.py                       # KST 오늘 → me.yaml의 사람마다 해석 생성 → 텔레그램 발송
  python run_daily.py --dry-run             # 해석만 출력 (발송·state 저장 안 함. Claude 호출은 한다)
  python run_daily.py --date 2026-11-15 --dry-run   # 특정 날짜로 시험
  python run_daily.py --people 하늘          # 이름을 골라 보내기 (기본: me.yaml 전원)
  python run_daily.py --force               # 오늘 이미 보낸 사람에게도 다시 발송 (같은 날 가드 해제)

설정은 me.yaml 하나(me_config.py가 읽는다). 사람마다 명식·최근 발송문 파일·받을 곳이 다르고,
한 사람이 실패해도 다른 사람의 발송·저장에는 영향을 주지 않는다.

같은 날 가드: 그 사람의 state에 오늘 날짜가 있으면(= 오늘 이미 보냈으면) 건너뛴다. 예약 실행 뒤에
수동 실행을 한 번 더 눌러도 두 번 가지 않고 요금도 두 번 나가지 않는다(state는 발송 성공 때만 저장).

환경변수(로컬에서는 이 폴더의 .env를 자동으로 읽는다):
  ANTHROPIC_API_KEY · TELEGRAM_BOT_TOKEN · TELEGRAM_CHAT_ID · (선택) FORTUNE_CHAT_IDS
"""
import argparse
import json
import os
import re
import sys
import traceback
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import astro_core  # noqa: E402
import me_config  # noqa: E402
import saju_core  # noqa: E402

# 최근 발송문 상태 — 다음날 프롬프트에 넣어 문장 틀 반복을 피한다.
# 워크플로가 발송 뒤 state/ 폴더를 커밋한다(.github/workflows/daily-fortune.yml). 폴더는 첫 저장 때 만든다.
STATE_PATH = os.path.join(HERE, "state", "recent.json")
RECENT_KEEP = 7


def state_path_for(state_file: str) -> str:
    """사람별 state 파일 경로. STATE_PATH의 폴더를 기준으로 잡아, 테스트가 STATE_PATH를
    바꿔 끼우면 모든 사람이 함께 임시 경로를 탄다."""
    return os.path.join(os.path.dirname(STATE_PATH), state_file)


def load_recent(path: str | None = None) -> list:
    """state 파일 → [{date, text}] (없거나 깨졌으면 빈 목록, fail-open).
    path 기본값을 인자에 묶지 않는다 — 그러면 STATE_PATH를 바꿔 끼워도 안 먹는다."""
    try:
        with open(path or STATE_PATH, encoding="utf-8") as f:
            rows = json.load(f)
        return [r for r in rows if isinstance(r, dict) and r.get("date") and r.get("text")]
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def recent_for_prompt(recent: list, d: date) -> list:
    """프롬프트용 최근 발송문 — 오늘자 항목은 뺀다. 같은 날 다시 만들 때 그날 아침 발송문이
    '반복 회피 대조용'으로 들어가면 모델이 그것을 밑그림 삼아 거의 그대로 베낀다."""
    return [r for r in recent if r["date"] != d.isoformat()]


def save_recent(recent: list, d: date, msg: str, path: str | None = None) -> None:
    """오늘 발송문을 추가하고 최근 RECENT_KEEP일만 유지 (같은 날짜는 대체)."""
    path = path or STATE_PATH
    rows = [r for r in recent if r["date"] != d.isoformat()]
    rows.append({"date": d.isoformat(), "text": msg})
    rows.sort(key=lambda r: r["date"])
    rows = rows[-RECENT_KEEP:]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
        f.write("\n")


def _load_env(fname: str = ".env") -> None:
    """간단 .env 로더 — 이 폴더의 .env만 읽고, 이미 있는 환경변수는 덮지 않는다."""
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


def kst_today() -> date:
    return datetime.now(timezone(timedelta(hours=9))).date()


def sent_today(person, d: date) -> bool:
    """그 사람의 state에 d 날짜 발송문이 있으면 True — 그날 이미 보냈다는 뜻이다."""
    return any(r["date"] == d.isoformat() for r in load_recent(state_path_for(person.state_file)))


def report_chat_id(tag: str, where: str, chat_id, dry_run: bool) -> None:
    """dry-run에서 받을 곳이 실제로 풀리는지 말한다(시크릿을 넣고 다음날 '조용히 건너뜀'을 발견하지
    않도록). 실발송 경로는 조용하다. 전체 id는 남기지 않고 끝 4자리만 찍는다."""
    if not dry_run:
        return
    if chat_id:
        print(f"{tag} [dry-run] chat_id 확인 (…{str(chat_id)[-4:]}, {where})")
    else:
        print(f"{tag} [dry-run] chat_id 없음 ({where}) — 실발송이면 건너뛴다")


def prepare(person, d: date, dry_run: bool, model: str):
    """한 사람의 생성 입력(명식 층·최근 발송문·프롬프트 프로파일)을 만든다.
    → ctx dict, 또는 받을 곳(chat id)이 없어 건너뛸 때 "skipped"."""
    import interpret
    import quality_gate

    tag = f"[{person.name}]"
    chat_id = me_config.resolve_chat_id(person.chat)
    report_chat_id(tag, person.chat_where, chat_id, dry_run)
    if not dry_run and not chat_id:
        # 보내지도 못할 운세에 Claude 요금을 쓰지 않는다 — 생성 전에 거른다
        print(f"{tag} chat_id 없음 ({person.chat_where}) → 발송 건너뜀")
        return "skipped"

    chart = person.chart
    for w in chart.WARNINGS:            # 자시 경계·표준시 보정·절기 경계 — 조용히 틀리는 자리
        print(f"{tag} 확인 필요: {w}")

    layers = saju_core.four_layers(d, chart)
    layers["astro"] = astro_core.today_layer(d, chart=chart)
    spath = state_path_for(person.state_file)
    recent = load_recent(spath)
    layers["recent"] = recent_for_prompt(recent, d)
    if d.weekday() == 0:                       # 매주 월요일 → 이번 주 흐름
        layers["weekly"] = saju_core.week_outlook(d, chart)
    if d.day == 1:                             # 매월 1일 → 이번 달 흐름
        layers["monthly"] = saju_core.month_outlook(d, chart)

    # 데이터 미리보기 (로그)
    _a = layers["astro"]
    print(f"{tag} [{d}] 4층:"
          f" 대운 {layers['daewoon']['ganji'] if layers['daewoon'] else '-'} /"
          f" 년 {layers['year']['ganji']} /"
          f" 월 {layers['month']['ganji']} /"
          f" 일 {layers['day']['ganji']}")
    _new = sum(1 for a in _a["aspects"] if not a.get("persists"))
    print(f"{tag}         별자리: 달 {_a['moon'][0]} {_a['moon'][1]:.0f}°"
          f" / 태양 {_a['sun'][0]} {_a['sun'][1]:.0f}°"
          f" / 주요각 {len(_a['aspects'])}건 (새 각 {_new})"
          f" / 최근 발송문 {len(layers['recent'])}건(프롬프트 기준, 오늘자 제외)")

    return {
        "person": person, "tag": tag, "chat_id": chat_id, "layers": layers, "model": model,
        "prof": interpret.profile_for(chart), "gate": quality_gate.EXTERNAL_PROFILE,
        "hdr": {"monthly": "monthly" in layers, "weekly": "weekly" in layers},
        "date_line": interpret.date_line(d),     # 맨 윗줄의 정답 — 게이트가 글자까지 대조한다
        "recent": recent, "spath": spath,
    }


# 끝까지 오지 않은 응답 — 위반으로 보고 다시 쓰게 하고, 끝까지 이런 글뿐이면 보내지 않는다(fail-open의 예외)
_CUT_PREFIX = "온전하지 않은 응답"
_CUT_NOTES = {
    "max_tokens": f"{_CUT_PREFIX}: 분량 상한(max_tokens)에서 끊김 — 더 짧게 쓰고 마지막 문장까지 끝맺을 것",
    "refusal": f"{_CUT_PREFIX}: 거절로 끝남 — 주어진 계산값을 근거로 오늘 운세 본문을 쓸 것",
}


def _complete(viols) -> bool:
    """보낼 수 있는 온전한 글인지 — 끊김·거절이 없고 필수 섹션(오늘 한 줄·네 섹션·종합)이 다 있다."""
    return not any(str(v).startswith((_CUT_PREFIX, "필수 요소 누락")) for v in viols)


def _pick(msg1, v1, msg2, v2):
    """재생성본이 같거나 나으면 재생성본(피드백 반영본 우선) — 온전한 글인지를 위반 수보다 먼저 본다."""
    return (msg2, v2) if (not _complete(v2), len(v2)) <= (not _complete(v1), len(v1)) else (msg1, v1)


def _gate(ctx: dict, msg: str):
    """게이트 검사 → 서식 위반(마크다운 기호·이모지)은 문자 제거로, 날짜 줄은 코드가 만든 글자로 자동 교정
    → 재검사. 반환 (msg, 남은 위반, 교정 전 위반). 교정 전 위반도 재생성 지시(다시 쓰지 말 목록)에 넣는다."""
    import quality_gate

    dl = ctx["date_line"]
    cut = [_CUT_NOTES[r] for r in (getattr(msg, "stop_reason", None),) if r in _CUT_NOTES]
    viols = quality_gate.check(msg, ctx["gate"], headers=ctx["hdr"], date_line=dl) + cut
    raw = list(viols)
    if viols and quality_gate.autofixable(viols):
        fixed = quality_gate.autofix(msg, date_line=dl)
        if fixed != msg:
            fv = quality_gate.check(fixed, ctx["gate"], headers=ctx["hdr"], date_line=dl) + cut
            print(f"{ctx['tag']} [게이트] 자동 교정(서식 기호·이모지·날짜 줄): 위반 {len(viols)}→{len(fv)}건")
            msg, viols = fixed, fv
    return msg, viols, raw


def finish(ctx: dict, msg: str, d: date, dry_run: bool) -> str:
    """게이트 → (필요 시 재생성) → 발송 → state 저장. → "sent" | "dry" | "failed"."""
    import interpret

    tag, person = ctx["tag"], ctx["person"]

    # 발송 게이트 — 프롬프트 지시로 못 잡는 굳은 틀·용어 누출을 기계 검출.
    # 서식 위반은 자동 교정, 나머지 위반은 위반 목록을 붙여 재생성 최대 2회,
    # 그래도 남으면 위반 적은 쪽 발송(fail-open — 안 오는 날이 틀 반복 하루보다 나쁘다).
    msg, viols, raw = _gate(ctx, msg)
    # 재생성 지시는 '채택본의 위반'이 아니라 지금까지 본 위반의 합집합 — 1회차에서 본 위반이
    # 2회차 지시에서 빠지면 같은 위반을 또 만든다.
    seen = list(raw)
    for attempt in (1, 2):   # 재생성이 새 위반을 만들 수 있어 최대 2회
        if not viols:
            break
        print(f"{tag} [게이트] 위반 {len(viols)}건 → 재생성 {attempt}회차"
              f" (지시 누적 {len(seen)}건): {' / '.join(seen)}")
        retry = interpret.generate(ctx["layers"], model=ctx["model"], retry_note=seen,
                                   profile=ctx["prof"])
        retry, rv, rraw = _gate(ctx, retry)
        seen += [x for x in rraw if x not in seen]
        print(f"{tag} [게이트] 재생성 {attempt}회차 위반 {len(rv)}건"
              + (f": {' / '.join(rv)}" if rv else ""))
        msg, viols = _pick(msg, viols, retry, rv)

    print(f"\n===== 생성 메시지 ({person.name}) =====")
    print(msg)
    print("=======================")
    if not _complete(viols):
        print(f"{tag} [게이트] 끝까지 온전한 글이 없어 보내지 않음(끊김·거절·필수 섹션 누락): "
              + " / ".join(v for v in viols if not _complete([v])))
        return "failed"
    print(f"{tag} [게이트] 통과" if not viols
          else f"{tag} [게이트] 잔존 {len(viols)}건 fail-open 발송: {' / '.join(viols)}")

    if dry_run:
        print(f"{tag} [dry-run] 발송·state 저장 생략")
        return "dry"

    import notify
    if not notify.send_telegram(msg, chat_id=ctx["chat_id"]):
        print(f"{tag} [발송 실패] 텔레그램 발송 실패 — state 저장 생략", file=sys.stderr)
        return "failed"

    save_recent(ctx["recent"], d, msg, ctx["spath"])
    print(f"{tag} [발송 완료] state 저장: state/{os.path.basename(ctx['spath'])}")
    return "sent"


def run_one(person, d: date, dry_run: bool, model: str) -> str:
    """한 사람 처리 → "sent" | "dry" | "skipped" | "failed".
    자기 state 파일만 읽고 쓴다 — 한 사람의 실패가 다른 사람의 반복 회피 입력을 오염시키지 않는다."""
    import interpret

    ctx = prepare(person, d, dry_run, model)
    if ctx == "skipped":
        return "skipped"
    msg = interpret.generate(ctx["layers"], model=model, profile=ctx["prof"])
    return finish(ctx, msg, d, dry_run)


def send_precheck(all_people, selected) -> str | None:
    """실발송 전, Claude를 부르기 전에 봇 토큰과 본인(맨 위 사람)의 받을 곳을 확인한다 → 문제면 고칠 말 한 문장.
    토큰이 없으면 Claude 요금만 쓰고 발송에서 죽고, 본인의 chat id가 없으면 '건너뜀'으로 초록 불이 켜져
    아무것도 안 온 날을 알 길이 없다. 가족·친구의 chat id가 없는 것은 종전대로 그 사람만 건너뛴다."""
    where = "저장소 Settings → Secrets and variables → Actions(내 컴퓨터에서 돌릴 때는 이 폴더의 .env)"
    if not (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip():
        return (f"시크릿 TELEGRAM_BOT_TOKEN이 비어 있습니다 — {where}에 BotFather가 준 봇 토큰을 넣어 주세요"
                "(Claude는 부르지 않았습니다).")
    me = next((p for p in all_people if p.primary), None)
    if me is None or not any(p is me for p in selected) or me_config.resolve_chat_id(me.chat):
        return None
    if me.chat == "me":
        return (f"시크릿 TELEGRAM_CHAT_ID가 비어 있습니다 — 맨 위 사람(본인) '{me.name}'에게 보낼 chat id(숫자)를 "
                f"{where}에 넣어 주세요(찾는 법: README '시크릿 3개 넣기', Claude는 부르지 않았습니다).")
    return (f"맨 위 사람(본인) '{me.name}'의 받을 곳({me.chat_where})이 비어 있습니다 — 시크릿 FORTUNE_CHAT_IDS에 "
            f'{{"{me.chat}": "숫자"}}를 넣거나 me.yaml에서 chat: me로 바꿔 주세요(Claude는 부르지 않았습니다).')


def _resend_hint() -> str:
    """같은 날 가드 안내 — Actions에는 --force 입력이 없으니 실행 기록에서는 dry_run을 알려 준다."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return "같은 날 두 번 보내지 않습니다. 오늘 글을 다시 만들어 보려면 수동 실행에서 dry_run을 체크하세요(보내지 않음)"
    return "다시 보내려면 --force"


_SECRET_ENVS = ("TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY", "TELEGRAM_CHAT_ID", "FORTUNE_CHAT_IDS")


def redact(text: str) -> str:
    """로그로 내보낼 글자에서 시크릿 값과 토큰·키 꼴을 가린다. 라이브러리 예외 문장에는 요청 URL(텔레그램은 URL에 토큰이
    들어간다)이나 헤더 값이 실려 올 수 있다 — 앞뒤 공백을 지운 값, 줄바꿈으로 쪼개진 조각, 이스케이프된 꼴까지 지운다."""
    pieces = set()
    for name in _SECRET_ENVS:
        raw = os.environ.get(name) or ""
        pieces |= {raw, raw.strip(), raw.encode("unicode_escape").decode("ascii", "replace")}
        pieces |= set(re.split(r"\s+", raw)) | set(re.findall(r"\d{6,}", raw))
    for p in sorted((p for p in pieces if len(p) >= 6), key=len, reverse=True):
        text = text.replace(p, "<가림>")
    text = re.sub(r"\d{6,}:[A-Za-z0-9_-]{10,}", "<토큰 가림>", text)
    return re.sub(r"sk-ant-[A-Za-z0-9_\-]+", "sk-ant-<가림>", text)


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):      # 한글 윈도의 cp949 콘솔·파이프에서 못 쓰는 글자(—)는 ?로 — 죽지 않는다
        if hasattr(s, "reconfigure"):
            s.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description="me.yaml의 사람마다 오늘 운세를 만들어 텔레그램으로 보낸다")
    ap.add_argument("--dry-run", action="store_true",
                    help="해석만 출력하고 발송·state 저장은 생략 (Claude 호출은 한다)")
    ap.add_argument("--date", help="YYYY-MM-DD (시험용, 기본 KST 오늘)")
    ap.add_argument("--people", help="보낼 사람 이름 콤마 구분 (기본 me.yaml 전원)")
    ap.add_argument("--force", action="store_true",
                    help="같은 날 가드 해제 — 오늘 이미 보낸 사람에게도 다시 발송")
    ap.add_argument("--config", default=me_config.DEFAULT_PATH, help="설정 파일 경로 (기본 me.yaml)")
    args = ap.parse_args(argv)

    _load_env()

    try:
        d = date.fromisoformat(args.date) if args.date else kst_today()
    except ValueError:
        print(f"[run] --date '{args.date}'를 읽지 못했습니다 — 2026-11-15처럼 YYYY-MM-DD로 적어 주세요.",
              file=sys.stderr)
        return 1
    try:
        cfg = me_config.load(args.config)
        people = me_config.select(cfg.people, args.people)
    except me_config.ConfigError as e:
        print(f"[me.yaml] {e}", file=sys.stderr)
        return 1
    print(f"[run] {d} 받을 사람 {[p.name for p in people]} · 모델 {cfg.model}")
    if not args.dry_run:
        problem = send_precheck(cfg.people, people)
        if problem:
            print(f"[설정] {problem}", file=sys.stderr)
            return 1

    results = {}
    # 같은 날 가드 — 생성 전에 거른다. 이미 보낸 사람 몫의 Claude 호출도 하지 않는다.
    # dry-run은 발송하지 않으므로 가드 대상이 아니다(미리보기는 그대로).
    if not args.dry_run and not args.force:
        for p in people:
            if sent_today(p, d):
                print(f"[{p.name}] {d} 이미 발송됨 (state에 오늘 날짜) → 건너뜀 — {_resend_hint()}")
                results[p.name] = "already"

    for p in people:
        if p.name in results:
            continue
        try:
            results[p.name] = run_one(p, d, args.dry_run, cfg.model)
        except Exception:          # 한 사람의 사고가 나머지 발송을 막지 않는다
            print(redact(traceback.format_exc()), end="", file=sys.stderr)
            results[p.name] = "failed"

    print("[run] 결과: " + ", ".join(f"{p.name}={results[p.name]}" for p in people))

    failed = [p for p in people if results[p.name] == "failed"]
    if not failed:
        return 0
    for p in failed:
        print(f"::error title=fortune-{p.birth.key}::발송 실패 — 로그의 [{p.name}] 줄 확인",
              file=sys.stderr)
    if any(p.primary for p in failed):
        return 1               # 맨 위 사람(본인) 실패 = 전체 실패
    return 2                   # 부분 실패 — 워크플로가 state 커밋 뒤 빨간불로 처리


if __name__ == "__main__":
    raise SystemExit(main())
