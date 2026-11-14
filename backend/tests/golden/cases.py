"""결과 고정 시험의 사건 만들기 (tests/golden/README.md)

가짜 분석기로 데모 사건(android/tools/sd_data.py DEMO_SCENARIOS)과 차량 사건 API 대표 사건을 만들고,
정해진 답을 보낸 뒤의 응답을 단계마다 모은다. 시각·id·토큰처럼 매번 달라지는 값은 빼거나 고정한다.

  build_all() → {이름: {단계: 응답(정리한 것)}}

- 서버 시각(store.now_ms)은 촬영 1분 뒤, 차량 사건은 사고 1분 뒤로 고정. 시험 영상은 30초(시나리오 시각 그대로).
- 데모 차량 기록은 sd_data.py가 에뮬레이터에 넣는 루프 CSV와 같은 값(앱 VehicleRecord가 samples로 바꾸는 모양 그대로).
- 환경변수 HMTM_BB_ANALYZER와 상관없이 fake로 돈다 (ApiBase가 고정).
"""
import os
import shutil
import sys
import tempfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
REPO = os.path.dirname(ROOT)
for p in (ROOT, TESTS, os.path.join(REPO, "android", "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import sd_data                       # noqa: E402  데모 시나리오·차량 기록 모양
import test_bb_api as bbt            # noqa: E402  (os.chdir(backend))
import test_vehicle_api as vt        # noqa: E402
from bb_common import make_video     # noqa: E402
from src.blackbox import store       # noqa: E402
from src.vehicle import store as vstore   # noqa: E402

DATA = os.path.join(HERE, "data")
DURATION = 30.0
NOW = bbt.S0 + 60_000                # 서버가 받은 시각: 촬영 1분 뒤
VEH_NOW = vt.T + 60_000              # 차량 사건: 사고 1분 뒤
GEAR = {v: k for k, v in sd_data.GEAR.items()}   # 정수 → P/R/N/D (앱 VehicleRecord.gear)

# 응답 맨 위에서 빼는 칸: 매번 달라지는 값(id·시각)과 판정 버전 문자열(버전만 올린 변경으로 깨지지 않게)
DROP_TOP = {"id", "created_at", "updated_at", "judge_version"}


def clean(view):
    """응답에서 매번 달라지는 값을 뺀다 (맨 위 칸만. 안쪽 id는 도표 가감 요소 id 등이라 남김)"""
    if isinstance(view, list):
        return [clean(v) for v in view]
    if not isinstance(view, dict):
        return view
    out = {k: v for k, v in view.items() if k not in DROP_TOP}
    sy = out.get("sync")
    if isinstance(sy, dict):
        out["sync"] = {k: v for k, v in sy.items() if k != "params"}   # 상수 표 (설정값)
    return out


def demo_vehicle(scenario):
    """sd_data.py records와 같은 차량 기록 → 앱이 영상 구간 [S0 − 15초, S0 + 길이 + 15초]만 잘라 보내는 samples"""
    prof = sd_data.profile(scenario, DURATION)
    col = bbt.S0 + int(sd_data.collision_t(scenario, DURATION) * 1000)
    lo, hi = bbt.S0 - 15_000, bbt.S0 + int(DURATION * 1000) + 15_000
    out = []
    for t in range(lo, hi + 1, sd_data.STEP_MS):
        v, g, s, b = sd_data.sample(prof, (t - col) / 1000)
        out.append({"t": t, "speedKmh": float(f"{v:.2f}"), "gear": GEAR[g], "turnSignal": s, "brake": b})
    return {"range": {"from": lo, "to": hi}, "samples": out, "vehicle": {"cls": "car"}, "location": None,
            "client": {"app_version": "golden"}}


def reverse_vehicle():
    """후진 기록 (save_bb_responses.py reverse_vehicle와 같은 모양): 충돌 2.5초 전부터 기어 R, 3km/h"""
    col = bbt.S0 + 18_200   # 시나리오 충돌 시각 (30초 영상)
    out = [{"t": col + r, "speedKmh": 3.0, "gear": "R" if r >= -2500 else "D", "turnSignal": "OFF", "brake": False}
           for r in range(-12_000, 2_001, 100)]
    return {"range": {"from": out[0]["t"], "to": out[-1]["t"]}, "samples": out, "vehicle": {"cls": "car"},
            "location": None, "client": {"app_version": "golden"}}


# 데모 사건: (이름, 시나리오, 차량 기록, [(단계 이름, 보낼 것)])
#   차량 기록: True → sd_data.py 데모 기록, False → 영상만, 함수 → 그 함수가 만든 기록
#   보낼 것: {"answers": {...}} → PUT answers, {"pick": "first"} → 첫 후보로 사고 순간 고르기
RT_ANSWERS = {"road.signal_present": False, "road.wider_road": "equal", "parties.ego.driver_factors": []}
DEMO = [
    ("right_turn_left_straight", "right_turn_left_straight", True, [
        ("answered", {"answers": RT_ANSWERS}),
        ("speed_20plus", {"answers": dict(RT_ANSWERS, **{"parties.ego.driver_factors": ["speed_20plus"]})}),
        ("speed_20plus_causal", {"answers": dict(RT_ANSWERS, **{"parties.ego.driver_factors": ["speed_20plus"],
                                                                "parties.ego.avoidable_at_limit": True})}),
        ("signal_present", {"answers": {"road.signal_present": True}}),
    ]),
    ("ped_crosswalk_unsignalized", "ped_crosswalk_unsignalized", True, [
        ("night", {"answers": {"road.ped_visibility": "night"}}),
        ("night_speed_causal", {"answers": {"road.ped_visibility": "night",
                                            "parties.ego.driver_factors": ["speed_20plus"],
                                            "parties.ego.avoidable_at_limit": True}}),
    ]),
    ("mostly_unknown", "mostly_unknown", True, [
        ("other_pedestrian", {"answers": {"parties.other.cls": "pedestrian"}}),
    ]),
    ("left_turn_motion", "left_turn_motion", True, []),
    ("left_turn_motion_nosignal", "left_turn_motion_nosignal", True, []),
    ("straight_motion_slowed", "straight_motion_slowed", True, []),
    ("no_collision_pick", "no_collision_pick", True, [("picked", {"pick": "first"})]),
    # 차량 기록 없이 영상만 (sd.ps1 -NoRecord)
    ("right_turn_left_straight_video_only", "right_turn_left_straight", False, []),
    ("left_turn_motion_nosignal_video_only", "left_turn_motion_nosignal", False, []),
    # 출처 충돌(source_conflicts): 영상은 내 차 직진, 차량 기록은 후진
    ("ego_reverse_vehicle", "ego_reverse_video_wrong", reverse_vehicle, []),
]

# 차량 사건 API 대표 사건 (docs/api-spec.md, tests/test_vehicle_api.py 기록 모양)
VEHICLE = [
    ("vehicle_right_turn", dict(speed=vt.SLOW_DOWN, turn=vt.RIGHT_ON), [
        ("answered", {"parties.ego.movement": "right_turn", **vt.CROSS}),
    ]),
    ("vehicle_straight_slowed", dict(speed=vt.SLOW_DOWN), [
        ("answered", {"parties.ego.movement": "straight", "parties.other.entry_from": "left",
                      "parties.other.movement": "straight", "parties.other.cls": "car",
                      "intersection_entry_order": "same_time"}),
    ]),
    ("vehicle_reverse", dict(gear=lambda r: "R" if r >= -2500 else "D", speed=3.0), []),
]


class _Bb(bbt.ApiBase):
    def runTest(self):
        pass

    def put(self, h, cid, answers):
        r = self.c.put(f"/api/bb-cases/{cid}/answers", json={"answers": answers}, headers=h)
        assert r.status_code == 200, r.text
        return r.json()

    def pick(self, h, cid, t):
        r = self.c.put(f"/api/bb-cases/{cid}/collision", json={"t": t}, headers=h)
        assert r.status_code == 202, r.text
        return self.result(h, cid)

    def build(self, only=None):
        h = self.login("golden")
        out = {}
        for name, scenario, with_vehicle, steps in DEMO:
            if only and name not in only:
                continue
            veh = with_vehicle() if callable(with_vehicle) else demo_vehicle(scenario) if with_vehicle else None
            view = self.run_case(h, scenario=scenario, veh=veh)
            got = {"post": clean(view)}
            for step, send in steps:
                if "answers" in send:
                    got[step] = clean(self.put(h, view["id"], send["answers"]))
                else:
                    t = view["collision_review"]["candidates"][0]["t"]
                    got[step] = clean(self.pick(h, view["id"], t))
            last = list(got)[-1]
            g = clean(self.result(h, view["id"]))
            got["get"] = f"= {last}" if g == got[last] else g   # GET이 마지막 응답과 같으면 그 단계 이름만
            out[name] = got
        return out


class _Veh(vt.ApiBase):
    def runTest(self):
        pass

    def build(self, only=None):
        h = self.login("golden")
        out = {}
        for name, rec, steps in VEHICLE:
            if only and name not in only:
                continue
            r = self.post(vt.body(vt.build(**rec)), h)
            assert r.status_code == 201, r.text
            view = r.json()
            got = {"post": clean(view)}
            for step, answers in steps:
                p = self.c.put(f"/api/vehicle-cases/{view['id']}/answers", json={"answers": answers}, headers=h)
                assert p.status_code == 200, p.text
                got[step] = clean(p.json())
            out[name] = got
        return out


def names():
    return [d[0] for d in DEMO] + [v[0] for v in VEHICLE]


def build_all(only=None):
    """모든 사건을 임시 DB·임시 영상으로 만들어 {이름: {단계: 응답}}"""
    vtmp = tempfile.mkdtemp(prefix="hmtm_golden_")
    bbt.ApiBase.video = make_video(os.path.join(vtmp, bbt.NAME), seconds=DURATION, fps=5.0)
    bbt.ApiBase.vtmp = vtmp
    out = {}
    try:
        for cls in (_Bb, _Veh):
            s = cls()
            s.setUp()
            try:
                with mock.patch.object(store, "now_ms", return_value=NOW),                         mock.patch.object(vstore, "now_ms", return_value=VEH_NOW):
                    out.update(s.build(only))
            finally:
                s.tearDown()
    finally:
        del bbt.ApiBase.video, bbt.ApiBase.vtmp   # setUpClass가 클래스마다 다시 만듦
        shutil.rmtree(vtmp, ignore_errors=True)
    return out


# ---------- 저장·비교 ----------

def path_of(name):
    return os.path.join(DATA, name + ".json")


def save(name, got):
    import json
    os.makedirs(DATA, exist_ok=True)
    with open(path_of(name), "w", encoding="utf-8", newline="\n") as f:
        json.dump(got, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def load(name):
    import json
    with open(path_of(name), encoding="utf-8") as f:
        return json.load(f)


def _short(v, n=120):
    import json
    s = json.dumps(v, ensure_ascii=False, sort_keys=True)
    return s if len(s) <= n else s[:n] + f"… ({len(s)}자)"


def diff(saved, now, path=""):
    """다른 칸 목록: ["경로: 저장 X → 지금 Y", ...]. 목록 길이가 다르면 앞쪽 같은 자리끼리 비교한 뒤 남는 것을 적음"""
    if isinstance(saved, dict) and isinstance(now, dict):
        out = []
        for k in sorted(set(saved) | set(now), key=str):
            p = f"{path}.{k}" if path else str(k)
            if k not in now:
                out.append(f"{p}: 없어짐 (저장 {_short(saved[k])})")
            elif k not in saved:
                out.append(f"{p}: 새로 생김 (지금 {_short(now[k])})")
            else:
                out += diff(saved[k], now[k], p)
        return out
    if isinstance(saved, list) and isinstance(now, list):
        out = []
        for i, (a, b) in enumerate(zip(saved, now)):
            out += diff(a, b, f"{path}[{i}]")
        if len(saved) != len(now):
            out.append(f"{path}: 개수 {len(saved)} → {len(now)} "
                       f"(남는 것 {_short(saved[len(now):] if len(saved) > len(now) else now[len(saved):])})")
        return out
    if saved != now or type(saved) is not type(now):
        return [f"{path}: 저장 {_short(saved)} → 지금 {_short(now)}"]
    return []
