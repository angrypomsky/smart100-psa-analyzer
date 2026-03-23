# -*- coding: utf-8 -*-
# SMART100 PSA Analyzer Ver.2
# 변수명 파일 기반 자동 매핑 + PRHRS 상대 비교 알고리즘
#
# Ver.1 대비 변경사항:
#   - VarMapper: 변수명 파일에서 역할별 pandas 컬럼명 자동 추출
#   - _check_prhrs_count: 절대 임계값 → 상대 비교 (max × RATIO)
#   - 각 사고유형별 PRHRS 파라미터를 클래스 변수로 선언 (코드 중복 제거)

import pandas as pd
import numpy as np
from pathlib import Path
import tkinter as tk
from tkinter import filedialog


def _pick_files(title, multiple=True):
    """tkinter GUI로 파일 선택 → 경로 리스트 반환"""
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    ftypes = [('Excel files', '*.xlsx *.xls'), ('All files', '*.*')]
    if multiple:
        paths = filedialog.askopenfilenames(title=title, filetypes=ftypes)
    else:
        p = filedialog.askopenfilename(title=title, filetypes=ftypes)
        paths = [p] if p else []
    root.destroy()
    return list(paths)


# ============================================================
# VarMapper
# ============================================================

class VarMapper:
    """
    변수명 파일 → 역할별 pandas 컬럼명 자동 매핑

    변수명 파일 구조 (MARS-KS 출력 기준):
      col0: vartype     (cntrlvar, mflowj, httemp, pmphead, ...)
      col1: var_id      (307, 308, 120000803, ...)
      col2: (빈 컬럼)
      col3: description (영문 자연어 설명)

    pandas 컬럼명 규칙:
      같은 vartype의 첫 번째 등장 = vartype
      이후 등장 순서대로          = vartype.1, vartype.2, ...

    ROLE_KEYWORDS:
      역할명 → 설명에서 찾을 키워드 목록 (모두 포함 시 해당 역할로 분류)
      다른 노형을 추가할 때 이 딕셔너리만 조정하면 됨
    """

    ROLE_KEYWORDS = {
        'PRHRS_HX': [['PRHRS HX']],       # PRHRS 열교환기 열출력 (4개)
        'PCT':      [['cladding temp']],   # 연료 피복재 온도
        'RCP_HEAD': [['RCP', 'head']],     # RCP 펌프 헤드
    }

    def __init__(self, path):
        self.path   = Path(path)
        self.col_map = {}   # role → [pandas_col, ...]
        self.full_df = None
        self._load()

    def _load(self):
        raw = pd.read_excel(self.path, header=None)

        # pandas 컬럼명 생성: 출현 순서 기반
        counts    = {}
        col_names = []
        for vartype in raw.iloc[:, 0]:
            v = str(vartype)
            if v not in counts:
                counts[v] = 0
                col_names.append(v)
            else:
                counts[v] += 1
                col_names.append(f'{v}.{counts[v]}')

        self.full_df = pd.DataFrame({
            'pandas_col':  col_names,
            'vartype':     raw.iloc[:, 0].astype(str),
            'var_id':      raw.iloc[:, 1],
            'description': raw.iloc[:, 3].fillna('').astype(str),
        })

        # 역할별 키워드 매핑
        for role, keyword_groups in self.ROLE_KEYWORDS.items():
            matched = []
            for keywords in keyword_groups:
                mask = self.full_df['description'].apply(
                    lambda d: all(k.lower() in d.lower() for k in keywords)
                )
                matched.extend(self.full_df.loc[mask, 'pandas_col'].tolist())
            self.col_map[role] = matched

    def get(self, role):
        """역할에 해당하는 pandas 컬럼명 리스트 반환"""
        return self.col_map.get(role, [])

    def available_cols(self, role, df):
        """실제 DataFrame에 존재하는 컬럼만 필터링하여 반환"""
        return [c for c in self.get(role) if c in df.columns]

    def summary(self):
        print('\n  [VarMapper 매핑 결과]')
        for role, cols in self.col_map.items():
            descs = self.full_df.loc[
                self.full_df['pandas_col'].isin(cols), 'description'
            ].tolist()
            print(f'    {role}: {cols}')
            for col, desc in zip(cols, descs):
                print(f'      └ {col}: {desc}')


# ============================================================
# BaseAnalyzer
# ============================================================

class BaseAnalyzer:
    """
    공통 베이스 클래스 (Ver.2)

    PRHRS 검출 파라미터 (서브클래스에서 오버라이드):
      PRHRS_FLOOR      최소 작동 임계값 (W) — 이 미만이면 전부 꺼진 것으로 판정
      PRHRS_RATIO      상대 비교 비율 — 최대값 × RATIO 이상이면 작동 계통으로 판정
      PRHRS_WAIT       RT 이후 판정 대기 시간 (s)
      PRHRS_USE_PEAK   True: 피크값 기준, False: 평균값 기준
      PRHRS_TAIL_FRAC  None: 전체 평균, float: 후반 N% 평균 (예: 0.3 = 후반 30%)
      PRHRS_CORRECTION 계통수 보정값 (SGTR: -1, 나머지: 0)
    """

    ACCIDENT_TYPE = 'Unknown'
    CD_THRESHOLD  = 1477  # NRC 규제 기준 PCT Core Damage 판정 (K)

    # PRHRS 검출 파라미터 기본값
    PRHRS_FLOOR      = 1e4   # W
    PRHRS_RATIO      = 0.1   # 10%
    PRHRS_WAIT       = 100   # s
    PRHRS_USE_PEAK   = False
    PRHRS_TAIL_FRAC  = None
    PRHRS_CORRECTION = 0

    def __init__(self):
        self.var_mapper    = None
        self.scenarios_data = []
        print('=' * 70)
        print(f'SMART100 {self.ACCIDENT_TYPE} Analyzer  Ver.2')
        print('=' * 70)
        print('\n사용 순서:')
        print('  1. analyzer.step1_load_mapping()  → 변수명 파일 선택')
        print('  2. analyzer.step2_upload_files()  → 시나리오 파일들 선택')
        print('  3. analyzer.show_results()        → 결과 확인')
        print('  4. analyzer.save_results()        → CSV 저장')
        print('=' * 70)

    # ── Step 1: 변수명 파일 로드 ──────────────────────────────

    def step1_load_mapping(self, path=None):
        print(f'\n{"="*70}')
        print('Step 1: 변수명 파일 선택')
        print(f'{"="*70}')
        if path is None:
            paths = _pick_files('변수명 파일 선택 (smart100데이터_변수명_확인.xlsx)', multiple=False)
            if not paths:
                print('❌ 파일이 선택되지 않았습니다.')
                return
            path = paths[0]
        self.var_mapper = VarMapper(path)
        print(f'✓ 변수명 파일 로드: {Path(path).name}')
        self.var_mapper.summary()
        print('\n▶ 다음: analyzer.step2_upload_files()')

    # ── Step 2: 시나리오 파일 분석 ───────────────────────────

    def step2_upload_files(self):
        if self.var_mapper is None:
            print('❌ 먼저 step1_load_mapping()을 실행하세요.')
            return
        print(f'\n{"="*70}')
        print(f'Step 2: {self.ACCIDENT_TYPE} 시나리오 파일 선택')
        print(f'{"="*70}')
        paths = _pick_files('시나리오 파일 선택 (여러 개 가능)')
        if not paths:
            print('❌ 파일이 선택되지 않았습니다.')
            return
        print(f'\n✓ {len(paths)}개 파일 선택 완료')
        print('-' * 70)
        for filepath in paths:
            filename = Path(filepath).name
            print(f'  {filename}...', end=' ')
            try:
                df_raw = pd.read_excel(filepath)
                df_raw = df_raw.dropna(subset=['time'])
                df     = df_raw.iloc[2:].copy()
                df['time'] = pd.to_numeric(df['time'])
                for c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors='coerce')
                result = self._analyze_single(filename, df)
                self.scenarios_data.append(result)
                self._print_result(result)
            except Exception as e:
                print(f'✗ 오류: {e}')
        print(f'\n{"="*70}')
        print(f'✓ 분석 완료: {len(self.scenarios_data)}개 시나리오')
        print('\n▶ 다음: analyzer.show_results()')

    # ── 역할별 컬럼 조회 ──────────────────────────────────────

    def _hx_cols(self, df):
        return self.var_mapper.available_cols('PRHRS_HX', df)

    def _pct_cols(self, df):
        return self.var_mapper.available_cols('PCT', df)

    def _rcp_cols(self, df):
        return self.var_mapper.available_cols('RCP_HEAD', df)

    # ── 공통 분석 로직 ────────────────────────────────────────

    def _analyze_single(self, filename, df):
        scenario_name     = Path(filename).stem
        rt_time           = self._detect_rt(df)
        reactor_trip      = 'Success' if rt_time < df['time'].max() * 0.99 else 'Fail'
        rcp_status        = self._check_rcp_status(df, rt_time)
        prhrs_count       = self._check_prhrs_count(df, rt_time)
        pct_max, pct_time = self._calculate_pct(df, rt_time)
        outcome           = 'CD' if pct_max >= self.CD_THRESHOLD else 'OK'
        return {
            'Scenario':         scenario_name,
            'Reactor_Trip':     reactor_trip,
            'RCP_Status':       rcp_status,
            'PRHRS_count':      prhrs_count,
            'ADS_BLEED_count':  'N/A',
            'PSIS_FEED_status': 'N/A',
            'SIT_Refill_time':  'N/A',
            'PCT_max':          pct_max,
            'PCT_time':         pct_time,
            'Outcome':          outcome,
        }

    def _print_result(self, result):
        print(f'✓ PRHRS={result["PRHRS_count"]}계통, '
              f'PCT={result["PCT_max"]:.1f}K @ {result["PCT_time"]:.0f}s, '
              f'{result["Outcome"]}')

    def _check_rcp_status(self, df, rt_time):
        rcp_cols = self._rcp_cols(df)
        if not rcp_cols:
            return 'Unknown'
        df_after = df[(df['time'] > rt_time) & (df['time'] < rt_time + 200)]
        if len(df_after) == 0:
            return 'Unknown'
        avg_head = df_after[rcp_cols].mean().mean()
        if avg_head > 1000:
            return 'Running'
        elif avg_head > -200:
            return 'Coast-down'
        else:
            return 'Natural Circulation'

    def _find_rt_for_pct(self, df):
        """
        PCT 계산용 RT 시점: 초기 출력 대비 90% 이상 감소한 첫 시점
        데이터가 RT 이후부터 시작(GTRN/LSSB/SGTR)하면 time.min() 반환
        """
        try:
            initial_power = float(df['rktpow'].iloc[0])
            threshold     = initial_power * 0.1  # 90% 감소 = 초기의 10% 이하
            trip_rows     = df[df['rktpow'] < threshold]
            if len(trip_rows) > 0:
                return float(trip_rows['time'].min())
        except Exception:
            pass
        return float(df['time'].min())

    def _calculate_pct(self, df, rt_time):
        """
        PCT 계산 — 출력 90% 감소 시점 이후 구간에서 피복재 온도 컬럼의 최대값
        변수명 파일에서 'cladding temp' 키워드로 자동 추출
        """
        pct_cols   = self._pct_cols(df)
        if not pct_cols:
            return 0.0, 0.0
        rt_for_pct = self._find_rt_for_pct(df)
        df_valid   = df[df['time'] >= rt_for_pct].copy()
        df_valid   = df_valid[(df_valid[pct_cols] < 10000).all(axis=1)]
        if len(df_valid) == 0:
            return 0.0, 0.0
        df_valid['pct_row_max'] = df_valid[pct_cols].max(axis=1)
        pct_max  = df_valid['pct_row_max'].max()
        pct_time = df_valid.loc[df_valid['pct_row_max'].idxmax(), 'time']
        return float(pct_max), float(pct_time)

    def _check_prhrs_count(self, df, rt_time):
        """
        PRHRS 작동 계통수 판정 — 상대 비교 알고리즘

        알고리즘:
          1. RT 이후 PRHRS_WAIT 초 대기
          2. 4개 HX 값을 집계 (PEAK / TAIL평균 / 전체평균 중 선택)
          3. max_val < PRHRS_FLOOR → 0계통 (아무것도 작동 안 함)
          4. val >= max_val × PRHRS_RATIO → 해당 계통 작동으로 판정
          5. PRHRS_CORRECTION 보정 적용

        예시 (RATIO=0.1):
          [1e6, 1e2, 1e2, 1e2] → max=1e6, 기준=1e5 → 1계통
          [1e6, 9e5, 8e5, 1e2] → max=1e6, 기준=1e5 → 3계통
          [1e2, 1e2, 1e2, 1e2] → max=1e2 < FLOOR   → 0계통
        """
        hx_cols = self._hx_cols(df)
        if not hx_cols:
            return -1

        df_after = df[df['time'] > rt_time + self.PRHRS_WAIT]
        if len(df_after) == 0:
            return 0

        # 집계 방식 선택
        if self.PRHRS_USE_PEAK:
            vals = df_after[hx_cols].max()
        elif self.PRHRS_TAIL_FRAC is not None:
            tail_n = max(1, int(len(df_after) * self.PRHRS_TAIL_FRAC))
            vals = df_after[hx_cols].tail(tail_n).mean()
        else:
            vals = df_after[hx_cols].mean()

        # 상대 비교
        max_val = vals.max()
        if max_val < self.PRHRS_FLOOR:
            return 0
        count = int((vals >= max_val * self.PRHRS_RATIO).sum())
        return max(0, count + self.PRHRS_CORRECTION)

    def _detect_rt(self, df):
        raise NotImplementedError(f'{self.__class__.__name__}에서 _detect_rt()를 구현하세요.')

    # ── 결과 출력 / 저장 ──────────────────────────────────────

    def show_results(self):
        if not self.scenarios_data:
            print('❌ 분석된 시나리오가 없습니다.')
            return None
        df = pd.DataFrame(self.scenarios_data)
        print(f'\n{"="*70}')
        print(f'{self.ACCIDENT_TYPE} 분석 결과 요약')
        print(f'{"="*70}')
        print(f'총 시나리오:      {len(df)}개')
        print(f'OK:              {(df["Outcome"]=="OK").sum()}개')
        print(f'Core Damage(CD): {(df["Outcome"]=="CD").sum()}개')
        print(f'평균 PCT:         {df["PCT_max"].mean():.1f} K')
        print(f'최고 PCT:         {df["PCT_max"].max():.1f} K')
        print(f'\nPRHRS 계통수 분포:')
        print(df['PRHRS_count'].value_counts().sort_index().to_string())
        print(f'{"="*70}')
        return df

    def save_results(self, filename=None):
        if not self.scenarios_data:
            print('❌ 저장할 데이터가 없습니다.')
            return
        if filename is None:
            filename = f'{self.ACCIDENT_TYPE.lower()}_results.csv'
        df = pd.DataFrame(self.scenarios_data)
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f'✓ 저장 완료: {Path(filename).resolve()}')


# ============================================================
# LOFWAnalyzer
# ============================================================

class LOFWAnalyzer(BaseAnalyzer):
    """
    LOFW (Loss of Feedwater)
    - RT: 50초 고정
    - PRHRS: 전체 평균, WAIT=50s
    """
    ACCIDENT_TYPE = 'LOFW'
    PRHRS_WAIT    = 50

    def _detect_rt(self, df):
        return 50.0


# ============================================================
# SBLOCAAnalyzer
# ============================================================

class SBLOCAAnalyzer(BaseAnalyzer):
    """
    SBLOCA (Small Break LOCA)
    - RT: 초기 출력 5% 이하 시점 자동 감지
    - PRHRS: 전체 평균, WAIT=100s
    """
    ACCIDENT_TYPE = 'SBLOCA'

    def _detect_rt(self, df):
        initial_power = df.iloc[0]['rktpow']
        threshold     = initial_power * 0.05
        trip_rows     = df[df['rktpow'] < threshold]
        return float(trip_rows['time'].min()) if len(trip_rows) > 0 else float(df['time'].max())

    def _analyze_single(self, filename, df):
        result = super()._analyze_single(filename, df)
        result['RT_time'] = self._detect_rt(df)
        return result

    def _print_result(self, result):
        print(f'✓ RT={result["RT_time"]:.0f}s, PRHRS={result["PRHRS_count"]}계통, '
              f'PCT={result["PCT_max"]:.1f}K @ {result["PCT_time"]:.0f}s, '
              f'{result["Outcome"]}')

    def show_results(self):
        df = super().show_results()
        if df is not None and 'RT_time' in df.columns:
            print(f'\nRT 시간 분포 (s):')
            print(df['RT_time'].describe().to_string())
        return df


# ============================================================
# GTRNAnalyzer
# ============================================================

class GTRNAnalyzer(BaseAnalyzer):
    """
    GTRN (General Transient)
    - RT: 데이터가 RT 이후부터 저장 → time.min() 사용
    - PRHRS: 전체 평균, WAIT=100s
    - Reactor_Trip: 항상 Success
    """
    ACCIDENT_TYPE = 'GTRN'

    def _detect_rt(self, df):
        return float(df['time'].min())

    def _analyze_single(self, filename, df):
        scenario_name     = Path(filename).stem
        rt_time           = self._detect_rt(df)
        rcp_status        = self._check_rcp_status(df, rt_time)
        prhrs_count       = self._check_prhrs_count(df, rt_time)
        pct_max, pct_time = self._calculate_pct(df, rt_time)
        outcome           = 'CD' if pct_max >= self.CD_THRESHOLD else 'OK'
        return {
            'Scenario':         scenario_name,
            'Reactor_Trip':     'Success',
            'RCP_Status':       rcp_status,
            'PRHRS_count':      prhrs_count,
            'ADS_BLEED_count':  'N/A',
            'PSIS_FEED_status': 'N/A',
            'SIT_Refill_time':  'N/A',
            'PCT_max':          pct_max,
            'PCT_time':         pct_time,
            'Outcome':          outcome,
        }


# ============================================================
# LSSBAnalyzer
# ============================================================

class LSSBAnalyzer(BaseAnalyzer):
    """
    LSSB (Large Secondary Side Break)
    - RT: time.min() 사용
    - PRHRS: 후반 30% 평균 (초기 대형 과도현상 제외), WAIT=100s
    - 조기 종료: Note='EarlyTerm'
    """
    ACCIDENT_TYPE   = 'LSSB'
    PRHRS_TAIL_FRAC = 0.3   # 후반 30% 평균

    def _detect_rt(self, df):
        return float(df['time'].min())

    def _analyze_single(self, filename, df):
        scenario_name     = Path(filename).stem
        rt_time           = self._detect_rt(df)
        rcp_status        = self._check_rcp_status(df, rt_time)
        prhrs_count       = self._check_prhrs_count(df, rt_time)
        pct_max, pct_time = self._calculate_pct(df, rt_time)
        outcome           = 'CD' if pct_max >= self.CD_THRESHOLD else 'OK'
        note              = 'EarlyTerm' if df['time'].max() < 1000 else ''
        return {
            'Scenario':         scenario_name,
            'Reactor_Trip':     'Success',
            'RCP_Status':       rcp_status,
            'PRHRS_count':      prhrs_count,
            'ADS_BLEED_count':  'N/A',
            'PSIS_FEED_status': 'N/A',
            'SIT_Refill_time':  'N/A',
            'PCT_max':          pct_max,
            'PCT_time':         pct_time,
            'Outcome':          outcome,
            'Note':             note,
        }

    def _print_result(self, result):
        note = f' [{result["Note"]}]' if result.get('Note') else ''
        print(f'✓ PRHRS={result["PRHRS_count"]}계통, '
              f'PCT={result["PCT_max"]:.1f}K @ {result["PCT_time"]:.0f}s, '
              f'{result["Outcome"]}{note}')

    def show_results(self):
        if not self.scenarios_data:
            print('❌ 분석된 시나리오가 없습니다.')
            return None
        df = pd.DataFrame(self.scenarios_data)
        print(f'\n{"="*70}')
        print(f'LSSB 분석 결과 요약')
        print(f'{"="*70}')
        normal = (df['Note'] == '').sum() if 'Note' in df.columns else len(df)
        early  = (df['Note'] == 'EarlyTerm').sum() if 'Note' in df.columns else 0
        print(f'총 시나리오:      {len(df)}개  (정상:{normal} / 조기종료:{early})')
        print(f'OK:              {(df["Outcome"]=="OK").sum()}개')
        print(f'Core Damage(CD): {(df["Outcome"]=="CD").sum()}개')
        print(f'평균 PCT:         {df["PCT_max"].mean():.1f} K')
        print(f'최고 PCT:         {df["PCT_max"].max():.1f} K')
        print(f'\nPRHRS 계통수 분포:')
        print(df['PRHRS_count'].value_counts().sort_index().to_string())
        print(f'\n※ ADS/PSIS/SIT: plotfl 미포함 → N/A 처리')
        print(f'{"="*70}')
        return df


# ============================================================
# SGTRAnalyzer
# ============================================================

class SGTRAnalyzer(BaseAnalyzer):
    """
    SGTR (Steam Generator Tube Rupture)
    - RT: time.min() 사용
    - PRHRS: 피크값 기준, 파단 유로 HX 1개 차감 (CORRECTION=-1)
             → 상대 비교 알고리즘에서 파단 HX가 max가 되고
               나머지 작동 계통이 RATIO 기준을 충족하면 자연스럽게 분류됨
    - 조기 종료: Note='EarlyTerm'
    """
    ACCIDENT_TYPE    = 'SGTR'
    PRHRS_USE_PEAK   = True
    PRHRS_CORRECTION = -1   # 파단 유로 HX 1개 차감

    def _detect_rt(self, df):
        return float(df['time'].min())

    def _detect_reactor_trip(self, df):
        """출력이 30% 이상 감소하면 Success"""
        try:
            p_start = float(df['rktpow'].iloc[0])
            p_end   = float(df['rktpow'].iloc[-1])
            if p_start > 0 and (p_start - p_end) / p_start > 0.3:
                return 'Success'
            return 'Fail'
        except Exception:
            return 'Success'

    def _analyze_single(self, filename, df):
        scenario_name     = Path(filename).stem
        rt_time           = self._detect_rt(df)
        rcp_status        = self._check_rcp_status(df, rt_time)
        prhrs_count       = self._check_prhrs_count(df, rt_time)
        pct_max, pct_time = self._calculate_pct(df, rt_time)
        outcome           = 'CD' if pct_max >= self.CD_THRESHOLD else 'OK'
        note              = 'EarlyTerm' if df['time'].max() < 1000 else ''
        return {
            'Scenario':         scenario_name,
            'Reactor_Trip':     self._detect_reactor_trip(df),
            'RCP_Status':       rcp_status,
            'PRHRS_count':      prhrs_count,
            'ADS_BLEED_count':  'N/A',
            'PSIS_FEED_status': 'N/A',
            'SIT_Refill_time':  'N/A',
            'PCT_max':          pct_max,
            'PCT_time':         pct_time,
            'Outcome':          outcome,
            'Note':             note,
        }

    def _print_result(self, result):
        note = f' [{result["Note"]}]' if result.get('Note') else ''
        print(f'✓ PRHRS={result["PRHRS_count"]}계통, '
              f'PCT={result["PCT_max"]:.1f}K @ {result["PCT_time"]:.0f}s, '
              f'{result["Outcome"]}{note}')

    def show_results(self):
        if not self.scenarios_data:
            print('❌ 분석된 시나리오가 없습니다.')
            return None
        df = pd.DataFrame(self.scenarios_data)
        print(f'\n{"="*70}')
        print(f'SGTR 분석 결과 요약')
        print(f'{"="*70}')
        normal = (df['Note'] == '').sum() if 'Note' in df.columns else len(df)
        early  = (df['Note'] == 'EarlyTerm').sum() if 'Note' in df.columns else 0
        print(f'총 시나리오:      {len(df)}개  (정상:{normal} / 조기종료:{early})')
        print(f'OK:              {(df["Outcome"]=="OK").sum()}개')
        print(f'Core Damage(CD): {(df["Outcome"]=="CD").sum()}개')
        print(f'평균 PCT:         {df["PCT_max"].mean():.1f} K')
        print(f'최고 PCT:         {df["PCT_max"].max():.1f} K')
        print(f'\nPRHRS 계통수 분포:')
        print(df['PRHRS_count'].value_counts().sort_index().to_string())
        print(f'\n※ ADS/PSIS/SIT: plotfl 미포함 → N/A 처리')
        print(f'{"="*70}')
        return df


# ============================================================
# 실행
# ============================================================

ANALYZERS = {
    '1': ('LOFW',   LOFWAnalyzer,   'lofw_results.csv'),
    '2': ('SBLOCA', SBLOCAAnalyzer, 'sbloca_results.csv'),
    '3': ('GTRN',   GTRNAnalyzer,   'gtrn_results.csv'),
    '4': ('LSSB',   LSSBAnalyzer,   'lssb_results.csv'),
    '5': ('SGTR',   SGTRAnalyzer,   'sgtr_results.csv'),
}

if __name__ == '__main__':
    print('\n' + '=' * 70)
    print('SMART100 PSA Analyzer  Ver.2')
    print('변수명 파일 기반 + PRHRS 상대 비교 알고리즘')
    print('=' * 70)
    print('분석할 사고 유형을 선택하세요:')
    for key, (name, _, _) in ANALYZERS.items():
        print(f'  {key}. {name}')
    print('=' * 70)

    choice = input('선택: ').strip()
    if choice not in ANALYZERS:
        print('❌ 잘못된 입력입니다.')
        exit()

    name, cls, result_file = ANALYZERS[choice]
    analyzer = cls()
    analyzer.step1_load_mapping()
    analyzer.step2_upload_files()
    df = analyzer.show_results()
    if df is not None:
        print(df.to_string(index=False))
        analyzer.save_results(result_file)
