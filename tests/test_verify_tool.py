# -*- coding: utf-8 -*-
"""
tools/verify_with_de421.py(선택 도구, 수업 4장 3강) — skyfield·DE421 파일 없이 도는 부분만 시험한다.

매일 도는 워크플로에는 skyfield가 깔리지 않는다(requirements.txt에 없다). 그래서 여기서는 대조표가
astro_core의 천체와 맞는지, 입력·파일이 잘못되면 내려받거나 계산하지 않고 멈추는지만 본다.
DE421과 실제로 대조한 출력은 수업자료(검증 기록)에 있다.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import astro_core

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "verify_with_de421.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("verify_with_de421", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(*args) -> tuple[int, str]:
    r = subprocess.run([sys.executable, "-X", "utf8", str(TOOL), *map(str, args)],
                       capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout + r.stderr


def test_tool_table_covers_exactly_the_bodies_astro_core_uses():
    """astro_core의 트랜짓 천체를 바꾸면 대조표도 같이 바꿔야 한다 — 어긋나면 대조에 빈 천체가 생긴다."""
    tool = _load_tool()
    assert set(tool.DE421_TARGETS) == {label for label, _body in astro_core.TRANSIT_BODIES}


def test_tool_stops_on_missing_ephemeris_file(tmp_path):
    """도구는 스스로 내려받지 않는다 — 대신 받는 방법이 적힌 곳(README의 계산 검증 도구 절)을 알려 준다."""
    code, out = _run("2026-11-14", tmp_path / "없는파일.bsp")
    assert code == 2
    assert "[파일 없음]" in out and "내려받지 않고" in out
    assert "README" in out and "계산 검증 도구" in out


def test_tool_rejects_bad_date(tmp_path):
    code, out = _run("2026/11/14", tmp_path / "de421.bsp")
    assert code == 2 and "[입력 오류]" in out


def test_tool_rejects_dates_outside_de421_span(tmp_path):
    code, out = _run("2099-01-01", tmp_path / "de421.bsp")
    assert code == 2 and "DE421 구간" in out
