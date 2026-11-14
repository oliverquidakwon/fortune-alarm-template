# -*- coding: utf-8 -*-
"""
me.yaml 로더 테스트 — 설정 파일 하나가 사람·출생정보·받을 곳을 정한다.

잘못 적힌 칸은 무엇을 어떻게 고치라는 한 문장으로 멈춰야 한다. 조용히 넘어가면 다른 사람의
사주(또는 틀린 사주)가 매일 아침 나간다. 테스트는 임시 폴더에 yaml을 써서 읽는다.
"""
import pytest

import me_config as MC
from examples import BADA_YAML, HANEUL_YAML


def _write(tmp_path, text: str):
    p = tmp_path / "me.yaml"
    p.write_text(text, encoding="utf-8")
    return str(p)


# ── 기본 읽기 ────────────────────────────────────────────────

def test_load_haneul_into_birth_data(tmp_path):
    cfg = MC.load(_write(tmp_path, HANEUL_YAML))
    assert [p.name for p in cfg.people] == ["하늘"]
    b = cfg.people[0].birth
    assert (b.solar, b.place, b.sex, b.convention) == ("1992-03-14 10:10", "대전", "여", "A")
    assert b.coords == (36.350, 127.385)          # 대전 — 지역 사전 값


# ── hour_rule — 자시 경계 관례 선택 ─────────────────────────

@pytest.mark.parametrize("rule,day,hour", [
    ("A", "乙丑", "丁亥"),
    ("B", "丙寅", "戊子"),
    ("C", "乙丑", "丙子"),
])
def test_hour_rule_picks_the_convention(tmp_path, rule, day, hour):
    """세 관례의 일주·시주가 서로 다른 바다로 시험한다. 세 관례가 같은 하늘로는
    hour_rule을 무시하는 결함을 잡지 못한다."""
    import chart_factory
    b = MC.load(_write(tmp_path, BADA_YAML.format(rule=rule))).people[0].birth
    natal = chart_factory.build(b).NATAL
    assert (natal["day"], natal["hour"]) == (day, hour)


def test_hour_rule_defaults_to_a(tmp_path):
    assert MC.load(_write(tmp_path, HANEUL_YAML)).people[0].birth.convention == "A"


# ── 지역 사전에 없는 곳은 lat/lon ───────────────────────────

def test_place_outside_dictionary_uses_lat_lon(tmp_path):
    text = HANEUL_YAML.replace("place: 대전", "place: 우리동네\n      lat: 36.6\n      lon: 127.5")
    b = MC.load(_write(tmp_path, text)).people[0].birth
    assert b.coords == (36.6, 127.5)
    assert b.place == "우리동네"


# ── 출생 시각 모름 — 엔진은 시각 없이 계산하지 못한다 ──────────

@pytest.mark.parametrize("blank", ["", "~", "null"])
def test_missing_birth_time_stops_with_instruction(tmp_path, blank):
    text = HANEUL_YAML.replace("time: 10:10", f"time: {blank}".rstrip())
    with pytest.raises(MC.ConfigError) as e:
        MC.load(_write(tmp_path, text))
    msg = str(e.value)
    assert "birth.time" in msg and "HH:MM" in msg and "12:00" in msg


# ── 잘못 적힌 me.yaml — 고칠 방법을 말하고 멈춘다 ────────────

def _error(tmp_path, text: str) -> str:
    with pytest.raises(MC.ConfigError) as e:
        MC.load(_write(tmp_path, text))
    return str(e.value)


@pytest.mark.parametrize("bad", ["1992.03.14", "1992/03/14", "92-03-14", "1992년 3월 14일"])
def test_bad_date_format(tmp_path, bad):
    msg = _error(tmp_path, HANEUL_YAML.replace("date: 1992-03-14", f"date: {bad}"))
    assert "birth.date" in msg and "1992-03-14" in msg and "하이픈" in msg


def test_date_not_on_calendar(tmp_path):
    msg = _error(tmp_path, HANEUL_YAML.replace("1992-03-14", "1992-02-30"))
    assert "달력에 없는 날짜" in msg


def test_future_date(tmp_path):
    msg = _error(tmp_path, HANEUL_YAML.replace("1992-03-14", "2999-03-14"))
    assert "미래" in msg


def test_date_before_1900(tmp_path):
    msg = _error(tmp_path, HANEUL_YAML.replace("1992-03-14", "0992-03-14"))
    assert "1900" in msg


@pytest.mark.parametrize("text", [
    HANEUL_YAML.replace("date: 1992-03-14", "date: 음력 1992-02-10"),
    HANEUL_YAML.replace("date: 1992-03-14", "date: 1992-02-10(음력)"),
    HANEUL_YAML.replace("date: 1992-03-14", "date: 1992-02-10\n      lunar: true"),
])
def test_lunar_date_is_refused(tmp_path, text):
    """엔진에 음력 변환기가 없다. 음력 날짜를 양력으로 읽으면 조용히 다른 사람 사주가 나간다."""
    msg = _error(tmp_path, text)
    assert "음력" in msg and "양력" in msg


def test_explicit_solar_marker_is_accepted(tmp_path):
    cfg = MC.load(_write(tmp_path, HANEUL_YAML.replace("date: 1992-03-14", "date: 1992-03-14(양력)")))
    assert cfg.people[0].birth.solar == "1992-03-14 10:10"


@pytest.mark.parametrize("bad", ["녀", "여자", "F", "male"])
def test_gender_typo(tmp_path, bad):
    msg = _error(tmp_path, HANEUL_YAML.replace("gender: 여", f"gender: {bad}"))
    assert "gender" in msg and "여 또는 남" in msg


@pytest.mark.parametrize("bad", ["25:00", "10시", "1010", "오후 3시", "10:75"])
def test_bad_time_format(tmp_path, bad):
    msg = _error(tmp_path, HANEUL_YAML.replace("time: 10:10", f"time: {bad}"))
    assert "birth.time" in msg and "24시간" in msg


def test_time_is_normalized_to_two_digits(tmp_path):
    cfg = MC.load(_write(tmp_path, HANEUL_YAML.replace("time: 10:10", "time: 9:05")))
    assert cfg.people[0].birth.solar == "1992-03-14 09:05"


def test_bad_hour_rule(tmp_path):
    msg = _error(tmp_path, BADA_YAML.format(rule="D"))
    assert "hour_rule" in msg and "A·B·C" in msg


def test_lowercase_hour_rule_is_accepted(tmp_path):
    assert MC.load(_write(tmp_path, BADA_YAML.format(rule="b"))).people[0].birth.convention == "B"


def test_unknown_key_is_refused_not_ignored(tmp_path):
    """오타 칸(hour_rul)을 조용히 무시하면 관례가 기본값 A로 바뀐 채 매일 나간다."""
    msg = _error(tmp_path, HANEUL_YAML + "    hour_rul: B\n")
    assert "hour_rul" in msg and "hour_rule" in msg


def test_unknown_birth_key_is_refused(tmp_path):
    msg = _error(tmp_path, HANEUL_YAML.replace("place: 대전", "place: 대전\n      plcae: 서울"))
    assert "plcae" in msg


def test_unknown_place_without_coords(tmp_path):
    msg = _error(tmp_path, HANEUL_YAML.replace("place: 대전", "place: 김포"))
    assert "김포" in msg and "lat" in msg and "lon" in msg and "대전" in msg


def test_place_suffix_is_tolerated(tmp_path):
    cfg = MC.load(_write(tmp_path, HANEUL_YAML.replace("place: 대전", "place: 대전광역시")))
    assert cfg.people[0].birth.place == "대전"


def test_lat_without_lon(tmp_path):
    msg = _error(tmp_path, HANEUL_YAML.replace("place: 대전", "place: 우리동네\n      lat: 36.6"))
    assert "lat" in msg and "lon" in msg


def test_lat_lon_must_be_numbers_in_range(tmp_path):
    msg = _error(tmp_path, HANEUL_YAML.replace(
        "place: 대전", "place: 우리동네\n      lat: 북위36\n      lon: 127.5"))
    assert "숫자" in msg
    msg2 = _error(tmp_path, HANEUL_YAML.replace(
        "place: 대전", "place: 우리동네\n      lat: 136.6\n      lon: 127.5"))
    assert "범위" in msg2


def test_chat_id_number_must_not_live_in_me_yaml(tmp_path):
    """chat id 숫자는 시크릿에 둔다 — 저장소가 실수로 공개되면 me.yaml은 누구나 읽는다."""
    msg = _error(tmp_path, HANEUL_YAML + "    chat: 12345\n")
    assert "FORTUNE_CHAT_IDS" in msg


def test_duplicate_names(tmp_path):
    two = HANEUL_YAML + HANEUL_YAML.split("people:\n", 1)[1]
    msg = _error(tmp_path, two)
    assert "하늘" in msg and "다른 이름" in msg


@pytest.mark.parametrize("text", ["model: claude-sonnet-5-5\n", "people: []\n", "people:\n"])
def test_people_missing_or_empty(tmp_path, text):
    msg = _error(tmp_path, text)
    assert "people" in msg


def test_missing_name(tmp_path):
    msg = _error(tmp_path, HANEUL_YAML.replace("  - name: 하늘\n    birth:", "  - birth:"))
    assert "name" in msg


def test_missing_birth_block(tmp_path):
    msg = _error(tmp_path, "people:\n  - name: 하늘\n    gender: 여\n")
    assert "birth" in msg


def test_yaml_syntax_error_points_to_line(tmp_path):
    broken = HANEUL_YAML.replace("    gender: 여", "  gender 여: :")
    msg = _error(tmp_path, broken)
    assert "번째 줄" in msg and "들여쓰기" in msg


# YAML 파서는 고장 난 줄의 다음 줄을 가리킬 때가 많다 — 실제로 틀린 줄 번호가 문장에 들어 있어야 한다.
# HANEUL_YAML: 1 people: / 2 - name / 3 birth: / 4 date / 5 time / 6 place / 7 gender
def test_yaml_error_names_the_line_without_a_space_after_the_colon(tmp_path):
    msg = _error(tmp_path, HANEUL_YAML.replace("time: 10:10", "time:10:10"))
    assert "5번째 줄" in msg


def test_yaml_error_names_the_line_with_a_full_width_colon(tmp_path):
    msg = _error(tmp_path, HANEUL_YAML.replace("date: 1992-03-14", "date：1992-03-14"))
    assert "4번째 줄" in msg


def test_yaml_error_names_an_uncommented_line_that_kept_its_space(tmp_path):
    """'# model:'에서 #만 지우면 앞 공백이 남아 들여쓰기가 어긋난다 — 그 줄을 가리키고, # 뒤 공백까지 지우라고 말한다."""
    text = " model: claude-sonnet-5-5\n\n" + HANEUL_YAML          # 1번째 줄이 틀렸다(3번째 줄이 people:)
    msg = _error(tmp_path, text)
    assert "1번째 줄" in msg and "# 뒤 공백" in msg


def test_duplicate_people_key_stops_with_both_line_numbers(tmp_path):
    """people:를 두 번 쓰면 YAML은 뒤의 것으로 앞의 것을 말없이 덮는다 — 맨 위 사람(본인)이 사라진다."""
    text = HANEUL_YAML + BADA_YAML.format(rule="A")                 # people: 가 1번째 줄과 8번째 줄
    msg = _error(tmp_path, text)
    assert "'people' 칸이 두 번" in msg and "1번째 줄" in msg and "8번째 줄" in msg


def test_duplicate_date_key_stops(tmp_path):
    text = HANEUL_YAML.replace("      date: 1992-03-14\n", "      date: 1992-03-14\n      date: 2001-02-03\n")
    msg = _error(tmp_path, text)
    assert "'date' 칸이 두 번" in msg and "4번째 줄" in msg and "5번째 줄" in msg


# ── 이름이 같은 다른 곳 — 조용히 한쪽으로 읽지 않는다 ──────────

def test_gwangju_si_is_ambiguous_and_stops(tmp_path):
    """'광주시'는 경기도 광주시의 공식 이름이기도 하다 — 광주광역시 좌표로 읽으면 진태양시가 어긋난다."""
    msg = _error(tmp_path, HANEUL_YAML.replace("place: 대전", "place: 광주시"))
    assert "경기도 광주시" in msg and "광주광역시" in msg and "lat" in msg


def test_gwangju_metro_names_still_resolve(tmp_path):
    for name in ("광주", "광주광역시"):
        p = MC.load(_write(tmp_path, HANEUL_YAML.replace("place: 대전", f"place: {name}"))).people[0]
        assert p.birth.coords == (35.160, 126.851), name


# ── 한글 윈도의 로컬 점검 — 출력이 cp949 파이프·콘솔이어도 죽지 않는다 ────

def _cp949_run(*args):
    """-X utf8 없이, 표준 출력이 cp949인 환경(한글 윈도의 파이프·리다이렉트)처럼 돌린다."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    env["PYTHONIOENCODING"] = "cp949"
    r = subprocess.run([sys.executable, "-B", *map(str, args)], cwd=Path(__file__).resolve().parents[1],
                       capture_output=True, env=env)
    return r.returncode, r.stdout.decode("cp949", "replace"), r.stderr.decode("cp949", "replace")


def test_check_survives_a_cp949_pipe(tmp_path):
    """'—' 같은 글자를 cp949가 못 써도 점검이 트레이스백으로 끝나지 않는다(못 쓰는 글자만 ?로 바뀐다)."""
    code, out, err = _cp949_run("me_config.py", _write(tmp_path, TWO))
    assert code == 0, err
    assert "별자리 세 축" in out and "UnicodeEncodeError" not in err


# ── 점검 출력 — 대운 줄 ─────────────────────────────────────

HANEUL_DW = "  대운 역행 · 대운수 3세 (원값 2.91) · 지금 기해(己亥) 대운 2025년부터 2034년까지 — 올해 2026년은 2년째"
BADA_DW = ("  대운 순행 · 대운수 10세 (원값 9.56) · 지금 임술(壬戌) 대운 2019년부터 2028년까지 — 올해 2026년은 8년째"
           " · 반올림/버림 경계(시작 해가 1년 앞뒤로 갈릴 수 있음)")


def test_cli_check_prints_the_daewoon_line_in_order(tmp_path, capsys, monkeypatch):
    """2장 3강이 '점검 출력에서 지금 대운을 읽는 법'으로 쓰는 줄 — 방향·대운수(원값)·지금 대운의 간지와 기간·
    올해가 몇 년째인지. 한 사람분 순서: 첫 줄 → 사주 원국 → 관례별 → 대운 → 별자리 세 축 → 확인 필요."""
    import birth as B
    monkeypatch.setattr(B, "_kst_year", lambda: 2026)              # 실행 연도에 기대지 않는다
    assert MC.main([_write(tmp_path, TWO)]) == 0
    out = capsys.readouterr().out.splitlines()
    h = out.index("[하늘] 1992-03-14 10:10 대전 · 여 · 관례 A · 받을 곳 TELEGRAM_CHAT_ID")
    assert out[h + 3] == HANEUL_DW
    for i, head in ((1, "  사주 원국:"), (2, "  관례별 일주·시주:"), (4, "  별자리 세 축:"), (5, "  확인 필요:")):
        assert out[h + i].startswith(head), (i, out[h + i])
    b = next(i for i, ln in enumerate(out) if ln.startswith("[바다]"))
    assert out[b + 3] == BADA_DW


def test_daewoon_line_outside_the_table(tmp_path, capsys, monkeypatch):
    import birth as B
    monkeypatch.setattr(B, "_kst_year", lambda: 2026)
    assert MC.main([_write(tmp_path, HANEUL_YAML.replace("date: 1992-03-14", "date: 1905-05-20"))]) == 0
    dw = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("  대운 ")]
    assert dw and dw[0].endswith("올해 2026년은 대운표 범위 밖")


def test_check_and_preview_print_the_same_daewoon_words(tmp_path, capsys, monkeypatch):
    """birth.py 미리보기와 점검 출력이 대운 방향·대운수를 같은 글자로 찍는다(한 곳에서 만든다)."""
    import sys

    import birth as B
    monkeypatch.setattr(B, "_kst_year", lambda: 2026)
    monkeypatch.setattr(sys, "argv", ["birth.py", "--solar", "1988-07-09 23:40", "--place", "부산", "--sex", "남"])
    assert B.main() == 0
    preview = capsys.readouterr().out
    assert "대운 순행 · 대운수 10세 (원값 9.56)  <- 반올림/버림 경계" in preview      # 예전 미리보기 글자 그대로
    assert "A 기준 2026 대운 壬戌" in preview
    assert BADA_DW.strip().startswith("대운 순행 · 대운수 10세 (원값 9.56)")


# ── 점검 출력 — 별자리 세 축 ────────────────────────────────

def test_cli_check_prints_the_three_astro_axes(tmp_path, capsys):
    """3장 1강이 '내 세 축을 확인하는 명령'으로 쓰는 줄 — 출생 천궁도 계산값 그대로(태양·달·상승점)."""
    assert MC.main([_write(tmp_path, TWO)]) == 0
    out = capsys.readouterr().out
    assert "  별자리 세 축: 태양 물고기자리 24도 · 달 게자리 19도 · 상승점 쌍둥이자리 5도" in out     # 하늘
    bada = [ln for ln in out.splitlines() if "별자리 세 축" in ln][1]
    assert bada.startswith("  별자리 세 축: 태양 게자리 ")


def test_missing_file(tmp_path):
    with pytest.raises(MC.ConfigError) as e:
        MC.load(str(tmp_path / "없는파일.yaml"))
    assert "me.yaml" in str(e.value)


# ── 받을 곳(chat) 해석 — 실제 chat id는 시크릿에서만 온다 ─────

TWO = HANEUL_YAML + BADA_YAML.format(rule="B").split("people:\n", 1)[1] + "    chat: bada\n"


def test_chat_defaults_to_me(tmp_path):
    cfg = MC.load(_write(tmp_path, TWO))
    assert [p.chat for p in cfg.people] == ["me", "bada"]


def test_resolve_chat_me_uses_telegram_chat_id(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", " 1001 ")
    monkeypatch.delenv("FORTUNE_CHAT_IDS", raising=False)
    assert MC.resolve_chat_id("me") == "1001"


def test_resolve_chat_key_uses_json_secret(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1001")
    monkeypatch.setenv("FORTUNE_CHAT_IDS", '{"bada": "2002", "sky": 3003}')
    assert MC.resolve_chat_id("bada") == "2002"
    assert MC.resolve_chat_id("sky") == "3003"       # 숫자로 적혀 있어도 글자로 돌려준다
    assert MC.resolve_chat_id("me") == "1001"        # me는 JSON이 아니라 TELEGRAM_CHAT_ID


def test_resolve_chat_missing_is_none(monkeypatch):
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv("FORTUNE_CHAT_IDS", '{"other": "1"}')
    assert MC.resolve_chat_id("me") is None
    assert MC.resolve_chat_id("bada") is None


def test_resolve_chat_broken_json_is_skip_not_crash(monkeypatch, capsys):
    monkeypatch.setenv("FORTUNE_CHAT_IDS", "{깨진 json")
    assert MC.resolve_chat_id("bada") is None
    assert "FORTUNE_CHAT_IDS" in capsys.readouterr().out
    monkeypatch.setenv("FORTUNE_CHAT_IDS", '["객체가", "아니다"]')
    assert MC.resolve_chat_id("bada") is None


def test_chat_where_names_the_secret(tmp_path):
    cfg = MC.load(_write(tmp_path, TWO))
    assert cfg.people[0].chat_where == "TELEGRAM_CHAT_ID"
    assert cfg.people[1].chat_where == 'FORTUNE_CHAT_IDS의 "bada" 칸'


# ── 받을 사람 목록 해석 ──────────────────────────────────────

def test_select_all_by_default(tmp_path):
    people = MC.load(_write(tmp_path, TWO)).people
    assert [p.name for p in MC.select(people, None)] == ["하늘", "바다"]
    assert [p.name for p in MC.select(people, "")] == ["하늘", "바다"]
    assert [p.name for p in MC.select(people, "all")] == ["하늘", "바다"]


def test_select_subset_keeps_me_yaml_order(tmp_path):
    people = MC.load(_write(tmp_path, TWO)).people
    assert [p.name for p in MC.select(people, "바다, 하늘")] == ["하늘", "바다"]
    assert [p.name for p in MC.select(people, "바다")] == ["바다"]


def test_select_unknown_name_errors(tmp_path):
    people = MC.load(_write(tmp_path, TWO)).people
    with pytest.raises(MC.ConfigError) as e:
        MC.select(people, "구름")
    assert "구름" in str(e.value) and "하늘" in str(e.value)


def test_first_person_is_primary(tmp_path):
    """맨 위 사람(본인)의 발송 실패는 전체 실패, 나머지 사람의 실패는 부분 실패로 갈린다."""
    assert [p.primary for p in MC.load(_write(tmp_path, TWO)).people] == [True, False]


# ── 최근 발송문 파일 이름 ────────────────────────────────────

def test_state_file_named_after_person(tmp_path):
    assert [p.state_file for p in MC.load(_write(tmp_path, TWO)).people] == [
        "recent_하늘.json", "recent_바다.json"]


def test_state_file_name_is_file_safe(tmp_path):
    cfg = MC.load(_write(tmp_path, HANEUL_YAML.replace("name: 하늘", "name: 하늘 / 엄마")))
    assert cfg.people[0].state_file == "recent_하늘_엄마.json"


def test_names_that_collide_as_files_are_refused(tmp_path):
    a = HANEUL_YAML.replace("name: 하늘", "name: 하늘 엄마")
    b = HANEUL_YAML.replace("name: 하늘", "name: 하늘/엄마").split("people:\n", 1)[1]
    with pytest.raises(MC.ConfigError) as e:
        MC.load(_write(tmp_path, a + b))
    assert "다른 이름" in str(e.value)


# ── 해석 모델 ───────────────────────────────────────────────

def test_model_defaults_to_the_code_constant(tmp_path):
    import interpret
    assert MC.load(_write(tmp_path, HANEUL_YAML)).model == interpret.DEFAULT_MODEL


def test_default_model_is_the_one_checked_by_a_real_call(tmp_path):
    """기본 모델은 실제 호출로 확인한 값이어야 한다 — 2026-11-14 실호출에서 claude-sonnet-5-5는 하늘 1회
    호출로 게이트를 통과했다(claude-sonnet-5는 재생성 2회 뒤 통과). 바꿀 때는 실호출로 다시 확인한다."""
    assert MC.load(_write(tmp_path, HANEUL_YAML)).model == "claude-sonnet-5-5"


def test_model_can_be_changed_in_me_yaml(tmp_path):
    cfg = MC.load(_write(tmp_path, "model: claude-opus-5\n" + HANEUL_YAML))
    assert cfg.model == "claude-opus-5"


@pytest.mark.parametrize("bad", ["sonnet", "claude sonnet 5", "gpt-4o"])
def test_model_must_look_like_a_claude_model_id(tmp_path, bad):
    msg = _error(tmp_path, f"model: {bad}\n" + HANEUL_YAML)
    assert "model" in msg and "claude-" in msg


# ── 호칭 · 명식 ──────────────────────────────────────────────

def test_honorific_reaches_birth_data(tmp_path):
    cfg = MC.load(_write(tmp_path, HANEUL_YAML + "    honorific: 하늘님\n"))
    assert cfg.people[0].birth.honorific == "하늘님"
    assert MC.load(_write(tmp_path, HANEUL_YAML)).people[0].birth.honorific == ""


def test_cli_check_prints_chart_summary_and_warnings(tmp_path, capsys):
    """python me_config.py — Claude를 부르지 않고(요금 0) 사람마다 명식과 확인할 점을 보여 준다."""
    assert MC.main([_write(tmp_path, TWO)]) == 0
    out = capsys.readouterr().out
    assert "[하늘]" in out and "임신 · 계묘 · 기축 · 기사" in out and "일간 기토" in out
    assert "A 을축/정해 · B 병인/무자 · C 을축/병자" in out          # 바다: 관례마다 갈린다
    assert "[바다] 확인 필요: 표준시 보정 적용" in out
    assert 'FORTUNE_CHAT_IDS의 "bada" 칸' in out


def test_cli_check_flags_birth_before_1908(tmp_path, capsys):
    """1908-04-01 전 출생도 받는다 — 막지 않고 점검 출력의 '확인 필요'로 알린다."""
    assert MC.main([_write(tmp_path, HANEUL_YAML.replace("date: 1992-03-14", "date: 1905-05-20"))]) == 0
    assert "[하늘] 확인 필요: 1908년 4월 이전 출생은 표준시 기준이 달라" in capsys.readouterr().out


def test_cli_check_bad_yaml_exits_1(tmp_path, capsys):
    assert MC.main([_write(tmp_path, HANEUL_YAML.replace("gender: 여", "gender: 녀"))]) == 1
    assert "여 또는 남" in capsys.readouterr().err


def test_person_chart_is_built_once_from_birth(tmp_path):
    p = MC.load(_write(tmp_path, HANEUL_YAML)).people[0]
    assert p.chart.NATAL == {"year": "壬申", "month": "癸卯", "day": "己丑", "hour": "己巳"}
    assert p.chart is p.chart
