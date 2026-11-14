"""A의 facts.json(schema 0.2 / 0.3)을 엔진 입력 형식으로 변환

- 0.3의 값 객체 {"value", "source", "evidence_frame"}를 풀고 출처를 차량별 _sources에 기록한다.
- 0.2에 없는 값은 None(판단 불가)으로 둔다. 추측으로 채우지 않는다.
- 필드 정의는 docs/FACTS_SPEC.md 참고.
"""
import json

# A의 road_type -> 인정기준 도로 구분
ROAD_CLASS = {"no_center_line": "side_street"}
# 교차로 영역으로 볼 zone 이름
DEFAULT_INTERSECTION_ZONES = ["intersection", "junction"]
# A의 cls -> 엔진 cls
CLS_MAP = {"vehicle": "car", "car": "car", "two_wheeler": "two_wheeler", "motorcycle": "two_wheeler",
           "truck": "truck", "bus": "bus", "person": "person", "pedestrian": "person", "bicycle": "bicycle",
           "farm_machine": "farm_machine"}

# A 질문(src/app/chapters.py) 답 → 엔진 이름 (hmtm-0.1.1). 이름만 바꿔 뜻이 같은 것만 넣는다.
# carriageway(횡단보도 없는 차도), sidewalk(보도·길 가장자리)는 엔진 값 여럿에 걸쳐 있어 바꾸지 않는다 (ped_place = None)
CROSSING_PLACE_TO_PED_PLACE = {"on_crosswalk": "crosswalk", "near_crosswalk": "near_crosswalk"}
PED_SIGNAL_VALUES = {"green_flashing": "flashing_green"}

# 진입 방위 표기 정규화: A의 scene.json 진입로 이름(appr_n 등)이나 약자도 받는다
COMPASS = {"north": "north", "south": "south", "east": "east", "west": "west",
           "n": "north", "s": "south", "e": "east", "w": "west",
           "appr_n": "north", "appr_s": "south", "appr_e": "east", "appr_w": "west"}

# 차량별로 그대로 읽는 선택 필드 (0.3 제안)
OPTIONAL_PARTY_FIELDS = [
    "speed_kmh", "intersection_entry_speed_kmh", "wide_turn", "narrow_turn", "sudden_turn",
    "off_right_side", "turn_signal_used", "body_partly_out_waiting", "unsafe_distance",
    "forbidden_lane_change", "bus_lane_violation", "entered_congested_intersection",
    "turn_in_forbidden_place", "low_visibility_no_care", "avoidable_at_limit",
    "user_factors", "damage_severity", "damage_enlarged", "is_large_relative",
    # 신호 있는 교차로 (차1~차4)
    "signal_at_entry", "signal_at_collision", "unprotected_left_sign",
    "entered_just_before_red", "lane_marking_violation", "turn_almost_completed",
    "view_obstructed", "lane_change_after_turn", "stopped_before_entry", "stopped_in_intersection",
    # 한쪽 신호등 교차로 (차5~차6)
    "lane_change_in_intersection", "ped_signal_green_at_turn",
    # 한쪽 지시표지 교차로 (차7~차10)
    "stop_sign", "one_way_violation", "left_turn_prohibited_violation", "left_turn_method_violation",
    # 교차로 노면표시 위반 (차11)
    "lane_marking", "no_lane_across", "could_foresee_other_turn", "yield_violation", "started_from_parking",
    # 신호등 없는 교차로 (차12~차18)
    "on_wider_road", "slowed_before_entry", "right_turn_method_violation",
    # 교차로 부근 동시 회전 (차19~차21)
    "lead_order", "side_in_pair", "cut_in", "forced_cut_in", "crossed_shoulder_or_sidewalk", "right_space_wide",
    # 마주보는 방향 사고 (차31~차33)
    "wrong_way", "from_off_road", "crossed_center_line", "overtook_in_no_passing_zone", "rear_inattention",
    "crossed_double_solid_center", "going_uphill", "crossed_virtual_center", "stationary_at_collision",
    "evasive_action", "ran_signal", "u_turn_type",
    # 같은 방향 사고 (차41~차48)
    "stop_state", "position", "merging", "lane_change_dir", "from_congested_lane", "lane_change_first",
    "to_shoulder", "through_safety_zone", "in_safety_zone_at_collision", "overtake_type", "u_turn_timing",
    "started_after_stop", "at_bus_stop", "dropped_cargo", "is_school_bus",
    "slow_or_stop_without_reason", "brake_light_failure", "sudden_stop_without_reason", "no_fault_in_stopping",
    "in_passing_lane", "warning_sign_installed", "hazard_lights_on", "could_not_evacuate",
    "parking_prohibited_place", "improper_parking", "no_safety_measures", "unavoidable", "partially_in_lane",
    "stopped_without_necessity", "no_warning_sign", "lane_change_into_passing_lane", "congested_lane_change",
    "speeding", "consecutive_lane_change", "long_distance_lane_change", "signaled_lane_change_first",
    "overtaking_situation", "did_not_approach_center", "crossed_road_boundary",
    "overtake_right_after_lane_change", "obstructed_overtaking", "overtake_risky_place", "u_turn_outside_zone",
    # 기타 유형 (차51~차55)
    "in_parking_aisle", "leaving_parking_space", "entering_parking_space", "against_parking_arrow",
    "door_opening", "door_open_foreseeable", "door_toward_traffic", "sudden_door_open", "door_at_transit_stop",
    "crossing_on_crosswalk", "ped_signal_at_crossing", "roundabout_action", "roundabout_lane", "big_entry",
    "entry_lane_from", "late_entry_no_yield", "is_emergency", "driving_left_side", "overtaking", "sudden_lane_change",
    # 자동차 대 이륜차 특수유형 (차61)
    "between_congested_queue", "narrow_passing_space", "on_sidewalk", "to_off_road", "stopped_before_sidewalk",
    "passing_on_right",
    # 차대보행자 도표 (보1~보36)
    "impact_after_intersection", "passed_crosswalk", "right_turn_signal", "riding_on_crosswalk", "on_motorway",
    "ped_place", "ped_activity", "ped_signal_at_start", "ped_signal_at_impact", "dist_from_crosswalk_m",
    "crossing_road_width", "expressway_walk_reason", "roadway_walk_position", "sidewalk_closed",
    # 차대보행자 수정요소 (modifiers_pedestrian.json)
    "ped_posture", "ped_factors", "vulnerable_type", "walk_manner", "diagonal_crossing", "opposite_side_start",
    "in_own_protection_zone", "inside_stop_line", "on_shoulder", "passed_stopped_vehicles", "reverse_warning",
    "behind_before_reverse",
    # A 질문 답 (src/app/chapters.py). 아래 변환에서 ped_place로 옮김
    "crossing_place",
    # 차대자전거 도표 (거1~거43)
    "approached_right_edge", "bike_lane_type", "crossing_road", "on_bike_crossing",
    # 차대자전거 수정요소 (modifiers_bicycle.json)
    "bike_lane_nearby", "in_bike_lane", "left_side_riding", "obstacle_ahead", "path_blocked", "foresee_lane_change",
]

# facts.road에서 엔진 scene으로 그대로 넘기는 장소 필드
SCENE_FIELDS = [
    "location", "junction_type", "road_width", "lane_fits_two", "center_line", "center_line_rule_not_applied",
    "road_type", "residential_area", "low_visibility", "night", "roundabout_lanes",
    # 차대보행자 (보1~보36)
    "crosswalk_signal", "view_obstructed", "bad_weather", "bright_place", "arterial_road", "ped_busy_area",
    "protection_zone", "sidewalk_separated", "crossing_prohibition", "vehicle_access_zone", "easy_walk_area",
    "ped_warning_sign",
    # 차대자전거 (거1~거43)
    "lanes_two_plus", "dashed_bike_lane_border",
]


def load_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def unwrap(x):
    """0.3 값 객체면 (값, 출처, 근거 프레임), 아니면 (x, None, None)"""
    if isinstance(x, dict) and "value" in x:
        return x.get("value"), x.get("source"), x.get("evidence_frame")
    return x, None, None


def _zone_entry(raw, tid, zones):
    for e in raw.get("events", []):
        if e.get("type") == "enter_zone" and str(e.get("track")) == tid and e.get("zone") in zones:
            return e.get("t"), f"{tid}번 교차로 진입 = '{e.get('zone')}' 영역 진입 ({e.get('t')}초)"
    return None, None


def _inherit(target, field, a, b, src_field):
    """계산값의 출처: 재료 중 하나라도 사용자 입력이면 계산값도 사용자 입력으로 본다"""
    srcs = {a["_sources"].get(src_field), b["_sources"].get(src_field)}
    if "user" in srcs:
        target["_sources"][field] = "user"


def _from_chapter_answers(v, sources):
    """A 질문 답(crossing_place, ped_signal_at_crossing)의 이름·값을 엔진 이름으로. 엔진 이름 값이 이미 있으면 그대로"""
    sig = v.get("ped_signal_at_crossing")
    if sig in PED_SIGNAL_VALUES:
        v["ped_signal_at_crossing"] = PED_SIGNAL_VALUES[sig]
    place = CROSSING_PLACE_TO_PED_PLACE.get(v.get("crossing_place"))
    if place and v.get("ped_place") is None and v.get("cls") == "person":   # 자전거 도표는 ped_place를 읽지 않음
        v["ped_place"] = place
        if sources.get("crossing_place"):
            sources["ped_place"] = sources["crossing_place"]


def to_engine_facts(raw, assumptions=None):
    """반환: (엔진 형식 facts, 적용한 가정 목록)"""
    assumptions = assumptions or {}
    ver = str(raw.get("schema_version", ""))
    if ver.startswith("1.") or ver.startswith("2."):
        return raw, []
    if not (ver.startswith("0.2") or ver.startswith("0.3")):
        raise ValueError(f"지원하지 않는 facts schema_version: {ver}")

    assumed = []
    party_over = {k: v for k, v in assumptions.get("parties", {}).items() if not k.startswith("_")}
    inter = assumptions.get("intersection", {})
    zones = inter.get("zones", DEFAULT_INTERSECTION_ZONES)
    road = {k: unwrap(v)[0] for k, v in (raw.get("road") or {}).items()}

    vehicles, by_id = [], {}
    for tid, p in raw.get("parties", {}).items():
        tid = str(tid)
        sources, evidence = {}, {}

        def take(key, default=None):
            val, src, ev = unwrap(p.get(key, default))
            if src:
                sources[key] = src
            if ev is not None:
                evidence[key] = ev
            return val

        mv = take("movement")
        cls = take("cls")
        v = {
            "track_id": tid,
            "cls": CLS_MAP.get(cls, cls),
            "origin_zone": take("origin_zone"),
            "movement": None if mv in (None, "unknown") else mv,
            "heading": take("heading_start") or take("heading_before_collision"),
            "intersection_entry_t": None,
            "entry_speed": take("intersection_entry_speed") or take("approach_speed"),
            "entry_lead_sec": None,
            "entry_speed_ratio": None,
            "entry_speed_to_limit": None,
            "speed_over_limit_kmh": None,
        }
        for key in OPTIONAL_PARTY_FIELDS:
            v[key] = take(key)
        # 진입 방위: 그 차가 들어온 쪽. 두 차 모두 있으면 엔진이 화면 방향 벡터 대신 방위로 좌우를 판단
        ef = take("entry_from")
        v["entry_from"] = COMPASS.get(str(ef).lower()) if ef is not None else None
        # 교차로 진입 시각: 0.3 필드 > 교차로 영역 이벤트 > 측면 진입로에서 도로로 들어온 시점
        ie = take("intersection_entry")
        if isinstance(ie, dict) and ie.get("t") is not None:
            v["intersection_entry_t"] = ie["t"]
        else:
            t, note = _zone_entry(raw, tid, zones)
            if t is None and inter.get("side_entry_is_road") \
                    and str(p.get("origin_zone") or "").startswith("side_entry") and p.get("enter_road"):
                t = p["enter_road"].get("t")
                note = f"{tid}번 교차로 진입 = 측면 진입로에서 도로로 들어온 시점 ({t}초)"
            v["intersection_entry_t"] = t
            if note:
                assumed.append(note)
        # 사용자 입력 / 가정 파일 값 (출처: user)
        for k, val in (party_over.get(tid) or {}).items():
            if k == "cls":
                val = CLS_MAP.get(val, val)
            elif k == "entry_from" and val is not None:
                val = COMPASS.get(str(val).lower())
            v[k] = val
            sources[k] = "user"
            assumed.append(f"{tid}번 {k} = {val}")
        if v.get("slowed_before_entry") is None and v.get("stopped_before_entry") is True:
            v["slowed_before_entry"] = True   # 일시정지했으면 서행한 것으로 봄 (차12 "서행(일시정지 포함)")
        _from_chapter_answers(v, sources)
        v["_sources"] = sources
        v["_evidence"] = evidence
        vehicles.append(v)
        by_id[tid] = v

    # 제한속도 기준 계산값 (실속도 km/h가 있을 때만)
    limit = road.get("speed_limit_kmh")
    for v in vehicles:
        if limit:
            if v.get("intersection_entry_speed_kmh") is not None:
                v["entry_speed_to_limit"] = round(v["intersection_entry_speed_kmh"] / limit, 3)
            if v.get("speed_kmh") is not None:
                v["speed_over_limit_kmh"] = round(v["speed_kmh"] - limit, 1)

    c = raw.get("collision") or {}
    between = [str(x) for x in (c.get("a"), c.get("b")) if x is not None]

    # 두 당사자 사이 상대값
    if len(between) == 2 and all(t in by_id for t in between):
        a, b = by_id[between[0]], by_id[between[1]]
        for x, y in ((a, b), (b, a)):
            if x["entry_lead_sec"] is None and x["intersection_entry_t"] is not None \
                    and y["intersection_entry_t"] is not None:
                x["entry_lead_sec"] = round(y["intersection_entry_t"] - x["intersection_entry_t"], 3)
                _inherit(x, "entry_lead_sec", x, y, "intersection_entry_t")
            # 속도 비율: 실속도(km/h)가 있으면 우선, 없으면 화면 비율 속도 (비율이라 단위가 상쇄됨)
            sk = "intersection_entry_speed_kmh" if x.get("intersection_entry_speed_kmh") \
                and y.get("intersection_entry_speed_kmh") else "entry_speed"
            if x["entry_speed_ratio"] is None and x.get(sk) and y.get(sk):
                x["entry_speed_ratio"] = round(x[sk] / y[sk], 3)
                _inherit(x, "entry_speed_ratio", x, y, sk)

    # 장면: facts.road(0.3) > road_type 변환 > 가정 파일
    scene = {}
    rc = road.get("road_class") or ROAD_CLASS.get(raw.get("road_type"))
    if rc:
        scene["road_class"] = rc
        if not road.get("road_class"):
            assumed.append(f"scene.road_class = {rc} (road_type '{raw.get('road_type')}'에서 변환)")
    for key in SCENE_FIELDS:
        if road.get(key) is not None:
            scene[key] = road[key]
    for k, val in assumptions.get("scene", {}).items():
        if k.startswith("_") or k in scene:
            continue
        scene[k] = val
        assumed.append(f"scene.{k} = {val}")

    if road.get("signal_present") is False:
        signal = {"state": "none"}
    elif road.get("signal_present") is True:
        signal = {"state": road.get("signal_mode") or "normal"}  # normal / flashing
    elif "signal" in assumptions:
        signal = assumptions["signal"]
        assumed.append(f"signal.state = {signal.get('state')}")
    else:
        signal = {"state": None}

    facts = {
        "schema_version": "2.0",
        "source_schema": ver,
        "video": raw.get("video"),
        "fps": raw.get("fps"),
        "scene": scene,
        "signal": signal,
        "vehicles": vehicles,
        "collision": {"frame": c.get("frame"), "t": c.get("t"), "between": between,
                      "zone": c.get("zone"), "pos": c.get("pos")},
        "events": raw.get("events", []),
        "unknowns": raw.get("unknowns", []),
    }
    return facts, assumed
