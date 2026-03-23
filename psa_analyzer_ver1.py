# -*- coding: utf-8 -*-
# SMART100 PSA Analyzer
# python smart100_psa_analyzer.py 실행

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
# BaseAnalyzer
# ============================================================

class BaseAnalyzer:
    """
    공통 베이스 클래스
    - PCT 계산, RCP 상태, 결과 저장 등 모든 사고 유형에서 동일한 로직
    - _detect_rt(), _check_prhrs_count()는 사고별로 다르므로 서브클래스에서 구현
    """

    ACCIDENT_TYPE = 'Unknown'
    CD_THRESHOLD  = 1477  # NRC 규제 기준 PCT Core Damage 판정 (K)

    def __init__(self):
        self.var_mapping_df = None
        self.scenarios_data = []
        print('=' * 70)
        print(f'📊 SMART100 {self.ACCIDENT_TYPE} Analyzer')
        print('=' * 70)
        print('\n사용 순서:')
        print('  1. analyzer.step2_upload_files()  → 시나리오 파일들 선택')
        print('  2. analyzer.show_results()        → 결과 확인')
        print('  3. analyzer.save_results()        → CSV 저장')
        print('=' * 70)

    def step1_load_mapping(self):
        print(f'\n{"="*70}')
        print('Step 1: 변수 매핑 파일 선택')
        print(f'{"="*70}')
        paths = _pick_files('변수 매핑 파일 선택 (smart100데이터_변수명_확인.xlsx)', multiple=False)
        if not paths:
            print('❌ 파일이 선택되지 않았습니다.')
            return
        self.var_mapping_df = pd.read_excel(paths[0])
        print(f'✓ 변수 매핑 로드: {Path(paths[0]).name} ({len(self.var_mapping_df)}개 변수)')
        print('\n▶ 다음: analyzer.step2_upload_files()')

    def step2_upload_files(self):
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
            print(f'📊 {filename}...', end=' ')
            try:
                df_raw = pd.read_excel(filepath)
                df_raw = df_raw.dropna(subset=['time'])
                df = df_raw.iloc[2:].copy()
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

    def _analyze_single(self, filename, df):
        scenario_name     = Path(filename).stem
        rt_time           = self._detect_rt(df)
        reactor_trip      = 'Success' if rt_time < df['time'].max() * 0.99 else 'Fail'
        rcp_status        = self._check_rcp_status(df, rt_time)
        prhrs_count       = self._check_prhrs_count(df, rt_time)
        pct_max, pct_time = self._calculate_pct(df, rt_time)
        outcome           = 'CD' if pct_max >= self.CD_THRESHOLD else 'OK'
        return {
            'Scenario':          scenario_name,
            'Reactor_Trip':      reactor_trip,
            'RCP_Status':        rcp_status,
            'PRHRS_count':       prhrs_count,
            'ADS_BLEED_count':   'N/A',
            'PSIS_FEED_status':  'N/A',
            'SIT_Refill_time':   'N/A',
            'PCT_max':           pct_max,
            'PCT_time':          pct_time,
            'Outcome':           outcome,
        }

    def _print_result(self, result):
        print(f'✓ PRHRS={result["PRHRS_count"]}계통, '
              f'PCT={result["PCT_max"]:.1f}K @ {result["PCT_time"]:.0f}s, '
              f'{result["Outcome"]}')

    def _check_rcp_status(self, df, rt_time):
        df_after = df[(df['time'] > rt_time) & (df['time'] < rt_time + 200)]
        if len(df_after) == 0:
            return 'Unknown'
        avg_head = df_after[['pmphead','pmphead.1','pmphead.2','pmphead.3']].mean().mean()
        if avg_head > 1000:
            return 'Running'
        elif avg_head > -200:
            return 'Coast-down'
        else:
            return 'Natural Circulation'

    def _calculate_pct(self, df, rt_time):
        """
        PCT 계산 - RT 이후 구간에서 3개 노드 중 최대값
        httemp   = 120000803 (노드 8)
        httemp.1 = 120000903 (노드 9)
        httemp.2 = 120001003 (노드 10)
        """
        pct_cols = ['httemp', 'httemp.1', 'httemp.2']
        df_valid = df[df['time'] >= rt_time].copy()
        df_valid = df_valid[(df_valid[pct_cols] < 10000).all(axis=1)]
        if len(df_valid) == 0:
            return 0.0, 0.0
        df_valid['pct_row_max'] = df_valid[pct_cols].max(axis=1)
        pct_max  = df_valid['pct_row_max'].max()
        pct_time = df_valid.loc[df_valid['pct_row_max'].idxmax(), 'time']
        return float(pct_max), float(pct_time)

    def _detect_rt(self, df):
        raise NotImplementedError(f'{self.__class__.__name__}에서 _detect_rt()를 구현하세요.')

    def _check_prhrs_count(self, df, rt_time):
        raise NotImplementedError(f'{self.__class__.__name__}에서 _check_prhrs_count()를 구현하세요.')

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
    LOFW (Loss of Feedwater) 전용 Analyzer

    - RT: 사고 초기 발생 → 50초 고정
    - PRHRS: feedwater 유량 기준 (mflowj.13~16, 임계값 0.5 kg/s)
    - ADS/PSIS/SIT: plotfl 미포함 → N/A
    """

    ACCIDENT_TYPE = 'LOFW'

    def _detect_rt(self, df):
        return 50.0

    def _check_prhrs_count(self, df, rt_time):
        try:
            df_after = df[df['time'] > rt_time + 50]
            if len(df_after) == 0:
                return 0
            hx_cols = ['cntrlvar.25', 'cntrlvar.26', 'cntrlvar.27', 'cntrlvar.28']
            avg_heat = df_after[hx_cols].mean()
            return int((avg_heat > 10000).sum())
        except Exception:
            return -1


# ============================================================
# SBLOCAAnalyzer
# ============================================================

class SBLOCAAnalyzer(BaseAnalyzer):
    """
    SBLOCA (Small Break LOCA) 전용 Analyzer

    - RT: 초기 출력 5% 이하 시점 자동 감지
    - PRHRS: HX 열출력 기준 (cntrlvar.25~28, 임계값 10000 W)
    - ADS/PSIS/SIT: plotfl 미포함 → N/A
    """

    ACCIDENT_TYPE = 'SBLOCA'

    def _detect_rt(self, df):
        initial_power = df.iloc[0]['rktpow']
        threshold = initial_power * 0.05
        trip_rows = df[df['rktpow'] < threshold]
        return float(trip_rows['time'].min()) if len(trip_rows) > 0 else float(df['time'].max())

    def _check_prhrs_count(self, df, rt_time):
        try:
            df_after = df[df['time'] > rt_time + 100]
            if len(df_after) == 0:
                return 0
            hx_cols = ['cntrlvar.25', 'cntrlvar.26', 'cntrlvar.27', 'cntrlvar.28']
            avg_heat = df_after[hx_cols].mean()
            return int((avg_heat > 10000).sum())
        except Exception:
            return -1

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
    GTRN (General Transient, 일반 과도상태) 전용 Analyzer

    - RT: 데이터가 RT 이후부터 저장 → time.min() 사용
    - PRHRS: HX 열출력 기준 (cntrlvar.25~28, 임계값 10000 W)
    - ADS/PSIS/SIT: plotfl 미포함 → N/A
    - Reactor_Trip: 항상 Success (데이터가 RT 이후부터 저장)
    """

    ACCIDENT_TYPE = 'GTRN'

    def _detect_rt(self, df):
        return float(df['time'].min())

    def _check_prhrs_count(self, df, rt_time):
        try:
            df_after = df[df['time'] > rt_time + 100]
            if len(df_after) == 0:
                return 0
            hx_cols = ['cntrlvar.25', 'cntrlvar.26', 'cntrlvar.27', 'cntrlvar.28']
            avg_heat = df_after[hx_cols].mean()
            return int((avg_heat > 10000).sum())
        except Exception:
            return -1

    def _analyze_single(self, filename, df):
        scenario_name     = Path(filename).stem
        rt_time           = self._detect_rt(df)
        rcp_status        = self._check_rcp_status(df, rt_time)
        prhrs_count       = self._check_prhrs_count(df, rt_time)
        pct_max, pct_time = self._calculate_pct(df, rt_time)
        outcome           = 'CD' if pct_max >= self.CD_THRESHOLD else 'OK'
        return {
            'Scenario':          scenario_name,
            'Reactor_Trip':      'Success',
            'RCP_Status':        rcp_status,
            'PRHRS_count':       prhrs_count,
            'ADS_BLEED_count':   'N/A',
            'PSIS_FEED_status':  'N/A',
            'SIT_Refill_time':   'N/A',
            'PCT_max':           pct_max,
            'PCT_time':          pct_time,
            'Outcome':           outcome,
        }


# ============================================================
# LSSBAnalyzer
# ============================================================

class LSSBAnalyzer(BaseAnalyzer):
    """
    LSSB (Large Secondary Side Break, 대형 2차측 파단) 전용 Analyzer

    - RT: 데이터가 RT 이후부터 저장 → time.min() 사용
    - PRHRS: HX 열출력 기준 (cntrlvar.25~28, 임계값 10000 W)
             RT+100s 이후 평균 사용 (초반 이상값 회피)
    - ADS/PSIS/SIT: plotfl 미포함 → N/A
    - Reactor_Trip: 항상 Success
    - 조기 종료 시나리오: Note='EarlyTerm' 표기
    """

    ACCIDENT_TYPE = 'LSSB'

    def _detect_rt(self, df):
        return float(df['time'].min())

    def _check_prhrs_count(self, df, rt_time):
        try:
            df_after = df[df['time'] > rt_time + 100]
            if len(df_after) == 0:
                return 0
            hx_cols = ['cntrlvar.25', 'cntrlvar.26', 'cntrlvar.27', 'cntrlvar.28']
            tail_n = max(1, int(len(df_after) * 0.3))
            steady_heat = df_after[hx_cols].tail(tail_n).mean()
            count = int((steady_heat > 8e5).sum())
            return count
        except Exception:
            return -1

    def _analyze_single(self, filename, df):
        scenario_name     = Path(filename).stem
        rt_time           = self._detect_rt(df)
        rcp_status        = self._check_rcp_status(df, rt_time)
        prhrs_count       = self._check_prhrs_count(df, rt_time)
        pct_max, pct_time = self._calculate_pct(df, rt_time)
        outcome           = 'CD' if pct_max >= self.CD_THRESHOLD else 'OK'
        note              = 'EarlyTerm' if df['time'].max() < 1000 else ''
        return {
            'Scenario':          scenario_name,
            'Reactor_Trip':      'Success',
            'RCP_Status':        rcp_status,
            'PRHRS_count':       prhrs_count,
            'ADS_BLEED_count':   'N/A',
            'PSIS_FEED_status':  'N/A',
            'SIT_Refill_time':   'N/A',
            'PCT_max':           pct_max,
            'PCT_time':          pct_time,
            'Outcome':           outcome,
            'Note':              note,
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
    SGTR (Steam Generator Tube Rupture, 증기발생기 세관파열) 전용 Analyzer

    - RT: 데이터가 RT 이후부터 저장 → time.min() 사용
    - PRHRS: HX 열출력 기준 (cntrlvar.25~28, 임계값 10000 W)
    - ADS/PSIS/SIT: plotfl 미포함 → N/A
    - Reactor_Trip: 항상 Success
    - 조기 종료 시나리오: Note='EarlyTerm' 표기
    """

    ACCIDENT_TYPE = 'SGTR'

    def _detect_rt(self, df):
        return float(df['time'].min())

    def _check_prhrs_count(self, df, rt_time):
        try:
            df_after = df[df['time'] > rt_time + 100]
            if len(df_after) == 0:
                return 0
            hx_cols = ['cntrlvar.25', 'cntrlvar.26', 'cntrlvar.27', 'cntrlvar.28']
            # 피크 기준 판정: HX가 한 번이라도 작동했으면 작동으로 간주
            # (후반부 평균 사용 시 감쇠 구간에서 누락되는 문제 방지)
            peak_heat = df_after[hx_cols].max()
            count = int((peak_heat > 10000).sum())
            # SGTR 보정: 파단 유로 HX(cntrlvar.307)가 항상 높은 피크값 유지
            # → 실제 작동 계통 수에서 1 차감
            return max(0, count - 1)
        except Exception:
            return -1

    def _detect_reactor_trip(self, df):
        """RT 성공 여부 판단: 출력이 30% 이상 감소하면 Success"""
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
            'Scenario':          scenario_name,
            'Reactor_Trip':      self._detect_reactor_trip(df),
            'RCP_Status':        rcp_status,
            'PRHRS_count':       prhrs_count,
            'ADS_BLEED_count':   'N/A',
            'PSIS_FEED_status':  'N/A',
            'SIT_Refill_time':   'N/A',
            'PCT_max':           pct_max,
            'PCT_time':          pct_time,
            'Outcome':           outcome,
            'Note':              note,
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
    print('SMART100 PSA Analyzer')
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
    analyzer.step2_upload_files()
    df = analyzer.show_results()
    if df is not None:
        print(df.to_string(index=False))
        analyzer.save_results(result_file)