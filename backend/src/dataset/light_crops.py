"""AI Hub 프레임 라벨의 신호등 박스를 영상에서 잘라 색 분류기 학습·평가용 데이터를 만든다

  python src/dataset/light_crops.py data/videos/bb_lights outputs/lights

라벨 종류: traffic-light-red / traffic-light-green / traffic-light-etc (노랑, 꺼짐, 화살표 등 나머지)
영상 단위로 학습(train)·검증(val)·시험(test)을 나눈다 (같은 영상의 이웃 프레임은 거의 같은 그림이라서).
출력: <out>/crops/<영상>_<프레임>_<k>.png, <out>/index.json [{"file", "label", "video", "split", "w", "h"}]
"""
import glob
import hashlib
import json
import os
import sys
import zipfile

import cv2

sys.path.insert(0, os.getcwd())
from src.dataset.aihub import clean_bbox

LABELS = {"traffic-light-red": "red", "traffic-light-green": "green", "traffic-light-etc": "etc"}
MIN_W = 10      # 이보다 좁은 박스는 색을 볼 수 없어서 뺌 (픽셀)
PAD = 0.15      # 박스를 이만큼 넓혀 자름 (테두리가 잘리지 않게)


def split_of(video):
    """영상 이름 해시로 7 : 1.5 : 1.5"""
    h = int(hashlib.md5(video.encode()).hexdigest(), 16) % 20
    return "train" if h < 14 else "val" if h < 17 else "test"


def label_index():
    """영상 이름 -> {프레임: [(라벨, 박스 픽셀)]}"""
    out = {}
    for z in glob.glob("data/aihub/frame_labels_raw/**/*.zip", recursive=True):
        zf = zipfile.ZipFile(z)
        for n in zf.namelist():
            if not (n.startswith("bb_") and n.endswith(".json")):
                continue
            raw = zf.read(n)
            if b"traffic-light" not in raw:
                continue
            j = json.loads(raw)
            for o in j["objects"]:
                if o["category"] in LABELS:
                    b, _ = clean_bbox(o["bbox"], j["width"], j["height"])
                    if b:
                        out.setdefault(n.split("/")[0], {}).setdefault(int(j["sequence_frame_number"]), []).append(
                            (LABELS[o["category"]], b))
    return out


def run(video_dir, out_dir):
    os.makedirs(os.path.join(out_dir, "crops"), exist_ok=True)
    labels = label_index()
    rows = []
    for path in sorted(glob.glob(os.path.join(video_dir, "*.mp4"))):
        name = os.path.basename(path)[:-4]
        if name not in labels:
            continue
        cap = cv2.VideoCapture(path)
        for f, objs in sorted(labels[name].items()):
            cap.set(cv2.CAP_PROP_POS_FRAMES, f)
            ok, img = cap.read()
            if not ok:
                continue
            H, W = img.shape[:2]
            for k, (lab, (x, y, w, h)) in enumerate(objs):
                px, py, pw, ph = x * W, y * H, w * W, h * H
                if pw < MIN_W:
                    continue
                x1, y1 = int(max(0, px - pw * PAD)), int(max(0, py - ph * PAD))
                x2, y2 = int(min(W, px + pw * (1 + PAD))), int(min(H, py + ph * (1 + PAD)))
                fn = f"{name}_{f:04d}_{k}.png"
                cv2.imwrite(os.path.join(out_dir, "crops", fn), img[y1:y2, x1:x2])
                rows.append({"file": fn, "label": lab, "video": name, "split": split_of(name),
                             "w": round(pw), "h": round(ph)})
        cap.release()
    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8") as fp:
        json.dump(rows, fp, ensure_ascii=False)
    from collections import Counter
    print(len(rows), "개", Counter((r["split"], r["label"]) for r in rows))


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
