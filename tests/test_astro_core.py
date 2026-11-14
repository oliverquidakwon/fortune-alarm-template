# -*- coding: utf-8 -*-
"""astro_core 회귀 테스트 — 결정론(ephem) 기반. 예시 인물 값은 계산 엔진의 실제 출력으로 고정했다."""
from datetime import date

import ephem
import pytest

import astro_core as A


# ── 황경 → 별자리 ────────────────────────────────────────────
def test_lon_to_sign_boundaries():
    assert A.lon_to_sign(0) == ("양자리", 0.0)
    assert A.lon_to_sign(210) == ("전갈", 0.0)
    s, d = A.lon_to_sign(195)
    assert s == "천칭" and abs(d - 15.0) < 1e-9


def test_lon_to_sign_wraps():
    s, d = A.lon_to_sign(360 + 45)   # 45° → 황소 15°
    assert s == "황소" and abs(d - 15.0) < 1e-9


# ── natal 파싱 ───────────────────────────────────────────────
def test_parse_natal_degrees():
    assert abs(A.parse_natal("물고기 24°") - 354.0) < 1e-6   # 하늘 태양
    assert abs(A.parse_natal("쌍둥이 5°") - 65.0) < 1e-6     # 하늘 상승점
    assert abs(A.parse_natal("양자리 11°") - 11.0) < 1e-6    # 하늘 수성 — '자리'가 붙은 이름도 읽는다


def test_natal_longitudes_from_chart(haneul):
    n = A.natal_longitudes(haneul)
    assert "asc_ruler" not in n           # 룰러(행성명)는 좌표 아님 → 제외
    assert abs(n["sun"] - 354.0) < 1e-6   # 물고기 24°
    assert abs(n["asc"] - 65.0) < 1e-6    # 쌍둥이 5°
    assert abs(n["moon"] - 109.0) < 1e-6  # 게 19°


def test_natal_longitudes_requires_a_chart():
    """명식을 안 넘기면 멈춘다 — 누구의 출생 천궁도도 기본값으로 쓰지 않는다."""
    with pytest.raises(TypeError):
        A.natal_longitudes()


# ── 트랜짓 황경 (천체력 회귀 고정값) ─────────────────────────
def test_transit_known_date():
    # 2000-01-01, hour_kst=21 → UT 12:00
    tr = A.transit_longitudes(date(2000, 1, 1), hour_kst=21)
    sun_sign, sun_deg = A.lon_to_sign(tr["태양"][0])
    moon_sign, _ = A.lon_to_sign(tr["달"][0])
    assert sun_sign == "염소" and 10.0 < sun_deg < 11.0   # 280.38°
    assert moon_sign == "전갈"                              # 223.33°


# ── 각도/아스펙트 ────────────────────────────────────────────
def test_angular_sep():
    assert abs(A.angular_sep(10, 350) - 20.0) < 1e-9
    assert abs(A.angular_sep(10, 190) - 180.0) < 1e-9


def test_find_aspects_detects_and_rejects():
    natal = {"sun": 210.0}
    asp = A.find_aspects({"달": (210.0, False)}, natal)          # 정확히 합
    assert any(a["aspect"] == "합" and a["n_key"] == "sun" for a in asp)
    asp2 = A.find_aspects({"달": (330.0, False)}, natal)         # 120° → 삼각
    assert any(a["aspect"] == "삼각" and a["n_key"] == "sun" for a in asp2)
    asp3 = A.find_aspects({"달": (260.0, False)}, natal)         # 50° = 메이저 각 아님
    assert not asp3


# ── today_layer ─────────────────────────────────────────────
def test_today_layer_shape(haneul):
    L = A.today_layer(date(2026, 6, 22), chart=haneul)
    assert L["date"] == "2026-06-22"
    assert isinstance(L["moon"], tuple) and len(L["moon"]) == 2
    assert isinstance(L["sun"], tuple)
    assert isinstance(L["aspects"], list)
    assert "달" in L["transits"]


def test_today_layer_requires_a_chart():
    with pytest.raises(TypeError):
        A.today_layer(date(2026, 6, 22))


# ── 황경 좌표계 — apparent of-date (절기·점성 관례와 동일) ───
def test_sun_longitude_of_date_at_sohseo():
    # 2026 소서(태양 황경 105° 통과) = 7/7 10:57 KST(이 엔진 10:56:59.6 · JPL DE421 10:56:57.4,
    # tools/verify_with_de421.py --sun-crossing 105로 대조). 11시 계산이면 105°를 막 지난 값(105.002°)이어야 한다.
    # J2000 분점 황경을 쓰면 104.64° 근처로 떨어져 실패한다 (세차 0.36°).
    tr = A.transit_longitudes(date(2026, 7, 7), hour_kst=11)
    assert abs(tr["태양"][0] - 105.0) < 0.05, f"태양 황경 {tr['태양'][0]:.3f}"


# ── 각 지속성(persists) — 반복 조언 차단 입력 ────────────────
def test_aspects_have_persists_flag(haneul):
    L = A.today_layer(date(2026, 7, 3), chart=haneul)
    assert L["aspects"] and all(isinstance(a.get("persists"), bool) for a in L["aspects"])


def test_persists_all_carryover_day(haneul):
    # 2026-06-03(하늘): 이날 8각 전부 어제부터 지속 — "새 각 없는 날"
    L = A.today_layer(date(2026, 6, 3), chart=haneul)
    by_key = {(a["t"], a["aspect"], a["n_key"]): a["persists"] for a in L["aspects"]}
    assert by_key[("목성", "삼각", "sun")] is True
    assert by_key[("토성", "합", "mercury")] is True
    assert L["aspects"] and all(a["persists"] for a in L["aspects"])


def test_persists_only_moon_aspect_is_new(haneul):
    # 2026-06-01(하늘): 달 각만 새로 들어오고 나머지는 지속
    L = A.today_layer(date(2026, 6, 1), chart=haneul)
    moon_new = [a for a in L["aspects"] if a["t"] == "달"]
    others = [a for a in L["aspects"] if a["t"] != "달"]
    assert moon_new and all(a["persists"] is False for a in moon_new)
    assert others and all(a["persists"] is True for a in others)


# ── 역행 종료일(순행 전환일) — 기한 없는 "미뤄라" 차단 입력 ──
def test_retro_until_mercury_2026_july():
    # 2026-07 수성 역행은 7/23까지, 7/24 낮부터 순행.
    assert A.retro_until(ephem.Mercury, date(2026, 7, 19)) == date(2026, 7, 24)


def test_retro_until_none_when_direct():
    assert A.retro_until(ephem.Mercury, date(2026, 7, 24)) is None


def test_today_layer_carries_retro_until(haneul):
    L = A.today_layer(date(2026, 7, 19), chart=haneul)
    assert L["retro_until"].get("수성") == "2026-07-24"
    for k in L["retro_until"]:                 # 실린 행성은 transits에서도 역행 표시여야 (정합)
        assert L["transits"][k][1] is True
