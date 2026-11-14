"""CCTV 영상을 사고 단위로 묶어 학습·예비·평가로 나눈다 (탐지 모델 재학습용 목록)

  python tools/data/make_split.py outputs/dedup/groups.json   # → splits/cctv_split.json, splits/cctv_split.md

groups.json: 눈으로 확인한 중복 묶음 {"groups": [[영상, 영상, ...], ...]} (find_duplicates.py 결과를 확인해 만든 것)
묶음에 없는 영상은 혼자 한 사고로 본다. 같은 사고의 복사본은 항상 같은 쪽에 들어간다.

규칙
1. 신호 있는 장소(장소 이름에 "신호등있음")의 사고는 전부 평가
2. 사고가 SMALL_CAT개 이하인 카테고리(대상 × 장소)는 전부 평가
3. 지금 평가에 쓰는 사고(outputs/gt_cc)와 영상을 받지 않아 중복을 못 본 사고(UNCHECKED)는 평가
4. 나머지 카테고리는 TRAIN_PER_CAT개를 학습, 이륜차·자전거 카테고리는 RESERVE_PER_CAT개를 예비로 두고
   나머지는 평가. 학습·예비는 프레임이 많은 영상(라벨 프레임이 많음)이 든 사고부터 고른다
예비는 처음에는 학습에도 평가에도 쓰지 않는다. 학습 뒤 CCTV 이륜차 탐지가 부족하면 학습으로 옮긴다.

평가 기준 라벨
같은 사고의 복사본끼리 과실비율 라벨이 다른 경우가 있다. 그래서 사고마다 기준 영상 하나를 정한다.
- 기준 영상: 지금 평가에 쓰는 영상이 있으면 그 영상. 없으면 다수 라벨을 가진 복사본 중 이름순 첫 번째
- 정답(answer): 기준 영상의 라벨. A·B는 기준 영상의 프레임 라벨(isObjectA/B) 기준
- 복사본의 A·B가 기준 영상과 반대로 붙은 경우가 있다(cc_3_170203 묶음). 프레임 라벨의 A·B 종류가 다르면
  종류로, 같으면 박스 평균 위치로 맞춘다. 차이가 AB_MARGIN보다 작으면 "unknown"
- 허용 비율(allowed): 복사본 라벨을 기준 영상의 A·B로 맞춘 비율 전부. 라벨이 다른 사고는 결과표에서
  "기준 라벨 일치"(주 지표)와 "허용 비율 중 하나와 일치"를 나눠서 센다
- 비율이 하나만 적힌 라벨(A만 있음)은 B = 100 - A
"""
import collections
import glob
import json
import os
import sys
import zipfile

import cv2

SMALL_CAT = 3
TRAIN_PER_CAT = 2
RESERVE_PER_CAT = 1
RESERVE_OBJECTS = ("차대이륜차", "차대자전거")
UNCHECKED = {("TL", "차대차", "직선도로")}   # 원천 영상 46GB라 받지 않음. 중복 확인 없이 평가로 둠
AB_MARGIN = 0.03   # A·B를 위치로 맞출 때, 같음/반대 거리 차이가 이보다 작으면 판단하지 않음
ORDER_GAP = 15     # A·B가 처음 나타난 프레임이 이만큼 이상 차이 나면 나타난 순서로 맞춤 (15fps 기준 1초)
LABEL_DIRS = ("data/aihub/frame_labels_raw", "data/aihub/cc_labels")   # 프레임 라벨 (zip 또는 풀어 둔 json)


def label_index():
    """영상 이름 -> 프레임 라벨 json을 읽는 함수 목록"""
    index = {}
    for root in LABEL_DIRS:
        for z in glob.glob(os.path.join(root, "**", "*.zip"), recursive=True):
            zf = zipfile.ZipFile(z)
            for n in zf.namelist():
                if n.endswith(".json") and "/" in n:
                    index.setdefault(n.split("/")[-2], []).append(lambda zf=zf, n=n: json.loads(zf.read(n)))
        for p in glob.glob(os.path.join(root, "**", "cc_*", "*.json"), recursive=True):
            index.setdefault(os.path.basename(os.path.dirname(p)), []).append(
                lambda p=p: json.load(open(p, encoding="utf-8")))
    return index


def parties(readers):
    """프레임 라벨에서 당사자 A·B의 박스 평균 위치(바닥 중앙, 0~1), 가장 많은 종류, 처음 나타난 프레임"""
    pos, cls, first = collections.defaultdict(list), collections.defaultdict(collections.Counter), {}
    for read in readers:
        j = read()
        f = int(j["sequence_frame_number"])
        for o in j["objects"]:
            p = "A" if o.get("isObjectA") else "B" if o.get("isObjectB") else None
            if p:
                x, y, w, h = o["bbox"]
                pos[p].append(((x + w / 2) / j["width"], (y + h) / j["height"]))
                cls[p][o["category"]] += 1
                first[p] = min(first.get(p, f), f)
    return {p: {"pos": (sum(a for a, _ in v) / len(v), sum(b for _, b in v) / len(v)),
                "cls": cls[p].most_common(1)[0][0], "first": first[p]} for p, v in pos.items()}


def ab_relation(p, ref):
    """복사본 p의 A·B가 기준 ref와 같은 대상인지: same / swapped / unknown
    1. 종류(차량·보행자 등)가 A·B끼리 다르면 종류로
    2. 한쪽이 ORDER_GAP 프레임 이상 먼저 나타나면 나타난 순서로 (화면을 휘거나 자른 복사본에도 그대로)
    3. 둘 다 아니면 박스 평균 위치로"""
    if len(p) < 2 or len(ref) < 2:
        return "unknown"
    if ref["A"]["cls"] != ref["B"]["cls"] and p["A"]["cls"] != p["B"]["cls"]:
        return "same" if p["A"]["cls"] == ref["A"]["cls"] else "swapped"
    gap_p, gap_r = p["A"]["first"] - p["B"]["first"], ref["A"]["first"] - ref["B"]["first"]
    if abs(gap_p) >= ORDER_GAP and abs(gap_r) >= ORDER_GAP:
        return "same" if (gap_p > 0) == (gap_r > 0) else "swapped"
    d = lambda a, b: ((p[a]["pos"][0] - ref[b]["pos"][0]) ** 2 + (p[a]["pos"][1] - ref[b]["pos"][1]) ** 2) ** .5
    same, swap = d("A", "A") + d("B", "B"), d("A", "B") + d("B", "A")
    if abs(same - swap) < AB_MARGIN:
        return "unknown"
    return "same" if same < swap else "swapped"


def main(groups_path, video_dir="data/videos/cc", out_dir="splits"):
    rows = {r["name"]: r for r in json.load(open("outputs/aihub_survey.json", encoding="utf-8"))
            if r["filming_way"] == "cc"}
    with open(groups_path, encoding="utf-8") as f:
        groups = [list(g) for g in json.load(f)["groups"]]
    grouped = {v for g in groups for v in g}
    groups += [[v] for v in sorted(rows) if v not in grouped]
    eval_now = {os.path.basename(p)[:-5] for p in glob.glob("outputs/gt_cc/*.json")}

    def frames(v):
        cap = cv2.VideoCapture(os.path.join(video_dir, v + ".mp4"))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        return n

    index = label_index()

    def rate(v):
        a, b = rows[v]["rate_a"], rows[v]["rate_b"]
        return [a, b if b is not None else 100 - a]

    def labels_of(g):
        """기준 영상과, 복사본 라벨을 기준 영상의 A·B로 맞춘 목록"""
        pts = {v: parties(index.get(v, [])) for v in g}

        def against(ref):
            labs = []
            for v in g:
                r = rate(v)
                # 라벨(비율·유형)이 기준과 똑같으면 맞출 필요가 없음
                same_label = r == rate(ref) and rows[v]["type"] == rows[ref]["type"]
                rel = "same" if v == ref or same_label else ab_relation(pts[v], pts[ref])
                labs.append({"video": v, "rate": r, "type": rows[v]["type"], "ab": rel,
                             "rate_ref": r[::-1] if rel == "swapped" else r})
            return labs

        now = [v for v in g if v in eval_now]
        if now:
            return now[0], against(now[0])
        # 다수 라벨을 가진 복사본 중 이름순 첫 번째 (A·B를 못 맞춘 복사본은 세지 않음)
        labs = against(g[0])
        top = collections.Counter(tuple(l["rate_ref"]) for l in labs if l["ab"] != "unknown").most_common(1)[0][0]
        ref = next(l["video"] for l in labs if l["ab"] != "unknown" and tuple(l["rate_ref"]) == top)
        return ref, against(ref)

    accidents = []
    for g in groups:
        g = sorted(g)
        cats = {(rows[v]["object"], rows[v]["place"]) for v in g}
        obj, place = sorted(cats)[0]   # 복사본끼리 카테고리가 다르면 첫 번째로 (md에 표시)
        unchecked = any((rows[v]["split"], rows[v]["object"], rows[v]["place"]) in UNCHECKED for v in g)
        ref, labs = labels_of(g)
        allowed = sorted({tuple(l["rate_ref"]) for l in labs if l["ab"] != "unknown"})
        accidents.append({
            "id": g[0], "videos": g, "object": obj, "place": place, "category_conflict": len(cats) > 1,
            "signal": any("신호등있음" in rows[v]["place"] for v in g),
            "unchecked": unchecked,
            "eval_now": any(v in eval_now for v in g),
            "frames": 0 if unchecked else max(frames(v) for v in g),
            "reference": ref, "answer": rate(ref), "type": rows[ref]["type"],
            "allowed": [list(r) for r in allowed], "labels": labs,
            # 맞춘 비율이 여러 개이거나, A·B를 못 맞춘 복사본의 라벨이 기준과 다르면 라벨이 흔들리는 사고
            "label_conflict": len(allowed) > 1 or any(l["ab"] == "unknown" and l["rate"] != rate(ref)
                                                     for l in labs),
        })

    by_cat = {}
    for a in accidents:
        by_cat.setdefault((a["object"], a["place"]), []).append(a)
    for (obj, place), accs in sorted(by_cat.items()):
        fixed = [a for a in accs if a["signal"] or a["eval_now"] or a["unchecked"]]
        free = sorted((a for a in accs if a not in fixed), key=lambda a: (-a["frames"], a["id"]))
        for a in fixed:
            a["set"], a["why"] = "eval", ("신호 있는 장소" if a["signal"] else
                                          "지금 평가 영상" if a["eval_now"] else "영상 미확인")
        if len(accs) <= SMALL_CAT:
            for a in free:
                a["set"], a["why"] = "eval", f"사고 {SMALL_CAT}개 이하 카테고리"
            continue
        n_res = RESERVE_PER_CAT if obj in RESERVE_OBJECTS else 0
        for i, a in enumerate(free):
            if i < TRAIN_PER_CAT:
                a["set"], a["why"] = "train", f"카테고리당 {TRAIN_PER_CAT}개"
            elif i < TRAIN_PER_CAT + n_res:
                a["set"], a["why"] = "reserve", "이륜차·자전거 예비"
            else:
                a["set"], a["why"] = "eval", "나머지"

    os.makedirs(out_dir, exist_ok=True)
    out = {"rule": __doc__.split("규칙")[1].strip(), "accidents": accidents,
           "counts": {s: {"accidents": sum(a["set"] == s for a in accidents),
                          "videos": sum(len(a["videos"]) for a in accidents if a["set"] == s)}
                      for s in ("train", "reserve", "eval")}}
    with open(os.path.join(out_dir, "cctv_split.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    name = {"train": "학습", "reserve": "예비", "eval": "평가"}
    lines = ["# CCTV 학습·평가 나누기", "",
             "`tools/data/make_split.py`가 만든 파일이다. 규칙은 그 파일 맨 위 설명에 있다.", "",
             "**같은 사고의 복사본은 모두 같은 쪽이다. 학습에는 \"학습\" 사고의 영상만 쓰고, 그 프레임 라벨만 쓴다.**", "",
             "| 구분 | 사고 수 | 영상 수 |", "|---|---|---|"]
    for s in ("train", "reserve", "eval"):
        c = out["counts"][s]
        lines.append(f"| {name[s]} | {c['accidents']} | {c['videos']} |")
    lines += ["", "평가 정답은 사고마다 **기준 영상**(굵게 표시)의 라벨이다. 같은 사고의 복사본끼리 라벨이 다른 경우는 "
              "맨 아래 \"라벨이 다른 사고\"에 정리했다."]
    for s in ("train", "reserve", "eval"):
        lines += ["", f"## {name[s]}", "", "| 대상 | 장소 | 이유 | 정답 A : B | 영상 (같은 사고) |", "|---|---|---|---|---|"]
        for a in sorted((a for a in accidents if a["set"] == s), key=lambda a: (a["object"], a["place"], a["id"])):
            mark = " (복사본끼리 카테고리 다름)" if a["category_conflict"] else ""
            vids = "<br>".join(f"**{v}**" if v == a["reference"] and len(a["videos"]) > 1 else v for v in a["videos"])
            ans = f"{a['answer'][0]} : {a['answer'][1]}" + (" ※" if a["label_conflict"] else "")
            lines.append(f"| {a['object']} | {a['place']}{mark} | {a['why']} | {ans} | {vids} |")

    ab = {"same": "같음", "swapped": "반대", "unknown": "못 맞춤"}
    lines += ["", "## 라벨이 다른 사고", "",
              "같은 사고의 복사본끼리 과실비율이나 A·B 표기가 다른 사고다. 위 표에서 ※로 표시했다.", "",
              "- 정답은 기준 영상의 라벨이다. A·B도 기준 영상의 프레임 라벨(isObjectA/B)을 따른다.",
              "- \"A·B\"는 그 복사본의 A·B가 기준 영상과 같은 대상인지다. 프레임 라벨의 종류(차량·보행자 등)가 다르면 "
              "종류로, 같으면 박스 평균 위치로 맞췄다. \"반대\"면 비율을 뒤집어 기준 영상의 A·B로 맞춘다.",
              "- 허용 비율은 맞춘 비율 전부다. 결과표에서는 \"기준 라벨 일치\"를 주 지표로 쓰고, "
              "\"허용 비율 중 하나와 일치\"는 따로 센다.",
              "- A·B 표기만 반대이고 맞추면 비율이 같은 사고(※ 없음)는 아래 표에 넣지 않았다. "
              "프레임 라벨을 쓸 때 A·B가 뒤바뀌어 있다는 점만 주의한다.", "",
              "| 구분 | 사고 (기준 영상) | 복사본 라벨 (원래 A : B, 유형, A·B) | 기준 A·B로 맞춘 허용 비율 |", "|---|---|---|---|"]
    for a in sorted((a for a in accidents if a["label_conflict"]), key=lambda a: (a["set"], a["id"])):
        labs = "<br>".join(f"{l['video'][5:11]}: {l['rate'][0]} : {l['rate'][1]}, 유형 {l['type']}, {ab[l['ab']]}"
                           for l in a["labels"])
        allowed = ", ".join(f"{r[0]} : {r[1]}" for r in a["allowed"])
        lines.append(f"| {name[a['set']]} | {a['reference']} | {labs} | {allowed} |")
    swapped = [a for a in accidents if not a["label_conflict"] and any(l["ab"] == "swapped" for l in a["labels"])]
    if swapped:
        lines += ["", "A·B 표기만 반대인 사고: " + ", ".join(
            f"{a['reference'][5:11]} 묶음({', '.join(l['video'][5:11] for l in a['labels'] if l['ab'] == 'swapped')}이 반대)"
            for a in swapped)]
    with open(os.path.join(out_dir, "cctv_split.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    for s in ("train", "reserve", "eval"):
        print(f"{name[s]}: 사고 {out['counts'][s]['accidents']}개, 영상 {out['counts'][s]['videos']}개")


if __name__ == "__main__":
    main(sys.argv[1])
