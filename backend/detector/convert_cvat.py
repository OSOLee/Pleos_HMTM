"""교차로 신호 체계 데이터(CVAT XML 바운딩박스) -> YOLO 학습 데이터에 추가

convert_aihub.py가 만든 데이터 폴더에 이어서 넣는다(--out 같은 폴더). 파일 이름 앞에 'x_'를 붙여 출처를 구분한다.
학습·검증·평가 분할은 카메라(파일 이름 첫 부분, 예: 11011) 단위.

--labels, --images에는 압축을 푼 폴더 또는 **압축 파일 그대로** 줄 수 있다.
AI Hub 교차로 데이터는 확장자가 .zip이지만 실제로는 7z 형식이라 7-Zip으로 읽는다 (Colab: apt-get install p7zip-full).
압축 파일이면 필요한 사진만 꺼내 쓰므로, 드라이브의 53GB TS_4를 풀지 않고 Colab에서 바로 쓸 수 있다.

사용법:
  python convert_cvat.py --labels C:\\mtm_data\\cross\\VL_4 --images C:\\mtm_data\\cross\\VS_4 --out C:\\mtm_data\\work\\dataset_v2 --max-images 4000 --dry-run
  python convert_cvat.py ... (--dry-run 없이)
옵션:
  --min-gap 3       같은 영상에서 3초 이상 떨어진 프레임만 사용 (비슷한 장면 줄이기)
  --max-images N    이 데이터에서 가져올 이미지 수 상한 (사고 영상 데이터와 비율 조절)
  --save-crops      차종(car/bus/truck) 박스를 잘라 crops/ 에 저장 (M2 차종 분류 학습용)
결과: <out>/images|labels/{train,val,test}/x_*.jpg|txt, <out>/report_cross.json
주의: 이 데이터는 보행자 라벨이 없다. 변환 후 pseudo_label.py로 보행자를 채워야 한다.
"""
import argparse
import json
import random
import re
import shutil
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from classes import CLASSES, CLASS_ID

IMG_EXT = {".jpg", ".jpeg", ".png"}


def zip_name(info):
    """압축 파일 안 이름. 한글 이름이 cp949로 들어 있으면(UTF-8 표시 없음) 고쳐서 돌려준다"""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp949")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


SEVEN_Z_MAGIC = b"7z\xbc\xaf\x27\x1c"


def find_7z():
    """7-Zip 실행 파일 찾기 (Colab: apt로 p7zip-full 설치, 윈도우: 7-Zip 기본 설치 경로)"""
    import shutil as sh
    for name in ("7z", "7za", "7zz"):
        if sh.which(name):
            return sh.which(name)
    for p in (r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if Path(p).exists():
            return p
    return None


class Source:
    """폴더, zip, 7z(확장자가 .zip이어도 내용이 7z인 AI Hub 파일)를 같은 방식으로 읽기.
    7z는 파일 하나씩 꺼내기 어려워서, 필요한 파일 목록을 먼저 정한 뒤 prefetch()로 한 번에 꺼낸다."""

    def __init__(self, path, tmp="_extract_tmp"):
        self.path = Path(path)
        self.zip = None
        self.kind = "dir"
        self.tmp = Path(tmp) / self.path.stem
        if self.path.is_file():
            with open(self.path, "rb") as f:
                magic = f.read(6)
            if magic == SEVEN_Z_MAGIC:
                self.kind = "7z"
                self.exe = find_7z()
                print(f"  {self.path.name}: 확장자는 zip이지만 7z 형식 → {'7-Zip 사용' if self.exe else 'py7zr 사용 (느림)'}")
            else:
                import zipfile
                self.kind = "zip"
                self.zip = zipfile.ZipFile(self.path)

    # ---------- 7z ----------
    def _7z_names(self):
        if self.exe:
            import subprocess
            out = subprocess.run([self.exe, "l", "-slt", "-ba", "-sccUTF-8", str(self.path)],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
            names, cur, is_dir = [], None, False
            for line in out.splitlines() + [""]:
                if line.startswith("Path = "):
                    cur = line[7:]
                elif line.startswith("Attributes = ") and "D" in line[13:14]:
                    is_dir = True
                elif line.startswith("Folder = +"):
                    is_dir = True
                elif not line.strip() and cur is not None:
                    if not is_dir:
                        names.append(cur.replace("\\", "/"))
                    cur, is_dir = None, False
            return names
        import py7zr
        with py7zr.SevenZipFile(self.path) as z:
            return [i.filename for i in z.list() if not i.is_directory]

    def prefetch(self, names):
        """7z에서 names만 임시 폴더로 꺼냄 (폴더·zip이면 아무것도 안 함)"""
        if self.kind != "7z" or not names:
            return
        self.tmp.mkdir(parents=True, exist_ok=True)
        print(f"  {self.path.name}에서 {len(names):,}개 파일 꺼내는 중... (압축 전체를 한 번 읽어서 시간이 걸림)")
        if self.exe:
            import subprocess
            lst = self.tmp.parent / f"{self.path.stem}_list.txt"
            lst.write_text("\n".join(names), encoding="utf-8")
            r = subprocess.run([self.exe, "x", str(self.path), f"-o{self.tmp}", "-y", "-scsUTF-8", f"@{lst}"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode not in (0, 1):
                raise RuntimeError(f"7z 압축 풀기 실패: {r.stderr[-500:]}")
        else:
            import py7zr
            with py7zr.SevenZipFile(self.path) as z:
                z.extract(path=self.tmp, targets=list(names))

    def files(self, exts):
        """(표시 이름, 열쇠) 목록. 열쇠는 read()에 넘긴다"""
        if self.kind == "zip":
            for info in self.zip.infolist():
                name = zip_name(info)
                if not info.is_dir() and Path(name).suffix.lower() in exts:
                    yield name, info
        elif self.kind == "7z":
            names = [n for n in self._7z_names() if Path(n).suffix.lower() in exts]
            if exts == {".xml"}:          # 라벨은 작으니 전부 미리 꺼냄
                self.prefetch(names)
            for n in names:
                yield n, n
        else:
            for p in self.path.rglob("*"):
                if p.suffix.lower() in exts:
                    yield str(p.relative_to(self.path)), p

    def read(self, key):
        if self.kind == "zip":
            return self.zip.read(key)
        if self.kind == "7z":
            return (self.tmp / key).read_bytes()
        return Path(key).read_bytes()

    def cleanup(self):
        if self.kind == "7z" and self.tmp.exists():
            shutil.rmtree(self.tmp, ignore_errors=True)


def parse_time(s):
    """'01:31.00' 또는 '01:31:00' -> 초"""
    nums = [float(x) for x in re.split(r"[:.]", s or "") if x != ""]
    return nums[0] * 60 + nums[1] if len(nums) >= 2 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True, help="TL_4 또는 VL_4 압축을 푼 폴더 (xml)")
    ap.add_argument("--images", required=True, help="TS_4 또는 VS_4 압축을 푼 폴더 (jpg)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--classes", default=str(Path(__file__).parent / "cvat_classes.json"))
    ap.add_argument("--min-gap", type=float, default=3.0)
    ap.add_argument("--max-images", type=int, default=0)
    ap.add_argument("--split", type=float, nargs=3, default=[0.7, 0.15, 0.15])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--save-crops", action="store_true")
    ap.add_argument("--zip", action="store_true", help="끝나고 데이터 폴더 전체를 dataset.zip으로 압축")
    ap.add_argument("--tmp", default=None, help="7z에서 꺼낸 파일을 잠시 둘 폴더 (기본: 출력 폴더 옆 _extract_tmp)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cfg = json.loads(Path(a.classes).read_text(encoding="utf-8"))
    cmap, ignore, subtype = cfg["map"], set(cfg.get("ignore", [])), cfg.get("subtype", {})

    print("원천 이미지 색인 중... (압축 파일이면 목록만 읽음)")
    tmp = Path(a.tmp) if a.tmp else Path(a.out).parent / "_extract_tmp"
    img_src = Source(a.images, tmp)
    img_index = {Path(name).name: key for name, key in img_src.files(IMG_EXT)}
    print(f"  이미지 {len(img_index):,}장")

    print("라벨 읽는 중...")
    lab_src = Source(a.labels, tmp)
    frames = []          # (카메라, 영상, 초, 이미지 이름, w, h, 박스들, 상위 폴더)
    unknown_labels, no_image, bad = Counter(), 0, 0
    for xname, xkey in lab_src.files({".xml"}):
        try:
            root = ET.fromstring(lab_src.read(xkey))
        except ET.ParseError:
            bad += 1
            continue
        group = "/".join(Path(xname).parts[:-1][-1:]) or "-"
        for im in root.iter("image"):
            name = im.get("name")
            if name not in img_index:
                no_image += 1
                continue
            boxes = []
            for b in im.iter("box"):
                lab = b.get("label")
                if lab in ignore:
                    continue
                if lab not in cmap:
                    unknown_labels[lab] += 1
                    continue
                boxes.append((lab, float(b.get("xtl")), float(b.get("ytl")), float(b.get("xbr")), float(b.get("ybr"))))
            cam = name.split("_")[0]
            vid = im.findtext("video_id") or name.rsplit("_", 1)[0]
            sec = parse_time(im.findtext("time"))
            frames.append((cam, vid, sec, name, int(im.get("width")), int(im.get("height")), boxes, group))
    print(f"  라벨 이미지 {len(frames):,}장 (원천 없음 {no_image:,}, 읽기 실패 xml {bad})")

    # 같은 영상에서 min-gap초 이상 떨어진 프레임만
    by_vid = defaultdict(list)
    for f in frames:
        by_vid[f[1]].append(f)
    kept = []
    for vid, fs in by_vid.items():
        last = None
        for f in sorted(fs, key=lambda x: (x[2] is None, x[2] or 0)):
            if f[2] is None or last is None or f[2] - last >= a.min_gap:
                kept.append(f)
                last = f[2] if f[2] is not None else last
    print(f"  {a.min_gap:g}초 간격 적용 후 {len(kept):,}장")

    # 카메라 단위 분할 + 이미지 수 상한
    rnd = random.Random(a.seed)
    if a.max_images and len(kept) > a.max_images:
        # 카메라·폴더(교차로/악천후/시간대)가 고르게 남도록 섞어서 자른다
        rnd.shuffle(kept)
        per = defaultdict(list)
        for f in kept:
            per[(f[0], f[7])].append(f)
        keys, out, i = list(per), [], 0
        while len(out) < a.max_images and any(per.values()):
            k = keys[i % len(keys)]
            if per[k]:
                out.append(per[k].pop())
            i += 1
        kept = out
    cams = sorted({f[0] for f in kept})
    rnd.shuffle(cams)
    n_img = Counter(f[0] for f in kept)
    total = sum(n_img.values())
    split_of, acc = {}, 0
    for c in cams:
        r = acc / max(1, total)
        split_of[c] = "train" if r < a.split[0] else ("val" if r < a.split[0] + a.split[1] else "test")
        acc += n_img[c]
    # 카메라가 적어 val/test가 비면 이미지 수가 적은 카메라부터 채운다
    for need in ("val", "test"):
        if need not in split_of.values() and len(cams) >= 3:
            c = min((c for c in cams if split_of[c] == "train"), key=lambda c: n_img[c])
            split_of[c] = need

    out = Path(a.out)
    if not a.dry_run:
        img_src.prefetch([img_index[f[3]] for f in kept])
    stats = {s: Counter() for s in ("train", "val", "test")}
    imgs_per, groups, crops = Counter(), Counter(), 0
    for n_done, (cam, vid, sec, name, w, h, boxes, group) in enumerate(kept, 1):
        if not a.dry_run and n_done % 500 == 0:
            print(f"  {n_done:,}/{len(kept):,}장 꺼내는 중")
        s = split_of[cam]
        lines = []
        for lab, x1, y1, x2, y2 in boxes:
            x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
            if x2 - x1 < 2 or y2 - y1 < 2:
                continue
            c = CLASS_ID[cmap[lab]]
            lines.append(f"{c} {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}")
            stats[s][CLASSES[c]] += 1
        imgs_per[s] += 1
        groups[group] += 1
        if a.dry_run:
            continue
        (out / "images" / s).mkdir(parents=True, exist_ok=True)
        (out / "labels" / s).mkdir(parents=True, exist_ok=True)
        data = img_src.read(img_index[name])
        (out / "images" / s / f"x_{name}").write_bytes(data)
        (out / "labels" / s / f"x_{Path(name).stem}.txt").write_text("\n".join(lines), encoding="utf-8")
        if a.save_crops:
            import cv2
            import numpy as np
            img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            for k, (lab, x1, y1, x2, y2) in enumerate(boxes):
                st = subtype.get(lab)
                if st is None or (x2 - x1) < 24 or (y2 - y1) < 24:
                    continue
                if img is None:
                    break
                ih, iw = img.shape[:2]
                crop = img[max(0, int(y1)):min(ih, int(y2)), max(0, int(x1)):min(iw, int(x2))]
                if crop.size == 0:
                    continue
                d = out.parent / "crops" / s / st
                d.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(d / f"{Path(name).stem}_{k}.jpg"), crop)
                crops += 1

    report = {
        "source": "교차로 신호 체계 데이터 (CVAT XML)", "labels": a.labels, "images": a.images,
        "cameras": {s: sorted(c for c in cams if split_of[c] == s) for s in ("train", "val", "test")},
        "split_images": dict(imgs_per), "boxes_per_class": {s: dict(c) for s, c in stats.items()},
        "folders": dict(groups), "unmapped_labels": dict(unknown_labels), "label_images_without_source": no_image,
        "min_gap_sec": a.min_gap, "crops": crops,
        "note": "보행자 라벨 없음 -> pseudo_label.py 실행 필요",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    img_src.cleanup()
    lab_src.cleanup()
    shutil.rmtree(tmp, ignore_errors=True)
    if not a.dry_run:
        out.mkdir(parents=True, exist_ok=True)
        (out / "report_cross.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if not (out / "data.yaml").exists():   # 사고 영상 변환 없이 이 데이터만 쓸 때
            (out / "data.yaml").write_text("path: /content/dataset\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n"
                                           + "".join(f"  {i}: {c}\n" for i, c in enumerate(CLASSES)), encoding="utf-8")
        if a.zip:
            print("압축 중...")
            shutil.make_archive(str(out.parent / "dataset"), "zip", root_dir=out)
            print(f"  {out.parent / 'dataset.zip'}")


if __name__ == "__main__":
    main()
