# -*- coding: utf-8 -*-
"""
파이프라인 가드 — 매일 도는 워크플로가 '조용히' 멈추지 않게 하는 장치가 사라지면 여기서 깨진다.

  ① 의존성 메이저 상한: 상한이 없으면 새 메이저 버전이 어느 날 깔려 호출 인자가 바뀌고,
     테스트는 SDK를 가짜로 바꿔 끼워 통과하는데 실제 생성만 죽는다.
  ② 실패 알림: 알림 스텝이 없으면 며칠을 못 받아도 아무 신호가 없다.
예약 시각(cron)은 수강생이 바꿀 수 있으니 값을 고정하지 않는다.
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows" / "daily-fortune.yml"


def _workflow() -> dict:
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def _steps() -> dict:
    return {s.get("name"): s for s in _workflow()["jobs"]["send"]["steps"]}


def test_every_requirement_has_a_major_upper_bound():
    specs = [ln.split("#", 1)[0].strip()
             for ln in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()]
    specs = [s for s in specs if s]
    assert specs
    for spec in specs:
        assert re.search(r"<\s*\d", spec) or "==" in spec or "~=" in spec, f"상한 없는 의존성: {spec}"


def test_optional_verify_requirements_are_separate_and_bounded():
    """계산 검증 도구(skyfield)는 선택이다 — 매일 알림 설치(requirements.txt)에 섞지 않고 따로 둔다."""
    specs = [ln.split("#", 1)[0].strip()
             for ln in (ROOT / "requirements-verify.txt").read_text(encoding="utf-8").splitlines()]
    specs = [s for s in specs if s]
    assert any(s.lower().startswith("skyfield") for s in specs)
    for spec in specs:
        assert re.search(r"<\s*\d", spec) or "==" in spec or "~=" in spec, f"상한 없는 의존성: {spec}"
    assert "skyfield" not in (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()


def test_workflow_installs_requirements_and_runs_tests_before_sending():
    runs = [s.get("run", "") for s in _workflow()["jobs"]["send"]["steps"]]
    i_pip = next(i for i, r in enumerate(runs) if "pip install -r requirements.txt" in r)
    i_test = next(i for i, r in enumerate(runs) if "pytest" in r)
    i_send = next(i for i, r in enumerate(runs) if "run_daily.py" in r)
    assert i_pip < i_test < i_send


CHECK_STEP = "내 명식 점검 (me.yaml)"


def test_chart_check_step_runs_before_tests_without_secrets():
    """파이썬이 없는 수강생도 실행 기록에서 점검 출력(네 기둥·관례별 후보·별자리 세 축·확인 필요)을 보게 한다.
    me.yaml이 잘못됐으면 여기서 고칠 말 한 문장과 함께 멈춘다. 계산만 하니 비밀값은 주지 않는다."""
    steps = _workflow()["jobs"]["send"]["steps"]
    names = [s.get("name") for s in steps]
    assert CHECK_STEP in names
    i_pip = next(i for i, s in enumerate(steps) if "pip install -r requirements.txt" in s.get("run", ""))
    i_check, i_test = names.index(CHECK_STEP), names.index("Run tests")
    assert i_pip < i_check < i_test < names.index("Send daily fortune")
    check = steps[i_check]
    assert "me_config.py" in check["run"] and "-X utf8" in check["run"]
    assert "env" not in check and "secrets." not in str(check)


def test_workflow_ends_with_a_failure_alert_that_checks_telegram_ok():
    """실패뿐 아니라 취소(작업 시간 제한에 걸린 경우 포함)에도 알린다."""
    last = _workflow()["jobs"]["send"]["steps"][-1]
    assert last.get("if") == "failure() || cancelled()"
    assert "sendMessage" in last["run"] and 'r.get("ok")' in last["run"]
    assert "secrets.TELEGRAM_BOT_TOKEN" in str(last.get("env"))


def test_dry_run_input_reaches_run_daily_and_skips_the_state_commit():
    wf = _workflow()
    on = wf.get("on", wf.get(True))            # PyYAML은 'on' 키를 True로 읽는다
    assert on["workflow_dispatch"]["inputs"]["dry_run"]["type"] == "boolean"
    steps = _steps()
    assert "inputs.dry_run" in steps["Send daily fortune"]["run"]
    assert "!inputs.dry_run" in steps["Commit state"]["if"]


def test_secrets_stay_out_of_the_test_step():
    """테스트 스텝에 API 키가 있으면 실수로 실제 호출(요금)을 하는 테스트가 생겨도 모른다."""
    wf = _workflow()
    assert "env" not in wf["jobs"]["send"]
    assert "secrets." not in str(_steps()["Run tests"])


def test_overlapping_runs_wait_instead_of_cancelling():
    """예비 예약(같은 날 두 번째 실행)이 본 발송과 겹치면 기다렸다가 같은 날 가드로 건너뛴다 — 진행 중인 발송을 끊지 않는다."""
    c = _workflow()["concurrency"]
    assert c["group"] and c["cancel-in-progress"] is False


def _if_holds(expr: str, *, success: bool, send: str, dry_run: bool) -> bool:
    """스텝의 if 식을 상황별로 풀어 본다 — 이 워크플로가 쓰는 꼴만(success()·failure()·steps.send.outcome·
    inputs.dry_run·&&·||·!·괄호). 다른 꼴이 들어오면 풀지 않고 멈춘다. 깃허브는 !를 ==보다 먼저 묶고 파이썬
    not은 나중에 묶으므로, '!이름 == 값' 꼴은 받지 않는다(&&가 ||보다 먼저 묶이는 것은 둘이 같다)."""
    assert not re.search(r"!\s*[\w.()]+\s*[=!]=", expr), f"풀 수 없는 식: {expr}"
    py = (expr.replace("success()", " SUCCESS ").replace("failure()", " FAILURE ")
              .replace("steps.send.outcome", " SEND ").replace("inputs.dry_run", " DRY ")
              .replace("&&", " and ").replace("||", " or "))
    py = re.sub(r"!(?!=)", " not ", py)
    assert re.fullmatch(r"[\sA-Za-z()'=]*", py), f"풀 수 없는 식: {expr}"
    return bool(eval(py, {"__builtins__": {}},
                     {"SUCCESS": success, "FAILURE": not success, "SEND": send, "DRY": dry_run}))


def test_commit_state_also_runs_when_the_send_step_failed():
    """본인(맨 위 사람)이 실패하면 Send 스텝이 실패한다. 그래도 같은 실행에서 보낸 사람의 state는 커밋해야
    07:17 예비 예약이 그 사람에게 한 번 더 보내지 않는다. 테스트·명식 점검에서 멈춘 날(send가 skipped)과
    dry_run은 커밋하지 않는다. 식에 success()가 있어야 깃허브가 기본 success()를 앞에 덧붙이지 않는다."""
    cond = _steps()["Commit state"]["if"]
    assert "success()" in cond
    cases = [
        (dict(success=True, send="success", dry_run=False), True),     # 모두 보냄(종료 2도 Send가 흡수해 여기)
        (dict(success=False, send="failure", dry_run=False), True),    # 본인 실패(종료 1) — 보낸 가족의 state는 커밋
        (dict(success=False, send="skipped", dry_run=False), False),   # 테스트·명식 점검에서 멈춘 날
        (dict(success=True, send="success", dry_run=True), False),     # dry_run은 저장하지 않는다
        (dict(success=False, send="failure", dry_run=True), False),
    ]
    for ctx, want in cases:
        assert _if_holds(cond, **ctx) is want, (ctx, cond)


def test_workflow_can_commit_state():
    assert _workflow()["permissions"]["contents"] == "write"


def test_repo_write_token_reaches_only_the_commit_step():
    """쓰기 권한은 job 단위라 스텝으로 못 좁힌다 — 대신 checkout이 토큰을 git 설정에 남기지 않게 하고(pip·pytest·
    발송 스텝의 코드가 못 읽게) 커밋 스텝에만 env로 준다."""
    steps = _workflow()["jobs"]["send"]["steps"]
    checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["persist-credentials"] is False
    holders = [s.get("name") for s in steps if "github.token" in str(s) or "GITHUB_TOKEN" in str(s)]
    assert holders == ["Commit state"]
    commit = _steps()["Commit state"]
    assert commit["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert "$GH_TOKEN" in commit["run"] or "${GH_TOKEN}" in commit["run"]


def test_shell_steps_parse():
    """손댈 수 없는 실제 실행 전에 스텝 스크립트의 셸 문법만이라도 본다(bash가 있을 때)."""
    import shutil
    import subprocess

    bash = shutil.which("bash")
    if not bash:
        import pytest
        pytest.skip("bash 없음")
    for s in _workflow()["jobs"]["send"]["steps"]:
        if "run" not in s:
            continue
        script = re.sub(r"\$\{\{[^}]*\}\}", "X", s["run"])          # 워크플로 식은 셸 문법이 아니다
        r = subprocess.run([bash, "-n"], input=script, capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, (s.get("name"), r.stderr)


def test_gitignore_keeps_secrets_build_files_and_ephemeris_out():
    lines = {ln.strip() for ln in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
    for need in (".env", ".env.*", "!.env.example", "__pycache__/", "*.pyc", ".pytest_cache/", ".venv/", "*.bsp"):
        assert need in lines, need
