# -*- coding: utf-8 -*-
"""같은 날 가드 — 그날 이미 보낸 사람은 다시 만들지도 보내지도 않는다(요금이 두 번 나가지 않게).

예약 실행 뒤에 Actions에서 수동 실행을 한 번 더 눌러도 같은 사람에게 두 번 가지 않는다.
state에 오늘 날짜가 있으면 이미 보낸 것이다(state는 발송이 성공했을 때만 저장된다).
다시 보내려면 로컬에서 --force, 내용만 다시 보려면 --dry-run(가드 대상 아님).
"""
from datetime import date, timedelta

import pytest

import me_config as MC
import run_daily as R
from examples import BADA_YAML, HANEUL_YAML

D = date(2026, 10, 13)
TWO = HANEUL_YAML + BADA_YAML.format(rule="B").split("people:\n", 1)[1] + "    chat: bada\n"


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """state를 임시 경로로, 생성·발송을 기록용 가짜로 바꾼다."""
    monkeypatch.setattr(R, "STATE_PATH", str(tmp_path / "state" / "recent.json"))
    monkeypatch.setattr(R, "_load_env", lambda *a, **k: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234" + "56789:" + "Gg" * 18)   # 실발송 사전 점검 통과용 가짜
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "5550" + "1234")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)                      # 안내 문구를 로컬 기준으로 고정
    cfg = tmp_path / "me.yaml"
    cfg.write_text(TWO, encoding="utf-8")
    calls = []

    def fake_run_one(person, d, dry_run, model):
        calls.append((person.name, dry_run))
        return "dry" if dry_run else "sent"

    monkeypatch.setattr(R, "run_one", fake_run_one)

    def run(*argv):
        return R.main(["--config", str(cfg), "--date", D.isoformat(), *argv])

    def mark_sent(name: str, d: date):
        person = MC.select(MC.load(str(cfg)).people, name)[0]
        path = R.state_path_for(person.state_file)
        R.save_recent(R.load_recent(path), d, f"{name} 발송문", path)

    return calls, run, mark_sent


def test_skips_person_already_sent_today(harness, capsys):
    calls, run, mark_sent = harness
    mark_sent("하늘", D)
    assert run("--people", "하늘") == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "[하늘] 2026-10-13 이미 발송됨" in out
    assert "하늘=already" in out


def test_force_resends(harness):
    calls, run, mark_sent = harness
    mark_sent("하늘", D)
    assert run("--people", "하늘", "--force") == 0
    assert calls == [("하늘", False)]


def test_dry_run_is_not_guarded(harness):
    calls, run, mark_sent = harness
    mark_sent("하늘", D)
    assert run("--people", "하늘", "--dry-run") == 0
    assert calls == [("하늘", True)]


def test_yesterday_state_does_not_block(harness):
    calls, run, mark_sent = harness
    mark_sent("하늘", D - timedelta(days=1))
    assert run("--people", "하늘") == 0
    assert calls == [("하늘", False)]


def test_guard_is_per_person(harness, capsys):
    calls, run, mark_sent = harness
    mark_sent("하늘", D)
    assert run() == 0
    assert calls == [("바다", False)]
    assert "하늘=already, 바다=sent" in capsys.readouterr().out


def test_second_run_after_primary_failure_retries_only_the_primary(tmp_path, monkeypatch, capsys):
    """예비 예약(같은 날 두 번째 실행)의 전제 — 본인이 실패하고 가족이 성공한 실행 뒤 같은 날 다시 돌면, 가족은
    state의 오늘 날짜로 건너뛰고(Claude도 부르지 않는다) 본인만 다시 시도한다. 여기서는 state가 같은 폴더에
    남는다. 깃허브에서는 Commit state가 본인 실패 날에도 가족의 state를 커밋해 이 전제를 만든다(그 조건은
    test_pipeline_guard가 본다). 가짜 Claude·텔레그램을 쓰고 계산·게이트 앞뒤·state 저장은 실제 코드다."""
    import interpret
    import notify
    import quality_gate as QG

    me_id, bada_id = "5550" + "1234", "7770" + "4321"          # 가짜 id — 이어 붙여 만든다
    monkeypatch.setattr(R, "STATE_PATH", str(tmp_path / "state" / "recent.json"))
    monkeypatch.setattr(R, "_load_env", lambda *a, **k: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234" + "56789:" + "Gg" * 18)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", me_id)
    monkeypatch.setenv("FORTUNE_CHAT_IDS", '{"bada": "' + bada_id + '"}')
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(QG, "check", lambda msg, profile=None, headers=None, date_line=None: [])
    cfg = tmp_path / "me.yaml"
    cfg.write_text(TWO, encoding="utf-8")
    made, sent, me_ok = [], [], [False]
    monkeypatch.setattr(interpret, "generate", lambda *a, **k: made.append(1) or "가짜 발송문")

    def fake_send(msg, chat_id=None, **k):
        sent.append(chat_id)
        return me_ok[0] if chat_id == me_id else True

    monkeypatch.setattr(notify, "send_telegram", fake_send)
    argv = ["--config", str(cfg), "--date", D.isoformat()]

    assert R.main(argv) == 1                                    # 06:47 — 본인 실패, 바다는 보냄
    assert (len(made), sent) == (2, [me_id, bada_id])
    assert "하늘=failed, 바다=sent" in capsys.readouterr().out

    made.clear()
    sent.clear()
    me_ok[0] = True
    assert R.main(argv) == 0                                    # 07:17 — 같은 날 다시
    assert (len(made), sent) == (1, [me_id])                    # 바다 몫은 만들지도 보내지도 않는다
    out = capsys.readouterr().out
    assert f"[바다] {D.isoformat()} 이미 발송됨" in out and "하늘=sent, 바다=already" in out
