"""평가 영상을 정답 답까지 넣어 돌린다: 정답 파일 → 장면(찍어 둔 모서리) → 판정 → 정답 답 → 다시 판정

  cd ~/MTM && .venv/bin/python tools/evaluate/run_eval.py cc_3_210819_vehicle_313_066 ... [--out outputs/eval_expand]

영상마다:
  1. 정답 파일 (--gt/<영상>.json): 없으면 AI Hub 라벨(--labels, 영상_*·이미지_* 폴더)로 만든다 (src/dataset/aihub.load_video).
     프레임 라벨(당사자 박스)이 없으면 건너뜀
  2. 모서리: scenes/cc_<날짜>_corners.json (tools/pick_corners.py로 찍은 것, 장소 종류·길 없는 쪽 포함)
  3. run_app.py로 판정 → tools/evaluate/gt_answer.py로 정답 답 → 다시 판정 (질문이 남으면 3번까지)
     교차로는 신호등 유무를 splits의 signal(장소 이름의 신호등 있음/없음)로 답함 (라벨에 따로 없어서)
그 뒤 tools/evaluate/metrics.py --tap <out> --gt <gt>로 지표를 낸다.
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.getcwd())
from src.dataset.aihub import load_video


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def make_gt(name, labels, gt_dir):
    path = os.path.join(gt_dir, name + ".json")
    if os.path.exists(path):
        return path
    try:
        label, frames, dropped = load_video(labels, name)
    except IndexError:
        return None
    if not frames:   # 프레임 라벨(이미지_*)이 없으면 당사자를 맞출 수 없음
        return None
    os.makedirs(gt_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": "0.2", "source": "aihub", "video": name, "label": label,
                   "frames": frames, "dropped": dropped}, f, ensure_ascii=False, indent=1)
    return path


def run_app(video, out, *extra):
    return subprocess.run([sys.executable, "run_app.py", video, "--out", out, *extra], capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--out", default="outputs/eval_expand")
    ap.add_argument("--gt", default="outputs/gt_expand")
    ap.add_argument("--labels", default="data/aihub/cc_labels")
    args = ap.parse_args()
    signal = {a["reference"]: a["signal"] for a in load("splits/cctv_split.json")["accidents"]}
    for name in args.videos:
        gt = make_gt(name, args.labels, args.gt)
        scene = f"scenes/cc_{name.split('_')[2]}_corners.json"
        if gt is None or not os.path.exists(scene):
            print(f"{name}: 건너뜀 ({'정답 프레임 라벨 없음' if gt is None else '모서리 없음'})")
            continue
        s = load(scene)
        corners = " ".join(f"{x},{y}" for x, y in s["corners"])
        place = s.get("road_type") or "intersection"
        extra = ["--corners", corners, "--place", place] + (["--closed", s["closed_side"]] if s.get("closed_side") else [])
        out = os.path.join(args.out, name)
        # 지난번 답이 남아 있으면 지금 코드가 새로 미리 고른 값(model_guess)을 덮어써서 매번 새로 답함
        if os.path.exists(os.path.join(out, "answers.json")):
            os.remove(os.path.join(out, "answers.json"))
        video = f"data/videos/cc/{name}.mp4"
        p = run_app(video, out, *extra)
        road = {"road.signal_present": bool(signal.get(name))} if place == "intersection" else {}
        road.update(s.get("road_answers") or {})   # 사람이 장면을 보고 모서리 파일에 적어 둔 도로 답 (중앙선 등)
        for _ in range(3):
            subprocess.run([sys.executable, "tools/evaluate/gt_answer.py", out, "--gt", args.gt,
                            "--road", json.dumps(road)], capture_output=True, text=True)
            p = run_app(video, out, "--answers", os.path.join(out, "answers.json"))
            app = load(os.path.join(out, "app.json")) if os.path.exists(os.path.join(out, "app.json")) else {}
            if app.get("status") != "needs_answers" or not any(not q.get("optional") for q in app.get("questions", [])):
                break
        v = app.get("verdict") or {}
        print(f"{name}: {app.get('status')} {v.get('rule_id')} {v.get('fault_by_track')} "
              f"| {(p.stdout + p.stderr).strip().splitlines()[-1:] if p.returncode else ''}")


if __name__ == "__main__":
    main()
