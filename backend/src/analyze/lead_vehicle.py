"""블랙박스 앞차(촬영 차 바로 앞 차) 찾기와 접근 속도 추정 (tracks.json + ego_motion.json → lead_vehicle.json)

  python src/analyze/lead_vehicle.py <결과 폴더>

앞차 = 화면 가운데 길(가로 LANE_X 안)에서 가장 가까운(상자 아래쪽이 가장 낮은) 차.
거리는 상자 너비로 본다: 같은 차는 가까워지면 상자가 커진다. 상자 너비가 커지는 빠르기로
"부딪치기까지 남은 시간"(TTC = 너비 / 너비 증가 속도)을 어림한다. 카메라 보정 없이 어림한 값이라
숫자 자체보다 "급격히 가까워졌나"를 보는 용도다.

프레임마다: lead(앞차 궤적 id), w(상자 너비, 화면 비율), ttc(초, 가까워지는 중일 때만)
요약: 충격 후보 프레임(ego_motion 요약의 jolt_frames 첫 값) 직전의 앞차 크기·TTC.
"""
import json
import os
import sys

import numpy as np

LANE_X = (0.28, 0.72)     # 앞차로 보는 상자 가운데의 가로 범위 (화면 비율)
MIN_W = 0.04              # 너무 작은(먼) 상자는 앞차로 안 봄
VEHICLES = ("car", "truck", "bus")
WIN = 5                   # 너비 증가 속도를 보는 창 (프레임)
NEAR_W = 0.35             # 상자 너비가 화면의 이 비율 이상이면 "코앞"
LOOK_BACK = 45            # 충격 전 이 프레임 수 안에서 TTC 최솟값을 봄


def load(p):
    with open(p, encoding="utf-8") as fp:
        return json.load(fp)


def run(out_dir):
    tr = load(os.path.join(out_dir, "tracks.json"))
    fps = tr.get("fps") or 30.0
    n = tr["frames_analyzed"]
    # 프레임별 후보: {frame: [(id, bbox)]}
    by = {}
    for tid, recs in tr["tracks"].items():
        for r in recs:
            if r["cls"] in VEHICLES and r["bbox"][2] >= MIN_W:
                cx = r["bbox"][0] + r["bbox"][2] / 2
                if LANE_X[0] <= cx <= LANE_X[1]:
                    by.setdefault(r["frame"], []).append((tid, r["bbox"]))
    lead = {}
    for f, cs in by.items():
        lead[f] = max(cs, key=lambda c: c[1][1] + c[1][3])   # 아래쪽이 가장 낮은 = 가장 가까운 차
    # 앞차 궤적의 너비 시계열
    width = {}
    for f, (tid, b) in lead.items():
        width.setdefault(tid, {})[f] = b[2]
    rows = []
    for f in range(n):
        row = {"frame": f, "lead": None, "w": None, "ttc": None}
        if f in lead:
            tid, b = lead[f]
            row["lead"], row["w"] = tid, round(b[2], 4)
            ws = width[tid]
            g = f - WIN
            if g in ws and ws[f] > ws[g]:
                dw = (ws[f] - ws[g]) / (WIN / fps)
                row["ttc"] = round(float(ws[f] / dw), 2)
        rows.append(row)

    jolts = []
    ep = os.path.join(out_dir, "ego_motion.json")
    if os.path.exists(ep):
        jolts = load(ep)["summary"]["jolt_frames"]
    impact = jolts[0] if jolts else None
    summary = {"impact_frame": impact, "lead_at_impact": None, "w_at_impact": None, "near": None, "min_ttc": None}
    if impact is not None:
        around = [r for r in rows if impact - 5 <= r["frame"] <= impact and r["lead"] is not None]
        if around:
            r = around[-1]
            summary.update(lead_at_impact=r["lead"], w_at_impact=r["w"], near=bool(r["w"] >= NEAR_W))
        ttcs = [r["ttc"] for r in rows if impact - LOOK_BACK <= r["frame"] <= impact and r["ttc"] is not None]
        if ttcs:
            summary["min_ttc"] = round(float(np.min(ttcs)), 2)
    out = {"params": {"lane_x": LANE_X, "min_w": MIN_W, "win": WIN, "near_w": NEAR_W}, "summary": summary, "frames": rows}
    with open(os.path.join(out_dir, "lead_vehicle.json"), "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False)
    return out


if __name__ == "__main__":
    s = run(sys.argv[1])["summary"]
    print(s)
