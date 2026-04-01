# [Plan] 데모용 PSA 데이터셋 생성기

> 작성일: 2026-03-26 | 피처: demo-dataset | Phase: Plan

---

## Executive Summary

| 관점 | 내용 |
|------|------|
| **Problem** | Binary ET 알고리즘 개발/데모에 쓸 현실적 PSA 데이터셋 없음. 실제 SMART100 데이터는 제한적이고 공개 불가. |
| **Solution** | 경수로 물리 특성 기반 합성 데이터셋 생성기 (`demo_dataset_generator.py`). 앞 계통 성공/실패에 따라 뒤 계통 성공기준이 달라지는 상관관계 반영. |
| **UX Effect** | 논문/발표 데모 시 즉시 실행 가능한 그럴싸한 데이터 제공. ET 알고리즘 검증 기반 마련. |
| **Core Value** | PSA 후처리 자동화 전체 파이프라인(psa_analyzer → demo_data → et_generator)의 엔드-투-엔드 데모 가능화. |

---

## Context Anchor

| 항목 | 내용 |
|------|------|
| **WHY** | Binary ET 자동생성 알고리즘(논문 핵심 contribution) 개발/검증/데모에 현실적 입력 데이터 필요 |
| **WHO** | 논문 저자(본인) + 발표 청중 (원자력 PSA 전문가) |
| **RISK** | 물리적으로 비현실적인 데이터 → 데모 신뢰성 손상 / 논문 심사에서 지적 가능성 |
| **SUCCESS** | psa_analyzer 출력 형식과 호환 + 계통 간 상관관계 반영 + CD/OK 비율 현실적 |
| **SCOPE** | 데이터 생성기 단독 모듈. ET 알고리즘 자체는 별도 피처. |

---

## 1. 배경 및 목적

### 1.1 현황

- `psa_analyzer.py` Ver.2: 5개 사고유형 RT/PRHRS/PCT 자동 후처리 완성
- `et_generator.py`: CSV → ET 구조 Excel 기본 생성기 존재
- **부재**: 알고리즘 개발/검증에 쓸 현실적 합성 데이터셋

### 1.2 필요성

```
실제 SMART100 데이터
  → 제한적 (시나리오 수 부족)
  → 공개/배포 불가 (보안)
  → CD 시나리오 없음 (OK 케이스만 존재)

∴ 합성 데이터셋 필요:
  - 논문 데모용 (그럴싸해야 함)
  - ET 알고리즘 검증용 (성공기준 경계 케이스 포함)
  - CD/OK 혼재 (알고리즘 테스트)
```

---

## 2. 요구사항

### 2.1 기능 요구사항

| ID | 요구사항 | 우선순위 |
|----|----------|---------|
| F-01 | psa_analyzer.py 출력 컬럼과 동일한 형식 생성 | 필수 |
| F-02 | 사고유형별 물리적으로 타당한 파라미터 범위 설정 | 필수 |
| F-03 | 앞 계통 성공/실패 → 뒤 계통 성공기준 변화 반영 (계통 간 상관관계) | 필수 |
| F-04 | CD/OK 비율이 PSA 현실과 유사 (CD는 소수) | 필수 |
| F-05 | 시나리오 수 설정 가능 (기본값: 100~200개) | 필수 |
| F-06 | 사고유형 선택 가능 (LOFW / SBLOCA / GTRN / LSSB / SGTR) | 권장 |
| F-07 | CSV 및 Excel 형식으로 저장 | 권장 |
| F-08 | 재현성을 위한 random seed 설정 가능 | 권장 |

### 2.2 계통 간 상관관계 규칙 (핵심)

**[1단계] PRHRS 샘플링 (RT + RCP 조건부)**

```
RT 성공 + RCP Running    → [4: 60%, 3: 25%, 2: 10%, 1: 4%,  0: 1%]
RT 성공 + RCP Coast-down → [4: 40%, 3: 35%, 2: 15%, 1: 8%,  0: 2%]
RT 성공 + RCP NC         → [4: 30%, 3: 30%, 2: 25%, 1: 10%, 0: 5%]
RT 실패                  → [4: 10%, 3: 20%, 2: 30%, 1: 25%, 0: 15%]
```

**[2단계] Feed-and-Bleed 시퀀스 (PRHRS ≤ 1일 때만 진입)**

```
PRHRS_count ≥ 2  →  ADS = N/A, PSIS = N/A, SIT = N/A

PRHRS_count = 0 or 1  →  Feed-and-Bleed 시퀀스
  │
  ├─ ADS_BLEED_count = 0  →  PSIS_FEED = Fail (확정)  →  SIT_Refill = N/A
  │
  └─ ADS_BLEED_count = 1 or 2
       ├─ PSIS_FEED = Fail  →  SIT_Refill = N/A
       └─ PSIS_FEED = Success  →  SIT_Refill_time = 0~108000 s (최대 30시간)
```

- `ADS_BLEED_count` 범위: 0~2
- `PSIS_FEED_status`: Success / Fail
- `SIT_Refill_time`: float (초) 또는 N/A

### 2.3 PCT 범위 설정 (물리적 근거)

```
[PRHRS ≥ 2]
  → PCT ~ 900-1350 K  (대부분 OK)

[PRHRS ≤ 1 + ADS ≥ 1 + PSIS 성공]
  → PCT ~ 1100-1500 K  (OK 가능)

[PRHRS ≤ 1 + ADS ≥ 1 + PSIS 실패]
  → PCT ~ 1300-1700 K  (CD 가능성 높음)

[PRHRS ≤ 1 + ADS = 0]
  → PCT ~ 1400-1800 K  (대부분 CD)

CD 판정: PCT ≥ 1477 K (NRC 10 CFR 50.46 기준)
```

### 2.4 비기능 요구사항

| ID | 요구사항 |
|----|----------|
| NF-01 | 생성 코드가 단독 실행 가능 (외부 의존성 최소화: pandas, numpy만 사용) |
| NF-02 | 파라미터를 쉽게 조정할 수 있도록 상수/설정부를 상단에 집중 |
| NF-03 | 생성된 데이터는 psa_analyzer 결과처럼 자연스러워야 함 |

---

## 3. 출력 스펙

### 3.1 생성 컬럼 (psa_analyzer 호환)

| 컬럼 | 타입 | 예시 |
|------|------|------|
| `Scenario` | str | `LOFW_001`, `SBLOCA_042` |
| `Reactor_Trip` | str | `Success` / `Fail` |
| `RCP_Status` | str | `Running` / `Coast-down` / `Natural Circulation` |
| `PRHRS_count` | int | 0~4 |
| `ADS_BLEED_count` | int/str | 0~2 또는 `N/A` (PRHRS ≥ 2이면 N/A) |
| `PSIS_FEED_status` | str | `Success` / `Fail` / `N/A` |
| `SIT_Refill_time` | float/str | 0~108000 s 또는 `N/A` |
| `PCT_max` | float | 900~1800 (K) |
| `PCT_time` | float | RT_time + 100~3000 (s) |
| `Outcome` | str | `OK` / `CD` |
| `Note` | str | 빈칸 or `EarlyTerm` (LSSB/SGTR) |

### 3.2 저장 파일

```
demo_data/
├── LOFW_demo.csv
├── LOFW_demo.xlsx
├── SBLOCA_demo.csv
└── ...
```

---

## 4. 구현 설계 방향

### 4.1 클래스 구조 (안)

```python
DemoDataGenerator
├── generate(accident_type, n_scenarios, seed) → DataFrame
├── _sample_rt(accident_type) → str
├── _sample_rcp(rt_status, accident_type) → str
├── _sample_prhrs(rt_status, rcp_status, accident_type) → int
├── _sample_pct(prhrs_count, accident_type) → float
└── save(df, accident_type, format=['csv','xlsx'])
```

### 4.2 사고유형별 파라미터 테이블

| 파라미터 | LOFW | SBLOCA | GTRN | LSSB | SGTR |
|---------|------|--------|------|------|------|
| RT 성공률 | 98% | 95% | 99% | 97% | 95% |
| RCP Running 비율 (RT 성공 시) | 60% | 40% | 70% | 30% | 45% |
| CD 비율 전체 목표 | ~5% | ~10% | ~2% | ~15% | ~12% |

---

## 5. 리스크

| 리스크 | 영향 | 대응 |
|--------|------|------|
| 생성 데이터가 물리적으로 비현실적 | 논문 데모 신뢰성 손상 | 경수로 PSA 문헌 기반 파라미터 설정 + 사후 분포 시각화 확인 |
| psa_analyzer 출력 형식 불일치 | et_generator 입력 오류 | 기존 sgtr_results.csv 컬럼 기준으로 검증 |
| 계통 간 상관관계 단순화 과도 | 알고리즘 검증 무의미 | 성공기준 경계 케이스 명시적 생성 |

---

## 6. 성공 기준

| 기준 | 측정 방법 |
|------|----------|
| psa_analyzer 출력 컬럼과 100% 호환 | et_generator.py로 바로 입력 가능 |
| 각 사고유형별 CD 비율이 목표 범위 내 | 생성 후 통계 출력으로 확인 |
| 앞 계통 상태별 PRHRS 분포 차이 존재 | 조건부 교차표 확인 |
| 재현성 보장 | seed 고정 시 동일 결과 |

---

## 7. 다음 단계

완료 후 → `[Plan] 성공기준 자동 탐색 알고리즘` 또는 `/pdca design demo-dataset`
