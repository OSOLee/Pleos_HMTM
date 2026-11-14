"""AI Hub 교통사고 영상 데이터 라벨 점검: 원천 영상을 받기 전에 라벨만으로 구성을 파악

사용법:
  python inspect_aihub.py D:\\mtm_data\\labels
  python inspect_aihub.py D:\\mtm_data\\labels --examples 3      # 종류별 JSON 예시 경로도 출력
결과: 화면 요약 + <폴더>/_inspect_summary.json

라벨 JSON 형식을 정확히 몰라도 동작하도록, 파일 안을 훑어
  - "bbox"와 "category"가 있는 항목 → 박스로 집계
  - "filming_way", "video_name" 등이 있는 항목 → 영상 정보로 집계
"""
import argparse
import json
import zipfile
from collections import Counter, defaultdict
from pathlib import Path


def load_json(path):
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            return json.loads(Path(path).read_text(encoding=enc))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return None


def walk(obj, fn):
    """중첩된 dict/list를 모두 방문"""
    if isinstance(obj, dict):
        fn(obj)
        for v in obj.values():
            walk(v, fn)
    elif isinstance(obj, list):
        for v in obj:
            walk(v, fn)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="라벨을 풀어 둔 폴더")
    ap.add_argument("--examples", type=int, default=2)
    a = ap.parse_args()
    root = Path(a.root)

    zips = list(root.rglob("*.zip"))
    files = list(root.rglob("*.json"))
    print(f"zip {len(zips)}개, json {len(files)}개")
    if zips and not files:
        print("→ 아직 압축이 풀리지 않았습니다. 7-Zip 등으로 먼저 풀어 주세요.")
        return

    cat_boxes, cat_images = Counter(), Counter()
    filming, pov, place_videos = Counter(), Counter(), Counter()
    sizes, frames_per_video = Counter(), defaultdict(int)
    kinds, examples, keys_seen = Counter(), defaultdict(list), defaultdict(Counter)
    bad = 0

    for f in files:
        data = load_json(f)
        if data is None:
            bad += 1
            continue
        found = {"box": 0, "video": False, "cats": set()}

        def visit(d):
            if "bbox" in d and "category" in d:
                found["box"] += 1
                c = str(d["category"])
                cat_boxes[c] += 1
                found["cats"].add(c)
            if "filming_way" in d or "accident_type" in d or "video_point_of_view" in d:
                found["video"] = True
                filming[str(d.get("filming_way"))] += 1
                pov[str(d.get("video_point_of_view"))] += 1
            if "width" in d and "height" in d and "file_name" in d:
                sizes[f"{d['width']}x{d['height']}"] += 1
                if "video_file_name" in d:
                    frames_per_video[str(d["video_file_name"])] += 1

        walk(data, visit)
        for c in found["cats"]:
            cat_images[c] += 1
        kind = "box" if found["box"] else ("video" if found["video"] else "other")
        kinds[kind] += 1
        place_videos[f"{kind} | {f.parent.name}"] += 1
        if len(examples[kind]) < a.examples:
            examples[kind].append(str(f))
        if isinstance(data, dict):
            keys_seen[kind].update(data.keys())

    summary = {
        "json_total": len(files), "unreadable": bad, "kinds": dict(kinds),
        "categories_boxes": dict(cat_boxes.most_common()),
        "categories_images": dict(cat_images.most_common()),
        "filming_way": dict(filming), "point_of_view": dict(pov),
        "image_sizes": dict(sizes.most_common(5)),
        "videos_with_frame_labels": len(frames_per_video),
        "frames_per_video_avg": round(sum(frames_per_video.values()) / max(1, len(frames_per_video)), 1),
        "files_per_folder": dict(sorted(place_videos.items())),
        "top_level_keys": {k: [x for x, _ in v.most_common(15)] for k, v in keys_seen.items()},
        "examples": dict(examples),
    }
    out = root / "_inspect_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[JSON 종류] 박스 라벨 {kinds['box']} / 영상 라벨 {kinds['video']} / 기타 {kinds['other']} / 읽기 실패 {bad}")
    print("\n[클래스별 박스 수 (박스가 있는 이미지 수)]")
    for c, n in cat_boxes.most_common():
        print(f"  {c:<20} {n:>9,}  ({cat_images[c]:,})")
    print(f"\n[촬영 방법] {dict(filming)}   (cc = CCTV, bb = 블랙박스)")
    print(f"[영상 시점] {dict(pov)}   (1 = 1인칭, 3 = 3인칭)")
    print(f"[이미지 크기] {dict(sizes.most_common(3))}")
    print(f"[프레임 라벨이 있는 영상] {len(frames_per_video):,}개, 영상당 평균 {summary['frames_per_video_avg']}프레임")
    print("\n[예시 파일]")
    for k, v in examples.items():
        for p in v:
            print(f"  {k}: {p}")
    print(f"\n요약 저장: {out}")


if __name__ == "__main__":
    main()
