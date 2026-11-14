# -*- coding: utf-8 -*-
"""
한국 표준시 이력 — 기간표가 빠뜨렸던 세 구간(1908–1911 UTC+8:30, 1948–1951·1955–1960 서머타임).

부모·조부모 세대를 받는 사람으로 더하면 이 구간에 태어난 사람이 들어온다. 여름 출생 시각을
한 시간 틀린 오프셋으로 UTC로 바꾸면 진태양시가 한 시간 밀려 시주가 한 칸 틀린다.

날짜는 tz database(asia 파일의 Rule ROK·Zone Asia/Seoul)의 규칙을 실제 날짜로 푼 값이다.
서머타임은 시작일 0:00(표준시)에 시작해 종료일 24:00(서머타임)에 끝난다. 경계 관례는 기존
1987·1988 구간과 같다: [시작일 표준시 벽시계, 종료 직후 벽시계) — 종료일 밤에 두 번 지나가는
23시대는 서머타임 쪽으로 읽는다.
"""
from datetime import datetime, timedelta

import pytest

import birth as B

MINUTE = timedelta(minutes=1)

# (연도, 시작 벽시계, 끝 벽시계 = 종료일 다음날 0:00, 평소 오프셋, 서머타임 오프셋)
SUMMER_TIME = [
    (1948, datetime(1948, 6, 1), datetime(1948, 9, 13), 9.0, 10.0),
    (1949, datetime(1949, 4, 3), datetime(1949, 9, 11), 9.0, 10.0),
    (1950, datetime(1950, 4, 1), datetime(1950, 9, 10), 9.0, 10.0),
    (1951, datetime(1951, 5, 6), datetime(1951, 9, 9), 9.0, 10.0),
    (1955, datetime(1955, 5, 5), datetime(1955, 9, 9), 8.5, 9.5),     # UTC+8:30 시기라 그 위에 1시간
    (1956, datetime(1956, 5, 20), datetime(1956, 9, 30), 8.5, 9.5),
    (1957, datetime(1957, 5, 5), datetime(1957, 9, 22), 8.5, 9.5),
    (1958, datetime(1958, 5, 4), datetime(1958, 9, 21), 8.5, 9.5),
    (1959, datetime(1959, 5, 3), datetime(1959, 9, 20), 8.5, 9.5),
    (1960, datetime(1960, 5, 1), datetime(1960, 9, 18), 8.5, 9.5),
]


@pytest.mark.parametrize("year,start,end,usual,summer", SUMMER_TIME,
                         ids=[str(row[0]) for row in SUMMER_TIME])
def test_summer_time_boundaries(year, start, end, usual, summer):
    """시작 1분 전·시작·끝 1분 전·끝 — 네 시각의 오프셋과 사유."""
    off, why = B.utc_offset(start - MINUTE)
    assert off == usual and "서머타임" not in why
    assert B.utc_offset(start) == (summer, f"{year} 서머타임")
    assert B.utc_offset(end - MINUTE) == (summer, f"{year} 서머타임")
    off, why = B.utc_offset(end)
    assert off == usual and "서머타임" not in why


def test_1908_to_1911_used_the_127_5_meridian():
    """1908-04-01부터 1911-12-31까지 UTC+8:30(동경 127.5도), 1912-01-01부터 UTC+9."""
    label = "1908–1911 UTC+8:30 (표준자오선 127.5도)"
    assert B.utc_offset(datetime(1908, 4, 1, 0, 0)) == (8.5, label)
    assert B.utc_offset(datetime(1911, 12, 31, 23, 59)) == (8.5, label)
    assert B.utc_offset(datetime(1912, 1, 1, 0, 0)) == (9.0, "")


def test_before_1908_is_not_claimed():
    """1908-04-01 전은 지방평균시(서울 UTC+8:27:52)라 표가 다루지 않는다 — 1908 구간이 덮지 않는지만 본다."""
    assert "1908" not in B.utc_offset(datetime(1908, 3, 31, 23, 59))[1]


@pytest.mark.parametrize("wall,off", [
    (datetime(1954, 3, 20, 23, 59), 9.0),
    (datetime(1954, 3, 21, 0, 0), 8.5),
    (datetime(1961, 8, 9, 23, 59), 8.5),
    (datetime(1961, 8, 10, 0, 0), 9.0),
    (datetime(1987, 5, 10, 1, 59), 9.0),
    (datetime(1987, 5, 10, 2, 0), 10.0),
    (datetime(1987, 10, 11, 2, 59), 10.0),
    (datetime(1987, 10, 11, 3, 0), 9.0),
    (datetime(1988, 5, 8, 1, 59), 9.0),
    (datetime(1988, 5, 8, 2, 0), 10.0),
    (datetime(1988, 10, 9, 2, 59), 10.0),
    (datetime(1988, 10, 9, 3, 0), 9.0),
])
def test_existing_spans_keep_their_boundaries(wall, off):
    """새 구간을 넣어도 1954–1961 UTC+8:30과 1987·1988 서머타임 경계는 그대로다."""
    assert B.utc_offset(wall)[0] == off


@pytest.mark.parametrize("wall,off", [
    (datetime(1952, 7, 15, 12, 0), 9.0),
    (datetime(1953, 7, 15, 12, 0), 9.0),
    (datetime(1954, 7, 15, 12, 0), 8.5),     # UTC+8:30으로 바뀐 해, 서머타임은 없다
    (datetime(1961, 7, 15, 12, 0), 8.5),
])
def test_summers_without_summer_time(wall, off):
    """서머타임을 하지 않은 여름까지 덮지 않는다."""
    got, why = B.utc_offset(wall)
    assert got == off and "서머타임" not in why


# 이 보정 전의 기간표(세 구간). 보정 효과를 보여 주려고 테스트에만 남긴다.
OLD_TABLE = [
    (datetime(1954, 3, 21, 0, 0), datetime(1961, 8, 10, 0, 0), 8.5, "UTC+8:30 (표준자오선 127.5도)"),
    (datetime(1987, 5, 10, 2, 0), datetime(1987, 10, 11, 3, 0), 10.0, "1987 서머타임"),
    (datetime(1988, 5, 8, 2, 0), datetime(1988, 10, 9, 3, 0), 10.0, "1988 서머타임"),
]

# 지어낸 출생 시각 셋(서울, 관례 A). 기대값은 기간표를 쓰지 않고 오프셋을 직접 넣어 따로 계산했다.
#   (벽시계, 일주, 보정 전 시주, 보정 후 시주, 보정 뒤 경고 첫 줄)
SUMMER_BIRTHS = [
    ("1949-07-15 14:10", "丙午", "乙未", "甲午",       # 진태양시 13:32 → 12:32
     "표준시 보정 적용: 1949 서머타임 (UTC+10.0) — 벽시계 그대로 쓰면 틀린다"),
    ("1957-07-15 13:40", "戊子", "己未", "戊午",       # 13:32 → 12:32
     "표준시 보정 적용: 1957 서머타임 (UTC+9.5) — 벽시계 그대로 쓰면 틀린다"),
    ("1910-06-15 13:20", "辛亥", "甲午", "乙未",       # 12:47 → 13:17
     "표준시 보정 적용: 1908–1911 UTC+8:30 (표준자오선 127.5도) (UTC+8.5) — 벽시계 그대로 쓰면 틀린다"),
]


def _person(solar: str) -> B.BirthData:
    return B.BirthData(key="t", name="t", solar=solar, place="서울", sex="여")


@pytest.mark.parametrize("solar,day,before,after,_warn", SUMMER_BIRTHS,
                         ids=[row[0][:4] for row in SUMMER_BIRTHS])
def test_hour_pillar_follows_the_corrected_offset(monkeypatch, solar, day, before, after, _warn):
    """보정 뒤 시주가 바뀐다 — 옛 기간표로 되돌리면 예전 시주가 나온다(일주는 그대로)."""
    b = _person(solar)
    assert B.pillar_candidates(b)["A"][:2] == (day, after)
    monkeypatch.setattr(B, "_TZ_SPANS", OLD_TABLE)
    assert B.pillar_candidates(b)["A"][:2] == (day, before)


@pytest.mark.parametrize("solar,_day,_before,_after,warn", SUMMER_BIRTHS,
                         ids=[row[0][:4] for row in SUMMER_BIRTHS])
def test_corrected_birth_is_flagged(solar, _day, _before, _after, warn):
    """보정한 사실을 경고 첫 줄로 알린다(실행 로그의 '확인 필요:')."""
    assert B.warnings_for(_person(solar))[:1] == [warn]


# 1908-04-01 전은 지방평균시 시절이라 표로 보정하지 않는다 — 막지 않고 경고만 띄운다.
PRE_1908_WARNING = "1908년 4월 이전 출생은 표준시 기준이 달라 시각 보정을 하지 않는다 — 시주가 어긋날 수 있다"


def test_birth_before_1908_gets_a_warning_not_a_block():
    """1905년생(지어낸 시각)도 명식은 계산하고, 보정하지 않았다는 사실을 경고 첫 줄로 알린다."""
    b = _person("1905-05-20 10:20")
    assert B.pillar_candidates(b)["A"][:2] == ("己未", "己巳")
    assert B.warnings_for(b)[:1] == [PRE_1908_WARNING]


@pytest.mark.parametrize("solar,flagged", [
    ("1908-03-31 23:59", True),
    ("1908-04-01 00:00", False),
    ("1910-06-15 13:20", False),
    ("1957-07-15 13:40", False),
])
def test_pre_1908_warning_stops_at_1908_04_01(solar, flagged):
    """경고는 1908-04-01 0시 전 출생에만 — 그 뒤는 기간표가 보정한다."""
    assert (PRE_1908_WARNING in B.warnings_for(_person(solar))) is flagged
