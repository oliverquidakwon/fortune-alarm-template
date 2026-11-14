# -*- coding: utf-8 -*-
"""interpret 회귀 테스트 — 프롬프트 조립·톤 규칙·호칭·SDK 계약. Claude를 실제로 부르지 않는다.

시스템 프롬프트(interpret.SYSTEM)의 말투를 고치면 아래 '톤 규칙' 테스트의 문구도 같이 고친다.
그 테스트들은 단정 금지·지어내기 금지 같은 안전 규칙이 실수로 지워지는 것을 막는다.
"""
import re
from datetime import date

import pytest

import astro_core
import chart_factory
import interpret
import saju_core
from examples import haneul_birth


def _layers(chart, d=date(2026, 7, 6)):
    return saju_core.four_layers(d, chart)


def _prompt(chart, layers):
    return interpret.build_prompt(layers, interpret.profile_for(chart))


# ── 프롬프트 데이터 블록 ─────────────────────────────────────

def test_prompt_without_recent_has_no_block(haneul):
    assert "최근 발송문" not in _prompt(haneul, _layers(haneul))


def test_prompt_injects_recent_block(haneul):
    L = _layers(haneul)
    L["recent"] = [{"date": "2026-07-04", "text": "그제 발송문 본문"},
                   {"date": "2026-07-05", "text": "어제 발송문 본문"}]
    p = _prompt(haneul, L)
    assert "===== 최근 발송문 (반복 회피 대조용) =====" in p
    assert "--- 2026-07-05 ---" in p and "어제 발송문 본문" in p
    assert "--- 2026-07-04 ---" in p and "그제 발송문 본문" in p
    assert "문장 틀과 은유" in p            # 말미 반복 회피 지시


def test_prompt_injects_the_persons_natal_brief(haneul):
    p = _prompt(haneul, _layers(haneul))
    assert "===== 명식 요약(근거) =====" in p
    assert haneul.NATAL_BRIEF in p


def test_prompt_labels_aspect_persistence(haneul):
    d = date(2026, 6, 1)                    # 하늘: 달 각 1건만 새로 들어오고 나머지는 지속
    L = _layers(haneul, d)
    L["astro"] = astro_core.today_layer(d, chart=haneul)
    p = _prompt(haneul, L)
    assert "[오늘 새 각]" in p and "[어제부터 지속]" in p


def test_prompt_includes_interactions_line(haneul):
    # 2026-08-03 己酉일: 酉-卯 충(원국 월지) → 데이터 줄은 한글로
    p = _prompt(haneul, _layers(haneul, date(2026, 8, 3)))
    assert "특수 관계" in p
    assert "- 지지충: 유-묘 (원국 월지와)" in p
    assert "酉" not in p


def test_prompt_includes_term_change_line(haneul):
    p = _prompt(haneul, _layers(haneul, date(2026, 7, 7)))    # 소서 10:56, 을미로
    assert "절기 전환" in p and "을미" in p and "10:5" in p


def test_prompt_no_interaction_line_when_absent(haneul):
    # 2026-07-05 庚辰일: 하늘 원국과 충합 없음 → 줄 자체가 없어야
    assert "특수 관계" not in _prompt(haneul, _layers(haneul, date(2026, 7, 5)))


def test_prompt_includes_background_interactions(haneul):
    p = _prompt(haneul, _layers(haneul, date(2026, 7, 19)))
    assert "배경 충합" in p
    assert "- 10년 배경(대운): 지지충 해-사 (원국 시지와) — 이 기간 내내 지속" in p
    assert "- 이달 배경(월운): 지지충 미-축 (원국 일지와) — 이 기간 내내 지속" in p
    assert "亥" not in p and "巳" not in p


def test_prompt_retro_until_date(haneul):
    d = date(2026, 7, 19)                   # 수성 역행 중, 7/24 순행 전환
    L = _layers(haneul, d)
    L["astro"] = astro_core.today_layer(d, chart=haneul)
    assert "7/24부터 순행" in _prompt(haneul, L)


def test_prompt_uses_each_persons_day_master(haneul, bada_a):
    assert "(일간은 기토." in _prompt(haneul, _layers(haneul))
    pb = _prompt(bada_a, _layers(bada_a))
    assert "(일간은 을목." in pb and "기토" not in pb


def test_prompt_has_no_hanja(haneul, bada_b):
    d = date(2026, 8, 3)                    # 월요일 — 주간 블록까지 넣어 본다
    for ch in (haneul, bada_b):
        L = _layers(ch, d)
        L["astro"] = astro_core.today_layer(d, chart=ch)
        L["weekly"] = saju_core.week_outlook(d, ch)
        assert not re.findall(r"[一-鿿]", _prompt(ch, L))


def test_ziwei_block_absent(haneul):
    L = _layers(haneul, date(2026, 8, 3))
    assert L["ziwei"] is None
    assert "[자미두수]" not in _prompt(haneul, L)


def test_prompt_binds_comparison_ban_to_yesterday_line(haneul):
    p = _prompt(haneul, _layers(haneul))
    line = next(ln for ln in p.splitlines() if ln.startswith("- 어제 일진"))
    assert "문형 금지" in line


def test_domain_strengths_pure():
    L = {"day": {"gan_sipsung": "비견", "branch_sipsung": "상관"},
         "astro": {"aspects": [{"t": "달", "n": "수성", "persists": False},
                               {"t": "화성", "n": "천왕성", "persists": True}]}}
    assert interpret.domain_strengths(L) == {"돈": True, "일": True, "건강": False, "연애": True}


def test_domain_strengths_quiet_day():
    L = {"day": {"gan_sipsung": "정인", "branch_sipsung": "편인"},
         "astro": {"aspects": [{"t": "목성", "n": "태양", "persists": True}]}}
    assert interpret.domain_strengths(L) == {"돈": False, "일": False, "건강": True, "연애": False}


def test_prompt_includes_domain_strength_block(haneul):
    p = _prompt(haneul, _layers(haneul, date(2026, 7, 19)))    # 甲午일: 정관(일)·편인(건강)
    assert "- 오늘 데이터가 실제로 가리키는 영역: 건강·일" in p
    assert "약한 영역(돈·연애)" in p and "지어내지" in p


def test_prompt_forbids_monthly_header_on_non_first_day(haneul):
    d = date(2026, 8, 17)                   # 월요일, 1일 아님
    L = _layers(haneul, d)
    L["weekly"] = saju_core.week_outlook(d, haneul)
    p = _prompt(haneul, L)
    assert "[헤더 금지] 오늘은 매월 1일이 아니다" in p
    assert "[이번 주 7일 일진" in p
    assert "[헤더 금지] 오늘은 월요일이 아니다" not in p


def test_prompt_header_bans_follow_the_date(haneul):
    d = date(2026, 9, 1)                    # 매월 1일(화요일)
    L = _layers(haneul, d)
    L["monthly"] = saju_core.month_outlook(d, haneul)
    p = _prompt(haneul, L)
    assert "[이번 달 흐름 — 월간 섹션용" in p
    assert "[헤더 금지] 오늘은 매월 1일이 아니다" not in p
    assert "[헤더 금지] 오늘은 월요일이 아니다" in p


def test_date_line_is_built_by_code():
    assert interpret.date_line(date(2026, 11, 14)) == "11월 14일 토요일"
    assert interpret.date_line(date(2026, 6, 1)) == "6월 1일 월요일"


def test_prompt_hands_over_the_exact_date_line(haneul):
    p = _prompt(haneul, _layers(haneul, date(2026, 11, 14)))
    assert "맨 윗줄(날짜 줄)은 이 글자 그대로: 11월 14일 토요일" in p


def test_prompt_counts_the_year_of_the_current_daewoon(haneul, bada_a):
    """대운이 시작한 해와 올해가 그 몇 년째인지를 코드가 세어 준다 — 해석문이 2019–2028 대운에 '10년째'라고
    스스로 센 사례가 있었다(바다 출력). 바다는 대운수가 반올림 경계라 1년 앞뒤로 갈릴 수 있다는 말도 붙인다."""
    p = _prompt(bada_a, _layers(bada_a, date(2026, 8, 3)))
    assert ("- 지금 대운: 2019년에 시작해 2028년까지(10년) — 올해 2026년은 그 8년째다. "
            "몇 년째인지는 이 숫자를 그대로 써라(직접 세지 마라)"
            " · 대운수 반올림 경계라 시작 연도가 1년 앞뒤로 갈릴 수 있다") in p
    h = _prompt(haneul, _layers(haneul, date(2026, 8, 3)))
    assert "- 지금 대운: 2025년에 시작해 2034년까지(10년) — 올해 2026년은 그 2년째다." in h
    assert "반올림 경계" not in h


def test_no_daewoon_year_line_outside_the_daewoon_table(haneul):
    p = _prompt(haneul, _layers(haneul, date(1993, 8, 3)))       # 첫 대운(1995) 전
    assert "- 대운: (범위 밖)" in p and "지금 대운:" not in p


def test_system_prompt_has_no_example_dates():
    """지시문에 예시 날짜('6월 28일 일요일')가 있으면 모델이 끌어다 쓴다 — 실호출 첫 줄이
    '6월이 아니라 11월 14일 토요일'로 나왔다. 날짜는 데이터 블록의 코드 값만 준다."""
    assert not re.findall(r"\d{1,2}월 \d{1,2}일", interpret.SYSTEM)


def test_prompt_includes_last_same_ganji_day(haneul):
    d = date(2026, 8, 30)                   # 60갑자 — 60일 전이 정확히 같은 일진
    assert saju_core.day_ganji(d) == saju_core.day_ganji(date(2026, 7, 1))
    assert "같은 일진이 마지막으로 온 날: 7월 1일" in _prompt(haneul, _layers(haneul, d))


# ── 톤 규칙 (시스템 프롬프트) ────────────────────────────────

def test_system_prompt_bans_repetition_frames():
    s = interpret.SYSTEM
    assert "반복 금지" in s and "어제는 ~였다면" in s and "같은 방향" in s and "마크다운" in s


def test_system_headline_domain_and_tail_rules():
    s = interpret.SYSTEM
    assert "오늘 한 줄" in s and "돈(투자·지출)" in s
    assert "순행" in s and "이어지는 주의" in s and "배경 충합" in s


def test_system_requires_four_domain_section():
    s = interpret.SYSTEM
    assert "【돈·연애·건강·일】" in s and "연애 —" in s and "건강 —" in s
    assert "상대 유무를 단정" in s and "의학적 단정" in s


def test_system_forbids_prophecy_and_invented_life():
    s = interpret.SYSTEM
    assert "미래 사건 예언" in s and "구체 금액·특정 사건·확률 단정 금지" in s
    assert "직업·회사·가족·과거·재무 상황은 주어지지 않았다" in s


def test_system_bans_year_superlative():
    assert "올 들어 처음" in interpret.SYSTEM


def test_system_casual_haeyo_tone():
    s = interpret.SYSTEM
    assert "해요체" in s and "합쇼체" in s
    assert "존댓말" not in s


def test_system_length_guidance():
    s = interpret.SYSTEM
    assert "1,400~2,000자" in s and "800~1,200자" in s


def test_system_direct_wording_scene_and_device_rotation():
    s = interpret.SYSTEM
    assert "돌려 말하지 마라" in s and "장면" in s
    assert "오늘 하지 말 것 딱 하나" in s and "같은 일진이 마지막으로 온 날" in s
    assert "이틀 연속" in s and "최대 한 개" in s


def test_retry_block_lists_violations():
    b = interpret.retry_block(["비교 틀: 어제~였다면", "수렴 선언: 두 신호"])
    assert "재작성" in b and "비교 틀: 어제~였다면" in b and "수렴 선언: 두 신호" in b


def test_retry_block_empty_when_no_violations():
    assert interpret.retry_block([]) == ""


# ── 호칭 ────────────────────────────────────────────────────

def test_no_honorific_means_no_address(haneul):
    s = interpret.profile_for(haneul)["system"]
    assert "호칭은 쓰지 마라" in s


def test_honorific_is_per_person():
    s = interpret.profile_for(chart_factory.build(haneul_birth(honorific="하늘님")))["system"]
    assert "'하늘님'" in s and "호칭은 쓰지 마라" not in s


def test_honorific_swap_fails_loud_on_drift(monkeypatch):
    """호칭 줄이 사라진 프롬프트에서 조용히 넘어가면 호칭 지시가 빠진 채 나간다 — 죽어야 한다."""
    monkeypatch.setattr(interpret, "SYSTEM", "호칭 줄이 없는 프롬프트")
    with pytest.raises(RuntimeError):
        interpret.profile_for(chart_factory.build(haneul_birth(honorific="하늘님")))


# ── Claude 호출 계약 (SDK를 실제로 부르지 않는다) ───────────────

def test_installed_sdk_accepts_create_kwargs():
    """우리가 messages.create()에 넘기는 키가 설치된 SDK 시그니처에 전부 있어야 한다.
    SDK 메이저가 바뀌어 인자가 빠지면 아침 생성 단계가 아니라 이 테스트에서 먼저 터진다."""
    import inspect
    anthropic = pytest.importorskip("anthropic")
    sig = inspect.signature(anthropic.resources.messages.Messages.create)
    missing = [k for k in interpret.CREATE_KWARGS if k not in sig.parameters]
    assert not missing, f"설치된 anthropic {anthropic.__version__}이 받지 않는 인자: {missing}"


def test_create_kwargs_have_no_sampling_params():
    """Sonnet 5는 temperature·top_p·top_k에 400을 돌려준다 — 기본 모델도 이 인자 없이 확인했다."""
    assert not ({"temperature", "top_p", "top_k"} & set(interpret.CREATE_KWARGS))


class _Block:
    def __init__(self, type_, text=""):
        self.type, self.text = type_, text


class _Usage:
    input_tokens, output_tokens, cache_read_input_tokens = 1200, 800, 0


def _fake_client(calls, content=None, stop_reason="end_turn"):
    class _Resp:
        def __init__(self):
            self.content = content or [_Block("thinking", ""), _Block("text", "  오늘 운세 본문  ")]
            self.usage, self.stop_reason = _Usage(), stop_reason

    class _Messages:
        def create(self, **kw):
            calls.append(kw)
            return _Resp()

    class _Client:
        messages = _Messages()

    return _Client()


def test_generate_sends_chosen_model_system_and_prompt(monkeypatch, haneul):
    calls = []
    monkeypatch.setattr(interpret, "_client", lambda: _fake_client(calls))
    prof = interpret.profile_for(haneul)
    L = _layers(haneul)
    assert interpret.generate(L, model="claude-test-model", profile=prof) == "오늘 운세 본문"
    kw = calls[0]
    assert kw["model"] == "claude-test-model"
    assert kw["system"] == prof["system"]
    assert kw["messages"] == [{"role": "user", "content": interpret.build_prompt(L, prof)}]
    assert kw["max_tokens"] == interpret.CREATE_KWARGS["max_tokens"]
    assert not ({"temperature", "top_p", "top_k"} & set(kw))


def test_generate_appends_retry_note(monkeypatch, haneul):
    calls = []
    monkeypatch.setattr(interpret, "_client", lambda: _fake_client(calls))
    interpret.generate(_layers(haneul), retry_note=["A 위반"], profile=interpret.profile_for(haneul))
    assert calls[0]["messages"][0]["content"].endswith(interpret.retry_block(["A 위반"]))


def test_generate_keeps_why_the_reply_ended(monkeypatch, haneul):
    """분량 상한(max_tokens)에서 끊겼는지·거절로 끝났는지를 본문과 함께 넘긴다 — 발송 쪽이 끊긴 글을 보내지 않게."""
    for reason in ("max_tokens", "refusal", "end_turn"):
        monkeypatch.setattr(interpret, "_client", lambda r=reason: _fake_client([], stop_reason=r))
        reply = interpret.generate(_layers(haneul), profile=interpret.profile_for(haneul))
        assert reply == "오늘 운세 본문" and reply.stop_reason == reason


def test_generate_logs_token_usage(monkeypatch, haneul, capsys):
    monkeypatch.setattr(interpret, "_client", lambda: _fake_client([]))
    interpret.generate(_layers(haneul), profile=interpret.profile_for(haneul))
    assert "[usage] in=1200 out=800 cache_read=0" in capsys.readouterr().out


def test_generate_fails_loud_without_text(monkeypatch, haneul):
    """생각 블록만 오고 본문이 없으면(거절 등) 빈 메시지를 보내지 않고 크게 죽는다."""
    monkeypatch.setattr(interpret, "_client",
                        lambda: _fake_client([], content=[_Block("thinking", "")]))
    with pytest.raises(RuntimeError):
        interpret.generate(_layers(haneul), profile=interpret.profile_for(haneul))


def test_client_needs_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError) as e:
        interpret._client()
    assert "ANTHROPIC_API_KEY" in str(e.value)


def test_client_strips_the_key_and_bounds_each_call(monkeypatch):
    """키에 딸려 온 앞뒤 공백·줄바꿈은 지운다(그대로면 헤더 오류 문장에 키가 실린다). 호출마다 시간 제한과 재시도 수를
    정해 둔다 — 멈춘 호출이 작업 시간 제한(30분)에 걸려 취소되기 전에 실패로 끝나야 실패 알림 스텝이 돈다."""
    anthropic = pytest.importorskip("anthropic")
    seen = {}
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: seen.update(kw) or object())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "  sk-ant-" + "x" * 24 + "\n")
    interpret._client()
    assert seen["api_key"] == "sk-ant-" + "x" * 24
    assert seen["timeout"] == interpret.CLIENT_TIMEOUT_S and seen["max_retries"] == interpret.CLIENT_MAX_RETRIES
    worst = (1 + interpret.CLIENT_MAX_RETRIES) * interpret.CLIENT_TIMEOUT_S
    assert 60 <= interpret.CLIENT_TIMEOUT_S and worst <= 10 * 60       # 한 사람의 멈춘 호출이 최악 10분 안
