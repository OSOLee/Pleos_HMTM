import os
import sys
import json
import glob
from collections import Counter, defaultdict

def parse_dir_name(d):
    split, obj, _, place = os.path.basename(d).split("_", 3)
    return split, obj, place

def rates(v):
    """(A 과실, B 과실). 비율이 하나만 있는 형식은 B를 None으로 둔다"""
    if "accident_negligence_rateA" in v:
        return v["accident_negligence_rateA"], v["accident_negligence_rateB"]
    return v["accident_negligence_rate"], None

def run(root="data/aihub/video_labels", out_path="outputs/aihub_survey.json"):
    rows = []
    for d in sorted(glob.glob(os.path.join(root, "*"))):
        if not os.path.isdir(d):
            continue
        split, obj, place = parse_dir_name(d)
        for p in glob.glob(os.path.join(d, "**", "*.json"), recursive=True):
            with open(p, encoding="utf-8") as f:
                v = json.load(f)["video"]
            
            rate_a, rate_b = rates(v)
            rows.append({"split": split, "object": obj, "place": place,
                         "name": v["video_name"], "filming_way": v["filming_way"],
                         "rate_a": rate_a, "rate_b": rate_b,
                         "type": v.get("traffic_accident_type", v.get("accident_type"))})

    if not rows:
        raise SystemExit(f"영상 라벨을 찾지 못했음: {root} (압축을 풀었는지 확인)")
    ways = sorted({r["filming_way"] for r in rows})
    table = defaultdict(Counter)
    for r in rows:
        table[(r["object"], r["place"])][r["filming_way"]] += 1

    print(f"영상 {len(rows)}개 | filming_way {dict(Counter(r['filming_way'] for r in rows))}\n")
    print("사고 객체 | 장소 | " + " | ".join(ways))
    for (obj, place), c in sorted(table.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"{obj} | {place} | " + " | ".join(str(c[w]) for w in ways))

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print(f"\n저장: {out_path}")

if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "data/aihub/video_labels"
    run(root)