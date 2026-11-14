"""AI Hub 정답 라벨로 run_app 질문에 답한다 ("답 반영" 평가에서 완벽하게 답하는 사용자를 흉내 냄)

  python tools/evaluate/gt_answer.py outputs/eval_tap/<영상> --road '{"road.center_line": true, ...}'
  → <결과 폴더>/answers.json에 답을 더하고, 무엇을 답했는지 출력한다. run_app을 다시 돌리고 질문이 남으면 반복

정답 라벨로 답하는 것: 부딪힌 쌍, 놓친 당사자 박스(user_tracks), 들어온 길, 진행 방향, 진입 시점, 진입 순서, 종류
라벨로 알 수 없는 도로 정보(신호등, 중앙선, 도로 폭)는 사람이 장면을 보고 --road로 준다.
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.getcwd())
from src.analyze.build_facts import DIRS, SAME_TIME_SEC, in_poly, zone_movement
from src.app.tap_track import USER_ID_MIN
from src.eval.match_parties import align_gt, match

CLS = {"vehicle": "car", "two_wheeler": "two_wheeler", "bicycle": "bicycle", "pedestrian": "pedestrian"}
MIN_HITS = 3   # 궤적이 라벨 당사자와 이만큼 이상 겹쳐야 그 당사자로 봄


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def gap(p, q):
    dx = max(0, max(p[0], q[0]) - min(p[0] + p[2], q[0] + q[2]))
    dy = max(0, max(p[1], q[1]) - min(p[1] + p[3], q[1] + q[3]))
    return math.hypot(dx, dy)


def zone(scene, pos):
    for z in scene["zones"]:
        if in_poly(pos, z["polygon"]):
            return z.get("direction") if z["type"] == "approach" else z["type"]
    return None


def path_facts(scene, recs, fps):
    """경로(프레임순 [(frame, pos)])로 들어온 길, 나간 길, 진행 방향, 교차로 진입 프레임.
    들어온 길은 교차로에 처음 들어가기 직전의 진입로만 인정한다. 예전엔 경로에서 처음 보이는 진입로를 썼는데,
    경로가 교차로 안에서 시작하면 나간 뒤의 길이 들어온 길로 잡혔다 (cc_190106 두 차 모두 south). 모르면 None"""
    zs = [(f, zone(scene, p)) for f, p in recs]
    inside = [k for k, (f, z) in enumerate(zs) if z == "intersection"]
    if not inside:
        return {"entry_from": next((z for f, z in zs if z in DIRS), None), "exit": None, "entry_frame": None,
                "movement": None}
    came = next((z for f, z in reversed(zs[:inside[0]]) if z in DIRS), None)
    entry = zs[inside[0]][0] if came else None
    left = next((z for f, z in zs[inside[-1]:] if z in DIRS), None)
    return {"entry_from": came, "exit": left, "entry_frame": entry,
            "movement": zone_movement(came, left) if came and left else None}


def party_path(lab_p, track):
    """정답 라벨 위치에, 라벨이 없는 프레임은 그 당사자로 매칭된 궤적 위치를 채운 경로. 정답 라벨은 충돌 근처
    몇 프레임에만 있을 때가 있어서 라벨만으로는 어디서 왔는지 모름"""
    pos = {r["frame"]: r["pos"] for r in track["frames"]} if track else {}
    pos.update({f: o["pos"] for f, o in lab_p})
    return sorted(pos.items())


TYPE_CODES = "data/aihub/type_codes.json"   # tools/data/type_codes.py (AI Hub 데이터 설명서의 사고 유형 표)


def type_codes():
    return {r["type"]: r for r in load(TYPE_CODES)} if os.path.exists(TYPE_CODES) else {}


# 유형 진행 앞의 신호 표시 → 신호 색 답 ("[적색신호] 직진", "[녹색 좌회전 신호] 좌회전"). 라벨에 당사자별 신호 색이
# 따로 없어서 사람이 영상을 보고 적으려던 것을 유형 표로 대신함 (cc_210313·211219·210819)
SIGNAL_TAGS = [("녹색좌회전", "green_arrow"), ("적색점멸", "flashing_red"), ("황색점멸", "flashing_yellow"),
               ("녹색", "green"), ("황색", "yellow"), ("적색", "red")]


def signal_of(text):
    if not text.startswith("["):
        return None
    tag = text[1:text.find("]")]
    return next((v for k, v in SIGNAL_TAGS if k in tag), None)


def type_answers(ans, app, label, of, party_track, entry_of=None):
    """경로로 답하지 못한 질문을 라벨의 사고 유형(accident_type)으로 답한다. 유형 표에는 당사자 A·B의 진행
    ("통로 직진", "주차구역에서 후진 출차", "진로변경(회전1차로→회전2차로)" 등)이 적혀 있어서, 교차로가 없는
    장소(주차장·회전교차로·교차로 아닌 길)의 진행 방향과 장소별 행동을 여기서 얻는다"""
    code = type_codes().get(label.get("traffic_accident_type", label.get("accident_type")))
    if not code:
        return
    # 도로 폭: 유형의 장소 특징이 "대로와 소로"면 "대로에서 …"인 당사자가 들어온 길의 축이 넓은 길, "동일폭"이면 같음.
    # 사람이 장면을 보고 넣은 답("폭 비슷함")이 유형과 다를 때가 있어서(cc_190506, 220114) 유형을 따름
    feat = (code.get("feature") or "").replace(" ", "")
    if "동일폭" in feat:
        ans["road.wider_road"] = "equal"
    elif "대로와소로" in feat:
        big = next((p for p in "AB" if code[p]["text"].replace(" ", "").startswith("대로")), None)
        came = ans.get(f"parties.{party_track.get(big)}.entry_from") or (entry_of or {}).get(big)
        if came:
            ans["road.wider_road"] = "north_south" if came in ("north", "south") else "east_west"
    # 이미 답한 진행 방향(경로로 낸 답·예전 답)도 유형 표 값으로 바꿈
    for tid, p in of.items():
        mv = (code.get(p) or {}).get("movement")
        if mv and f"parties.{tid}.movement" in ans:
            ans[f"parties.{tid}.movement"] = mv
    for q in app.get("questions", []):
        fld, opts = q["field"], q.get("options") or []
        # 진행 방향은 유형 표가 있으면 경로로 낸 답보다 유형 표를 따름. 라벨 박스가 충돌 근처 몇 프레임뿐이라 경로
        # 각도가 틀릴 때가 있음 (cc_211119 둘 다 직진인데 좌회전, cc_200303 좌회전인데 우회전, 주차장 후진 출차를 유턴)
        if fld in ans and not fld.endswith(".movement"):
            continue
        if fld.startswith("parties."):
            _, tid, key = fld.split(".", 2)
            info = code.get(of.get(tid)) or {}
            text = (info.get("text") or "").replace(" ", "")
            # 서 있던 이유: 유형 진행에 정차·주차가 없으면 달리던 중(잠깐 멈춘 것)으로 봄
            stop = "parked" if "주차중" in text or "주정차" in text else \
                "accident_stop" if "정차" in text else "driving"
            val = {"movement": info.get("movement"), "parking_action": info.get("parking"),
                   "roundabout_action": info.get("roundabout"), "stop_state": stop,
                   "signal_at_entry": signal_of(text)}.get(key)
            if val in opts:
                ans[fld] = val
        elif fld == "situation.special" and len(party_track) == 2:
            # 특수 상황: 유형 진행에 "문 열림"이 있으면 그 당사자 문 열림, "차도가 아닌 장소에서 … 진입"이면 도로
            # 아닌 곳에서 나옴, "정체도로 사이에서"면 막힌 차들 틈으로 직진(이륜차, 차61-1)
            # (cc_210303 열린 문, cc_210412·220118 차도가 아닌 장소, cc_200914 정체도로 사이)
            picks = []
            for p in "AB":
                text = code[p]["text"].replace(" ", "")
                key = "door" if "문열림" in text else "off_road" if text.startswith("차도가아닌장소에서") else \
                    "queue" if text.startswith("정체도로사이") else None
                if key and f"{key}:{party_track[p]}" in opts:
                    picks.append(f"{key}:{party_track[p]}")
            if picks:
                ans[fld] = picks
        elif fld == "road.roundabout_lanes":
            feat = (code.get("feature") or "").replace(" ", "")
            ans[fld] = "multi" if "2차로" in feat else "single" if "1차로" in feat else None
            if ans[fld] is None:
                del ans[fld]
        elif fld == "intersection_entry_order" and len(party_track) == 2:
            ea, eb = code["A"].get("entry"), code["B"].get("entry")
            if ea == "same" or eb == "same":
                ans[fld] = "same_time"
            elif ea == "first" or eb == "later":
                ans[fld] = party_track["A"]
            elif eb == "first" or ea == "later":
                ans[fld] = party_track["B"]
        elif fld == "pair.lead_order" and len(party_track) == 2:   # "선행 …"이 앞차
            lead = next((p for p in "AB" if "선행" in code[p]["text"]), None) or \
                next((p for p in "AB" if "후행" in code["BA"["AB".index(p)]]["text"]), None)
            if lead:
                ans[fld] = party_track[lead]
            elif right_of(code) and "side_by_side" in opts:   # 앞뒤 없이 "(오른쪽 차로)·(왼쪽 차로)"면 나란히 (유형 57 등)
                ans[fld] = "side_by_side"
        elif fld == "pair.right_side" and len(party_track) == 2 and right_of(code):
            ans[fld] = party_track[right_of(code)]
        elif fld == "road.lane_fits_two":   # 장소 특징 "통행 가능한 차로폭"·"2개 차량이 나란히 통행"이면 넓음 (유형 281, 54)
            feat = (code.get("feature") or "").replace(" ", "")
            if "통행가능한차로폭" in feat or "나란히" in feat:
                ans[fld] = True
            elif "통행불가능" in feat:
                ans[fld] = False


def right_of(code):
    """유형 진행의 "(오른쪽 차로)"·"(차로 우측)"으로 오른쪽에 있던 당사자 (A/B). 없으면 None"""
    for p in "AB":
        text = code[p]["text"].replace(" ", "")
        if "오른쪽차로" in text or "차로우측" in text:
            return p
    for p in "AB":
        text = code[p]["text"].replace(" ", "")
        if "왼쪽차로" in text or "차로좌측" in text:
            return "BA"["AB".index(p)]
    return None


def main(out, road, gt_dir="outputs/gt_cc"):
    name = os.path.basename(out.rstrip("/"))
    gt = load(os.path.join(gt_dir, f"{name}.json"))
    app = load(os.path.join(out, "app.json"))
    ans_path = os.path.join(out, "answers.json")
    ans = load(ans_path) if os.path.exists(ans_path) else {}
    ans.update(road)
    tracks = load(os.path.join(out, "tracks_final.json"))["tracks"]
    scene = load(os.path.join(out, "scene.json"))
    fps = load(os.path.join(out, "tracks.json"))["fps"]
    gt = align_gt(gt, out)   # 흔들림을 보정한 영상이면 정답 박스를 보정 좌표로
    m = match(gt, tracks)

    # 프레임 순서로 (한 프레임에 같은 당사자 박스가 둘인 라벨도 있어서 프레임으로만 정렬)
    lab = {p: sorted(((fr["frame"], o) for fr in gt["frames"] for o in fr["objects"] if o["party"] == p),
                     key=lambda x: x[0]) for p in "AB"}
    gt_cls = {p: CLS.get(lab[p][0][1]["cls"], "car") for p in "AB" if lab[p]}
    # 충돌 순간 대신: 두 당사자 라벨 박스가 가장 가까운 프레임
    n_frames = load(os.path.join(out, "tracks.json"))["frames_analyzed"]   # 화면 전환이 있으면 그 앞까지만
    both = {f for f, _ in lab["A"]} & {f for f, _ in lab["B"]} & set(range(n_frames))
    box = {p: dict(lab[p]) for p in "AB"}
    f0 = min(both, key=lambda f: gap(box["A"][f]["bbox"], box["B"][f]["bbox"])) if both else None

    # 1. 당사자 궤적 정하기: 라벨과 MIN_HITS 이상 겹친 궤적이 없으면 정답 박스로 직접 표시
    taps = ans.get("user_tracks", {})   # 직접 표시한 박스에는 어느 라벨 당사자인지("party")를 같이 적어 둠
    # 예전에 손으로 찍은 박스에는 "party"가 없음: 그 프레임(없으면 가장 가까운 프레임) 라벨 박스와 중심이 가까운 당사자로
    # (안 하면 궤적이 바뀐 뒤 다른 궤적을 그 당사자로 고르거나 박스를 또 만듦, cc_200822·200914)
    for v in taps.values():
        if "party" in v:
            continue
        cx, cy = v["bbox"][0] + v["bbox"][2] / 2, v["bbox"][1] + v["bbox"][3] / 2
        near = {}
        for p in "AB":
            if box[p]:
                b = box[p][min(box[p], key=lambda f: abs(f - v["frame"]))]["bbox"]
                near[p] = math.hypot(b[0] + b[2] / 2 - cx, b[1] + b[3] / 2 - cy)
        p = min(near, key=near.get) if near else None
        if p and near[p] < 0.05 and not any(w.get("party") == p for w in taps.values()):
            v["party"] = p
    party_track = {}
    for p in "AB":
        tapped = next((k for k, v in taps.items() if v.get("party") == p), None)
        hits = {t: c for t, c in m[p]["tracks"].items() if c >= MIN_HITS and t not in m["merged_tracks"]}
        if tapped:
            party_track[p] = tapped
        elif hits:
            party_track[p] = max(hits, key=hits.get)
        elif f0 is not None:
            tid = str(USER_ID_MIN + len(taps))
            taps[tid] = {"frame": f0, "bbox": box[p][f0]["bbox"], "cls": gt_cls[p], "party": p}
            party_track[p] = tid
            print(f"  {p}: 궤적 없음 → 정답 박스로 직접 표시 {tid} ({f0}프레임)")
    if taps:
        ans["user_tracks"] = taps
    if len(party_track) == 2:
        ans["collision.parties"] = [party_track["A"], party_track["B"]]
    of = {t: p for p, t in party_track.items()}
    facts = {p: path_facts(scene, party_path(lab[p], tracks.get(party_track.get(p))), fps) for p in "AB"}

    # 2. 남은 질문에 답하기
    for q in app.get("questions", []):
        fld = q["field"]
        if fld.startswith("parties."):
            _, tid, key = fld.split(".", 2)
            p = of.get(tid)
            if not p:
                continue
            if key == "entry_from" and facts[p]["entry_from"] in (q["options"] or []):
                ans[fld] = facts[p]["entry_from"]
            elif key == "movement" and facts[p]["movement"]:   # 유형 표에 있으면 type_answers가 덮어씀
                ans[fld] = facts[p]["movement"]
            elif key == "intersection_entry" and facts[p]["entry_frame"] is not None:
                ans[fld] = facts[p]["entry_frame"]
            # 이륜차 피해 정도(damage_severity)는 답하지 않음 (건너뛴 사용자와 같음 → 감산 없음). 라벨에 부상 정보가 없고
            # 라벨 비율도 사고마다 다름: cc_200822는 이륜차 -10이 들어간 값(30:70), cc_180629는 감산 없는 값(60:40)
            elif key == "cls":
                ans[fld] = q["model_guess"] if gt_cls[p] == "car" and q["model_guess"] in ("car", "truck", "bus") else gt_cls[p]
        elif fld == "intersection_entry_order":
            ea, eb = facts["A"]["entry_frame"], facts["B"]["entry_frame"]
            if ea is not None and eb is not None:
                a, b = party_track["A"], party_track["B"]
                ans[fld] = "same_time" if abs(ea - eb) / fps < SAME_TIME_SEC else (a if ea < eb else b)
    type_answers(ans, app, gt["label"], of, party_track, {p: facts[p]["entry_from"] for p in "AB"})
    with open(ans_path, "w", encoding="utf-8") as f:
        json.dump(ans, f, ensure_ascii=False, indent=1)
    print(f"{name[5:11]}: A={party_track.get('A')} B={party_track.get('B')} | 경로 A {facts['A']} | B {facts['B']}")
    print("  답:", {k: v for k, v in ans.items() if k != "user_tracks"})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--road", default="{}", help="도로 정보 답 (JSON)")
    ap.add_argument("--gt", default="outputs/gt_cc", help="정답 라벨 폴더 (평가 밖 영상으로 실험할 때 바꿈)")
    a = ap.parse_args()
    main(a.out, json.loads(a.road), a.gt)
