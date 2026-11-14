"""블랙박스 사건 합치기·질문·판정 (docs/design-blackbox.md 3.3 "합치기", 4절)

  build(bb, vehicle_req, sync, user) → {view, rule_results, rules, judge_version, with_vehicle}

  차량 기록은 참고 자료 (4.4, 2026-11-10): 아래 1~4를 차량 기록 없이(base → result) 한 번, 차량 기록을 넣고
  (with_vehicle → result_with_vehicle) 한 번 돌린다. 차이·질문 참고·그래프 요약은 effects.py

  1. 차량 규칙 (sync 등급이 coarse 이상일 때만): T = sync.t_collision_ms, Ctx(T, "manual") (5.4)
     내 차 진행 방향·진로 변경 방향은 합친 값(user > vehicle > video)을 다음 규칙의 입력으로 줌
  2. 합치기 (merge): user > vehicle > video > default, source_conflicts
  3. 질문: 사고 장(상대 종류, chapter.py)별로. 차대차는 차량 사건과 같은 기본 질문 + 상황 질문,
     차대보행자·차대자전거는 chapter.questions. 영상·차량이 정한 항목은 빼고, 추정값 출처에 video를 더함.
     상대 종류가 추정값뿐이면 "상대는 무엇이었나요?"를 remaining 맨 앞에 둠
  4. 판정: 분석기 facts를 값 그대로 쓴 facts 껍데기 → MTM fill_guesses / to_assumptions / judge_bridge
     (장 질문의 답·추정값은 chapter.add_assumptions / chapter.fill로 판정 엔진 이름으로 바꿔 넣음)

src/vehicle/adapter.py의 함수(base_questions, clean_question, to_mtm, _met, view_result 등)를 불러 쓰고 고치지 않는다.
"""
import copy
import json
import os
import tempfile

from src.app import answers as ans
from src.app import judge_bridge, situation
from src.app.pipeline import JUDGE_DIR
from src.blackbox import chapter, effects, evidence, merge, multi
from src.vehicle import adapter as va
from src.vehicle import rules
from src.vehicle.samples import Timeline, VehicleError

EGO, OTHER = va.EGO, va.OTHER
SOURCE_TO_ENGINE = {"vehicle": "vehicle", "video": "model"}   # 판정 엔진에 넘기는 source (4.1)
RULE_INPUTS = ("parties.ego.movement", "parties.ego.lane_change_dir")
REMAINING_KEYS = ("field", "question", "answer_type", "options", "choices", "model_guess", "guess_source",
                  "guess_evidence", "default", "group", "depends_on")
SYNC_SUSPECT = 2              # vehicle_vs_video 충돌이 이만큼 이상이면 시각 맞추기가 틀렸을 수 있다고 경고 (4.3)


def _run_rules(vreq, sync, user, video_def):
    """차량 규칙. 시각 맞추기가 none이거나 차량 기록이 없으면 []"""
    if not vreq or sync["grade"] not in ("coarse", "fine", "user"):
        return [], None
    tl = Timeline(vreq["samples"], end=vreq["range"]["to"])
    ctx = rules.Ctx(sync["t_collision_ms"], "manual")
    first = rules.run_rules(tl, ctx, user)
    vdef, _, _ = merge.vehicle_values(first, sync["grade"])
    inputs = dict(user)
    for f in RULE_INPUTS:   # 진행 방향 합친 값으로 지시등·진로 변경 방향을 다시 계산
        if f not in inputs:
            win = vdef.get(f) or video_def.get(f)
            if win is not None:
                inputs[f] = win["value"]
    return rules.run_rules(tl, ctx, inputs), tl


def _shell(bb, vreq, place, junction, decided):
    """MTM 함수에 넣을 facts 껍데기: 값은 그냥 값. 영상·차량이 정한 값(user 제외)을 넣는다"""
    facts = bb["facts"]
    col = facts["collision"]
    fps = (bb.get("video") or {}).get("fps") or va.FPS
    ego = {"cls": vreq["vehicle_cls"] if vreq else "car", "movement": None, "entry_from": "south"}
    other = {"cls": None, "movement": None, "entry_from": None}
    _, _, extra = merge.video_values(facts)
    ego.update(extra.get(EGO, {}))
    other.update(extra.get(OTHER, {}))
    road = {"location": place, "junction_type": junction, "signal_present": None, "road_width": None}
    parties = {EGO: ego, OTHER: other}
    for f, d in decided.items():
        if d["source"] == "user":
            continue
        v = va.to_mtm({f: d["value"]}).get(f)
        if f.startswith("parties."):
            _, pid, k = f.split(".", 2)
            parties[pid][k] = v
        elif f.startswith("road."):
            road[f.split(".", 1)[1]] = v
    # 앞뒤는 한쪽만 알아도 다른 쪽이 정해짐 (MTM pair.lead_order 답과 같은 모양: leading ↔ following)
    pair = {"leading": "following", "following": "leading"}
    for a, b in ((EGO, OTHER), (OTHER, EGO)):
        if parties[a].get("lead_order") in pair and parties[b].get("lead_order") is None:
            parties[b]["lead_order"] = pair[parties[a]["lead_order"]]
    # 영상의 "충돌 때 서 있었음"을 MTM 이름으로도 넣음: 같은 방향 사고에서 "왜 서 있었나요?"(stop_state) 질문이 나옴
    for p in parties.values():
        if p.get("stationary_at_collision") is True:
            p.setdefault("stopped_before_collision", True)
    zone = col.get("zone") or "intersection"   # 모르면 교차로로 둠 (차량 사건과 같음, "교차로 안이었나" 질문을 안 냄)
    return {
        "schema_version": "0.3", "video": None, "fps": fps,
        "collision": {"a": EGO, "b": OTHER, "frame": col.get("frame") or 0, "t": col.get("t") or 0, "zone": zone},
        "parties": parties, "road": road, "events": [], "unknowns": [],
    }


def _judge(facts, asm, sources, judge_dir):
    """판정 facts의 당사자 값에 출처를 붙여(vehicle / model) judge_bridge.judge 호출"""
    f = copy.deepcopy(facts)
    for field, src in sources.items():
        if not field.startswith("parties."):
            continue
        _, pid, k = field.split(".", 2)
        if f["parties"][pid].get(k) is not None and not isinstance(f["parties"][pid][k], dict):
            f["parties"][pid][k] = {"value": f["parties"][pid][k], "source": SOURCE_TO_ENGINE[src]}
    fd, path = tempfile.mkstemp(prefix="bb_facts_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(f, fp, ensure_ascii=False)
        return judge_bridge.judge(path, asm, judge_dir)
    finally:
        os.remove(path)


def _fault_display(chapter_name, fault):
    """비율 표기 (3.6). 차대보행자 장은 인정기준이 보행자 과실만 정한다: 내 차 = 100 − 보행자 과실.
    fault_by_party는 장과 관계없이 두 당사자 합 100으로 두고(앱 막대), 앱은 text를 머리 숫자로 씀"""
    if not fault:
        return None
    if chapter_name == chapter.CAR_PED:
        p = fault.get(OTHER)
        return {"kind": "pedestrian_only", "party": OTHER, "value": p, "text": f"보행자 과실 {p}%",
                "note": f"차대보행자 기준은 보행자 과실만 정해요. 내 차 몫은 나머지 {100 - p}%예요"}
    return {"kind": "ratio", "party": None, "value": None,
            "text": f"내 차 {fault.get(EGO)} : 상대 {fault.get(OTHER)}", "note": None}


def _result(verdict, provisional, used, filled, chapter_name, user=None):
    """2.7 result. 가감 요소 출처는 user > vehicle > video > default (4.3 끝). 장(chapter)과 비율 표기를 더함"""
    out = va.view_result(verdict, provisional, used, filled)
    for m in out["modifiers"]:
        m["source"] = merge.source_of({used.get(k, {}).get("source") for f in m["facts"]
                                       for k in multi.source_keys(va.fact_keys(f, m["party"]), f, user or {})})
    out["chapter"] = chapter_name
    out["fault_display"] = _fault_display(chapter_name, out["fault_by_party"])
    return out


def _data_quality(tl, vreq, sync, conflicts):
    dq = {"vehicle_record": vreq is not None, "sync_grade": sync["grade"], "sync_reason": sync["reason"],
          "samples": len(vreq["samples"]) if vreq else 0, "gaps": [], "fields_missing": [],
          "sync_suspect": sum(c["kind"] == "vehicle_vs_video" for c in conflicts) >= SYNC_SUSPECT,
          # 명세 6.1: 시각 맞추기가 none인 이유 한 문장, 서버 시각과 하루 넘게 다른 시계 (sync에서 계산해 저장)
          "sync_reason_text": sync.get("reason_text"), "clock_warnings": sync.get("clock_warnings") or []}
    if tl is not None:
        T = sync["t_collision_ms"]
        a = max(vreq["range"]["from"], T - va.FIELDS_MISSING_MS)
        dq["gaps"] = tl.gaps()
        dq["fields_missing"] = [k for k in va.SAMPLE_KEYS if tl.known(k, a, T) == 0]
    return dq


def remaining(left):
    """실제로 답이 필요한 질문 (선택 질문 제외). 판정에는 지금 추정값·기본값이 들어가 있음 (provisional).
    상대 종류 질문은 맨 앞 (장이 바뀌면 나머지 질문이 통째로 바뀜, 8.3.1)"""
    out = []
    left = sorted(left, key=lambda q: q["field"] != chapter.CLS_FIELD)
    for q in left:
        if q.get("optional"):
            continue
        item = {k: copy.deepcopy(q.get(k)) for k in REMAINING_KEYS}
        g = q.get("model_guess")
        item["guess_choice"] = evidence._choice(q, g) if g not in (None, []) else None
        out.append(item)
    return out


def _add_evidence(used, decided, all_q, by_field):
    """answers[키].evidence: 출처마다 근거 문장 ("~했어요"). vehicle은 차량 규칙 문장, video는 영상 값 문장"""
    for f, u in used.items():
        q = all_q.get(f)
        src, val = u["source"], u["value"]
        if src in ("vehicle", "video") and decided.get(f, {}).get("evidence"):
            u["evidence"] = decided[f]["evidence"]
        elif src == "vehicle":                       # 내 차 종류 (차량 정보)
            u["evidence"] = f"{evidence.sentence(f, val, q)} (차량 정보)"
        elif src == "video":
            u["evidence"] = evidence.for_video(f, val, None, q)
        elif src == "user":
            u["evidence"] = evidence.for_user(f, val, q)
        else:
            q_ = by_field.get(f) or {}
            basis = q_.get("guess_source") if q_.get("model_guess") not in (None, []) else None
            # basis: guess = 영상·차량 기록 추정값으로 채움 (앱 "추정" 배지), default = 기본값 (앱 "가정" 배지)
            u["basis"] = "guess" if basis in ("video", "vehicle") else "default"
            u["evidence"] = evidence.for_default(f, val, basis, q)


def user_scene_wins(judge_facts, asm, video_def, conflicts):
    """확정 Q9(사용자 > 차량 > 영상 > 기본값)를 장면 값에도 지킴 (2026-11-11). 반환: 새 source_conflicts.

    판정 엔진(judge/adapter.py)은 장면 값을 facts.road에서 먼저 읽고 가정(사용자 답)은 빈 칸만 채운다 (당사자 값은 가정이 이김).
    같은 질문 키(road.signal_present 등)면 _shell이 사용자 답이 있는 값을 facts에 넣지 않아 괜찮지만, 답 키가 다르면
    (보행자 road.ped_visibility → night·bad_weather, 차대차 situation.special의 "밤이었음" → night, "비·눈·안개" → low_visibility)
    영상 값이 facts에 남아 사용자 답을 이겼다. 사용자 답에서 나온 장면 값(asm.scene)과 다른 facts.road 값은 빼서 답이 이기게 하고,
    그 값이 영상 확정값이면 user_vs_video 충돌로 남긴다 (같은 내용을 질문 키 충돌로 이미 남겼으면 빼기만).
    반환: (새 충돌, 판정에서 뺀 질문 키)"""
    road, out, overruled = judge_facts["road"], [], []
    covered = {c["field"] for c in conflicts}
    for k, v in (asm.get("scene") or {}).items():
        if k.startswith("_") or road.get(k) is None or road[k] == v:
            continue
        old = road.pop(k)
        overruled.append(f"road.{k}")
        vid = video_def.get(f"road.{k}")
        if vid is None or vid["value"] != old:
            continue                                   # 기본값·추정값이 채운 값: 충돌 아님
        if chapter.VISIBILITY_FIELD in covered and k in chapter.VISIBILITY_SCENE["clear"]:
            continue                                   # 영상 밤·악천후 → 시야 질문 확정값과 이미 충돌로 남김
        out.append({"field": f"road.{k}", "used": {"value": v, "source": "user"},
                    "others": [{"value": old, "source": "video", "evidence": vid.get("evidence")}],
                    "evidence": evidence.for_user(f"road.{k}", v), "kind": "user_vs_video"})
    # 당사자 값은 엔진에서 가정이 이미 이김. 답 키가 다른 경우(특수 상황 보기 → 당사자 사실 등)의 충돌 기록만 더함
    for pid, kv in (asm.get("parties") or {}).items():
        if str(pid).startswith("_") or pid not in judge_facts["parties"]:
            continue
        for k, v in kv.items():
            field = f"parties.{pid}.{k}"
            vid, old = video_def.get(field), judge_facts["parties"][pid].get(k)
            if field in covered or vid is None or old is None or vid["value"] != old or old == v:
                continue
            overruled.append(field)
            out.append({"field": field, "used": {"value": v, "source": "user"},
                        "others": [{"value": old, "source": "video", "evidence": vid.get("evidence")}],
                        "evidence": evidence.for_user(field, v), "kind": "user_vs_video"})
    return out, overruled


def _pair(rec):
    return {"result": rec["view"]["result"], "answers": rec["view"]["answers"]} if rec else None


def build(bb, vreq, sync, user=None, judge_dir=JUDGE_DIR):
    """분석 결과(bb_facts, status ok) + 차량 기록(정리한 요청 또는 None) + 시각 맞추기 + 사용자 답 → 저장할 기록.

    차량 기록은 참고 자료다 (4.4): result는 영상·사용자 답·기본값만으로 낸 판정(base), result_with_vehicle은 base에
    차량 기록을 더한 판정(기록이 없으면 null), vehicle_effects는 둘의 차이를 만든 기록, vehicle_timeline은 그래프용 요약.
    차량 기록이 답하던 질문도 base 기준으로 remaining에 나오고, 차량 기록 값은 질문마다 vehicle_hint로 붙는다.
    시각 맞추기가 coarse/none이면 타이밍 값은 with_vehicle에도 쓰지 않는다. 정확히 맞췄다고 본 판정(hypo)과 다르면
    그 값을 applied: false로 vehicle_effects에 남긴다"""
    base = _build(bb, vreq, sync, user, judge_dir, use_vehicle=False)
    with_v = _build(bb, vreq, sync, user, judge_dir, use_vehicle=True) if vreq else None
    grade = sync["grade"]
    hypo, reason = None, None
    results = with_v["results"] if with_v else []
    if vreq and grade not in merge.FULL_GRADES and sync.get("t_collision_ms") is not None:
        reason = "sync_coarse" if grade == "coarse" else "sync_none"
        hypo = _build(bb, vreq, dict(sync, grade="fine"), user, judge_dir, use_vehicle=True)
        results = hypo["results"]

    def unusable(r):
        if reason == "sync_none" or (reason == "sync_coarse" and r["rule"] in merge.TIMING_RULES):
            return reason
        return None

    hint_map = effects.hints(results, unusable)
    view = base["view"]
    for key in ("remaining", "questions", "answered"):
        for q in view[key]:
            q["vehicle_hint"] = copy.deepcopy(hint_map.get(q["field"]))
    view["result_with_vehicle"] = with_v["view"]["result"] if with_v else None
    view["vehicle_effects"] = effects.effects(_pair(base), _pair(with_v), _pair(hypo), reason, hint_map)
    view["vehicle_timeline"] = effects.timeline(vreq, sync.get("t_collision_ms"), grade,
                                                bb["facts"]["collision"].get("t"))
    if with_v:   # 차량 기록 쪽 칸은 차량 기록을 넣은 판정 기준 (자동 답변, 출처끼리 다른 값, 기록 품질)
        for k in ("auto_answers", "source_conflicts", "answer_conflicts", "data_quality"):
            view[k] = with_v["view"][k]
    src = with_v or base
    return {"view": view, "rule_results": src["rule_results"], "rules": src["rules"],
            "judge_version": base["judge_version"],
            "with_vehicle": with_v["view"] if with_v else None}   # 저장하지 않음 (시험·설명용 전체 판정)


def _build(bb, vreq, sync, user, judge_dir, use_vehicle):
    """판정 한 번. use_vehicle=False면 차량 규칙을 돌리지 않음 (base). 내 차 종류(차량 정보)는 둘 다 씀"""
    user = dict(user or {})
    if user.get(chapter.CLS_FIELD) in chapter.CLS_TO_ANSWER:   # 분석기 이름(person)으로 답해도 받음
        user[chapter.CLS_FIELD] = chapter.to_answer_cls(user[chapter.CLS_FIELD])
    video_def, video_guess, _ = merge.video_values(bb["facts"])
    cls_info = chapter.adjust_video(bb["facts"], video_def, video_guess)
    results, tl = _run_rules(vreq, sync, user, video_def) if use_vehicle else ([], None)
    vehicle_def, vehicle_guess, _ = merge.vehicle_values(results, sync["grade"])
    decided, guesses, conflicts = merge.merge(user, vehicle_def, video_def, vehicle_guess, video_guess)

    def value(f, default=None):
        return decided[f]["value"] if f in decided else default

    # 사고 장: 상대 종류 사용자 답 > 영상 확실한 값 > 영상 추정값 (추정값으로 임시 판정)
    other_cls = value(chapter.CLS_FIELD, (guesses.get(chapter.CLS_FIELD) or {}).get("model_guess"))
    ch = chapter.chapter_of(other_cls)
    if ch != chapter.CAR_PED:   # 영상 밤·악천후 → 보행자 시야 질문 값은 보행자 장에서만 (다른 장은 road.night 그대로)
        decided.pop(chapter.VISIBILITY_FIELD, None)
        guesses.pop(chapter.VISIBILITY_FIELD, None)
        conflicts = [c for c in conflicts if c["field"] != chapter.VISIBILITY_FIELD]

    place = value("scene.place", va.DEFAULTS["scene.place"])
    junction = value("scene.junction_type", va.DEFAULTS["scene.junction_type"]) if place == "intersection" else None
    mtm_user = va.to_mtm(user)
    facts = chapter.drop_overridden(_shell(bb, vreq, place, junction, decided), ch, user)
    # 상황 질문은 정해진 값을 답처럼 본다 (신호 있음·없음 등). 사용자 답은 가정으로만 판정에 넘어감 (to_assumptions)
    seen = va.to_mtm({f: d["value"] for f, d in decided.items()})
    # 상황 질문(MTM)은 장을 상대 종류로 고른다: 추정 종류도 넣고, 자전거는 차처럼 진행 방향·신호·표지를 물으려고 차로 봄
    if other_cls is not None:
        seen[chapter.CLS_FIELD] = "car" if ch == chapter.CAR_BIKE else other_cls
    base = [va.clean_question(q) for q in va.base_questions(place) if not va._video_only(q)]
    sit = [va.clean_question(q) for q in situation.questions(facts, seen) if not va._video_only(q)]
    qs = [multi.with_none(q) for q in chapter.speed_followups(chapter.questions(ch, base, sit))]
    effective = {**{f: v for f, v in va.DEFAULTS.items() if f.startswith("road.")},
                 **{f: d["value"] for f, d in decided.items()}}
    asked = {q["field"] for q in qs if va._met(q, effective)}
    # 차량 규칙의 질문 답은 그 질문이 나올 때만 씀 (차량 사건과 같음). 규칙 사실·영상 값은 늘 씀
    auto_fields = {f for f, d in decided.items() if d["source"] == "vehicle"
                   and (f in asked or f.split(".")[-1] in va.RULE_FACTS)}
    for f in [f for f, d in decided.items() if d["source"] == "vehicle" and f not in auto_fields]:
        _, pid, k = f.split(".", 2)
        facts["parties"][pid].pop(k, None)
        del decided[f]
        conflicts = [c for c in conflicts if c["field"] != f]
        if f in video_def:   # 차량 값을 안 쓰면 영상 값으로 내려감
            decided[f] = {"value": video_def[f]["value"], "source": "video", "evidence": video_def[f]["evidence"]}
            if f.startswith("parties."):
                _, pid, k = f.split(".", 2)
                facts["parties"][pid][k] = va.to_mtm({f: video_def[f]["value"]})[f]
    machine = {f: d for f, d in decided.items() if d["source"] != "user"}

    for q in qs:
        g = guesses.get(q["field"])
        if g:
            q.update(model_guess=g["model_guess"], guess_source=g["guess_source"], guess_evidence=g["guess_evidence"],
                     default=False)
        if q["field"] == "situation.special":
            for r in results:
                if r["determined"] and r["field"] in auto_fields:
                    for v in (r.get("preselect") or {}).get("situation.special", []):
                        if v in q["options"] and v not in q["model_guess"]:
                            q["model_guess"] = q["model_guess"] + [v]
                            q["guess_source"] = "vehicle"
    asked_all = {q["field"] for q in qs}
    all_q = {q["field"]: q for q in qs}
    qs = [q for q in qs if q["field"] not in machine]

    try:
        ans.check({"unknowns": qs}, user, 0)
        multi.check(user)
    except ValueError as e:
        raise VehicleError("answer_invalid", f"답을 확인해 주세요: {e}")
    bad = [k for k in user if not (isinstance(k, str) and va.ANSWER_KEY.match(k)) and k not in asked_all]
    if bad:
        raise VehicleError("answer_invalid", f"답을 확인해 주세요: 없는 질문 키 {bad[0]!r}")

    answered = {**user, **{f: d["value"] for f, d in machine.items()}}
    left = [q for q in ans.remaining({"unknowns": qs}, answered) if not chapter.skipped(q, answered)]

    facts["unknowns"] = [dict(q, model_guess=va.to_mtm({q["field"]: q["model_guess"]}).get(q["field"], q["model_guess"]))
                         for q in qs]
    facts["judge_thresholds"] = judge_bridge.thresholds(judge_dir)
    mtm_left = [u for u in facts["unknowns"] if u["field"] in {q["field"] for q in left}]
    judge_facts, filled = ans.fill_guesses(facts, mtm_left, mtm_user)
    ch_fields = {q["field"] for q in chapter.ped_questions() + chapter.bike_questions()}
    judge_facts, ch_filled = chapter.fill(judge_facts, ch, {q["field"]: q.get("model_guess") for q in left
                                                            if q["field"] in ch_fields})
    filled += [f for f in ch_filled if f not in filled]
    for f in ("scene.place", "scene.junction_type"):
        if f in asked and f not in decided:
            filled.append(f)
    road = judge_facts["road"]
    if road.get("road_width") is None and "road.wider_road" not in user and ch != chapter.CAR_PED:
        road["road_width"] = va.DEFAULT_ROAD_WIDTH
        if "road.wider_road" not in filled:
            filled.append("road.wider_road")
    # 여러 개 고르기 답은 MTM 변환(안 고른 보기 = 아니요)에서 빼고 multi가 바꿈 (고른 보기만 사용자 답)
    asm = multi.assumptions(facts, ans.to_assumptions(facts, multi.strip(mtm_user)), user, video_def)
    asm = chapter.avoidable_assumptions(chapter.add_assumptions(asm, ch, user), user)
    sources = {f: d["source"] for f, d in machine.items()}
    if vreq:
        sources["parties.ego.cls"] = "vehicle"
    new_conflicts, overruled = user_scene_wins(judge_facts, asm, video_def, conflicts)
    conflicts = conflicts + new_conflicts
    for f in overruled:                                # 판정에 안 쓴 영상 값은 answers에도 안 보임 (충돌에만)
        machine.pop(f, None)
    verdict = _judge(judge_facts, asm, sources, judge_dir)

    by_field = {q["field"]: q for q in qs}
    used = {"parties.ego.cls": {"value": vreq["vehicle_cls"] if vreq else "car",
                                "source": "vehicle" if vreq else "default"}}
    for f, d in machine.items():
        used[f] = {"value": d["value"], "source": d["source"]}
        if d["source"] == "vehicle" and (vehicle_def.get(f) or {}).get("rule"):
            used[f]["rule"] = vehicle_def[f]["rule"]
    for f in filled:
        if f in used:
            continue
        val = by_field[f]["model_guess"] if f in by_field else None
        if f == "road.wider_road" and val is None:
            val = va.DEFAULT_ROAD_WIDTH
        if f == "scene.place":
            val = place
        if f == "scene.junction_type":
            val = junction
        used[f] = {"value": val, "source": "default"}
    for f, v in user.items():
        used[f] = {"value": v, "source": "user"}
    _add_evidence(used, decided, all_q, by_field)
    for c in conflicts:
        if c["used"] and c["used"]["source"] == "user" and c["field"] in used:   # 장면 값 충돌은 답 키가 달라 그대로
            c["evidence"] = used[c["field"]]["evidence"]
    answer_conflicts = [{"field": c["field"], "vehicle_value": o["value"], "user_value": c["used"]["value"],
                         "evidence": o["evidence"]}
                        for c in conflicts if c["used"] and c["used"]["source"] == "user"
                        for o in c["others"] if o["source"] == "vehicle"]

    status = "needs_answers" if any(not q.get("optional") for q in left) else "done"
    judged_ch = verdict["result"].get("accident_category") or ch   # 판정 엔진이 고른 장 (판정 못 하면 질문 장)
    col = bb["facts"]["collision"]
    view = {
        "status": status,
        "event": {"t_event": sync["t_collision_ms"], "t_event_source": "video", "collision_t": col.get("t"),
                  "collision_frame": col.get("frame"), "range": vreq["range"] if vreq else None},
        "data_quality": _data_quality(tl, vreq, sync, conflicts),
        "parties": {EGO: {"label": "내 차", "cls": used["parties.ego.cls"]["value"]},
                    OTHER: {"label": "상대", "cls": other_cls}},
        "other_cls": chapter.cls_view(decided, guesses, cls_info, judged_ch),
        "auto_answers": [rules.auto_answer(r) for r in results if r["determined"] and r["field"] in auto_fields
                         and decided.get(r["field"], {}).get("source") == "vehicle"],
        "answers": used,
        "answer_conflicts": answer_conflicts,
        "source_conflicts": conflicts,
        "questions": left,
        "remaining": remaining(left),
        "remaining_count": len(remaining(left)),
        "answered": answered_questions(all_q, user),
        "result": _result(verdict, status == "needs_answers", used, filled, judged_ch, user),
        "judge_version": verdict["judge_version"],
    }
    return {"view": view, "rule_results": results, "rules": sorted({r["rule"] for r in results}),
            "judge_version": verdict["judge_version"], "results": results}


def answered_questions(all_q, user):
    """사용자가 답한 질문의 정의 (답변 고치기 화면). remaining과 같은 모양 + optional + 지금 답(value).
    선택 질문(특수 상황·운전자 요인·과속 인과관계, optional)도 넣는다 (2026-11-12): 그때는 questions[] 한 줄과 같은 칸 전부
    (여러 개 고르기의 option_groups·more_options 등). 지금 장에 없는 질문과 조건(skip_when·when_any)으로 빠지게 된 질문은 뺌"""
    out = []
    for f, v in user.items():
        q = all_q.get(f)
        if q is None or chapter.skipped(q, user):
            continue
        if q.get("optional"):
            item = copy.deepcopy(q)
        else:
            item = {k: copy.deepcopy(q.get(k)) for k in REMAINING_KEYS}
        item["optional"] = bool(q.get("optional"))
        g = q.get("model_guess")
        item["guess_choice"] = evidence._choice(q, g) if g not in (None, []) else None
        item["value"] = v
        item["value_choice"] = evidence._choice(q, v)
        out.append(item)
    return out
