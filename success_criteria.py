# -*- coding: utf-8 -*-
"""
=============================================================================
SMART100 PSA 성공기준 자동 탐색 알고리즘 (Success Criteria Finder)
=============================================================================
설계 문서: 분석_1_성공기준_알고리즘_설계.md

기능:
  - MARS-KS 시뮬레이션 결과(CSV)에서 PCT 응답을 기반으로
    안전계통(PRHRS 등)의 성공기준(N/M)을 데이터 주도적으로 자동 탐색
  - 최적화 모드: 조건별로 독립적인 완화된(최소 N) 성공기준 탐색
                 → ET 분기마다 다른 N 적용
  - 보수적 모드: 조건별 최소 N들의 envelope(최대값)를 단일 통일 기준으로 채택
                 → ET 전체에서 동일한 N 적용 (가장 엄격한 조건이 모든 조건 커버)
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
        'optimization' : 조건별로 독립적인 최소 N 적용 (ET 분기마다 상이 가능)
        'conservative' : 조건별 최소 N들의 max(envelope)를 전 조건에 통일 적용
                         (가장 엄격한 조건이 모든 조건을 자동 커버)
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

        # PCT 임계값 계산 (두 모드 공통: margin 적용)
        # - optimization: 조건별 최소 N 탐색 시 사용
        # - conservative: 조건별 최소 N 탐색 후 max(N_i) 를 통일 기준으로 채택
        #   → margin=0.0 으로 호출하면 엄격한 보수 기준, 기본값(0.20)이면 마진 반영 보수 기준
        self.pct_threshold = pct_limit * (1.0 - margin)

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

        # 3. Conservative envelope: 조건별 min_count의 max를 통일 기준으로 채택
        envelope_info = None
        if self.mode == 'conservative' and conditional_results:
            global_result, envelope_info = self._apply_conservative_envelope(
                conditional_results, global_result
            )

        # 4. 이진 매핑 및 컬럼 추가
        binary_mapping = self._build_binary_mapping(conditional_results, global_result)
        self.df[self._binary_col_name()] = self._apply_binary_mapping(binary_mapping)
        # 사람이 읽기 쉬운 라벨 컬럼 추가: "Success (3/4)" 형식
        # (ET 분기는 PRHRS_binary 를, 리포트/대시보드 표시는 PRHRS_binary_label 을 사용)
        self.df[self._binary_label_col_name()] = self._build_binary_labels()

        return self._assemble_result(
            global_result, conditional_results, binary_mapping, envelope_info
        )

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
        """subset(전체 또는 조건부) 레벨에서 최소 N 탐색.

        두 모드 모두 optimization 로직(최소 N 탐색)을 공유한다.
        conservative 모드의 '엄격함'은 run() 마지막 단계에서 조건별 결과의
        envelope(max)를 글로벌 기준으로 채택하는 방식으로 구현된다.
        """
        return self._find_criteria_optimization(subset, label, condition_vars)

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

    # ── Conservative envelope (조건부 결과 통합) ────────────────────

    def _apply_conservative_envelope(self, conditional_results, global_result):
        """
        조건별 최소 N들의 envelope(max)를 단일 통일 기준으로 채택.

        원칙:
          "N=3이 N=2 조건을 자동 커버하므로, 가장 엄격한 N을 모든 조건의
           단일 성공기준으로 통일하면 ET 전 분기에 대해 안전 측 보장이 된다."

        처리 규칙:
          - 조건별 min_count 값들 중 max를 unified_count 로 선택
          - min_count=None(노심 보호 불가)이 하나라도 있으면 unified=None
            (안전 측: 전체 브랜치를 Fail 로 처리)
          - min_count=0(계통 불필요)은 envelope 후보에 포함되나 max 선택에서
            자연스럽게 배제됨

        Returns
        -------
        (envelope_global, envelope_info) : tuple
            envelope_global : 기존 global_result 를 envelope 기준으로 덮어쓴 레코드
            envelope_info   : 통합 과정 메타정보 (조건별 원래 N, 선정 N)
        """
        per_condition = [
            {"condition_vars": r['condition_vars'], "min_count": r['min_count']}
            for r in conditional_results
        ]
        counts = [r['min_count'] for r in conditional_results]

        if any(c is None for c in counts):
            unified_count = None
            criteria_str = "None (일부 조건에서 노심 보호 불가 → 전체 Fail)"
        else:
            unified_count = max(counts)
            if unified_count == 0:
                criteria_str = f"0/{self.M} (모든 조건에서 PRHRS 불필요)"
            else:
                criteria_str = (f"{unified_count}/{self.M} "
                                f"(envelope of conditional criteria)")

        envelope_global = dict(global_result)
        envelope_global.update({
            "label":        "CONSERVATIVE_ENVELOPE",
            "min_count":    unified_count,
            "criteria_str": criteria_str,
        })

        envelope_info = {
            "per_condition":  per_condition,
            "unified_count":  unified_count,
            "criteria_str":   criteria_str,
        }
        return envelope_global, envelope_info

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

    def _binary_label_col_name(self):
        """이진 라벨 컬럼명 생성 (예: PRHRS_count → PRHRS_binary_label)"""
        return self.target_col.replace('_count', '_binary_label')

    def _build_binary_labels(self):
        """PRHRS_binary_label 값 생성: '{Success|Fail} ({count}/{M})' 형식.

        예) PRHRS_count=3, PRHRS_binary=Success → "Success (3/4)"
            PRHRS_count=1, PRHRS_binary=Fail    → "Fail (1/4)"
        """
        binary_col = self._binary_col_name()

        def _fmt(row):
            status = row[binary_col]
            try:
                n = int(row[self.target_col])
            except (ValueError, TypeError):
                return str(status)
            return f"{status} ({n}/{self.M})"

        return self.df.apply(_fmt, axis=1)

    def _build_binary_mapping(self, conditional_results, global_result):
        """
        조건 튜플 → N값 매핑 딕셔너리 생성

        모드별 동작:
          - optimization : 조건별 독립 N (예: {("Success",): 2, ("Fail",): 3})
          - conservative : 모든 조건에 envelope N 일괄 적용
                           (예: {("Success",): 3, ("Fail",): 3})
        """
        if not conditional_results:
            return {(): global_result['min_count']}

        if self.mode == 'conservative':
            unified_n = global_result['min_count']
            return {
                tuple(r['condition_vars'].values()): unified_n
                for r in conditional_results
            }

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

    def _assemble_result(self, global_result, conditional_results,
                         binary_mapping, envelope_info=None):
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
            "envelope_info":        envelope_info,  # conservative 모드일 때만 비어있지 않음
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

    env = result.get('envelope_info')
    if env is not None:
        print(f"\n  [Conservative Envelope (조건부 → 통일 기준)]")
        for item in env['per_condition']:
            cond_str = ', '.join(f"{k}={v}" for k, v in item['condition_vars'].items())
            mc = item['min_count']
            mc_str = f"{mc}/{meta['system_capacity']}" if mc is not None else "None"
            print(f"    {cond_str}: 조건부 N = {mc_str}")
        print(f"    → 통일 N (envelope) = {env['criteria_str']}")
        print(f"      (모든 조건에 동일 N 적용 → ET 전 분기 단일 성공기준)")

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


# ── 파이프라인 ─────────────────────────────────────────────────────

def run_pipeline(csv_paths, mode='optimization', margin=0.20,
                 pct_representative='p95', min_samples=5,
                 condition_vars=None, template_path=None,
                 output_dir='pipeline_results'):
    """
    전체 파이프라인 실행:
    psa_analyzer CSV → 성공기준 탐색 → Binary ET 생성 → Dashboard 로딩

    Parameters
    ----------
    csv_paths : list[str|Path]
        psa_analyzer 출력 CSV 파일 경로 목록
    mode : str
        'optimization' 또는 'conservative'
    margin : float
        PCT 안전 여유도 (기본: 0.20)
    pct_representative : str
        'p95' | 'mean' | 'max'
    min_samples : int
        최소 샘플 수
    condition_vars : list[str]
        앞 계통 조건 변수 (기본: ['Reactor_Trip'])
    template_path : str|Path, optional
        Dashboard 템플릿 xlsx 경로 (None이면 Dashboard 단계 건너뜀)
    output_dir : str|Path
        결과 저장 기본 폴더

    Returns
    -------
    dict : 사고유형별 {scenario_name: criteria_result}

    사용 예시
    ---------
    >>> from success_criteria import run_pipeline
    >>> run_pipeline(
    ...     csv_paths=['lofw_results.csv', 'sgtr_results.csv'],
    ...     mode='optimization',
    ...     template_path='PSA_DET_Dashboard_Template.xlsx',
    ... )
    """
    from pathlib import Path
    from et_generator import ET_Generator, DEFAULT_HEADINGS, HEADINGS_BY_TYPE

    # 컬럼명 정규화 (et_generator.RENAME_MAP과 동일)
    RENAME_MAP = {
        'PRHRS_HX_count': 'PRHRS_count',
        'RT_status':       'Reactor_Trip',
        'RCP_status':      'RCP_Status',
        'PCT_K':           'PCT_max',
        'State':           'Outcome',
    }

    output_dir = Path(output_dir)
    binary_dir = output_dir / 'binary_csv'
    et_dir     = output_dir / 'et_results'
    binary_dir.mkdir(parents=True, exist_ok=True)

    if condition_vars is None:
        condition_vars = ['Reactor_Trip']

    print("=" * 70)
    print("SMART100 PSA 파이프라인")
    print(f"  모드: {mode} | 마진: {margin*100:.0f}% | 대표값: {pct_representative}")
    print("=" * 70)

    # ── Phase 1: 성공기준 탐색 + Binary CSV 생성 ─────────────────
    print(f"\n{'─'*70}")
    print("Phase 1: 성공기준 탐색")
    print('─' * 70)

    binary_csv_paths = []
    criteria_results = {}
    custom_headings  = {}

    for csv_path in [Path(p) for p in csv_paths]:
        print(f"\n  [{csv_path.name}]")

        # CSV 로드 (인코딩 자동 감지)
        df = None
        for enc in ('utf-8-sig', 'cp949', 'euc-kr', 'utf-8', 'latin-1'):
            try:
                df = pd.read_csv(csv_path, encoding=enc)
                break
            except (UnicodeDecodeError, Exception):
                continue
        if df is None:
            print(f"    CSV 인코딩 감지 실패 → 건너뜀")
            continue

        # 컬럼명 정규화 (demo_dataset_generator 출력 호환)
        df = df.rename(columns=RENAME_MAP)

        scenario_name = (csv_path.stem
                         .replace('_results', '')
                         .replace('__6_', '')
                         .upper())

        # PRHRS_count 없는 사고유형은 성공기준 탐색 건너뜀
        target_col = 'PRHRS_count'
        if target_col not in df.columns:
            print(f"    {target_col} 컬럼 없음 → 원본 그대로 전달")
            binary_csv = binary_dir / csv_path.name
            df.to_csv(binary_csv, index=False, encoding='utf-8-sig')
            binary_csv_paths.append(binary_csv)
            continue

        # 성공기준 탐색
        result = SuccessCriteriaFinder(
            df, target_system=target_col,
            condition_vars=condition_vars,
            mode=mode, margin=margin,
            pct_representative=pct_representative,
            min_samples=min_samples
        ).run()

        criteria_results[scenario_name] = result
        print_criteria_report(result)

        # Binary CSV 저장 (원본 파일명 유지, 별도 폴더)
        df_binary = result['df_with_binary']
        binary_csv = binary_dir / csv_path.name
        df_binary.to_csv(binary_csv, index=False, encoding='utf-8-sig')
        binary_csv_paths.append(binary_csv)
        print(f"  → Binary CSV: {binary_csv}")

        # Binary headings 구성 (PRHRS_count → PRHRS_binary 교체)
        original_headings = (HEADINGS_BY_TYPE.get(scenario_name)
                             or DEFAULT_HEADINGS)
        binary_headings = []
        for h in original_headings:
            binary_col = h.replace('_count', '_binary')
            if binary_col != h and binary_col in df_binary.columns:
                binary_headings.append(binary_col)
            else:
                binary_headings.append(h)
        custom_headings[scenario_name] = binary_headings
        print(f"  → 헤딩: {binary_headings}")

    if not binary_csv_paths:
        print("\n처리할 CSV 파일이 없습니다.")
        return criteria_results

    # ── Phase 2: Binary ET 생성 ──────────────────────────────────
    print(f"\n{'─'*70}")
    print("Phase 2: Binary ET 생성")
    print('─' * 70)

    et_gen = ET_Generator(output_dir=str(et_dir))
    et_gen.run_all(
        [str(p) for p in binary_csv_paths],
        custom_headings=custom_headings
    )

    # ── Phase 3: Dashboard 로딩 (선택) ───────────────────────────
    if template_path is not None:
        template_path = Path(template_path)
        if not template_path.exists():
            print(f"\nDashboard 템플릿 없음: {template_path}")
        else:
            print(f"\n{'─'*70}")
            print("Phase 3: Dashboard 로딩")
            print('─' * 70)

            from load_to_dashboard import run_all as load_dashboard
            et_files = sorted(et_dir.glob('*_ET_result.xlsx'))
            if et_files:
                dash_dir = output_dir / 'dashboard_results'
                load_dashboard(et_files, template_path, dash_dir)
            else:
                print("  ET 결과 파일이 없습니다.")

    # ── 완료 ─────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("파이프라인 완료")
    print(f"  Binary CSV: {binary_dir}")
    print(f"  ET 결과:    {et_dir}")
    if template_path is not None:
        print(f"  Dashboard:  {output_dir / 'dashboard_results'}")
    print('=' * 70)

    return criteria_results


# ── CLI 실행 ────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description='SMART100 PSA 성공기준 자동 탐색 / 파이프라인',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""사용 예시:
  # 단독 분석
  python success_criteria.py lofw_results.csv
  python success_criteria.py lofw_results.csv --mode conservative

  # 파이프라인 (성공기준 → Binary ET → Dashboard)
  python success_criteria.py --pipeline lofw_results.csv sgtr_results.csv
  python success_criteria.py --pipeline data/ -t template.xlsx -o results/
"""
    )
    parser.add_argument(
        'inputs', nargs='+',
        help='CSV 파일 또는 폴더 경로'
    )
    parser.add_argument(
        '--mode', choices=['optimization', 'conservative'],
        default='optimization', help='탐색 모드 (기본: optimization)'
    )
    parser.add_argument(
        '--margin', type=float, default=0.20,
        help='PCT 안전 여유도 (기본: 0.20)'
    )
    parser.add_argument(
        '--representative', choices=['p95', 'mean', 'max'],
        default='p95', help='PCT 대표값 정책 (기본: p95)'
    )
    parser.add_argument(
        '--min-samples', type=int, default=5,
        help='최소 샘플 수 (기본: 5)'
    )
    parser.add_argument(
        '--conditions', nargs='*', default=['Reactor_Trip'],
        help='앞 계통 조건 변수 (기본: Reactor_Trip)'
    )
    parser.add_argument(
        '--pipeline', action='store_true',
        help='전체 파이프라인 실행 (성공기준 → ET 생성 → Dashboard)'
    )
    parser.add_argument(
        '-t', '--template',
        help='Dashboard 템플릿 xlsx 경로 (--pipeline 모드에서 사용)'
    )
    parser.add_argument(
        '-o', '--output', default='pipeline_results',
        help='파이프라인 결과 저장 폴더 (기본: pipeline_results/)'
    )
    args = parser.parse_args()

    # CSV 파일 수집
    csv_files = []
    for inp in args.inputs:
        p = Path(inp)
        if p.is_dir():
            csv_files.extend(sorted(p.glob('*.csv')))
        elif p.suffix.lower() == '.csv' and p.exists():
            csv_files.append(p)
        else:
            print(f"경고: '{inp}' → CSV 파일이 아니거나 존재하지 않습니다.")

    if not csv_files:
        print("처리할 CSV 파일이 없습니다.")
        exit(1)

    if args.pipeline:
        # 파이프라인 모드
        run_pipeline(
            csv_paths=csv_files,
            mode=args.mode,
            margin=args.margin,
            pct_representative=args.representative,
            min_samples=args.min_samples,
            condition_vars=args.conditions,
            template_path=args.template,
            output_dir=args.output,
        )
    else:
        # 단독 분석 모드
        for csv_file in csv_files:
            print(f"\n{'─'*70}")
            print(f"분석: {csv_file.name}")
            print('─' * 70)
            df = pd.read_csv(csv_file)
            result = SuccessCriteriaFinder(
                df=df,
                condition_vars=args.conditions,
                mode=args.mode,
                margin=args.margin,
                pct_representative=args.representative,
                min_samples=args.min_samples,
            ).run()
            print_criteria_report(result)
