# -*- coding: utf-8 -*-
"""
서양 별자리 "오늘 레이어" — 실제 천체력(pyephem) 기반 트랜짓 계산.

사주 엔진(saju_core)이 오늘 간지를 결정론적으로 계산하듯,
여기서는 오늘 하늘의 행성 위치(트랜짓)를 계산해 그 사람의 출생천궁도(chart.NATAL_ASTRO)에
대입한 주요 각(아스펙트)을 뽑는다. 해석은 담지 않는다(interpret.py에서 Claude가 생성).
명식(chart)은 chart_factory가 출생정보로 만들고, 부르는 쪽이 반드시 넘긴다 — 기본값이 없다.

좌표계: 지심 겉보기(apparent) 황경, 진분점 of-date = 서양 점성의 회귀(tropical) 황경.
주의 — ephem.Ecliptic(body) 기본값은 J2000 분점이라 세차(2026년 약 0.36°)만큼
어긋난다(절기 시각으로 바꾸면 약 +9시간). 그래서 g_ra/g_dec + epoch=of-date
변환으로 계산한다 (_ecl_lon).
기준 시각: 낮 12시 KST (= 03:00 UT). 그날의 대표 하늘.
"""
import math
import re
from datetime import datetime, timedelta, timezone

import ephem

# ── 별자리(황경 30° 단위) ────────────────────────────────────
SIGNS = ["양자리", "황소", "쌍둥이", "게", "사자", "처녀",
         "천칭", "전갈", "사수", "염소", "물병", "물고기"]
SIGN_BASE = {name: i * 30 for i, name in enumerate(SIGNS)}

# 트랜짓 대상 (개인행성 + 느린 배경)
TRANSIT_BODIES = [
    ("태양", ephem.Sun), ("달", ephem.Moon), ("수성", ephem.Mercury),
    ("금성", ephem.Venus), ("화성", ephem.Mars),
    ("목성", ephem.Jupiter), ("토성", ephem.Saturn),
]

# natal 키 → 표시명 (asc_ruler는 좌표가 아니라 제외)
NATAL_LABELS = {
    "sun": "태양", "moon": "달", "asc": "상승점(첫인상)", "mercury": "수성",
    "venus": "금성", "mars": "화성", "jupiter": "목성", "saturn": "토성",
    "uranus": "천왕성", "neptune": "해왕성", "pluto": "명왕성", "mc": "중천점(천직)",
}

# (각도, 이름, orb) — 메이저 5각
ASPECTS = [(0, "합", 6.0), (60, "육각", 3.0), (90, "사각", 4.0),
           (120, "삼각", 4.0), (180, "대충", 6.0)]

MAX_ASPECTS = 8   # 가장 정확한 것 위주로 노이즈 컷


def lon_to_sign(lon: float):
    """절대황경 → (별자리, 별자리내 도수)."""
    lon %= 360
    i = int(lon // 30)
    return SIGNS[i], lon - i * 30


def parse_natal(s: str) -> float:
    """'물고기 24°' → 354.0,  '쌍둥이 5°' → 65.0  (예시 인물 하늘의 태양·상승점)."""
    m = re.search(r"([가-힣]+)\s*([\d.]+)", s)
    if not m or m.group(1) not in SIGN_BASE:
        raise ValueError(f"natal 좌표 파싱 실패: {s!r}")
    return SIGN_BASE[m.group(1)] + float(m.group(2))


def natal_longitudes(chart) -> dict:
    """chart.NATAL_ASTRO → {키: 절대황경}. asc_ruler 제외."""
    out = {}
    for k, v in chart.NATAL_ASTRO.items():
        if k == "asc_ruler":
            continue
        out[k] = parse_natal(v)
    return out


def _ecl_lon(body, edate) -> float:
    """겉보기 황경 (진분점 of-date). Ecliptic(b) 직접 변환은 J2000 분점이라 금지."""
    b = body()
    b.compute(edate)
    eq = ephem.Equatorial(b.g_ra, b.g_dec, epoch=edate)
    return math.degrees(float(ephem.Ecliptic(eq).lon)) % 360


def transit_longitudes(d, hour_kst: int = 12) -> dict:
    """그 날짜(KST hour_kst시)의 트랜짓 → {표시명: (황경, 역행여부)}."""
    ut = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + \
        timedelta(hours=hour_kst - 9)
    edate = ephem.Date(ut.replace(tzinfo=None))
    edate_next = ephem.Date(float(edate) + 1.0)   # +1일 → 역행 판정
    out = {}
    for label, body in TRANSIT_BODIES:
        lon = _ecl_lon(body, edate)
        lon2 = _ecl_lon(body, edate_next)
        delta = ((lon2 - lon + 180) % 360) - 180
        out[label] = (lon, delta < 0)
    return out


def angular_sep(a: float, b: float) -> float:
    d = abs((a - b) % 360)
    return min(d, 360 - d)


# ── 역행 종료일 (순행 전환일) ────────────────────────────────
# 수성 ~23일, 금성 ~42일, 화성 ~72일, 목성 ~120일, 토성 ~140일 역행 → 160일이면 전부 커버.
RETRO_SCAN_DAYS = 160


def _is_retro(body, d, hour_kst: int = 12) -> bool:
    """그 날짜(낮 hour_kst시 KST) 기준 역행 여부 — transit_longitudes와 동일 판정."""
    ut = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + \
        timedelta(hours=hour_kst - 9)
    edate = ephem.Date(ut.replace(tzinfo=None))
    lon = _ecl_lon(body, edate)
    lon2 = _ecl_lon(body, ephem.Date(float(edate) + 1.0))
    return (((lon2 - lon + 180) % 360) - 180) < 0


def retro_until(body, d, hour_kst: int = 12):
    """d에 역행 중인 행성이 순행으로 도는 첫 날짜(date). 역행 아니거나 창 초과면 None.
    발송문이 '언제까지 보류'인지 날짜를 말할 수 있게 하는 입력이다."""
    if not _is_retro(body, d, hour_kst):
        return None
    cur = d
    for _ in range(RETRO_SCAN_DAYS):
        cur = cur + timedelta(days=1)
        if not _is_retro(body, cur, hour_kst):
            return cur
    return None


def find_aspects(transits: dict, natal: dict) -> list:
    """트랜짓 × natal 주요 각. orb 작은 순 정렬."""
    res = []
    for tname, (tlon, retro) in transits.items():
        for nkey, nlon in natal.items():
            sep = angular_sep(tlon, nlon)
            for angle, aname, orb in ASPECTS:
                if abs(sep - angle) <= orb:
                    res.append({
                        "t": tname, "aspect": aname,
                        "n_key": nkey, "n": NATAL_LABELS.get(nkey, nkey),
                        "orb": round(abs(sep - angle), 1), "retro": retro,
                    })
                    break
    res.sort(key=lambda a: a["orb"])
    return res


def _aspect_keys(d, hour_kst: int, natal: dict) -> set:
    """그 날짜에 존재하는 각의 (트랜짓, 각, natal) 키 집합 — 지속성 판정용.
    MAX_ASPECTS 컷 없이 전체와 비교한다 (어제 순위 밖이었어도 하늘에 있었으면 지속)."""
    tr = transit_longitudes(d, hour_kst)
    return {(a["t"], a["aspect"], a["n_key"]) for a in find_aspects(tr, natal)}


def today_layer(d, hour_kst: int = 12, *, chart) -> dict:
    """오늘 별자리 레이어 — interpret가 소비하는 구조.
    각마다 persists(어제도 같은 각이 있었는지)를 표시한다. 토성 같은 느린 트랜짓 각이
    매일 '오늘의 신호'로 재등장해 같은 조언이 반복되는 것을 막는 입력이다."""
    tr = transit_longitudes(d, hour_kst)
    natal = natal_longitudes(chart)
    asp = find_aspects(tr, natal)[:MAX_ASPECTS]
    y_keys = _aspect_keys(d - timedelta(days=1), hour_kst, natal)
    for a in asp:
        a["persists"] = (a["t"], a["aspect"], a["n_key"]) in y_keys
    body_by_label = dict(TRANSIT_BODIES)
    retro_dates = {}
    for label, (_lon, is_r) in tr.items():
        if is_r:
            u = retro_until(body_by_label[label], d, hour_kst)
            if u:
                retro_dates[label] = u.isoformat()
    return {
        "date": d.isoformat(),
        "moon": lon_to_sign(tr["달"][0]),
        "sun": lon_to_sign(tr["태양"][0]),
        "transits": {k: (lon_to_sign(v[0]), v[1]) for k, v in tr.items()},
        "retro_until": retro_dates,   # {행성: 순행 전환일 ISO} — 역행 중인 행성만
        "aspects": asp,
    }
