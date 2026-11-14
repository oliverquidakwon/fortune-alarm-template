# -*- coding: utf-8 -*-
"""
출생정보 → 명식 좌표. 사람을 늘릴 때 손으로 계산하지 않기 위한 공통 코어.

받는 것은 사람이 아는 형태(양력 생년월일시 + 지역 + 성별)뿐이고, 나머지는 전부 계산한다.
  - 한국 표준시 이력 보정 (1908~11·1954~61 UTC+8:30, 1948~51·1955~60·1987·88 서머타임) — 이걸 빼면 조용히 틀린다
  - 진태양시 (경도 + 균시차)
  - 사주 4주 + 자시 경계 후보 3종
  - 대운 (방향·대운수·연도 매핑)
  - 출생 천궁도 천체 10개(해·달·수성·금성·화성·목성·토성·천왕성·해왕성·명왕성) + 상승점·중천점
  - 십성·오행 분포·프롬프트용 명식 요약

CLI (사람을 me.yaml에 넣기 전 후보 확인용):
  python birth.py --solar "1988-07-09 23:40" --place 부산 --sex 남    # 예시 인물 바다(지어낸 사람)
"""
import argparse
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import ephem

import astro_core as A
import saju_core as sc

# ── 한국 표준시 이력 ─────────────────────────────────────────
# 사람이 말하는 시각은 그때의 '벽시계'다. 표준자오선과 서머타임이 바뀐 구간을
# 반영하지 않으면 사주 시주와 천궁도가 함께 틀어진다.
#   1908-04-01 ~ 1911-12-31 : UTC+8:30 (동경 127.5도 기준)
#   1948 ~ 1951 여름         : 서머타임 (UTC+10)
#   1954-03-21 ~ 1961-08-09 : UTC+8:30 (동경 127.5도 기준)
#   1955 ~ 1960 여름         : 서머타임 (UTC+8:30 위에 1시간 = UTC+9:30)
#   1987-05-10 ~ 1987-10-11 : 서머타임 (UTC+10)
#   1988-05-08 ~ 1988-10-09 : 서머타임 (UTC+10)
#   그 외                    : UTC+9 (1908-04-01 전은 지방평균시인데 이 표는 다루지 않는다 — warnings_for가 알린다)
#
# 출처가 서로 다른 곳:
#   - 서머타임 연도는 공공 기록끼리도 다르다 — 정책브리핑 1948~1951·1955~1960, 국가기록원
#     오늘의 기록 1948~1960, 국가기록원 해설 1949~1961, 한국민족문화대백과 1949~1960(1961-05-01
#     폐지). 정책브리핑과 tz database(asia 파일 Rule ROK)가 같은 연도를 따른다.
#   - 공공 기록 사본에는 시작·종료 날짜가 없어 날짜는 tz database 규칙을 풀었다. 1955~1960
#     종료일은 tz database 주석이 국가기록원 전자책의 공고를 근거로 든 날짜와 같다(1955·1956
#     공고는 시각 없이 날짜만, 1957~1960 공고는 24시).
#   - 1954 전환 시각은 국가기록원의 두 쪽이 0시(오늘의 기록)와 0시 30분(이달의 기록이 옮긴
#     관보 공고)으로 다르다. 0시를 쓴다 — 어느 쪽이든 갈리는 것은 두 번 지나간 벽시계 30분뿐이다.
# 서머타임은 시작일 0:00(표준시)에 시작해 종료일 24:00(서머타임)에 끝난다. 표의 끝은 종료일
# 다음날 0:00이고, 종료일 밤에 두 번 지나가는 23시대는 서머타임으로 읽는다(1987·88과 같은 관례).
# 첫 일치가 이긴다 — 1955~1960 서머타임 줄이 1954~1961 줄보다 먼저 와야 한다.
_TZ_SPANS = [
    (datetime(1908, 4, 1, 0, 0), datetime(1912, 1, 1, 0, 0), 8.5, "1908–1911 UTC+8:30 (표준자오선 127.5도)"),
    (datetime(1948, 6, 1, 0, 0), datetime(1948, 9, 13, 0, 0), 10.0, "1948 서머타임"),
    (datetime(1949, 4, 3, 0, 0), datetime(1949, 9, 11, 0, 0), 10.0, "1949 서머타임"),
    (datetime(1950, 4, 1, 0, 0), datetime(1950, 9, 10, 0, 0), 10.0, "1950 서머타임"),
    (datetime(1951, 5, 6, 0, 0), datetime(1951, 9, 9, 0, 0), 10.0, "1951 서머타임"),
    (datetime(1955, 5, 5, 0, 0), datetime(1955, 9, 9, 0, 0), 9.5, "1955 서머타임"),
    (datetime(1956, 5, 20, 0, 0), datetime(1956, 9, 30, 0, 0), 9.5, "1956 서머타임"),
    (datetime(1957, 5, 5, 0, 0), datetime(1957, 9, 22, 0, 0), 9.5, "1957 서머타임"),
    (datetime(1958, 5, 4, 0, 0), datetime(1958, 9, 21, 0, 0), 9.5, "1958 서머타임"),
    (datetime(1959, 5, 3, 0, 0), datetime(1959, 9, 20, 0, 0), 9.5, "1959 서머타임"),
    (datetime(1960, 5, 1, 0, 0), datetime(1960, 9, 18, 0, 0), 9.5, "1960 서머타임"),
    (datetime(1954, 3, 21, 0, 0), datetime(1961, 8, 10, 0, 0), 8.5, "UTC+8:30 (표준자오선 127.5도)"),
    (datetime(1987, 5, 10, 2, 0), datetime(1987, 10, 11, 3, 0), 10.0, "1987 서머타임"),
    (datetime(1988, 5, 8, 2, 0), datetime(1988, 10, 9, 3, 0), 10.0, "1988 서머타임"),
]


def utc_offset(wall: datetime):
    """벽시계 시각 → (UTC 오프셋 시간, 사유). 표에서 처음 맞는 줄, 없으면 +9."""
    for lo, hi, off, why in _TZ_SPANS:
        if lo <= wall < hi:
            return off, why
    return 9.0, ""


# ── 지역 좌표 (시·군 단위면 충분 — 상승점 오차 1도 미만) ──────
PLACES = {
    "서울": (37.566, 126.978), "인천": (37.456, 126.705), "수원": (37.264, 127.029),
    "춘천": (37.881, 127.730), "강릉": (37.752, 128.876), "청주": (36.642, 127.489),
    "대전": (36.350, 127.385), "세종": (36.480, 127.289), "천안": (36.815, 127.114),
    "전주": (35.824, 127.148), "광주": (35.160, 126.851), "목포": (34.812, 126.392),
    "여수": (34.760, 127.662), "순천": (34.951, 127.487), "대구": (35.872, 128.601),
    "포항": (36.019, 129.343), "안동": (36.568, 128.730), "울산": (35.538, 129.311),
    "부산": (35.180, 129.076), "창원": (35.228, 128.682), "마산": (35.200, 128.570),
    "진주": (35.180, 128.108), "제주": (33.499, 126.531),
}

_ELEM_KOR = {"木": "목", "火": "화", "土": "토", "金": "금", "水": "수"}
_ELEM_EASY = {"木": "나무", "火": "불", "土": "흙", "金": "쇠", "水": "물"}
_GAN_YY = {"甲": "陽", "乙": "陰", "丙": "陽", "丁": "陰", "戊": "陽",
           "己": "陰", "庚": "陽", "辛": "陰", "壬": "陽", "癸": "陰"}
_HANJA2KOR = {
    "甲": "갑", "乙": "을", "丙": "병", "丁": "정", "戊": "무",
    "己": "기", "庚": "경", "辛": "신", "壬": "임", "癸": "계",
    "子": "자", "丑": "축", "寅": "인", "卯": "묘", "辰": "진", "巳": "사",
    "午": "오", "未": "미", "申": "신", "酉": "유", "戌": "술", "亥": "해",
}

# 십성 → 일상어 (프롬프트·요약에서 전문용어를 흘리지 않기 위해)
_SIPSUNG_EASY = {
    "정관": "자리·책임", "편관": "압박·자리", "정재": "꾸준한 돈", "편재": "큰 돈·기회",
    "정인": "배움·정리", "편인": "배움·쉼", "식신": "표현·생산", "상관": "말·표현",
    "비견": "내 힘", "겁재": "경쟁·지출",
}

# 절기 12개 (황경, 달력월 힌트) — 월주 경계
_TERMS = [(285, 1), (315, 2), (345, 3), (15, 4), (45, 5), (75, 6),
          (105, 7), (135, 8), (165, 9), (195, 10), (225, 11), (255, 12)]


def _kor(gj: str) -> str:
    return "".join(_HANJA2KOR.get(c, c) for c in gj)


def _term_moments(year: int) -> list:
    """그 해 12절입 시각 (오름차순)."""
    return sorted(sc.solar_term_moment(year, lon, m) for lon, m in _TERMS)


def _adjacent_terms(when: datetime):
    """출생 직전·직후 절입 시각."""
    all_t = _term_moments(when.year - 1) + _term_moments(when.year) + _term_moments(when.year + 1)
    prev = max(t for t in all_t if t <= when)
    nxt = min(t for t in all_t if t > when)
    return prev, nxt


def hour_ganji(day_gan: str, branch: str) -> str:
    """오자둔(五鼠遁) — 일간이 정하는 자시 천간에서 지지만큼 순행.
    甲己→甲子 · 乙庚→丙子 · 丙辛→戊子 · 丁壬→庚子 · 戊癸→壬子."""
    zi = (sc.GAN.index(day_gan) % 5) * 2
    return sc.GAN[(zi + sc.BRANCH.index(branch)) % 10] + branch


def hour_branch(hour: int, minute: int) -> str:
    """시각 → 시지. 23:00~00:59 자, 01:00~02:59 축 … (2시간 단위)."""
    return sc.BRANCH[(((hour + 1) % 24) // 2)]


@dataclass
class BirthData:
    """사람이 아는 형태 그대로. 여기 없는 값은 전부 계산으로 만든다."""
    key: str                 # 코드 키 (상태 파일 이름에 쓰임)
    name: str                # 표시 이름
    solar: str               # "YYYY-MM-DD HH:MM" 양력 벽시계 (음력이면 미리 변환해 올 것)
    place: str               # 지역명 (PLACES) 또는 임의 문자열 + lat/lon 지정
    sex: str                 # "남" | "여" — 대운 방향
    convention: str = "A"    # 자시 경계 관례 A(진태양시)·B(자시 익일)·C(야자시)
    lat: float | None = None
    lon: float | None = None
    source: str = ""         # 시각 출처·본인 확인 등 근거 메모
    honorific: str = ""      # 발송문에서 부를 호칭(예: 하늘님). ""이면 부르지 않는다
    notes: list = field(default_factory=list)

    @property
    def when(self) -> datetime:
        return datetime.strptime(self.solar, "%Y-%m-%d %H:%M")

    @property
    def coords(self):
        if self.lat is not None and self.lon is not None:
            return self.lat, self.lon
        if self.place in PLACES:
            return PLACES[self.place]
        raise ValueError(f"지역 '{self.place}' 좌표를 모른다. lat/lon을 직접 지정할 것.")


# ── 계산 ─────────────────────────────────────────────────────

def equation_of_time_min(when_utc: datetime) -> float:
    """균시차(분) — 진태양시 − 평균태양시.

    부호 약속: 이 함수는 '진태양시 − 평균태양시'(11월 초 약 +16분, 2월 중순 약 −14분)를 돌려주고 true_solar_time이 더한다 — 표준국어대사전의 균시차(평균 태양시 − 진태양시)와 부호가 반대다.
    """
    e = ephem.Date(when_utc)
    s = ephem.Sun()
    s.compute(e)
    T = (float(e) + 2415020.0 - 2451545.0) / 36525.0
    L0 = (280.46646 + 36000.76983 * T + 0.0003032 * T * T) % 360
    ra = math.degrees(float(s.g_ra)) % 360
    return (((L0 - ra + 180) % 360) - 180) * 4.0


def true_solar_time(b: BirthData):
    """(진태양시 datetime, 경도보정 분, 균시차 분). 사주 시주 판정용."""
    _lat, lon = b.coords
    off, _ = utc_offset(b.when)
    meridian = off * 15.0                      # 그 시절 시계가 따른 자오선(서머타임이면 표준자오선보다 15도 동쪽)
    lon_corr = (lon - meridian) * 4.0
    eot = equation_of_time_min(b.when - timedelta(hours=off))
    return b.when + timedelta(minutes=lon_corr + eot), lon_corr, eot


def pillar_candidates(b: BirthData) -> dict:
    """일주·시주 후보 3종. 연·월주는 후보 무관.

    A: 진태양시로 시지를 정하고 일주는 당일 유지
    B: 벽시계 기준. 밤 자시(23시대)면 일주를 다음날로 넘긴다
    C: 벽시계 기준. 야자시를 인정해 일주는 당일 유지

    일주가 갈리는 것은 벽시계 23:00~23:59뿐이다. 00:00~00:59는 달력 날짜가 이미
    넘어가 있어 어느 관례든 같고, 그 밖의 시각은 자시가 아니라 애초에 논쟁이 없다.
    (그 경우 세 후보의 일주는 같고, 시지만 진태양시 여부로 갈릴 수 있다.)
    """
    w = b.when
    d = w.date()
    tst, _, _ = true_solar_time(b)
    same = sc.day_ganji(d)
    late_zi = w.hour == 23                      # 밤 자시 — 여기서만 일주가 갈린다
    day_b = sc.day_ganji(d + timedelta(days=1)) if late_zi else same
    tsb = hour_branch(tst.hour, tst.minute)     # 진태양시 기준 시지
    wcb = hour_branch(w.hour, w.minute)         # 벽시계 기준 시지
    return {
        "A": (same, hour_ganji(same[0], tsb), f"진태양시 {tst:%H:%M} 기준"),
        "B": (day_b, hour_ganji(day_b[0], wcb),
              "자시부터 다음날로 넘기는 관례" if late_zi else "벽시계 기준"),
        "C": (same, hour_ganji(same[0], wcb),
              "야자시 — 당일 일주 유지" if late_zi else "벽시계 기준"),
    }


def daewoon(b: BirthData, year_gan: str, month_gj: str) -> dict:
    """대운 방향·대운수·연도 매핑. 양남음녀 순행 / 음남양녀 역행."""
    yang_year = _GAN_YY[year_gan] == "陽"
    forward = (yang_year and b.sex == "남") or (not yang_year and b.sex == "여")
    prev_t, next_t = _adjacent_terms(b.when)
    delta = ((next_t - b.when) if forward else (b.when - prev_t)).total_seconds() / 86400
    su_raw = delta / 3
    su = round(su_raw)
    step = 1 if forward else -1

    # 대운은 생일에 바뀌는데 표는 연 단위다. 전환 연도를 어느 쪽에 붙일지가 문제인데,
    # 그 해의 '더 긴 쪽'을 택한다 — 상반기 출생이면 전환 연도의 대부분이 새 대운이고,
    # 하반기 출생이면 대부분이 직전 대운이라 한 해 미룬다. 그래도 전환 연도 안에서
    # 생일 전후는 어긋나므로, 경계 연도는 항상 ±1년으로 본다.
    shift = 0 if (b.when.month, b.when.day) <= (7, 1) else 1

    g, br = sc.GAN.index(month_gj[0]), sc.BRANCH.index(month_gj[1])
    ranges = []
    # 10개(약 100년) — 6개만 만들면 60대 후반부터 '현재 대운 없음'이 되어
    # 프롬프트에서 대운 줄이 통째로 빠진다.
    for k in range(10):
        g = (g + step) % 10
        br = (br + step) % 12
        start = b.when.year + su + shift + 10 * k
        ranges.append((start, start + 9, sc.GAN[g] + sc.BRANCH[br]))
    return {"forward": forward, "su": su, "su_raw": su_raw, "ranges": ranges,
            "year_shift": shift,
            # 대운수 원값이 x.5 근처면 반올림·버림 유파차로 전환기가 1년 흔들린다
            "boundary": abs(su_raw - int(su_raw) - 0.5) < 0.17}


def daewoon_head(dw: dict) -> str:
    """'대운 역행 · 대운수 3세 (원값 2.91)' — 미리보기(main)와 점검 출력(me_config)이 같은 글자를 쓴다."""
    return f"대운 {'순행' if dw['forward'] else '역행'} · 대운수 {dw['su']}세 (원값 {dw['su_raw']:.2f})"


def daewoon_now(ranges: list, year: int):
    """대운표에서 그 해가 든 대운 → (간지, 시작 해, 끝 해, 그 몇 년째) 또는 None(대운표 밖).
    해석 데이터(interpret.daewoon_year_line)·점검 출력(me_config)·미리보기(main)가 같은 셈을 쓴다."""
    for start, end, gj in ranges:
        if start <= year <= end:
            return gj, start, end, year - start + 1
    return None


def _obliquity(e) -> float:
    T = (float(ephem.Date(e)) + 2415020.0 - 2451545.0) / 36525.0
    return math.radians(23.439291 - 0.0130042 * T - 1.64e-7 * T * T + 5.04e-7 * T ** 3)


def _asc_mc(e, lat: float, lon: float):
    obs = ephem.Observer()
    obs.lat, obs.lon, obs.date = math.radians(lat), math.radians(lon), e
    ramc, eps, phi = float(obs.sidereal_time()), _obliquity(e), math.radians(lat)
    mc = math.atan2(math.sin(ramc), math.cos(ramc) * math.cos(eps))
    asc = math.atan2(math.cos(ramc),
                     -(math.sin(ramc) * math.cos(eps) + math.tan(phi) * math.sin(eps)))
    return math.degrees(asc) % 360, math.degrees(mc) % 360


_BODIES = [("sun", ephem.Sun), ("moon", ephem.Moon), ("mercury", ephem.Mercury),
           ("venus", ephem.Venus), ("mars", ephem.Mars), ("jupiter", ephem.Jupiter),
           ("saturn", ephem.Saturn), ("uranus", ephem.Uranus),
           ("neptune", ephem.Neptune), ("pluto", ephem.Pluto)]


def natal_astro(b: BirthData):
    """(NATAL_ASTRO 문자열 dict, 정밀 황경 dict, 역행 dict).
    서양 점성은 벽시계 시각 기준 — 사주의 진태양시 보정을 적용하지 않는다."""
    lat, lon = b.coords
    off, _ = utc_offset(b.when)
    e = ephem.Date(b.when - timedelta(hours=off))
    precise, retro = {}, {}
    for name, body in _BODIES:
        l1 = A._ecl_lon(body, e)
        l2 = A._ecl_lon(body, ephem.Date(float(e) + 1.0))
        precise[name] = l1
        retro[name] = (((l2 - l1 + 180) % 360) - 180) < 0
    precise["asc"], precise["mc"] = _asc_mc(e, lat, lon)
    out = {}
    for k, v in precise.items():
        s, d = A.lon_to_sign(v)
        out[k] = f"{s} {d:.0f}°"
    out["asc_ruler"] = _SIGN_RULER[A.lon_to_sign(precise["asc"])[0]]
    return out, precise, retro


_SIGN_RULER = {"양자리": "화성", "황소": "금성", "쌍둥이": "수성", "게": "달", "사자": "태양",
               "처녀": "수성", "천칭": "금성", "전갈": "명왕성", "사수": "목성",
               "염소": "토성", "물병": "천왕성", "물고기": "해왕성"}


def elements(natal: dict) -> dict:
    """오행 분포 (천간 + 지지 본기)."""
    c = {k: 0 for k in "木火土金水"}
    for gj in natal.values():
        c[sc.GAN_ELEM[gj[0]]] += 1
        c[sc.GAN_ELEM[sc.BRANCH_BONGI[gj[1]]]] += 1
    return c


def _kst_year() -> int:
    """지금 연도(KST). 새해 첫 아침 발송이 UTC 기준 전년도로 계산되지 않게 KST로 잰다."""
    return datetime.now(timezone(timedelta(hours=9))).year


def natal_brief(natal: dict, dm: str, astro: dict, ranges: list, year: int | None = None) -> str:
    """프롬프트 주입용 명식 요약. 한자·전문용어 없이, 아는 것과 모르는 것을 함께 적는다.
    year: '현재 10년 대운'을 고를 연도. 안 주면 실행 연도(KST) — 연도를 고정하면 대운이 바뀌는 해부터 틀린다."""
    year = _kst_year() if year is None else year
    label = {"year": "연주", "month": "월주", "day": "일주", "hour": "시주"}
    lines = ["[타고난 사주 — 원국]"]
    for key in ("year", "month", "day", "hour"):
        gj = natal[key]
        g = "본인" if key == "day" else _SIPSUNG_EASY[sc.sipsung(dm, gj[0])]
        bch = _SIPSUNG_EASY[sc.branch_sipsung(dm, gj[1])]
        tail = f"   <- 일간 {_kor(dm)}{_ELEM_KOR[sc.GAN_ELEM[dm]]}" if key == "day" else ""
        lines.append(f"- {label[key]}: {_kor(gj)} ({g} / {bch}){tail}")

    el = elements(natal)
    lines.append("- 오행 분포: " + " · ".join(f"{_ELEM_EASY[k]} {el[k]}" for k in "木火土金水"))
    absent = [_ELEM_EASY[k] for k in "木火土金水" if el[k] == 0]
    if absent:
        lines.append(f"- 원국에 없는 기운: {', '.join(absent)} — 밖에서 들어올 때 체감이 크다")
    lines.append("- 용신·희신은 확정하지 않았다. 오행을 '보충하라/피하라'는 처방을 쓰지 마라.")

    cur = next((g for s, e, g in ranges if s <= year <= e), None)
    if cur:
        lines.append(f"- 현재 10년 대운: {_kor(cur)} "
                     f"({_SIPSUNG_EASY[sc.sipsung(dm, cur[0])]} / "
                     f"{_SIPSUNG_EASY[sc.branch_sipsung(dm, cur[1])]})")

    lines += ["", "[타고난 별자리 — 출생천궁도]",
              f"- 상승 {astro['asc']} (룰러 {astro['asc_ruler']}) · 달 {astro['moon']} · 태양 {astro['sun']}",
              "- 하우스(1~12) 번호는 산출하지 않았다. 하우스를 언급하지 마라.",
              "", "[아는 것은 여기까지다]",
              "직업·회사·가족·재무 상황·과거 이력은 주어지지 않았다. 지어내지 마라."]
    return "\n".join(lines)


# 이 시각 전은 지방평균시 시절이라 기간표로 보정하지 않는다 — 막지 않고 경고로 알린다.
TZ_TABLE_FROM = datetime(1908, 4, 1, 0, 0)


def warnings_for(b: BirthData) -> list:
    """확인이 필요한 지점 — 조용히 틀리는 자리를 미리 드러낸다."""
    w = []
    off, why = utc_offset(b.when)
    if why:
        w.append(f"표준시 보정 적용: {why} (UTC+{off}) — 벽시계 그대로 쓰면 틀린다")
    elif b.when < TZ_TABLE_FROM:
        w.append("1908년 4월 이전 출생은 표준시 기준이 달라 시각 보정을 하지 않는다 — 시주가 어긋날 수 있다")

    prev_t, next_t = _adjacent_terms(b.when)
    near = min((b.when - prev_t).total_seconds(), (next_t - b.when).total_seconds()) / 3600
    if near < 24:
        w.append(f"절입 경계에서 {near:.1f}시간 — 월주(입춘 부근이면 연주까지) 확인 필요")

    tst, _, _ = true_solar_time(b)
    cands = pillar_candidates(b)
    if len({c[0] for c in cands.values()}) > 1:
        w.append(f"자시 경계에 걸림 (벽시계 {b.when:%H:%M} / 진태양시 {tst:%H:%M}) — "
                 "관례에 따라 일주·일간이 갈린다. 본인 확인 필수")
    elif len({c[1] for c in cands.values()}) > 1:
        # 일주는 같지만 진태양시가 두 시간 칸을 넘어 시주만 갈리는 경우
        w.append(f"시주 경계에 걸림 (벽시계 {b.when:%H:%M} / 진태양시 {tst:%H:%M}) — "
                 "일간은 같고 시주만 갈린다")

    if b.when.minute % 30 == 0 and b.when.hour % 2 == 1:
        w.append("시각이 정각·반각이라 반올림된 기록일 수 있다 — 시주 경계면 확인")
    return w


# ── CLI — 수신자 추가 전 후보 확인용 ─────────────────────────

def main() -> int:
    import sys
    for s in (sys.stdout, sys.stderr):      # 한글 윈도의 cp949 콘솔·파이프에서 못 쓰는 글자(—)는 ?로 — 죽지 않는다
        if hasattr(s, "reconfigure"):
            s.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description="출생정보 → 명식 후보 미리보기")
    ap.add_argument("--solar", required=True, help='"YYYY-MM-DD HH:MM" 양력 벽시계')
    ap.add_argument("--place", required=True, help="지역명 (또는 --lat/--lon)")
    ap.add_argument("--sex", required=True, choices=["남", "여"])
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    a = ap.parse_args()

    b = BirthData(key="preview", name="preview", solar=a.solar, place=a.place,
                  sex=a.sex, lat=a.lat, lon=a.lon)
    lat, lon = b.coords
    off, why = utc_offset(b.when)
    tst, lonc, eot = true_solar_time(b)

    print(f"출생  {b.when:%Y-%m-%d %H:%M} 벽시계 / {b.place} ({lat}N {lon}E) / {b.sex}")
    print(f"표준시 UTC+{off}{' — ' + why if why else ''}")
    print(f"진태양시 {tst:%H:%M}  (경도 {lonc:+.1f}분, 균시차 {eot:+.1f}분)\n")

    yg = sc.year_ganji(b.when.date(), hour_kst=b.when.hour)
    mg = sc.month_ganji(b.when.date(), hour_kst=b.when.hour)
    print(f"연주 {yg} / 월주 {mg}  (후보 무관)\n")
    print("자시 경계 후보:")
    for k, (dp, hp, note) in pillar_candidates(b).items():
        print(f"  {k}: 일주 {dp} 시주 {hp}  일간 {dp[0]}({_kor(dp[0])}"
              f"{_ELEM_KOR[sc.GAN_ELEM[dp[0]]]})  — {note}")

    print()
    dw0 = daewoon(b, yg[0], mg)
    this_year = _kst_year()
    now = daewoon_now(dw0["ranges"], this_year)
    cur = now[0] if now else None
    for k, (dp, _hp, _n) in pillar_candidates(b).items():
        if cur:
            print(f"  {k} 기준 {this_year} 대운 {cur} "
                  f"({sc.sipsung(dp[0], cur[0])}/{sc.branch_sipsung(dp[0], cur[1])})")
        else:
            print(f"  {k} 기준 {this_year} 대운: 범위 밖 (대운표 {dw0['ranges'][0][0]}"
                  f"~{dw0['ranges'][-1][1]})")

    dw = daewoon(b, yg[0], mg)
    print(f"\n{daewoon_head(dw)}" + ("  <- 반올림/버림 경계" if dw["boundary"] else ""))

    warns = warnings_for(b)
    if warns:
        print("\n확인 필요:")
        for w in warns:
            print(f"  · {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
