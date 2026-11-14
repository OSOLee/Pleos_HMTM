"""AI Hub 정답 라벨의 A(빨강)·B(파랑) 박스와 지나온 길, 교차로(노랑)·진입로(회색) 영역을 6장면에 그린다

  python tools/evaluate/gt_sheet.py cc_3_211208_vehicle_120_011              # outputs/check/gt/<영상>.jpg
  python tools/evaluate/gt_sheet.py cc_3_211208_vehicle_120_011 --scene outputs/eval_tap/<영상>/scene.json

먼저 필요한 것: outputs/gt_cc/<영상>.json, data/videos/cc/<영상>.mp4, 장면(scene.json)
"""
import argparse
import json
import os

import cv2
import numpy as np

COLOR = {"A": (0, 0, 255), "B": (255, 128, 0)}
TILES = 6        # 라벨 프레임 중 고르게 뽑을 장면 수
TILE_W = 640     # 장면 한 칸의 폭


def run(name, scene_path, out_path):
    with open(f"outputs/gt_cc/{name}.json", encoding="utf-8") as f:
        gt = json.load(f)
    with open(scene_path, encoding="utf-8") as f:
        scene = json.load(f)
    lab = {p: {fr["frame"]: o for fr in gt["frames"] for o in fr["objects"] if o["party"] == p} for p in "AB"}
    keys = sorted(set(lab["A"]) | set(lab["B"]))
    picks = [keys[int(i * (len(keys) - 1) / (TILES - 1))] for i in range(TILES)]

    cap = cv2.VideoCapture(f"data/videos/cc/{name}.mp4")
    tiles = []
    for f in picks:
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, img = cap.read()
        if not ok:
            continue
        h, w = img.shape[:2]
        for z in scene["zones"]:
            pts = np.array([[int(x * w), int(y * h)] for x, y in z["polygon"]], np.int32)
            inter = z["type"] == "intersection"
            cv2.polylines(img, [pts], True, (0, 255, 255) if inter else (150, 150, 150), 2)
            if not inter:
                cv2.putText(img, z["id"], tuple(pts.mean(axis=0).astype(int)), 0, 1.0, (200, 200, 200), 2)
        for p in "AB":
            path = [lab[p][k]["pos"] for k in sorted(lab[p]) if k <= f]
            for a, b in zip(path, path[1:]):
                cv2.line(img, (int(a[0] * w), int(a[1] * h)), (int(b[0] * w), int(b[1] * h)), COLOR[p], 3)
            o = lab[p].get(f)
            if o:
                x, y, bw, bh = o["bbox"]
                cv2.rectangle(img, (int(x * w), int(y * h)), (int((x + bw) * w), int((y + bh) * h)), COLOR[p], 3)
                cv2.putText(img, f"{p} {o['cls']}", (int(x * w), int(y * h) - 8), 0, 1.0, COLOR[p], 3)
        cv2.putText(img, f"f{f}", (20, 60), 0, 2, (255, 255, 255), 4)
        tiles.append(cv2.resize(img, (TILE_W, int(TILE_W * h / w))))
    cap.release()
    while len(tiles) % 2:
        tiles.append(np.zeros_like(tiles[0]))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cv2.imwrite(out_path, np.vstack([np.hstack(tiles[i:i + 2]) for i in range(0, len(tiles), 2)]))
    print(f"저장: {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="정답 라벨 A·B를 영상 장면에 그린 확인용 그림")
    ap.add_argument("name", help="영상 이름 (확장자 없이)")
    ap.add_argument("--scene", help="scene.json (기본 outputs/eval_auto/<영상>/scene.json)")
    ap.add_argument("--out", help="저장 경로 (기본 outputs/check/gt/<영상>.jpg)")
    args = ap.parse_args()
    run(args.name, args.scene or f"outputs/eval_auto/{args.name}/scene.json",
        args.out or f"outputs/check/gt/{args.name}.jpg")
