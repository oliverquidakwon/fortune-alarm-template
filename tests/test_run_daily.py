# -*- coding: utf-8 -*-
"""
run_daily 흐름 — 여러 사람 격리 · 종료 코드 · 설정 오류 · 경고 출력 · 게이트 루프.

Claude(interpret.generate)와 텔레그램(notify.send_telegram)은 가짜로 바꿔 끼운다 — 이 테스트는
돈이 드는 호출을 하지 않는다. 최근 발송문 state는 임시 폴더로 돌린다.
"""
from datetime import date

import pytest

import interpret
import me_config as MC
import notify
import quality_gate as QG
import run_daily as R
from examples import BADA_YAML, EVIDENCE_DATE_LINE, EVIDENCE_WRONG_DATE_LINE, HANEUL_YAML

TWO = HANEUL_YAML + BADA_YAML.format(rule="B").split("people:\n", 1)[1] + "    chat: bada\n"


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "STATE_PATH", str(tmp_path / "state" / "recent.json"))
    monkeypatch.setattr(R, "_load_env", lambda *a, **k: None)
    for k in ("TELEGRAM_CHAT_ID", "FORTUNE_CHAT_IDS", "ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def cfg_path(tmp_path):
    def make(text=TWO):
        p = tmp_path / "me.yaml"
        p.write_text(text, encoding="utf-8")
        return str(p)
    return make


def _people(cfg_path, text=TWO):
    return MC.load(cfg_path(text)).people


def _run_main(monkeypatch, outcomes, argv, secrets=True):
    if secrets:                                  # 실발송 전 사전 점검(봇 토큰·본인 chat id)을 통과시킨다
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_TOKEN)
        monkeypatch.setenv("TELEGRAM_CHAT_ID", FAKE_CHAT_ID)
    calls = []

    def fake_run_one(person, d, dry_run, model):
        calls.append((person.name, model))
        r = outcomes[person.name]
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(R, "run_one", fake_run_one)
    return R.main(argv), calls


# ═══ 설정 오류 — 한 문장 + 종료 코드 1 ════════════════════════

def test_bad_me_yaml_exits_1_with_one_sentence(cfg_path, capsys):
    code = R.main(["--config", cfg_path(HANEUL_YAML.replace("gender: 여", "gender: 녀")), "--dry-run"])
    err = capsys.readouterr().err
    assert code == 1
    assert "[me.yaml]" in err and "여 또는 남" in err
    assert "Traceback" not in err


def test_unknown_people_filter_exits_1(cfg_path, capsys):
    assert R.main(["--config", cfg_path(), "--people", "구름", "--dry-run"]) == 1
    assert "구름" in capsys.readouterr().err


def test_bad_date_argument_exits_1(cfg_path, capsys):
    assert R.main(["--config", cfg_path(), "--date", "2026/11/15"]) == 1
    assert "--date" in capsys.readouterr().err


# ═══ 종료 코드 — 한 사람의 사고가 나머지 발송을 막지 않는다 ════

def test_exit_0_when_all_sent(cfg_path, monkeypatch):
    code, calls = _run_main(monkeypatch, {"하늘": "sent", "바다": "sent"},
                            ["--config", cfg_path(), "--date", "2026-08-03"])
    assert code == 0 and [c[0] for c in calls] == ["하늘", "바다"]


def test_exit_2_on_secondary_failure(cfg_path, monkeypatch):
    """둘째 사람 실패는 부분 실패(2) — 워크플로가 첫 사람 state를 커밋한 뒤 빨간불로 처리한다."""
    code, _ = _run_main(monkeypatch, {"하늘": "sent", "바다": "failed"},
                        ["--config", cfg_path(), "--date", "2026-08-03"])
    assert code == 2


def test_exit_2_when_secondary_raises(cfg_path, monkeypatch):
    code, calls = _run_main(monkeypatch, {"하늘": "sent", "바다": RuntimeError("명식 계산 사고")},
                            ["--config", cfg_path(), "--date", "2026-08-03"])
    assert code == 2 and [c[0] for c in calls] == ["하늘", "바다"]


def test_exit_1_on_primary_failure(cfg_path, monkeypatch):
    code, _ = _run_main(monkeypatch, {"하늘": "failed", "바다": "sent"},
                        ["--config", cfg_path(), "--date", "2026-08-03"])
    assert code == 1


def test_primary_crash_still_lets_the_rest_go(cfg_path, monkeypatch):
    code, calls = _run_main(monkeypatch, {"하늘": RuntimeError("사고"), "바다": "sent"},
                            ["--config", cfg_path(), "--date", "2026-08-03"])
    assert code == 1 and [c[0] for c in calls] == ["하늘", "바다"]


def test_skipped_is_not_failure(cfg_path, monkeypatch):
    """가족·친구(맨 위가 아닌 사람)의 chat id 미등록 = 건너뜀이지 실패가 아니다. 본인은 사전 점검이 막는다(아래)."""
    code, _ = _run_main(monkeypatch, {"하늘": "sent", "바다": "skipped"},
                        ["--config", cfg_path(), "--date", "2026-08-03"])
    assert code == 0


def _no_claude(monkeypatch) -> list:
    called = []
    monkeypatch.setattr(interpret, "generate", lambda *a, **k: called.append(1) or "가짜 발송문")
    return called


def test_missing_bot_token_stops_before_calling_claude(cfg_path, capsys, monkeypatch):
    """봇 토큰이 비면 Claude를 부른 뒤(요금) 죽지 말고, 부르기 전에 무엇을 어디에 넣을지 한 문장으로 멈춘다."""
    called = _no_claude(monkeypatch)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", FAKE_CHAT_ID)
    assert R.main(["--config", cfg_path(), "--date", "2026-08-03"]) == 1
    err = capsys.readouterr().err
    assert "TELEGRAM_BOT_TOKEN" in err and "Settings" in err
    assert called == []


def test_missing_own_chat_id_stops_instead_of_a_green_run(cfg_path, capsys, monkeypatch):
    """본인(맨 위 사람)의 chat id가 비면 '건너뜀'으로 초록 불을 켜지 않고 실패로 멈춘다(아무것도 안 온 날을 모른다)."""
    called = _no_claude(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_TOKEN)
    assert R.main(["--config", cfg_path(), "--date", "2026-08-03"]) == 1
    err = capsys.readouterr().err
    assert "TELEGRAM_CHAT_ID" in err and "하늘" in err
    assert called == []


def test_own_chat_named_in_the_json_must_be_there_too(cfg_path, capsys, monkeypatch):
    called = _no_claude(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_TOKEN)
    me_first_as_bada = HANEUL_YAML + "    chat: bada\n"
    assert R.main(["--config", cfg_path(me_first_as_bada), "--date", "2026-08-03"]) == 1
    assert "FORTUNE_CHAT_IDS" in capsys.readouterr().err
    assert called == []


def test_dry_run_skips_the_send_precheck(cfg_path, monkeypatch):
    """dry_run은 보내지 않으니 토큰·chat id 없이도 해석을 만들어 보여 준다."""
    called = _no_claude(monkeypatch)
    monkeypatch.setattr(QG, "check", lambda msg, profile=None, headers=None, date_line=None: [])
    assert R.main(["--config", cfg_path(HANEUL_YAML), "--date", "2026-08-03", "--dry-run"]) == 0
    assert called == [1]


def test_people_filter_runs_only_named(cfg_path, monkeypatch):
    code, calls = _run_main(monkeypatch, {"하늘": "sent", "바다": "sent"},
                            ["--config", cfg_path(), "--people", "바다", "--date", "2026-08-03"])
    assert code == 0 and [c[0] for c in calls] == ["바다"]


def test_model_from_me_yaml_reaches_run_one(cfg_path, monkeypatch):
    code, calls = _run_main(monkeypatch, {"하늘": "dry", "바다": "dry"},
                            ["--config", cfg_path("model: claude-opus-5\n" + TWO), "--dry-run"])
    assert code == 0 and {c[1] for c in calls} == {"claude-opus-5"}


# ═══ run_one — 받을 곳 · 경고 · 발송 · state ═══════════════════

def test_run_one_skips_without_chat_id_before_paying(cfg_path, capsys, monkeypatch):
    called = []
    monkeypatch.setattr(interpret, "generate", lambda *a, **k: called.append(1) or "x")
    bada = _people(cfg_path)[1]                   # chat: bada, FORTUNE_CHAT_IDS 없음
    assert R.run_one(bada, date(2026, 8, 3), dry_run=False, model="m") == "skipped"
    assert "chat_id 없음" in capsys.readouterr().out
    assert called == []                           # 보내지도 못할 운세에 Claude 요금을 쓰지 않는다


def test_run_one_prints_birth_warnings(cfg_path, capsys, monkeypatch):
    monkeypatch.setattr(interpret, "generate", lambda *a, **k: "가짜 발송문")
    monkeypatch.setattr(QG, "check", lambda msg, profile=None, headers=None, date_line=None: [])
    bada = _people(cfg_path)[1]
    assert R.run_one(bada, date(2026, 8, 3), dry_run=True, model="m") == "dry"
    out = capsys.readouterr().out
    assert "[바다] 확인 필요: 표준시 보정 적용: 1988 서머타임" in out
    assert "[바다] 확인 필요: 자시 경계에 걸림" in out


def test_run_one_flags_birth_before_1908(cfg_path, capsys, monkeypatch):
    monkeypatch.setattr(interpret, "generate", lambda *a, **k: "가짜 발송문")
    monkeypatch.setattr(QG, "check", lambda msg, profile=None, headers=None, date_line=None: [])
    old = _people(cfg_path, HANEUL_YAML.replace("date: 1992-03-14", "date: 1905-05-20"))[0]
    assert R.run_one(old, date(2026, 8, 3), dry_run=True, model="m") == "dry"
    assert "[하늘] 확인 필요: 1908년 4월 이전 출생은 표준시 기준이 달라" in capsys.readouterr().out


FAKE_TOKEN = "1234" + "56789:" + "WxYz" * 9           # 지어낸 토큰(이어 붙여 만든다)


def _no_network(*a, **k):
    raise OSError("시험 중 네트워크 차단")


def _shown(capsys) -> str:
    c = capsys.readouterr()
    return c.out + c.err


def test_failure_log_never_shows_secret_values(cfg_path, capsys, monkeypatch):
    """한 사람의 실패는 트레이스백으로 남기되 시크릿 글자는 가린다 — 라이브러리 예외 문장에 토큰이 실려 와도."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_TOKEN + "\n")

    def boom(*a, **k):
        raise ValueError(f"https://api.telegram.org/bot{FAKE_TOKEN}\n/sendMessage 실패")

    monkeypatch.setattr(R, "run_one", boom)
    assert R.main(["--config", cfg_path(HANEUL_YAML), "--dry-run"]) == 1
    shown = _shown(capsys)
    assert "ValueError" in shown                       # 무슨 일이 났는지는 남는다
    for part in (FAKE_TOKEN, FAKE_TOKEN.split(":")[1], FAKE_TOKEN[:12]):
        assert part not in shown


def test_bad_token_in_a_real_send_fails_without_showing_it(cfg_path, capsys, monkeypatch):
    """줄바꿈이 붙은(가운데에도 낀) 가짜 토큰으로 실제 발송 경로를 타면 실패하되, 출력 어디에도 토큰 글자가 없다."""
    import socket

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_TOKEN[:20] + "\n" + FAKE_TOKEN[20:] + "\n")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", FAKE_CHAT_ID)
    monkeypatch.setattr(interpret, "generate", lambda *a, **k: "가짜 발송문")
    monkeypatch.setattr(QG, "check", lambda msg, profile=None, headers=None, date_line=None: [])
    monkeypatch.setattr(socket, "create_connection", _no_network)
    monkeypatch.setattr(notify, "_sleep", lambda s: None)
    assert R.main(["--config", cfg_path(HANEUL_YAML), "--date", "2026-08-03"]) == 1
    shown = _shown(capsys)
    assert "TELEGRAM_BOT_TOKEN" in shown
    for part in (FAKE_TOKEN[:20], FAKE_TOKEN[20:], "api.telegram.org/bot"):
        assert part not in shown


def test_same_day_message_fits_where_it_runs(cfg_path, capsys, monkeypatch):
    """Actions에는 --force 입력이 없다 — 실행 기록에서는 dry_run을, 내 컴퓨터에서는 --force를 안내한다."""
    monkeypatch.setattr(R, "sent_today", lambda p, d: True)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", FAKE_CHAT_ID)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert R.main(["--config", cfg_path(HANEUL_YAML), "--date", "2026-08-03"]) == 0
    out = capsys.readouterr().out
    assert "이미 발송됨" in out and "dry_run" in out and "--force" not in out
    monkeypatch.delenv("GITHUB_ACTIONS")
    assert R.main(["--config", cfg_path(HANEUL_YAML), "--date", "2026-08-03"]) == 0
    assert "--force" in capsys.readouterr().out


def test_run_log_survives_a_cp949_pipe(cfg_path):
    """-X utf8 없이 표준 출력이 cp949여도 실행 기록 줄('—'가 든 줄)에서 죽지 않는다. 키가 없으니 Claude는 못 부르고
    그 사람은 실패로 끝나지만, 그 전의 안내 줄은 찍혀야 한다."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    drop = {"PYTHONUTF8", "PYTHONIOENCODING", "ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
            "FORTUNE_CHAT_IDS"}
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env["PYTHONIOENCODING"] = "cp949"
    r = subprocess.run([sys.executable, "-B", "run_daily.py", "--dry-run", "--config", cfg_path(HANEUL_YAML)],
                       cwd=Path(__file__).resolve().parents[1], capture_output=True, env=env)
    out, err = r.stdout.decode("cp949", "replace"), r.stderr.decode("cp949", "replace")
    assert "chat_id 없음" in out and "UnicodeEncodeError" not in err


def test_quiet_birth_prints_no_warning(cfg_path, capsys, monkeypatch):
    monkeypatch.setattr(interpret, "generate", lambda *a, **k: "가짜 발송문")
    monkeypatch.setattr(QG, "check", lambda msg, profile=None, headers=None, date_line=None: [])
    R.run_one(_people(cfg_path)[0], date(2026, 8, 3), dry_run=True, model="m")
    assert "확인 필요" not in capsys.readouterr().out


def test_send_uses_the_persons_chat_id_and_saves_only_their_state(cfg_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1001")
    monkeypatch.setenv("FORTUNE_CHAT_IDS", '{"bada": "2002"}')
    monkeypatch.setattr(interpret, "generate", lambda *a, **k: "바다 발송문")
    monkeypatch.setattr(QG, "check", lambda msg, profile=None, headers=None, date_line=None: [])
    sent = []
    monkeypatch.setattr(notify, "send_telegram",
                        lambda msg, chat_id=None, **k: sent.append((chat_id, msg)) or True)
    haneul, bada = _people(cfg_path)
    assert R.run_one(bada, date(2026, 8, 3), dry_run=False, model="m") == "sent"
    assert sent == [("2002", "바다 발송문")]
    assert R.load_recent(R.state_path_for(bada.state_file))[0]["text"] == "바다 발송문"
    assert R.load_recent(R.state_path_for(haneul.state_file)) == []


def test_send_failure_keeps_state_untouched(cfg_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1001")
    monkeypatch.setattr(interpret, "generate", lambda *a, **k: "하늘 발송문")
    monkeypatch.setattr(QG, "check", lambda msg, profile=None, headers=None, date_line=None: [])
    monkeypatch.setattr(notify, "send_telegram", lambda *a, **k: False)
    haneul = _people(cfg_path)[0]
    assert R.run_one(haneul, date(2026, 8, 3), dry_run=False, model="m") == "failed"
    assert R.load_recent(R.state_path_for(haneul.state_file)) == []


def test_dry_run_reports_missing_chat_id(capsys):
    R.report_chat_id("[바다]", 'FORTUNE_CHAT_IDS의 "bada" 칸', None, dry_run=True)
    out = capsys.readouterr().out
    assert "chat_id 없음" in out and "실발송이면 건너뛴다" in out


FAKE_CHAT_ID = "5550" + "1234"                   # 가짜 id — 이어 붙여 만든다(긴 숫자를 글자 그대로 두지 않는다)


def test_dry_run_reports_resolved_chat_id_masked(capsys):
    R.report_chat_id("[하늘]", "TELEGRAM_CHAT_ID", FAKE_CHAT_ID, dry_run=True)
    out = capsys.readouterr().out
    assert "chat_id 확인" in out and "1234" in out
    assert FAKE_CHAT_ID not in out               # 전체 id는 로그에 남기지 않는다


def test_send_mode_stays_quiet_on_resolved_chat_id(capsys):
    R.report_chat_id("[하늘]", "TELEGRAM_CHAT_ID", FAKE_CHAT_ID, dry_run=False)
    assert capsys.readouterr().out == ""


# ═══ 게이트 연동 ═════════════════════════════════════════════

def test_run_one_passes_header_expectation_and_profile(cfg_path, monkeypatch):
    captured = {}

    def fake_check(msg, profile=None, headers=None, date_line=None):
        captured.update(headers=headers, profile=profile, date_line=date_line)
        return []

    monkeypatch.setattr(QG, "check", fake_check)
    monkeypatch.setattr(interpret, "generate", lambda *a, **k: "가짜 발송문")
    assert R.run_one(_people(cfg_path)[0], date(2026, 8, 3), dry_run=True, model="m") == "dry"
    assert captured["headers"] == {"monthly": False, "weekly": True}     # 월요일
    assert captured["profile"] is QG.EXTERNAL_PROFILE
    assert captured["date_line"] == "8월 3일 월요일"                      # 코드가 만든 날짜 줄


def test_wrong_date_line_is_fixed_before_sending_without_regeneration(cfg_path, monkeypatch, capsys):
    """실호출 증거: 첫 줄 '6월이 아니라 11월 14일 토요일'이 게이트를 통과해 나갈 뻔했다.
    이제는 코드가 만든 날짜 줄로 바꿔 내보내고, 그 때문에 Claude를 다시 부르지 않는다."""
    calls = []
    monkeypatch.setattr(interpret, "generate", lambda *a, **k: calls.append(1) or EVIDENCE_WRONG_DATE_LINE)
    haneul = _people(cfg_path)[0]
    assert R.run_one(haneul, date(2026, 11, 14), dry_run=True, model="m") == "dry"
    body = capsys.readouterr().out.split("===== 생성 메시지 (하늘) =====\n", 1)[1]
    assert body.startswith(EVIDENCE_DATE_LINE + "\n")
    assert "6월이 아니라" not in body
    assert calls == [1]


def test_retry_note_accumulates_all_seen_violations(cfg_path, monkeypatch):
    """1차(A) → 재생성 1회차(B·C) → 위반 적은 1차 채택 → 2회차 지시에 A·B·C가 모두 있어야
    1회차에서 본 위반을 또 만들지 않는다."""
    notes, msgs = [], iter(["m0", "m1", "m2"])
    viol = {"m0": ["A"], "m1": ["B", "C"], "m2": ["B"]}

    def fake_generate(layers, model=None, retry_note=None, profile=None):
        notes.append(list(retry_note or []))
        return next(msgs)

    monkeypatch.setattr(interpret, "generate", fake_generate)
    monkeypatch.setattr(QG, "check", lambda msg, profile=None, headers=None, date_line=None: list(viol[msg]))
    assert R.run_one(_people(cfg_path)[0], date(2026, 8, 17), dry_run=True, model="m") == "dry"
    assert notes == [[], ["A"], ["A", "B", "C"]]


def _replies(monkeypatch, *items) -> list:
    """generate가 차례로 돌려줄 (본문, 끝난 이유). 마지막 것을 계속 돌려준다. 받은 재생성 지시를 기록한다."""
    notes = []

    def fake(*a, retry_note=None, **k):
        notes.append(list(retry_note or []))
        text, why = items[min(len(notes), len(items)) - 1]
        return interpret.Reply(text, why)

    monkeypatch.setattr(interpret, "generate", fake)
    return notes


def _sender(monkeypatch) -> list:
    sent = []
    monkeypatch.setattr(notify, "send_telegram", lambda msg, chat_id=None, **k: sent.append(msg) or True)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", FAKE_CHAT_ID)
    return sent


def test_cut_off_reply_is_rewritten_and_the_complete_one_sent(cfg_path, monkeypatch):
    """분량 상한에서 끊긴 글은 위반으로 보고 다시 쓰게 한다 — 끝까지 온 글을 보낸다."""
    notes = _replies(monkeypatch, ("끊긴 글 지출 하나를 저", "max_tokens"), ("온전한 글", "end_turn"))
    monkeypatch.setattr(QG, "check", lambda msg, profile=None, headers=None, date_line=None: [])
    sent = _sender(monkeypatch)
    assert R.run_one(_people(cfg_path)[0], date(2026, 8, 3), dry_run=False, model="m") == "sent"
    assert sent == ["온전한 글"]
    assert len(notes) == 2 and any("끊" in n for n in notes[1])


def test_reply_that_never_completes_is_not_sent(cfg_path, monkeypatch, capsys):
    """다시 써도 끝까지 온전한 글이 없으면 '덜 틀린 쪽'을 보내지 않고 실패로 끝낸다(이 경우만 fail-open의 예외)."""
    notes = _replies(monkeypatch, ("끊긴 글", "max_tokens"))
    monkeypatch.setattr(QG, "check", lambda msg, profile=None, headers=None, date_line=None: [])
    sent = _sender(monkeypatch)
    assert R.run_one(_people(cfg_path)[0], date(2026, 8, 3), dry_run=False, model="m") == "failed"
    assert sent == [] and len(notes) == 3
    assert "보내지 않" in capsys.readouterr().out


def test_refusal_reply_is_not_sent(cfg_path, monkeypatch):
    _replies(monkeypatch, ("죄송하지만 이 요청은 도와드릴 수 없어요.", "refusal"))
    monkeypatch.setattr(QG, "check", lambda msg, profile=None, headers=None, date_line=None: [])
    sent = _sender(monkeypatch)
    assert R.run_one(_people(cfg_path)[0], date(2026, 8, 3), dry_run=False, model="m") == "failed"
    assert sent == []


def test_reply_missing_a_required_section_is_not_sent(cfg_path, monkeypatch):
    """끝맺음 없이 끊긴 글·본문 대신 온 거절 문장은 필수 섹션이 빠진다 — 다시 써도 빠지면 보내지 않는다."""
    _replies(monkeypatch, ("죄송하지만 이 요청은 도와드릴 수 없어요.", "end_turn"))
    monkeypatch.setattr(QG, "check", lambda msg, profile=None, headers=None, date_line=None:
                        ["필수 요소 누락: 【종합】"])
    sent = _sender(monkeypatch)
    assert R.run_one(_people(cfg_path)[0], date(2026, 8, 3), dry_run=False, model="m") == "failed"
    assert sent == []


def test_other_leftover_violations_still_fail_open(cfg_path, monkeypatch):
    """굳은 틀·용어 같은 위반은 종전대로 두 번 다시 쓰게 한 뒤 남아도 보낸다(안 오는 날이 더 나쁘다)."""
    _replies(monkeypatch, ("온전하지만 용어가 남은 글", "end_turn"))
    monkeypatch.setattr(QG, "check", lambda msg, profile=None, headers=None, date_line=None:
                        ["전문용어 노출: 상관"])
    sent = _sender(monkeypatch)
    assert R.run_one(_people(cfg_path)[0], date(2026, 8, 3), dry_run=False, model="m") == "sent"
    assert sent == ["온전하지만 용어가 남은 글"]


def test_autofix_avoids_regeneration(cfg_path, monkeypatch):
    """서식 위반만 있는 1차 생성문은 문자 제거로 통과 — 재생성(요금) 0회."""
    direct = []
    monkeypatch.setattr(interpret, "generate", lambda *a, **k: direct.append(1) or "**굵게** 본문")
    monkeypatch.setattr(QG, "check", lambda msg, profile=None, headers=None, date_line=None:
                        ["마크다운 서식 기호 사용"] if "**" in msg else [])
    assert R.run_one(_people(cfg_path)[0], date(2026, 8, 3), dry_run=True, model="m") == "dry"
    assert direct == [1]


def test_generate_receives_model_and_the_persons_own_chart(cfg_path, monkeypatch):
    seen = {}

    def fake_generate(layers, model=None, retry_note=None, profile=None):
        seen.update(model=model, chart=profile["chart"], dm=layers["day_master"])
        return "x"

    monkeypatch.setattr(interpret, "generate", fake_generate)
    monkeypatch.setattr(QG, "check", lambda *a, **k: [])
    bada = _people(cfg_path)[1]                   # hour_rule B → 일간 丙
    R.run_one(bada, date(2026, 8, 3), dry_run=True, model="claude-opus-5")
    assert seen == {"model": "claude-opus-5", "chart": bada.chart, "dm": "丙"}
