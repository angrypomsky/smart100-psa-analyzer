# AIMS-PSA `.ket` 파일 형식 명세서

> 작성일: 2026-04-22
> 대상: AIMS-PSA / CONPAS v3.0 (KAERI) 호환 Event Tree 파일
> 참고 샘플: `aims/0929/Base/01-iSMR-CSGTR-T-R0.ket`
> 목적: 본 프로그램의 Binary ET 결과를 `.ket` (텍스트) 로 저장하여 AIMS-PSA 에서 열 수 있도록 포맷을 확정한다.

---

## 0. 개요

### 0.1 파일 성격

- **인코딩**: ASCII 텍스트 (확장자 `.ket`, 실질은 `.txt` 와 동일, CR/LF 또는 LF 모두 허용)
- **구조**: 단일 파일에 "이벤트 트리 한 개"를 담는다.
- **구성 방식**: CSV 유사 레코드 + 섹션 헤더 라인 + DFS 방식 트리 직렬화의 혼합
- **생성 주체**: CONPAS v3.0 (KAERI) 및 이를 계승한 AIMS-PSA

### 0.2 전체 섹션 순서

```
[1] 시그니처 라인                                    (1줄)
[2] 메타데이터 (Title/User/Comments/PageInsert)      (4줄)
[3] #NoEvent 카운트 라인                              (1줄)
[4] 헤더 주석 "--- Event Tree Information ---"        (1줄)
[5] Head Information   섹션  (헤딩 정의)
[6] Branch Information 섹션  (트리 노드, DFS 직렬화)
[7] Sequence Information 섹션 (말단 시퀀스)
[8] 공백 라인 ""
[9] ET Print margin 섹션 (인쇄/표시 설정)
[10] 트레일러: "111" + 브랜치별 확장 슬롯 0..N_max
```

섹션 사이에 빈 줄은 원칙적으로 넣지 않는다 (샘플 파일 기준).

---

## 1. 레코드 문법 (Lexical)

- 한 레코드 = 한 줄.
- 필드 구분자: `,` (쉼표).
- 문자열 필드는 **항상 큰따옴표로 감싼다** `"..."`. 숫자 필드는 따옴표 없이 쓰거나 따옴표로 감싸는 경우가 혼재한다 (아래 각 섹션 참고).
- 문자열 안에 쉼표/큰따옴표가 등장하는 케이스는 샘플 파일에서 관찰되지 않음 → **생성 시 사용 금지** 를 권장.
- 공백(trailing space) 은 헤딩 이름 필드 끝에 존재할 수 있음 (`"Faulted Steam Generator Isolation "` 처럼). AIMS 가 trim 하지 않고 그대로 보관하므로, 의미 없는 공백은 붙이지 않는다.

---

## 2. 시그니처 및 메타데이터 (라인 1~5)

### 2.1 시그니처 (1번째 줄, **필수, 고정**)

```
"#2 CONPAS v3.0, developed by [KAERI]#"
```

- 이 문자열이 없거나 다르면 AIMS 가 파일을 인식하지 못할 가능성이 매우 높다.
- **우리 프로그램은 이 라인을 그대로 복제해서 출력한다.**

### 2.2 메타데이터 (2~5번째 줄)

```
"Title=",""
"UserName=",""
"Comments=",""
"PageInsert=",""
```

각 줄은 `"KEY=", "VALUE"` 형식의 2필드 CSV. 값은 비워도 되고, UTF-8 보다는 ASCII/CP949 호환 문자만 넣는 것이 안전.

---

## 3. `#NoEvent` 카운트 라인 (6번째 줄)

```
"#NoEvent=",10,91,15
```

| 인덱스 | 샘플값 | 의미 (추정)                                                      |
|-------|-------|------------------------------------------------------------------|
| 1     | 10    | **헤딩(Head) 개수** — Head Information 섹션의 행 수와 일치         |
| 2     | 91    | **최대 Branch 인덱스** — Branch Information 의 마지막 `ID` 와 일치. 실제 브랜치 배열은 0..91 총 92 슬롯이 예약됨. 샘플에서 의미 있는 브랜치는 0~70, 71~91 은 빈 자리(padding). |
| 3     | 15    | **시퀀스 할당 크기** — 실제 기록된 시퀀스 행 수(14) 보다 1 많음. AIMS 가 예약 슬롯 1개를 포함해 카운트하는 것으로 추정. 실제 기록 수 + 1 로 출력하면 호환.                                                                                                         |

> **구현 원칙**: 세 값은 뒤에서 정확히 세어 채워 넣는다. 잘못 채우면 AIMS 가 버퍼를 잘못 잡아 하단 섹션을 읽지 못할 수 있다.

---

## 4. Head Information 섹션

### 4.1 섹션 시작

```
"--- Event Tree Information ---"
"Head Information"
```

이 두 줄은 고정 문자열로 반드시 이 순서로 출력.

### 4.2 Head 정의 행

한 헤딩당 1행:

```
<idx>,"<HeadID>","<DisplayName>","","",""
```

| 필드 | 타입   | 설명                                                          |
|------|--------|---------------------------------------------------------------|
| 1    | int    | 0부터 시작하는 헤딩 인덱스 (순서가 곧 ET 좌→우 순서)           |
| 2    | string | 헤딩 ID (공백 없는 짧은 식별자, 예: `SG-ISOL`, `PAFS`, `RT`)   |
| 3    | string | 화면 표시용 설명 (공백/영문 문장 허용, 한글은 인코딩 주의)     |
| 4~6  | string | 예약 필드. 샘플에서 모두 `""`. **`""` 고정 출력**              |

### 4.3 샘플 매핑 예

```
0,"GCONSGTR","Consequential SGTR","","",""     ← idx=0 : IE 전용 헤딩 (아래 §5.3 참고)
1,"SG-ISOL","Faulted Steam Generator Isolation ","","",""
2,"PAFS","Secondary Cooldown by PAFS","","",""
...
9,"EMGB-OR","Emergency Boration (Sensitivity)","","",""
```

- **idx=0 헤딩은 "Initiating Event 자체"를 의미**한다. 실제 사용자가 보는 헤딩(분기점) 은 idx=1 부터. 따라서 분기 헤딩이 9개이면 `#NoEvent` 의 Head 카운트는 **10** 이다.
- 우리 프로그램 대응: 본 프로젝트의 `headings` 리스트에 사고 유형명 (예: `LOFW`, `SLOCA2`) 를 idx=0 슬롯으로 강제 삽입해야 한다.

---

## 5. Branch Information 섹션 (핵심)

### 5.1 섹션 시작

```
"Branch Information"
```

이후 라인들은 **DFS 순회 순서로 직렬화된 트리** 이다.

### 5.2 브랜치 레코드 문법

각 브랜치는 **정의 라인 1개 + (자식 ID 참조 라인 Type개)** 로 구성된다.

#### 정의 라인

```
<ID>,<ParentID>,<Type>,"<GateName>",<Flag>,"<Remark>"
```

| 필드      | 타입   | 의미                                                                      |
|-----------|--------|---------------------------------------------------------------------------|
| ID        | int    | 브랜치 고유 번호. 0부터 시작, 파일 내에서 오름차순 DFS.                    |
| ParentID  | int    | 부모 브랜치 ID. 루트는 `-1`.                                              |
| Type      | int    | 0 = 말단(Terminal), 1 = 단일 경로(Skip/N-A), 2 = 이진 분기(Success/Fail) |
| GateName  | string | Fail 분기일 때 실패 게이트명 (예: `GEMG-BOR`). Success/Skip 분기는 `""`. 루트(ID=0) 에 한해 Initiating Event 이름 (예: `IE-CSGTR`). |
| Flag      | int    | 샘플 전부 `0`. 의미 미상 → **`0` 고정 출력**                              |
| Remark    | string | 샘플 전부 `""`. **`""` 고정 출력**                                        |

#### 자식 참조 라인

정의 라인 바로 뒤에 Type 개수만큼 자식 브랜치 ID 를 각각 **숫자만 한 줄씩** 출력한다.

- Type=2 → 자식 ID 2줄. **첫 줄 = Success 자식, 두 번째 줄 = Fail 자식** (관례)
- Type=1 → 자식 ID 1줄 (Skip 의 유일 continuation)
- Type=0 → 자식 ID 라인 없음 (곧바로 다음 브랜치 정의가 이어짐)

### 5.3 루트 브랜치 특례

```
0,-1,2,"IE-CSGTR",0,""
1
44
```

- `ParentID=-1` 은 "없음". AIMS 는 루트를 하나만 허용한다.
- 루트의 GateName 에는 **Initiating Event 이름** 을 넣는다 (시퀀스 경로 표기의 첫 토큰이 됨, §6.3).
- 루트의 Type 은 보통 `2` (IE 발생 → 첫 헤딩 Success/Fail 로 분기).

### 5.4 Type 별 의미 정밀화

| Type | ET 의미                                                                       | 시퀀스 경로 표기                             |
|------|-------------------------------------------------------------------------------|----------------------------------------------|
| 0    | 해당 경로의 끝점 → Sequence Information 의 한 행과 대응                        | 경로 문자열은 이 노드까지 누적된 값          |
| 1    | 이 헤딩은 해당 경로에서 N/A (논리적으로 가지 없음)                             | **경로에 이 헤딩 토큰이 포함되지 않음**      |
| 2    | 이 헤딩이 Success/Fail 로 분기                                                 | Success = `/<HeadID>`, Fail = `<GateName>`   |

Skip(Type=1) 의 존재 이유: 앞 계통의 상태에 따라 뒤 계통이 물리적으로 의미 없어질 때 (예: 성공 시 완화계통 불필요), 트리 폭을 유지하면서 경로를 생략.

### 5.5 Padding 브랜치

샘플에서 브랜치 71~91 은 모두:

```
71,0,0,"",0,""
72,0,0,"",0,""
...
91,0,0,"",0,""
```

- `ParentID=0`, `Type=0`, 게이트/비고 모두 빈 값.
- 실제 트리에서 도달되지 않는 예약 슬롯으로 보임 (AIMS 내부 할당 정책).
- 우리 생성기는 **이 padding 블록을 굳이 출력하지 않아도 되며**, 출력한다면 `#NoEvent` 두 번째 값과 정확히 맞춰야 한다. 호환을 최대화하려면 **출력 권장**.

### 5.6 DFS 직렬화 규칙 (생성 알고리즘)

```text
assign_id(root=0)
next_id = 1
emit_dfs(node):
    emit "<node.id>,<parent>,<type>,\"<gate>\",0,\"\""
    if type == 2:
        emit "<child0.id>"       # Success
        emit "<child1.id>"       # Fail
        emit_dfs(child0)
        emit_dfs(child1)
    elif type == 1:
        emit "<child0.id>"
        emit_dfs(child0)
    else:  # type == 0
        pass
```

중요한 점: **자식 ID 참조 라인은 자식의 실제 정의보다 먼저 나온다**. 따라서 ID 할당은 DFS 진입 시점에 미리 끝내야 한다 (emit 하기 전에 전체 트리를 한 번 순회해 ID 를 pre-assign 하는 것이 가장 안전).

---

## 6. Sequence Information 섹션

### 6.1 섹션 시작

```
"Sequence Information"
"SEQ#","FREA","STATE","CONSEQUNCE","F_SEQUNCE","S_REMARKS","R_METRICS"
```

두 번째 줄은 컬럼 헤더. 고정 문자열.

### 6.2 시퀀스 행

```
<SeqNum>,"<Frea>","<State>","<Conseq>","<F_Sequnce>","<S_Remarks>","<R_Metrics>"
```

| 필드        | 타입/형식                 | 설명                                                                  |
|-------------|---------------------------|-----------------------------------------------------------------------|
| SEQ#        | int (따옴표 없음)         | 1부터 시작. **첫 행 (SEQ#=1) 은 placeholder 로 예약**.                |
| FREA        | string (지수표기 or "")   | 시퀀스 빈도. 예: `"8.972e-13"`. 계산 전/불필요면 `""`.                |
| STATE       | string                    | 말단 상태. 관찰된 값: `"OK"`, `"CD"`. placeholder 행은 `""`.         |
| CONSEQUNCE  | string                    | 결말 카테고리. 샘플 전부 `""`.                                        |
| F_SEQUNCE   | string                    | **경로 문자열**. §6.3 참고.                                           |
| S_REMARKS   | string                    | 비고. 샘플 전부 `""`.                                                 |
| R_METRICS   | string                    | 지표. 샘플 전부 `""`.                                                 |

### 6.3 F_SEQUNCE 경로 표기

- 토큰 구분자: 공백 `" "`
- 첫 토큰: **Initiating Event 이름** (루트 브랜치의 GateName 그대로, 슬래시 없음)
- 이후 토큰: 트리에서 만난 Type=2 헤딩 순서대로
  - **Success**: `/<HeadID>` (슬래시 + 헤딩 ID)
  - **Fail**: `<GateName>` (슬래시 없음, 그 브랜치의 게이트명)
- Type=1 (Skip) 헤딩은 **토큰에 포함하지 않는다** (§5.4).

예시:

```
IE-CSGTR /SG-ISOL /PAFS /EMGB-OR                                 → OK
IE-CSGTR /SG-ISOL /PAFS GEMG-BOR                                 → CD
IE-CSGTR /SG-ISOL GPAFS-3-SGTR /POSRV /BLD-POSRV GEDV-2          → CD (중간 헤딩 일부 skip)
IE-CSGTR GSGISOL GPOSRV-2-RD                                     → CD
```

### 6.4 Placeholder 행

```
1,"0","","","","",""
```

- SEQ#=1 행은 모든 텍스트 필드가 빈 값, FREA 에 `"0"` 이 들어간 형태로 고정.
- 실제 시퀀스는 **SEQ#=2 부터** 시작한다.
- `#NoEvent` 세 번째 값 = (실제 시퀀스 수 + 1) 로 출력.

### 6.5 시퀀스 ↔ 터미널 브랜치 매핑

Branch Information 의 Type=0 브랜치를 **DFS 순서**로 열거하면, 그 순서가 곧 SEQ#=2, 3, 4, ... 로 1:1 매핑된다. 경로 문자열은 해당 말단 노드까지 누적된 분기 이력을 §6.3 규칙으로 직렬화하여 채운다.

---

## 7. 빈 라인 및 ET Print margin 섹션

### 7.1 섹션 사이 공백 라인

시퀀스 섹션 종료 직후 빈 따옴표 라인 1개:

```
""
```

### 7.2 ET Print margin 섹션

인쇄/표시 설정. **수치만 다르고 구조는 모든 파일에서 동일**. 기본값으로 그대로 복제 출력하면 AIMS 에서 열린다.

```
"ET Print margin"
"Top= ","1.55"
"Bot= ","3.15"
"Left = ","1.35"
"Right = ","1.35"
"ScaleDown = ","1.0"
"HeadRow = ","1.55"
"SeqCol = ","3.6"
"ThickTree = "," 6"
"ThickEvent = "," 3"
"Bot Title = "," 1.5"
"Seq Freq = "," 1"
"Seq Bin = "," 1"
"Seq Num = "," 1"
"HFSize = ","5"
"BFSize = ","5"
"SFSize = ","5"
"TFSize = ","11"
"SFSize = ","5"
"HFName = ","Arial"
"BFName = ","Arial"
"SFName = ","Arial"
"TFName = ","Arial"
"SFName = ","Arial"
"FBold = ",0
```

- 키 문자열의 공백/등호는 **샘플 그대로 1바이트도 바꾸지 말 것** (예: `"Top= "` 는 `=` 뒤에 공백이 있음, `"Left = "` 는 양쪽 모두 공백).
- `"SFSize = "`, `"SFName = "` 가 두 번씩 등장하는 것도 샘플 그대로 보존.
- `"FBold = "` 만 유일하게 값이 숫자(따옴표 없음) `0` 임.

---

## 8. 트레일러: 브랜치별 확장 슬롯

### 8.1 시작

```
"111"
```

3문자 문자열 `"111"` 1줄. 의미 미상이지만 고정값.

### 8.2 슬롯 반복 (인덱스 0 부터 `#NoEvent` 두 번째 값까지)

각 슬롯 블록은 **정확히 4줄**:

```
<index>
"","","","","",""          ← 6필드
"","","",""                ← 5필드… 로 보이지만 실제로는 5개의 "" + 구분자 해석에 따름
""                         ← 1필드
```

> 주의: 원문은
> ```
> "","","","","",""
> "","","","",""
> ""
> ```
> 처럼 두 줄째가 5개의 `""` 로 읽힌다 (샘플의 많은 블록에서 동일). 우리 생성기는 **샘플을 그대로 복제** 하는 것을 목표로 한다.

- 인덱스는 0, 1, 2, ... `#NoEvent[1]` 까지 (샘플에서 0~91 = 92개 블록).
- 각 블록은 해당 브랜치에 대한 "사용자 주석/서식" 확장 필드로 추정되며 빈 값 출력이면 충분.

### 8.3 파일 종료

마지막 슬롯의 마지막 줄 (`""`) 이 곧 EOF. 추가 개행/데이터 없음.

---

## 9. 본 프로그램 (SMART100 PSA Analyzer) 과의 매핑

### 9.1 Binary ET → KET 매핑 테이블

| KET 구성 요소     | 본 프로그램 산출물                                                                   |
|-------------------|--------------------------------------------------------------------------------------|
| 시그니처           | 하드코딩 상수                                                                         |
| 메타 Title         | `scenario_name` (예: `LOFW`, `SBLOCA`, ...) 를 넣어도 되고 비워도 됨                  |
| Head idx=0         | Initiating Event 헤딩. ID = `scenario_name`, Display = 사고 시나리오 설명            |
| Head idx=1..N      | `binary_headings` 리스트 (예: `Reactor_Trip`, `PRHRS_status`, `ADS_status` ...). ID 는 축약명 (`RT`, `PRHRS`, `ADS` ...) 사용 (§5.4 표의 `SHORT_NAME` 맵과 일치) |
| 루트 브랜치        | `ID=0`, `Parent=-1`, `Type=2`, `GateName=<scenario_name>`                            |
| 내부 브랜치        | Binary ET 노드를 DFS 로 직렬화. Success 자식 먼저, Fail 자식 뒤. Gate 이름: Fail 측 `G<HEADID>` (예: `GPRHRS`), Success 측 `""`. |
| 말단 브랜치        | Binary ET 의 leaf. `dominant_outcome` (`OK`/`CD`) 는 시퀀스 STATE 로 매핑.             |
| 시퀀스 FREA        | `branch.probability` 를 지수 표기로 (`f"{p:.3e}"`). 0 이면 `""`.                      |
| 시퀀스 F_SEQUNCE   | §6.3 규칙으로 DFS 경로를 토큰 조립                                                    |
| Skip (Type=1)      | 본 프로그램 현 단계에선 사용하지 않음 (모든 헤딩이 매 경로에 등장하는 완전 이진 ET). 필요 시 `BinaryMapper` 에서 조건부 N/A 로직이 추가될 때 도입. |

### 9.2 게이트 이름 생성 규칙 (제안)

- Fail 측 gate: `G` + `<HEAD_SHORT_ID>` (예: `GRT`, `GPRHRS`, `GADS`)
- 조건부 성공기준이 다를 경우 접미사 추가 가능: `GPRHRS-2`, `GPRHRS-3` 처럼 기준값으로 구분.
- Success 측 gate 는 공백 `""` 고정.

### 9.3 생성 파이프라인 (의사코드)

```python
def write_ket(path, scenario_name, binary_headings, root_node, sequences):
    # root_node: BinaryETNode (dataclass from 분석_2 §4.1), DFS 가능
    # sequences: List[Tuple[path_tokens, end_state, frequency_or_None]]

    # 1) DFS 로 브랜치 ID pre-assign
    nodes_in_order = []
    assign_ids(root_node, nodes_in_order, start_id=0)
    max_idx = max(91, nodes_in_order[-1].id)  # padding 용 (AIMS 기본 할당과 유사하게)

    with open(path, "w", encoding="ascii", newline="\r\n") as f:
        w = f.write
        w('"#2 CONPAS v3.0, developed by [KAERI]#"\n')
        w('"Title=",""\n"UserName=",""\n"Comments=",""\n"PageInsert=",""\n')
        n_heads = len(binary_headings) + 1  # +1 = IE head
        w(f'"#NoEvent=",{n_heads},{max_idx},{len(sequences)+1}\n')

        w('"--- Event Tree Information ---"\n')
        w('"Head Information"\n')
        w(f'0,"{scenario_name}","{scenario_name} Initiating Event","","",""\n')
        for i, h in enumerate(binary_headings, start=1):
            short = SHORT_NAME[h]
            display = COL_DISPLAY.get(h, h)
            w(f'{i},"{short}","{display}","","",""\n')

        w('"Branch Information"\n')
        emit_branch_dfs(w, root_node)            # §5.6
        # padding 0..max_idx 중 미사용 ID 를 모두 출력
        emit_padding_branches(w, used_ids, max_idx)

        w('"Sequence Information"\n')
        w('"SEQ#","FREA","STATE","CONSEQUNCE","F_SEQUNCE","S_REMARKS","R_METRICS"\n')
        w('1,"0","","","","",""\n')              # placeholder
        for i, (tokens, state, frea) in enumerate(sequences, start=2):
            frea_s = f"{frea:.3e}" if frea else ""
            w(f'{i},"{frea_s}","{state}","","{" ".join(tokens)}","",""\n')

        w('""\n')
        emit_et_print_margin(w)                   # §7.2 고정 블록
        w('"111"\n')
        for i in range(0, max_idx + 1):
            w(f'{i}\n"","","","","",""\n"","","",""\n""\n')
```

### 9.4 검증 체크리스트

생성 후 실제 AIMS 에서 열기 전 자체 검증:

- [ ] 1번째 줄이 정확히 시그니처 문자열인가
- [ ] `#NoEvent` 세 숫자가 (Head 수, max Branch ID, 시퀀스 수 + 1) 과 일치
- [ ] 모든 Type=2 브랜치가 자식 2개를 참조, Type=1 은 1개, Type=0 은 0개
- [ ] 모든 브랜치 ID 가 0..max 연속 (빠진 번호 없음 → padding 으로 채움)
- [ ] Success 자식이 Fail 자식보다 먼저 나열됨
- [ ] 시퀀스 SEQ#=1 이 placeholder 행이고 실제 시퀀스는 2 부터
- [ ] F_SEQUNCE 첫 토큰이 IE 이름과 동일, Success 는 `/ID` 형태
- [ ] ET Print margin 블록이 샘플과 바이트 단위로 동일
- [ ] 트레일러 블록이 0..max Branch ID 만큼 반복 (각 4줄)

---

## 10. 알려진 불확실성 (후속 검증 필요)

샘플 파일 1종만 분석한 단계이므로, 아래 항목은 **추가 샘플 또는 AIMS 공식 문서** 로 확인해야 한다.

| 항목                     | 현재 이해                                         | 확인 방법                              |
|-------------------------|-------------------------------------------------|----------------------------------------|
| `#NoEvent` 세 번째 숫자 | 시퀀스 수 + 1 (placeholder 포함)                 | 시퀀스 수가 다른 샘플과 비교           |
| Padding 브랜치 출력 여부 | 출력 권장 (예약 슬롯)                             | 출력 생략 시 AIMS 동작 테스트          |
| 브랜치 Flag 필드(5번째) | 항상 `0`                                          | 0 이 아닌 샘플 탐색                    |
| 트레일러 `"111"` 의미   | 플래그 상수로 고정                                 | 다른 버전 ET 파일 비교                  |
| 인코딩                  | ASCII (한글 사용 회피 권장)                        | 한글 Display 를 넣은 파일 테스트        |
| 줄바꿈                  | CRLF 로 출력 권장 (Windows 네이티브 툴이라)       | LF 전용 파일로 열어 동작 확인          |

첫 번째 구현은 샘플 파일을 재현하는 **라운드트립 테스트** (우리 생성기가 샘플과 바이트 유사한 파일을 만들 수 있는지) 로 유효성을 검증하고, 이후 본 프로그램의 Binary ET 결과로 확장 적용한다.
