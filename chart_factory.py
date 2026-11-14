# -*- coding: utf-8 -*-
"""
BirthData → 명식 모듈 대체물(chart).

saju_core·astro_core·interpret는 chart를 '모듈처럼 속성을 가진 무언가'로만 쓴다
(NATAL·DAY_MASTER·current_daewoon·NATAL_ASTRO·NATAL_BRIEF 등). 그래서 사람마다
파이썬 파일을 손으로 만들 필요가 없고, me.yaml의 출생정보 한 줄에서 만들어 내면 된다.

검증: tests/test_chart_factory.py가 예시 인물 하늘·바다의 출생정보로 만든 chart를
고정해 둔 계산값과 대조한다. 팩토리가 그 값을 재현하지 못하면 실패한다.
"""
import saju_core as sc
from birth import (BirthData, daewoon, elements, natal_astro, natal_brief,
                   pillar_candidates, true_solar_time, utc_offset, warnings_for)

_SIGN_OF = lambda s: s.split()[0]      # noqa: E731  "물고기 24°" → "물고기"


class Chart:
    """명식 상수 묶음. saju_core·astro_core·interpret가 읽는 속성을 제공한다."""

    ZIWEI_ENABLED = False       # 자미두수 명반 포국은 계산·검증 대상이 아니라 제외
    YONGSIN = HEESIN = GUSIN = None   # 강약 판정은 유파가 갈려 확정하지 않는다

    def __init__(self, b: BirthData):
        self.birth = b
        self.key, self.display_name = b.key, b.name
        self.HONORIFIC = b.honorific
        w = b.when
        lat, lon = b.coords
        off, tz_why = utc_offset(w)
        tst, lon_corr, eot = true_solar_time(b)

        day, hour, conv_note = pillar_candidates(b)[b.convention]
        self.NATAL = {
            "year": sc.year_ganji(w.date(), hour_kst=w.hour),
            "month": sc.month_ganji(w.date(), hour_kst=w.hour),
            "day": day,
            "hour": hour,
        }
        self.DAY_MASTER = day[0]
        self.DAY_MASTER_ELEM = sc.GAN_ELEM[self.DAY_MASTER]
        self.DAY_MASTER_YINYANG = "陽" if sc.GAN.index(self.DAY_MASTER) % 2 == 0 else "陰"
        self.BIRTH_YEAR = w.year
        self.ELEMENTS = elements(self.NATAL)

        self.BIRTH = {
            "solar": f"{b.solar} KST",
            "place": f"{b.place} ({lon}E {lat}N)",
            "sex": b.sex,
            "convention": f"{b.convention} — {conv_note}" + (f" ({b.source})" if b.source else ""),
            "true_solar": f"{tst:%H:%M} (경도 {lon_corr:+.1f}분 · 균시차 {eot:+.1f}분)",
            "tz": f"UTC+{off}" + (f" — {tz_why}" if tz_why else ""),
        }

        dw = daewoon(b, self.NATAL["year"][0], self.NATAL["month"])
        self.DAEWOON_RANGES = dw["ranges"]
        self.DAEWOON_INFO = dw

        self.NATAL_ASTRO, self.ASTRO_PRECISE, self.ASTRO_RETRO = natal_astro(b)
        self.HOUSE_SYSTEM = f"Placidus ({b.place} {lat}N {lon}E) — 중간 커스프 미산출"
        self.ASTRO_SUMMARY = self._astro_summary()
        self.NATAL_BRIEF = natal_brief(self.NATAL, self.DAY_MASTER,
                                       self.NATAL_ASTRO, self.DAEWOON_RANGES)
        self.WARNINGS = warnings_for(b)

    # ── 인터페이스 (saju_core가 부르는 메서드) ──────────────
    def current_daewoon(self, year: int):
        for start, end, gj in self.DAEWOON_RANGES:
            if start <= year <= end:
                return gj, None
        return None

    def current_daehan_branch(self, age_se: int):
        return None            # 자미 미보유

    # ── 내부 ────────────────────────────────────────────────
    _LABEL = {"mercury": "수성", "venus": "금성", "mars": "화성", "jupiter": "목성",
              "saturn": "토성", "uranus": "천왕성", "neptune": "해왕성",
              "pluto": "명왕성", "sun": "태양", "moon": "달"}

    def _astro_summary(self) -> str:
        """프롬프트 '출생 핵심' 한 줄. 하우스 번호는 쓰지 않는다(커스프 미산출)."""
        A_ = self.NATAL_ASTRO
        parts = [f"{_SIGN_OF(A_['asc'])} 상승(룰러 {A_['asc_ruler']})",
                 f"달 {_SIGN_OF(A_['moon'])}", f"태양 {_SIGN_OF(A_['sun'])}"]
        # 한 별자리에 3개 이상 모이면 그것이 그 사람 차트의 무게중심이다
        buckets = {}
        for k, v in A_.items():
            if k in self._LABEL:
                buckets.setdefault(_SIGN_OF(v), []).append(self._LABEL[k])
        for sign, planets in buckets.items():
            if len(planets) >= 3:
                parts.append(f"{sign} 밀집({'·'.join(planets)})")
        return "·".join(parts)

    def __repr__(self):
        n = self.NATAL
        return (f"<Chart {self.key} {n['year']}/{n['month']}/{n['day']}/{n['hour']} "
                f"일간 {self.DAY_MASTER}>")


def build(b: BirthData) -> Chart:
    return Chart(b)
