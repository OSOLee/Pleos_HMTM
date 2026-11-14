# MTM(OSOLee/MTM) feature/server의 src/analyze/bb_partner.py 복사본. import만 video_lib로 바꿈 (docs/origin.md). MTM 쪽을 고친 뒤 다시 복사한다.
"""블랙박스 사고 순간과 사고 상대 차 고르기 (tracks.json + ego_motion.json → bb_partner.json)

  python src/analyze/bb_partner.py <결과 폴더>

1) 충격 프레임: 촬영 차가 달리다 멈추는 순간 근처의 화면 흔들림(충격 후보)을 쓴다.
   - 흔들림 후보(ego_motion의 jolt_frames)가 있으면, 달림→멈춤 경계(가장 마지막) 근처의 것을 고른다
   - 흔들림이 없으면 달림→멈춤 경계 자체를 쓴다
   - 처음부터 끝까지 안 달렸으면(정차 중 사고) 충격 프레임을 모른다 (None)
   - 사용자가 사고 순간을 골랐으면(run의 collision_t, 초) 자동으로 찾지 않고 그 시각의 프레임을 충격 프레임으로 쓴다 (근거 "user_pick")
2) 사고 상대: 충격 프레임 직전 WINDOW 프레임 안에서 상자가 가장 많이 커진(= 가장 크게 다가온) 차.
   (그냥 가장 큰 차를 고르면 옆 차로에 나란히 있던 가까운 차가 뽑혀서, 커진 정도를 본다. 17개 영상 검증: 10 → 13개 맞음)
   화면 어디든 본다 (옆에서 오는 차도 포함). 어느 쪽(왼쪽·가운데·오른쪽)에서 가장 커졌는지를 side로 남긴다.
   뒤에서 받힌 경우는 화면에 안 보이므로 상대가 없거나 엉뚱한 차가 골라질 수 있다 (confidence가 낮음).
"""
import json
import os
import sys

VEHICLES = ("car", "truck", "bus", "motorcycle")
WINDOW = (-30, 2)          # 충격 프레임 기준으로 상대 차를 찾는 범위 (프레임)
MIN_DETS = 2               # 이 범위에서 최소 탐지 수
JOLT_NEAR = 35             # 달림→멈춤 경계에서 이 프레임 안의 흔들림만 충격으로 인정
SIDE_LEFT, SIDE_RIGHT = 0.36, 0.64
PICK_SOURCE = "user_pick"  # 사용자가 고른 사고 순간 (impact_source)


def load(p):
    with open(p, encoding="utf-8") as fp:
        return json.load(fp)


def find_impact(ego):
    """(충격 프레임, 근거) 또는 (None, 이유)"""
    segs = ego["segments"]
    jolts = ego["jolt_frames"]
    # 달림→멈춤 경계: 달리던 구간 바로 뒤에 멈춤 구간이 오는 곳 중 마지막
    edges = [b["from"] for a, b in zip(segs, segs[1:]) if a["state"] == "moving" and b["state"] == "stopped"]
    edge = edges[-1] if edges else None
    if edge is not None:
        near = [j for j in jolts if abs(j - edge) <= JOLT_NEAR]
        if near:
            return min(near), "jolt_near_stop"
        return max(edge - 3, 0), "moving_to_stopped"
    if jolts:
        return min(jolts), "jolt_only"
    moving = [g for g in segs if g["state"] == "moving"]
    return None, "never_moving" if not moving else "no_stop_found"


def pick_impact(ego, collision_t):
    """사용자가 고른 시각(초) → (충격 프레임, "user_pick"). 영상 길이를 넘으면 마지막 프레임으로 맞춘다"""
    frame = int(round(float(collision_t) * (ego.get("fps") or 30.0)))
    n = ego.get("frames")
    return max(0, min(frame, n - 1) if n else frame), PICK_SOURCE


def run(out_dir, collision_t=None):
    """collision_t: 사고 순간(초). 없으면(None) 지금처럼 자동으로 찾는다"""
    ego = load(os.path.join(out_dir, "ego_motion.json"))["summary"]
    tr = load(os.path.join(out_dir, "tracks.json"))["tracks"]
    impact, source = find_impact(ego) if collision_t is None else pick_impact(ego, collision_t)
    out = {"impact_frame": impact, "impact_source": source, "partner": None, "alternatives": []}
    if impact is not None:
        lo, hi = impact + WINDOW[0], impact + WINDOW[1]
        cands = []
        for tid, recs in tr.items():
            rs = [r for r in recs if r["cls"] in VEHICLES and lo <= r["frame"] <= hi and not r.get("filled")]
            if len(rs) < MIN_DETS:
                continue
            rs.sort(key=lambda r: r["frame"])
            big = max(rs, key=lambda r: r["bbox"][2] * r["bbox"][3])
            growth = big["bbox"][2] * big["bbox"][3] - rs[0]["bbox"][2] * rs[0]["bbox"][3]   # 창 안에서 얼마나 커졌나
            cx = big["bbox"][0] + big["bbox"][2] / 2
            cands.append({"id": tid, "cls": big["cls"], "area": round(big["bbox"][2] * big["bbox"][3], 4), "growth": round(growth, 4),
                          "frame": big["frame"], "bbox": big["bbox"],
                          "side": "left" if cx < SIDE_LEFT else "right" if cx > SIDE_RIGHT else "center",
                          "dets": len(rs)})
        cands.sort(key=lambda c: -c["growth"])
        if cands:
            out["partner"] = cands[0]
            out["alternatives"] = cands[1:3]
    with open(os.path.join(out_dir, "bb_partner.json"), "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    r = run(sys.argv[1])
    p = r["partner"]
    print(f"충격 {r['impact_frame']} ({r['impact_source']}), 상대 " +
          (f"{p['cls']} {p['id']} {p['side']} 크기 {p['area']}" if p else "없음"))
