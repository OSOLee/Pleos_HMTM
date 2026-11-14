"""facts.json -> 과실 판정 -> result.json

사용법:
  python run_judge.py facts.json
  python run_judge.py facts.json --assume 22.movement=right_turn
  python run_judge.py facts.json --assume 28.damage_severity=severe -o result.json
  python run_judge.py facts.json --assume '22.user_factors=["phone"]'
"""
import argparse
import copy
import itertools
import json
from pathlib import Path

from adapter import load_json, to_engine_facts
from fault_engine import judge

MOVEMENTS = ["right_turn", "left_turn", "straight"]
MOVEMENT_KO = {"right_turn": "우회전", "left_turn": "좌회전", "straight": "직진"}


def parse_value(s):
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return s


def parse_assume(items):
    out = {}
    for s in items or []:
        key, val = s.split("=", 1)
        tid, field = key.split(".", 1)
        out.setdefault(tid, {})[field] = parse_value(val)
    return out


def find_assumptions(raw, explicit):
    if explicit:
        return load_json(explicit)
    stem = Path(str(raw.get("video", ""))).stem
    cand = Path(__file__).parent / "assumptions" / f"{stem}.json"
    if cand.exists():
        return load_json(cand)
    print(f"[경고] 가정 파일을 찾지 못했습니다: {cand}")
    return {}


def fmt(f):
    return ", ".join(f"{k}번 {v}" for k, v in f.items())


def summarize(r):
    if not r["supported"]:
        return "해당 규칙 없음"
    s = f"{r['rule_id']} → {fmt(r['fault_by_track'])}"
    if r["applied_modifiers"]:
        s += "  [적용: " + ", ".join(m["label"] for m in r["applied_modifiers"]) + "]"
    if r["fault_if_pending_by_track"] != r["fault_by_track"]:
        s += f"  (보정 대기 포함 시 {fmt(r['fault_if_pending_by_track'])})"
    s += f"  | 확인 필요 {len(r['unverifiable_factors'])}개"
    return s


def main():
    ap = argparse.ArgumentParser(description="facts.json으로 과실비율 판정")
    ap.add_argument("facts")
    ap.add_argument("--assumptions", help="장소·신호 가정 파일 (없으면 assumptions/<영상이름>.json)")
    ap.add_argument("--assume", action="append", help="차량 값 지정. 예: 22.movement=right_turn")
    ap.add_argument("-o", "--out", default="result.json")
    args = ap.parse_args()

    raw = load_json(args.facts)
    assumptions = find_assumptions(raw, args.assumptions)
    for tid, kv in parse_assume(args.assume).items():
        assumptions.setdefault("parties", {}).setdefault(tid, {}).update(kv)

    facts, assumed = to_engine_facts(raw, assumptions)
    # 사고 유형(차대차·차대보행자·차대자전거)은 엔진이 충돌 당사자의 차종으로 정한다
    result = judge(facts)
    output = {"video": facts.get("video"), "assumptions": assumed, "result": result}

    involved = set(facts["collision"]["between"])
    unknown = [v["track_id"] for v in facts["vehicles"]
               if v["track_id"] in involved and v.get("movement") is None]

    print(f"[{facts.get('video')}]")
    if assumed:
        print("적용한 가정:")
        for a in assumed:
            print(f"  - {a}")

    if not result["supported"] and unknown:
        output["status"] = "needs_confirmation"
        output["message"] = "진행 방향을 알 수 없는 차량이 있어 가정별 결과를 제시합니다."
        output["scenarios"] = []
        print(f"진행 방향 미확인 차량: {', '.join(unknown)}번 → 가정별 결과")
        for combo in itertools.product(MOVEMENTS, repeat=len(unknown)):
            hyp = dict(zip(unknown, combo))
            f2 = copy.deepcopy(facts)
            for v in f2["vehicles"]:
                if v["track_id"] in hyp:
                    v["movement"] = hyp[v["track_id"]]
            r = judge(f2)
            output["scenarios"].append({"assume_movement": hyp, "result": r})
            label = ", ".join(f"{k}번 {MOVEMENT_KO[m]}" for k, m in hyp.items())
            print(f"  - {label}: {summarize(r)}")
    else:
        output["status"] = "ok" if result["supported"] else "no_rule"
        print(f"결과: {summarize(result)}")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"저장: {args.out}")


if __name__ == "__main__":
    main()
