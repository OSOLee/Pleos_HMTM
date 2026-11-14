import os
import sys
import json
import glob
from collections import Counter

CLS_MAP = {
    "vehicle": "vehicle",
    "two-wheeled-vehicle": "two_wheeler",
    "pedestrian": "pedestrian",
    "traffic-light-red": "traffic_light",
    "traffic-light-etc": "traffic_light",
    "bike": "bicycle",
}
LIGHT = {"traffic-light-red": "red", "traffic-light-etc": "etc"}

def rates(v):
    if "accident_negligence_rateA" in v:
        return v["accident_negligence_rateA"], v["accident_negligence_rateB"]
    return v["accident_negligence_rate"], None

def party_of(o):
    if o["isObjectA"]:
        return "A"
    if o["isObjectB"]:
        return "B"
    if o["isObjectOthers"]:
        return "others"
    return None

def clean_bbox(b, W, H):
    """[x, y, w, h] 픽셀 -> (0~1 bbox, None) 또는 (None, 버린 이유)"""
    x, y, w, h = b
    if w <= 0 or h <= 0:
        return None, "non_positive_size"
    x1, y1 = max(x, 0), max(y, 0)
    x2, y2 = min(x + w, W), min(y + h, H)
    if x2 <= x1 or y2 <= y1:
        return None, "out_of_image"
    return [round(x1 / W, 4), round(y1 / H, 4),
            round((x2 - x1) / W, 4), round((y2 - y1) / H, 4)], None

def load_video(label_root, name):
    with open(glob.glob(os.path.join(label_root, "영상_*", name + ".json"))[0],
              encoding="utf-8") as f:
        label = json.load(f)["video"]
    frames, dropped = [], []
    for p in glob.glob(os.path.join(label_root, "이미지_*", name, "*.json")):
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
            W, H = d["width"], d["height"]
            fno = d["sequence_frame_number"] - 1
            objs = []
            for o in d["objects"]:
                cls = CLS_MAP.get(o["category"])
                if cls is None:
                    continue
                bbox, why = clean_bbox(o["bbox"], W, H)
                if why:
                    dropped.append({"frame": fno, "reason": why, "category": o["category"],
                                    "party": party_of(o), "bbox_raw": o["bbox"]})
                    continue
                rec = {"cls": cls, "party": party_of(o), "bbox": bbox,
                       "pos": [round(bbox[0] + bbox[2] / 2, 4), round(bbox[1] + bbox[3], 4)]}
                if o["category"] in LIGHT:
                    rec["light"] = LIGHT[o["category"]]
                objs.append(rec)
            frames.append({"frame": fno, "objects":objs})
    
    frames.sort(key=lambda r: r["frame"])
    return label, frames, dropped

def run(label_root, out_dir="outputs/gt"):
    os.makedirs(out_dir, exist_ok=True)
    names = sorted(os.path.splitext(os.path.basename(p))[0]
                   for p in glob.glob(os.path.join(label_root, "영상_*", "*.json")))

    for name in names:
        label, frames, dropped = load_video(label_root, name)
        parties = Counter((ob["party"], ob["cls"]) for fr in frames
                          for ob in fr["objects"] if ob["party"] in ("A", "B"))

        print(f"\n=== {name} ===")
        rate_a, rate_b = rates(label)
        print(f"촬영 {label['filming_way']} | 과실 A {rate_a} : B {rate_b} "
              f"| 사고 유형 {label.get('traffic_accident_type', label.get('accident_type'))}")
        print(f"프레임 {len(frames)}개 | 객체 {sum(len(fr['objects']) for fr in frames)}개 "
              f"| 버림 {len(dropped)}개 {dict(Counter(d['reason'] for d in dropped))}")
        print(f"당사자 라벨 {dict(parties)}")

        out = {
            "schema_version": "0.2",
            "source": "aihub",
            "video": name,
            "label": label,
            "frames": frames,
            "dropped": dropped,
        }
        out_path = os.path.join(out_dir, name + ".json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"저장: {out_path}")


if __name__ == "__main__":
    label_root = sys.argv[1] if len(sys.argv) > 1 else "data/aihub/labels"
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "outputs/gt"
    run(label_root, out_dir)