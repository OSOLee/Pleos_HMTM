"""일관성: 같은 사고의 다른 파일(색 변경, 테두리, 크기, 앞뒤 자름)에서 자동 결과가 같은지 비교

  python tools/evaluate/consistency.py > outputs/일관성.md

기준 영상(outputs/eval_auto)과 복사본(outputs/consistency, 모서리는 tools/evaluate/map_corners.py로 옮김)을 짝지어
사고마다 이것을 본다. 각자의 AI Hub 정답 라벨(gt_cc, gt_copies)로 당사자를 맞춘다.
- 분석: 둘 다 고정 카메라로 분석했는지
- 당사자: 둘 다 정답 쌍을 골랐는지
- 사실: 둘 다 맞았을 때, 라벨 A·B 각각의 들어온 길·진행 방향(답 없이 모델이 정한 값)이 같은지
- 판정: 도표와 라벨 A·B 기준 비율이 같은지
"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())
sys.path.insert(0, "tools")
from results_table import assign
from src.eval.match_parties import align_gt, match


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def summary(out_dir, gt_path):
    app = load(os.path.join(out_dir, "app.json"))
    if app["status"] == "unsupported" or not os.path.exists(os.path.join(out_dir, "tracks_final.json")):
        return {"analysed": False}
    m = match(align_gt(load(gt_path), out_dir), load(os.path.join(out_dir, "tracks_final.json"))["tracks"])
    c = app.get("collision")
    ab = assign(sorted([c["a"], c["b"]]), m) if c else None
    s = {"analysed": True, "party": bool(ab)}
    if ab:
        facts = load(os.path.join(out_dir, "facts_judge.json"))["parties"]
        s["facts"] = {p: (facts[t].get("entry_from"), facts[t].get("movement")) for p, t in zip("AB", ab)}
        v = app.get("verdict") or {}
        f = v.get("fault_by_track")
        s["verdict"] = (v.get("rule_id"), (f[ab[0]], f[ab[1]]) if f else None)
    return s


def main():
    split = load("splits/cctv_split.json")
    rows = []
    for a in split["accidents"]:
        ref = a["reference"]
        if not os.path.exists(f"outputs/eval_auto/{ref}/app.json"):
            continue
        r = summary(f"outputs/eval_auto/{ref}", f"outputs/gt_cc/{ref}.json")
        for v in a["videos"]:
            if v == ref or not os.path.exists(f"outputs/consistency/{v}/app.json"):
                continue
            c = summary(f"outputs/consistency/{v}", f"outputs/gt_copies/{v}.json")
            # 복사본 라벨의 A·B가 기준과 반대로 붙은 경우(cc_3_211208 묶음) 기준 A·B로 맞춘다 (make_split의 ab)
            if c.get("facts") and next(l["ab"] for l in a["labels"] if l["video"] == v) == "swapped":
                c["facts"] = {"A": c["facts"]["B"], "B": c["facts"]["A"]}
                rule, f = c["verdict"]
                c["verdict"] = (rule, f[::-1] if f else None)
            row = {"ref": ref, "copy": v, "analysed": r["analysed"] and c["analysed"]}
            if row["analysed"]:
                row["party"] = (r["party"], c["party"])
                if r["party"] and c["party"]:
                    row["facts_same"] = r["facts"] == c["facts"]
                    row["verdict_same"] = r["verdict"] == c["verdict"]
                    row["detail"] = (r["facts"], c["facts"], r["verdict"], c["verdict"])
            else:
                row["why"] = f"분석 안 됨 (기준 {r['analysed']}, 복사본 {c['analysed']})"
            rows.append(row)

    yn = lambda b: "같음" if b else "다름"
    print("| 기준 | 복사본 | 당사자 (기준/복사본) | 사실 | 판정 | 비고 |")
    print("|---|---|---|---|---|---|")
    for r in rows:
        if not r["analysed"]:
            print(f"| {r['ref'][5:11]} | {r['copy'][5:11]} | - | - | - | {r['why']} |")
            continue
        p = "/".join("맞음" if x else "틀림" for x in r["party"])
        if "facts_same" in r:
            rf, cf, rv, cv = r["detail"]
            note = "" if r["facts_same"] and r["verdict_same"] else f"기준 {rf} {rv} / 복사본 {cf} {cv}"
            print(f"| {r['ref'][5:11]} | {r['copy'][5:11]} | {p} | {yn(r['facts_same'])} | {yn(r['verdict_same'])} | {note} |")
        else:
            print(f"| {r['ref'][5:11]} | {r['copy'][5:11]} | {p} | - | - | |")
    an = [r for r in rows if r["analysed"]]
    both = [r for r in an if "facts_same" in r]
    print(f"\n쌍 {len(rows)}개, 둘 다 분석 {len(an)}개, 당사자 결과(맞음/틀림)가 같음 "
          f"{sum(r['party'][0] == r['party'][1] for r in an)}/{len(an)}, 둘 다 맞음 {len(both)}개 중 "
          f"사실 같음 {sum(r['facts_same'] for r in both)}, 판정 같음 {sum(r['verdict_same'] for r in both)}")


if __name__ == "__main__":
    main()
