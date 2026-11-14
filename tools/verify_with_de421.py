# -*- coding: utf-8 -*-
"""verify_with_de421 — 이 봇의 트랜짓 계산(pyephem, astro_core.py)을 NASA JPL 천문력 DE421과 대조한다.

선택 도구다(수업 4장 3강 '천문력(DE421)으로 트랜짓 계산하고 검증하기'). 매일 알림에는 필요 없다.
봇은 DE421을 읽지 않는다. 계산은 pyephem(astro_core.transit_longitudes)이 하고, 이 스크립트는 같은 시각·같은 기준의
황경을 skyfield + DE421로 따로 구해 차이를 잰다. 이 템플릿의 astro_core를 import만 한다(바이트코드도 쓰지 않는다).

설치(선택): pip install -r requirements-verify.txt
사용:
  python -X utf8 tools/verify_with_de421.py <UTC 날짜 YYYY-MM-DD> <de421.bsp 경로> [--hour-utc 3] [--retro-scan] [--sun-crossing 도]
    --hour-utc      UTC 시(기본 3 = 낮 12시 KST — astro_core 의 기준 시각 '낮 12시 KST(= 03:00 UT)')
    --retro-scan    그 날짜에 역행인 천체마다 순행 전환일을 astro_core.retro_until 과 DE421(같은 방법: 매일 낮 12시 KST 황경과
                    하루 뒤 비교, 최대 RETRO_SCAN_DAYS 일)로 따로 찾아 같은지 본다 — 다르면 종료 1
    --sun-crossing  태양 겉보기 황경이 그 도수를 지나는 시각을 날짜 앞뒤 하루 안에서 pyephem(astro_core._ecl_lon)과
                    DE421 로 각각 이분법(1초)으로 찾아 KST 로 찍는다 — 차이가 CROSS_TOL_SEC 를 넘으면 종료 1(절기 시각 검산에도 쓴다)

맞춘 기준(astro_core 머리 주석: "지심 겉보기(apparent) 황경, 진분점 of-date"):
  ① astro_core  : transit_longitudes(날짜, hour_kst=hour_utc+9) — 봇이 매일 부르는 함수 그대로.
                  내부는 _ecl_lon = pyephem g_ra/g_dec(겉보기 지심 적경·적위) → epoch=당일 Ecliptic 변환.
  ② DE421       : skyfield earth.at(t).observe(천체).apparent() — 지구 중심, 광행시·광행차·빛 휨 보정한 겉보기 위치를
                  framelib.ecliptic_frame('true ecliptic and equinox of date')의 황경으로 바꾼다.
  천체 대상: 태양·달·수성·금성은 DE421 의 천체 자체, 화성은 커널에 499 가 있으면 천체 자체 아니면 계 질량중심,
            목성·토성은 계 질량중심(DE421 에 행성 자체 구간이 없다 — 스크립트가 커널 목록에서 골라 찍는다).
판정: 7천체의 황경 차이가 모두 TOL_ARCSEC 안이고 역행 표시(하루 뒤 황경이 줄면 역행 — astro_core 와 같은 방법)가
      모두 같으면 통과(종료 0), 하나라도 어긋나면 종료 1. 입력·파일 문제는 종료 2. 파일은 내려받지 않는다.
진단: 기준을 일부러 하나씩 바꾼 DE421 값끼리의 차이(분점·광행차·지심/일심)를 함께 찍어, 기준이 어긋나면 얼마나 벌어지는지 보인다.
"""
import argparse
import os
import statistics
import sys
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 템플릿 폴더(astro_core.py가 있는 곳)

# 허용 오차 — 봇은 각의 오차(orb)를 0.1°(= 6각분 = 360각초) 단위로 반올림해 쓰고, 출생 천궁도는 1° 단위로 쓴다.
# 그 가장 작은 표시 단위의 1/6 인 1각분 안에서 같으면 '봇의 판단에는 같은 값'으로 본다. 실행 전에 정한 값이다.
TOL_ARCSEC = 60.0
# 태양이 한 도수를 지나는 시각(절기 시각)의 두 계산 차이 허용치 — 태양은 1각초를 약 24초에 지나므로 TOL_ARCSEC 에 맞먹는 값.
CROSS_TOL_SEC = 60.0

# astro_core.TRANSIT_BODIES 의 표시명 → DE421 대상 후보(앞의 것이 커널에 있으면 그것을 쓴다)
DE421_TARGETS = {
    "태양": ["sun"],
    "달": ["moon"],
    "수성": ["mercury", "mercury barycenter"],
    "금성": ["venus", "venus barycenter"],
    "화성": ["mars", "mars barycenter"],
    "목성": ["jupiter", "jupiter barycenter"],
    "토성": ["saturn", "saturn barycenter"],
}
DE421_SPAN = (date(1899, 7, 29), date(2053, 10, 9))   # JPL 안내문의 DE421 구간(JED 2414864.5 ~ 2471184.5)


def wrap180(x):
    return ((x + 180.0) % 360.0) - 180.0


def dms(deg):
    """부호 있는 각도(도) → '+0°00′00.4″' 꼴."""
    s = "-" if deg < 0 else "+"
    a = abs(deg) * 3600.0
    d_ = int(a // 3600)
    m_ = int((a - d_ * 3600) // 60)
    sec = a - d_ * 3600 - m_ * 60
    if sec >= 59.95:                      # 반올림 표시가 60.0″ 가 되지 않게
        sec = 0.0
        m_ += 1
        if m_ == 60:
            m_ = 0
            d_ += 1
    return f"{s}{d_}°{m_:02d}′{sec:04.1f}″"


def main():
    sys.dont_write_bytecode = True          # 템플릿 폴더에 __pycache__ 를 만들지 않는다
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="astro_core(pyephem) 트랜짓 황경을 skyfield + DE421 과 대조")
    ap.add_argument("utc_date", help="UTC 날짜 YYYY-MM-DD")
    ap.add_argument("bsp", help="de421.bsp 경로(내려받지 않는다)")
    ap.add_argument("--hour-utc", type=int, default=3, help="UTC 시 0~23 (기본 3 = 낮 12시 KST)")
    ap.add_argument("--retro-scan", action="store_true", help="역행 천체의 순행 전환일을 astro_core 와 DE421 로 각각 찾는다")
    ap.add_argument("--sun-crossing", type=float, default=None, help="태양 겉보기 황경이 이 도수를 지나는 시각(날짜 ±1일)")
    a = ap.parse_args()

    try:
        d = datetime.strptime(a.utc_date, "%Y-%m-%d").date()
    except ValueError:
        print(f"[입력 오류] 날짜 형식은 YYYY-MM-DD: {a.utc_date!r}")
        return 2
    if not (0 <= a.hour_utc <= 23):
        print(f"[입력 오류] --hour-utc 는 0~23: {a.hour_utc}")
        return 2
    if not (DE421_SPAN[0] + timedelta(days=2) <= d <= DE421_SPAN[1] - timedelta(days=2)):
        print(f"[입력 오류] DE421 구간({DE421_SPAN[0]} ~ {DE421_SPAN[1]}) 밖이다: {d}")
        return 2
    if not os.path.isfile(a.bsp):
        print(f"[파일 없음] {a.bsp} — 내려받지 않고 멈춘다\n"
              "받는 방법은 README의 '계산 검증 도구' 절에 있다")
        return 2

    sys.path.insert(0, ROOT)

    import ephem
    import jplephem
    import skyfield
    from skyfield import framelib
    from skyfield.api import load, load_file
    import astro_core as A                  # 이 템플릿의 계산 모듈(읽기만)

    try:
        eph = load_file(a.bsp)
    except Exception as e:                  # noqa: BLE001 — 어떤 이유든 열리지 않으면 멈춘다
        print(f"[파일 열기 실패] {a.bsp}: {type(e).__name__}: {e} — 내려받지 않고 멈춘다")
        return 2
    ts = load.timescale(builtin=True)       # 내장 시간 자료만(내려받기 없음)

    ut = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(hours=a.hour_utc)
    kst = ut + timedelta(hours=9)
    t0 = ts.from_datetime(ut)
    t1 = ts.from_datetime(ut + timedelta(days=1))

    # ① 봇의 계산 — 봇이 매일 부르는 함수 그대로
    bot = A.transit_longitudes(d, hour_kst=a.hour_utc + 9)
    labels = [lab for lab, _body in A.TRANSIT_BODIES]
    if set(labels) != set(DE421_TARGETS):
        print(f"[대상 불일치] astro_core 천체 {labels} 와 대조표 {list(DE421_TARGETS)} 가 다르다")
        return 2

    names = {str(n).lower() for codes in eph.names().values() for n in codes} if hasattr(eph, "names") else set()
    earth = eph["earth"]
    sun = eph["sun"]

    def pick(label):
        for nm in DE421_TARGETS[label]:
            if nm in names:
                return nm
        return DE421_TARGETS[label][-1]

    def lon_apparent_of_date(target, t):
        lat, lon, _dist = earth.at(t).observe(target).apparent().frame_latlon(framelib.ecliptic_frame)
        return lon.degrees % 360.0

    rows, diag = [], []
    for label in labels:
        nm = pick(label)
        tgt = eph[nm]
        lon_bot, retro_bot = bot[label]
        lon_de = lon_apparent_of_date(tgt, t0)
        lon_de_next = lon_apparent_of_date(tgt, t1)
        retro_de = wrap180(lon_de_next - lon_de) < 0
        diff = wrap180(lon_bot - lon_de)
        rows.append((label, nm, lon_bot, lon_de, diff, retro_bot, retro_de))

        # 진단: 기준을 하나씩 바꿨을 때 DE421 값끼리의 차이
        astrom = earth.at(t0).observe(tgt)
        app = astrom.apparent()
        _, lon_j2000, _ = app.frame_latlon(framelib.ecliptic_J2000_frame)
        _, lon_geom, _ = astrom.frame_latlon(framelib.ecliptic_frame)
        if label == "태양":
            helio = None
        else:
            _, lon_h, _ = sun.at(t0).observe(tgt).frame_latlon(framelib.ecliptic_frame)
            helio = wrap180(lon_de - lon_h.degrees)
        diag.append((label,
                     wrap180(lon_de - lon_j2000.degrees),       # 당일 진분점 − J2000 분점
                     wrap180(lon_de - lon_geom.degrees),        # 겉보기 − 기하(광행시·광행차·빛 휨 보정 전)
                     helio))                                   # 지구 중심 − 태양 중심

    # ── 출력 ──
    size = os.path.getsize(a.bsp)
    print("# verify_with_de421 — astro_core(pyephem) 트랜짓 황경 vs skyfield + JPL DE421")
    print(f"# 시각: {ut:%Y-%m-%d %H:%M} UTC (= {kst:%Y-%m-%d %H:%M} KST)"
          + ("  — 봇 기준 시각(낮 12시 KST)" if a.hour_utc == 3 else ""))
    print("# 기준: 지구 중심 · 겉보기(apparent) · 당일 진분점 황경  /  역행 = 하루 뒤 황경이 줄면(astro_core 와 같은 방법)")
    print(f"# 라이브러리: ephem {ephem.__version__} · skyfield {skyfield.__version__} · jplephem {jplephem.__version__}"
          f" · {os.path.basename(a.bsp)} {size:,} 바이트")
    print(f"# 허용 오차: {TOL_ARCSEC:.0f}″ (실행 전에 정한 상수 TOL_ARCSEC)")
    print()
    print(f"{'천체':<4} {'DE421 대상':<20} {'astro_core':>12} {'DE421':>12} {'차이(각초)':>10}  {'차이(도·분·초)':<14} 역행(봇/DE421)")
    bad = []
    for label, nm, lb, ld, df_, rb, rd in rows:
        arcsec = df_ * 3600.0
        ok = abs(arcsec) <= TOL_ARCSEC and rb == rd
        if not ok:
            bad.append(label)
        print(f"{label:<4} {nm:<20} {lb:>11.5f}° {ld:>11.5f}° {arcsec:>+10.2f}  {dms(df_):<14} "
              f"{'역행' if rb else '순행'}/{'역행' if rd else '순행'}{'' if ok else '   <- 어긋남'}")
    abs_sec = [abs(r[4]) * 3600.0 for r in rows]
    worst = max(range(len(rows)), key=lambda i: abs_sec[i])
    retro_same = sum(1 for r in rows if r[5] == r[6])
    print()
    print(f"최대 |차이|: {rows[worst][0]} {abs_sec[worst]:.2f}″ · 중앙값 {statistics.median(abs_sec):.2f}″ · "
          f"허용 오차 안 {sum(1 for x in abs_sec if x <= TOL_ARCSEC)}/{len(rows)} · 역행 표시 일치 {retro_same}/{len(rows)}")
    verdict = "통과" if not bad else "실패(" + "·".join(bad) + ")"
    print(f"판정: {verdict}")

    print()
    print("[진단] 기준을 하나씩 바꿨을 때 DE421 값끼리의 차이 — 기준이 어긋나면 이만큼 벌어진다")
    print(f"{'천체':<4} {'분점: 당일−J2000':>18} {'광행차 등: 겉보기−기하':>22} {'중심: 지구−태양':>18}")
    for label, d_eq, d_ab, d_he in diag:
        he = "      (태양 자신)" if d_he is None else f"{d_he:>+17.4f}°"
        print(f"{label:<4} {d_eq:>+17.4f}° {d_ab * 3600:>+20.1f}″  {he}")
    eq_vals = [x[1] for x in diag]
    print(f"분점 차이 범위: {min(eq_vals):+.4f}° ~ {max(eq_vals):+.4f}° "
          f"(= {min(eq_vals) * 3600:+.0f}″ ~ {max(eq_vals) * 3600:+.0f}″)")

    extra_bad = []
    if a.retro_scan:
        body_by_label = dict(A.TRANSIT_BODIES)

        def de_retro(nm, day):
            u0 = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(hours=a.hour_utc)
            l1 = lon_apparent_of_date(eph[nm], ts.from_datetime(u0))
            l2 = lon_apparent_of_date(eph[nm], ts.from_datetime(u0 + timedelta(days=1)))
            return wrap180(l2 - l1) < 0

        print()
        print(f"[순행 전환일] {d} 에 역행인 천체 — astro_core.retro_until vs DE421 같은 방법(최대 {A.RETRO_SCAN_DAYS}일)")
        retro_labels = [r[0] for r in rows if r[5]]
        if not retro_labels:
            print("  이 날짜에 역행인 천체가 없다(봇 판정)")
        for label in retro_labels:
            bot_until = A.retro_until(body_by_label[label], d, hour_kst=a.hour_utc + 9)
            nm = pick(label)
            cur, de_until = d, None
            if de_retro(nm, d):
                for _ in range(A.RETRO_SCAN_DAYS):
                    cur = cur + timedelta(days=1)
                    if not de_retro(nm, cur):
                        de_until = cur
                        break
            same = bot_until == de_until
            if not same:
                extra_bad.append(f"{label} 순행 전환일")
            print(f"  {label}: 봇 {bot_until} · DE421 {de_until} → {'같음' if same else '다름'}")

    if a.sun_crossing is not None:
        target = a.sun_crossing % 360.0
        lo = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) - timedelta(days=1)
        hi = lo + timedelta(days=3)

        def f_bot(u):
            return A._ecl_lon(ephem.Sun, ephem.Date(u.replace(tzinfo=None)))

        def f_de(u):
            return lon_apparent_of_date(sun, ts.from_datetime(u))

        def crossing(f):
            if not (wrap180(f(lo) - target) < 0 <= wrap180(f(hi) - target)):
                return None
            x0, x1 = lo, hi
            for _ in range(60):
                mid = x0 + (x1 - x0) / 2
                if wrap180(f(mid) - target) < 0:
                    x0 = mid
                else:
                    x1 = mid
                if (x1 - x0).total_seconds() < 1:
                    break
            return x0 + (x1 - x0) / 2

        cb, cd = crossing(f_bot), crossing(f_de)
        print()
        print(f"[태양 황경 {target:g}° 통과 시각] {lo:%Y-%m-%d} ~ {hi:%Y-%m-%d} UTC 안에서 이분법(1초)")
        if cb is None or cd is None:
            extra_bad.append("태양 통과 시각 못 찾음")
            print(f"  구간 안에서 못 찾음 — 봇 {cb} · DE421 {cd}")
        else:
            gap = abs((cb - cd).total_seconds())
            if gap > CROSS_TOL_SEC:
                extra_bad.append("태양 통과 시각")
            k9 = timedelta(hours=9)
            print(f"  봇(pyephem) {(cb + k9):%Y-%m-%d %H:%M:%S} KST · DE421 {(cd + k9):%Y-%m-%d %H:%M:%S} KST · "
                  f"차이 {gap:.0f}초(허용 {CROSS_TOL_SEC:.0f}초) → {'통과' if gap <= CROSS_TOL_SEC else '실패'}")

    if extra_bad:
        print(f"추가 대조 판정: 실패({'·'.join(extra_bad)})")
    elif a.retro_scan or a.sun_crossing is not None:
        print("추가 대조 판정: 통과")
    return 0 if not (bad or extra_bad) else 1


if __name__ == "__main__":
    raise SystemExit(main())
