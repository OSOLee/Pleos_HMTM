"""기획서 8절 평가 지표를 한 번에 재서 마크다운 표로 낸다 (중간 점검·발표용)

  cd ~/MTM && .venv/bin/python tools/evaluate/metrics.py                          # 답 반영(outputs/eval_tap) + 자동(outputs/eval_auto)
  cd ~/MTM && .venv/bin/python tools/evaluate/metrics.py --tap <폴더> --auto <폴더> > outputs/지표.md

결과 폴더마다 <영상>/app.json이 있어야 함 (run_app.py). 정답은 outputs/gt_cc/<영상>.json (src/dataset/aihub.py).

| 지표 | 어떻게 잼 |
|---|---|
| 판정 나옴 | 도표가 골라져 비율이 나온 영상 비율 ("해당 규칙 없음"·충돌 못 찾음 제외) |
| 당사자 식별 | 고른 충돌 쌍이 라벨 A·B와 맞는지 (results_table.assign, 같은 차의 조각 궤적도 인정) |
| 비율 정확히 일치 / 허용 일치 | 정답 비율과 같음 / 같은 사고 복사본 라벨 중 하나와 같음 |
| 비율 오차 (MAE) | 판정이 나오고 당사자가 맞은 영상에서 \\|예측 A 과실 − 정답 A 과실\\| 평균 (%p). 10%p 안 비율도 같이 |
| 질문 수 | 영상당 남은 질문 (꼭 답할 것 / 선택) |
| 일관성 | tools/evaluate/consistency.py 결과(outputs/일관성.md) 마지막 줄 |
| 영상 종류 판단 | tools/data/camera_survey.py 결과(outputs/camera_survey.json): 블랙박스를 CCTV로 받은 비율 등 |

| 사고 유형 (기본 비율) | 고른 도표의 기본 비율(+ 삼거리 T자 회전 가산)이 라벨 사고 유형의 기본 비율과 같은지 (유형 번호 ↔ 도표 대응표는 없어서
|  | 기본 비율로 대신 봄. data/aihub/type_codes.json, tools/data/type_codes.py) |
| 진행 방향 | 영상에서 잰 진행 방향(facts.json)이 사고 유형 표의 A·B 진행과 같은지 (답이 아니라 측정값) |

평가 세트는 여러 개를 이어서 볼 수 있음: --tap 폴더1 폴더2 --gt 정답1 정답2 (1차 24개 + 늘린 세트)
"""
import argparse
import glob
import json
import os
import sys
from statistics import mean

sys.path.insert(0, os.getcwd())
from src.dataset.aihub import rates
from src.eval.match_parties import align_gt, match
from tools.evaluate.gt_answer import type_codes
from tools.evaluate.results_table import ALLOWED, assign

NOT_JUDGED = ("no_collision", "cannot_analyze", "unsupported")


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


CODES = type_codes()


def case_row(gt_path, roots):
    """영상 하나: 당사자, 판정 여부, 비율 오차, 기본 비율, 진행 방향, 질문 수. 결과 폴더가 없으면 None"""
    name = os.path.basename(gt_path)[:-5]
    d = next((os.path.join(r, name) for r in roots if os.path.exists(os.path.join(r, name, "app.json"))), None)
    if d is None:
        return None
    gt, app = load(gt_path), load(os.path.join(d, "app.json"))
    ra, rb = rates(gt["label"])
    rb = rb if rb is not None else 100 - ra
    tp = os.path.join(d, "tracks_final.json")
    tracks = load(tp)["tracks"] if os.path.exists(tp) else {}
    m = match(align_gt(gt, d), tracks)
    col = app.get("collision")
    pair = sorted([col["a"], col["b"]]) if col else None
    got = assign(pair, m) if pair and m["A"]["matched"] and m["B"]["matched"] else None
    fault = (app.get("verdict") or {}).get("fault_by_track") or {}
    judged = app["status"] not in NOT_JUDGED and bool(fault)
    err = exact = allowed = None
    if judged and got:
        pa = fault.get(got[0])
        if pa is not None:
            err = abs(pa - ra)
            exact = pa == ra and fault.get(got[1]) == rb
            allowed = exact or [pa, fault.get(got[1])] in ALLOWED.get(name, [])
    # 사고 유형: 도표 기본 비율(B result.base, 역할 A·B의 궤적) vs 라벨 유형의 기본 비율
    code = CODES.get(gt["label"].get("traffic_accident_type", gt["label"].get("accident_type")))
    base_ok = None
    rp = os.path.join(d, "result.json")
    if judged and got and code and os.path.exists(rp):
        r = load(rp).get("result") or {}
        roles = r.get("roles") or {}
        by_track = {str(roles.get(k, {}).get("track_id")): v for k, v in (r.get("base") or {}).items()}
        # AI Hub 유형 비율은 삼거리(T자) 회전 차량 가산(+10, 인정기준 차14·16 등의 수정요소 ②)을 이미 더한 값이라
        # (유형 107 = 차16-1 40:60 + 10 = 30:70) 그 수정요소가 붙었으면 기본 비율에 더해서 비교
        for m in r.get("applied_modifiers", []):
            if "삼거리(T자)" in (m.get("label") or "") and m.get("party") in roles:
                t = str(roles[m["party"]].get("track_id"))
                for k in by_track:
                    by_track[k] += m["delta"] if k == t else -m["delta"]
        if got[0] in by_track:
            base_ok = by_track[got[0]] == code["rate"][0]
    # 진행 방향: 영상에서 잰 값(facts.json, 답 반영 전)이 유형 표의 진행과 같은지
    moves = []
    fp = os.path.join(d, "facts.json")
    if got and code and os.path.exists(fp):
        parties = load(fp).get("parties") or {}
        for p, t in zip("AB", got):
            want, have = code[p].get("movement"), (parties.get(t) or {}).get("movement")
            if want and have not in (None, "unknown"):
                moves.append(want == have)
    qs = app.get("questions") or []
    return {"video": name, "party": bool(got), "judged": judged, "err": err, "exact": exact, "allowed": allowed,
            "base_ok": base_ok, "moves": moves,
            "required": sum(not q.get("optional") for q in qs), "optional": sum(bool(q.get("optional")) for q in qs)}


def pct(n, d):
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "-"


def summary(rows):
    n = len(rows)
    errs = [r["err"] for r in rows if r["err"] is not None]
    return {
        "영상 수": str(n),
        "판정 나옴": pct(sum(r["judged"] for r in rows), n),
        "당사자 식별": pct(sum(r["party"] for r in rows), n),
        "비율 정확히 일치": pct(sum(bool(r["exact"]) for r in rows), n),
        "비율 허용 일치 (복사본 라벨 포함)": pct(sum(bool(r["allowed"]) for r in rows), n),
        "비율 오차 MAE (판정·당사자 맞은 영상)": f"{mean(errs):.1f}%p (영상 {len(errs)}개)" if errs else "-",
        "오차 10%p 이내": pct(sum(e <= 10 for e in errs), len(errs)),
        "사고 유형 (도표 기본 비율 = 유형 기본 비율)": pct(sum(r["base_ok"] is True for r in rows),
                                                 sum(r["base_ok"] is not None for r in rows)),
        "진행 방향 (영상 측정, 당사자 수)": pct(sum(sum(r["moves"]) for r in rows), sum(len(r["moves"]) for r in rows)),
        "질문 수 (꼭 답할 것)": f"평균 {mean(r['required'] for r in rows):.1f}개" if rows else "-",
        "질문 수 (선택)": f"평균 {mean(r['optional'] for r in rows):.1f}개" if rows else "-",
    }


def last_line(path):
    if not os.path.exists(path):
        return "결과 없음"
    lines = [l.strip() for l in open(path, encoding="utf-8") if l.strip()]
    return lines[-1] if lines else "결과 없음"


def camera_summary(path="outputs/camera_survey.json"):
    """영상 종류 판단: 정답(truth: cc/bb)별로 앱이 어떻게 처리했는지"""
    if not os.path.exists(path):
        return "결과 없음"
    rows = load(path)
    cc = [r for r in rows if r.get("truth") == "cc"]
    bb = [r for r in rows if r.get("truth") == "bb"]
    cc_ok = sum("CCTV" in r.get("app", "") or "보정" in r.get("app", "") for r in cc)
    bb_in = sum("CCTV" in r.get("app", "") for r in bb)
    return (f"CCTV {len(cc)}개 중 분석함 {cc_ok}, 블랙박스 {len(bb)}개 중 CCTV로 받아들임 {bb_in} "
            f"(블랙박스는 사용자가 고르면 바로 안내, 이 값은 CCTV로 잘못 골랐을 때의 안전장치)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tap", nargs="+", default=["outputs/eval_tap"], help="정답 답을 반영한 결과 폴더(들)")
    ap.add_argument("--auto", nargs="+", default=["outputs/eval_auto"], help="답 없이 자동으로 낸 결과 폴더(들)")
    ap.add_argument("--gt", nargs="+", default=["outputs/gt_cc"], help="정답 라벨 폴더(들)")
    args = ap.parse_args()
    gts = sorted(p for g in args.gt for p in glob.glob(os.path.join(g, "*.json")))
    sets = {"답 반영": [r for g in gts if (r := case_row(g, args.tap))],
            "자동 (답 없음)": [r for g in gts if (r := case_row(g, args.auto))]}
    sums = {k: summary(v) for k, v in sets.items()}
    print("## 평가 지표\n")
    print("| 지표 | " + " | ".join(sums) + " |")
    print("|---|" + "---|" * len(sums))
    for key in next(iter(sums.values())):
        print(f"| {key} | " + " | ".join(s[key] for s in sums.values()) + " |")
    print(f"\n- 일관성 (같은 사고 다른 파일): {last_line('outputs/일관성.md')}")
    print(f"- 영상 종류 판단: {camera_summary()}")
    print("- 사고 유형은 유형 번호 ↔ 도표 대응표가 없어 기본 비율로 대신 봄 (같은 기본 비율의 다른 도표도 맞음으로 셈)")
    print("\n## 영상별 (답 반영)\n")
    print("| 영상 | 당사자 | 판정 | 비율 오차 | 기본 비율 | 질문 (꼭/선택) |\n|---|---|---|---|---|---|")
    yn = {True: "맞음", False: "다름", None: "-"}
    for r in sets["답 반영"]:
        err = "-" if r["err"] is None else f"{r['err']}%p" + (" (일치)" if r["exact"] else "")
        print(f"| {r['video'][5:11]} | {'맞음' if r['party'] else '틀림'} | {'나옴' if r['judged'] else '없음'} "
              f"| {err} | {yn[r['base_ok']]} | {r['required']} / {r['optional']} |")


if __name__ == "__main__":
    main()
