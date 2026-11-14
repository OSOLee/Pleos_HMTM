# MTM(OSOLee/MTM) feature/server의 src/analyze/bb_facts.py 복사본. import만 video_lib로 바꿈 (docs/origin.md). MTM 쪽을 고친 뒤 다시 복사한다.
"""블랙박스(시점 1) 같은 방향 사고의 사실 파일 만들기 (ego_motion + bb_partner → bb_facts.json)

  python src/analyze/bb_facts.py <결과 폴더>

촬영 차(ego)와 사고 상대 차 두 대를 당사자로 하는 facts.json(v0.3)을 만든다. 1차는 같은 방향 사고(추돌)만:
  - 상대가 앞(가운데)에 있고 촬영 차가 달리다 부딪힘  → 촬영 차 = 뒤차(following), 상대 = 앞차(leading)
  - 상대가 안 보이는데 촬영 차가 달리다/서 있다 부딪힘 → 뒤에서 받힌 것으로 봄: 촬영 차 = 앞차, 상대 = 뒤차 (화면에 없는 가상 차)
  - 상대가 옆(왼쪽·오른쪽)에서 옴 → 진로변경·교차로일 수 있어 1차에서는 판정하지 않음 (supported=False 이유 기록)
뒤에서 받힌 경우는 영상에 상대가 없어 근거가 약하다 (confidence 낮음으로 표시).
"""
import json
import os
import sys

from src.blackbox.video_lib import bb_kind

EGO_ID = "0"
BEHIND_ID = "9999"          # 화면에 안 보이는 뒤차 (가상)
CENTER_MIN_AREA = 0.01      # 가운데 상대 차로 인정하는 최소 크기 (화면 비율)


def load(p):
    with open(p, encoding="utf-8") as fp:
        return json.load(fp)


def state_at(segs, f):
    for g in segs:
        if g["from"] <= f <= g["to"]:
            return g["state"]
    return None


ANSWER_ROLES = ("rear_ender", "rear_ended", "partner_changed", "ego_changed", "partner_from_congested",
                # 추가 상황 (도표: 차45-6, 차47-1, 차32-1, 차31-1, 차43-3). 질문은 bb_questions.py
                "partner_overtook_solid", "started_after_stop", "oncoming_passing", "partner_crossed_center",
                "both_changed_lanes")
# 화면에 없는 가상 당사자의 종류 (사용자 답). 보행자·자전거 도표 파일이 판정 모듈에 생기면 그 장으로 판정
# (src/app/chapters.py). 종류 이름은 A의 facts 이름(pedestrian·bicycle)을 따름
PARTNER_KINDS = {"vehicle": "car", "pedestrian": "pedestrian", "bicycle": "bicycle"}
HINT_CLS = {"person": "pedestrian", "bicycle": "bicycle"}   # bb_kind의 종류 → facts 종류 이름


def run(out_dir, video=None, place=None, answers=None):
    ego = load(os.path.join(out_dir, "ego_motion.json"))["summary"]
    part = load(os.path.join(out_dir, "bb_partner.json"))
    tr = load(os.path.join(out_dir, "tracks.json"))
    fps = tr.get("fps") or 30.0
    imp = part["impact_frame"]
    out = {"supported": False, "reason": None, "case": None, "confidence": None}
    p = part["partner"]
    moving = None
    if imp is not None:
        moving = state_at(ego["segments"], max(imp - 8, 0)) == "moving"
    facts = None
    road = None   # 장면 사실 (중앙선 등). 마주 오는 사고(차31·차32)에서만 넣음
    role = (answers or {}).get("role")
    # 상대 종류: 사용자 답 > 사고 직전 탐지 신호(bb_kind, 보행자·자전거일 때만) > 자동차류
    hint = bb_kind.load(out_dir)
    kind_cls = PARTNER_KINDS.get((answers or {}).get("partner_kind"))
    kind_src = "user" if kind_cls else None
    if kind_cls is None and hint and hint.get("fired"):
        kind_cls, kind_src = HINT_CLS.get(hint["kind"]), "video"
    if kind_cls == "car":
        kind_cls = None
    out["kind_source"] = kind_src
    vcls = kind_cls or "car"   # 화면에 없는 가상 당사자 종류
    if role in ANSWER_ROLES:
        # 사용자가 답한 사고 모양을 그대로 사실로 씀 (영상에서 추측하지 않음)
        if imp is None:
            imp = ego["segments"][-1]["to"] if ego.get("segments") else 0
        pid = str(p["id"]) if p else "9998"
        pcls = kind_cls or ("two_wheeler" if p and p["cls"] == "motorcycle" else "car")
        a, b = EGO_ID, pid
        e0 = {"cls": "car", "entry_from": "north"}
        p0 = {"cls": pcls, "entry_from": "north"}
        if role == "rear_ender":            # 촬영 차가 앞차를 받음 (차41-1)
            parties = {a: {**e0, "movement": "straight", "lead_order": "following"},
                       b: {**p0, "movement": "straight", "lead_order": "leading", "stop_state": "driving"}}
        elif role == "rear_ended":          # 촬영 차가 뒤에서 받힘 (차41-1)
            b = BEHIND_ID
            parties = {a: {**e0, "movement": "straight", "lead_order": "leading", "stop_state": "driving"},
                       b: {"cls": vcls, "entry_from": "north", "movement": "straight", "lead_order": "following"}}
        elif role == "partner_changed":     # 상대가 차로를 바꿔 끼어듦 (차43-2)
            parties = {a: {**e0, "movement": "straight", "lead_order": "following"},
                       b: {**p0, "movement": "lane_change", "lead_order": "leading"}}
        elif role == "ego_changed":         # 촬영 차가 차로를 바꿈 (차43-2, 촬영 차가 선행 진로변경)
            parties = {a: {**e0, "movement": "lane_change", "lead_order": "leading"},
                       b: {**p0, "movement": "straight", "lead_order": "following"}}
        elif role == "partner_from_congested":   # 정체 차로의 상대가 급하게 들어옴 (차43-4)
            parties = {a: {**e0, "movement": "straight"},
                       b: {**p0, "movement": "lane_change", "from_congested_lane": True}}
        elif role == "partner_overtook_solid":   # 상대가 흰색 실선을 넘어 앞지르기, 촬영 차는 선행 직진 (차45-6)
            parties = {a: {**e0, "movement": "straight", "lead_order": "leading"},
                       b: {**p0, "movement": "straight", "lead_order": "following", "overtake_type": "white_solid"}}
        elif role == "started_after_stop":       # 촬영 차가 정차했다 출발, 상대가 정차 차량을 피해 추월 (차47-1)
            parties = {a: {**e0, "movement": "straight", "started_after_stop": True},
                       b: {**p0, "movement": "straight", "overtake_type": "around_stopped"}}
        elif role in ("oncoming_passing", "partner_crossed_center"):
            # 마주 오던 차와 부딪힘: 중앙선 없는 길의 교행(차32-1) / 상대가 중앙선을 넘어 역주행(차31-1)
            parties = {a: {**e0, "movement": "straight"},
                       b: {**p0, "movement": "straight", "entry_from": "south"}}
            if role == "partner_crossed_center":
                parties[b]["wrong_way"] = True
            road = {"location": "straight", "center_line": role == "partner_crossed_center"}
        else:                                    # both_changed_lanes: 양쪽이 같이 차로를 바꿈 (차43-3, 촬영 차 = 오른쪽에서 왼쪽)
            parties = {a: {**e0, "movement": "lane_change", "lane_change_dir": "left"},
                       b: {**p0, "movement": "lane_change", "lane_change_dir": "right"}}
        out.update(case="answer_" + role, confidence="user")
    elif imp is None:
        # 사고 순간을 못 찾음 = 촬영 차가 처음부터 끝까지 서 있었거나 멈춘 순간이 없음.
        # 차대차는 판정이 안 나오는 경우가 없어야 하므로, 서 있다가 뒤에서 받힌 것으로 보고 영상 끝을 충돌 시점으로 둠
        imp = ego["segments"][-1]["to"] if ego.get("segments") else 0
        out.update(case="ego_hit_from_behind", confidence="low")
        a, b = EGO_ID, BEHIND_ID
        parties = {a: {"cls": "car", "movement": "straight", "lead_order": "leading", "stop_state": "driving", "entry_from": "north"},
                   b: {"cls": vcls, "movement": "straight", "lead_order": "following", "entry_from": "north"}}
    elif p is not None and p["side"] == "center" and p["area"] >= CENTER_MIN_AREA and moving:
        out.update(case="ego_rear_ends_front", confidence="medium")
        a, b = EGO_ID, str(p["id"])
        parties = {a: {"cls": "car", "movement": "straight", "lead_order": "following", "entry_from": "north"},
                   b: {"cls": kind_cls or ("car" if p["cls"] != "motorcycle" else "two_wheeler"), "movement": "straight",
                       "lead_order": "leading", "stop_state": "driving", "entry_from": "north"}}
    elif p is None or p["side"] == "center" and p["area"] < CENTER_MIN_AREA:
        out.update(case="ego_hit_from_behind", confidence="low")
        a, b = EGO_ID, BEHIND_ID
        parties = {a: {"cls": "car", "movement": "straight", "lead_order": "leading", "stop_state": "driving", "entry_from": "north"},
                   b: {"cls": vcls, "movement": "straight", "lead_order": "following", "entry_from": "north"}}
    elif place == "직선도로":
        # 직선도로에서 옆(왼쪽·오른쪽)에서 들어온 상대 = 진로변경해 끼어든 앞차, 촬영 차 = 직진하던 뒤차 (차43-2)
        out.update(case="partner_cuts_in", confidence="low")
        a, b = EGO_ID, str(p["id"])
        parties = {a: {"cls": "car", "movement": "straight", "lead_order": "following", "entry_from": "north"},
                   b: {"cls": kind_cls or ("car" if p["cls"] != "motorcycle" else "two_wheeler"), "movement": "lane_change",
                       "lead_order": "leading", "entry_from": "north"}}
    else:
        out["reason"] = f"상대가 {p['side']}쪽에서 옴 (진로변경·교차로 가능성, 1차 범위 밖)"
    if out["case"]:
        out["supported"] = True
        facts = {"schema_version": "0.3", "video": video or tr.get("video"), "fps": fps,
                 "collision": {"frame": imp, "t": round(imp / fps, 3), "a": a, "b": b, "zone": "road"},
                 "parties": parties, "events": [], "unknowns": []}
        if road:
            facts["road"] = road
        with open(os.path.join(out_dir, "bb_facts.json"), "w", encoding="utf-8") as fp:
            json.dump(facts, fp, ensure_ascii=False, indent=1)
    out["facts"] = facts
    out["ego"] = EGO_ID
    return out


if __name__ == "__main__":
    r = run(sys.argv[1])
    print(r["case"], r["confidence"], r["reason"])
