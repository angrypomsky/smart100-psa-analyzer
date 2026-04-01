# -*- coding: utf-8 -*-
"""
SMART100 PSA 데모 데이터셋 생성기
  - psa_analyzer.py 출력 형식과 동일한 합성 데이터 생성
  - 계통 간 상관관계 반영: RT → RCP → PRHRS → ADS → PSIS → SIT → PCT → Outcome

사용법:
  python demo_dataset_generator.py --type LOFW --n 200 --seed 42
  python demo_dataset_generator.py --all --n 200 --seed 42 --output demo_data/
"""

import argparse
import numpy as np
import pandas as pd
from pathlib import Path

# ============================================================
# 상수 테이블
# ============================================================

ACCIDENT_TYPES = ['LOFW', 'SBLOCA', 'GTRN', 'LSSB', 'SGTR']

# 사고유형별 RT 성공률
RT_SUCCESS_PROB = {
    'LOFW':   0.98,
    'SBLOCA': 0.95,
    'GTRN':   0.99,
    'LSSB':   0.97,
    'SGTR':   0.95,
}

# RCP 상태 조건부 확률 (RT 결과 | 순서: Running, Coast-down, Natural Circulation)
RCP_STATES = ['Running', 'Coast-down', 'Natural Circulation']
RCP_GIVEN_RT = {
    'Success': [0.60, 0.30, 0.10],
    'Fail':    [0.10, 0.30, 0.60],
}

# PRHRS 계통수 조건부 확률 (RT + RCP | 순서: 4,3,2,1,0)
PRHRS_VALUES = [4, 3, 2, 1, 0]
PRHRS_GIVEN_RT_RCP = {
    ('Success', 'Running'):             [0.60, 0.25, 0.10, 0.04, 0.01],
    ('Success', 'Coast-down'):          [0.40, 0.35, 0.15, 0.08, 0.02],
    ('Success', 'Natural Circulation'): [0.30, 0.30, 0.25, 0.10, 0.05],
    ('Fail',    'Running'):             [0.10, 0.20, 0.30, 0.25, 0.15],
    ('Fail',    'Coast-down'):          [0.10, 0.20, 0.30, 0.25, 0.15],
    ('Fail',    'Natural Circulation'): [0.10, 0.20, 0.30, 0.25, 0.15],
}

# ADS 작동 수 조건부 확률 (PRHRS ≤ 1일 때만 | 순서: 0,1,2)
ADS_VALUES = [0, 1, 2]
ADS_GIVEN_PRHRS = {
    0: [0.40, 0.35, 0.25],
    1: [0.30, 0.40, 0.30],
}

# PSIS 성공률 (ADS 작동 수 조건부)
PSIS_SUCCESS_GIVEN_ADS = {
    0: 0.00,   # ADS=0 → 감압 실패 → PSIS 무조건 Fail
    1: 0.60,
    2: 0.85,
}

# SIT Refill 시간 범위 (PSIS 성공 시, 초)
SIT_RANGE = (3600, 108000)   # 1시간 ~ 30시간

# PCT 파라미터 (mean_K, std_K) — 최종 냉각 경로별
# key: (prhrs_ok, ads_ok, psis_ok)  True/False
PCT_PARAMS = {
    (True,  True,  True):  (1050,  80),   # PRHRS ≥ 2 (ADS/PSIS 무관)
    (True,  True,  False): (1050,  80),
    (True,  False, False): (1050,  80),
    (False, True,  True):  (1300, 120),   # Feed-and-Bleed 성공
    (False, True,  False): (1550, 130),   # ADS 성공, PSIS 실패
    (False, False, False): (1650, 100),   # ADS 실패 (최악)
}

# PCT_time 오프셋 범위 (RT_time 이후, 초)
PCT_TIME_OFFSET = (100, 3000)

# RT_time 범위 (초)
RT_TIME_RANGE = {
    'LOFW':   (10,  60),
    'SBLOCA': (20, 120),
    'GTRN':   (5,   40),
    'LSSB':   (15,  80),
    'SGTR':   (30, 150),
}

# EarlyTerm Note 확률 (LSSB, SGTR만 해당)
EARLY_TERM_PROB = 0.05


# ============================================================
# DemoDatasetGenerator
# ============================================================

class DemoDatasetGenerator:

    def __init__(self):
        pass

    def generate(self, accident_type: str, n: int = 200, seed: int = 42) -> pd.DataFrame:
        accident_type = accident_type.upper()
        if accident_type not in ACCIDENT_TYPES:
            raise ValueError(f"지원하지 않는 사고유형: {accident_type}. 가능: {ACCIDENT_TYPES}")

        rng = np.random.default_rng(seed)
        rows = []

        for i in range(n):
            rt      = self._sample_rt(accident_type, rng)
            rcp     = self._sample_rcp(rt, rng)
            prhrs   = self._sample_prhrs(rt, rcp, rng)
            ads     = self._sample_ads(prhrs, rng)
            psis    = self._sample_psis(ads, rng)
            sit     = self._sample_sit(psis, rng)
            rt_time = float(rng.uniform(*RT_TIME_RANGE[accident_type]))
            pct     = self._sample_pct(prhrs, ads, psis, rng)
            pct_t   = rt_time + float(rng.uniform(*PCT_TIME_OFFSET))
            outcome = 'CD' if pct >= 1477.0 else 'OK'
            note    = self._sample_note(accident_type, rng)

            rows.append({
                'Scenario':         f'{accident_type}_{i+1:03d}',
                'Reactor_Trip':     rt,
                'RCP_Status':       rcp,
                'PRHRS_count':      prhrs,
                'ADS_BLEED_count':  ads,
                'PSIS_FEED_status': psis,
                'SIT_Refill_time':  sit,
                'PCT_max':          round(pct, 1),
                'PCT_time':         round(pct_t, 1),
                'Outcome':          outcome,
                'Note':             note,
            })

        df = pd.DataFrame(rows)
        self._print_stats(accident_type, df)
        return df

    # ── 샘플링 메서드 ───────────────────────────────────────────────────

    def _sample_rt(self, accident_type: str, rng) -> str:
        p = RT_SUCCESS_PROB[accident_type]
        return 'Success' if rng.random() < p else 'Fail'

    def _sample_rcp(self, rt: str, rng) -> str:
        probs = RCP_GIVEN_RT[rt]
        return str(rng.choice(RCP_STATES, p=probs))

    def _sample_prhrs(self, rt: str, rcp: str, rng) -> int:
        key = (rt, rcp)
        probs = PRHRS_GIVEN_RT_RCP[key]
        return int(rng.choice(PRHRS_VALUES, p=probs))

    def _sample_ads(self, prhrs: int, rng):
        """PRHRS ≥ 2이면 N/A, 이하이면 조건부 샘플링"""
        if prhrs >= 2:
            return 'N/A'
        probs = ADS_GIVEN_PRHRS[prhrs]
        return int(rng.choice(ADS_VALUES, p=probs))

    def _sample_psis(self, ads) -> str:
        """ADS가 N/A이면 N/A, 아니면 ADS 작동 수 조건부"""
        if ads == 'N/A':
            return 'N/A'
        p_success = PSIS_SUCCESS_GIVEN_ADS[ads]
        # rng 없이 결정론적 분기 가능하지만 호출부에서 rng 전달
        return p_success  # 임시 — 아래에서 오버라이드

    def _sample_psis(self, ads, rng) -> str:
        if ads == 'N/A':
            return 'N/A'
        p_success = PSIS_SUCCESS_GIVEN_ADS[ads]
        return 'Success' if rng.random() < p_success else 'Fail'

    def _sample_sit(self, psis, rng):
        """PSIS 성공 시에만 SIT Refill 시간 반환"""
        if psis != 'Success':
            return 'N/A'
        return round(float(rng.uniform(*SIT_RANGE)), 1)

    def _sample_pct(self, prhrs: int, ads, psis: str, rng) -> float:
        prhrs_ok = prhrs >= 2
        ads_ok   = isinstance(ads, int) and ads >= 1
        psis_ok  = psis == 'Success'

        key = (prhrs_ok, ads_ok, psis_ok)
        mean, std = PCT_PARAMS[key]
        pct = rng.normal(mean, std)
        return float(np.clip(pct, 800, 1900))

    def _sample_note(self, accident_type: str, rng) -> str:
        if accident_type in ('LSSB', 'SGTR'):
            return 'EarlyTerm' if rng.random() < EARLY_TERM_PROB else ''
        return ''

    # ── 검증 출력 ──────────────────────────────────────────────────────

    def _print_stats(self, accident_type: str, df: pd.DataFrame):
        n = len(df)
        rt_ok   = (df['Reactor_Trip'] == 'Success').mean() * 100
        cd_rate = (df['Outcome'] == 'CD').mean() * 100
        pct_mean = df['PCT_max'].mean()
        pct_max  = df['PCT_max'].max()

        print(f"\n[{accident_type}] {n}개 생성 완료")
        print(f"  RT 성공률:    {rt_ok:.1f}%  (기대: ~{RT_SUCCESS_PROB[accident_type]*100:.0f}%)")
        print(f"  CD 비율:      {cd_rate:.1f}%")

        prhrs_dist = df['PRHRS_count'].value_counts().sort_index(ascending=False)
        dist_str = '  '.join(f"{int(k)}계통:{v/n*100:.0f}%" for k, v in prhrs_dist.items())
        print(f"  PRHRS 분포:   {dist_str}")

        low_prhrs = df[df['PRHRS_count'] <= 1]
        if len(low_prhrs) > 0:
            ads_zero  = (low_prhrs['ADS_BLEED_count'] == 0).sum()
            ads_nonzero = len(low_prhrs) - ads_zero
            psis_ok   = (low_prhrs['PSIS_FEED_status'] == 'Success').sum()
            print(f"  PRHRS ≤ 1 진입: {len(low_prhrs)}개")
            print(f"    ADS=0: {ads_zero}개 → PSIS Fail 확정")
            print(f"    ADS≥1: {ads_nonzero}개 → PSIS Success: {psis_ok}개 / Fail: {ads_nonzero - psis_ok}개")

        print(f"  PCT 평균: {pct_mean:.0f} K  |  최대: {pct_max:.0f} K")

    # ── 저장 ──────────────────────────────────────────────────────────

    def save(self, df: pd.DataFrame, accident_type: str, output_dir: str = '.', fmt: str = 'csv'):
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        df_save = df.fillna({'ADS_BLEED_count': 'N/A',
                              'PSIS_FEED_status': 'N/A',
                              'SIT_Refill_time': 'N/A',
                              'Note': ''})

        if fmt in ('csv', 'both'):
            path = out / f'{accident_type}_demo.csv'
            df_save.to_csv(path, index=False, encoding='utf-8-sig')
            print(f"  저장: {path}")

        if fmt in ('excel', 'both'):
            path = out / f'{accident_type}_demo.xlsx'
            df_save.to_excel(path, index=False)
            print(f"  저장: {path}")


# ============================================================
# CLI 진입점
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='SMART100 PSA 데모 데이터셋 생성기')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--type', choices=ACCIDENT_TYPES,
                       help='단일 사고유형 (예: LOFW)')
    group.add_argument('--all', action='store_true',
                       help='5개 사고유형 전체 생성')
    parser.add_argument('--n',      type=int,  default=200, help='시나리오 수 (기본: 200)')
    parser.add_argument('--seed',   type=int,  default=42,  help='랜덤 시드 (기본: 42)')
    parser.add_argument('--output', type=str,  default='demo_data', help='저장 폴더 (기본: demo_data/)')
    parser.add_argument('--fmt',    choices=['csv', 'excel', 'both'], default='csv',
                        help='저장 형식 (기본: csv)')
    args = parser.parse_args()

    gen = DemoDatasetGenerator()
    targets = ACCIDENT_TYPES if args.all else [args.type]

    for i, acc in enumerate(targets):
        # 사고유형마다 seed 오프셋 적용 → 각자 다른 데이터
        df = gen.generate(acc, n=args.n, seed=args.seed + i)
        gen.save(df, acc, output_dir=args.output, fmt=args.fmt)

    print(f"\n완료: {len(targets)}개 사고유형, 저장 위치: {args.output}/")


if __name__ == '__main__':
    main()
