# -*- coding: utf-8 -*-
"""
=============================================================================
SMART100 PSA 성공기준 자동 탐색 알고리즘 (Success Criteria Finder)
=============================================================================
설계 문서: 분석_1_성공기준_알고리즘_설계.md

기능:
  - MARS-KS 시뮬레이션 결과(CSV)에서 PCT 응답을 기반으로
    안전계통(PRHRS 등)의 성공기준(N/M)을 데이터 주도적으로 자동 탐색
  - 최적화 모드: 가장 완화된(최소 N) 성공기준 탐색 (20% PCT 마진 적용)
  - 보수적 모드: 가장 엄격한(최대 N) 성공기준 탐색 (마진 없음)
  - 조건부 성공기준: 앞 계통 상태별 독립 탐색
  - 이진 변환: PRHRS_count → PRHRS_binary (Success/Fail) 컬럼 생성

사용법:
  import pandas as pd
  from success_criteria import SuccessCriteriaFinder

  df = pd.read_csv("lofw_results.csv")
  result = SuccessCriteriaFinder(
      df=df, condition_vars=['Reactor_Trip'],
      mode='optimization', margin=0.20
  ).run()

  print(result['global_criteria']['criteria_str'])
  df_binary = result['df_with_binary']
=============================================================================
"""

from itertools import product

import numpy as np
import pandas as pd


class SuccessCriteriaFinder:
    """
    성공기준 자동 탐색 클래스

    Parameters
    ----------
    df : pd.DataFrame
        psa_analyzer 출력 CSV (PRHRS_count, PCT_max 등 포함)
    target_system : str
        대상 계통 컬럼명 (기본: 'PRHRS_count')
    system_capacity : int
        전체 계통 수 (SMART100 PRHRS: 4)
    condition_vars : list[str]
        앞 계통 컬럼명 목록 (예: ['Reactor_Trip'])
    pct_col : str
        PCT 컬럼명 (기본: 'PCT_max')
    pct_limit : float
        NRC 10 CFR 50.46 규제 한계치 (기본: 1477.0 K)
    margin : float
        PCT 안전 여유도 (기본: 0.20 = 20%, 최적화 모드)
    mode : str
        'optimization' (완화적) 또는 'conservative' (보수적)
    pct_representative : str
        PCT 대표값 정책: 'p95' | 'mean' | 'max'
    min_samples : int
        최소 샘플 수 (기본: 5, 미만 시 글로벌 fallback)
    """

    PCT_LIMIT_DEFAULT = 1477.0

    def __init__(self, df, target_system='PRHRS_count', system_capacity=4,
                 condition_vars=None, pct_col='PCT_max',
                 pct_limit=1477.0, margin=0.20,
                 mode='optimization', pct_representative='p95',
                 min_samples=5):
        if mode not in ('optimization', 'conservative'):
            raise ValueError(f"mode는 'optimization' 또는 'conservative'여야 합니다: {mode}")
        if pct_representative not in ('p95', 'mean', 'max'):
            raise ValueError(f"pct_representative는 'p95', 'mean', 'max' 중 하나: {pct_representative}")

        self.df                 = df.copy()
        self.target_col         = target_system
        self.M                  = system_capacity
        self.condition_vars     = condition_vars or []
        self.pct_col            = pct_col
        self.pct_limit          = pct_limit
        self.margin             = margin
        self.mode               = mode
        self.pct_representative = pct_representative
        self.min_samples        = min_samples

        # PCT 임계값 계산
        if mode == 'optimization':
            self.pct_threshold = pct_limit * (1.0 - margin)
        else:
            self.pct_threshold = pct_limit  # 보수적 모드: 마진 없음

        # 전처리: 이상치 제거 및 유효 범위 제한
        self.df = self.df[self.df[pct_col] < 10000].copy()
        self.df[target_system] = (
            self.df[target_system].clip(lower=0, upper=system_capacity).astype(int)
        )

    def run(self):
        """
        성공기준 탐색 실행

        Returns
        -------
        dict
            metadata, global_criteria, conditional_criteria,
            binary_mapping, df_with_binary 키를 포함하는 결과 딕셔너리
        """
        # 1. 글로벌 성공기준 탐색 (조건 없이 전체 데이터)
        global_result = self._find_criteria_for_subset(self.df, label="GLOBAL")

        # 2. 조건부 성공기준 탐색 (앞 계통 상태별)
        conditional_results = []
        if self.condition_vars:
            for condition_dict in self._enumerate_conditions():
                subset = self._filter_by_condition(self.df, condition_dict)
                if len(subset) < self.min_samples:
                    result = self._make_fallback(condition_dict, global_result)
                else:
                    result = self._find_criteria_for_subset(
                        subset, label=str(condition_dict),
                        condition_vars=condition_dict
                    )
                conditional_results.append(result)

        # 3. 이진 매핑 및 컬럼 추가
        binary_mapping = self._build_binary_mapping(conditional_results, global_result)
        self.df[self._binary_col_name()] = self._apply_binary_mapping(binary_mapping)

        return self._assemble_result(global_result, conditional_results, binary_mapping)

    # ── 조건 열거 및 필터링 ─────────────────────────────────────────

    def _enumerate_conditions(self):
        """condition_vars의 모든 카테고리 조합 열거"""
        unique_values = {
            var: sorted(self.df[var].dropna().unique())
            for var in self.condition_vars if var in self.df.columns
        }
        vars_list = list(unique_values.keys())
        if not vars_list:
            return
        for combo in product(*[unique_values[v] for v in vars_list]):
            yield dict(zip(vars_list, combo))

    def _filter_by_condition(self, df, condition_dict):
        """조건 딕셔너리로 DataFrame 필터링"""
        mask = pd.Series(True, index=df.index)
        for var, val in condition_dict.items():
            if var in df.columns:
                mask &= (df[var] == val)
        return df[mask].copy()

    # ── 성공기준 탐색 (모드 분기) ───────────────────────────────────

    def _find_criteria_for_subset(self, subset, label="", condition_vars=None):
        """모드에 따라 적절한 탐색 메서드 호출"""
        if self.mode == 'optimization':
            return self._find_criteria_optimization(subset, label, condition_vars)
        else:
            return self._find_criteria_conservative(subset, label, condition_vars)

    def _find_criteria_optimization(self, subset, label, condition_vars):
        """
        최적화 모드: 높은 계통수(M)부터 순회하여 PCT < threshold인 최소 N 탐색

        탐색 방향: M → 0 (가장 완화된 성공기준 탐색)
        """
        pct_stats = self._compute_pct_stats_by_count(subset)
        pct_stats = self._enforce_monotonicity(pct_stats)

        min_count = None
        for count in range(self.M, -1, -1):  # 4, 3, 2, 1, 0
            if count not in pct_stats or pct_stats[count]['n'] < self.min_samples:
                # 데이터 부재 또는 샘플 부족 → 안전 측 처리: 탐색 중단
                # PSA 원칙: 검증되지 않은 영역을 안전하다고 가정하지 않음
                break
            stats = pct_stats[count]
            if stats[self.pct_representative] < self.pct_threshold:
                min_count = count  # 더 낮은 계통수도 확인 계속
            else:
                break  # PCT 초과 → 이보다 낮은 count는 더 위험하므로 중단

        if min_count is None:
            criteria_str = "None (노심 보호 불가)"
            final_count = None
        elif min_count == 0:
            criteria_str = f"0/{self.M} (PRHRS 불필요)"
            final_count = 0
        else:
            criteria_str = f"{min_count}/{self.M}"
            final_count = min_count

        return self._build_criteria_record(
            condition_vars, subset, final_count, criteria_str, pct_stats, label
        )

    def _find_criteria_conservative(self, subset, label, condition_vars):
        """
        보수적 모드: 낮은 N(1)부터 순회하여 PCT < threshold 만족하는 가장 높은 N 선택

        탐색 방향: 1 → M (가장 엄격한 성공기준 탐색)
        """
        pct_stats = self._compute_pct_stats_by_count(subset)
        best_count = None

        for count in range(1, self.M + 1):  # 1, 2, 3, 4
            subset_ge = subset[subset[self.target_col] >= count]
            if len(subset_ge) == 0:
                break
            if subset_ge[self.pct_col].max() < self.pct_threshold:
                best_count = count  # 더 엄격한 N+1도 확인 계속

        if best_count is not None:
            criteria_str = f"{best_count}/{self.M}"
        else:
            criteria_str = "None (어떤 N/M도 안전 보장 불가)"

        return self._build_criteria_record(
            condition_vars, subset, best_count, criteria_str, pct_stats, label
        )

    # ── PCT 통계 계산 ───────────────────────────────────────────────

    def _compute_pct_stats_by_count(self, subset):
        """계통수별 PCT 통계 (n, mean, p95, max, min) 집계"""
        stats = {}
        for count in range(0, self.M + 1):
            rows = subset[subset[self.target_col] == count]
            if len(rows) == 0:
                continue
            pct_vals = rows[self.pct_col].dropna()
            if len(pct_vals) == 0:
                continue
            stats[count] = {
                'n':    len(pct_vals),
                'mean': float(pct_vals.mean()),
                'p95':  float(pct_vals.quantile(0.95)) if len(pct_vals) >= 2 else float(pct_vals.max()),
                'max':  float(pct_vals.max()),
                'min':  float(pct_vals.min()),
            }
        return stats

    def _enforce_monotonicity(self, pct_stats):
        """
        단조성 보정: 계통수 증가 시 PCT 단조 감소 원칙 강제 적용

        순회 방향: 낮은 계통수(0) → 높은 계통수(M)
        원칙: count 증가 시 PCT는 non-increasing이어야 함
        위반 시: 누적 최소값(cumulative minimum)으로 보정

        예: {0: 1200, 1: 950, 2: 800, 3: 820(역전), 4: 700}
        →  {0: 1200, 1: 950, 2: 800, 3: 800,        4: 700}
        """
        sorted_counts = sorted(pct_stats.keys())  # 낮은 계통수부터
        min_so_far = float('inf')
        for count in sorted_counts:
            cur = pct_stats[count][self.pct_representative]
            if cur > min_so_far:
                pct_stats[count][self.pct_representative] = min_so_far
                pct_stats[count]['monotonicity_corrected'] = True
            else:
                min_so_far = cur
                pct_stats[count]['monotonicity_corrected'] = False
        return pct_stats

    # ── 결과 레코드 빌드 ────────────────────────────────────────────

    def _build_criteria_record(self, condition_vars, subset, min_count,
                               criteria_str, pct_stats, label):
        """개별 성공기준 탐색 결과 레코드 생성"""
        n = len(subset)
        if n >= 10:
            confidence = "HIGH"
        elif n >= 5:
            confidence = "MEDIUM"
        elif n >= 3:
            confidence = "LOW"
        else:
            confidence = "INSUFFICIENT"

        return {
            "label":           label,
            "condition_vars":  condition_vars or {},
            "n_scenarios":     n,
            "min_count":       min_count,
            "criteria_str":    criteria_str,
            "pct_at_criteria": pct_stats.get(min_count, {}) if min_count is not None else {},
            "confidence":      confidence,
            "pct_stats_all":   pct_stats,
        }

    def _make_fallback(self, condition_dict, global_result):
        """샘플 부족 시 글로벌 기준으로 fallback"""
        return {
            "label":           str(condition_dict),
            "condition_vars":  condition_dict,
            "n_scenarios":     0,
            "min_count":       global_result['min_count'],
            "criteria_str":    global_result['criteria_str'] + " [FALLBACK]",
            "pct_at_criteria": {},
            "confidence":      "INSUFFICIENT",
            "pct_stats_all":   {},
        }

    # ── 이진 매핑 ──────────────────────────────────────────────────

    def _binary_col_name(self):
        """이진 변환 컬럼명 생성 (예: PRHRS_count → PRHRS_binary)"""
        return self.target_col.replace('_count', '_binary')

    def _build_binary_mapping(self, conditional_results, global_result):
        """
        조건 튜플 → N값 매핑 딕셔너리 생성

        Returns
        -------
        dict
            예: {("Success",): 2, ("Fail",): 3}
        """
        if not conditional_results:
            return {(): global_result['min_count']}
        return {
            tuple(r['condition_vars'].values()): r['min_count']
            for r in conditional_results
        }

    def _apply_binary_mapping(self, binary_mapping):
        """PRHRS_binary 컬럼 생성 (Success / Fail)"""
        def classify_row(row):
            if self.condition_vars:
                key = tuple(row[v] for v in self.condition_vars)
            else:
                key = ()
            n_threshold = binary_mapping.get(key)
            if n_threshold is None:
                # 성공기준 미정의 = 노심 보호 불가 → 안전 측 "Fail" 처리
                # (설계 문서 7.3절: 해당 브랜치 전체 CD로 종결)
                return "Fail"
            if n_threshold == 0:
                return "Success"
            return "Success" if row[self.target_col] >= n_threshold else "Fail"

        return self.df.apply(classify_row, axis=1)

    # ── 최종 결과 조립 ─────────────────────────────────────────────

    def _assemble_result(self, global_result, conditional_results, binary_mapping):
        """최종 결과 딕셔너리 조립"""
        return {
            "metadata": {
                "target_system":    self.target_col,
                "system_capacity":  self.M,
                "mode":             self.mode,
                "pct_limit_K":      self.pct_limit,
                "margin_pct":       self.margin * 100,
                "pct_threshold_K":  self.pct_threshold,
                "pct_representative": self.pct_representative,
                "n_total":          len(self.df),
            },
            "global_criteria":      global_result,
            "conditional_criteria": conditional_results,
            "binary_mapping":       binary_mapping,
            "df_with_binary":       self.df,
        }


# ── 편의 함수 ──────────────────────────────────────────────────────

def find_success_criteria(df, condition_vars=None, mode='optimization',
                          margin=0.20, pct_representative='p95',
                          min_samples=5, **kwargs):
    """
    성공기준 탐색 편의 함수

    Parameters
    ----------
    df : pd.DataFrame
    condition_vars : list[str], optional
    mode : str
    margin : float
    pct_representative : str
    min_samples : int

    Returns
    -------
    dict : 탐색 결과
    """
    return SuccessCriteriaFinder(
        df=df,
        condition_vars=condition_vars,
        mode=mode,
        margin=margin,
        pct_representative=pct_representative,
        min_samples=min_samples,
        **kwargs
    ).run()


def _print_pct_line(s, indent="    "):
    """PCT 통계를 안전하게 포맷하여 출력"""
    def _fmt(key):
        v = s.get(key)
        return f"{v:.1f}" if isinstance(v, (int, float)) else "N/A"
    print(f"{indent}PCT@기준: mean={_fmt('mean')} K, "
          f"p95={_fmt('p95')} K, max={_fmt('max')} K")


def print_criteria_report(result):
    """성공기준 탐색 결과를 콘솔에 출력"""
    meta = result['metadata']
    print("=" * 70)
    print(f"  성공기준 탐색 결과 보고서")
    print("=" * 70)
    print(f"  대상 계통:     {meta['target_system']}")
    print(f"  계통 용량:     {meta['system_capacity']}")
    print(f"  탐색 모드:     {meta['mode']}")
    print(f"  PCT 한계치:    {meta['pct_limit_K']:.1f} K")
    print(f"  마진:          {meta['margin_pct']:.1f}%")
    print(f"  PCT 임계값:    {meta['pct_threshold_K']:.1f} K")
    print(f"  대표값 정책:   {meta['pct_representative']}")
    print(f"  총 시나리오:   {meta['n_total']}")
    print("-" * 70)

    gc = result['global_criteria']
    print(f"\n  [글로벌 성공기준]")
    print(f"    기준: {gc['criteria_str']}  (신뢰도: {gc['confidence']}, n={gc['n_scenarios']})")
    if gc['pct_at_criteria']:
        s = gc['pct_at_criteria']
        _print_pct_line(s, indent="    ")

    if result['conditional_criteria']:
        print(f"\n  [조건부 성공기준]")
        for crit in result['conditional_criteria']:
            cond_str = ', '.join(f"{k}={v}" for k, v in crit['condition_vars'].items())
            print(f"    {cond_str}")
            print(f"      → {crit['criteria_str']}  "
                  f"(신뢰도: {crit['confidence']}, n={crit['n_scenarios']})")
            if crit['pct_at_criteria']:
                _print_pct_line(crit['pct_at_criteria'], indent="      ")

    bm = result['binary_mapping']
    print(f"\n  [이진 매핑]")
    for key, val in bm.items():
        key_str = ', '.join(str(k) for k in key) if key else "전체"
        if val is None:
            print(f"    {key_str} → 노심 보호 불가 (전체 Fail)")
        else:
            print(f"    {key_str} → count ≥ {val} → Success")

    df_bin = result['df_with_binary']
    binary_col = [c for c in df_bin.columns if c.endswith('_binary')]
    if binary_col:
        col = binary_col[0]
        print(f"\n  [이진 변환 결과 ({col})]")
        vc = df_bin[col].value_counts()
        for val, cnt in vc.items():
            print(f"    {val}: {cnt}건 ({cnt/len(df_bin)*100:.1f}%)")

    print("=" * 70)


# ── CLI 실행 ────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='SMART100 PSA 성공기준 자동 탐색')
    parser.add_argument('csv', help='입력 CSV 파일 경로')
    parser.add_argument('--mode', choices=['optimization', 'conservative'],
                        default='optimization', help='탐색 모드 (기본: optimization)')
    parser.add_argument('--margin', type=float, default=0.20,
                        help='PCT 안전 여유도 (기본: 0.20)')
    parser.add_argument('--representative', choices=['p95', 'mean', 'max'],
                        default='p95', help='PCT 대표값 정책 (기본: p95)')
    parser.add_argument('--min-samples', type=int, default=5,
                        help='최소 샘플 수 (기본: 5)')
    parser.add_argument('--conditions', nargs='*', default=['Reactor_Trip'],
                        help='앞 계통 조건 변수 (기본: Reactor_Trip)')
    args = parser.parse_args()

    df = pd.read_csv(args.csv)
    result = SuccessCriteriaFinder(
        df=df,
        condition_vars=args.conditions,
        mode=args.mode,
        margin=args.margin,
        pct_representative=args.representative,
        min_samples=args.min_samples,
    ).run()

    print_criteria_report(result)
