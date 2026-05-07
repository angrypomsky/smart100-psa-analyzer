# -*- coding: utf-8 -*-
"""
GTRN_DEMO_ET_result.xlsx -> GTRN_DEMO.ket 샘플 생성기 (일회성 스크립트).

.ket 형식은 `분석_3_KET_파일_형식.md` 를 따른다 (CONPAS v3.0 / AIMS-PSA 호환).

이진화 규칙:
  RT    : 그대로 (Success/Fail)
  PRHRS : PRHRS_binary 컬럼 그대로 (Success/Fail)
  ADS   : ADS_BLEED_count >= 1 -> Success, 0 -> Fail, NaN -> Skip
  PSIS  : PSIS_FEED_status 그대로 (NaN -> Skip)
  SIT   : SIT_Refill_time 숫자 -> Success, NaN -> Fail 또는 Skip (상위 Skip 전파)

Skip 전파:
  PRHRS Success  -> ADS/PSIS/SIT 모두 Skip
  ADS   Fail(0)  -> PSIS/SIT Skip
  PSIS  Fail     -> SIT Skip
"""
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional
import pandas as pd
import numpy as np

SRC  = Path("pipeline_results/et_results/GTRN_DEMO_ET_result.xlsx")
DEST = Path("pipeline_results/et_results/GTRN_DEMO.ket")
SCENARIO_NAME = "GTRN_DEMO"

# 헤딩 정의: (Short ID, Display Name) -- idx=0 은 IE 전용
HEAD_IE   = (SCENARIO_NAME, "General Transient Initiating Event")
HEADINGS  = [
    ("RT",    "Reactor Trip"),
    ("PRHRS", "PRHRS Cooldown"),
    ("ADS",   "ADS Bleed"),
    ("PSIS",  "PSIS Feed"),
    ("SIT",   "SIT Refill"),
]
# 실패 게이트명 규칙
GATE = {"RT":"GRT", "PRHRS":"GPRHRS", "ADS":"GADS", "PSIS":"GPSIS", "SIT":"GSIT"}

S, F, N = "S", "F", "N"   # N = Skip(N/A)

# ---------------------------------------------------------------- 1) 이진화
def binarize(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["RT"]    = df["Reactor_Trip"].map({"Success":S, "Fail":F}).fillna(F)
    out["PRHRS"] = df["PRHRS_binary"].map({"Success":S, "Fail":F}).fillna(F)

    def ads(row):
        if row["PRHRS"] == S: return N             # Skip
        c = row["_ads_cnt"]
        return S if (pd.notna(c) and c >= 1) else F
    def psis(row):
        if row["PRHRS"] == S: return N
        if row["ADS"]   == F: return N
        v = row["_psis"]
        return S if v == "Success" else F
    def sit(row):
        if row["PRHRS"] == S: return N
        if row["ADS"]   == F: return N
        if row["PSIS"]  == F: return N
        t = row["_sit"]
        return S if pd.notna(t) else F

    out["_ads_cnt"] = df["ADS_BLEED_count"]
    out["_psis"]    = df["PSIS_FEED_status"]
    out["_sit"]     = df["SIT_Refill_time"]
    out["ADS"]  = out.apply(ads,  axis=1)
    out["PSIS"] = out.apply(psis, axis=1)
    out["SIT"]  = out.apply(sit,  axis=1)
    out["Outcome"] = df["Outcome"]
    return out[["RT","PRHRS","ADS","PSIS","SIT","Outcome"]]

# ---------------------------------------------------------------- 2) 트리 구축
@dataclass
class Node:
    head_idx: int                       # 0 = root(IE), 1..N = HEADINGS[i-1]
    path: tuple                         # 여기까지의 (S/F/N) 조합
    type_: int = 0                      # 0 leaf, 1 skip, 2 binary
    gate: str = ""
    parent_id: int = -1
    id: int = -1
    children: List["Node"] = field(default_factory=list)
    count: int = 0
    cd: int = 0
    ok: int = 0

def is_skip(head_short: str, parent_path: tuple) -> bool:
    """
    상위 경로의 상태로 해당 헤딩이 N/A(Skip) 인지 결정.
    parent_path 는 HEADINGS 순서대로 S/F/N 값이 쌓인 튜플.
    index: 0=RT, 1=PRHRS, 2=ADS, 3=PSIS, 4=SIT
    """
    if head_short in ("RT", "PRHRS"):
        return False
    if head_short == "ADS":
        return parent_path[1] == S                    # PRHRS Success
    if head_short == "PSIS":
        return parent_path[1] == S or parent_path[2] == F
    if head_short == "SIT":
        return parent_path[1] == S or parent_path[2] == F or parent_path[3] == F
    return False

def build_tree(bdf: pd.DataFrame) -> Node:
    total = len(bdf)
    root = Node(head_idx=0, path=(), type_=2, gate=SCENARIO_NAME, parent_id=-1)
    root.count = total

    def recurse(node: Node, subset: pd.DataFrame):
        if node.head_idx == len(HEADINGS):
            node.type_ = 0
            node.count = len(subset)
            node.ok = int((subset["Outcome"] == "OK").sum()) if len(subset) else 0
            node.cd = int((subset["Outcome"] == "CD").sum()) if len(subset) else 0
            return

        col = HEADINGS[node.head_idx][0]

        # 1) Skip 판단: 상위 경로 기준
        if is_skip(col, node.path + (None,)*(5-len(node.path))):
            child = Node(head_idx=node.head_idx+1, path=node.path+(N,),
                         type_=2, gate="", parent_id=-1)
            node.type_ = 1
            node.children = [child]
            # 데이터도 함께 넘김 (subset 안의 이 컬럼은 대부분 N 여야 정상)
            recurse(child, subset)
            return

        # 2) 정상 이진 분기
        sub_s = subset[subset[col] == S] if len(subset) else subset
        sub_f = subset[subset[col] == F] if len(subset) else subset
        node.type_ = 2
        child_s = Node(head_idx=node.head_idx+1, path=node.path+(S,),
                       type_=2, gate="", parent_id=-1)
        child_f = Node(head_idx=node.head_idx+1, path=node.path+(F,),
                       type_=2, gate=GATE[col], parent_id=-1)
        node.children = [child_s, child_f]
        recurse(child_s, sub_s)
        recurse(child_f, sub_f)

    recurse(root, bdf)
    return root

def has_any_count(node: Node) -> bool:
    if node.type_ == 0:
        return node.count > 0
    return any(has_any_count(c) for c in node.children)

def prune_dead(node: Node):
    """
    Type=2 의 한 쪽 서브트리가 완전히 비어 있으면 해당 자식만 제거.
    남은 자식이 0개이면 leaf 로, 1개이면 Skip(type=1) 으로 변환하지 않고
    그대로 type=2 유지하되 비어버린 자리에는 count=0 leaf 를 남긴다.
    (ET 구조의 의미를 유지: "물리적으로 가능하나 표본 없음")
    """
    for c in node.children:
        if c.type_ != 0:
            prune_dead(c)
    # 이 샘플 스크립트에서는 의미를 유지하기 위해 pruning 을 하지 않는다.
    return

# ---------------------------------------------------------------- 3) ID 할당 (DFS pre-order)
def assign_ids(root: Node) -> List[Node]:
    order = []
    counter = [0]
    def dfs(n: Node, parent_id: int):
        n.id = counter[0]; counter[0] += 1
        n.parent_id = parent_id
        order.append(n)
        for c in n.children:
            dfs(c, n.id)
    dfs(root, -1)
    return order

# ---------------------------------------------------------------- 4) 시퀀스 수집
def collect_sequences(root: Node) -> List[dict]:
    seqs = []
    def dfs(n: Node, tokens: List[str]):
        # tokens 에는 이미 현재 노드의 결과(Success/Fail) 토큰까지 누적되어야 함
        if n.type_ == 0:
            state = "OK" if n.ok >= n.cd else "CD"
            if n.count == 0:
                state = "N/A"
            freq  = n.count / TOTAL if TOTAL else 0.0
            seqs.append({
                "tokens": tokens[:],
                "state":  state,
                "freq":   freq,
                "count":  n.count,
            })
            return
        for c in n.children:
            # 현재 자식에서 어떤 토큰을 추가할지 결정
            # (c 는 "다음 헤딩"의 노드. 즉 c.head_idx 는 부모 n.head_idx+1 또는 동일)
            # 트리 설계상 c 는 부모에게서 내려온 분기 결과를 path 의 끝에 갖는다.
            new_tokens = tokens[:]
            if n.type_ == 2:
                # 부모 n (head_idx=k) 의 분기는 HEADINGS[k] 헤딩에 대한 결정이다.
                # k 가 유효 헤딩 인덱스인 경우에만 토큰 추가.
                if 0 <= n.head_idx < len(HEADINGS):
                    heading_short = HEADINGS[n.head_idx][0]
                    side = c.path[-1]
                    if side == S:
                        new_tokens.append(f"/{heading_short}")
                    else:  # F
                        new_tokens.append(GATE.get(heading_short, f"G{heading_short}"))
            # type_ == 1 (Skip) 은 토큰 추가 안 함
            dfs(c, new_tokens)
    # 루트는 head_idx=0, IE 자체 -> 첫 토큰은 시나리오명
    init_tokens = [SCENARIO_NAME]
    # 루트가 type=2 면 자식으로 내려갈 때 헤딩 1(RT) 기준 토큰 추가됨
    dfs(root, init_tokens)
    return seqs

# ---------------------------------------------------------------- 5) KET 파일 쓰기
def write_ket(path: Path, nodes: List[Node], seqs: List[dict]):
    max_idx = max(91, nodes[-1].id)      # 최소 91 이상 유지 (CONPAS 기본 예약 크기)
    n_heads = 1 + len(HEADINGS)          # IE + 실제 헤딩 수
    n_seq_field = len(seqs) + 1          # placeholder 포함

    L = []
    CRLF = "\r\n"

    # (1) 시그니처
    L.append('"#2 CONPAS v3.0, developed by [KAERI]#"')
    # (2) 메타
    L.append('"Title=",""')
    L.append('"UserName=",""')
    L.append('"Comments=",""')
    L.append('"PageInsert=",""')
    # (3) 카운트
    L.append(f'"#NoEvent=",{n_heads},{max_idx},{n_seq_field}')
    # (4) 섹션 헤더
    L.append('"--- Event Tree Information ---"')
    # (5) Head Information
    L.append('"Head Information"')
    L.append(f'0,"{HEAD_IE[0]}","{HEAD_IE[1]}","","",""')
    for i, (sid, disp) in enumerate(HEADINGS, start=1):
        L.append(f'{i},"{sid}","{disp}","","",""')
    # (6) Branch Information (DFS pre-order: 정의 + 자식 ID 참조)
    L.append('"Branch Information"')
    used = set()
    for n in nodes:
        L.append(f'{n.id},{n.parent_id},{n.type_},"{n.gate}",0,""')
        used.add(n.id)
        # 자식 ID 참조 라인 (type 만큼)
        for c in n.children:
            L.append(f'{c.id}')
    # Padding: 0..max_idx 중 미사용 ID 채우기
    for i in range(max_idx + 1):
        if i not in used:
            L.append(f'{i},0,0,"",0,""')

    # (7) Sequence Information
    L.append('"Sequence Information"')
    L.append('"SEQ#","FREA","STATE","CONSEQUNCE","F_SEQUNCE","S_REMARKS","R_METRICS"')
    L.append('1,"0","","","","",""')                           # placeholder
    for i, s in enumerate(seqs, start=2):
        frea_s  = f"{s['freq']:.3e}" if s["freq"] > 0 else ""
        path_s  = " ".join(s["tokens"])
        L.append(f'{i},"{frea_s}","{s["state"]}","","{path_s}","",""')
    L.append('""')

    # (8) ET Print margin (샘플 그대로)
    margin_block = [
        '"ET Print margin"',
        '"Top= ","1.55"',
        '"Bot= ","3.15"',
        '"Left = ","1.35"',
        '"Right = ","1.35"',
        '"ScaleDown = ","1.0"',
        '"HeadRow = ","1.55"',
        '"SeqCol = ","3.6"',
        '"ThickTree = "," 6"',
        '"ThickEvent = "," 3"',
        '"Bot Title = "," 1.5"',
        '"Seq Freq = "," 1"',
        '"Seq Bin = "," 1"',
        '"Seq Num = "," 1"',
        '"HFSize = ","5"',
        '"BFSize = ","5"',
        '"SFSize = ","5"',
        '"TFSize = ","11"',
        '"SFSize = ","5"',
        '"HFName = ","Arial"',
        '"BFName = ","Arial"',
        '"SFName = ","Arial"',
        '"TFName = ","Arial"',
        '"SFName = ","Arial"',
        '"FBold = ",0',
    ]
    L.extend(margin_block)

    # (9) Trailer
    L.append('"111"')
    for i in range(max_idx + 1):
        L.append(f'{i}')
        L.append('"","","","","",""')
        L.append('"","","",""')
        L.append('""')

    path.write_text(CRLF.join(L) + CRLF, encoding="ascii", errors="replace")
    print(f"Saved: {path}  (branches={len(nodes)}, seqs={len(seqs)}, max_idx={max_idx})")

# ------------------------------------------------------------------- main
if __name__ == "__main__":
    df = pd.read_excel(SRC, sheet_name=0)
    bdf = binarize(df)
    TOTAL = len(bdf)
    print(f"Loaded {TOTAL} scenarios from {SRC}")
    print(bdf.head(10).to_string())
    print("\nBinary value counts per heading:")
    for h,_ in HEADINGS:
        print(f"  {h}: {dict(bdf[h].value_counts())}")

    root = build_tree(bdf)
    prune_dead(root)
    nodes = assign_ids(root)
    seqs  = collect_sequences(root)

    print(f"\nBranches: {len(nodes)}")
    print(f"Sequences: {len(seqs)}")
    for s in seqs:
        print(f"  [{s['state']:>3}] freq={s['freq']:.4f}  count={s['count']:>3}  {' '.join(s['tokens'])}")

    write_ket(DEST, nodes, seqs)
