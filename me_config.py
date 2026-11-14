# -*- coding: utf-8 -*-
"""
me.yaml → 받을 사람 목록. 이 템플릿에서 사람을 정하는 유일한 곳.

  python me_config.py              # me.yaml 점검 — 사람마다 명식·관례별 후보·대운·별자리 세 축·확인할 점 (Claude 호출 없음, 요금 0)
  python me_config.py 다른파일.yaml

잘못 적힌 칸은 무엇을 어떻게 고치라는 한 문장(ConfigError)으로 멈춘다. 조용히 다른 사람의
사주(또는 틀린 사주)가 매일 아침 나가는 것이 이 시스템의 최악이라, 모르는 칸·애매한 값은
추측하지 않고 멈춘다.
"""
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import yaml

import interpret
from birth import PLACES, BirthData

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "me.yaml")

_BLANK = {"", "~", "null", "Null", "NULL"}
_TOP_KEYS = ("model", "people")
_PERSON_KEYS = ("name", "birth", "gender", "hour_rule", "chat", "honorific")
_BIRTH_KEYS = ("date", "time", "place", "lat", "lon")
_LUNAR_KEYS = {"lunar", "calendar", "음력", "양력", "음양력"}
_DATE_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_PLACE_SUFFIXES = ("특별자치시", "특별자치도", "특별시", "광역시", "시")
_CHAT_KEY_RE = re.compile(r"^[A-Za-z0-9_\-가-힣]+$")
_UNSAFE_FILE_CHARS = re.compile(r"[^0-9A-Za-z가-힣_\-]+")


class ConfigError(ValueError):
    """me.yaml을 고쳐야 하는 경우. 메시지는 무엇을 어떻게 고칠지 한 문장."""


@dataclass
class Person:
    """me.yaml의 한 사람. 명식(chart)은 처음 쓸 때 한 번만 계산한다."""
    name: str
    birth: BirthData
    chat: str                  # "me" 또는 FORTUNE_CHAT_IDS의 칸 이름
    primary: bool = False      # 맨 위 사람(본인) — 이 사람 발송 실패는 전체 실패
    _chart: object = field(default=None, repr=False, compare=False)

    @property
    def state_file(self) -> str:
        return f"recent_{self.birth.key}.json"

    @property
    def chat_where(self) -> str:
        return "TELEGRAM_CHAT_ID" if self.chat == "me" else f'FORTUNE_CHAT_IDS의 "{self.chat}" 칸'

    @property
    def chart(self):
        if self._chart is None:
            import chart_factory
            self._chart = chart_factory.build(self.birth)
        return self._chart


@dataclass
class Config:
    people: list
    model: str                 # 해석에 쓸 Claude 모델 (me.yaml에서 비우면 interpret.DEFAULT_MODEL)


# ── 칸별 읽기 ────────────────────────────────────────────────

def _text(v) -> str:
    """BaseLoader가 준 값 → 앞뒤 공백을 뗀 글자. 빈 값 표기(~·null)는 빈 글자로."""
    s = "" if v is None else str(v).strip()
    return "" if s in _BLANK else s


def _kst_today() -> date:
    return datetime.now(timezone(timedelta(hours=9))).date()


def _lunar_error(name: str) -> ConfigError:
    return ConfigError(
        f"'{name}'의 생일이 음력으로 적혀 있습니다 — 이 템플릿은 양력만 받으니 음력-양력 변환기로 "
        "양력 날짜를 확인해(윤달인지도 함께) birth.date에 1992-03-14처럼 적어 주세요.")


def _check_keys(where: str, raw: dict, allowed: tuple, lunar_name: str = "") -> None:
    extra = [k for k in raw if k not in allowed]
    if not extra:
        return
    if lunar_name and any(k in _LUNAR_KEYS for k in extra):
        raise _lunar_error(lunar_name)
    raise ConfigError(
        f"{where}에 이 템플릿이 모르는 칸이 있습니다('{extra[0]}') — "
        f"{'·'.join(allowed)} 중 하나인지 철자를 확인해 주세요.")


def _date(name: str, raw) -> str:
    s = _text(raw)
    if not s:
        raise ConfigError(f"'{name}'의 birth.date가 비어 있습니다 — 1992-03-14처럼 양력 생년월일을 "
                          "연-월-일 하이픈(-)으로 적어 주세요.")
    if re.search(r"음력|윤달|lunar", s, re.I):
        raise _lunar_error(name)
    m = _DATE_RE.match(re.sub(r"\(?\s*양력\s*\)?", "", s).strip())
    if not m:
        raise ConfigError(f"'{name}'의 birth.date '{s}'를 읽지 못했습니다 — 1992-03-14처럼 "
                          "연(네 자리)-월-일을 하이픈(-)으로 이어 적어 주세요.")
    try:
        d = date(*(int(x) for x in m.groups()))
    except ValueError:
        raise ConfigError(f"'{name}'의 birth.date '{s}'는 달력에 없는 날짜입니다 — 월(1~12)과 "
                          "그 달의 날짜 수를 다시 확인해 주세요.") from None
    if d.year < 1900:
        raise ConfigError(f"'{name}'의 birth.date '{s}'는 1900년보다 이릅니다 — 이 템플릿은 "
                          "1900년 이후 출생만 받으니 연도를 다시 확인해 주세요.")
    if d > _kst_today():
        raise ConfigError(f"'{name}'의 birth.date '{s}'는 미래 날짜입니다 — 연도를 다시 확인해 주세요.")
    return d.isoformat()


def _time(name: str, raw) -> str:
    s = _text(raw)
    if not s:
        raise ConfigError(
            f"'{name}'의 birth.time이 비어 있습니다 — 이 템플릿은 태어난 시각 없이는 시주와 상승점을 "
            "계산하지 못하니 출생신고서나 가족 기억으로 HH:MM(예: 10:10)을 넣고, 끝내 모르면 12:00을 "
            "넣되 그때는 시주와 상승점이 실제와 다를 수 있다는 점을 알아 두세요.")
    m = _TIME_RE.match(s)
    h, mi = (int(m.group(1)), int(m.group(2))) if m else (-1, -1)
    if not m or h > 23 or mi > 59:
        raise ConfigError(f"'{name}'의 birth.time '{s}'를 읽지 못했습니다 — 23:40처럼 24시간제 "
                          "시:분으로 적어 주세요(오후 3시 5분이면 15:05).")
    return f"{h:02d}:{mi:02d}"


# 지역 사전의 이름과 겹치지만 다른 곳일 수 있는 이름 — 조용히 한쪽 좌표로 읽지 않고 멈춘다
_AMBIGUOUS_PLACES = {
    "광주시": "'광주시'는 경기도 광주시와 광주광역시 중 어느 곳인지 알 수 없습니다 — 광주광역시면 place: 광주로, "
             "경기도 광주시면 place 아래에 lat·lon(위도·경도)을 함께 적어 주세요(README '지역 목록').",
}


def _place_key(place: str):
    if place in PLACES:
        return place
    for suf in _PLACE_SUFFIXES:
        if place.endswith(suf) and place[: -len(suf)] in PLACES:
            return place[: -len(suf)]
    return None


def _place(name: str, birth: dict):
    """(place, lat, lon). 지역 사전에 있으면 좌표는 None(사전 값을 쓴다)."""
    place = _text(birth.get("place"))
    lat_s, lon_s = _text(birth.get("lat")), _text(birth.get("lon"))
    if lat_s or lon_s:
        if not (lat_s and lon_s):
            raise ConfigError(f"'{name}'의 birth에 lat과 lon 중 하나만 있습니다 — 위도(lat)와 "
                              "경도(lon)를 둘 다 적어 주세요(예: lat: 37.57, lon: 126.98).")
        try:
            lat, lon = float(lat_s), float(lon_s)
        except ValueError:
            raise ConfigError(f"'{name}'의 lat·lon은 숫자여야 합니다 — 37.57처럼 소수로 적어 주세요"
                              "(북위·동경 같은 글자는 빼고).") from None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ConfigError(f"'{name}'의 lat {lat_s}·lon {lon_s}는 범위 밖입니다 — 위도는 -90에서 90, "
                              "경도는 -180에서 180 사이로 적어 주세요.")
        return (place or "직접 입력한 좌표"), lat, lon
    if not place:
        raise ConfigError(f"'{name}'의 birth.place가 비어 있습니다 — 태어난 시 이름(예: 대전)을 적거나, "
                          "목록에 없는 곳이면 lat·lon(위도·경도)을 적어 주세요.")
    if place in _AMBIGUOUS_PLACES:
        raise ConfigError(f"'{name}'의 birth.place: {_AMBIGUOUS_PLACES[place]}")
    key = _place_key(place)
    if key is None:
        raise ConfigError(f"'{name}'의 birth.place '{place}'는 지역 목록에 없습니다 — 목록"
                          f"({'·'.join(PLACES)}) 가운데 하나로 적거나, place 아래 줄에 "
                          "lat·lon(위도·경도)을 함께 적어 주세요.")
    return key, None, None


def _gender(name: str, raw) -> str:
    s = _text(raw)
    if s in ("여", "남"):
        return s
    what = f"gender '{s}'를 알 수 없습니다" if s else "gender가 비어 있습니다"
    raise ConfigError(f"'{name}'의 {what} — 여 또는 남 중 하나로 적어 주세요"
                      "(대운이 흐르는 방향이 이 값으로 정해집니다).")


def _hour_rule(name: str, raw) -> str:
    s = _text(raw).upper()
    if not s:
        return "A"
    if s in ("A", "B", "C"):
        return s
    raise ConfigError(f"'{name}'의 hour_rule '{_text(raw)}'는 쓸 수 없습니다 — A·B·C 중 하나로 "
                      "적어 주세요(모르면 A, 뜻은 README의 '자시 경계와 세 가지 관례').")


def _chat(name: str, raw) -> str:
    s = _text(raw) or "me"
    if re.fullmatch(r"[+-]?\d+", s):
        raise ConfigError(f"'{name}'의 chat에 숫자(chat id)를 직접 적지 마세요 — 숫자는 GitHub 시크릿 "
                          "FORTUNE_CHAT_IDS에 넣고, 여기에는 그 칸 이름(예: bada)만 적어 주세요.")
    if not _CHAT_KEY_RE.match(s):
        raise ConfigError(f"'{name}'의 chat '{s}'는 쓸 수 없습니다 — me(내 텔레그램) 또는 "
                          "띄어쓰기 없는 칸 이름(예: bada)을 적어 주세요.")
    return s


# ── 사람 · 파일 ──────────────────────────────────────────────

def _person(i: int, raw) -> Person:
    if not isinstance(raw, dict):
        raise ConfigError(f"people의 {i}번째 항목을 읽지 못했습니다 — '- name: 하늘'처럼 하이픈 다음에 "
                          "칸을 적고, 그 사람의 칸들은 같은 깊이로 들여 써 주세요.")
    name = _text(raw.get("name"))
    if not name:
        raise ConfigError(f"people의 {i}번째 사람에 name이 없습니다 — 로그와 상태 파일에 쓸 "
                          "이름(예: 하늘)을 적어 주세요.")
    _check_keys(f"'{name}'", raw, _PERSON_KEYS)
    birth = raw.get("birth")
    if not isinstance(birth, dict):
        raise ConfigError(f"'{name}'에 birth 칸이 없습니다 — birth: 아래에 date·time·place를 "
                          "한 단계 더 들여 써 주세요.")
    _check_keys(f"'{name}'의 birth", birth, _BIRTH_KEYS, lunar_name=name)
    solar = f"{_date(name, birth.get('date'))} {_time(name, birth.get('time'))}"
    place, lat, lon = _place(name, birth)
    key = _UNSAFE_FILE_CHARS.sub("_", name).strip("_") or "person"   # 파일 이름에 쓸 수 있는 글자만
    b = BirthData(key=key, name=name, solar=solar, place=place,
                  sex=_gender(name, raw.get("gender")),
                  convention=_hour_rule(name, raw.get("hour_rule")),
                  lat=lat, lon=lon, honorific=_text(raw.get("honorific")))
    return Person(name=name, birth=b, chat=_chat(name, raw.get("chat")))


def _parse(data) -> Config:
    if not isinstance(data, dict):
        raise ConfigError("me.yaml이 비어 있거나 모양이 다릅니다 — 예시처럼 맨 위에 people: 칸을 두고 "
                          "그 아래에 사람을 적어 주세요.")
    _check_keys("me.yaml 맨 위", data, _TOP_KEYS)
    model = _text(data.get("model"))
    if model and not re.fullmatch(r"claude-[A-Za-z0-9.\-]+", model):
        raise ConfigError(f"model 칸의 값('{model}')이 Claude 모델 이름 꼴이 아닙니다 — 비워 두면 "
                          f"기본 모델 {interpret.DEFAULT_MODEL}을 쓰고, 바꾸려면 claude-로 시작하는 "
                          "모델 이름을 적어 주세요.")
    raw_people = data.get("people")
    if not isinstance(raw_people, list) or not raw_people:
        raise ConfigError("me.yaml에 people 목록이 없거나 비어 있습니다 — people: 아래에 "
                          "'- name: 하늘'처럼 적어도 한 사람을 적어 주세요.")
    people, seen = [], set()
    for i, raw in enumerate(raw_people, 1):
        p = _person(i, raw)
        if p.birth.key in seen:
            raise ConfigError(f"people에 이름이 겹치는 사람이 있습니다('{p.name}') — 사람마다 다른 이름을 "
                              "적어 주세요(최근 발송문 파일 이름이 이름에서 만들어집니다).")
        seen.add(p.birth.key)
        people.append(p)
    people[0].primary = True
    return Config(people=people, model=model or interpret.DEFAULT_MODEL)


def select(people: list, spec) -> list:
    """보낼 사람 고르기. 비었거나 'all'이면 전원, 아니면 콤마로 적은 이름만(me.yaml 순서 유지)."""
    names = [s.strip() for s in (spec or "").split(",") if s.strip()]
    if not names or "all" in names:
        return list(people)
    known = [p.name for p in people]
    unknown = [n for n in names if n not in known]
    if unknown:
        raise ConfigError(f"me.yaml에 없는 이름입니다('{unknown[0]}') — me.yaml의 name과 똑같이 "
                          f"적어 주세요({'·'.join(known)}).")
    return [p for p in people if p.name in names]


def resolve_chat_id(chat: str):
    """받을 곳 → 실제 chat id(없으면 None = 그 사람은 건너뜀).

    me는 시크릿 TELEGRAM_CHAT_ID, 그 밖의 이름은 시크릿 FORTUNE_CHAT_IDS(JSON 하나에 모은 것)의
    그 칸이다. GitHub 시크릿은 이름으로 하나씩 꺼내야 해서, 사람을 늘릴 때마다 워크플로를
    고치지 않도록 추가 수신자는 JSON 하나에 모은다."""
    if chat == "me":
        return os.environ.get("TELEGRAM_CHAT_ID", "").strip() or None
    blob = os.environ.get("FORTUNE_CHAT_IDS", "").strip()
    if not blob:
        return None
    try:
        table = json.loads(blob)
    except json.JSONDecodeError:
        table = None
    if not isinstance(table, dict):
        print(f"[chat] FORTUNE_CHAT_IDS가 올바른 JSON 객체가 아닙니다 — '{chat}' 건너뜀 "
              '(꼴: {"bada": "숫자"})')
        return None
    v = table.get(chat)
    return str(v).strip() if v not in (None, "") else None


def load(path: str = DEFAULT_PATH) -> Config:
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        raise ConfigError(f"설정 파일 {path}를 찾지 못했습니다 — 저장소 맨 위 폴더에 me.yaml이 "
                          "있는지 확인해 주세요.") from None
    try:
        # 모든 값을 글자 그대로 읽고(10:10 → 610, 날짜 → date 객체 같은 자동 변환을 막는다), 같은 칸이 두 번이면 멈춘다
        data = yaml.load(text, Loader=_StrictLoader)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None) or getattr(e, "context_mark", None)
        raise ConfigError(f"me.yaml {_where(text, mark)}을 읽지 못했습니다 — 예시처럼 '칸 이름: 값' 꼴(콜론 뒤 "
                          "한 칸)과 스페이스 들여쓰기(탭 금지)를 지키고, 주석을 풀 때는 # 뒤 공백까지 지워 위 줄과 "
                          "칸을 맞춰 주세요.") from None
    return _parse(data)


def _where(text: str, mark) -> str:
    """오류 위치 문구. YAML 파서는 고장 난 줄의 다음 줄을 가리킬 때가 많아, 바로 위의 내용 줄도 함께 적는다."""
    if mark is None:
        return "한 곳"
    lines, ln = text.splitlines(), mark.line + 1
    prev = next((i for i in range(min(ln, len(lines) + 1) - 1, 0, -1)
                 if lines[i - 1].strip() and not lines[i - 1].lstrip().startswith("#")), None)
    return f"{prev}번째 줄이나 {ln}번째 줄" if prev else f"{ln}번째 줄"


class _StrictLoader(yaml.BaseLoader):
    """BaseLoader(모든 값을 글자로) + 같은 칸이 두 번이면 멈춘다. YAML 기본은 뒤의 값이 앞의 값을 말없이 덮는다 —
    people:를 두 번 쓰면 맨 위 사람(본인)이 사라지고 다음 사람이 본인이 된다."""

    def construct_mapping(self, node, deep=False):
        seen = {}
        for key_node, _value in node.value:
            key = self.construct_object(key_node, deep=deep)
            line = key_node.start_mark.line + 1
            if key in seen:
                raise ConfigError(f"me.yaml에 '{key}' 칸이 두 번 있습니다({seen[key]}번째 줄과 {line}번째 줄) — "
                                  "뒤의 것이 앞의 것을 말없이 지우니 하나로 합쳐 주세요(사람을 더할 때는 people: "
                                  "아래에 '- name:' 블록만 붙입니다).")
            seen[key] = line
        return super().construct_mapping(node, deep=deep)


# ── CLI — me.yaml 점검 (계산만, Claude 호출 없음) ─────────────

def _daewoon_line(B, dw: dict, year: int) -> str:
    """'대운 역행 · 대운수 3세 (원값 2.91) · 지금 기해(己亥) 대운 2025년부터 2034년까지 — 올해 2026년은 2년째'.
    앞부분은 birth.py 미리보기와 같은 글자(birth.daewoon_head), 몇 년째는 해석 데이터와 같은 셈(birth.daewoon_now)."""
    now = B.daewoon_now(dw["ranges"], year)
    tail = (f" · 지금 {B._kor(now[0])}({now[0]}) 대운 {now[1]}년부터 {now[2]}년까지 — 올해 {year}년은 {now[3]}년째"
            if now else f" · 올해 {year}년은 대운표 범위 밖")
    edge = " · 반올림/버림 경계(시작 해가 1년 앞뒤로 갈릴 수 있음)" if dw.get("boundary") and now else ""
    return B.daewoon_head(dw) + tail + edge


def _axis(s: str) -> str:
    """출생 천궁도 값 '물고기 24°' → '물고기자리 24도'(이미 '양자리'면 그대로)."""
    sign, deg = s.split()[0], s.split()[1].rstrip("°")
    return f"{sign if sign.endswith('자리') else sign + '자리'} {deg}도"


def main(argv=None) -> int:
    import birth as B

    for s in (sys.stdout, sys.stderr):      # 한글 윈도의 cp949 콘솔·파이프에서 못 쓰는 글자(—)는 ?로 — 죽지 않는다
        if hasattr(s, "reconfigure"):
            s.reconfigure(errors="replace")
    argv = sys.argv[1:] if argv is None else argv
    path = argv[0] if argv else DEFAULT_PATH
    try:
        cfg = load(path)
    except ConfigError as e:
        print(f"[me.yaml] {e}", file=sys.stderr)
        return 1
    print(f"me.yaml 확인 — 사람 {len(cfg.people)}명 · 모델 {cfg.model} (계산만 하고 Claude는 부르지 않는다)")
    for p in cfg.people:
        b, ch = p.birth, p.chart
        print(f"[{p.name}] {b.solar} {b.place} · {b.sex} · 관례 {b.convention} · 받을 곳 {p.chat_where}")
        natal = " · ".join(B._kor(ch.NATAL[k]) for k in ("year", "month", "day", "hour"))
        print(f"  사주 원국: {natal} (일간 {interpret.day_master_kor(ch.DAY_MASTER)})")
        cands = B.pillar_candidates(b)
        print("  관례별 일주·시주: "
              + " · ".join(f"{k} {B._kor(v[0])}/{B._kor(v[1])}" for k, v in cands.items()))
        print("  " + _daewoon_line(B, ch.DAEWOON_INFO, B._kst_year()))
        print("  별자리 세 축: " + " · ".join(f"{label} {_axis(ch.NATAL_ASTRO[k])}"
                                         for label, k in (("태양", "sun"), ("달", "moon"), ("상승점", "asc"))))
        for w in ch.WARNINGS:
            print(f"  [{p.name}] 확인 필요: {w}")
        if not ch.WARNINGS:
            print("  확인 필요: 없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
