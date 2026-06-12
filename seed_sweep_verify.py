# -*- coding: utf-8 -*-
"""
Seed Sweep 검증 — 10개 독립 seed 로 demo_dataset_generator.py 실행 후
ATWS / 완전실패 / PRHRS=4 / 상관 / CD 분포의 통계 안정성 평가.

산출물:
  seed_sweep/seed_XXXX/*.csv  (10개 seed × 5 사고유형 = 50 파일)
  seed_sweep/raw_metrics.csv  (50행, seed×accident 별 metric)
  seed_sweep/summary.csv      (사고유형별 mean±std, range)
  콘솔 출력: 통계 요약 표
"""
import subprocess, sys
from pathlib import Path
import pandas as pd
import numpy as np

SEEDS     = [42, 142, 242, 342, 442, 542, 642, 742, 842, 942]
ACCIDENTS = ['GTRN', 'LOFW', 'LSSB', 'SBLOCA', 'SGTR']
N         = 200
ROOT      = Path("seed_sweep")
ROOT.mkdir(exist_ok=True)

# --------------------------------------------------------------- 1) 데이터 생성
print(f"[Step 1] {len(SEEDS)} seeds × n={N} 데이터 생성")
for i, seed in enumerate(SEEDS, 1):
    out = ROOT / f"seed_{seed:04d}"
    if out.exists() and len(list(out.glob("*.csv"))) == 5:
        print(f"  ({i}/{len(SEEDS)}) seed={seed} 스킵 (이미 존재)")
        continue
    print(f"  ({i}/{len(SEEDS)}) seed={seed} 생성 중 ...", end=" ", flush=True)
    res = subprocess.run(
        [sys.executable, "demo_dataset_generator.py",
         "--all", "--n", str(N), "--seed", str(seed),
         "--output", str(out), "--mode", "stratified"],
        capture_output=True, text=True
    )
    if res.returncode != 0:
        print(f"실패!\n{res.stderr}")
        sys.exit(1)
    print("완료")

# --------------------------------------------------------------- 2) Metric 추출
print(f"\n[Step 2] (seed × accident) = {len(SEEDS)*len(ACCIDENTS)}개 조합 metric 계산")
records = []
for seed in SEEDS:
    for acc in ACCIDENTS:
        path = ROOT / f"seed_{seed:04d}" / f"{acc}_demo.csv"
        df = pd.read_csv(path)
        rt_fail   = df[df['Reactor_Trip'] == 'Fail']
        full_fail = df[(df['PRHRS_count']==0) &
                       (df['ADS_BLEED_count']==0) &
                       (df['PSIS_FEED_status']=='Fail')]
        prhrs_max = df[df['PRHRS_count'] == df['PRHRS_count'].max()]

        records.append({
            'seed':            seed,
            'accident':        acc,
            'n_total':         len(df),
            'atws_n':          len(rt_fail),
            'atws_cd_pct':     (rt_fail['Outcome']=='CD').mean()*100 if len(rt_fail) else np.nan,
            'fullfail_n':      len(full_fail),
            'fullfail_cd_pct': (full_fail['Outcome']=='CD').mean()*100 if len(full_fail) else np.nan,
            'prhrs4_n':        len(prhrs_max),
            'prhrs4_ok_pct':   (prhrs_max['Outcome']=='OK').mean()*100 if len(prhrs_max) else np.nan,
            'corr_pct_prhrs':  df[['PCT_max','PRHRS_count']].corr().iloc[0,1],
            'cd_overall_pct':  (df['Outcome']=='CD').mean()*100,
        })

raw = pd.DataFrame(records)
raw.to_csv(ROOT / "raw_metrics.csv", index=False)
print(f"  raw_metrics.csv 저장 ({len(raw)}행)")

# --------------------------------------------------------------- 3) 사고유형별 집계
def agg_stat(s):
    return pd.Series({
        'n_seeds':  s.notna().sum(),
        'mean':     s.mean(skipna=True),
        'std':      s.std(skipna=True),
        'min':      s.min(skipna=True),
        'max':      s.max(skipna=True),
    })

print(f"\n[Step 3] 사고유형별 집계\n")

# A. ATWS CD%
print("=" * 78)
print(" A. ATWS (RT=Fail) CD%  -10 seed 평균 ± std (Range)")
print("=" * 78)
print(f"{'사고유형':<10}{'ATWS n총합':>12}{'평균':>10}{'± std':>10}{'min':>10}{'max':>10}")
print("-" * 78)
for acc in ACCIDENTS:
    sub = raw[raw['accident']==acc]
    n_tot = sub['atws_n'].sum()
    a = agg_stat(sub['atws_cd_pct'])
    print(f"{acc:<10}{n_tot:>12}{a['mean']:>9.1f}%{a['std']:>9.1f}%{a['min']:>9.1f}%{a['max']:>9.1f}%")

# B. Complete failure CD%
print("\n" + "=" * 78)
print(" B. 완전실패 (PRHRS=0 & ADS=0 & PSIS=Fail) CD%  -10 seed 평균")
print("=" * 78)
print(f"{'사고유형':<10}{'완전실패 n총합':>16}{'평균':>10}{'± std':>10}{'min':>10}{'max':>10}")
print("-" * 78)
for acc in ACCIDENTS:
    sub = raw[raw['accident']==acc]
    n_tot = sub['fullfail_n'].sum()
    a = agg_stat(sub['fullfail_cd_pct'])
    print(f"{acc:<10}{n_tot:>16}{a['mean']:>9.1f}%{a['std']:>9.1f}%{a['min']:>9.1f}%{a['max']:>9.1f}%")

# C. PRHRS=max OK%
print("\n" + "=" * 78)
print(" C. PRHRS 최대 작동 (PRHRS=4) 시 OK%  -10 seed 평균")
print("=" * 78)
print(f"{'사고유형':<10}{'PRHRS=4 n총합':>16}{'평균':>10}{'± std':>10}{'min':>10}{'max':>10}")
print("-" * 78)
for acc in ACCIDENTS:
    sub = raw[raw['accident']==acc]
    n_tot = sub['prhrs4_n'].sum()
    a = agg_stat(sub['prhrs4_ok_pct'])
    print(f"{acc:<10}{n_tot:>16}{a['mean']:>9.1f}%{a['std']:>9.1f}%{a['min']:>9.1f}%{a['max']:>9.1f}%")

# D. Correlation & overall CD
print("\n" + "=" * 78)
print(" D. PCT~PRHRS 상관계수 & 전체 CD%  -10 seed 평균")
print("=" * 78)
print(f"{'사고유형':<10}{'corr 평균':>12}{'corr std':>12}{'CD% 평균':>14}{'CD% std':>12}")
print("-" * 78)
for acc in ACCIDENTS:
    sub = raw[raw['accident']==acc]
    c = agg_stat(sub['corr_pct_prhrs'])
    o = agg_stat(sub['cd_overall_pct'])
    print(f"{acc:<10}{c['mean']:>+12.3f}{c['std']:>12.3f}{o['mean']:>13.1f}%{o['std']:>11.1f}%")

# Save summary
summary_rows = []
for acc in ACCIDENTS:
    sub = raw[raw['accident']==acc]
    row = {'accident': acc}
    for col, label in [('atws_cd_pct','atws_cd'),
                        ('fullfail_cd_pct','fullfail_cd'),
                        ('prhrs4_ok_pct','prhrs4_ok'),
                        ('corr_pct_prhrs','corr'),
                        ('cd_overall_pct','cd_overall')]:
        a = agg_stat(sub[col])
        row[f'{label}_mean'] = round(a['mean'], 3)
        row[f'{label}_std']  = round(a['std'], 3)
        row[f'{label}_min']  = round(a['min'], 3)
        row[f'{label}_max']  = round(a['max'], 3)
    row['atws_n_total']     = int(sub['atws_n'].sum())
    row['fullfail_n_total'] = int(sub['fullfail_n'].sum())
    summary_rows.append(row)
pd.DataFrame(summary_rows).to_csv(ROOT / "summary.csv", index=False)

print("\n" + "=" * 78)
print(f" 결과 파일")
print("=" * 78)
print(f"  raw_metrics.csv  ({len(raw)}행, seed×accident 단위)")
print(f"  summary.csv      ({len(summary_rows)}행, accident 단위 통계)")
print(f"  seed_sweep/seed_XXXX/*.csv  (50개 표본 데이터)")
