r"""에뮬레이터 시험·데모 데이터 준비 (android/tools/sd.ps1이 부른다). backend 가상환경의 Python(OpenCV)으로 돌린다

  prepare  영상 폴더 정리: 비었으면 시험 영상 만들기, -Demo 세 시나리오, 지금 시각 기준 이름, 시나리오 표시, 경고
  records  영상 파일 이름의 시각에 맞춰 시나리오별 차량 기록(루프 CSV, 100ms)을 만든다
  push     만든 루프 CSV를 에뮬레이터 앱(운전자 사용자 10번)의 files/loop에 넣는다 (adb push + run-as cp, 크기 대조)

루프 CSV 형식은 앱 LoopRecorder와 같다: files/loop/seg_<분 시작 epoch ms>.csv, 헤더 t,speedKmh,gear,turnSignal,brake.
기어 정수는 VehicleGear(P=4, R=2, N=1, D=8), 지시등 LEFT/RIGHT/OFF, 브레이크 true/false (VehicleRecord.parseLine).
파일 이름 시각은 한국 시각(UTC+9)으로 본다 (서버 sync.DEFAULT_TZ_MIN, 앱은 기기 시간대 → 에뮬레이터를 Asia/Seoul로).

기록은 영상 앞뒤 1분을 분 파일 단위로 통째로 만든다. 앱이 지금 쓰고 있는 분 파일과 겹치면 기록이 섞이므로
영상 구간은 늘 지금보다 앞이어야 한다 (prepare --now가 그렇게 이름을 붙인다).
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCENARIO_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "backend", "src", "blackbox", "scenarios"))
DEFAULT_SCENARIO = "right_turn_left_straight"   # 서버 가짜 분석기 기본값 (fake.DEFAULT_SCENARIO)
# 데모: 차대차 질문 / 보행자 / 상대 종류 추정 + 차량 기록이 결과를 바꾸는지 (좌회전 지시등 켬·안 켬, 직진 서행, 시각 fine)
# + 사고 순간 고르기 (no_collision_pick: 분석기가 충돌을 못 찾고 후보를 줌 → 고르면 판정)
DEMO_SCENARIOS = ["right_turn_left_straight", "ped_crosswalk_unsignalized", "mostly_unknown",
                  "left_turn_motion", "left_turn_motion_nosignal", "straight_motion_slowed", "no_collision_pick"]
VIDEO_EXT = (".mp4", ".avi", ".mov", ".mkv", ".ts")
KST = dt.timezone(dt.timedelta(hours=9))
NAME_TIME = re.compile(r"(?<!\d)(20\d\d)[-_.]?(\d\d)[-_.]?(\d\d)[-_T ]?(\d\d)[-_:.]?(\d\d)[-_:.]?(\d\d)(?!\d)")
SCN = re.compile(r"__scn-([A-Za-z0-9_]+)")
GEN_MARK = "_gen"            # 이 도구가 만든 시험 영상 표시 (-Demo가 지우고 다시 만듦)
MINUTE = 60_000
STEP_MS = 100
PAD_MS = 60_000              # 영상 앞뒤로 만드는 기록 (앱·서버 여유 15초보다 넉넉히)
MAX_AGE_MS = 72 * 3_600_000  # 앱 루프 기록 보관 기간
PKG = "com.example.hmtm"
GEAR = {"P": 4, "R": 2, "N": 1, "D": 8}

# 시나리오별 차량 기록 (충돌 시각 기준 τ초). 시나리오 JSON의 이야기(fake.description)에 맞춘 값이다.
#   speed  [(τ, km/h)] 사이는 선형 보간, 앞뒤는 끝 값
#   signal [(τ시작, τ끝, LEFT|RIGHT)] 그 밖은 OFF
#   brake  [(τ시작, τ끝)] 그 밖은 false
#   충돌 뒤 10초가 지나면 기어 P (그 전은 D)
_STOP_AFTER = (1.5, 0)
PROFILES = {
    "right_turn_left_straight": {
        "story": "우회전 전 40→15km/h 감속, 충돌 약 3초 전부터 오른쪽 지시등, 충돌 뒤 정지",
        "speed": [(-8, 40), (-4, 18), (-0.3, 15), (0, 15), _STOP_AFTER],
        "signal": [(-3.2, 6, "RIGHT")],
        "brake": [(-8, -4), (0, 30)],
    },
    "right_turn_motion": "right_turn_left_straight",
    "left_turn_opposite": {
        "story": "좌회전 전 40→15km/h 감속, 충돌 약 4초 전부터 왼쪽 지시등, 충돌 뒤 정지",
        "speed": [(-9, 40), (-5, 18), (0, 15), _STOP_AFTER],
        "signal": [(-4.0, 6, "LEFT")],
        "brake": [(-9, -5), (0, 30)],
    },
    "straight_same_time": {
        "story": "교차로 앞 35→20km/h 서행(진입 약 1초 전까지), 지시등 없음, 충돌 뒤 정지",
        "speed": [(-8, 35), (-4, 20), (0, 20), (1.8, 0)],
        "signal": [],
        "brake": [(-8, -4), (0, 30)],
    },
    "rear_end_lead": {
        "story": "50km/h로 가다 충돌 1.2초 전 급제동(50→30km/h), 서 있던 앞차를 추돌",
        "speed": [(-1.2, 50), (0, 30), (1.0, 0)],
        "signal": [],
        "brake": [(-1.2, 30)],
    },
    "ped_crosswalk_unsignalized": {
        "story": "횡단보도 앞 40→20km/h 감속, 지시등 없음, 보행자와 부딪힌 뒤 정지",
        "speed": [(-7, 40), (-3, 20), (0, 20), (1.2, 0)],
        "signal": [],
        "brake": [(-7, -3), (-0.2, 30)],
    },
    "bike_crossing_side": {
        "story": "30km/h로 가다 옆에서 나온 자전거와 충돌 직전 제동",
        "speed": [(-0.8, 30), (0, 22), (1.2, 0)],
        "signal": [],
        "brake": [(-0.8, 30)],
    },
    "mostly_unknown": {
        "story": "30km/h로 직진(영상은 추정만)하다 충돌 직전 제동, 충돌 뒤 정지",
        "speed": [(-0.5, 30), (0, 25), (1.5, 0)],
        "signal": [],
        "brake": [(-0.5, 30)],
    },
    "_default": {
        "story": "30km/h로 가다 충돌 직전 제동, 충돌 뒤 정지 (이야기가 따로 없는 시나리오)",
        "speed": [(-0.5, 30), (0, 25), (1.5, 0)],
        "signal": [],
        "brake": [(-0.5, 30)],
    },
}


MOTION_KMH = 40.0   # ego_motion.speed_proxy 1.0 = 40km/h (backend tests/test_bb_fine.py samples와 같음)


def load_scenario(name, _seen=()):
    """시나리오 JSON (fake.load_scenario처럼 "extends"를 풀어 줌: 위 칸은 덮고 fake는 합침)"""
    if name in _seen:
        sys.exit(f"[오류] 시나리오 extends가 돌아요: {name}")
    try:
        with open(os.path.join(SCENARIO_DIR, f"{name}.json"), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    parent = d.pop("extends", None)
    if parent:
        base = load_scenario(parent, _seen + (name,))
        fake = dict(base.get("fake") or {}, **(d.get("fake") or {}))
        d = {**base, **d, "fake": fake}
    return d


def motion_profile(name, dur):
    """ego_motion과 fake.vehicle_demo가 있는 시나리오: 영상 속 내 차 움직임을 그대로 따르는 기록.
    서버 정밀 시각 맞추기(fine, 설계 5.3)가 속도 모양으로 맞출 수 있다. 없으면 None"""
    d = load_scenario(name)
    em, demo = d.get("ego_motion"), (d.get("fake") or {}).get("vehicle_demo")
    if not em or demo is None:
        return None
    k = dur / ((d.get("video") or {}).get("duration_s") or dur)
    col = collision_t(name, dur)
    speed = [(t * k - col, MOTION_KMH * sp) for t, sp in zip(em["t"], em["speed_proxy"])]
    speed.append((speed[-1][0] + 0.5, 0.0))                       # 영상 끝 뒤 정지
    sig, lead = demo.get("turn_signal"), demo.get("signal_lead_s")
    return {
        "story": (d.get("fake") or {}).get("description") or "영상 속 내 차 움직임을 따름",
        "speed": speed,
        "signal": [(-float(lead), 6, sig)] if sig and lead is not None else [],
        "brake": [(0, 30)],
    }


def profile(name, dur=30.0):
    m = motion_profile(name, dur)
    if m is not None:
        return m
    p = PROFILES.get(name, PROFILES["_default"])
    return PROFILES[p] if isinstance(p, str) else p


# ---------- 영상 ----------

def videos(folder):
    return sorted(p for p in glob.glob(os.path.join(folder, "*")) if p.lower().endswith(VIDEO_EXT))


def duration_s(path):
    try:
        import cv2
        cap = cv2.VideoCapture(path)
        fps, n = cap.get(cv2.CAP_PROP_FPS) or 0, cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        cap.release()
        if fps > 0 and n > 0:
            return n / fps
    except ImportError:
        pass
    return None


def name_time_ms(name):
    """파일 이름 시각(한국 시각) → epoch ms, 없으면 None"""
    m = NAME_TIME.search(os.path.basename(name))
    if not m:
        return None
    try:
        d = dt.datetime(*map(int, m.groups()), tzinfo=KST)
    except ValueError:
        return None
    return int(d.timestamp() * 1000)


def scenario_of(name):
    m = SCN.search(os.path.basename(name))
    return m.group(1) if m else None


def stamp(ms):
    return dt.datetime.fromtimestamp(ms / 1000, KST).strftime("%Y%m%d_%H%M%S")


def make_video(path, seconds):
    """make_test_video.py와 같은 회색 영상 (화면에 경과 초)"""
    subprocess.run([sys.executable, os.path.join(HERE, "make_test_video.py"), path, "--seconds", str(seconds)], check=True)


def rename(path, start_ms=None, scenario=None):
    """시각·시나리오 표시를 바꾼 새 이름으로 옮긴다. 시각이 없던 이름은 앞에 붙인다"""
    folder, base = os.path.split(path)
    stem, ext = os.path.splitext(base)
    if scenario is not None:
        stem = SCN.sub("", stem) + f"__scn-{scenario}"
    if start_ms is not None:
        if NAME_TIME.search(stem):
            stem = NAME_TIME.sub(stamp(start_ms), stem, count=1)
        else:
            stem = f"{stamp(start_ms)}_{stem}"
    new = os.path.join(folder, stem + ext)
    if new != path:
        if os.path.exists(new):
            sys.exit(f"[오류] 이름이 겹쳐요: {new}")
        os.replace(path, new)
    return new


def plan_starts(durations, now_ms):
    """지금보다 앞쪽으로 겹치지 않게 촬영 시작 시각을 정한다 (앱이 쓰는 지금 분 파일과도 안 겹치게).
    영상마다 [S0 − 1분, S0 + 길이 + 1분]의 분 파일이 따로 생긴다. 최근 것부터 차례로 뒤로."""
    cursor = now_ms // MINUTE * MINUTE           # 지금 분의 시작. 이 분 파일은 건드리지 않음
    starts = []
    for d in durations:
        s0 = (cursor - int(d * 1000) - PAD_MS - 10_000) // MINUTE * MINUTE + 10_000   # 분 시작 + 10초
        starts.append(s0)
        cursor = (s0 - PAD_MS) // MINUTE * MINUTE
    return starts


def cmd_prepare(a):
    os.makedirs(a.videos, exist_ok=True)
    now = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    if a.demo:
        for p in videos(a.videos):
            if GEN_MARK in os.path.basename(p):
                os.remove(p)
                print(f"지움(전 데모 영상): {os.path.basename(p)}")
        for scn in DEMO_SCENARIOS:
            p = os.path.join(a.videos, f"20000101_000000_F{GEN_MARK}__scn-{scn}.mp4")
            make_video(p, a.seconds)
    elif not videos(a.videos):
        scn = a.scenario or DEFAULT_SCENARIO
        print(f"영상 폴더가 비어 시험 영상을 만들어요 (시나리오 {scn}, {a.seconds}초)")
        make_video(os.path.join(a.videos, f"20000101_000000_F{GEN_MARK}__scn-{scn}.mp4"), a.seconds)

    vids = videos(a.videos)
    if a.scenario and not a.demo:
        vids = [rename(p, scenario=a.scenario) for p in vids]
    # 지금 시각 기준 이름: --now면 전부, 아니면 이 도구가 만든 영상만 (만든 영상은 늘 새 시각)
    to_time = [p for p in vids if a.now or GEN_MARK in os.path.basename(p)]
    if to_time:
        durs = [duration_s(p) or a.seconds for p in to_time]
        newest_first = list(reversed(to_time))
        starts = plan_starts(list(reversed(durs)), now)
        mapping = {p: rename(p, start_ms=s) for p, s in zip(newest_first, starts)}
        vids = [mapping.get(p, p) for p in vids]

    print(f"영상 폴더: {a.videos}")
    warn = 0
    for p in videos(a.videos):
        base = os.path.basename(p)
        t, d, scn = name_time_ms(base), duration_s(p), scenario_of(base)
        line = f"  {base}  ({d:.1f}초)" if d else f"  {base}  (길이 못 읽음)"
        print(line)
        if t is None:
            warn += 1
            print("    [경고] 파일 이름에 촬영 시각(YYYYMMDD_HHMMSS)이 없어요. 차량 기록을 못 붙여요 → -Now로 이름을 붙이세요")
        elif t > now - (d or a.seconds) * 1000 - 15_000:
            warn += 1
            print("    [경고] 촬영 시각이 아직 안 지났어요(영상 끝 + 15초). 차량 기록이 덜 붙어요 → -Now")
        elif t < now - MAX_AGE_MS:
            warn += 1
            print("    [경고] 촬영 시각이 72시간보다 오래돼 앱이 차량 기록을 지워요 → -Now")
        if scn is None:
            print(f"    (시나리오 표시 __scn- 없음 → 서버 기본 시나리오 {DEFAULT_SCENARIO})")
    return 0


# ---------- 차량 기록 ----------

def _interp(points, tau):
    if tau <= points[0][0]:
        return points[0][1]
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if tau <= t1:
            return v0 + (v1 - v0) * (tau - t0) / (t1 - t0)
    return points[-1][1]


def sample(prof, tau):
    """충돌 기준 τ초의 (속도, 기어, 지시등, 브레이크)"""
    v = max(0.0, _interp(prof["speed"], tau))
    sig = next((s for a, b, s in prof["signal"] if a <= tau < b), "OFF")
    brk = any(a <= tau < b for a, b in prof["brake"])
    gear = "P" if tau >= 10 else "D"
    return v, GEAR[gear], sig, brk


def collision_t(scn, dur):
    """시나리오 JSON의 충돌 시각을 실제 영상 길이에 비례해 옮김 (fake._rescale과 같음)"""
    d = load_scenario(scn)
    t = ((d.get("facts") or {}).get("collision") or {}).get("t")
    base = (d.get("video") or {}).get("duration_s") or dur
    if isinstance(t, (int, float)):
        return t * dur / base
    return dur * 0.6


def cmd_records(a):
    now = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    cur_minute = now // MINUTE * MINUTE
    plans = []
    for p in videos(a.videos):
        base = os.path.basename(p)
        s0 = name_time_ms(base)
        if s0 is None:
            print(f"  건너뜀(이름에 시각 없음): {base}")
            continue
        dur = duration_s(p) or 30.0
        if s0 < now - MAX_AGE_MS:
            print(f"  건너뜀(72시간보다 오래됨, 앱이 지움): {base}")
            continue
        scn = scenario_of(base) or DEFAULT_SCENARIO
        t_col = s0 + int(collision_t(scn, dur) * 1000)
        lo = (s0 - PAD_MS) // MINUTE * MINUTE
        hi = (s0 + int(dur * 1000) + PAD_MS) // MINUTE * MINUTE      # 마지막 분 파일의 시작
        if hi >= cur_minute:
            print(f"  건너뜀(지금 기록 중인 분과 겹침, -Now로 이름을 앞당기세요): {base}")
            continue
        plans.append({"video": base, "scenario": scn, "start_ms": s0, "collision_ms": t_col, "duration_s": dur,
                      "minutes": list(range(lo, hi + MINUTE, MINUTE)), "story": profile(scn, dur)["story"]})

    os.makedirs(a.out, exist_ok=True)
    for f in glob.glob(os.path.join(a.out, "seg_*.csv")):
        os.remove(f)
    written = {}
    for pl in plans:
        prof = profile(pl["scenario"], pl["duration_s"])
        for m in pl["minutes"]:
            if m in written:
                sys.exit(f"[오류] {pl['video']}의 기록이 {written[m]}와 같은 분 파일을 써요. 영상 시각을 2분 넘게 떼어 주세요 (-Now)")
            written[m] = pl["video"]
            lines = ["t,speedKmh,gear,turnSignal,brake"]
            for t in range(m, m + MINUTE, STEP_MS):
                v, g, s, b = sample(prof, (t - pl["collision_ms"]) / 1000)
                lines.append(f"{t},{v:.2f},{g},{s},{'true' if b else 'false'}")
            # 앱 BufferedWriter.newLine()과 같은 LF, 바이트 그대로 넣으려고 newline=""
            with open(os.path.join(a.out, f"seg_{m}.csv"), "w", encoding="ascii", newline="") as f:
                f.write("\n".join(lines) + "\n")
        print(f"  {pl['video']}: {pl['scenario']} — {pl['story']}")
        print(f"    촬영 시작 {stamp(pl['start_ms'])}, 충돌 {stamp(pl['collision_ms'])}, 분 파일 {len(pl['minutes'])}개")
    with open(os.path.join(a.out, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plans, f, ensure_ascii=False, indent=1)
    print(f"차량 기록 {len(written)}개 파일 → {a.out}")
    return 0


TMP_DIR = "/data/local/tmp/hmtm_loop"


def _adb(adb, *args):
    return subprocess.run([adb, *args], capture_output=True)


def cmd_push(a):
    """adb push로 /data/local/tmp에 올린 뒤 run-as cp로 앱 폴더에 복사하고 크기를 대조한다.
    Windows에서 `adb shell` 파이프는 줄 끝이 바뀌거나 잘리고, `adb exec-in` + stdin도 약 18KB에서 잘렸다
    (이 도구를 만들 때 확인). adb push는 바이트 그대로이고, shell이 올린 파일(0666)은 debuggable 앱이 run-as로 읽을 수 있다."""
    files = sorted(glob.glob(os.path.join(a.dir, "seg_*.csv")))
    if not files:
        print("넣을 차량 기록이 없어요")
        return 0
    run_as = ["shell", "run-as", PKG, "--user", str(a.user)]
    r = _adb(a.adb, *run_as, "mkdir", "-p", "files/loop")
    if r.returncode != 0:
        sys.exit(f"[오류] 앱 폴더에 못 들어가요 (앱 설치·사용자 {a.user} 확인): {(r.stdout + r.stderr).decode(errors='replace')}")
    _adb(a.adb, "shell", "rm", "-rf", TMP_DIR)
    _adb(a.adb, "shell", "mkdir", "-p", TMP_DIR)
    r = _adb(a.adb, "push", *files, TMP_DIR + "/")
    if r.returncode != 0:
        sys.exit(f"[오류] adb push 실패: {(r.stdout + r.stderr).decode(errors='replace')}")
    bad = 0
    for path in files:
        name = os.path.basename(path)
        r = _adb(a.adb, *run_as, "cp", f"{TMP_DIR}/{name}", f"files/loop/{name}")
        size = os.path.getsize(path)
        got = _adb(a.adb, *run_as, "stat", "-c", "%s", f"files/loop/{name}").stdout.decode().strip()
        ok = r.returncode == 0 and got == str(size)
        bad += not ok
        print(f"  {'넣음' if ok else '[실패]'} files/loop/{name} ({size:,} 바이트{'' if ok else f', 기기 {got}'})")
    _adb(a.adb, "shell", "rm", "-rf", TMP_DIR)
    if bad:
        sys.exit(f"[오류] {bad}개 파일이 제대로 안 들어갔어요")
    print(f"차량 기록 {len(files)}개를 앱(사용자 {a.user})의 files/loop에 넣었어요")
    return 0


def main():
    ap = argparse.ArgumentParser(description="에뮬레이터 시험·데모 데이터 (sd.ps1이 부름)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--videos", required=True)
    p.add_argument("--now", action="store_true", help="모든 영상 이름을 지금 시각 기준(몇 분 전)으로")
    p.add_argument("--scenario", help="모든 영상에 __scn-<이름> 붙이기")
    p.add_argument("--demo", action="store_true", help=f"데모 시나리오 영상 만들기: {', '.join(DEMO_SCENARIOS)}")
    p.add_argument("--seconds", type=float, default=30)
    p = sub.add_parser("records")
    p.add_argument("--videos", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("push")
    p.add_argument("--adb", required=True)
    p.add_argument("--dir", required=True)
    p.add_argument("--user", type=int, default=10)
    p = sub.add_parser("scenarios")
    a = ap.parse_args()
    if a.cmd == "scenarios":
        names = sorted(os.path.splitext(os.path.basename(x))[0] for x in glob.glob(os.path.join(SCENARIO_DIR, "*.json")))
        print("\n".join(names))
        return 0
    if a.scenario if a.cmd == "prepare" else False:
        if not os.path.isfile(os.path.join(SCENARIO_DIR, f"{a.scenario}.json")):
            sys.exit(f"[오류] 시나리오 {a.scenario}가 없어요. 목록: sd.ps1 -ListScenarios")
    return {"prepare": cmd_prepare, "records": cmd_records, "push": cmd_push}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
