# -*- coding: utf-8 -*-
"""
발송 전 결정론 품질 게이트.

프롬프트로 금지해도 생성문에서 되풀이되기 쉬운 굳은 틀(사주 '어제 ~였다면' 비교 틀 ·
종합 수렴 선언 · 별자리 보고 오프닝)과 용어 누출은 지시만으로 안 잡혀서 코드로 잡는다:
생성 직후 check() → 위반 시 위반 목록을 넣어 재생성 최대 2회 → 그래도 남으면
위반 적은 쪽을 발송(fail-open — 결측일이 반복 틀 하루보다 나쁘다). run_daily가 수행.

용어 정책: 십성(정관·편재 등)·점성 외래어(하우스 등)는 차단, 구조어(일진·천간·지지·
대운·세운)는 허용 — 실제로 문제가 된 것은 십성 노출이었고 구조어는 문맥으로 이해 가능.
'상관'은 일상어 '상관없-'을 제외하고 판정한다.
말투: 캐주얼 해요체 — 합쇼체(~니다 종결)가 3건 이상이면
보고서 톤 회귀로 보고 차단한다(1~2건은 강조용 허용).
"""
import re

# 십성 + 점성 외래어. 구조어(일진·천간·지지·대운·세운)는 의도적으로 제외.
_TERMS = [
    "정관", "편관", "정재", "편재", "정인", "편인", "식신", "비견", "겁재",
    "관성", "재성", "인성", "식상", "비겁", "관살",
    "하우스", "어스펙트", "트라인", "스퀘어", "컨정션",
]
_RE_SANGGWAN = re.compile(r"상관(?!\s*없|하|이\s*없)")       # 상관없이·상관 없이·상관하지는 평범한 낱말
_TERM_EXCEPT = {"식상": "(?![하한해했])", "비겁": "(?![하한해했])"}   # 식상하다(진부하다)·비겁하다는 평범한 낱말
_RE_HANJA = re.compile(r"[一-鿿]")
_EMOJI_CLASS = r"[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]"
_RE_EMOJI = re.compile(_EMOJI_CLASS)
_RE_MARKDOWN = re.compile(r"\*\*|__|^#|`", re.M)
# 자동 교정용: 서식 위반은 재생성(Claude 호출 1회 = 요금)이 아니라 문자 제거로 고친다.
_RE_MD_STRIP = re.compile(r"\*\*|__|`")
_RE_MD_HEADING = re.compile(r"^#{1,6}[ \t]*", re.M)
_RE_EMOJI_RUN = re.compile(r"[ \t]*" + _EMOJI_CLASS + r"+[ \t]*")
# 날짜 줄 — 맨 윗줄은 코드가 만든 글자(interpret.date_line)가 정답이다. 실호출에서 첫 줄이
# '6월이 아니라 11월 14일 토요일'로 나왔는데 예전 게이트는 첫 줄을 보지 않아 그대로 통과했다.
_DATE_LINE_PREFIX = "날짜 줄 불일치"
_AUTOFIX_PREFIXES = ("마크다운 서식 기호", "이모지 사용", _DATE_LINE_PREFIX)
# 사주 섹션의 '어제 ~다면/~는데' 비교·대조 문형 (생성문에서 굳어지기 쉬운 틀).
# 별자리의 "어제부터 이어지는 ~ 있는데" 같은 정상 지속 서술을 오탐하지 않도록
# 사주 섹션에만 적용한다.
_RE_COMPARE = re.compile(r"어제[^.]{0,60}(다면|는데)")
_RE_CONVERGE = re.compile(r"두 신호|같은 방향을 (가리|향하)|같은 곳을 향|공통으로 가리")
_RE_PARALLEL = re.compile(r"사주[는가].{0,80}별자리[는가]", re.S)
_RE_SUPERLATIVE = re.compile(r"올(해)? 들어 (처음|가장)")
# 캐주얼 해요체 강제 — '~니다' 종결(합쇼체·'아니다' 류 포함) 카운트
_RE_HAPSYO = re.compile(r"[가-힣]니다\b")
_HAPSYO_MAX = 2
# 별자리 첫 문장의 천체 보고 오프닝 (생성문에서 굳어지기 쉬운 틀)
_ASTRO_OPENERS = ["들어온 각", "들어온 신호", "새 각", "가장 선명한 신호", "가장 선명하게"]

# 조건부 헤더 섹션 — 데이터가 주어진 날에만 허용. 월요일에 【이번 달 흐름】이
# 무단으로 생기던 공백을 막는다(run_daily가 그날의 기대치를 넘긴다).
_HEADER_SECTIONS = {"monthly": "【이번 달 흐름】", "weekly": "【이번 주 흐름】"}
_HEADER_WHEN = {"monthly": "매월 1일", "weekly": "월요일"}

DOMAIN_SECTION = "【돈·연애·건강·일】"
_REQUIRED = ["오늘 한 줄:", "【오늘의 사주】", "【오늘의 별자리】", DOMAIN_SECTION, "【종합】"]
_DOMAINS = ["돈", "연애", "건강", "일"]

# 반말 종결 가드 — EXTERNAL_PROFILE에서 켠다.
# 합쇼체(~니다)·존댓말이 아닌 '~다.' 종결만 잡는다. lookbehind가 니/습을 배제한다.
_RE_BANMAL = re.compile(r"(?<=[가-힣])(?<![니습])다[.!?]")

# 프로파일 — DEFAULT_PROFILE은 반말 검사를 끈 기본값, EXTERNAL_PROFILE은 반말까지 막는다.
# 이 템플릿의 run_daily는 모든 사람에게 EXTERNAL_PROFILE을 쓴다(메시지가 해요체로만 나가게).
DEFAULT_PROFILE = {
    "hapsyo_max": _HAPSYO_MAX,
    "domain_section": DOMAIN_SECTION,
    "domains": _DOMAINS,
    "required": _REQUIRED,
    "ban_banmal": False,
}
EXTERNAL_PROFILE = {**DEFAULT_PROFILE, "ban_banmal": True}


def _section(msg: str, title: str) -> str:
    m = re.search(re.escape(title) + r"\s*\n(.*?)(?=\n【|\Z)", msg, re.S)
    return m.group(1).strip() if m else ""


def _first_sentence(text: str) -> str:
    return text.split(".", 1)[0] if text else ""


def _nonblank_lines(msg: str) -> list:
    """[(줄 번호, 앞뒤 공백 뗀 글자)] — 빈 줄은 뺀다."""
    return [(i, ln.strip()) for i, ln in enumerate(msg.split("\n")) if ln.strip()]


def check(msg: str, profile: dict | None = None, headers: dict | None = None,
          date_line: str | None = None) -> list:
    """위반 목록(설명 문자열). 비어 있으면 통과.
    profile을 안 주면 DEFAULT_PROFILE(반말 검사 꺼짐).
    headers={"monthly": bool, "weekly": bool} — 그날 데이터 기준 기대치. None이면
    이 검사는 건너뛴다(소급 리플레이·날짜 모르는 호출부 호환).
    date_line — 코드가 만든 맨 윗줄(interpret.date_line). 주면 첫 줄이 글자까지 같은지 본다."""
    P = profile or DEFAULT_PROFILE
    v = []

    if date_line is not None:
        lines = _nonblank_lines(msg)
        first = lines[0][1] if lines else ""
        if first != date_line:
            v.append(f"{_DATE_LINE_PREFIX}: 맨 윗줄은 '{date_line}'을 글자 그대로 — 지금은 '{first[:40]}'")

    m = _RE_HANJA.search(msg)
    if m:
        v.append(f"한자 노출: {m.group()}")
    if _RE_EMOJI.search(msg):
        v.append("이모지 사용")
    if _RE_MARKDOWN.search(msg):
        v.append("마크다운 서식 기호 사용")

    hapsyo = _RE_HAPSYO.findall(msg)
    if len(hapsyo) > P["hapsyo_max"]:
        v.append(f"합쇼체 과다: ~니다 종결 {len(hapsyo)}건 — 캐주얼 해요체(~예요/~해요)로")

    terms = sorted(t for t in _TERMS if re.search(re.escape(t) + _TERM_EXCEPT.get(t, ""), msg))
    if _RE_SANGGWAN.search(msg):
        terms.append("상관")
    if terms:
        v.append("전문용어 노출: " + "·".join(terms))

    for need in P["required"]:
        if need not in msg:
            v.append(f"필수 요소 누락: {need}")

    if headers is not None:
        for key, title in _HEADER_SECTIONS.items():
            has, want = title in msg, bool(headers.get(key))
            if has and not want:
                v.append(f"무단 헤더 섹션: {title} — {_HEADER_WHEN[key]}이 아닌데 생성")
            elif want and not has:
                v.append(f"필수 요소 누락: {title}")

    saju = _section(msg, "【오늘의 사주】")
    if _RE_COMPARE.search(saju):
        v.append("비교 틀: 사주 섹션 '어제 ~다면/~는데' 문형")

    astro_first = _first_sentence(_section(msg, "【오늘의 별자리】"))
    if astro_first.startswith("오늘 달이") or any(o in astro_first for o in _ASTRO_OPENERS):
        v.append("별자리 오프닝 보고 틀: 첫 문장을 각/천체 보고로 시작")

    if _RE_CONVERGE.search(msg):
        v.append("수렴 선언: '두 신호/같은 방향' 류")

    if _RE_PARALLEL.search(_section(msg, "【종합】")):
        v.append("종합 병렬 요약: '사주는 ~, 별자리는 ~' 틀")

    if _RE_SUPERLATIVE.search(msg):
        v.append("검증 불가 최상급: '올 들어 처음/가장' 류")

    if P["ban_banmal"]:
        bm = _RE_BANMAL.findall(msg)
        if bm:
            v.append(f"반말 종결 {len(bm)}건 — 해요체만 쓴다")

    dom = _section(msg, P["domain_section"])
    if dom:
        for d in P["domains"]:
            if not re.search(rf"^{d} ?[—\-–]", dom, re.M):
                v.append(f"영역 줄 누락: {d}")

    return v


def pick_better(msg1: str, v1: list, msg2: str, v2: list):
    """재생성본(msg2)이 같거나 나으면 재생성본 채택 (피드백 반영본 우선)."""
    return (msg2, v2) if len(v2) <= len(v1) else (msg1, v1)


def autofixable(violations) -> bool:
    """서식 위반(마크다운 기호·이모지)이나 날짜 줄 불일치가 하나라도 있으면 True — autofix로 고칠 수 있는 종류다."""
    return any(str(v).startswith(_AUTOFIX_PREFIXES) for v in violations)


def _fix_date_line(msg: str, date_line: str) -> str:
    """맨 윗줄을 코드가 만든 날짜 줄로 맞춘다. 구조가 분명할 때만 고친다:
      첫 줄이 '오늘 한 줄'이면 날짜 줄이 빠진 것 → 그 위에 넣는다
      둘째 줄이 '오늘 한 줄'이면 첫 줄이 (틀린) 날짜 줄 → 바꾼다
      그 밖이면 첫 줄이 날짜 줄인지 알 수 없다 → 손대지 않는다(위반으로 남아 재생성된다)."""
    lines = msg.split("\n")
    nb = _nonblank_lines(msg)
    if not nb or nb[0][1] == date_line:
        return msg
    i0 = nb[0][0]
    if nb[0][1].startswith("오늘 한 줄"):
        return "\n".join(lines[:i0] + [date_line] + lines[i0:])
    if len(nb) > 1 and nb[1][1].startswith("오늘 한 줄"):
        return "\n".join(lines[:i0] + [date_line] + lines[i0 + 1:])
    return msg


def _emoji_gap(m) -> str:
    """지운 이모지 자리 — 앞뒤가 낱말이면 한 칸을 남겨 낱말이 붙지 않게, 줄 끝·문장부호 앞이면 아무것도 남기지 않는다."""
    s = m.string
    prev = s[m.start() - 1] if m.start() > 0 else "\n"
    nxt = s[m.end()] if m.end() < len(s) else "\n"
    return " " if not prev.isspace() and not nxt.isspace() and nxt not in ".,!?…)]" else ""


def autofix(msg: str, date_line: str | None = None) -> str:
    """서식 위반의 결정론 교정 — 굵게(**·__)·코드(`)·줄머리 #·이모지만 지운다. 낱말은 손대지 않는다.
    date_line을 주면 맨 윗줄도 코드가 만든 날짜 줄로 맞춘다(_fix_date_line).
    같은 본문을 다시 생성하는 것보다 싸고(호출 0회), 채택된 문장이 그대로 남아 품질도 같다.
    용어 노출·문형 틀은 여기서 못 고친다 — 그건 종전대로 재생성(run_daily)."""
    out = _RE_MD_STRIP.sub("", msg)
    out = _RE_MD_HEADING.sub("", out)
    out = _RE_EMOJI_RUN.sub(_emoji_gap, out)
    out = re.sub(r"[ \t]+$", "", out, flags=re.M)     # 지운 자리의 꼬리 공백
    out = re.sub(r"^[ \t]+", "", out, flags=re.M)     # 줄머리 이모지를 지운 자리
    if date_line is not None:
        out = _fix_date_line(out, date_line)
    return out
