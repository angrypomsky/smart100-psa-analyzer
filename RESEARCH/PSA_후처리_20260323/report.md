# SMART100 PSA 결과 후처리 리서치 보고서
> 작성일: 2026-03-23 | 목적: psa_analyzer.py 코드 기능 추가

---

## 핵심 요약

현행 `psa_analyzer.py`는 **NRC/IAEA Level 1 PSA 기준에 적합**하게 구현되어 있음.
(PCT 1477K 기준, OK/CD 2원 분류, PRHRS 계통수 집계 모두 국제 표준과 일치)

추가 구현 가능한 후처리 기능은 아래 우선순위 순으로 정리.

---

## 추가 기능 로드맵

| 우선순위 | 기능 | 설명 |
|---------|------|------|
| ★★★ | ET 피벗 매트릭스 | PRHRS × RCP_Status → CD/OK 건수 교차표 |
| ★★★ | PRHRS별 PCT 통계 | 계통수별 평균·최대·CD비율 집계 |
| ★★★ | CD 임계값 민감도 | 1300~1600K 범위 CD건수 변화 |
| ★★ | PCT 백분위수 | 95th, 99th percentile (Wilks 기준) |
| ★★ | 사고유형 통합 요약 | 5개 사고 단일 비교 테이블 |
| ★ | Excel 다중 시트 출력 | 시나리오목록 + 피벗 + 민감도 시트 |

---

## 구현 코드 스니펫

### 1. PRHRS별 PCT 통계 (`show_prhrs_stats`)
```python
def show_prhrs_stats(self):
    df = pd.DataFrame(self.scenarios_data)
    stats = df.groupby('PRHRS_count').agg(
        N        = ('PCT_max', 'count'),
        PCT_평균 = ('PCT_max', 'mean'),
        PCT_최대 = ('PCT_max', 'max'),
        CD건수   = ('Outcome', lambda x: (x=='CD').sum())
    )
    stats['CD비율(%)'] = (stats['CD건수'] / stats['N'] * 100).round(1)
    print(stats.sort_index(ascending=False).to_string())
```

### 2. CD 임계값 민감도 (`show_cd_sensitivity`)
```python
def show_cd_sensitivity(self, thresholds=None):
    if thresholds is None:
        thresholds = [1300, 1350, 1400, 1450, 1477, 1500, 1550, 1600]
    df = pd.DataFrame(self.scenarios_data)
    pct = df['PCT_max'].values
    n = len(pct)
    for thr in thresholds:
        n_cd = (pct >= thr).sum()
        marker = " ◀ 현행기준" if thr == 1477 else ""
        print(f"{thr}K: CD {n_cd}건 ({n_cd/n*100:.1f}%){marker}")
    print(f"  PCT 95th percentile: {np.percentile(pct, 95):.1f} K")
    print(f"  PCT 99th percentile: {np.percentile(pct, 99):.1f} K")
```

### 3. ET 피벗 매트릭스 (`show_et_matrix`)
```python
def show_et_matrix(self):
    df = pd.DataFrame(self.scenarios_data)
    cd_matrix = pd.pivot_table(
        df, values='Outcome',
        index='PRHRS_count', columns='RCP_Status',
        aggfunc=lambda x: f"{(x=='CD').sum()}/{len(x)}"
    )
    print("\n[ET 결과 매트릭스] CD건수/전체건수")
    print("(행=PRHRS계통수, 열=RCP상태)")
    print(cd_matrix.to_string())
```

### 4. 사고유형 통합 비교 (독립 함수)
```python
def generate_psa_summary(results_dict):
    rows = []
    for accident, data in results_dict.items():
        df = pd.DataFrame(data)
        pct = df['PCT_max']
        rows.append({
            '사고유형':    accident,
            '시나리오수':  len(df),
            'CD건수':     (df['Outcome']=='CD').sum(),
            'CD비율(%)':  round((df['Outcome']=='CD').mean()*100, 1),
            'PCT_평균(K)': round(pct.mean(), 1),
            'PCT_최대(K)': round(pct.max(), 1),
            'PCT_P95(K)':  round(pct.quantile(0.95), 1),
        })
    summary = pd.DataFrame(rows).set_index('사고유형')
    print(summary.to_string())
    return summary
```

---

## 배경 지식

### PCT 기준
- **NRC 10 CFR 50.46**: 1204°C = **1477 K** (현행 코드와 동일)
- Wilks 95/95: 최소 **59개 샘플**로 95th percentile 단측 추정 가능

### PRHRS 성공 기준 (국제 기준)
- 4/4 작동: 완전 성공
- 3/4 작동: 성공 가능 (여유도 있음)
- 2/4 이하: T/H 계산으로 PCT 확인 필요
→ 현행 PRHRS_count(0~4) 추출 방식이 이 체계에 정확히 대응

### LSSB 임계값 8×10⁵ W 근거
- 대형 2차측 파단 초기 과도현상에서 높은 열출력 발생 → 10 kW로 판정 시 오판 가능
- 후반 30% 평균으로 "정상 작동 여부"만 추출하는 설계 = 국제 관행과 일치

### SGTR 피크 + 1 차감 근거
- 파단 유로 HX가 항상 높은 값을 유지 → 실제 냉각 목적 PRHRS 계통 수를 과대 계산하는 문제 보정

---

## 참고 문헌
- IAEA SSG-3 Rev.1 (2024) - Level 1 PSA 개발 및 적용
- NRC NUREG-2236 - 열수력 PSA 성공 기준 확인
- Frontiers in Nuclear Engineering (2025) - Large APR PRHRS 신뢰도 분석
- ScienceDirect (2025) - SMART100 Comprehensive Safety Analysis (SDA 취득)
- INL RAVEN Framework - Dynamic PRA + RELAP5-3D 연동
