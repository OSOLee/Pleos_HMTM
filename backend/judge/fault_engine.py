"""과실비율 규칙 엔진

rules.json(도표) + modifiers.json(수정요소 사전) + facts(엔진 형식) -> 판정 결과

근거
- 자동차사고 과실비율 인정기준 제2편 총설 4. 과실비율 인정기준의 적용 (p.20~21)
- 제3편 제2장 3. 수정요소의 해설 (p.128~146)
"""
import itertools
import json
import math
import operator
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).parent
RULES_PATH = BASE_DIR / "rules.json"
CATALOG_PATH = BASE_DIR / "modifiers.json"

# 사고 유형별 규칙 파일. 수정요소는 공통 사전(modifiers.json)에 유형별 추가 사전을 합쳐 쓴다
CATEGORIES = {
    "car_car": {"label": "차대차(이륜차 포함)", "rules": "rules.json", "extra_modifiers": None},
    "car_pedestrian": {"label": "차대보행자", "rules": "rules_pedestrian.json",
                       "extra_modifiers": "modifiers_pedestrian.json"},
    "car_bicycle": {"label": "차대자전거(농기계 포함)", "rules": "rules_bicycle.json",
                    "extra_modifiers": "modifiers_bicycle.json"},
}
PEDESTRIAN_CLS = {"person"}
BICYCLE_CLS = {"bicycle", "farm_machine"}
VERSION = (BASE_DIR / "VERSION").read_text(encoding="utf-8").strip() if (BASE_DIR / "VERSION").exists() else "unknown"

OPS = {
    ">=": operator.ge, "<=": operator.le, ">": operator.gt, "<": operator.lt,
    "==": operator.eq, "!=": operator.ne,
    "in": lambda a, b: a in b,
    "contains": lambda a, b: isinstance(a, (list, tuple, set)) and b in a,
}

# 방위 기준: 기준 차량의 진입 방향(entry_from) -> 그 차량 오른쪽에서 진입하는 차량의 entry_from
RIGHT_OF = {"south": "east", "east": "north", "north": "west", "west": "south"}
LEFT_OF = {v: k for k, v in RIGHT_OF.items()}
OPPOSITE = {"south": "north", "north": "south", "east": "west", "west": "east"}
RELATIONS = {"enters_from_right_of", "enters_from_left_of", "enters_from_opposite_of", "enters_from_side_of",
             "enters_same_direction_as"}
REL_COS = 0.5  # 진행 방향 벡터로 좌우를 판단할 때 허용 각도 (cos 60도)

DISCLAIMER = ("참고용이며 법적 판단이나 보험사의 공식 결정이 아닙니다. "
              "부상자에 대한 과실상계(인적 손해 별도적용기준)는 반영하지 않았습니다.")


# ---------------------------------------------------------------- 파일 읽기
def load_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def load_rules(path=RULES_PATH):
    return load_json(path)


def load_catalog(path=CATALOG_PATH):
    return load_json(path)


def detect_category(facts):
    """충돌 당사자의 차종으로 사고 유형을 정한다. (유형, 판단 근거) 반환

    - facts에 accident_category가 있으면 그 값을 쓴다 (테스트, 이후 확장용)
    - 당사자에 사람이 있으면 차대보행자, 자전거·농기계가 있으면 차대자전거
    - 차종을 모르면 기존 동작과 같게 차대차로 본다
    """
    given = facts.get("accident_category")
    if given:
        return given, "facts.accident_category"
    involved = {str(x) for x in (facts.get("collision") or {}).get("between", [])}
    classes = [v.get("cls") for v in facts.get("vehicles", []) if str(v.get("track_id")) in involved]
    if any(c in PEDESTRIAN_CLS for c in classes):
        if any(c in BICYCLE_CLS for c in classes):
            return None, "자전거와 보행자 사이의 사고는 인정기준의 자동차 사고 도표 범위 밖"
        return "car_pedestrian", "충돌 당사자에 보행자(person)가 있음"
    if any(c in BICYCLE_CLS for c in classes):
        return "car_bicycle", "충돌 당사자에 자전거·농기계가 있음"
    if not classes or any(c is None for c in classes):
        return "car_car", "차종 정보가 없어 차대차로 판정"
    return "car_car", "충돌 당사자가 모두 자동차·이륜차"


def load_category(category):
    """사고 유형의 (규칙 문서, 수정요소 사전). 아직 매핑하지 않은 유형이면 규칙 문서가 None"""
    spec = CATEGORIES[category]
    path = BASE_DIR / spec["rules"]
    rules_doc = load_json(path) if path.exists() else None
    catalog = load_catalog()
    extra = spec.get("extra_modifiers")
    if extra and (BASE_DIR / extra).exists():
        add = load_json(BASE_DIR / extra)
        catalog = {**catalog,
                   "categories": {**catalog.get("categories", {}), **add.get("categories", {})},
                   "exclusive_groups": catalog.get("exclusive_groups", []) + add.get("exclusive_groups", []),
                   "modifiers": catalog["modifiers"] + add.get("modifiers", [])}
    return rules_doc, catalog


# ---------------------------------------------------------------- 조건 판단
def get_path(data, path):
    for key in path.split("."):
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def threshold_ref(value):
    if isinstance(value, str) and value.startswith("$"):
        return value[1:]
    return None


def resolve(value, thresholds):
    name = threshold_ref(value)
    return thresholds[name]["value"] if name else value


def check(cond, obj, thresholds):
    """True / False / None(값이 없어 판단 불가). {"any": [...]}, {"all": [...]} 중첩 지원"""
    if "any" in cond:
        rs = [check(c, obj, thresholds) for c in cond["any"]]
        return True if any(r is True for r in rs) else (False if all(r is False for r in rs) else None)
    if "all" in cond:
        return all_status([check(c, obj, thresholds) for c in cond["all"]])
    v = get_path(obj, cond["fact"])
    if v is None:
        return None
    return bool(OPS[cond["op"]](v, resolve(cond["value"], thresholds)))


def all_status(results):
    if any(r is False for r in results):
        return False
    if any(r is None for r in results):
        return None
    return True


def _unit(vec):
    if not vec or len(vec) != 2:
        return None
    n = math.hypot(vec[0], vec[1])
    return (vec[0] / n, vec[1] / n) if n > 0 else None


def relation(kind, v, ref):
    """v가 ref의 오른쪽(왼쪽)에서 진입했는가. 방위 정보가 있으면 방위로, 없으면 진행 방향 벡터로 판단"""
    if kind not in RELATIONS:
        raise ValueError(f"지원하지 않는 relation: {kind}")
    a, b = v.get("entry_from"), ref.get("entry_from")
    if a is not None and b is not None:
        if kind == "enters_from_right_of":
            return RIGHT_OF.get(b) == a
        if kind == "enters_from_left_of":
            return LEFT_OF.get(b) == a
        if kind == "enters_from_opposite_of":
            return OPPOSITE.get(b) == a
        if kind == "enters_same_direction_as":
            return a == b
        return a in (RIGHT_OF.get(b), LEFT_OF.get(b))
    # 진입 전 진행 방향(heading_start) 벡터로 판단. 회전 차량도 회전 전 방향을 쓴다
    hv, hr = _unit(v.get("heading")), _unit(ref.get("heading"))
    if hv is None or hr is None:
        return None
    left = (hr[1], -hr[0])  # 화면 좌표(y가 아래로 증가) 기준 ref 진행 방향의 왼쪽
    d_left = hv[0] * left[0] + hv[1] * left[1]
    d_same = hv[0] * hr[0] + hv[1] * hr[1]
    if kind == "enters_from_right_of":   # 오른쪽에서 와서 왼쪽으로 진행
        return d_left >= REL_COS
    if kind == "enters_from_left_of":
        return d_left <= -REL_COS
    if kind == "enters_from_opposite_of":  # 마주 보며 진행
        return d_same <= -REL_COS
    if kind == "enters_same_direction_as":  # 같은 방향으로 나란히 진행 (차11 노면표시 사고)
        return d_same >= REL_COS
    return abs(d_left) >= REL_COS          # 측면 (좌우 어느 쪽이든)


# ---------------------------------------------------------------- 도표 선택
def bind_roles(spec, facts, thresholds):
    """충돌 당사자 차량을 역할(A, B)에 배정. (배정, 상태) 반환"""
    names = list(spec)
    involved = [str(x) for x in (facts.get("collision") or {}).get("between", [])]
    cands = [v for v in facts.get("vehicles", []) if str(v.get("track_id")) in involved]
    unknown = None
    for perm in itertools.permutations(cands, len(names)):
        bound = dict(zip(names, perm))
        results = []
        for name, v in bound.items():
            results += [check(c, v, thresholds) for c in spec[name].get("where", [])]
            for rel in spec[name].get("relations", []):
                results.append(relation(rel["type"], v, bound[rel["of"]]))
        status = all_status(results)
        if status is True:
            return bound, True
        if status is None and unknown is None:
            unknown = bound
    return (unknown, None) if unknown is not None else (None, False)


def match_rule(rule, facts, thresholds):
    conds = rule["applies_when"].get("scene", [])
    scene = [check(c, facts, thresholds) for c in conds]
    missing = [c.get("fact") or "/".join(x["fact"] for x in c.get("any", c.get("all", [])))
               for c, r in zip(conds, scene) if r is None]
    if all_status(scene) is False:
        return False, None, missing
    bound, bstatus = bind_roles(rule["applies_when"]["roles"], facts, thresholds)
    if bstatus is None:
        missing.append("roles(역할 배정에 필요한 차량 사실값)")
    status = all_status(scene + [bstatus])
    cautions = []
    if status is True:
        # 활용시 참고 사항의 "이 기준을 적용하지 않는 경우". 확인되면 제외, 모르면 주의 문구
        for x in rule.get("exclude_if", []):
            r = check(x, bound[x["role"]], thresholds)
            if r is True:
                return False, None, [x["reason"]]
            if r is None:
                cautions.append(f"확인 필요: {x['reason']}")
    rule["_cautions"] = cautions
    return status, bound, missing


def specificity(rule):
    w = rule["applies_when"]
    n = len(w.get("scene", []))
    for r in w["roles"].values():
        n += len(r.get("where", [])) + len(r.get("relations", []))
    return n


# ---------------------------------------------------------------- 수정요소
def expand_modifiers(rule, rules_doc, catalog, roles):
    """도표의 수정요소와 공통(global) 수정요소를 (차량, 사전 항목) 단위로 펼친다"""
    by_id = {m["id"]: m for m in catalog["modifiers"]}
    entries = list(rule.get("modifiers", []))
    skip = set(rule.get("exclude_global", []))
    entries += [g for g in rules_doc.get("global_modifiers", []) if g["ref"] not in skip]
    out = []
    for e in entries:
        ref = e["ref"]
        if ref.startswith("category:"):
            defs = [m for m in catalog["modifiers"] if m["category"] == ref.split(":", 1)[1]]
        else:
            if ref not in by_id:
                raise ValueError(f"modifiers.json에 없는 수정요소: {ref}")
            defs = [by_id[ref]]
        parties = list(roles) if e.get("party") == "each" else [e["party"]]
        for d in defs:
            for p in parties:
                out.append({
                    "key": f"{p}:{d['id']}",
                    "ref": d["id"],
                    "party": p,
                    "category": d["category"],
                    "label": f"{p} {e.get('label') or d['label']}",
                    "delta": e.get("delta", d.get("default_delta")),
                    "if": e.get("if", []),
                    "def": d,
                })
    return out


def _subject(cond, party, bound, facts):
    of = cond.get("of", "self")
    if of == "self":
        return bound[party]
    if of == "other":
        return bound[next(r for r in bound if r != party)]
    if of == "facts":
        return facts
    return bound[of]


def _eval(conds, party, bound, facts, thresholds):
    results, observed, placeholders, sources = [], {}, [], set()
    for c in conds:
        subj = _subject(c, party, bound, facts)
        results.append(check(c, subj, thresholds))
        of = c.get("of", "self")
        observed[c["fact"] if of == "self" else f"{of}.{c['fact']}"] = get_path(subj, c["fact"])
        t = threshold_ref(c["value"])
        if t and thresholds.get(t, {}).get("status") == "placeholder":
            placeholders.append(t)
        src = (subj.get("_sources") or {}).get(c["fact"]) if isinstance(subj, dict) else None
        if src:
            sources.add(src)
    return all_status(results), results, observed, placeholders, sources


def evaluate(cand, bound, facts, thresholds):
    """수정요소 하나의 상태: applied / pending / unverifiable / not_applied / no"""
    d = cand["def"]
    p = cand["party"]
    conds = d["when"]["all"] + cand.get("if", [])  # 도표가 붙인 추가 조건 (예: 전방 신호가 적색일 때만)
    r, results, observed, placeholders, sources = _eval(conds, p, bound, facts, thresholds)
    cand["observed"] = observed

    if r is None and d.get("when_fallback"):  # 실속도가 없을 때 임시 기준으로 판단
        r, results, observed, placeholders, sources = _eval(
            d["when_fallback"]["all"], p, bound, facts, thresholds)
        cand["observed"] = observed
    if r is None:
        cand["status"] = "unverifiable"
        cand["missing"] = [c["fact"] for c, x in zip(conds, results) if x is None]
        return cand
    if r is False:
        cand["status"] = "no"
        return cand

    if d.get("delta_by"):
        db = d["delta_by"]
        cand["delta"] = db["map"].get(get_path(bound[p], db["fact"]))
        if cand["delta"] is None:
            cand["status"] = "no"
            return cand

    if d.get("causal"):  # 위반이 있어도 사고와 인과관계가 있어야 적용 (총설 p.18~19)
        cr, _, cobs, _, _ = _eval(d["causal"]["all"], p, bound, facts, thresholds)
        cand["observed"].update(cobs)
        if cr is False:
            cand["status"] = "not_applied"
            cand["reason"] = "위반은 있으나 사고와 인과관계 없음"
            return cand
        if cr is None:
            cand["status"] = "pending"
            cand["reason"] = "인과관계 확인 필요 (제한속도였다면 피할 수 있었는지)"
            cand["would_apply"] = True
            return cand

    if placeholders:
        cand["status"] = "pending"
        cand["reason"] = "임시 기준으로만 판단 가능 (속도 보정 필요)"
        cand["would_apply"] = True
        return cand

    cand["status"] = "applied"
    cand["needs_proof"] = "user" in sources  # 사용자 입력값으로 적용 → 입증 필요 (총설 p.20 ②)
    return cand


def resolve_overlaps(applied, catalog):
    """중복 적용 규칙 (총설 p.21 ③~⑥, 수정요소 해설 p.135, 144~146)"""
    excluded = []
    cap = catalog["categories"]["notable"].get("cap_per_party", 20)
    groups = catalog.get("exclusive_groups", [])
    by_party = defaultdict(list)
    for c in applied:
        by_party[c["party"]].append(c)

    keep_all = []
    for party, lst in by_party.items():
        drop = set()
        # 1) 같은 그룹(서행·감속 불이행 vs 속도위반)은 하나만: 가장 큰 것
        for g in groups:
            members = [c for c in lst if c["ref"] in g["members"]]
            if len(members) > 1:
                best = max(members, key=lambda c: abs(c["delta"]))
                for c in members:
                    if c is not best:
                        drop.add(c["key"])
                        excluded.append({**_brief(c), "reason": g["note"]})
        has_grave = any(c["category"] == "grave" and c["key"] not in drop for c in lst)
        for c in lst:
            if c["key"] in drop:
                continue
            # 2) 중대한 과실이 있으면 현저한 과실은 제외
            if c["category"] == "notable" and has_grave:
                drop.add(c["key"])
                excluded.append({**_brief(c), "reason": "중대한 과실과 겹치면 중대한 과실만 적용 (총설 p.21 ④)"})
            # 3) 특정 분류가 있으면 적용하지 않는 요소 (예: 이륜차가 중대한 과실이면 이륜차 감산 없음)
            elif c["def"].get("unless_party_has") and any(
                    o["category"] in c["def"]["unless_party_has"] and o["key"] not in drop for o in lst):
                drop.add(c["key"])
                excluded.append({**_brief(c), "reason": "해당 차량에 중대한 과실이 있어 비적용 (p.144)"})
        # 4) 현저한 과실 합계 상한 20%
        total = 0
        for c in lst:
            if c["key"] in drop or c["category"] != "notable":
                continue
            room = cap - total
            if room <= 0:
                drop.add(c["key"])
                excluded.append({**_brief(c), "reason": f"현저한 과실 합계 상한 {cap}% 초과 (총설 p.21 ⑤)"})
                continue
            if c["delta"] > room:
                c["note"] = f"현저한 과실 상한 {cap}%로 {c['delta']}%p 중 {room}%p만 반영"
                c["delta"] = room
            total += c["delta"]
        keep_all += [c for c in lst if c["key"] not in drop]
    order = {c["key"]: i for i, c in enumerate(applied)}
    keep_all.sort(key=lambda c: order[c["key"]])
    return keep_all, excluded


def _brief(c):
    return {"id": c["key"], "label": c["label"], "party": c["party"],
            "category": c["category"], "delta": c["delta"], "observed": c.get("observed")}


def _apply(fault, party, delta):
    """한쪽에 더한 만큼 상대에서 빼서 합계 100 유지, 0~100 범위. 실제 적용량 반환 (총설 p.21 ②③)"""
    other = next(p for p in fault if p != party)
    new = max(0, min(100, fault[party] + delta))
    real = new - fault[party]
    fault[party] = new
    fault[other] -= real
    return real


# ---------------------------------------------------------------- 판정
def judge(facts, rules_doc=None, catalog=None):
    """rules_doc을 넘기지 않으면 사고 유형을 판단해 해당 유형의 규칙 파일을 쓴다"""
    category, category_reason = None, None
    if rules_doc is None:
        category, category_reason = detect_category(facts)
        if category is None:
            return {"supported": False, "engine_version": VERSION, "video": facts.get("video"),
                    "accident_category": None, "message": category_reason, "undetermined_rules": []}
        if category not in CATEGORIES:
            return {"supported": False, "engine_version": VERSION, "video": facts.get("video"),
                    "accident_category": category,
                    "message": f"알 수 없는 사고 유형: {category}", "undetermined_rules": []}
        rules_doc, cat_catalog = load_category(category)
        catalog = catalog or cat_catalog
        if rules_doc is None or not rules_doc.get("rules"):
            return {"supported": False, "engine_version": VERSION, "video": facts.get("video"),
                    "accident_category": category, "accident_category_reason": category_reason,
                    "message": f"{CATEGORIES[category]['label']} 사고 도표가 아직 매핑되지 않았습니다.",
                    "undetermined_rules": []}
    catalog = catalog or load_catalog()
    thresholds = rules_doc.get("thresholds", {})

    matched, undetermined = [], []
    for rule in rules_doc["rules"]:
        status, bound, missing = match_rule(rule, facts, thresholds)
        if status is True:
            matched.append((rule, bound))
        elif status is None:
            undetermined.append({"rule_id": rule["id"], "missing": missing})
    if not matched:
        return {"supported": False, "engine_version": VERSION, "video": facts.get("video"),
                "accident_category": category or rules_doc.get("category"),
                "message": "조건에 맞는 규칙이 없습니다.",
                "undetermined_rules": undetermined}

    # 특수 도표(긴급자동차, 문 열림 등)는 priority로 일반 도표보다 먼저, 같으면 조건이 많은 도표
    rule, bound = max(matched, key=lambda x: (x[0].get("priority", 0), specificity(x[0])))
    cands = [evaluate(c, bound, facts, thresholds)
             for c in expand_modifiers(rule, rules_doc, catalog, list(bound))]

    applied = [c for c in cands if c["status"] == "applied"]
    pending = [c for c in cands if c["status"] == "pending"]
    unverifiable = [c for c in cands if c["status"] == "unverifiable"]
    not_applied = [{**_brief(c), "reason": c["reason"]} for c in cands if c["status"] == "not_applied"]

    applied, excluded = resolve_overlaps(applied, catalog)

    fault = dict(rule["base"])
    steps = [{"step": "base", "source": rule["source"]["ref"], "fault": dict(fault)}]
    notes = []

    # 기본 비율에 0인 쪽이 있으면 그쪽 수정요소를 먼저, 상대가 100% 미만일 때만 상대 수정요소 적용 (총설 p.21 ②)
    zero = [p for p, v in rule["base"].items() if v == 0]
    if zero:
        z = zero[0]
        applied = [c for c in applied if c["party"] == z] + [c for c in applied if c["party"] != z]
    done = []
    for c in applied:
        if zero and c["party"] != zero[0]:
            other = c["party"]
            if fault[other] >= 100:
                excluded.append({**_brief(c), "reason": "기본 0:100에서 0인 쪽 수정요소 적용 후에도 상대가 100%라 미적용 (총설 p.21 ②)"})
                continue
        real = _apply(fault, c["party"], c["delta"])
        item = {**_brief(c), "delta": real, "needs_proof": c.get("needs_proof", False)}
        if c.get("note"):
            item["note"] = c["note"]
        done.append(item)
        steps.append({"step": "modifier", "id": c["key"], "label": c["label"],
                      "delta": real, "fault": dict(fault), **({"note": c["note"]} if c.get("note") else {})})

    # 보정 대기 요소까지 넣은 참고 비율. 이미 적용된 요소와 같은 중복 금지 그룹이면 넣지 않음
    group_of = {m: g["id"] for g in catalog.get("exclusive_groups", []) for m in g["members"]}
    used = {(c["party"], group_of[c["id"].split(":", 1)[1]]) for c in done
            if c["id"].split(":", 1)[1] in group_of}
    fault_if_pending = dict(fault)
    for c in pending:
        if (c["party"], group_of.get(c["ref"])) in used:
            c["reason"] += " (이미 적용된 속도위반과 중복되어 참고 비율에서 제외)"
            continue
        if c.get("would_apply") and c.get("delta") is not None:
            _apply(fault_if_pending, c["party"], c["delta"])

    if any(c["needs_proof"] for c in done):
        notes.append("사용자 입력으로 적용된 수정요소는 입증 자료가 있어야 인정됩니다.")

    spec = rule["applies_when"]["roles"]
    by_track = lambda f: {str(bound[n]["track_id"]): f[n] for n in bound}
    return {
        "schema_version": "2.0",
        "engine_version": VERSION,
        "rules_version": rules_doc.get("schema_version"),
        "video": facts.get("video"),
        "accident_category": category or rules_doc.get("category"),
        **({"accident_category_reason": category_reason} if category_reason else {}),
        "supported": True,
        "rule_id": rule["id"],
        "title": rule["title"],
        "source": rule["source"],
        "roles": {n: {"track_id": str(v["track_id"]), "label": spec[n]["label"], "cls": v.get("cls")}
                  for n, v in bound.items()},
        "base": rule["base"],
        "fault": fault,
        "fault_by_track": by_track(fault),
        "calculation": steps,
        "applied_modifiers": done,
        "excluded_modifiers": excluded,
        "not_applied_modifiers": not_applied,
        "pending_calibration": [{**_brief(c), "reason": c["reason"], "would_apply": c.get("would_apply")}
                                for c in pending],
        "fault_if_pending_applied": fault_if_pending,
        "fault_if_pending_by_track": by_track(fault_if_pending),
        "unverifiable_factors": [{**_brief(c), "missing": c.get("missing", []),
                                  "detect": c["def"]["detect"], "question": c["def"].get("question")}
                                 for c in unverifiable],
        "notes": notes + rule.get("_cautions", []),
        "table_notes": rule.get("notes", []),
        "table_not_applicable": rule.get("not_applicable", []),
        "basis": rule.get("basis"),
        "legal_refs": rule.get("legal_refs", []),
        "evidence": {"collision": facts.get("collision"), "events": facts.get("events", [])},
        "disclaimer": DISCLAIMER,
    }
