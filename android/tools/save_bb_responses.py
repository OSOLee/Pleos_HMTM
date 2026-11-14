"""앱 단위 시험용 서버 응답 다시 저장 (android/app/src/test/resources/bb/*.json)

  backend\\.venv\\Scripts\\python android\\tools\\save_bb_responses.py

backend 시험 도우미(tests/test_bb_api.ApiBase: 임시 DB·가짜 분석기·TestClient)로 실제 POST·PUT·GET·목록을 돌려
응답을 그대로 저장한다. 서버 시각은 촬영 1분 뒤로 고정(clock_mismatch만 3일 뒤). backend 코드는 고치지 않는다. 시험 영상은 30초(시나리오 시각 그대로, 충돌 18.2초).
analyzing.json(분석 중 객체)은 손으로 둔 그대로.
"""
import json
import os
import sys
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
BACKEND = os.path.join(REPO, "backend")
OUT = os.path.join(REPO, "android", "app", "src", "test", "resources", "bb")
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "tests"))

import test_bb_api as bbt   # noqa: E402  (os.chdir(backend))
from bb_common import make_video   # noqa: E402
from src.blackbox import analyzer, store   # noqa: E402
from test_bb_vehicle_evidence import LEFT_6S, samples as motion_samples   # noqa: E402

DAY = 86_400_000


def save(name, data):
    with open(os.path.join(OUT, name + ".json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("저장", name)


class Saver(bbt.ApiBase):
    def runTest(self):
        pass

    def put(self, h, cid, answers):
        r = self.c.put(f"/api/bb-cases/{cid}/answers", json={"answers": answers}, headers=h)
        assert r.status_code == 200, r.text
        return r.json()

    def case(self, h, scenario, **kw):
        return self.run_case(h, scenario=scenario, **kw)

    def motion_vehicle(self, scenario, turn):
        bb = analyzer.run(self.video, scenario=scenario, name="fake")
        s = motion_samples(bb, turn, s0=bbt.S0)
        return {"range": {"from": s[0]["t"], "to": s[-1]["t"]}, "samples": s, "vehicle": {"cls": "car"}}

    def all(self):
        h = self.login("saver")
        # 목록 (list.json): 오래된 것부터 만들어 최근 것이 위
        list_ids = []
        car = self.case(h, "mostly_unknown")
        list_ids.append(car["id"])
        ped = self.case(h, "ped_crosswalk_unsignalized")
        save("ped_crosswalk_unsignalized", ped)
        save("ped_modifiers", ped)
        list_ids.append(ped["id"])
        unknown = self.case(h, "mostly_unknown")
        save("mostly_unknown", unknown)
        save("cls_pedestrian", self.put(h, unknown["id"], {"parties.other.cls": "pedestrian"}))
        list_ids.append(unknown["id"])
        bike = self.case(h, "bike_crossing_side")
        save("bike_crossing_side", bike)
        list_ids.append(bike["id"])
        rows = self.c.get("/api/bb-cases", headers=h).json()
        save("list", [r for r in rows if r["id"] in list_ids])

        rt = self.case(h, "right_turn_left_straight")
        save("right_turn_left_straight", rt)
        save("answered", self.put(h, rt["id"], {
            "road.signal_present": True, "road.wider_road": "equal", "road.center_line": True,
            "intersection_entry_order": "ego", "parties.ego.turn_signal_used": True}))
        sp = self.case(h, "right_turn_left_straight")
        save("car_speed", self.put(h, sp["id"], {"parties.ego.driver_factors": ["speed_20plus"]}))

        nc = self.case(h, "no_collision")
        save("no_collision", nc)

        # 사고 순간 고르기: no_collision_pick → 고르면 판정 (pick_done), no_collision → 다시 못 찾음 (pick_failed)
        pk = self.case(h, "no_collision_pick")
        save("no_collision_pick", pk)
        r = self.c.put(f"/api/bb-cases/{pk['id']}/collision", json={"t": pk["collision_review"]["candidates"][0]["t"]},
                       headers=h)
        assert r.status_code == 202, r.text
        save("pick_accepted", r.json())
        save("pick_done", self.result(h, pk["id"]))
        r = self.c.put(f"/api/bb-cases/{nc['id']}/collision", json={"t": 12.0}, headers=h)
        assert r.status_code == 202, r.text
        save("pick_failed", self.result(h, nc["id"]))
        errors = {}
        for key, body, cid in (("not_needed", {"t": 1.0}, pk["id"]), ("invalid", {"t": 999}, nc["id"]),
                               ("shape", {"x": 1}, nc["id"])):
            r = self.c.put(f"/api/bb-cases/{cid}/collision", json=body, headers=h)
            errors[key] = {"status": r.status_code, "body": r.json()}
        save("pick_errors", errors)

        # 차량 기록
        lt_off = self.case(h, "left_turn_motion", veh=self.motion_vehicle("left_turn_motion", None))
        save("left_turn_effect", lt_off)
        lt_on = self.case(h, "left_turn_motion", veh=self.motion_vehicle("left_turn_motion", LEFT_6S))
        save("left_turn_noeffect", lt_on)
        save("reverse_vehicle", self.case(h, "ego_reverse_video_wrong",
                                          veh=bbt.vehicle(gear=bbt.REVERSE, speed=3.0)))
        veh_ids = [ped["id"], car["id"], lt_on["id"], lt_off["id"]]
        rows = self.c.get("/api/bb-cases", headers=h).json()
        save("list_vehicle", [r for r in rows if r["id"] in veh_ids])

        # 시계 경고: 서버가 촬영 3일 뒤에 받음(영상 시계), 차량 기록은 2시간 어긋남(차량 시계·안 겹침)
        veh = bbt.vehicle()
        for x in veh["samples"]:
            x["t"] -= 2 * 3_600_000
        veh["range"] = {"from": veh["samples"][0]["t"], "to": veh["samples"][-1]["t"]}
        with mock.patch.object(store, "now_ms", return_value=bbt.S0 + 3 * DAY):
            save("clock_mismatch", self.case(h, "right_turn_left_straight", veh=veh))

        # 목록에 사고 순간 확인 필요 (no_collision_pick를 하나 더, 고르지 않음)
        extra = self.case(h, "no_collision_pick")
        rows = self.c.get("/api/bb-cases?limit=50", headers=h).json()
        save("list_pick", [r for r in rows if r["id"] in (extra["id"], rt["id"], ped["id"])])


def main():
    # 차량 기록 도우미(bbt.vehicle)의 충돌 시각을 30초 영상의 18.2초로 (원래는 12초 영상 비율)
    bbt.T = bbt.S0 + 18_200
    bbt.ApiBase.video = make_video(os.path.join(bbt.ROOT, "data", "tmp_save_bb", bbt.NAME), seconds=30.0, fps=5.0)
    bbt.ApiBase.vtmp = os.path.dirname(bbt.ApiBase.video)
    s = Saver()
    s.setUp()
    try:
        # 서버는 촬영 1분 뒤에 받은 것으로 (지금 시각이면 시험 영상 날짜와 하루 넘게 달라 모든 응답에 시계 경고가 붙음)
        with mock.patch.object(store, "now_ms", return_value=bbt.S0 + 60_000):
            s.all()
    finally:
        s.tearDown()
        bbt.ApiBase.tearDownClass()


if __name__ == "__main__":
    main()
