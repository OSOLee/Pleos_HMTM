"""평가 영상 결과표: 앱 프로토타입 결과 + AI Hub 정답(outputs/gt_cc) -> 마크다운 표

  python tools/evaluate/results_table.py > outputs/결과표_자동.md                      # outputs/eval_auto
  python tools/evaluate/results_table.py outputs/eval_tap > outputs/결과표_답반영.md   # 답·당사자 표시 반영

먼저 필요한 것:
  - outputs/gt_cc/<영상>.json        (src/dataset/aihub.py)
  - <결과 폴더>/<영상>/app.json       (run_app.py --out <결과 폴더>/<영상>, 답이 있으면 --answers까지)
  - 당사자 매칭은 app 폴더 결과로 다시 계산한다 (src/eval/match_parties.match)
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.getcwd())
from src.dataset.aihub import rates
from src.eval.match_parties import align_gt, match

# 기준 영상 -> 허용 비율 목록 (같은 사고의 복사본 라벨을 기준 영상 A·B로 맞춘 것, tools/data/make_split.py)
with open("splits/cctv_split.json", encoding="utf-8") as _f:
    ALLOWED = {a["reference"]: a["allowed"] for a in json.load(_f)["accidents"]}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def assign(pair, m):
    """고른 두 궤적을 라벨 A·B에 맞춘다. 한 궤적이 라벨 한쪽과 한 번 이상 겹치고, 그쪽과 더 많이 겹쳐야 한다.
    두 차가 한 궤적으로 이어붙여진 궤적(merged_tracks)은 인정하지 않는다. 반환: (A 궤적, B 궤적) 또는 None"""
    hits = {p: m[p]["tracks"] for p in "AB"}
    for a, b in (pair, pair[::-1]):
        if a in m["merged_tracks"] or b in m["merged_tracks"]:
            continue
        if hits["A"].get(a, 0) > hits["B"].get(a, 0) and hits["B"].get(b, 0) > hits["A"].get(b, 0):
            return a, b
    return None


def row(gt_path, app_root="outputs/eval_auto"):
    name = os.path.basename(gt_path)[:-5]
    gt = load(gt_path)
    ra, rb = rates(gt["label"])
    rb = rb if rb is not None else 100 - ra
    app_dir = os.path.join(app_root, name)
    if not os.path.exists(os.path.join(app_dir, "app.json")):
        return None
    app = load(os.path.join(app_dir, "app.json"))
    # 이동 카메라로 판정돼 분석을 안 한 영상은 궤적이 없음 (휴대폰 재촬영 등)
    tracks_path = os.path.join(app_dir, "tracks_final.json")
    tracks = load(tracks_path)["tracks"] if os.path.exists(tracks_path) else {}
    m = match(align_gt(gt, app_dir), tracks)
    ta, tb = m["A"]["track"], m["B"]["track"]

    pair = sorted([app["collision"]["a"], app["collision"]["b"]]) if app.get("collision") else None
    # 고른 쌍이 라벨 A·B와 겹치는지로 본다. 라벨과 가장 많이 겹친 궤적 id와 비교하면, 같은 차를
    # 다른 궤적(사용자가 표시한 9001번 등)으로 고른 경우도 불일치가 된다
    assigned = assign(pair, m) if pair else None
    if not (m["A"]["matched"] and m["B"]["matched"]):
        party = "못 잡음"
    elif assigned:
        party = "일치"
        ta, tb = assigned
    else:
        party = "불일치"

    v = app.get("verdict") or {}
    fault = v.get("fault_by_track")
    if app["status"] in ("no_collision", "cannot_analyze", "unsupported"):
        verdict, ratio, ok = f"- ({app['status']})", "-", "-"
    elif not fault:
        verdict, ratio, ok = "해당 규칙 없음", "-", "-"
    else:
        verdict = v["rule_id"]
        ratio = " : ".join(f"{t}번 {p}" for t, p in fault.items())
        ok = "일치" if party == "일치" and fault.get(ta) == ra and fault.get(tb) == rb else "불일치"
        # 같은 사고의 복사본에 다른 라벨이 붙은 경우, 그 비율과 맞으면 "허용 일치" (splits의 allowed, 기준 영상 A·B 순서)
        if ok == "불일치" and party == "일치" and [fault.get(ta), fault.get(tb)] in ALLOWED.get(name, []):
            ok = "허용 일치"

    notes = []
    if app["status"] == "needs_answers":
        notes.append(f"질문 {len(app['questions'])}개 남음")
    elif app.get("answers"):
        notes.append("답 반영")
    if len(ALLOWED.get(name, [])) > 1:
        notes.append("복사본 라벨 다름: " + ", ".join(f"{a}:{b}" for a, b in ALLOWED[name]))
    return {
        "video": name.split("_")[2],
        "verdict": verdict,
        "ratio": ratio,
        "gt": f"{gt['label'].get('traffic_accident_type', gt['label'].get('accident_type'))} / A {ra} : B {rb}",
        "gt_tracks": f"A {ta or '-'}, B {tb or '-'}",
        "pair": " ↔ ".join(pair) if pair else "-",
        "party": party,
        "ok": ok,
        "note": ", ".join(notes),
    }


def main():
    app_root = sys.argv[1] if len(sys.argv) > 1 else "outputs/eval_auto"
    rows = [r for g in sorted(glob.glob("outputs/gt_cc/*.json")) if (r := row(g, app_root))]
    print("| 영상 | 판정 도표 | 판정 비율 (track) | AI Hub 유형 / 비율 | 정답 track | 고른 충돌 쌍 | 당사자 | 비율 일치 | 비고 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['video']} | {r['verdict']} | {r['ratio']} | {r['gt']} | {r['gt_tracks']} | {r['pair']} "
              f"| {r['party']} | {r['ok']} | {r['note']} |")
    n = len(rows)
    print(f"\n당사자 일치 {sum(r['party'] == '일치' for r in rows)}/{n}, "
          f"비율 일치 {sum(r['ok'] == '일치' for r in rows)}/{n}, "
          f"허용 비율까지 {sum(r['ok'] in ('일치', '허용 일치') for r in rows)}/{n}")


if __name__ == "__main__":
    main()
