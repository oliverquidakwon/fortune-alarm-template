# -*- coding: utf-8 -*-
"""
saju_core 회귀 테스트.

기대값의 출처: 예시 인물(하늘·바다) 값은 계산 엔진의 실제 출력을 고정한 것이고,
절기 시각은 전문 만세력(NASA DE441·천문연 기준) 앵커다. 기대값을 시험하는 코드로 다시 만들지 않는다.
"""
from datetime import date, datetime

import pytest

import saju_core as sc


# ── 일진 (JDN) ───────────────────────────────────────────────
def test_haneul_birth_day_is_gichuk():
    assert sc.day_ganji(date(1992, 3, 14)) == "己丑"


def test_bada_day_pillar_turns_at_midnight():
    # 바다는 밤 23:40 출생 — 달력 날짜가 바뀌기 전과 후의 일진이 다르다(관례 B가 다음날을 쓰는 이유)
    assert sc.day_ganji(date(1988, 7, 9)) == "乙丑"
    assert sc.day_ganji(date(1988, 7, 10)) == "丙寅"


def test_today_day_ganji():
    assert sc.day_ganji(date(2026, 6, 21)) == "丙寅"


# ── 연주 (입춘 경계) ─────────────────────────────────────────
def test_year_ganji_after_ipchun():
    assert sc.year_ganji(date(2026, 6, 21)) == "丙午"


def test_year_ganji_before_ipchun_rolls_back():
    # 입춘 전 → 전년(乙巳)
    assert sc.year_ganji(date(2026, 1, 15)) == "乙巳"


# ── 월주 (절기월 + 오호둔) ───────────────────────────────────
def test_month_ganji_table():
    cases = {
        date(2026, 6, 21): "甲午",
        date(2026, 7, 15): "乙未",
        date(2026, 8, 15): "丙申",
        date(2026, 9, 15): "丁酉",
        date(2026, 10, 15): "戊戌",
        date(2026, 11, 15): "己亥",
        date(2026, 12, 15): "庚子",
    }
    for d, expected in cases.items():
        assert sc.month_ganji(d) == expected, f"{d} → {sc.month_ganji(d)} != {expected}"


# ── 십성 전수 (기토 일간 — 하늘) ─────────────────────────────
def test_sipsung_all_gan():
    dm = "己"
    expected = {"甲": "정관", "乙": "편관", "丙": "정인", "丁": "편인", "戊": "겁재",
                "己": "비견", "庚": "상관", "辛": "식신", "壬": "정재", "癸": "편재"}
    for g, s in expected.items():
        assert sc.sipsung(dm, g) == s, f"{g} → {sc.sipsung(dm, g)} != {s}"


def test_branch_sipsung_all():
    dm = "己"
    expected = {"子": "편재", "丑": "비견", "寅": "정관", "卯": "편관", "辰": "겁재", "巳": "정인",
                "午": "편인", "未": "비견", "申": "상관", "酉": "식신", "戌": "겁재", "亥": "정재"}
    for b, s in expected.items():
        assert sc.branch_sipsung(dm, b) == s, f"{b} → {sc.branch_sipsung(dm, b)} != {s}"


# ── 4층 조합 (하늘) ──────────────────────────────────────────
def test_four_layers_haneul(haneul):
    r = sc.four_layers(date(2026, 6, 21), haneul)
    assert r["daewoon"] == {"ganji": "己亥", "gan_sipsung": "비견", "branch_sipsung": "정재"}
    assert r["year"] == {"ganji": "丙午", "gan_sipsung": "정인", "branch_sipsung": "편인"}
    assert r["month"] == {"ganji": "甲午", "gan_sipsung": "정관", "branch_sipsung": "편인"}
    assert r["day"] == {"ganji": "丙寅", "gan_sipsung": "정인", "branch_sipsung": "정관"}
    assert r["ziwei"] is None            # 자미두수 층은 이 템플릿에 없다


def test_four_layers_requires_a_chart():
    """명식 없이 계산하지 않는다 —
    누군가의 명식이 기본값으로 숨어 있으면 설정을 잘못 읽은 날 남의 운세가 나간다."""
    with pytest.raises(TypeError):
        sc.four_layers(date(2026, 6, 21))


# ── 절기 시각 경계 (ephem apparent of-date) ──────────────────
def test_sohseo_hour_boundary():
    # 2026 소서 = 7/7 10:56 KST (DE441 만세력 대조). 아침 발송(07시)은 아직 갑오월.
    assert sc.month_ganji(date(2026, 7, 7), hour_kst=7) == "甲午"
    assert sc.month_ganji(date(2026, 7, 7), hour_kst=12) == "乙未"


def test_mangjong_2026_is_june_6():
    # 2026 망종은 6/5가 아니라 6/6 00:48 KST.
    assert sc.month_ganji(date(2026, 6, 5)) == "癸巳"    # 아직 사월
    assert sc.month_ganji(date(2026, 6, 6)) == "甲午"    # 00:48 이후 (기본 07시)


def test_ipchun_hour_boundary():
    # 2026 입춘 = 2/4 05:02 KST. 그 전은 전년 을사.
    assert sc.year_ganji(date(2026, 2, 4), hour_kst=0) == "乙巳"
    assert sc.year_ganji(date(2026, 2, 4), hour_kst=7) == "丙午"


def test_solar_term_moment_external_anchors():
    # 전문 만세력(NASA DE441·천문연 기준) 앵커 ±5분: 입춘 2/4 05:02 · 망종 6/6 00:48 · 소서 7/7 10:56
    anchors = [(315, 2, datetime(2026, 2, 4, 5, 2)),
               (75, 6, datetime(2026, 6, 6, 0, 48)),
               (105, 7, datetime(2026, 7, 7, 10, 56))]
    for lon, hint, expected in anchors:
        got = sc.solar_term_moment(2026, lon, hint)
        diff_min = abs((got - expected).total_seconds()) / 60
        assert diff_min < 5, f"황경 {lon}°: {got} vs {expected} ({diff_min:.0f}분 차)"


def test_month_ganji_2029_no_keyerror():
    # 절기를 표가 아니라 계산으로 구하므로 몇 년 뒤도 계산된다
    assert sc.month_ganji(date(2029, 6, 15)) == "庚午"


# ── 일진 ↔ 원국 충합 (하늘: 壬申·癸卯·己丑·己巳) ─────────────
def test_interactions_gapin_haneul(haneul):
    # 甲寅: 寅-申 충(연지) + 甲-己 천간합(일간·시간 둘 다)
    kinds = {(i["kind"], i["natal_pos"]) for i in sc.ganji_interactions("甲寅", haneul)}
    assert kinds == {("지지충", "년지"), ("천간합", "일간"), ("천간합", "시간")}


def test_interactions_jeongyu_haneul(haneul):
    # 丁酉: 丁-壬 천간합(연간) + 酉-卯 충(월지)
    assert sc.ganji_interactions("丁酉", haneul) == [
        {"kind": "천간합", "pair": "丁-壬", "natal_pos": "년간"},
        {"kind": "지지충", "pair": "酉-卯", "natal_pos": "월지"}]


def test_interactions_none_haneul(haneul):
    assert sc.ganji_interactions("乙丑", haneul) == []


# ── four_layers 통합 (충합 + 절기 전환) ─────────────────────
def test_four_layers_term_change_on_sohseo(haneul):
    r = sc.four_layers(date(2026, 7, 7), haneul)
    tc = r["term_change"]
    assert tc is not None and tc["to_ganji"] == "乙未"
    assert tc["at"].startswith("10:5")                   # 10:56 (DE441 만세력 정합)
    assert tc["to_gan_sipsung"] == "편관" and tc["to_branch_sipsung"] == "비견"
    assert r["month"]["ganji"] == "甲午"                  # 발송 기준(07시)은 전환 전


def test_four_layers_normal_day_no_term_change(haneul):
    assert sc.four_layers(date(2026, 7, 5), haneul)["term_change"] is None


def test_four_layers_has_interactions(haneul):
    r = sc.four_layers(date(2026, 9, 1), haneul)         # 戊寅일 → 인신충 + 무계합
    kinds = {i["kind"] for i in r["interactions"]}
    assert kinds == {"지지충", "천간합"}


def test_ganji_interactions_alias_kept():
    assert sc.day_interactions is sc.ganji_interactions


def test_background_interactions_2026(haneul):
    r = sc.four_layers(date(2026, 7, 19), haneul)
    # 세운 丙午는 하늘 원국과 충합 없음
    assert r["year_interactions"] == []
    # 월운 乙未: 未-丑 충(일지)
    assert r["month_interactions"] == [{"kind": "지지충", "pair": "未-丑", "natal_pos": "일지"}]
    # 대운 己亥: 亥-巳 충(시지) — 10년 배경
    assert r["daewoon_interactions"] == [{"kind": "지지충", "pair": "亥-巳", "natal_pos": "시지"}]
