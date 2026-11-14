"""탐지를 다시 돌려 궤적 번호가 바뀐 결과 폴더로 답(answers.json)을 옮긴다

  python tools/evaluate/remap_answers.py <옛 결과 폴더> <새 결과 폴더>    # → <새 결과 폴더>/answers.json

재학습 모델로 바꾸면 같은 차라도 궤적 번호가 달라져서, 사람이 장면을 보고 넣은 답(진행 방향, 진입로 등)이
옛 번호에 묶여 버린다. 옛 궤적과 같은 프레임에서 박스가 가장 많이 겹치는 새 궤적으로 번호를 바꿔 준다.
직접 표시한 당사자(user_tracks, 9001부터)는 박스가 그대로라 번호를 바꾸지 않는다. 짝을 못 찾은 답은 빼고 알려 줌.
"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())
from src.app.tap_track import USER_ID_MIN
from src.eval.match_parties import iou

MIN_IOU = 0.3      # 같은 프레임 박스 겹침 평균이 이보다 작으면 같은 차로 보지 않음
MIN_COMMON = 5     # 같이 보인 프레임이 이보다 적으면 짝으로 보지 않음


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def track_map(old_tracks, new_tracks, tids):
    """옛 궤적 id → 새 궤적 id (평균 IoU가 가장 큰 것)"""
    new_by = {t: {r["frame"]: r["bbox"] for r in tr["frames"]} for t, tr in new_tracks.items()}
    out = {}
    for t in tids:
        if int(t) >= USER_ID_MIN:
            out[t] = t
            continue
        if t not in old_tracks:
            continue
        old = {r["frame"]: r["bbox"] for r in old_tracks[t]["frames"]}
        best, best_iou = None, 0.0
        for nt, nb in new_by.items():
            common = set(old) & set(nb)
            if len(common) < MIN_COMMON:
                continue
            m = sum(iou(old[f], nb[f]) for f in common) / len(common)
            if m > best_iou:
                best, best_iou = nt, m
        if best is not None and best_iou >= MIN_IOU:
            out[t] = best
    return out


def remap(old_dir, new_dir):
    ans = load(os.path.join(old_dir, "answers.json"))
    tids = set(map(str, ans.get("collision.parties") or []))
    tids |= {k.split(".")[1] for k in ans if k.startswith("parties.")}
    order = ans.get("intersection_entry_order")
    if order not in (None, "same_time"):
        tids.add(str(order))
    m = track_map(load(os.path.join(old_dir, "tracks_final.json"))["tracks"],
                  load(os.path.join(new_dir, "tracks_final.json"))["tracks"], tids)
    out, dropped = {}, []
    for k, v in ans.items():
        if k.startswith("parties."):
            _, t, key = k.split(".", 2)
            if t in m:
                out[f"parties.{m[t]}.{key}"] = v
            else:
                dropped.append(k)
        elif k == "collision.parties":
            if all(str(t) in m for t in v):
                out[k] = [m[str(t)] for t in v]
            else:
                dropped.append(k)
        elif k == "intersection_entry_order" and v != "same_time":
            if str(v) in m:
                out[k] = m[str(v)]
            else:
                dropped.append(k)
        else:
            out[k] = v
    with open(os.path.join(new_dir, "answers.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return m, dropped


if __name__ == "__main__":
    m, dropped = remap(sys.argv[1], sys.argv[2])
    print(f"{os.path.basename(sys.argv[2].rstrip('/'))}: 번호 바꿈 {m} | 못 옮긴 답 {dropped}")
