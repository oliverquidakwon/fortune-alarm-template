# -*- coding: utf-8 -*-
"""run_daily state(최근 발송문) 회귀 테스트 — 7일 롤링·동일 날짜 대체·fail-open 로드."""
import json
from datetime import date

import run_daily as R


def _patch_state(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "STATE_PATH", str(tmp_path / "state" / "recent.json"))


def test_load_missing_returns_empty(tmp_path, monkeypatch):
    _patch_state(monkeypatch, tmp_path)
    assert R.load_recent() == []


def test_load_broken_json_returns_empty(tmp_path, monkeypatch):
    _patch_state(monkeypatch, tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "recent.json").write_text("{깨진 json", encoding="utf-8")
    assert R.load_recent() == []


def test_load_filters_malformed_rows(tmp_path, monkeypatch):
    _patch_state(monkeypatch, tmp_path)
    (tmp_path / "state").mkdir()
    rows = [{"date": "2026-07-01", "text": "정상"}, {"date": "2026-07-02"}, "문자열"]
    (tmp_path / "state" / "recent.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    assert R.load_recent() == [{"date": "2026-07-01", "text": "정상"}]


def test_save_keeps_last_7_sorted(tmp_path, monkeypatch):
    _patch_state(monkeypatch, tmp_path)
    for i in range(1, 10):                       # 9일 적재 → 7일만 남아야
        R.save_recent(R.load_recent(), date(2026, 7, i), f"메시지{i}")
    rows = R.load_recent()
    assert len(rows) == R.RECENT_KEEP == 7
    assert rows[0]["date"] == "2026-07-03"       # 1·2일자는 밀려남
    assert rows[-1]["date"] == "2026-07-09"
    assert [r["date"] for r in rows] == sorted(r["date"] for r in rows)


def test_save_same_date_replaces(tmp_path, monkeypatch):
    _patch_state(monkeypatch, tmp_path)
    R.save_recent(R.load_recent(), date(2026, 7, 5), "첫 발송")
    R.save_recent(R.load_recent(), date(2026, 7, 5), "재실행 발송")
    rows = R.load_recent()
    assert len(rows) == 1 and rows[0]["text"] == "재실행 발송"


def test_save_roundtrip_korean(tmp_path, monkeypatch):
    _patch_state(monkeypatch, tmp_path)
    msg = "【오늘의 사주】\n에너지가 안으로 모이는 흐름이에요.\n\n마무리 한 줄이에요."
    R.save_recent([], date(2026, 7, 5), msg)
    assert R.load_recent()[0]["text"] == msg


def test_save_creates_the_state_folder(tmp_path, monkeypatch):
    """state/ 폴더는 저장소에 미리 두지 않는다 — 첫 발송 때 코드가 만든다."""
    _patch_state(monkeypatch, tmp_path)
    assert not (tmp_path / "state").exists()
    R.save_recent([], date(2026, 7, 5), "첫 발송")
    assert (tmp_path / "state" / "recent.json").exists()


def test_recent_for_prompt_excludes_same_date():
    # 같은 날 재발송 때 그날 아침 발송문이 들어가면 모델이 그것을 밑그림 삼아 거의 그대로 베낀다
    rows = [{"date": "2026-07-18", "text": "어제 발송문"},
            {"date": "2026-07-19", "text": "오늘 아침 발송문"}]
    assert R.recent_for_prompt(rows, date(2026, 7, 19)) == [{"date": "2026-07-18", "text": "어제 발송문"}]
    assert R.recent_for_prompt(rows, date(2026, 7, 20)) == rows


def test_state_path_follows_state_dir(tmp_path, monkeypatch):
    _patch_state(monkeypatch, tmp_path)
    assert R.state_path_for("recent_하늘.json") == str(tmp_path / "state" / "recent_하늘.json")
