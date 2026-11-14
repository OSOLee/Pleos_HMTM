"""차량 사건 → MTM 질문·판정 어댑터 (docs/api-spec.md 8.4)

영상 전용 입력을 빈 값으로 채운 facts 껍데기를 만들어 MTM 함수를 그대로 부른다 (MTM 코드는 고치지 않음).

  규칙(rules.run_rules) → facts 껍데기 → situation.questions → answers.remaining / fill_guesses
  → answers.to_assumptions → judge_bridge.judge → 차량 사건 객체(2.5)

당사자 id는 ego(내 차) / other(상대). 내 차는 남쪽에서 들어왔다고 고정하고(entry_from = south),
자기 차 기준 보기(left/right/opposite/same, mine/theirs)는 MTM에 넘기기 전에 동서남북 값으로 바꾼다 (2.6 ★).
"""
import copy
import json
import os
import re
import tempfile

from src.analyze.build_facts import SIGNAL_NAMES, SIGNALS
from src.app import answers as ans
from src.app import judge_bridge, situation
from src.app.pipeline import JUDGE_DIR
from src.vehicle import clock, rules
from src.vehicle.samples import Timeline, VehicleError

EGO, OTHER = "ego", "other"
FPS = 10                          # 껍데기의 fps (영상 전용 값. to_assumptions가 읽기만 함)
FIELDS_MISSING_MS = 10_000        # data_quality.fields_missing: t_event 앞 10초 (2.5)
SAMPLE_KEYS = ("speedKmh", "gear", "turnSignal", "brake")

PLACES = ["intersection", "roundabout", "parking_lot", "straight"]
PLACE_CHOICES = ["교차로", "회전교차로", "주차장", "교차로 아닌 길"]
JUNCTIONS = ["cross", "t"]
JUNCTION_CHOICES = ["사거리", "삼거리"]
MOVEMENTS = ["straight", "left_turn", "right_turn", "u_turn", "lane_change", "reverse", "unknown"]
MOVEMENT_CHOICES = ["직진", "좌회전", "우회전", "유턴", "진로 변경 (차로 바꾸기)", "후진", "모름"]
OTHER_CLASSES = ["car", "truck", "bus", "two_wheeler", "bicycle", "farm_machine", "pedestrian"]
OTHER_CLASS_CHOICES = ["승용차", "화물차", "버스", "이륜차", "자전거", "농기계", "보행자"]
ENTRIES = ["left", "right", "opposite", "same"]
ENTRY_CHOICES = ["내 차 기준 왼쪽 길", "내 차 기준 오른쪽 길", "맞은편", "같은 방향 (내 차 앞이나 뒤)"]
ENTRY_TO_COMPASS = {"left": "west", "right": "east", "opposite": "north", "same": "south"}   # 2.6 방위 변환
WIDER = ["equal", "mine", "theirs"]
WIDER_CHOICES = ["폭이 비슷함", "내 차가 달린 도로", "상대가 달린 도로"]
WIDER_TO_AXIS = {"equal": "equal", "mine": "north_south", "theirs": "east_west"}
DEFAULT_ROAD_WIDTH = "equal"      # 8.4: 도로 폭이 비면 판정 엔진이 "맞는 규칙 없음"을 내서 기본값을 채움
# 어댑터가 정한 기본값. 답이 없으면 이 값으로 판정하고 출처를 default로 표시함 (질문 guess_source, answers.source)
DEFAULTS = {"scene.place": "intersection", "scene.junction_type": "cross", "road.signal_present": False,
            "road.wider_road": DEFAULT_ROAD_WIDTH}

OWN_FIELDS = {"scene.place", "scene.junction_type"}   # 차량 사건 전용 키. MTM에 넘기지 않고 facts.road로 옮김
VIDEO_ONLY_KEYS = {"lane_marking"}                    # 영상 전용 질문 (바닥 화살표)
VIDEO_QUESTION_KEYS = ("evidence_frame", "image", "light_hints")
RULE_FACTS = ("stopped_before_entry", "stationary_at_collision")   # 규칙 facts 중 판정 엔진에 넘기는 것
QUESTION_DEFAULTS = {"model_guess": None, "guess_source": None, "guess_evidence": None, "default": False,
                     "optional": False, "group": None, "depends_on": None}
# 질문 키 모양 (2.2 "없는 질문 키"). 지금 질문에 없는 키라도 이 모양이면 받는다: 앱은 지금까지의 답을 전부 보내므로,
# 앞 답을 바꿔 사라진 질문(예: 진입 순서를 바꿔 없어진 intersection_entry_clear)의 답이 섞여 올 수 있음
ANSWER_KEY = re.compile(r"^(parties\.(ego|other)\.[a-z_]+|road\.[a-z_]+|scene\.(place|junction_type)"
                        r"|situation\.[a-z_]+|intersection_entry_[a-z_]+)$")
NAMES = (("ego번 차", "내 차"), ("other번 차", "상대 차"), ("ego번", "내 차"), ("other번", "상대"))
# MTM 문구는 "{t}번이 …"처럼 숫자 뒤 조사라 이름을 바꾸면 "내 차이"가 됨 → 바꾼 이름의 받침에 맞춰 조사도 바꿈.
# "ego번(이륜차)이"처럼 괄호 설명이 끼어도 괄호 앞 이름을 봄
NAME_JOSA = re.compile(r"(ego|other)번( 차)?(\([^()]*\))?((?:이|가|은|는|을|를|과|와)(?![가-힣]))?")
JOSA_PAIRS = {"이": ("이", "가"), "가": ("이", "가"), "은": ("은", "는"), "는": ("은", "는"),
              "을": ("을", "를"), "를": ("을", "를"), "과": ("과", "와"), "와": ("과", "와")}


def josa(word, j):
    """word 뒤 조사 j를 받침에 맞게 (이/가, 은/는, 을/를, 과/와). 한글이 아니면 받침 없음으로 봄"""
    pair = JOSA_PAIRS.get(j)
    if not pair:
        return j
    code = ord(word[-1]) - 0xAC00 if word else -1
    return pair[0] if 0 <= code < 11172 and code % 28 else pair[1]


# ---------- 질문 ----------

def _q(field, question, options, choices, **extra):
    return {"field": field, "question": question, "answer_type": "choice", "options": options, "choices": choices,
            **extra}


def base_questions(place):
    """영상 사건의 build_facts가 내던 기본 질문 중 영상 없이 뜻이 통하는 것 (2.6 표). 상황 질문은 situation이 냄"""
    qs = [_q("scene.place", "사고가 난 곳은 어디인가요?", PLACES, PLACE_CHOICES,
             model_guess=DEFAULTS["scene.place"], guess_source="default", default=True)]
    if place == "intersection":
        qs.append(_q("scene.junction_type", "교차로 모양은 어땠나요?", JUNCTIONS, JUNCTION_CHOICES,
                     model_guess=DEFAULTS["scene.junction_type"], guess_source="default", default=True))
    qs += [
        _q("parties.ego.movement", "내 차는 어느 방향으로 가고 있었나요?", MOVEMENTS, MOVEMENT_CHOICES),
        _q("parties.other.cls", "상대는 무엇이었나요?", OTHER_CLASSES, OTHER_CLASS_CHOICES),
        _q("parties.other.movement", "상대 차는 어느 방향으로 가고 있었나요?", MOVEMENTS, MOVEMENT_CHOICES),
    ]
    if place == "intersection":
        qs += [
            _q("parties.other.entry_from", "상대는 어느 쪽 길에서 왔나요?", ENTRIES, ENTRY_CHOICES),
            # 영상이 없어 신호등을 볼 수 없으므로 사용자에게 묻는다 (기본값 질문이 아님, default: false).
            # 답이 없으면 1차 범위(비신호 교차로)대로 "없음"으로 판정하고 출처 default로 표시
            _q("road.signal_present", "이 교차로에 신호등이 있었나요?", [True, False], ["있음", "없음"],
               model_guess=DEFAULTS["road.signal_present"], guess_source="default"),
            _q("parties.ego.signal_at_entry", "내 차가 교차로에 들어갈 때 신호는 무엇이었나요?", SIGNALS, SIGNAL_NAMES,
               depends_on={"road.signal_present": True}),
            _q("parties.other.signal_at_entry", "상대가 교차로에 들어갈 때 신호는 무엇이었나요?", SIGNALS, SIGNAL_NAMES,
               depends_on={"road.signal_present": True}),
            _q("road.wider_road", "교차하는 두 도로 중 어느 쪽이 더 넓은가요?", WIDER, WIDER_CHOICES,
               model_guess=DEFAULTS["road.wider_road"], guess_source="default", default=True,
               depends_on={"parties.other.entry_from": ["left", "right"]}),
            _q("road.center_line", "사고 난 길에 중앙선(가운데 노란 선)이 있나요?", [True, False], ["있음", "없음 (골목길)"]),
            _q("intersection_entry_order", "두 차 중 어느 쪽이 먼저 교차로에 들어갔나요?", [EGO, OTHER, "same_time"],
               ["내 차", "상대", "거의 동시에"]),
        ]
    return qs


def _rename(s):
    if not isinstance(s, str):
        return s
    def one(m):
        name = dict(NAMES)[f"{m.group(1)}번{m.group(2) or ''}"]
        return name + (m.group(3) or "") + (josa(name, m.group(4)) if m.group(4) else "")
    s = NAME_JOSA.sub(one, s)
    # MTM 보기 "{t}번이 상대가 가까이 왔을 때 …"의 "상대"는 다른 당사자라, 상대 쪽 보기는 "상대가 상대가"가 됨
    return s.replace("상대가 상대가 ", "상대가 내 차가 ").replace("상대가 상대보다 ", "상대가 내 차보다 ")


def clean_question(q):
    """MTM 질문 → 차량 사건 질문 모양 (2.6): 영상 전용 키를 빼고, 당사자 이름을 바꾸고, 빠진 키를 채움"""
    q = {k: v for k, v in q.items() if k not in VIDEO_QUESTION_KEYS}
    q["question"] = _rename(q["question"])
    if q.get("choices"):
        q["choices"] = [_rename(c) for c in q["choices"]]
    for k, v in QUESTION_DEFAULTS.items():
        q.setdefault(k, copy.deepcopy(v))
    return q


def _video_only(q):
    return q["field"].split(".")[-1] in VIDEO_ONLY_KEYS


def _met(q, answers):
    """depends_on 조건이 답에 맞는지 (answers.remaining과 같은 방식)"""
    return all(answers.get(k) in v if isinstance(v, list) else answers.get(k) == v
               for k, v in (q.get("depends_on") or {}).items())


# ---------- 답 변환 ----------

def to_mtm(user):
    """자기 차 기준 답 → MTM 답 (2.6 방위 변환). 차량 사건 전용 키는 뺌"""
    out = {}
    for k, v in user.items():
        if k in OWN_FIELDS:
            continue
        if k == "parties.other.entry_from":
            v = ENTRY_TO_COMPASS.get(v, v)
        elif k == "road.wider_road":
            v = WIDER_TO_AXIS.get(v, v)
        out[k] = v
    return out


def shell(req, place, junction, auto, rule_results):
    """MTM 함수에 넣을 facts 껍데기 (8.4). 값은 그냥 값(situation이 읽는 모양)으로 넣고,
    판정 직전에 출처가 vehicle인 값만 값 객체로 감싼다 (judge_facts)"""
    ego = {"cls": req["vehicle_cls"], "movement": None, "entry_from": "south"}
    for field, r in auto.items():
        if field.startswith("parties.ego."):
            ego[field.split(".", 2)[2]] = r["value"]
    for r in rule_results:
        for k, v in r.get("facts", {}).items():
            if k in RULE_FACTS and v is not None:
                ego[k] = v
    other = {"cls": None, "movement": None, "entry_from": None}
    return {
        "schema_version": "0.3", "video": None, "fps": FPS,
        # 영상 전용 값은 0·고정값. zone은 situation이 "교차로 안이었나" 질문을 내지 않게 교차로로 둠
        "collision": {"a": EGO, "b": OTHER, "frame": 0, "t": 0, "zone": "intersection"},
        "parties": {EGO: ego, OTHER: other},
        "road": {"location": place, "junction_type": junction, "signal_present": None, "road_width": None},
        "events": [], "unknowns": [],
    }


def vehicle_keys(auto, rule_results):
    """판정 facts에서 출처를 vehicle로 붙일 내 차 값 이름"""
    keys = {"cls"}
    keys |= {f.split(".", 2)[2] for f in auto if f.startswith("parties.ego.")}
    keys |= {k for r in rule_results for k, v in r.get("facts", {}).items() if k in RULE_FACTS and v is not None}
    return keys


# ---------- 결과 ----------

def data_quality(tl, req):
    T = req["t_event"]
    a = max(req["range"]["from"], T - FIELDS_MISSING_MS)
    return {"samples": len(req["samples"]), "gaps": tl.gaps(),
            "fields_missing": [k for k in SAMPLE_KEYS if tl.known(k, a, T) == 0],
            # 명세 6.1: 앱 시계가 서버 시각(받은 시각)과 하루 넘게 다르면 경고. 전에 저장한 요청은 받은 시각이 없어 []
            "clock_warnings": clock.warnings(req.get("server_ms"), vehicle_range=req["range"])}


def _fact_field(fact, party):
    """판정 엔진의 사실 이름(예: "turn_signal_used", "A.turn_signal_used") → 질문 키"""
    name = str(fact).split(".")[-1]
    return f"parties.{party}.{name}"


# 가감 요소 사실(엔진 이름) → 그 값을 정한 질문 키 (notes C10). {p} = 사실의 당사자.
# 엔진 이름과 질문 키가 같은 것(parties.<p>.<사실>)은 따로 적지 않음 (fact_keys가 늘 넣음)
FACT_KEYS = {
    "slowed_before_entry": ("parties.{p}.stopped_before_entry",),   # 일시정지했으면 서행 (judge/adapter)
    "on_wider_road": ("road.wider_road",),
    "stop_sign": ("road.stop_sign_side",),
    "lead_order": ("pair.lead_order",),
    "side_in_pair": ("pair.right_side",),
    "user_factors": ("parties.{p}.driver_factors",),
    "speed_over_limit_kmh": ("parties.{p}.driver_factors",),
    "entry_lead_sec": ("intersection_entry_order",),
    "intersection_entry_t": ("intersection_entry_order",),
    "crossing_on_crosswalk": ("parties.{p}.crossing_place",),
    "ped_signal_at_crossing": ("parties.{p}.ped_signal_at_impact",),
    # 블랙박스 보행자 장 질문 (src/blackbox/chapter.py)
    "ped_place": ("parties.{p}.crosswalk_distance", "parties.{p}.ped_place_other"),
    "dist_from_crosswalk_m": ("parties.{p}.crosswalk_distance", "parties.{p}.overpass_distance"),
    "in_own_protection_zone": ("parties.{p}.vulnerable_type", "road.protection_zone"),
}
SCENE_KEYS = {"road_width": ("road.wider_road",), "location": ("scene.place", "road.location"),
              "junction_type": ("scene.junction_type",), "road_class": ("road.center_line", "road.expressway"),
              "state": ("road.signal_present",),
              # 블랙박스 보행자 장 질문 (src/blackbox/chapter.py, 2026-11-11)
              "night": ("road.ped_visibility",), "view_obstructed": ("road.ped_visibility",),
              "bad_weather": ("road.ped_visibility",)}
SPECIAL_FACTS = {f.split("=")[0] for _, f, *_ in situation.SPECIAL if f}   # 특수 상황 보기로 정하는 사실


def fact_keys(fact, party):
    """가감 요소 근거 사실(엔진 observed 키) → 질문 키 목록. observed 키 모양: "사실"(그 당사자),
    "other.사실"(상대), "facts.scene.사실"·"facts.signal.state"(장면), "A.사실"(역할)"""
    parts = str(fact).split(".")
    name = parts[-1]
    if parts[0] == "facts":
        keys = list(SCENE_KEYS.get(name, ())) + [f"road.{name}"]
        if name in SPECIAL_FACTS:
            keys.append("situation.special")
        return keys
    p = {EGO: OTHER, OTHER: EGO}.get(party, party) if parts[0] == "other" and len(parts) > 1 else party
    keys = [f"parties.{p}.{name}"] + [k.format(p=p) for k in FACT_KEYS.get(name, ())]
    if name in SPECIAL_FACTS:
        keys.append("situation.special")
    return keys


def view_result(verdict, provisional, answers, auto_filled):
    """판정 엔진 결과 → 2.7 result"""
    r = verdict["result"]
    out = {"status": verdict["status"], "provisional": provisional, "rule_id": None, "title": None,
           "fault_by_party": None, "base_fault_by_party": None, "modifiers": [], "unverifiable_factors": [],
           "auto_filled": auto_filled, "notice": None}
    if verdict["status"] != "ok":
        return out
    track = {role: v["track_id"] for role, v in r["roles"].items()}

    def source_of(facts, party):
        """2.7: 근거 사실 중 하나라도 사용자 답이면 user, 아니고 차량 기록이면 vehicle, 둘 다 아니면 default"""
        srcs = {answers.get(k, {}).get("source") for f in facts for k in fact_keys(f, party)}
        return "user" if "user" in srcs else "vehicle" if "vehicle" in srcs else "default"

    mods = []
    for m in r["applied_modifiers"]:
        party = track.get(m["party"], m["party"])
        facts = sorted((m.get("observed") or {}).keys())
        mods.append({"label": m["label"], "party": party, "delta": m["delta"],
                     "source": source_of(facts, party), "facts": facts, "needs_proof": m.get("needs_proof", False)})
    out.update(rule_id=r["rule_id"], title=r["title"], fault_by_party=r["fault_by_track"],
               base_fault_by_party={track[role]: v for role, v in r["base"].items()},
               modifiers=mods,
               unverifiable_factors=[dict(u, party=track.get(u["party"], u["party"])) for u in r.get("unverifiable_factors", [])])
    return out


def judge(facts, asm, vkeys, judge_dir=JUDGE_DIR):
    """판정 facts를 임시 파일로 써서 judge_bridge.judge 호출 (그 함수가 파일 경로를 받음).
    vkeys: 출처를 vehicle로 붙일 내 차 값 이름"""
    f = copy.deepcopy(facts)
    for k in vkeys:
        if f["parties"][EGO].get(k) is not None:
            f["parties"][EGO][k] = {"value": f["parties"][EGO][k], "source": "vehicle"}
    fd, path = tempfile.mkstemp(prefix="vehicle_facts_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(f, fp, ensure_ascii=False)
        return judge_bridge.judge(path, asm, judge_dir)
    finally:
        os.remove(path)


# ---------- 묶어 돌리기 ----------

def build(req, user=None, judge_dir=JUDGE_DIR):
    """정리한 요청(samples.validate 결과) + 사용자 답(자기 차 기준 보기) → 저장할 기록
    {view(2.5, id·시각 제외), rule_results, rules, judge_version}

    차량 기록은 참고 자료다 (docs/design-blackbox.md 4.4, 2026-11-10): result는 사용자 답·기본값만으로 낸 판정,
    result_with_vehicle은 차량 규칙 자동 답변을 더한 판정. 자동 답변하던 질문도 questions에 남고 vehicle_hint가 붙는다.
    vehicle_effects·vehicle_timeline은 블랙박스 사건과 같은 모양 (src/blackbox/effects.py)"""
    from src.blackbox import effects   # 블랙박스 근거 문장을 같이 씀 (순환 import를 피해 여기서)
    with_v = _build(req, user, judge_dir, use_vehicle=True)
    base = _build(req, user, judge_dir, use_vehicle=False)
    hint_map = effects.hints(with_v["rule_results"])
    view = base["view"]
    for q in view["questions"]:
        q["vehicle_hint"] = copy.deepcopy(hint_map.get(q["field"]))
    view["result_with_vehicle"] = with_v["view"]["result"]
    view["vehicle_effects"] = effects.effects(
        {"result": view["result"], "answers": view["answers"]},
        {"result": with_v["view"]["result"], "answers": with_v["view"]["answers"]}, hint_map=hint_map)
    view["vehicle_timeline"] = effects.timeline(req, req["t_event"], "vehicle")
    for k in ("auto_answers", "answer_conflicts"):
        view[k] = with_v["view"][k]
    return {**base, "rule_results": with_v["rule_results"], "rules": with_v["rules"],
            "with_vehicle": with_v["view"]}   # 저장하지 않음 (시험·설명용 전체 판정)


def _build(req, user, judge_dir, use_vehicle):
    """판정 한 번. use_vehicle=False면 규칙을 돌리지 않음 (사용자 답·기본값만, 내 차 종류는 씀)"""
    user = dict(user or {})
    tl = Timeline(req["samples"], end=req["range"]["to"])
    ctx = rules.Ctx(req["t_event"], req["t_event_source"])
    results = rules.run_rules(tl, ctx, user) if use_vehicle else []
    determined = {r["field"]: r for r in results if r["determined"] and r["field"] not in user}
    guesses = {r["field"]: r for r in results if not r["determined"]}

    place = user.get("scene.place", DEFAULTS["scene.place"])
    junction = user.get("scene.junction_type", DEFAULTS["scene.junction_type"]) if place == "intersection" else None
    mtm_user = to_mtm(user)
    facts = shell(req, place, junction, determined, results)

    # 질문: 기본 질문 + 상황 질문. 영상 전용 질문은 뺌
    qs = base_questions(place) + situation.questions(facts, mtm_user)
    qs = [clean_question(q) for q in qs if not _video_only(q)]
    # 자동 답변은 그 질문이 나올 때만 씀 (서행: 신호 없는 교차로일 때만 묻는 질문, B10. 지시등: 회전할 때만).
    # depends_on은 답이 없는 기본값 질문(신호 없음)을 기본값으로 보고 따짐 (판정에 그 값을 쓰므로)
    effective = {**{f: v for f, v in DEFAULTS.items() if f.startswith("road.")}, **user}
    asked = {q["field"] for q in qs if _met(q, effective)}
    auto = {f: r for f, r in determined.items() if f in asked}
    for f in set(determined) - set(auto):   # 묻지 않는 질문의 자동 답변은 판정에도 넘기지 않음
        facts["parties"][EGO].pop(f.split(".", 2)[2], None)
    for q in qs:
        g = guesses.get(q["field"])
        if g:
            q.update(model_guess=g["model_guess"], guess_source=g["guess_source"], guess_evidence=g["guess_evidence"])
        if q["field"] == "situation.special":
            for r in auto.values():
                for v in (r.get("preselect") or {}).get("situation.special", []):
                    if v in q["options"] and v not in q["model_guess"]:
                        q["model_guess"] = q["model_guess"] + [v]
                        q["guess_source"] = "vehicle"
    asked_all = {q["field"] for q in qs}
    qs = [q for q in qs if q["field"] not in auto]

    try:
        ans.check({"unknowns": qs}, user, 0)
    except ValueError as e:
        raise VehicleError("answer_invalid", f"답을 확인해 주세요: {e}")
    bad = [k for k in user if not (isinstance(k, str) and ANSWER_KEY.match(k)) and k not in asked_all]
    if bad:
        raise VehicleError("answer_invalid", f"답을 확인해 주세요: 없는 질문 키 {bad[0]!r}")

    # 남은 질문: 자동 답변도 답으로 보고 depends_on을 따짐
    answered = {**user, **{f: r["value"] for f, r in auto.items()}}
    left = ans.remaining({"unknowns": qs}, answered)

    # 판정: 남은 질문은 추정값·기본값으로 채움 (MTM fill_guesses). 보기는 MTM 값으로 바꿔서 넘김
    facts["unknowns"] = [dict(q, model_guess=to_mtm({q["field"]: q["model_guess"]}).get(q["field"], q["model_guess"]))
                         for q in qs]
    facts["judge_thresholds"] = judge_bridge.thresholds(judge_dir)
    mtm_left = [u for u in facts["unknowns"] if u["field"] in {q["field"] for q in left}]
    judge_facts, filled = ans.fill_guesses(facts, mtm_left, mtm_user)
    for f in (f for f in ("scene.place", "scene.junction_type") if f in asked and f not in user):
        filled.append(f)
    road = judge_facts["road"]
    if road.get("road_width") is None and "road.wider_road" not in user:
        road["road_width"] = DEFAULT_ROAD_WIDTH
        if "road.wider_road" not in filled:
            filled.append("road.wider_road")
    # fill_guesses가 판정 facts의 장소를 비우므로 가정은 원래 facts로 만든다 (장소가 가정으로 넘어감, pipeline.solve와 같음)
    asm = ans.to_assumptions(facts, mtm_user)
    verdict = judge(judge_facts, asm, vehicle_keys(auto, results), judge_dir)

    # 판정에 쓴 답 전체 (2.5 answers)
    by_field = {q["field"]: q for q in qs}
    used = {"parties.ego.cls": {"value": req["vehicle_cls"], "source": "vehicle"}}
    for f, r in auto.items():
        used[f] = {"value": r["value"], "source": "vehicle"}
    for f in filled:
        val = by_field[f]["model_guess"] if f in by_field else None
        if f == "road.wider_road" and val is None:
            val = DEFAULT_ROAD_WIDTH
        if f == "scene.place":
            val = place
        if f == "scene.junction_type":
            val = junction
        used[f] = {"value": val, "source": "default"}
    for f, v in user.items():
        used[f] = {"value": v, "source": "user"}
    conflicts = [{"field": r["field"], "vehicle_value": r["value"], "user_value": user[r["field"]],
                  "evidence": r["evidence"]}
                 for r in results if r["determined"] and r["field"] in user and user[r["field"]] != r["value"]]

    status = "needs_answers" if any(not q.get("optional") for q in left) else "done"
    view = {
        "status": status,
        "event": {"t_event": req["t_event"], "t_event_source": req["t_event_source"], "range": req["range"]},
        "data_quality": data_quality(tl, req),
        "parties": {EGO: {"label": "내 차", "cls": req["vehicle_cls"]},
                    OTHER: {"label": "상대", "cls": user.get("parties.other.cls")}},
        "auto_answers": [rules.auto_answer(r) for r in auto.values()],
        "answers": used,
        "answer_conflicts": conflicts,
        "questions": left,
        "result": view_result(verdict, status == "needs_answers", used, filled),
        "judge_version": verdict["judge_version"],
    }
    return {"view": view, "rule_results": results, "rules": sorted({r["rule"] for r in results}),
            "judge_version": verdict["judge_version"]}
