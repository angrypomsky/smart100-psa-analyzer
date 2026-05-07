# -*- coding: utf-8 -*-
"""
demo_data_stratified/*.csv 에 대해 ET 통념 대비 CD/OK 판정 적절성 검사.

검사 항목
---------
[A] PCT 기반 Outcome 일관성
    A1. Outcome=CD ↔ PCT_max > 1477
    A2. Outcome 과 PCT 판정이 어긋나는 케이스 수

[B] Feed-and-Bleed 로직 (업데이트_예정.md §3.3)
    B1. PRHRS_count ≤ 1 이면 ADS 진입 (ADS_BLEED_count 가 NaN 아니어야)
    B2. ADS_BLEED_count = 0 이면 PSIS = Fail
    B3. PSIS = Fail 이면 SIT_Refill_time 은 NaN
    B4. PSIS = Success 이면 SIT_Refill_time 은 숫자

[C] ET 통념 상 CD/OK 기대 방향 (물리적 타당성)
    C1. 모든 완화계통 실패 (PRHRS=0, ADS=0 or fail, PSIS=Fail) → 원칙적으로 CD 기대
    C2. PRHRS 최대 작동 (PRHRS_count=4) → 원칙적으로 OK 기대
    C3. RT=Fail → ATWS, 원칙적으로 CD 기대
    C4. PCT_max 와 PRHRS_count 음의 상관 예상 (피어슨)

[D] 경계 근처 (PCT 1400~1550) 판정의 분산
    D1. ±5% (1403~1551) 구간 샘플 수와 CD/OK 비율
"""
from pathlib import Path
import pandas as pd
import numpy as np

SRC_DIR = Path("demo_data_stratified")
PCT_CD_THRESHOLD = 1477.0
MARGIN_LO = PCT_CD_THRESHOLD * 0.95   # 1403
MARGIN_HI = PCT_CD_THRESHOLD * 1.05   # 1551

def check_file(path: Path):
    df = pd.read_csv(path)
    n  = len(df)
    scen = path.stem.replace("_demo", "").upper()
    lines = [f"\n{'='*70}\n[{scen}]  total={n}"]
    issues = {"A":[], "B":[], "C":[], "D":[]}

    # ---------- [A] PCT 일관성 ----------
    expect_cd = df["PCT_max"] >= PCT_CD_THRESHOLD    # 생성기와 동일 (>=1477)
    is_cd     = df["Outcome"].str.upper() == "CD"
    mismatch  = expect_cd != is_cd
    m_count   = mismatch.sum()
    cd_but_low = df[(is_cd) & (~expect_cd)]
    ok_but_high= df[(~is_cd) & (expect_cd)]
    lines.append(f"\n[A] PCT(>1477K) vs Outcome")
    lines.append(f"  A1  Outcome=CD 인데 PCT≤1477 : {len(cd_but_low):>3}건")
    lines.append(f"  A2  Outcome=OK 인데 PCT>1477 : {len(ok_but_high):>3}건")
    if m_count > 0:
        issues["A"].append(m_count)
        # 몇 건 샘플 출력
        if len(cd_but_low) > 0:
            s = cd_but_low.head(3)[["Scenario","PCT_max","Outcome"]]
            lines.append(f"       예시 CD/low: {s.to_dict('records')}")
        if len(ok_but_high) > 0:
            s = ok_but_high.head(3)[["Scenario","PCT_max","Outcome"]]
            lines.append(f"       예시 OK/high: {s.to_dict('records')}")

    # ---------- [B] Feed-and-Bleed 로직 ----------
    lines.append(f"\n[B] Feed-and-Bleed 구조 일관성")

    b1_bad = df[(df["PRHRS_count"] <= 1) & (df["ADS_BLEED_count"].isna())]
    lines.append(f"  B1  PRHRS≤1 인데 ADS NaN       : {len(b1_bad):>3}건")
    if len(b1_bad) > 0: issues["B"].append(("B1", len(b1_bad)))

    b2_bad = df[(df["ADS_BLEED_count"] == 0) & (df["PSIS_FEED_status"] != "Fail")]
    lines.append(f"  B2  ADS=0 인데 PSIS≠Fail       : {len(b2_bad):>3}건")
    if len(b2_bad) > 0: issues["B"].append(("B2", len(b2_bad)))

    b3_bad = df[(df["PSIS_FEED_status"] == "Fail") & (df["SIT_Refill_time"].notna())]
    lines.append(f"  B3  PSIS=Fail 인데 SIT 숫자    : {len(b3_bad):>3}건")
    if len(b3_bad) > 0: issues["B"].append(("B3", len(b3_bad)))

    b4_bad = df[(df["PSIS_FEED_status"] == "Success") & (df["SIT_Refill_time"].isna())]
    lines.append(f"  B4  PSIS=Succ 인데 SIT NaN     : {len(b4_bad):>3}건")
    if len(b4_bad) > 0: issues["B"].append(("B4", len(b4_bad)))

    # PRHRS Success 구간에서 ADS 가 NaN 인지 (이 경우 Feed&Bleed 불필요)
    bx_ads_when_prhrs_ok = df[(df["PRHRS_count"] >= 2) & df["ADS_BLEED_count"].notna()]
    lines.append(f"  (참고) PRHRS≥2 인데 ADS 시도됨 : {len(bx_ads_when_prhrs_ok):>3}건"
                 f"  → 설계상 의도? (완화 불필요한데 작동했다면 과보수)")

    # ---------- [C] 물리적 타당성 ----------
    lines.append(f"\n[C] ET 통념 기대 방향")

    # C1. 완전 실패 시 CD 기대
    full_fail = df[
        (df["PRHRS_count"] == 0) &
        (df["ADS_BLEED_count"] == 0) &
        (df["PSIS_FEED_status"] == "Fail")
    ]
    if len(full_fail) > 0:
        cd_ratio = (full_fail["Outcome"] == "CD").mean()
        lines.append(f"  C1  PRHRS=0 & ADS=0 & PSIS=Fail (n={len(full_fail)})")
        lines.append(f"       → CD 비율 {cd_ratio*100:>5.1f}%  (기대: ~100%)")
        if cd_ratio < 0.9:
            issues["C"].append(("C1", f"CD비율{cd_ratio*100:.1f}%"))
    else:
        lines.append(f"  C1  완전 실패 케이스 없음")

    # C2. PRHRS 최대 작동
    prhrs_max = df[df["PRHRS_count"] == df["PRHRS_count"].max()]
    if len(prhrs_max) > 0:
        ok_ratio = (prhrs_max["Outcome"] == "OK").mean()
        lines.append(f"  C2  PRHRS={int(df['PRHRS_count'].max())} (최대, n={len(prhrs_max)})")
        lines.append(f"       → OK 비율 {ok_ratio*100:>5.1f}%  (기대: ~100%)")
        if ok_ratio < 0.9:
            issues["C"].append(("C2", f"OK비율{ok_ratio*100:.1f}%"))

    # C3. RT Fail
    rt_fail = df[df["Reactor_Trip"] == "Fail"]
    if len(rt_fail) > 0:
        cd_ratio = (rt_fail["Outcome"] == "CD").mean()
        lines.append(f"  C3  RT=Fail (ATWS, n={len(rt_fail)})")
        lines.append(f"       → CD 비율 {cd_ratio*100:>5.1f}%  (기대: ~100%)")
        if cd_ratio < 0.9 and len(rt_fail) >= 3:
            issues["C"].append(("C3", f"CD비율{cd_ratio*100:.1f}%"))
    else:
        lines.append(f"  C3  RT=Fail 케이스 없음")

    # C4. PCT vs PRHRS_count 상관
    corr = df[["PCT_max","PRHRS_count"]].corr().iloc[0,1]
    lines.append(f"  C4  corr(PCT_max, PRHRS_count) = {corr:+.3f}  (기대: 강한 음)")
    if corr > -0.3:
        issues["C"].append(("C4", f"corr={corr:+.2f}"))

    # ---------- [D] 경계 구간 ----------
    border = df[(df["PCT_max"] >= MARGIN_LO) & (df["PCT_max"] <= MARGIN_HI)]
    if len(border) > 0:
        cd_pct = (border["Outcome"] == "CD").mean() * 100
        lines.append(f"\n[D] 경계 구간 PCT∈[{MARGIN_LO:.0f},{MARGIN_HI:.0f}]"
                     f"  n={len(border):>3}  CD비율={cd_pct:>5.1f}%")
    else:
        lines.append(f"\n[D] 경계 구간 샘플 없음")

    # ---------- Outcome 분포 ----------
    lines.append(f"\n[Outcome 분포]")
    vc = df["Outcome"].value_counts()
    for k,v in vc.items():
        lines.append(f"  {k}: {v:>3}  ({v/n*100:>5.1f}%)")

    return "\n".join(lines), issues

def main():
    all_issues = {}
    reports = []
    for path in sorted(SRC_DIR.glob("*.csv")):
        rpt, iss = check_file(path)
        reports.append(rpt)
        all_issues[path.stem] = iss

    print("\n".join(reports))

    # 최종 요약
    print(f"\n{'='*70}\n[최종 요약]")
    total_issues = 0
    for name, iss in all_issues.items():
        cnt = sum(len(v) for v in iss.values())
        total_issues += cnt
        flag = "  " if cnt == 0 else "!!"
        print(f"  {flag} {name}: {cnt}개 이슈  {dict((k,v) for k,v in iss.items() if v)}")
    print(f"\n  총 이슈: {total_issues}개")

if __name__ == "__main__":
    main()
