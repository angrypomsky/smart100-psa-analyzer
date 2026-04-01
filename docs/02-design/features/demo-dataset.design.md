# [Design] 데모용 PSA 데이터셋 생성기

> 작성일: 2026-03-31 | 피처: demo-dataset | Phase: Design

---

## Context Anchor

| 항목 | 내용 |
|------|------|
| **WHY** | Binary ET 자동생성 알고리즘 개발/검증/데모에 현실적 입력 데이터 필요 |
| **WHO** | 논문 저자(본인) + 발표 청중 (원자력 PSA 전문가) |
| **RISK** | 물리적으로 비현실적인 데이터 → 데모 신뢰성 손상 |
| **SUCCESS** | psa_analyzer 출력 형식 호환 + 계통 간 상관관계 반영 + CD/OK 비율 현실적 |
| **SCOPE** | demo_dataset_generator.py 단독 모듈 |

---

## 1. 모듈 구조

```
demo_dataset_generator.py
│
├── ACCIDENT_PARAMS          ← 사고유형별 파라미터 상수 (dict)
├── COND_PROBS               ← 조건부 확률 테이블 (dict)
│
└── DemoDatasetGenerator     ← 메인 클래스
    ├── generate(accident_type, n, seed) → pd.DataFrame
    │     ├── _sample_rt()
    │     ├── _sample_rcp(rt)
    │     ├── _sample_prhrs(rt, rcp)
    │     ├── _sample_ads(prhrs)          ← PRHRS ≤ 1일 때만
    │     ├── _sample_psis(ads)
    │     ├── _sample_sit(psis)
    │     ├── _sample_pct(prhrs, ads, psis)
    │     └── _determine_outcome(pct)
    └── save(df, accident_type, fmt)      ← CSV / Excel
```

---

## 2. 조건부 확률 테이블

### 2.1 RT 성공률 (사고유형별)

```python
RT_SUCCESS_PROB = {
    'LOFW':   0.98,
    'SBLOCA': 0.95,
    'GTRN':   0.99,
    'LSSB':   0.97,
    'SGTR':   0.95,
}
```

### 2.2 RCP 상태 (RT 결과 조건부)

```python
RCP_GIVEN_RT = {
    'Success': {'Running': 0.60, 'Coast-down': 0.30, 'Natural Circulation': 0.10},
    'Fail':    {'Running': 0.10, 'Coast-down': 0.30, 'Natural Circulation': 0.60},
}
```

### 2.3 PRHRS 계통수 (RT + RCP 조건부)

```python
PRHRS_GIVEN_RT_RCP = {
    ('Success', 'Running'):            [0.60, 0.25, 0.10, 0.04, 0.01],  # 4,3,2,1,0
    ('Success', 'Coast-down'):         [0.40, 0.35, 0.15, 0.08, 0.02],
    ('Success', 'Natural Circulation'):[0.30, 0.30, 0.25, 0.10, 0.05],
    ('Fail',    '*'):                  [0.10, 0.20, 0.30, 0.25, 0.15],
}
# 인덱스 → 계통수: [4, 3, 2, 1, 0]
```

### 2.4 ADS_BLEED_count (PRHRS ≤ 1 조건부)

```python
ADS_GIVEN_PRHRS_LOW = {
    0: [0.40, 0.35, 0.25],   # PRHRS=0: ADS 작동 더 절실 → 고르게 분포
    1: [0.30, 0.40, 0.30],   # PRHRS=1: ADS=1 또는 2가 많음
}
# 인덱스 → ADS 작동 수: [0, 1, 2]
```

### 2.5 PSIS_FEED_status (ADS 조건부)

```python
PSIS_GIVEN_ADS = {
    0: {'Success': 0.00, 'Fail': 1.00},   # ADS=0 → 감압 실패 → PSIS 무조건 Fail
    1: {'Success': 0.60, 'Fail': 0.40},
    2: {'Success': 0.85, 'Fail': 0.15},
}
```

### 2.6 SIT_Refill_time (PSIS 조건부)

```python
# PSIS = 'Fail'    → N/A
# PSIS = 'Success' → Uniform(3600, 108000) 초  (1~30시간)
SIT_RANGE = (3600, 108000)
```

---

## 3. PCT 샘플링 설계

PCT는 최종 냉각 성공 경로에 따라 정규분포 파라미터를 선택:

```python
PCT_PARAMS = {
    # (prhrs_ok, ads_ok, psis_ok): (mean_K, std_K)
    (True,  '-',   '-'):   (1050, 80),   # PRHRS ≥ 2 → 충분한 냉각
    (False, True,  True):  (1300, 120),  # Feed-and-Bleed 성공
    (False, True,  False): (1550, 130),  # ADS 성공, PSIS 실패
    (False, False, False): (1650, 100),  # ADS 실패 (최악)
}
# prhrs_ok = PRHRS_count >= 2
# ads_ok   = ADS_BLEED_count >= 1
# psis_ok  = PSIS_FEED_status == 'Success'
```

이상값 클리핑: `PCT = clip(sampled, 800, 1900)`

---

## 4. 시나리오 ID 생성

```python
# 형식: {ACCIDENT_TYPE}_{번호:03d}
# 예시: LOFW_001, SBLOCA_042, SGTR_200
scenario_id = f"{accident_type}_{i+1:03d}"
```

---

## 5. 출력 컬럼 순서 (psa_analyzer 호환)

```python
OUTPUT_COLS = [
    'Scenario',
    'Reactor_Trip',
    'RCP_Status',
    'PRHRS_count',
    'ADS_BLEED_count',
    'PSIS_FEED_status',
    'SIT_Refill_time',
    'PCT_max',
    'PCT_time',
    'Outcome',
    'Note',
]
```

- `PCT_time`: RT_time 이후 랜덤 오프셋 (`RT_time + Uniform(100, 3000)` 초)
- `Note`: LSSB/SGTR에서 시뮬레이션 시간 < 1000s → `EarlyTerm` (5% 확률)

---

## 6. CLI 인터페이스

```bash
# 단일 사고유형
python demo_dataset_generator.py --type LOFW --n 200 --seed 42

# 전체 5개 사고유형 한 번에
python demo_dataset_generator.py --all --n 200 --seed 42

# 출력 폴더 지정
python demo_dataset_generator.py --all --n 200 --output demo_data/
```

출력 파일:
```
demo_data/
├── LOFW_demo.csv
├── SBLOCA_demo.csv
├── GTRN_demo.csv
├── LSSB_demo.csv
└── SGTR_demo.csv
```

---

## 7. 검증 출력 (생성 시 자동 프린트)

```
[LOFW] 200개 생성 완료
  RT 성공률:      97.5%  (기대: ~98%)
  CD 비율:         4.5%  (기대: ~5%)
  PRHRS 분포:     4계통: 58%, 3계통: 24%, 2계통: 11%, 1계통: 5%, 0계통: 2%
  PRHRS ≤ 1 진입: 14개
    ADS=0:  4개  → PSIS Fail 확정
    ADS≥1: 10개  → PSIS Success: 7개 / Fail: 3개
  PCT 평균: 1082 K  |  최대: 1621 K
```

---

## 8. 구현 순서

1. 상수 테이블 정의 (`ACCIDENT_PARAMS`, `COND_PROBS`, `PCT_PARAMS`)
2. `DemoDatasetGenerator.generate()` — 시나리오 1개 생성 루프
3. 각 `_sample_*()` 메서드 구현 (순서대로: RT → RCP → PRHRS → ADS → PSIS → SIT → PCT → Outcome)
4. `save()` — CSV/Excel 저장
5. CLI `argparse` 진입점
6. 검증 출력 함수
