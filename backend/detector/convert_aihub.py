"""AI Hub 교통사고 영상 데이터 -> YOLO 학습 데이터

원천은 둘 중 하나:
  --videos  TS_영상 폴더 (권장, 용량이 작음): 라벨의 프레임 번호로 영상에서 필요한 장면만 뽑음
  --images  TS_이미지 폴더: 이미 뽑혀 있는 프레임 사용

사용법:
  python convert_aihub.py --labels D:\\mtm_data\\TL --videos D:\\mtm_data\\TS --out D:\\mtm_data\\dataset_v1 \\
      --max-images 2000 --preview 20 --dry-run          # 먼저 집계와 미리보기만
  python convert_aihub.py ... --exclude eval_list.txt --zip   # 실제 변환
옵션:
  --step 15         영상마다 15프레임(1초)에 한 장씩 사용 (연속 프레임은 거의 같은 사진)
  --max-images N    전체 이미지 수 상한 (1차 2000, 2차 10000 등). 영상 수를 줄여 맞춤
  --exclude 파일    학습에서 뺄 영상 목록 (A의 판정 평가용 목록). 한 줄에 영상 이름 하나
  --split 0.7 0.15 0.15   영상 단위 학습/검증/평가 비율
  --no-stratify     드문 클래스 고르게 나누기를 끄고 무작위로 분할
  --label-fps 15    라벨 프레임 번호의 기준 fps (AI Hub는 1초 15프레임). 영상 fps가 다르면 자동 환산
  --preview N       박스를 그린 확인용 이미지 N장을 <out>/preview에 저장 (라벨과 프레임이 맞는지 눈으로 확인)
  --seq-start auto  라벨 프레임 번호 시작값. auto면 영상마다 최솟값(0 또는 1)을 시작으로 봄 (AI Hub는 001부터)
  --offsets 파일     align_offsets.py가 만든 영상별 추가 오프셋 (uncertain 표시된 영상은 0으로 처리)
  --keep-prefix cc_3_   이 접두어로 시작하는 영상만 사용 (기본: CCTV·3인칭). 빈 문자열이면 모두 사용
  --dry-run         학습 데이터는 만들지 않고 집계와 미리보기만
결과: <out>/images/{train,val,test}, <out>/labels/{train,val,test}, data.yaml, report.json, (선택) dataset.zip
"""
import argparse
import json
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path

IMG_EXT = {".png", ".jpg", ".jpeg"}
VID_EXT = {".mp4", ".avi", ".mov", ".mkv"}


def draw_preview(img, lines, classes, path):
    import cv2
    h, w = img.shape[:2]
    im = img.copy()
    for ln in lines:
        c, cx, cy, bw, bh = ln.split()
        cx, cy, bw, bh = float(cx) * w, float(cy) * h, float(bw) * w, float(bh) * h
        p1, p2 = (int(cx - bw / 2), int(cy - bh / 2)), (int(cx + bw / 2), int(cy + bh / 2))
        cv2.rectangle(im, p1, p2, (0, 255, 255), 2)
        cv2.putText(im, classes[int(c)], (p1[0], max(12, p1[1] - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    cv2.imwrite(str(path), im)


def load_json(path):
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            return json.loads(Path(path).read_text(encoding=enc))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return None


def find_frames(obj, out):
    """JSON 안에서 이미지(프레임) 라벨 단위를 찾음: file_name + objects 를 가진 dict"""
    if isinstance(obj, dict):
        if "file_name" in obj and ("objects" in obj or "width" in obj):
            out.append(obj)
            return
        for v in obj.values():
            find_frames(v, out)
    elif isinstance(obj, list):
        for v in obj:
            find_frames(v, out)


def video_key(frame, label_path):
    v = frame.get("video_file_name") or frame.get("video_name")
    if v:
        return Path(str(v)).stem
    return label_path.parent.name  # 영상 이름이 없으면 폴더 단위로 묶음


def to_yolo(bbox, w, h):
    x, y, bw, bh = [float(t) for t in bbox[:4]]
    x1, y1 = max(0.0, x), max(0.0, y)
    x2, y2 = min(float(w), x + bw), min(float(h), y + bh)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    return ((x1 + x2) / 2 / w, (y1 + y2) / 2 / h, (x2 - x1) / w, (y2 - y1) / h)


def stratified_split(names, sampled, cmap, ignore, ratio, seed):
    """영상 단위로 나누되, 드문 클래스가 학습·검증·평가에 비율대로 들어가도록 욕심쟁이 배정.
    드문 클래스를 많이 가진 영상부터, 그 클래스가 목표보다 가장 부족한 분할에 넣는다."""
    splits = ("train", "val", "test")
    counts = {}
    for v in names:
        c = Counter()
        for fr in sampled[v]:
            for ob in fr.get("objects", []) or []:
                cat = str(ob.get("category", "")).strip().lower()
                if cat in cmap and cat not in ignore:
                    c[cmap[cat]] += 1
        counts[v] = c
    total = Counter()
    for c in counts.values():
        total.update(c)
    rarity = {k: 1.0 / max(1, n) for k, n in total.items()}
    order = sorted(names, key=lambda v: (-sum(rarity[k] * n for k, n in counts[v].items()), v))
    rnd = random.Random(seed)
    got = {s: Counter() for s in splits}
    nvid = Counter()
    target_v = {s: r * len(names) for s, r in zip(splits, ratio)}
    split_of = {}
    for v in order:
        rare = min(counts[v], key=lambda k: total[k]) if counts[v] else None

        def deficit(s):
            # 목표 대비 얼마나 덜 찼는지(0~1). 분할 크기가 달라도 같은 기준으로 비교
            r = ratio[splits.index(s)]
            need_cls = 1 - got[s][rare] / max(1e-9, r * total[rare]) if rare else 0
            need_vid = 1 - nvid[s] / max(1e-9, target_v[s])
            return 2 * need_cls + need_vid + rnd.random() * 1e-6

        s = max(splits, key=deficit)
        split_of[v] = s
        got[s].update(counts[v])
        nvid[s] += 1
    return split_of


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True, help="TL_이미지 라벨 폴더")
    ap.add_argument("--images", default=None, help="TS_이미지 원천 폴더")
    ap.add_argument("--videos", default=None, help="TS_영상 원천 폴더 (권장)")
    ap.add_argument("--label-fps", type=float, default=15.0)
    ap.add_argument("--preview", type=int, default=0)
    ap.add_argument("--keep-prefix", default="cc_3_", help="영상 이름 접두어 필터 (cc=CCTV, 3=3인칭)")
    ap.add_argument("--offsets", default=None, help="align_offsets.py 결과 (영상별 프레임 오프셋)")
    ap.add_argument("--seq-start", default="auto", help="라벨 프레임 번호 시작값: auto, 0, 1")
    ap.add_argument("--min-align", type=float, default=0.0, help="오프셋 적용 후 IoU가 이보다 낮은 영상은 제외")
    ap.add_argument("--out", required=True)
    ap.add_argument("--classes", default=str(Path(__file__).parent / "aihub_classes.json"))
    ap.add_argument("--step", type=int, default=15)
    ap.add_argument("--max-images", type=int, default=0)
    ap.add_argument("--exclude", default=None)
    ap.add_argument("--split", type=float, nargs=3, default=[0.7, 0.15, 0.15])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--zip", action="store_true")
    ap.add_argument("--no-stratify", action="store_true", help="드문 클래스 균형 분할을 끔")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cfg = load_json(a.classes)
    classes = cfg["classes"]
    cmap = {k.strip().lower(): v for k, v in cfg["map"].items()}
    ignore = {s.strip().lower() for s in cfg.get("ignore", [])}
    cid = {c: i for i, c in enumerate(classes)}

    exclude = set()
    if a.exclude:
        exclude = {Path(l.strip()).stem for l in Path(a.exclude).read_text(encoding="utf-8-sig").splitlines() if l.strip()}

    if bool(a.images) == bool(a.videos):
        ap.error("--images 또는 --videos 중 하나만 지정하세요")
    # 1) 원천 색인
    img_index, vid_index = {}, {}
    if a.images:
        print("원천 이미지 색인 중...")
        for p in Path(a.images).rglob("*"):
            if p.suffix.lower() in IMG_EXT:
                img_index[p.name] = p
        print(f"  이미지 {len(img_index):,}장")
    else:
        print("원천 영상 색인 중...")
        for p in Path(a.videos).rglob("*"):
            if p.suffix.lower() in VID_EXT:
                vid_index[p.stem] = p
        print(f"  영상 {len(vid_index):,}개")

    def has_source(v, fr):
        return (v in vid_index) if a.videos else (Path(str(fr["file_name"])).name in img_index)

    # 2) 라벨 읽기 -> 영상별 프레임
    print("라벨 읽는 중...")
    videos = defaultdict(list)
    unknown_cats, n_labels, bad = Counter(), 0, 0
    for lp in Path(a.labels).rglob("*.json"):
        data = load_json(lp)
        if data is None:
            bad += 1
            continue
        frames = []
        find_frames(data, frames)
        for fr in frames:
            n_labels += 1
            videos[video_key(fr, lp)].append(fr)
    print(f"  프레임 라벨 {n_labels:,}개, 영상 {len(videos):,}개, 읽기 실패 {bad}")

    videos_all = {v: list(frs) for v, frs in videos.items()}
    # 3) 정렬 품질이 낮은 영상 제외 (오프셋을 찾아도 박스가 안 맞는 영상)
    low_align = []
    if a.offsets and a.min_align > 0:
        offs = load_json(a.offsets) or {}
        low_align = [v for v in videos if v in offs and offs[v].get("score", 1) < a.min_align]
        for v in low_align:
            del videos[v]
    # 접두어 필터(CCTV·3인칭), 제외 목록, 프레임 간격 샘플링
    filtered = [v for v in videos if a.keep_prefix and not v.startswith(a.keep_prefix)]
    for v in filtered:
        del videos[v]
    excluded = [v for v in videos if v in exclude or any(v.startswith(e) or e in v for e in exclude)]
    for v in excluded:
        del videos[v]
    sampled, missing_img = {}, 0
    for v, frs in videos.items():
        frs = sorted(frs, key=lambda f: int(f.get("sequence_frame_number", 0) or 0))
        pick_all = [f for i, f in enumerate(frs) if int(f.get("sequence_frame_number", i) or i) % a.step == 0]
        pick = [f for f in pick_all if has_source(v, f)]
        missing_img += len(pick_all) - len(pick)   # 라벨은 있는데 원천 이미지가 없는 프레임
        if pick:
            sampled[v] = pick

    # 4) 영상 단위 분할 (+ 이미지 수 상한)
    names = sorted(sampled)
    random.Random(a.seed).shuffle(names)
    if a.max_images:
        keep, total = [], 0
        for v in names:
            if total >= a.max_images:
                break
            keep.append(v)
            total += len(sampled[v])
        names = keep
    n = len(names)
    if a.no_stratify:
        n_tr, n_va = int(n * a.split[0]), int(n * a.split[1])
        split_of = {v: ("train" if i < n_tr else "val" if i < n_tr + n_va else "test") for i, v in enumerate(names)}
    else:
        split_of = stratified_split(names, sampled, cmap, ignore, a.split, a.seed)

    # 5) 쓰기
    out = Path(a.out)
    stats = {s: Counter() for s in ("train", "val", "test")}
    images_per, size_mismatch, read_fail, previews = Counter(), 0, 0, 0
    if a.preview:
        (out / "preview").mkdir(parents=True, exist_ok=True)

    offsets = load_json(a.offsets) if a.offsets else {}

    def seq_start(frs):
        if a.seq_start != "auto":
            return int(a.seq_start)
        return min(int(f.get("sequence_frame_number", 0) or 0) for f in frs) if frs else 0

    def frames_from_video(v, frs):
        """라벨 프레임 번호 -> 영상 프레임 번호로 환산해 차례로 읽음 (오프셋 보정 포함)"""
        import cv2
        cap = cv2.VideoCapture(str(vid_index[v]))
        vfps = cap.get(cv2.CAP_PROP_FPS) or a.label_fps
        o = offsets.get(v, {})
        off = 0 if o.get("uncertain") else int(o.get("offset", 0))
        start = seq_start(videos_all.get(v, frs))
        want = {}
        for fr in frs:
            idx = int(round((int(fr.get("sequence_frame_number", 0) or 0) - start) * vfps / a.label_fps)) + off
            if idx < 0:
                continue
            want.setdefault(idx, []).append(fr)
        got, i, last = {}, 0, max(want) if want else -1
        while i <= last:
            ok, img = cap.read()
            if not ok:
                break
            if i in want:
                for fr in want[i]:
                    got[id(fr)] = img
            i += 1
        cap.release()
        return got

    for v in names:
        s = split_of[v]
        imgs = frames_from_video(v, sampled[v]) if a.videos else {}
        for fr in sampled[v]:
            w, h = fr.get("width"), fr.get("height")
            if not w or not h:
                continue
            if a.videos:
                img = imgs.get(id(fr))
                if img is None:
                    read_fail += 1
                    continue
                if (img.shape[1], img.shape[0]) != (int(w), int(h)):
                    size_mismatch += 1
                src = None
                stem = f"{v}__{int(fr.get('sequence_frame_number', 0) or 0):03d}"
            else:
                src = img_index[Path(str(fr["file_name"])).name]
                img = None
                stem = f"{v}__{src.stem}"
            lines = []
            for ob in fr.get("objects", []) or []:
                cat = str(ob.get("category", "")).strip().lower()
                if cat in ignore:
                    continue
                if cat not in cmap:
                    unknown_cats[ob.get("category")] += 1
                    continue
                box = to_yolo(ob.get("bbox", []), w, h)
                if box is None:
                    continue
                cls = cmap[cat]
                lines.append(f"{cid[cls]} " + " ".join(f"{t:.6f}" for t in box))
                stats[s][cls] += 1
            images_per[s] += 1
            if previews < a.preview:
                import cv2
                pim = img if img is not None else cv2.imread(str(src))
                if pim is not None:
                    draw_preview(pim, lines, classes, out / "preview" / f"{stem}.jpg")
                    previews += 1
            if not a.dry_run:
                import cv2
                (out / "images" / s).mkdir(parents=True, exist_ok=True)
                (out / "labels" / s).mkdir(parents=True, exist_ok=True)
                if img is not None:
                    cv2.imwrite(str(out / "images" / s / f"{stem}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
                else:
                    shutil.copy2(src, out / "images" / s / f"{stem}{src.suffix.lower()}")
                (out / "labels" / s / f"{stem}.txt").write_text("\n".join(lines), encoding="utf-8")

    report = {
        "videos_total": len(videos) + len(excluded) + len(filtered), "videos_filtered_by_prefix": sorted(filtered),
        "videos_excluded": sorted(excluded), "videos_low_alignment": sorted(low_align), "videos_used": n,
        "split_videos": dict(Counter(split_of.values())), "split_images": dict(images_per),
        "boxes_per_class": {s: dict(c) for s, c in stats.items()},
        "unmapped_categories": dict(unknown_cats), "label_frames_without_source": missing_img,
        "video_frame_read_fail": read_fail, "frame_size_mismatch": size_mismatch, "previews": previews,
        "step": a.step, "classes": classes,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if a.dry_run:
        return
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "split_videos.json").write_text(json.dumps(split_of, ensure_ascii=False, indent=1), encoding="utf-8")
    yaml = "path: /content/dataset\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n" + \
        "".join(f"  {i}: {c}\n" for i, c in enumerate(classes))
    (out / "data.yaml").write_text(yaml, encoding="utf-8")
    if a.zip:
        print("압축 중...")
        shutil.make_archive(str(out.parent / "dataset"), "zip", root_dir=out)
        print(f"  {out.parent / 'dataset.zip'}")
    if unknown_cats:
        print("\n[주의] aihub_classes.json에 없는 category가 있어 제외했습니다:", dict(unknown_cats))


if __name__ == "__main__":
    main()
