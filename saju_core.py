# -*- coding: utf-8 -*-
"""
사주 계산 코어 — 결정론적. 환각 없음.

제공:
  - day_ganji(date)      : 일진 (JDN 기반 60갑자)
  - year_ganji(date, hour_kst)  : 연주 (입춘 '시각' 경계)
  - month_ganji(date, hour_kst) : 월주 (절기 '시각' + 오호둔)
  - solar_term_moment(...)      : 절입 시각 (ephem apparent of-date 황경, 분 단위)
  - sipsung(dm, gan)     : 천간 십성
  - branch_sipsung(dm, branch) : 지지(본기) 십성
  - ganji_interactions(ganji)  : 임의 간지 ↔ 원국 6충·6합·천간5합 (일진·대운·세운·월운 공용)
  - four_layers(date)    : 대운/년/월/일 4층 + 십성 + 충합(일진+배경) + 절기 전환

절기는 하드코딩 테이블이 아니라 태양 겉보기 황경(apparent, 진분점 of-date)을
ephem으로 직접 계산한다 — 고정 테이블은 한 칸만 틀려도 조용히 틀리고(예: 망종을 6/5로 적은 표, 실제
6/6 00:48 KST), J2000 분점을 쓰면 약 +9시간 어긋난다.
외부 앵커(전문 만세력, NASA DE441·천문연 기준 — 이 계산과 0~1분 정합):
2026 입춘 2/4 05:02 · 망종 6/6 00:48 · 소서 7/7 10:56.
(일반 포털 요약에 보이는 "입춘 04:00"·"소서 11:12"는 이 계산·앵커와 다르다.)
기준 시각 REF_HOUR=07시 — 아침 발송이 말하는 "오늘"의 연주·월주 판정 시각.

명식(chart)은 부르는 쪽이 넘긴다(chart_factory.build가 me.yaml의 출생정보로 만든다).
이 모듈은 누구의 명식도 기본값으로 갖지 않는다.

검증: 2026-06-21 → 일진 丙寅, 연주 丙午, 월주 甲午 (tests 참조)
"""
import math
from datetime import date, datetime, timedelta
from functools import lru_cache

import ephem

REF_HOUR = 7   # 연·월주 판정 기준 시각 (KST, 아침 발송 시점)

GAN = "甲乙丙丁戊己庚辛壬癸"
BRANCH = "子丑寅卯辰巳午未申酉戌亥"

# 천간 오행/음양
GAN_ELEM = {"甲":"木","乙":"木","丙":"火","丁":"火","戊":"土",
            "己":"土","庚":"金","辛":"金","壬":"水","癸":"水"}
GAN_YY = {"甲":"陽","乙":"陰","丙":"陽","丁":"陰","戊":"陽",
          "己":"陰","庚":"陽","辛":"陰","壬":"陽","癸":"陰"}

# 지지 지장간 본기(정기) — 십성 판정용
BRANCH_BONGI = {"子":"癸","丑":"己","寅":"甲","卯":"乙","辰":"戊","巳":"丙",
                "午":"丁","未":"己","申":"庚","酉":"辛","戌":"戊","亥":"壬"}

SHENG = {"木":"火","火":"土","土":"金","金":"水","水":"木"}  # 생
KE = {"木":"土","土":"水","水":"火","火":"金","金":"木"}      # 극


def sipsung(dm: str, target: str) -> str:
    """일간(dm) 기준 target 천간의 십성."""
    de, dy = GAN_ELEM[dm], GAN_YY[dm]
    te, ty = GAN_ELEM[target], GAN_YY[target]
    same = (dy == ty)
    if te == de:
        return "비견" if same else "겁재"
    if SHENG[de] == te:      # 내가 생 → 식상
        return "식신" if same else "상관"
    if KE[de] == te:         # 내가 극 → 재성
        return "편재" if same else "정재"
    if KE[te] == de:         # 나를 극 → 관성
        return "편관" if same else "정관"
    if SHENG[te] == de:      # 나를 생 → 인성
        return "편인" if same else "정인"
    raise ValueError(f"십성 판정 실패: {dm},{target}")


def branch_sipsung(dm: str, branch: str) -> str:
    """지지를 본기 천간으로 환산해 십성."""
    return sipsung(dm, BRANCH_BONGI[branch])


def _jdn(d: date) -> int:
    a = (14 - d.month) // 12
    y = d.year + 4800 - a
    m = d.month + 12 * a - 3
    return (d.day + (153 * m + 2) // 5 + 365 * y + y // 4
            - y // 100 + y // 400 - 32045)


def day_ganji(d: date) -> str:
    """일진. (JDN+49) mod 60 → 갑자=0 기준."""
    idx = (_jdn(d) + 49) % 60
    return GAN[idx % 10] + BRANCH[idx % 12]


# ── 절기 (ephem — 태양 apparent of-date 황경) ─────────────────
# 절기 정의 = 태양 겉보기 황경이 15° 배수를 지나는 순간. 12절만 월주에 쓴다.
# 寅월 시작 = 입춘(315°), 이후 30°마다 다음 달.

def _sun_apparent_lon(dt_kst: datetime) -> float:
    """KST naive datetime → 태양 겉보기 황경(도, 진분점 of-date).
    g_ra/g_dec(geocentric apparent) → 같은 epoch 황도 변환. J2000 분점을 쓰면
    세차만큼(2026년 약 0.36° = 절기 약 9시간) 어긋난다."""
    when = ephem.Date(dt_kst - timedelta(hours=9))
    s = ephem.Sun()
    s.compute(when)
    eq = ephem.Equatorial(s.g_ra, s.g_dec, epoch=when)
    return math.degrees(float(ephem.Ecliptic(eq).lon)) % 360


@lru_cache(maxsize=256)
def solar_term_moment(year: int, target_lon: int, month_hint: int) -> datetime:
    """그 해 태양 황경 target_lon(도) 통과 시각 (KST naive, 이분법 ±분 단위).
    month_hint: 그 절기가 드는 양력 월 (탐색 창 중심)."""
    lo = datetime(year, month_hint, 1) - timedelta(days=12)
    hi = lo + timedelta(days=42)

    def diff(dt):
        return ((_sun_apparent_lon(dt) - target_lon) + 180) % 360 - 180

    if not (diff(lo) < 0 <= diff(hi)):
        raise ValueError(f"절기 탐색 창 오류: {year}년 황경 {target_lon}° (hint {month_hint}월)")
    for _ in range(32):
        mid = lo + (hi - lo) / 2
        if diff(mid) < 0:
            lo = mid
        else:
            hi = mid
    return lo + (hi - lo) / 2


def _ipchun_moment(year: int) -> datetime:
    return solar_term_moment(year, 315, 2)


def year_ganji(d: date, hour_kst: int = REF_HOUR) -> str:
    """연주. 입춘 '시각' 경계 (예: 2026 입춘 2/4 05:02 — 그 전은 乙巳). base 1984=甲子."""
    y = d.year
    if datetime(d.year, d.month, d.day, hour_kst) < _ipchun_moment(y):
        y -= 1
    off = (y - 1984) % 60
    return GAN[off % 10] + BRANCH[off % 12]


# 오호둔: 연간 그룹 → 인월 천간
WUHU = {"甲":"丙","己":"丙","乙":"戊","庚":"戊","丙":"庚",
        "辛":"庚","丁":"壬","壬":"壬","戊":"甲","癸":"甲"}


def month_branch(d: date, hour_kst: int = REF_HOUR) -> str:
    """절기월 지지 — 그 시각 태양 황경에서 직접 (寅=315°부터 30°씩)."""
    lon = _sun_apparent_lon(datetime(d.year, d.month, d.day, hour_kst))
    idx = int(((lon - 315) % 360) // 30)
    return BRANCH[(BRANCH.index("寅") + idx) % 12]


def month_ganji(d: date, hour_kst: int = REF_HOUR) -> str:
    """월주. 연간(입춘 시각 경계) → 오호둔 인월천간 → 월지까지 순행."""
    yg = year_ganji(d, hour_kst)
    in_gan = WUHU[yg[0]]                    # 인월 천간
    mb = month_branch(d, hour_kst)
    steps = (BRANCH.index(mb) - BRANCH.index("寅")) % 12
    gan = GAN[(GAN.index(in_gan) + steps) % 10]
    return gan + mb


def _term_change_today(d: date):
    """그날(00:00~23:59 KST) 중 월지가 바뀌면 (전환시각 "HH:MM", 새 월주). 아니면 None."""
    b0 = month_branch(d, 0)
    lon_end = _sun_apparent_lon(datetime(d.year, d.month, d.day, 23, 59))
    idx_end = int(((lon_end - 315) % 360) // 30)
    b1 = BRANCH[(BRANCH.index("寅") + idx_end) % 12]
    if b0 == b1:
        return None
    target = (315 + idx_end * 30) % 360
    at = solar_term_moment(d.year, target, d.month)
    return at.strftime("%H:%M"), month_ganji(d, 23)


# ── 일진 ↔ 원국 특수 관계 (지지 6충·6합, 천간 5합) ───────────
# 형·해·파는 유파 차가 커서 제외. 동일 간지(복음)도 범위 외.
BRANCH_CHUNG = [{"子", "午"}, {"丑", "未"}, {"寅", "申"},
                {"卯", "酉"}, {"辰", "戌"}, {"巳", "亥"}]
BRANCH_YUKHAP = [{"子", "丑"}, {"寅", "亥"}, {"卯", "戌"},
                 {"辰", "酉"}, {"巳", "申"}, {"午", "未"}]
GAN_OHAP = [{"甲", "己"}, {"乙", "庚"}, {"丙", "辛"}, {"丁", "壬"}, {"戊", "癸"}]

_NATAL_PILLARS = [("년", "year"), ("월", "month"), ("일", "day"), ("시", "hour")]


def ganji_interactions(gj: str, chart) -> list:
    """간지(일진뿐 아니라 대운·세운·월운도)가 원국 4주와 맺는 충·합.
    [{kind, pair, natal_pos}] (없으면 빈 목록)."""
    g, b = gj[0], gj[1]
    out = []
    for pos, key in _NATAL_PILLARS:
        ng, nb = chart.NATAL[key][0], chart.NATAL[key][1]
        if {g, ng} in GAN_OHAP:
            out.append({"kind": "천간합", "pair": f"{g}-{ng}", "natal_pos": f"{pos}간"})
        if {b, nb} in BRANCH_CHUNG:
            out.append({"kind": "지지충", "pair": f"{b}-{nb}", "natal_pos": f"{pos}지"})
        if {b, nb} in BRANCH_YUKHAP:
            out.append({"kind": "지지합", "pair": f"{b}-{nb}", "natal_pos": f"{pos}지"})
    return out


day_interactions = ganji_interactions   # 하위호환 별칭 (기존 호출부·테스트)


def _age_se(year: int, chart) -> int:
    """세는나이 (자미 대한용)."""
    return year - chart.BIRTH_YEAR + 1


def four_layers(d: date, chart) -> dict:
    """대운/년/월/일 4층 + 십성 + 일진↔원국 충합 + 절기 전환. 해석 LLM에 넘길 구조화 데이터."""
    dm = chart.DAY_MASTER
    yg, mg, dg = year_ganji(d), month_ganji(d), day_ganji(d)

    def layer(ganji):
        g, b = ganji[0], ganji[1]
        return {"ganji": ganji, "gan_sipsung": sipsung(dm, g),
                "branch_sipsung": branch_sipsung(dm, b)}

    dw = chart.current_daewoon(d.year)
    daewoon = None
    if dw:
        dg2, _ = dw
        daewoon = layer(dg2)

    tc = _term_change_today(d)
    term_change = None
    if tc:
        at, to_ganji = tc
        term_change = {"at": at, "to_ganji": to_ganji, **{
            "to_gan_sipsung": sipsung(dm, to_ganji[0]),
            "to_branch_sipsung": branch_sipsung(dm, to_ganji[1]),
        }}

    return {
        "date": d.isoformat(),
        "day_master": dm,
        "daewoon": daewoon,      # 10년 흐름
        "year": layer(yg),       # 세운
        "month": layer(mg),      # 월운 (REF_HOUR 기준)
        "day": layer(dg),        # 일진
        "interactions": ganji_interactions(dg, chart),   # 일진 ↔ 원국 충합
        # 배경 충합 — 그 기간 내내 지속되는 관계 (예: 올해 세운 천간 ↔ 원국 일간의 천간합)
        "daewoon_interactions": ganji_interactions(daewoon["ganji"], chart) if daewoon else [],
        "year_interactions": ganji_interactions(yg, chart),
        "month_interactions": ganji_interactions(mg, chart),
        "term_change": term_change,             # 오늘 절입이면 전환 정보
        # 자미 레이어는 손으로 검증한 명반이 있을 때만 — 출생정보로 만드는 이 템플릿의 명식은
        # ZIWEI_ENABLED=False라 늘 None이다(interpret가 블록을 생략한다)
        "ziwei": {
            "ming_gung": chart.MING_GUNG,
            "yunyear_branch": _year_branch(yg),   # 유년명궁 지지
            "daehan_branch": chart.current_daehan_branch(_age_se(d.year, chart)),
        } if getattr(chart, "ZIWEI_ENABLED", True) else None,
    }


def _year_branch(year_ganji_str: str) -> str:
    return year_ganji_str[1]


def week_outlook(monday, chart) -> list:
    """월요일 기준 그 주 월~일 7일의 일진·십성 (주간 섹션용)."""
    import datetime
    dm = chart.DAY_MASTER
    names = ["월", "화", "수", "목", "금", "토", "일"]
    out = []
    for i in range(7):
        dd = monday + datetime.timedelta(days=i)
        g = day_ganji(dd)
        out.append({
            "wd": names[i], "date": dd.isoformat(), "ganji": g,
            "gan_sipsung": sipsung(dm, g[0]),
            "branch_sipsung": branch_sipsung(dm, g[1]),
        })
    return out


def month_outlook(d, chart) -> list:
    """이번 (양력)달의 절기월 십성. 양력달이 절기월 1~2개에 걸치면 세그먼트로 나눔.
    세그먼트 경계는 달력 관례(절입 '일' = 새 달 시작)를 따라 23시 기준으로 판정 —
    그날 중 절입이면 그날부터 새 기운으로 소개한다."""
    import calendar
    import datetime
    dm = chart.DAY_MASTER
    last_day = calendar.monthrange(d.year, d.month)[1]
    mg1 = month_ganji(datetime.date(d.year, d.month, 1), hour_kst=23)
    mg2 = month_ganji(datetime.date(d.year, d.month, last_day), hour_kst=23)

    def seg(mg, from_day=None):
        s = {"ganji": mg, "gan_sipsung": sipsung(dm, mg[0]),
             "branch_sipsung": branch_sipsung(dm, mg[1])}
        if from_day:
            s["from_day"] = from_day
        return s

    segs = [seg(mg1)]
    if mg2 != mg1:
        switch = next((day for day in range(2, last_day + 1)
                       if month_ganji(datetime.date(d.year, d.month, day), hour_kst=23) == mg2),
                      None)
        segs.append(seg(mg2, switch))
    return segs
