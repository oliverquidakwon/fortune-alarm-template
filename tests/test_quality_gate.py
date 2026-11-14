# -*- coding: utf-8 -*-
"""
quality_gate 검증 — 발송 직전 결정론 검사. 프롬프트 지시만으로 안 잡힌 굳은 틀(어제 비교 틀·
수렴 선언·별자리 보고 오프닝)과 용어 누출·서식 기호·구조 결손을 코드로 잡는다.
위반 문장 코퍼스는 생성문에서 되풀이되기 쉬운 꼴을 모았다.
"""
import quality_gate as qg
from examples import EVIDENCE_DATE_LINE, EVIDENCE_WRONG_DATE_LINE


def _msg(saju="오늘은 말과 글로 꺼내는 힘이 든든한 기반 위에 올라오는 날이에요. "
              "머릿속에서 익은 판단 하나를 골라 상대에게 직접 건네보세요.",
         astro="첫인상이 유난히 잘 전달되는 흐름이에요. "
               "처음 만나는 사람과의 자리도 평소보다 부드럽게 풀려요.",
         domains="돈 — 큰 결정보다 지출 점검 정도가 어울리는 날이에요.\n"
                 "연애 — 가까운 사람에게 먼저 안부를 건네면 반응이 따뜻하게 돌아와요.\n"
                 "건강 — 머리 오래 쓰는 일 사이에 짧은 산책 한 번 끼워 넣으면 좋아요.\n"
                 "일 — 미뤄둔 제안을 오늘 꺼내면 말이 잘 닿아요.",
         summary="오늘은 사람 쪽에 힘을 쓰는 하루예요. "
                 "협업 제안이든 안부든 하나만 골라 직접 건네보세요.",
         headline="오늘 한 줄: 꺼낼 것 하나 골라 사람에게 건네보기 좋은 날이에요."):
    return (f"7월 27일 월요일\n{headline}\n\n"
            f"【오늘의 사주】\n{saju}\n\n"
            f"【오늘의 별자리】\n{astro}\n\n"
            f"【돈·연애·건강·일】\n{domains}\n\n"
            f"【종합】\n{summary}\n\n"
            "건넨 말은 오늘 안에 어떤 식으로든 돌아와요.")


# ── 통과 케이스 ──────────────────────────────────────────────
def test_clean_message_passes():
    assert qg.check(_msg()) == []


def test_sanggwan_eopsi_not_flagged():
    # '상관없이'는 십성 '상관'이 아니다
    assert qg.check(_msg(saju="분량은 상관없이 오늘 기운의 핵심만 보면 됩니다. "
                              "판단 하나를 골라 건네보세요.")) == []


def test_yesterday_as_material_not_flagged():
    # '어제'를 재료로 쓰는 건 허용 — 금지는 '~였다면/~였는데' 비교 문형
    assert qg.check(_msg(saju="어제 정리해둔 판단을 오늘 밖으로 보내기 좋은 날입니다. "
                              "하나만 골라 건네보세요.")) == []


# ── 굳은 틀 ─────────────────────────────────────────────────
def test_yesterday_comparison_frame_flagged():
    v = qg.check(_msg(saju="어제 일진이 기회를 포착하고 내 안에서 정리하는 성질이었다면, "
                           "오늘은 그 성질이 완전히 다른 것으로 교체됩니다."))
    assert any("비교 틀" in x for x in v)


def test_yesterday_comparison_frame_midbody_flagged():
    # 첫 문장이 아니라 본문 중간에 나온 비교 틀도 잡는다
    v = qg.check(_msg(saju="이번 달 기운이 오늘 하루에 압축되는 날입니다. "
                           "어제 일진이 팽팽한 구성이었다면, 오늘은 그 긴장이 풀립니다."))
    assert any("비교 틀" in x for x in v)


def test_convergence_declaration_flagged():
    v = qg.check(_msg(summary="두 신호가 같은 방향을 가리키는 만큼, 오늘 하루는 "
                              "사람 영역에서 쓰는 것이 가장 자연스럽습니다."))
    assert any("수렴 선언" in x for x in v)


def test_convergence_variants_flagged():
    v1 = qg.check(_msg(summary="꺼내는 힘과 첫인상이 같은 방향을 향하고 있으니, "
                               "오늘 제안을 직접 건네보세요."))
    assert any("수렴 선언" in x for x in v1)
    v2 = qg.check(_msg(summary="오늘 기운이 공통으로 가리키는 곳은 일 영역입니다. "
                               "제안 하나를 꺼내보세요."))
    assert any("수렴 선언" in x for x in v2)


def test_summary_parallel_recap_flagged():
    v = qg.check(_msg(summary="사주는 꺼내는 힘을 가리키고, 별자리는 전달이 잘 되는 "
                              "결을 말합니다. 오늘은 사람에게 쓰세요."))
    assert any("병렬 요약" in x for x in v)


def test_astro_opening_frame_flagged():
    v = qg.check(_msg(astro="오늘 새로 들어온 각은 달이 타고난 가치 감각과 긁히는 "
                            "자극을 보내는 것입니다. 오후에 갸우뚱할 수 있습니다."))
    assert any("별자리 오프닝" in x for x in v)


def test_astro_aspect_later_not_flagged():
    # 각 언급 자체는 허용 — 첫 문장 보고 틀만 금지
    assert qg.check(_msg(astro="사람을 만나는 자리가 부드럽게 풀리는 하루입니다. "
                               "오늘 새로 들어온 각도 그 흐름에 힘을 보탭니다.")) == []


def test_year_superlative_flagged():
    v = qg.check(_msg(saju="올 들어 처음으로 내 안을 정리하는 힘이 앞서는 날입니다. "
                           "분류와 점검에 시간을 쓰면 좋습니다."))
    assert any("최상급" in x for x in v)


# ── 용어·표기 누출 ───────────────────────────────────────────
def test_everyday_words_that_contain_a_term_are_not_flagged():
    """'상관 없이'(띄어 씀)·'상관하지'·'식상하게'·'비겁하게'는 평범한 낱말이다 — 전문용어로 잡으면 쓸데없이 재생성한다."""
    for phrase in ("결과와 상관 없이 하나만 해 보세요.", "남이 뭐라든 상관하지 않아도 돼요.",
                   "같은 말을 반복하면 식상하게 들릴 수 있어요.", "피하는 건 비겁하게 느껴질 수 있어요."):
        v = qg.check(_msg(saju="오늘은 꺼내는 힘이 든든한 날이에요. " + phrase))
        assert not any("전문용어" in x for x in v), (phrase, v)


def test_the_same_terms_used_as_jargon_are_still_flagged():
    for phrase, term in (("오늘은 상관이 강하게 들어오는 날이에요.", "상관"),
                         ("식상이 살아나는 흐름이에요.", "식상"), ("비겁이 겹치는 날이에요.", "비겁")):
        v = qg.check(_msg(saju="오늘은 꺼내는 힘이 든든한 날이에요. " + phrase))
        assert any("전문용어" in x and term in x for x in v), (phrase, v)


def test_autofix_keeps_a_space_where_an_emoji_sat_between_words():
    """이모지를 지운 자리의 앞뒤 낱말이 붙으면 안 된다('좋아요 ✨오늘은' → '좋아요오늘은'이 아니라 '좋아요 오늘은')."""
    assert qg.autofix("좋아요 ✨오늘은 쉬어요") == "좋아요 오늘은 쉬어요"
    assert qg.autofix("좋아요✨오늘은 쉬어요") == "좋아요 오늘은 쉬어요"
    assert qg.autofix("✨오늘은 쉬어요\n끝이에요 🌙") == "오늘은 쉬어요\n끝이에요"


def test_sipsung_term_flagged():
    v = qg.check(_msg(saju="이번 달과 오늘이 똑같이 편재·편인의 조합으로 겹치는 날입니다. "
                           "기회를 알아보되 정리에 무게를 두세요."))
    assert sum(1 for x in v if "전문용어" in x) == 1  # 묶어서 1건 보고


def test_hanja_flagged():
    v = qg.check(_msg(saju="오늘 일진은 壬寅입니다. 꺼내는 힘이 살아 있습니다."))
    assert any("한자" in x for x in v)


def test_emoji_flagged():
    v = qg.check(_msg(headline="오늘 한 줄: 꺼내기 좋은 날입니다 🔮"))
    assert any("이모지" in x for x in v)


def test_markdown_flagged():
    v = qg.check(_msg(saju="**중요** 오늘은 꺼내는 날입니다. 하나만 골라 건네세요."))
    assert any("마크다운" in x for x in v)


# ── 구조 (필수 섹션·4영역) ───────────────────────────────────
def test_missing_domain_section_flagged():
    v = qg.check(_msg().replace("【돈·연애·건강·일】", "【영역】"))
    assert any("돈·연애·건강·일" in x for x in v)


def test_missing_one_domain_line_flagged():
    m = _msg(domains="돈 — 지출 점검 정도가 어울립니다.\n"
                     "건강 — 짧은 산책이 좋습니다.\n"
                     "일 — 제안을 꺼내기 좋습니다.")
    assert any("연애" in x for x in qg.check(m))


def test_domain_hyphen_variants_accepted():
    m = _msg(domains="돈 - 지출 점검 정도가 어울려요.\n"
                     "연애 - 안부를 건네보세요.\n"
                     "건강 - 짧은 산책이 좋아요.\n"
                     "일 - 제안을 꺼내기 좋은 날이에요.")
    assert qg.check(m) == []


def test_missing_headline_flagged():
    v = qg.check(_msg().replace("오늘 한 줄: ", ""))
    assert any("오늘 한 줄" in x for x in v)


# ── 재생성 선택 ──────────────────────────────────────────────
def test_pick_better_fewer_wins():
    assert qg.pick_better("m1", ["a", "b"], "m2", ["c"]) == ("m2", ["c"])
    assert qg.pick_better("m1", [], "m2", ["c"]) == ("m1", [])


def test_pick_better_tie_prefers_retry():
    m, _ = qg.pick_better("m1", ["a"], "m2", ["b"])   # 동률이면 피드백을 반영한 2차본
    assert m == "m2"


# ── 캐주얼 해요체 ────────────────────────────────────────────
def test_hapsyo_style_flagged():
    # 합쇼체(~니다 종결) 3건 이상 = 보고서 톤 회귀
    v = qg.check(_msg(saju="오늘은 꺼내는 힘이 살아 있는 날입니다. 기반도 든든합니다. "
                           "판단 하나를 골라 건네보시기 바랍니다."))
    assert any("합쇼체" in x for x in v)


def test_two_hapsyo_allowed():
    v = qg.check(_msg(saju="오늘은 꺼내는 힘이 사는 날입니다. 판단 하나만 골라 건네보세요. "
                           "타이밍은 오전이 좋습니다."))
    assert v == []


# ── 무단 헤더 섹션 ───────────────────────────────────────────
_W = "【이번 주 흐름】" + chr(10) + "전반 조용, 후반 분주한 주예요." + chr(10) + chr(10)
_M = "【이번 달 흐름】" + chr(10) + "자리 다지는 달이에요." + chr(10) + chr(10)


def _with_headers(pre):
    head, rest = _msg().split(chr(10) + chr(10), 1)
    return head + chr(10) + chr(10) + pre + rest


def test_unexpected_monthly_header_flagged():
    v = qg.check(_with_headers(_M + _W), headers={"monthly": False, "weekly": True})
    assert any("무단 헤더" in x and "이번 달" in x for x in v)


def test_unexpected_weekly_header_flagged():
    v = qg.check(_with_headers(_W), headers={"monthly": False, "weekly": False})
    assert any("무단 헤더" in x and "이번 주" in x for x in v)


def test_expected_headers_pass():
    assert qg.check(_with_headers(_M + _W), headers={"monthly": True, "weekly": True}) == []


def test_expected_weekly_missing_flagged():
    v = qg.check(_msg(), headers={"monthly": False, "weekly": True})
    assert any("누락" in x and "이번 주" in x for x in v)


def test_headers_none_skips_check():
    # 날짜 기대치 없이 부르는 호출(지난 발송분 다시 검사하기 등)에서는 판정하지 않는다
    assert qg.check(_with_headers(_M), headers=None) == []


# ── 프로파일 — 이 템플릿은 모든 사람에게 EXTERNAL_PROFILE(반말 차단 포함)을 쓴다 ──
_BANMAL = ("오늘 한 줄: 시험\n【오늘의 사주】\n기운이 좋다.\n【오늘의 별자리】\n무난해요.\n"
           "【돈·연애·건강·일】\n돈 — 좋아요\n연애 — 좋아요\n건강 — 좋아요\n일 — 좋아요\n"
           "【종합】\n오늘은 쉬어요.")


def test_banmal_blocked_with_external_profile():
    assert not any("반말" in v for v in qg.check(_BANMAL, qg.DEFAULT_PROFILE))
    assert any("반말" in v for v in qg.check(_BANMAL, qg.EXTERNAL_PROFILE))


def test_haeyo_text_passes_banmal_gate():
    ok = _BANMAL.replace("기운이 좋다.", "기운이 좋아요.")
    assert not any("반말" in v for v in qg.check(ok, qg.EXTERNAL_PROFILE))


def test_hapsyo_limit_is_profile_driven():
    msg = "합니다. " * 5
    assert any("합쇼체" in v for v in qg.check(msg, qg.DEFAULT_PROFILE))
    assert not any("합쇼체" in v for v in qg.check(msg, {**qg.DEFAULT_PROFILE, "hapsyo_max": 99}))


def test_domains_are_profile_driven():
    msg = _BANMAL.replace("연애 — 좋아요\n", "")
    assert any("영역 줄 누락: 연애" in v for v in qg.check(msg, qg.DEFAULT_PROFILE))
    slim = {**qg.DEFAULT_PROFILE, "domains": ["돈", "건강", "일"]}
    assert not any("영역 줄 누락" in v for v in qg.check(msg, slim))


# ── 서식 위반 자동 교정 — 재생성(Claude 호출) 대신 문자 제거 ─────
def test_autofix_strips_markdown_and_emoji_and_passes_gate():
    m = _msg(saju="**오늘은** 말과 글로 꺼내는 힘이 든든해요 ✨. `판단` 하나를 골라 건네보세요.")
    v = qg.check(m)
    assert any("마크다운" in x for x in v) and any("이모지" in x for x in v)
    fixed = qg.autofix(m)
    assert qg.check(fixed) == []
    assert "오늘은 말과 글로" in fixed and "든든해요." in fixed and "판단 하나" in fixed


def test_autofix_strips_heading_hash_and_leading_emoji():
    assert qg.autofix("# 오늘 한 줄: 좋아요") == "오늘 한 줄: 좋아요"
    assert qg.autofix("🌙 달이 밝아요") == "달이 밝아요"


def test_autofix_leaves_clean_message_untouched():
    assert qg.autofix(_msg()) == _msg()


def test_autofixable_only_for_format_violations():
    assert qg.autofixable(["마크다운 서식 기호 사용"])
    assert qg.autofixable(["이모지 사용", "전문용어 노출: 하우스"])
    assert not qg.autofixable(["전문용어 노출: 하우스"])
    assert not qg.autofixable([])


# ── 날짜 줄 — 코드가 만든 글자가 정답이다 ─────────────────────
# 실호출 증거: 첫 줄이 '6월이 아니라 11월 14일 토요일'로 나왔는데 예전 게이트를 통과했다(examples.py).
_NO_HEADERS = {"monthly": False, "weekly": False}          # 2026-11-14는 토요일·14일


def test_evidence_wrong_date_line_is_the_only_violation():
    v = qg.check(EVIDENCE_WRONG_DATE_LINE, qg.EXTERNAL_PROFILE, headers=_NO_HEADERS,
                 date_line=EVIDENCE_DATE_LINE)
    assert len(v) == 1 and v[0].startswith("날짜 줄 불일치")


def test_exact_date_line_passes():
    fixed = EVIDENCE_DATE_LINE + EVIDENCE_WRONG_DATE_LINE[EVIDENCE_WRONG_DATE_LINE.index("\n"):]
    assert qg.check(fixed, qg.EXTERNAL_PROFILE, headers=_NO_HEADERS, date_line=EVIDENCE_DATE_LINE) == []


def test_date_line_with_extra_words_is_flagged():
    m = _msg(headline="오늘 한 줄: 꺼낼 것 하나 골라 건네보기 좋은 날이에요.").replace(
        "7월 27일 월요일", "7월 27일 월요일입니다")
    assert any(x.startswith("날짜 줄") for x in qg.check(m, date_line="7월 27일 월요일"))


def test_date_line_check_is_off_without_an_expected_value():
    """날짜를 모르는 호출(지난 발송분 다시 검사하기 등)에서는 판정하지 않는다."""
    assert not any(x.startswith("날짜 줄") for x in qg.check(EVIDENCE_WRONG_DATE_LINE, qg.EXTERNAL_PROFILE))


def test_date_line_violation_is_autofixable():
    v = qg.check(EVIDENCE_WRONG_DATE_LINE, qg.EXTERNAL_PROFILE, date_line=EVIDENCE_DATE_LINE)
    assert qg.autofixable(v)


def test_autofix_puts_the_code_date_line_back_and_keeps_the_rest():
    fixed = qg.autofix(EVIDENCE_WRONG_DATE_LINE, date_line=EVIDENCE_DATE_LINE)
    assert fixed.split("\n")[0] == EVIDENCE_DATE_LINE
    assert "6월이 아니라" not in fixed
    assert fixed.split("\n", 1)[1] == EVIDENCE_WRONG_DATE_LINE.split("\n", 1)[1]   # 나머지는 한 글자도 그대로
    assert qg.check(fixed, qg.EXTERNAL_PROFILE, headers=_NO_HEADERS, date_line=EVIDENCE_DATE_LINE) == []


def test_autofix_inserts_a_missing_date_line_above_the_headline():
    no_date = EVIDENCE_WRONG_DATE_LINE.split("\n", 2)[2]          # '오늘 한 줄:'부터 시작
    fixed = qg.autofix(no_date, date_line=EVIDENCE_DATE_LINE)
    lines = fixed.split("\n")
    assert lines[0] == EVIDENCE_DATE_LINE and lines[1].startswith("오늘 한 줄:")


def test_autofix_does_not_guess_when_the_structure_is_unexpected():
    """첫 줄 다음이 '오늘 한 줄'이 아니면 첫 줄이 날짜 줄인지 알 수 없다 — 지우지 않고 재생성에 맡긴다."""
    odd = "오늘은 조용히 쉬어 가요.\n본문이 바로 시작돼요.\n" + EVIDENCE_WRONG_DATE_LINE.split("\n", 2)[2]
    assert qg.autofix(odd, date_line=EVIDENCE_DATE_LINE).split("\n")[0] == "오늘은 조용히 쉬어 가요."
    assert any(x.startswith("날짜 줄") for x in qg.check(odd, date_line=EVIDENCE_DATE_LINE))


def test_autofix_without_date_line_leaves_the_first_line_alone():
    assert qg.autofix(EVIDENCE_WRONG_DATE_LINE).split("\n")[0] == "6월이 아니라 11월 14일 토요일"
