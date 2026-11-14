"""판정 모듈(B) 수정요소 중 A가 한 번도 못 채우는(그래서 절대 적용되지 않는) 것을 찾는다

  cd ~/MTM && .venv/bin/python tools/evaluate/modifier_audit.py

수정요소마다 조건에 쓰는 사실(fact)을 모으고, A가 넘길 수 있는 사실(facts.json 측정값 + 답에서 만드는 가정 +
특수 상황 보기 + B adapter가 계산하는 값)과 비교한다. 도표(rules.json)에서 쓰이는 수정요소만 본다.
11-02: 처음 돌렸을 때 101개 중 68개가 한 번도 적용될 수 없었음 (이륜차 감산, 방향지시등 등). docs/facts_plan.md 8절
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.getcwd())
from src.app import situation

JUDGE = os.environ.get("MTM_JUDGE_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "judge"))
# B adapter가 스스로 계산하거나 A가 늘 넘기는 값 (facts.json 예전 결과에 없을 수 있어서 직접 적음)
ALWAYS = {"cls", "movement", "user_factors", "speed_over_limit_kmh", "entry_lead_sec", "entry_speed_ratio",
          "slowed_before_entry", "lead_order", "side_in_pair", "on_wider_road", "stop_sign", "u_turn_timing",
          "driving_left_side", "overtaking", "stationary_at_collision", "damage_severity",
          "scene.junction_type", "scene.location", "scene.road_type", "scene.night", "scene.low_visibility"}


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def facts_in(w, out):
    if isinstance(w, dict):
        if "fact" in w:
            out.add(w["fact"])
        for v in w.values():
            facts_in(v, out)
    elif isinstance(w, list):
        for v in w:
            facts_in(v, out)
    return out


def used_modifiers(mods, rules):
    """{수정요소 id: 쓰는 도표 수}. 도표의 ref는 id 또는 category:<분류>"""
    by_cat = {}
    for m in mods:
        by_cat.setdefault(m.get("category"), []).append(m["id"])
    used = {}
    refs = [(r.get("id"), x) for r in rules["rules"] for x in r.get("modifiers") or []]
    refs += [("global", x) for x in rules.get("global_modifiers") or []]
    for rid, x in refs:
        ref = x.get("ref", "")
        ids = by_cat.get(ref.split(":", 1)[1], []) if ref.startswith("category:") else [ref]
        for i in ids:
            used.setdefault(i, set()).add(rid)
    return {i: len(r) for i, r in used.items()}


def producible():
    """A가 넘길 수 있는 사실 이름"""
    out = set(ALWAYS)
    for p in glob.glob("outputs/eval_auto/*/facts.json") + glob.glob("outputs/eval_signal_auto/*/facts.json"):
        f = load(p)
        for v in f["parties"].values():
            out |= set(v)
        out |= {"scene." + k for k in (f.get("road") or {})}
    src = "".join(open(p, encoding="utf-8").read() for p in ("src/app/answers.py", "src/app/situation.py"))
    out |= set(re.findall(r'party\([^)]*\)\["(\w+)"\]', src))
    out |= {"scene." + k for k in re.findall(r'asm\["scene"\]\["(\w+)"\]', src)}
    for group in re.findall(r'elif key in \(([^)]*)\)', src):   # 답을 그대로 당사자 사실로 넘기는 질문들
        out |= set(re.findall(r'"(\w+)"', group))
    out |= {f for _, f, _, _ in situation.SPECIAL if f and not f.startswith("movement=")}
    out |= {"scene." + f for _, f, _, _, _ in situation.SPECIAL_SCENE}
    out |= set(situation.PARKING_FACTS.values())
    return out


def main():
    mods = load(os.path.join(JUDGE, "modifiers.json"))
    mods = mods["modifiers"] if isinstance(mods, dict) else mods
    used = used_modifiers(mods, load(os.path.join(JUDGE, "rules.json")))
    have = producible()
    rows = []
    for m in mods:
        if m["id"] not in used:
            continue
        need = facts_in(m.get("when"), set()) | ({m["delta_by"]["fact"]} if m.get("delta_by") else set())
        lack = sorted(n for n in need if n not in have and n.split(".")[-1] not in have)
        if lack:
            rows.append((m.get("default_delta"), m["id"], m.get("label"), lack, used[m["id"]]))
    print(f"도표에서 쓰는 수정요소 {len(used)}개 중 A가 못 채우는 것 {len(rows)}개\n")
    print("| 가감 | id | 이름 | 필요한 사실 | 쓰는 도표 수 |\n|---|---|---|---|---|")
    for d, i, lab, lack, n in sorted(rows, key=lambda r: (-r[4], r[1])):
        print(f"| {d} | {i} | {lab} | {', '.join(lack)} | {n} |")


if __name__ == "__main__":
    main()
