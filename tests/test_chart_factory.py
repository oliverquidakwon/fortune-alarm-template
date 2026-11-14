# -*- coding: utf-8 -*-
"""
출생정보 → 명식 팩토리 회귀 테스트.

세 축:
  ① 일반 규칙 — 표준시 이력·시지 경계·오자둔 기두·대운 방향처럼 사람마다 달라지는 계산
  ② 예시 인물 고정값 — 하늘(경계 밖)·바다(서머타임 + 밤 자시)의 값을 계산 엔진의
     실제 출력으로 고정했다. 계산 모듈을 고치다 값이 바뀌면 여기서 먼저 깨진다.
  ③ 구조 계약 — 계산할 수 없는 값(용신·하우스 번호)을 지어내지 않는다.
"""
import dataclasses
import re
from datetime import date, datetime, timedelta

import pytest

import astro_core as A
import birth as B
import chart_factory
import saju_core as sc
from examples import bada_birth, haneul_birth


# ═══ ① 일반 규칙 ════════════════════════════════════════════

@pytest.mark.parametrize("wall,off,why_has", [
    (datetime(1950, 1, 15, 12, 0), 9.0, False),     # 이력 밖(1950 여름은 서머타임 — test_korea_time_history)
    (datetime(1955, 1, 15, 12, 0), 8.5, True),      # 표준자오선 127.5도 시기(서머타임 철이 아닌 겨울)
    (datetime(1961, 8, 10, 12, 0), 9.0, False),     # 복귀 당일
    (datetime(1987, 7, 1, 12, 0), 10.0, True),      # 1987 서머타임
    (datetime(1988, 7, 9, 23, 40), 10.0, True),     # 1988 서머타임 (바다)
    (datetime(1988, 12, 1, 12, 0), 9.0, False),     # 서머타임 종료 후
    (datetime(1992, 3, 14, 10, 10), 9.0, False),    # 하늘
])
def test_korea_timezone_history(wall, off, why_has):
    """벽시계를 그대로 UTC+9로 두면 옛날 출생자 명식이 조용히 틀린다."""
    got, why = B.utc_offset(wall)
    assert got == off
    assert bool(why) is why_has


def test_equation_of_time_sign_convention():
    """균시차 부호 약속 — 진태양시 − 평균태양시(사전 정의와 반대). true_solar_time은 이 값을 더한다."""
    assert 16.0 < B.equation_of_time_min(datetime(2026, 11, 3, 3, 0)) < 16.7     # 11월 초: 해시계가 시계보다 빠르다
    assert -14.5 < B.equation_of_time_min(datetime(2026, 2, 11, 3, 0)) < -13.9   # 2월 중순: 해시계가 늦다
    b = haneul_birth()
    tst, lon_corr, eot = B.true_solar_time(b)
    assert tst == b.when + timedelta(minutes=lon_corr + eot)


@pytest.mark.parametrize("h,m,branch", [
    (23, 0, "子"), (23, 59, "子"), (0, 30, "子"), (1, 0, "丑"),
    (11, 30, "午"), (13, 0, "未"), (21, 0, "亥"), (22, 59, "亥"),
])
def test_hour_branch_boundaries(h, m, branch):
    assert B.hour_branch(h, m) == branch


@pytest.mark.parametrize("day_gan,zi", [
    ("甲", "甲子"), ("己", "甲子"), ("乙", "丙子"), ("庚", "丙子"),
    ("丙", "戊子"), ("辛", "戊子"), ("丁", "庚子"), ("壬", "庚子"),
    ("戊", "壬子"), ("癸", "壬子"),
])
def test_ozadun_head(day_gan, zi):
    """오자둔 기두 — 한 칸만 밀려도 시주가 통째로 틀린다."""
    assert B.hour_ganji(day_gan, "子") == zi


@pytest.mark.parametrize("year_gan,sex,forward", [
    ("庚", "남", True), ("庚", "여", False),      # 양년
    ("己", "남", False), ("己", "여", True),      # 음년
])
def test_daewoon_direction(year_gan, sex, forward):
    """양남음녀 순행 / 음남양녀 역행."""
    b = B.BirthData(key="t", name="t", solar="1990-06-15 12:00", place="서울", sex=sex)
    assert B.daewoon(b, year_gan, "壬午")["forward"] is forward


def test_place_lookup_and_override():
    b = B.BirthData(key="t", name="t", solar="2000-01-01 12:00", place="부산", sex="남")
    assert b.coords == (35.180, 129.076)
    b2 = B.BirthData(key="t", name="t", solar="2000-01-01 12:00",
                     place="어딘가", sex="남", lat=1.0, lon=2.0)
    assert b2.coords == (1.0, 2.0)
    with pytest.raises(ValueError):
        B.BirthData(key="t", name="t", solar="2000-01-01 12:00",
                    place="모르는곳", sex="남").coords


def test_warns_on_zi_boundary_and_quiet_otherwise():
    assert B.warnings_for(haneul_birth()) == []
    assert any("자시 경계" in w for w in B.warnings_for(bada_birth()))


def test_birth_cli_survives_a_cp949_pipe():
    """birth.py 미리보기도 -X utf8 없이 cp949 출력에서 죽지 않는다('—'는 ?로)."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    env["PYTHONIOENCODING"] = "cp949"
    r = subprocess.run([sys.executable, "-B", "birth.py", "--solar", "1988-07-09 23:40", "--place", "부산",
                        "--sex", "남"], cwd=Path(__file__).resolve().parents[1], capture_output=True, env=env)
    assert r.returncode == 0, r.stderr.decode("cp949", "replace")
    assert "1988 서머타임" in r.stdout.decode("cp949", "replace")


def test_warns_on_dst_birth():
    dst = B.BirthData(key="t", name="t", solar="1988-07-01 10:00", place="서울", sex="남")
    assert any("서머타임" in w for w in B.warnings_for(dst))


# ═══ ② 하늘 고정값 ══════════════════════════════════════════

def test_haneul_pillars_frozen(haneul):
    assert haneul.NATAL == {"year": "壬申", "month": "癸卯", "day": "己丑", "hour": "己巳"}
    assert haneul.DAY_MASTER == "己"
    assert haneul.DAY_MASTER_ELEM == "土" and haneul.DAY_MASTER_YINYANG == "陰"


def test_haneul_three_conventions_agree():
    """자시도 절기 경계도 아닌 시각이면 관례 A·B·C가 같은 일주·시주를 낸다."""
    got = {k: (v[0], v[1]) for k, v in B.pillar_candidates(haneul_birth()).items()}
    assert got == {"A": ("己丑", "己巳"), "B": ("己丑", "己巳"), "C": ("己丑", "己巳")}


def test_haneul_daewoon_frozen(haneul):
    """대운 역행(양년 壬申 + 여 = 양녀 역행), 대운수 = 원값 2.91 → 반올림 3세."""
    info = haneul.DAEWOON_INFO
    assert info["forward"] is False and info["su"] == 3
    assert 2.85 < info["su_raw"] < 2.95
    assert info["boundary"] is False and info["year_shift"] == 0
    assert haneul.DAEWOON_RANGES[:4] == [
        (1995, 2004, "壬寅"), (2005, 2014, "辛丑"), (2015, 2024, "庚子"), (2025, 2034, "己亥")]
    assert len(haneul.DAEWOON_RANGES) == 10          # 노년까지 커버
    assert haneul.current_daewoon(2026)[0] == "己亥"
    assert haneul.current_daewoon(2040)[0] == "戊戌"
    assert haneul.current_daewoon(1992) is None


def test_haneul_true_solar_time_frozen():
    tst, lon_corr, eot = B.true_solar_time(haneul_birth())
    assert tst.strftime("%H:%M") == "09:30"
    assert round(lon_corr, 1) == -30.5
    assert -9.4 < eot < -9.1


def test_haneul_elements_frozen(haneul):
    assert haneul.ELEMENTS == {"木": 1, "火": 1, "土": 3, "金": 1, "水": 2}


def test_haneul_natal_astro_frozen(haneul):
    assert haneul.NATAL_ASTRO == {
        "sun": "물고기 24°", "moon": "게 19°", "mercury": "양자리 11°", "venus": "물고기 0°",
        "mars": "물병 19°", "jupiter": "처녀 8°", "saturn": "물병 14°", "uranus": "염소 17°",
        "neptune": "염소 19°", "pluto": "전갈 23°", "asc": "쌍둥이 5°", "mc": "물병 14°",
        "asc_ruler": "수성",
    }
    assert haneul.ASTRO_SUMMARY == "쌍둥이 상승(룰러 수성)·달 게·태양 물고기"


def test_natal_astro_parses_for_astro_core(haneul):
    lons = A.natal_longitudes(haneul)
    assert set(lons) == set(haneul.NATAL_ASTRO) - {"asc_ruler"}
    for key, expect in [("sun", 354.0), ("asc", 65.0), ("mc", 314.0), ("moon", 109.0)]:
        assert abs(lons[key] - expect) < 1e-6, (key, lons[key])


def test_astro_layer_uses_own_natal(haneul, bada_a):
    assert A.natal_longitudes(haneul) != A.natal_longitudes(bada_a)
    assert A.today_layer(date(2026, 8, 3), chart=haneul)["aspects"]


# ═══ ② 바다 고정값 — 관례 A·B·C가 실제로 갈리는 사람 ═════════

@pytest.mark.parametrize("conv,day,hour", [
    ("A", "乙丑", "丁亥"),      # 진태양시 22:11 → 해시, 일주 당일
    ("B", "丙寅", "戊子"),      # 밤 자시부터 다음날로 넘기는 관례
    ("C", "乙丑", "丙子"),      # 야자시 — 당일 일주 유지, 시지는 벽시계 자시
])
def test_bada_candidate_table(conv, day, hour):
    got = B.pillar_candidates(bada_birth())[conv]
    assert (got[0], got[1]) == (day, hour)


def test_bada_true_solar_time_and_summer_time():
    b = bada_birth()
    assert B.utc_offset(b.when) == (10.0, "1988 서머타임")
    tst, lon_corr, eot = B.true_solar_time(b)
    assert tst.strftime("%H:%M") == "22:11"
    assert round(lon_corr, 1) == -83.7
    assert -5.3 < eot < -5.1


def test_bada_year_and_month_pillars_ignore_convention(bada_a, bada_b):
    assert sc.year_ganji(date(1988, 7, 9), hour_kst=23) == "戊辰"
    assert sc.month_ganji(date(1988, 7, 9), hour_kst=23) == "己未"
    assert bada_a.NATAL["year"] == bada_b.NATAL["year"] == "戊辰"
    assert bada_a.NATAL["month"] == bada_b.NATAL["month"] == "己未"


def test_bada_daewoon_frozen(bada_a):
    """대운 순행(양남), 원값 9.56 → 반올림 10세 — 9/10 유파차 구간이라 경계 표시가 켜진다."""
    info = bada_a.DAEWOON_INFO
    assert info["forward"] is True and info["su"] == 10
    assert 9.5 < info["su_raw"] < 9.6
    assert info["boundary"] is True and info["year_shift"] == 1     # 7월생 → 전환 연도를 한 해 미룸
    assert bada_a.DAEWOON_RANGES[:3] == [(1999, 2008, "庚申"), (2009, 2018, "辛酉"),
                                         (2019, 2028, "壬戌")]
    assert bada_a.current_daewoon(2026)[0] == "壬戌"


def test_bada_warnings():
    w = B.warnings_for(bada_birth())
    assert w == ["표준시 보정 적용: 1988 서머타임 (UTC+10.0) — 벽시계 그대로 쓰면 틀린다",
                 "자시 경계에 걸림 (벽시계 23:40 / 진태양시 22:11) — "
                 "관례에 따라 일주·일간이 갈린다. 본인 확인 필수"]


def test_convention_switch_changes_everything(bada_a, bada_b):
    """관례를 바꾸면 일간과 충합이 통째로 달라진다 — 조용히 바뀌면 안 되는 축."""
    assert bada_a.DAY_MASTER == "乙" and bada_b.DAY_MASTER == "丙"
    assert bada_a.NATAL_ASTRO == bada_b.NATAL_ASTRO          # 별자리는 관례와 무관
    assert sc.ganji_interactions("丙午", bada_a) == [
        {"kind": "지지합", "pair": "午-未", "natal_pos": "월지"}]
    assert {"kind": "지지충", "pair": "午-子", "natal_pos": "시지"} in sc.ganji_interactions("丙午", bada_b)


def test_convention_replace_rebuilds_chart(bada_a):
    alt = chart_factory.build(dataclasses.replace(bada_birth(), convention="B"))
    assert alt.DAY_MASTER == "丙" and bada_a.DAY_MASTER == "乙"


# ═══ ③ 구조 계약 ════════════════════════════════════════════

def test_no_invented_values(haneul):
    assert haneul.ZIWEI_ENABLED is False
    assert haneul.current_daehan_branch(37) is None
    assert haneul.YONGSIN is None and haneul.HEESIN is None and haneul.GUSIN is None


def test_natal_brief_is_plain_korean(haneul):
    assert not re.findall(r"[一-鿿]", haneul.NATAL_BRIEF)
    for term in ("정관", "편재", "식신", "겁재"):
        assert term not in haneul.NATAL_BRIEF          # 십성 용어는 일상어로 치환
    assert "지어내지 마라" in haneul.NATAL_BRIEF
    assert "기축" in haneul.NATAL_BRIEF and "일간 기토" in haneul.NATAL_BRIEF


def test_natal_brief_current_daewoon_follows_the_year(haneul):
    """'현재 10년 대운' 줄은 그 해의 대운이어야 한다. 연도를 고정해 두면
    대운이 바뀌는 해부터 프롬프트의 명식 요약과 오늘 데이터의 대운이 서로 달라진다."""
    args = (haneul.NATAL, haneul.DAY_MASTER, haneul.NATAL_ASTRO, haneul.DAEWOON_RANGES)
    assert "현재 10년 대운: 기해" in B.natal_brief(*args, year=2026)   # 2025~2034 己亥
    assert "현재 10년 대운: 무술" in B.natal_brief(*args, year=2040)   # 2035~2044 戊戌


def test_chart_brief_uses_the_running_year(monkeypatch):
    monkeypatch.setattr(B, "_kst_year", lambda: 2040)
    assert "현재 10년 대운: 무술" in chart_factory.build(haneul_birth()).NATAL_BRIEF


def test_astro_summary_has_no_house_numbers(haneul):
    assert not re.search(r"\d+하우스", haneul.ASTRO_SUMMARY)


def test_honorific_travels_to_chart():
    """호칭은 사람마다 다르다 — 기본값은 '부르지 않음'(빈 문자열)."""
    assert chart_factory.build(haneul_birth()).HONORIFIC == ""
    assert chart_factory.build(haneul_birth(honorific="하늘님")).HONORIFIC == "하늘님"
