# DET에서 Binary ET 변환 설계 문서

> 작성일: 2026-03-26
> 대상 코드: `et_generator.py` (ET_Generator 클래스)
> 목적: 현재 DET 방식(PRHRS_count 값 그대로 분기)을 PSA 표준 Binary ET 구조로 변환하는 설계

---

## 1. 현재 DET 구조의 문제점 분석

### 1.1 현재 `_build_branches()` 방식의 한계

현재 `et_generator.py`의 `_build_branches()` 메서드는 DataFrame의 각 헤딩 컬럼 값을 **있는 그대로** 조합하여 경로(path)를 만든다.

```python
# 현재 방식 (et_generator.py, line 186-206)
def _build_branches(self, df, headings):
    tree = {}
    for idx, row in df.iterrows():
        path = tuple(row[h] for h in headings)   # 값 그대로 tuple화
        tree.setdefault(path, []).append(idx)
```

이 방식의 근본적인 문제:

| 문제 | 설명 |
|------|------|
| **과다 분기** | PRHRS_count가 0~4이면 분기가 5개 생성됨 |
| **성공기준 미반영** | count=2와 count=3이 물리적으로 동일한 "성공"인데도 별개 분기 처리 |
| **조건부 기준 불가** | RT 성공/실패에 따라 PRHRS 성공기준이 달라지는 구조 표현 불가 |
| **확률 해석 왜곡** | 같은 Outcome(OK)인데 다른 경로로 분리되어 확률 분산 |
| **PSA 툴 비호환** | AIMS KET 등은 Binary ET(Success/Fail 두 분기)를 기본으로 요구 |

### 1.2 PSA ET 관점에서 Binary 구조가 필요한 이유

1. **성공기준(Success Criteria) 명시적 반영**: PRHRS 2/4 작동이 성공기준이라면 count=2, 3, 4는 모두 "Success"로 묶여야 한다.
2. **PSA 소프트웨어 호환**: AIMS, RiskSpectrum, FRANX 등은 모두 Binary ET를 입력으로 요구한다.
3. **사고 시퀀스 빈도 계산**: Binary 구조에서만 P(헤딩 성공) + P(헤딩 실패) = 1.0이 성립한다.
4. **조건부 확률 구조**: 앞 계통의 성공/실패에 따라 뒤 계통의 성공기준이 달라지는 **조건부 성공기준**을 자연스럽게 표현할 수 있다.

---

## 2. Binary ET 변환 아키텍처

### 2.1 데이터 변환 파이프라인

```
[1단계] CSV 로드 (기존 _normalize() 활용)
         ↓
[2단계] 성공기준 설정 (SuccessCriteria 딕셔너리)
         ↓
[3단계] PRHRS_count → PRHRS_status 변환 (BinaryMapper)
         ↓
[4단계] Binary ET 분기 집계 (BinaryBranchBuilder)
         ↓
[5단계] 분기 확률 계산
         ↓
[6단계] Excel 출력 (Binary ET 전용 시트)
```

### 2.2 성공기준 적용 전후 데이터 구조 변화

**변환 전 (DET):**
```
Scenario | Reactor_Trip | PRHRS_count | Outcome
case001  | Success      | 4           | OK
case002  | Success      | 2           | OK
case003  | Success      | 1           | CD
case004  | Fail         | 3           | OK
case005  | Fail         | 1           | CD
```

**변환 후 (Binary ET):**
성공기준: RT 성공 시 count>=2, RT 실패 시 count>=3
```
Scenario | Reactor_Trip | PRHRS_status | Outcome
case001  | Success      | Success      | OK    ← count=4 >= 2
case002  | Success      | Success      | OK    ← count=2 >= 2
case003  | Success      | Fail         | CD    ← count=1 <  2
case004  | Fail         | Success      | OK    ← count=3 >= 3
case005  | Fail         | Fail         | CD    ← count=1 <  3
```

### 2.3 조건부 성공기준 처리 방법

```python
SUCCESS_CRITERIA = {
    'PRHRS': {
        ('Reactor_Trip', 'Success'): 2,
        ('Reactor_Trip', 'Fail'):    3,
        'default': 2
    }
}
```

각 행 처리 시 앞 계통의 현재 상태(이미 변환된 Binary 값)를 조회하여 해당 기준을 적용한다.

---

## 3. 핵심 변환 로직 설계

### 3.1 PRHRS_count → PRHRS_status 변환 방법

```
1. 해당 행의 앞 계통들 상태 조회 (current_states dict)
2. 앞 계통 상태를 키로 SuccessCriteria 딕셔너리 검색
3. 기준값(threshold) 결정
4. PRHRS_count >= threshold → 'Success', 미만 → 'Fail'
```

### 3.2 조건부 매핑 테이블 설계

```python
BINARY_CRITERIA_MAP = {
    'LOFW': {
        'PRHRS': {
            frozenset([('Reactor_Trip', 'Success')]): 2,
            frozenset([('Reactor_Trip', 'Fail')]):    3,
        }
    },
}
```

### 3.3 다중 계통 처리 시 순서 의존성

headings 리스트 순서가 곧 처리 순서이다. `BinaryMapper._map_row()`에서 이미 변환된 상태를 `current_states` dict에 누적하며 순차 처리한다.

---

## 4. Binary ET 노드 구조 설계

### 4.1 트리 노드 데이터 구조

```python
from dataclasses import dataclass, field
from typing import Optional, List, Dict

@dataclass
class BinaryETNode:
    heading: str
    display_name: str
    branch_label: str               # 'Success' 또는 'Fail'
    success_threshold: Optional[int]
    probability: float
    scenario_count: int
    scenario_ids: List[int]
    children: List['BinaryETNode']  # 최대 2개
    is_terminal: bool = False
    outcome: Optional[str] = None   # 'OK' / 'CD'
    cd_count: int = 0
    ok_count: int = 0
    parent_states: Dict[str, str] = field(default_factory=dict)
```

### 4.2 분기 레이블

| 레이블 | 의미 | 원본값 |
|--------|------|--------|
| `Success` | 안전기능 성공 (성공기준 충족) | count >= threshold |
| `Fail` | 안전기능 실패 (성공기준 미충족) | count < threshold |

### 4.3 각 분기의 확률 계산 방법

```
P(PRHRS Success | RT Success) = (RT_Success & PRHRS_Success 수) / (RT_Success 수)
P(PRHRS Fail   | RT Success) = 1 - P(PRHRS Success | RT Success)
```

조건부 확률과 절대 확률을 모두 Excel에 출력한다.

### 4.4 말단 노드(Outcome) 처리

```
OK 비율 > 95%  → dominant_outcome = 'OK'
CD 비율 > 95%  → dominant_outcome = 'CD'
그 외           → dominant_outcome = 'MIXED' (성공기준 재검토 경고)
```

MIXED 발생은 성공기준이 물리적으로 부적절하거나 PCT와 계통 작동 간 비선형 상관관계가 존재함을 의미한다.

---

## 5. AIMS KET 형식과의 호환성

### 5.1 KET 형식이 요구하는 ET 구조

```
EVENT_TREE  <IE_Name>
  HEADING   <Heading_ID>  <Display_Name>
  BRANCH    <Heading_ID>  SUCCESS  <Probability>
  BRANCH    <Heading_ID>  FAILURE  <Probability>
  SEQUENCE  <Seq_ID>  <Path_Vector>  <End_State>
END_EVENT_TREE
```

| 항목 | 요구사항 |
|------|---------|
| 분기 수 | 헤딩당 정확히 2개 (Success/Fail) |
| 확률 합 | 동일 부모 하에서 Success + Fail = 1.0 |
| 시퀀스 | 말단 노드마다 고유 ID와 End State |
| 헤딩 ID | 알파벳+숫자 조합, 공백 불가 |

### 5.2 Binary ET → KET 변환 시 필요한 정보

| 필요 정보 | 출처 |
|----------|------|
| IE 이름 | CSV 파일명 (`scenario_name`) |
| 헤딩 목록 및 순서 | `headings` 리스트 |
| Success/Fail 확률 | BinaryBranchBuilder 집계 결과 (조건부 확률) |
| 시퀀스 경로 벡터 | 말단 노드의 `path` tuple |
| End State | 말단 노드의 `dominant_outcome` |
| 시퀀스 빈도 | 말단 노드의 `probability` |

헤딩 ID 축약 매핑: `Reactor_Trip` → `RT`, `PRHRS_status` → `PRHRS`, `ADS_BLEED_count` → `ADS`

---

## 6. et_generator.py 확장 설계

### 6.1 추가/수정이 필요한 클래스 및 메서드

```
et_generator.py
├── (기존) ET_Generator          ← 수정 없음 (DET 출력 유지)
├── (신규) SuccessCriteriaManager
│    ├── get_threshold(heading, parent_states) → int
│    └── validate(headings)
├── (신규) BinaryMapper
│    ├── transform(df) → df_binary
│    └── get_binary_headings() → list
├── (신규) BinaryBranchBuilder
│    ├── build(df_binary, binary_headings) → list
│    └── compute_conditional_probs(branches, binary_headings) → dict
└── (신규) BinaryET_Generator
     ├── run_all(csv_paths)
     └── _process_single(csv_path)
```

### 6.2 BinaryET_Generator 클래스 설계

```python
class BinaryET_Generator:
    """
    mode: 'manual' / 'optimized' / 'conservative'
    criteria: 성공기준 딕셔너리 (manual 모드에서 직접 지정)
    """
    BINARY_HEADINGS_MAP = {
        'PRHRS_count':     'PRHRS_status',
        'ADS_BLEED_count': 'ADS_status',
    }
```

### 6.3 기존 DET 출력과 Binary ET 출력 병행 지원

**권장 방식: 별도 클래스 + UnifiedRunner**

```python
class UnifiedRunner:
    def run(self, csv_paths, criteria):
        ET_Generator(output_dir=self.output_dir).run_all(csv_paths)
        BinaryET_Generator(output_dir=self.output_dir,
                           criteria=criteria).run_all(csv_paths)
```

기존 `ET_Generator`는 코드 변경 없이 DET 출력을 유지하고, `BinaryET_Generator`가 Binary ET 출력을 담당한다.

---

## 7. 출력 Excel 구조 설계

### 7.1 Binary ET 전용 시트 구성

| 시트 이름 | 내용 |
|-----------|------|
| `원본_데이터` | 정규화된 원본 CSV (기존과 동일) |
| `Binary_변환결과` | count → status 변환 후 전체 행 데이터 |
| `Binary_분기집계` | (RT_status, PRHRS_status, ...) 조합별 집계 |
| `Binary_ET_구조` | Binary ET 트리 시각적 표현 |
| `성공기준_요약` | 적용된 성공기준 및 조건 목록 |
| `KET_출력` | AIMS KET 형식 텍스트 (복사 가능) |

### 7.2 시각적 표현 방법

`Binary_ET_구조` 시트:

```
행\열   A              B          C        D         E
1      [IE: LOFW]
3      Reactor Trip   PRHRS      Outcome  확률(절대) 시나리오수
5      Success        Success → OK        40.0%     40
6                     Fail    → CD        10.0%     10
7      Fail           Success → OK        20.0%     20
8                     Fail    → CD        30.0%     30
```

색상 코딩: `Success` 셀 → 연두색(#C6EFCE), `Fail` 셀 → 연빨간색(#FFC7CE),
`CD` Outcome → 빨간색 굵은 글자, `OK` Outcome → 파란색 글자

---

## 8. Python 의사코드 (Pseudo-code)

### 8.1 SuccessCriteriaManager

```python
class SuccessCriteriaManager:
    def __init__(self, criteria: dict):
        self.criteria = criteria
        # criteria 구조:
        # {
        #   'PRHRS_status': {
        #       frozenset([('Reactor_Trip', 'Success')]): 2,
        #       frozenset([('Reactor_Trip', 'Fail')]):    3,
        #       'default': 2
        #   }
        # }

    def get_threshold(self, heading: str, parent_states: dict) -> int:
        heading_criteria = self.criteria.get(heading, {})
        if not heading_criteria:
            raise ValueError(f"'{heading}'에 대한 성공기준 미정의")
        state_set = frozenset(parent_states.items())
        for condition_key, threshold in heading_criteria.items():
            if condition_key == 'default':
                continue
            if isinstance(condition_key, frozenset) and condition_key.issubset(state_set):
                return threshold
        return heading_criteria.get('default', 1)

    def validate(self, headings: list):
        for h in headings:
            if h in ('PRHRS_count', 'ADS_BLEED_count'):
                status_key = h.replace('_count', '_status')
                if status_key not in self.criteria:
                    raise ValueError(f"'{status_key}' 성공기준 미정의")
```

### 8.2 BinaryMapper

```python
class BinaryMapper:
    COUNT_TO_STATUS = {
        'PRHRS_count':     'PRHRS_status',
        'ADS_BLEED_count': 'ADS_status',
    }

    def __init__(self, criteria_manager, headings):
        self.cm = criteria_manager
        self.headings = headings
        self.transform_targets = {
            h: self.COUNT_TO_STATUS[h]
            for h in headings if h in self.COUNT_TO_STATUS
        }

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        df_out = df.copy()
        for idx, row in df_out.iterrows():
            current_states = {}
            for heading in self.headings:
                if heading in self.transform_targets:
                    status_col = self.transform_targets[heading]
                    threshold  = self.cm.get_threshold(status_col, current_states)
                    count_val  = row[heading]
                    if pd.isna(count_val) or count_val < 0:
                        status = 'Unknown'
                    else:
                        status = 'Success' if int(count_val) >= threshold else 'Fail'
                    df_out.at[idx, status_col] = status
                    current_states[status_col] = status
                else:
                    current_states[heading] = row[heading]
        return df_out

    def get_binary_headings(self) -> list:
        return [
            self.transform_targets.get(h, h)
            for h in self.headings
        ]
```

### 8.3 BinaryBranchBuilder

```python
class BinaryBranchBuilder:
    def build(self, df: pd.DataFrame, binary_headings: list) -> list:
        tree = {}
        for idx, row in df.iterrows():
            path = tuple(str(row[h]) for h in binary_headings)
            tree.setdefault(path, []).append(idx)

        total    = len(df)
        branches = []
        for path, ids in tree.items():
            b = {'path': path, 'count': len(ids),
                 'probability': len(ids) / total, 'scenario_ids': ids}
            for i, h in enumerate(binary_headings):
                b[h] = path[i]
            if 'Outcome' in df.columns:
                outcomes = df.loc[ids, 'Outcome']
                b['cd_count'] = int((outcomes == 'CD').sum())
                b['ok_count'] = int((outcomes == 'OK').sum())
                total_b = len(ids)
                if b['cd_count'] / total_b < 0.05:
                    b['dominant_outcome'] = 'OK'
                elif b['ok_count'] / total_b < 0.05:
                    b['dominant_outcome'] = 'CD'
                else:
                    b['dominant_outcome'] = 'MIXED'
            branches.append(b)

        branches.sort(key=lambda x: x['probability'], reverse=True)
        return branches

    def compute_conditional_probs(self, branches, binary_headings) -> dict:
        cond_probs = {}
        for h_idx, heading in enumerate(binary_headings):
            parent_headings = binary_headings[:h_idx]
            cond_probs[heading] = {}
            parent_groups = {}
            for b in branches:
                parent_path = tuple(b[ph] for ph in parent_headings)
                parent_groups.setdefault(parent_path, []).append(b)
            for parent_path, group in parent_groups.items():
                total_g  = sum(b['count'] for b in group)
                success  = sum(b['count'] for b in group
                               if b[heading] == 'Success')
                cond_probs[heading][parent_path] = {
                    'Success': success / total_g,
                    'Fail':    (total_g - success) / total_g,
                    'total':   total_g,
                }
        return cond_probs
```

### 8.4 성공기준 자동 탐색 알고리즘

```python
def _auto_search_criteria(self, df, headings, mode='optimized') -> dict:
    """
    PCT 20% 마진 기준 성공기준 자동 탐색.

    [최적화 모드]
    - 실질 성공 경계: 1477K * 0.8 = 1181.6K
    - 각 RT_status 조건별로, PCT_max > 1181.6K 위반율이 5% 미만이 되는
      최소 PRHRS_count 값을 탐색 (낮은 count부터 → 관대한 기준)

    [보수적 모드]
    - 동일 탐색 후 경계값에서 +1 (더 엄격한 기준 선택)
    """
    PCT_MARGIN  = 1477 * 0.8   # 1181.6 K
    VIOLATION_THRESHOLD = 0.05  # 5%
    criteria = {'PRHRS_status': {}}

    max_count = int(df['PRHRS_count'].max())

    for rt_state in ['Success', 'Fail']:
        subset = df[df['Reactor_Trip'] == rt_state]
        if len(subset) == 0:
            continue

        candidate = max_count  # 기본값: 가장 엄격한 기준
        for threshold in range(1, max_count + 1):
            success_group  = subset[subset['PRHRS_count'] >= threshold]
            if len(success_group) == 0:
                continue
            violation_rate = (success_group['PCT_max'] > PCT_MARGIN).mean()
            if violation_rate < VIOLATION_THRESHOLD:
                candidate = threshold
                break  # 최솟값 (최적화) 찾으면 중단

        if mode == 'conservative':
            candidate = min(candidate + 1, max_count)

        key = frozenset([('Reactor_Trip', rt_state)])
        criteria['PRHRS_status'][key] = candidate

    return criteria
```

### 8.5 KET 텍스트 생성

```python
def generate_ket_text(scenario_name, binary_headings, branches, cond_probs) -> str:
    SHORT_NAME = {
        'Reactor_Trip':  'RT',
        'PRHRS_status':  'PRHRS',
        'ADS_status':    'ADS',
        'PSIS_status':   'PSIS',
        'SIT_status':    'SIT',
    }
    lines = [f"EVENT_TREE  {scenario_name}", ""]
    for h in binary_headings:
        hid = SHORT_NAME.get(h, h)
        lines.append(f"  HEADING  {hid}  \"{COL_DISPLAY.get(h, h)}\"")
    lines.append("")

    root_h  = binary_headings[0]
    root_id = SHORT_NAME.get(root_h, root_h)
    root_p  = cond_probs[root_h].get((), {})
    lines.append(f"  BRANCH  {root_id}  SUCCESS  {root_p.get('Success', 0):.6f}")
    lines.append(f"  BRANCH  {root_id}  FAILURE  {root_p.get('Fail',    0):.6f}")
    lines.append("")

    for seq_num, b in enumerate(branches, 1):
        path_str  = ','.join('S' if b[h] == 'Success' else 'F'
                             for h in binary_headings)
        end_state = 'OK' if b.get('dominant_outcome') == 'OK' else 'CD'
        lines.append(f"  SEQUENCE  SEQ-{seq_num:03d}  {path_str}  "
                     f"{end_state}  {b['probability']:.6E}")

    lines.append("END_EVENT_TREE")
    return "\n".join(lines)
```

---

## 부록: 구현 우선순위

| 순서 | 항목 | 담당 클래스/메서드 | 난이도 |
|------|------|-------------------|--------|
| 1 | 성공기준 딕셔너리 구조 확정 | `SuccessCriteriaManager` | 낮음 |
| 2 | `BinaryMapper.transform()` 구현 | `BinaryMapper` | 보통 |
| 3 | `BinaryBranchBuilder.build()` 구현 | `BinaryBranchBuilder` | 낮음 |
| 4 | Binary ET Excel 출력 | `BinaryET_Generator._export_binary()` | 보통 |
| 5 | 조건부 확률 계산 | `compute_conditional_probs()` | 보통 |
| 6 | KET 텍스트 생성 | `generate_ket_text()` | 보통 |
| 7 | 자동 성공기준 탐색 (최적화) | `_auto_search_criteria('optimized')` | 높음 |
| 8 | 자동 성공기준 탐색 (보수적) | `_auto_search_criteria('conservative')` | 보통 |
| 9 | `UnifiedRunner` 통합 실행 | `UnifiedRunner` | 낮음 |

### 핵심 설계 원칙

1. **기존 ET_Generator는 수정하지 않는다** — DET 출력 기능을 그대로 유지한다.
2. **순서 의존성을 headings 리스트로 자연스럽게 표현한다** — 별도 DAG 없이 리스트 순서만으로 처리 순서를 결정한다.
3. **성공기준을 외부 딕셔너리로 분리한다** — 코드 수정 없이 성공기준만 교체하여 다양한 사고유형에 대응한다.
4. **MIXED 분기를 명시적으로 감지하고 경고한다** — 성공기준의 물리적 타당성을 검증하는 수단으로 활용한다.
5. **KET 출력을 Excel 시트로도 제공한다** — PSA 도구에 바로 복사하여 사용할 수 있도록 한다.
