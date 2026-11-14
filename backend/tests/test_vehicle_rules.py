"""차량 기록 자동 답변 규칙 v0 시험 (docs/api-spec.md 2.1, 4절)

  python -m pytest tests/test_vehicle_rules.py
  python -m unittest tests.test_vehicle_rules -v

합성 기록(100ms 간격)을 만들어 규칙마다 경계 사례를 본다. 시각은 모두 사고 시각 T 기준 ms(보통 음수)로 적는다.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.vehicle import rules
from src.vehicle.samples import Timeline, VehicleError, signal_intervals, validate

T = 1_762_581_652_300   # 사고 시각 (epoch ms)


# ---------- 합성 기록 헬퍼 ----------

def _val(x, r):
    return x(r) if callable(x) else x


def build(start=-12000, end=2000, speed=40.0, gear="D", turn="OFF", brake=False, drop=(), step=100):
    """T+start ~ T+end를 step ms 간격으로 기록. 각 값은 상수 또는 r(T 기준 ms) → 값 함수.
    drop=[(a, b)]: a < r < b인 기록을 빼서 a~b 사이를 빈 곳으로 만든다 (두 기록 간격 = b - a)"""
    out = []
    for r in range(start, end + 1, step):
        if any(a < r < b for a, b in drop):
            continue
        out.append({"t": T + r, "speedKmh": _val(speed, r), "gear": _val(gear, r),
                    "turnSignal": _val(turn, r), "brake": _val(brake, r)})
    return out


def on(value, a, b, base="OFF"):
    """a ≤ r < b 동안만 value, 그 밖은 base"""
    return lambda r: value if a <= r < b else base


def pieces(*parts, default=None):
    """[(a, b, value), ...] 순서대로 처음 맞는 구간의 값"""
    def f(r):
        for a, b, v in parts:
            if a <= r < b:
                return v
        return default
    return f


def blink(d, a, b, on_ms=400, off_ms=400):
    """a ~ b 동안 깜빡이는 램프 (on_ms 켜짐, off_ms 꺼짐 반복)"""
    return lambda r: d if a <= r < b and (r - a) % (on_ms + off_ms) < on_ms else "OFF"


def ramp(v0, v1, a, b):
    """r < a는 v0, r ≥ b는 v1, 사이는 직선"""
    return lambda r: v0 if r < a else v1 if r >= b else v0 + (v1 - v0) * (r - a) / (b - a)


def setup(samples, source="manual"):
    return Timeline(samples), rules.Ctx(T, source)


def body(samples=None, **kw):
    samples = build(start=-5000, end=1000) if samples is None else samples
    b = {"range": {"from": T - 5000, "to": T + 1000}, "t_event": T, "t_event_source": "hard_brake",
         "samples": samples, "vehicle": {"cls": "car"}, "location": None, "client": {"app_version": "0.1.0"}}
    b.update(kw)
    return b


# ---------- samples.py ----------

class TimelineState(unittest.TestCase):
    def test_hold_until_next(self):
        """시각 t의 상태 = t 이전(포함) 마지막 기록"""
        tl = Timeline(build(start=-1000, end=0, speed=lambda r: float(r)))
        self.assertEqual(tl.state("speedKmh", T - 1000), -1000.0)
        self.assertEqual(tl.state("speedKmh", T - 950), -1000.0)
        self.assertEqual(tl.state("speedKmh", T - 900), -900.0)
        self.assertIsNone(tl.state("speedKmh", T - 1001))   # 첫 기록 전

    def test_state_in_gap_is_none(self):
        tl = Timeline(build(start=-6000, end=0, drop=[(-5000, -2500)]))
        self.assertIsNone(tl.state("speedKmh", T - 4000))
        self.assertEqual(tl.state("speedKmh", T - 2500), 40.0)

    def test_gaps(self):
        tl = Timeline(build(start=-6000, end=0, drop=[(-5000, -2500), (-2000, -100)]))
        self.assertEqual(tl.gaps(), [{"from": T - 5000, "to": T - 2500}])   # 1.9초는 빈 곳 아님

    def test_has_gap_threshold(self):
        """두 기록 사이가 2초보다 벌어져야 빈 곳"""
        self.assertFalse(Timeline(build(drop=[(-6000, -4000)])).has_gap(T - 10000, T))   # 정확히 2초
        self.assertTrue(Timeline(build(drop=[(-6000, -3900)])).has_gap(T - 10000, T))    # 2.1초
        # 구간 밖의 빈 곳은 상관없음
        self.assertFalse(Timeline(build(drop=[(-6000, -3000)])).has_gap(T - 2000, T))
        # 구간 앞쪽에 기록이 아예 없는 부분이 2초 넘으면 빈 곳
        self.assertTrue(Timeline(build(start=-3000)).has_gap(T - 10000, T))
        self.assertFalse(Timeline(build(start=-9000)).has_gap(T - 10000, T))

    def test_duration_and_mean(self):
        tl = Timeline(build(speed=pieces((-5000, -3000, 20.0), default=60.0)))
        self.assertEqual(tl.duration("speedKmh", T - 5000, T - 1000, lambda v: v < 30), 2000)
        self.assertAlmostEqual(tl.mean("speedKmh", T - 5000, T - 1000), 40.0)
        tl = Timeline(build(speed=None))
        self.assertIsNone(tl.mean("speedKmh", T - 5000, T))


class BlinkMerge(unittest.TestCase):
    def test_blink_is_one_interval(self):
        tl = Timeline(build(turn=blink("RIGHT", -6000, 0)))
        self.assertEqual(signal_intervals(tl, T - 10000, T), [("RIGHT", T - 6000, T)])   # 마지막 켜짐 [-400, 0)

    def test_off_up_to_1500_merges(self):
        turn = pieces((-6000, -5000, "RIGHT"), (-3500, 2000, "RIGHT"), default="OFF")
        tl = Timeline(build(turn=turn))
        self.assertEqual(signal_intervals(tl, T - 10000, T), [("RIGHT", T - 6000, T)])

    def test_off_over_1500_splits(self):
        turn = pieces((-6000, -5000, "RIGHT"), (-3400, 2000, "RIGHT"), default="OFF")
        tl = Timeline(build(turn=turn))
        self.assertEqual(signal_intervals(tl, T - 10000, T),
                         [("RIGHT", T - 6000, T - 5000), ("RIGHT", T - 3400, T)])

    def test_opposite_between_does_not_merge(self):
        turn = pieces((-6000, -5000, "RIGHT"), (-5000, -4500, "LEFT"), (-4500, 2000, "RIGHT"), default="OFF")
        tl = Timeline(build(turn=turn))
        self.assertEqual([d for d, _, _ in signal_intervals(tl, T - 10000, T)], ["RIGHT", "LEFT", "RIGHT"])


class Validate(unittest.TestCase):
    def code(self, b):
        with self.assertRaises(VehicleError) as cm:
            validate(b)
        return cm.exception

    def test_ok(self):
        v = validate(body())
        self.assertEqual(v["t_event"], T)
        self.assertEqual(v["vehicle_cls"], "car")
        self.assertEqual(len(v["samples"]), 61)

    def test_range(self):
        self.assertEqual(self.code(body(range={"from": T, "to": T})).code, "range_invalid")
        self.assertEqual(self.code(body(range={"from": T - 120001, "to": T})).code, "range_invalid")

    def test_t_event(self):
        self.assertEqual(self.code(body(t_event=T - 2001)).code, "t_event_out_of_range")   # 앞쪽 2.999초
        self.assertEqual(self.code(body(t_event=T + 1001)).code, "t_event_out_of_range")
        validate(body(t_event=T - 2000))   # 앞쪽 정확히 3초

    def test_samples_count_and_order(self):
        self.assertEqual(self.code(body(samples=[])).code, "samples_empty")
        many = [{"t": T - 5000 + i // 4, "speedKmh": 1.0, "gear": "D", "turnSignal": "OFF", "brake": False}
                for i in range(20001)]
        self.assertEqual(self.code(body(samples=many)).code, "samples_too_many")
        s = build(start=-5000, end=1000)
        s[3], s[4] = s[4], s[3]
        self.assertEqual(self.code(body(samples=s)).code, "samples_unsorted")

    def test_sample_values(self):
        for key, bad in (("gear", "X"), ("gear", 8), ("speedKmh", -3), ("speedKmh", True),
                         ("turnSignal", "HAZARD"), ("brake", "true")):
            with self.subTest(key=key, bad=bad):
                s = build(start=-5000, end=1000)
                s[1][key] = bad
                e = self.code(body(samples=s))
                self.assertEqual(e.code, "sample_invalid")
                self.assertIn("samples[1]", e.message)

    def test_location(self):
        self.assertEqual(self.code(body(location={"lat": 1})).code, "location_unsupported")


# ---------- turn_signal_v0 (4.4) ----------

class TurnSignal(unittest.TestCase):
    def run_rule(self, movement="right_turn", lane_change_dir=None, source="manual", **kw):
        tl, ctx = setup(build(**kw), source)
        return rules.turn_signal(tl, ctx, movement, lane_change_dir)

    def test_early_true(self):
        r = self.run_rule(turn=on("RIGHT", -6000, 9999))
        self.assertTrue(r["determined"])
        self.assertIs(r["value"], True)
        self.assertEqual(r["field"], "parties.ego.turn_signal_used")
        self.assertEqual(r["rule"], "turn_signal_v0")
        self.assertEqual(r["source"], "vehicle")
        self.assertEqual(r["evidence"]["text"], "사고 6초 전 오른쪽 지시등 켜짐 (사고 때까지 켜져 있음)")
        self.assertEqual(r["evidence"]["window"], {"from": T - 10000, "to": T})
        self.assertEqual(r["evidence"]["points"], [{"t": T - 6000, "key": "turnSignal", "value": "RIGHT"}])

    def test_on_then_off_true(self):
        r = self.run_rule(turn=on("RIGHT", -8000, -5000))
        self.assertIs(r["value"], True)
        self.assertEqual(r["evidence"]["text"], "사고 8초 전 오른쪽 지시등 켜짐 (3초 동안)")

    def test_late_false(self):
        """평균 32km/h → LEAD = 30m ÷ 8.89m/s = 3.4초. 1.8초 전에 켬은 늦음"""
        r = self.run_rule(speed=32.0, turn=on("RIGHT", -1800, 9999))
        self.assertIs(r["value"], False)
        self.assertEqual(r["evidence"]["text"],
                         "사고 1.8초 전에야 오른쪽 지시등을 켰어요 (평균 32km/h라 3.4초 전에는 켜야 해요)")
        self.assertEqual(r["params"]["lead_ms"], 3375)

    def test_none_false(self):
        r = self.run_rule()
        self.assertIs(r["value"], False)
        self.assertEqual(r["evidence"]["text"], "사고 전 10초 동안 오른쪽 지시등을 켜지 않았어요")

    def test_opposite_false(self):
        r = self.run_rule(turn=on("LEFT", -6000, 9999))
        self.assertIs(r["value"], False)
        self.assertEqual(r["evidence"]["text"], "오른쪽이 아니라 왼쪽 지시등을 켰어요")

    def test_short_false(self):
        r = self.run_rule(turn=on("RIGHT", -6000, -5400))
        self.assertIs(r["value"], False)
        self.assertEqual(r["evidence"]["text"], "사고 6초 전 오른쪽 지시등을 0.6초만 켰어요")

    def test_one_second_is_enough(self):
        self.assertIs(self.run_rule(turn=on("RIGHT", -6000, -5000))["value"], True)
        self.assertIs(self.run_rule(turn=on("RIGHT", -6000, -5100))["value"], False)

    def test_expected_direction(self):
        self.assertIs(self.run_rule("left_turn", turn=on("LEFT", -6000, 9999))["value"], True)
        self.assertIs(self.run_rule("u_turn", turn=on("LEFT", -6000, 9999))["value"], True)
        self.assertIs(self.run_rule("u_turn", turn=on("RIGHT", -6000, 9999))["value"], False)
        # 진로 변경: 방향 답이 없으면 어느 쪽이든 켰으면 됨
        self.assertIs(self.run_rule("lane_change", turn=on("LEFT", -6000, 9999))["value"], True)
        r = self.run_rule("lane_change", turn=on("RIGHT", -6000, 9999))
        self.assertIs(r["value"], True)
        r = self.run_rule("lane_change")
        self.assertEqual(r["evidence"]["text"], "사고 전 10초 동안 지시등을 켜지 않았어요")
        # 방향 답이 있으면 그 방향
        r = self.run_rule("lane_change", "right", turn=on("LEFT", -6000, 9999))
        self.assertEqual(r["evidence"]["text"], "오른쪽이 아니라 왼쪽 지시등을 켰어요")

    def test_not_applicable(self):
        """진행 방향이 회전·진로 변경이 아니거나 정해지지 않으면 계산하지 않음"""
        self.assertIsNone(self.run_rule("straight", turn=on("RIGHT", -6000, 9999)))
        self.assertIsNone(self.run_rule(None, turn=on("RIGHT", -6000, 9999)))
        self.assertIsNone(self.run_rule("reverse"))

    def test_gap_undetermined(self):
        r = self.run_rule(turn=on("RIGHT", -6000, 9999), drop=[(-6000, -3500)])
        self.assertFalse(r["determined"])
        self.assertIsNone(r["model_guess"])
        self.assertEqual(r["guess_evidence"], "사고 전 기록이 2초 넘게 끊긴 곳이 있어요")
        # 정확히 2초 간격은 빈 곳이 아님
        self.assertTrue(self.run_rule(turn=on("RIGHT", -6000, 9999), drop=[(-6000, -4000)])["determined"])

    def test_signal_all_null_undetermined(self):
        r = self.run_rule(turn=None)
        self.assertFalse(r["determined"])
        self.assertEqual(r["guess_evidence"], "사고 전 지시등 기록이 없어요")

    def test_speed_all_null_undetermined(self):
        r = self.run_rule(speed=None, turn=on("RIGHT", -6000, 9999))
        self.assertFalse(r["determined"])
        self.assertIn("속도 기록이 없어", r["guess_evidence"])

    def test_lead_function(self):
        self.assertEqual(rules.lead_ms(20), 5000)      # 5.4초 → 5초
        self.assertEqual(rules.lead_ms(30), 3600)
        self.assertEqual(rules.lead_ms(50), 2160)
        self.assertEqual(rules.lead_ms(60), 2000)      # 1.8초 → 2초
        self.assertEqual(rules.lead_ms(100), 2000)
        self.assertEqual(rules.lead_ms(0.5), 5000)     # 거의 서 있음
        self.assertEqual(rules.lead_ms(0), 5000)
        self.assertIsNone(rules.lead_ms(None))

    def test_lead_by_speed(self):
        """속도별 LEAD 경계: 켬 시작이 T - LEAD와 같으면 켰음, 0.1초 늦으면 늦음"""
        for v, lead in ((20, 5000), (30, 3600), (50, 2200), (60, 2000), (0, 5000)):
            with self.subTest(v=v):
                ok = self.run_rule(speed=float(v), turn=on("RIGHT", -lead, 9999))
                late = self.run_rule(speed=float(v), turn=on("RIGHT", -lead + 100, 9999))
                self.assertIs(ok["value"], True)
                self.assertIs(late["value"], False)
                self.assertIn("전에야", late["evidence"]["text"])
        r = self.run_rule(speed=0.0, turn=on("RIGHT", -4900, 9999))
        self.assertEqual(r["evidence"]["text"],
                         "사고 4.9초 전에야 오른쪽 지시등을 켰어요 (거의 서 있어서 5초 전에는 켜야 해요)")

    def test_lead_speed_window(self):
        """평균 속도 구간: manual [-5000, -500], hard_brake [-5000, -1500]"""
        speed = pieces((-5000, -1500, 20.0), default=100.0)
        hb = self.run_rule(source="hard_brake", speed=speed, turn=on("RIGHT", -6000, 9999))
        self.assertEqual(hb["params"]["lead_ms"], 5000)
        self.assertAlmostEqual(hb["params"]["v_avg_kmh"], 20.0)
        mn = self.run_rule(source="manual", speed=speed, turn=on("RIGHT", -6000, 9999))
        self.assertAlmostEqual(mn["params"]["v_avg_kmh"], (3500 * 20 + 1000 * 100) / 4500, places=1)

    def test_blink_true(self):
        r = self.run_rule(turn=blink("RIGHT", -6000, 9999))
        self.assertIs(r["value"], True)
        self.assertEqual(r["evidence"]["points"][0]["t"], T - 6000)

    def test_blink_merge_boundary(self):
        """30km/h (LEAD 3.6초): 앞 켜짐과 1.5초 끊김이면 이어서 6초 전 켬, 1.6초 끊김이면 3.4초 전 켬(늦음)"""
        merged = self.run_rule(speed=30.0, turn=pieces((-6000, -5000, "RIGHT"), (-3500, 9999, "RIGHT"),
                                                      default="OFF"))
        self.assertIs(merged["value"], True)
        self.assertEqual(merged["evidence"]["points"][0]["t"], T - 6000)
        split = self.run_rule(speed=30.0, turn=pieces((-6000, -5000, "RIGHT"), (-3400, 9999, "RIGHT"),
                                                     default="OFF"))
        self.assertIs(split["value"], False)
        self.assertEqual(split["evidence"]["text"],
                         "사고 3.4초 전에야 오른쪽 지시등을 켰어요 (평균 30km/h라 3.6초 전에는 켜야 해요)")

    def test_hard_brake_excludes_last_1500(self):
        """hard_brake면 [-1500, 0]은 보지 않음. 그 구간에만 켜졌으면 제외했다고 알림"""
        r = self.run_rule(source="hard_brake", turn=on("RIGHT", -1400, 9999))
        self.assertIs(r["value"], False)
        self.assertEqual(r["evidence"]["text"], "사고 직전 1.5초 안에만 켜져 판단에서 제외했어요")
        self.assertEqual(r["evidence"]["window"], {"from": T - 10000, "to": T - 1500})
        self.assertEqual(r["evidence"]["points"], [{"t": T - 1400, "key": "turnSignal", "value": "RIGHT"}])
        # 직전 1.5초에 반대 방향만 켜졌으면 안 켠 것
        r = self.run_rule(source="hard_brake", turn=on("LEFT", -1400, 9999))
        self.assertEqual(r["evidence"]["text"], "사고 전 10초 동안 오른쪽 지시등을 켜지 않았어요")
        # 앞 구간에 반대 방향을 켰으면 그 근거가 먼저
        r = self.run_rule(source="hard_brake",
                          turn=pieces((-6000, -4000, "LEFT"), (-1400, 9999, "RIGHT"), default="OFF"))
        self.assertEqual(r["evidence"]["text"], "오른쪽이 아니라 왼쪽 지시등을 켰어요")
        r = self.run_rule(source="manual", turn=on("RIGHT", -1400, 9999))
        self.assertTrue(r["evidence"]["text"].startswith("사고 1.4초 전에야"))
        # 남은 구간에서 1초 이상 켜져 있으면 켰음
        r = self.run_rule(source="hard_brake", turn=on("RIGHT", -3000, 9999))
        self.assertIs(r["value"], True)
        self.assertEqual(r["evidence"]["text"], "사고 3초 전 오른쪽 지시등 켜짐 (사고 때까지 켜져 있음)")


# ---------- slowed_v0 (4.5) ----------

class Slowed(unittest.TestCase):
    def run_rule(self, source="manual", **kw):
        tl, ctx = setup(build(**kw), source)
        return rules.slowed(tl, ctx)

    def test_stop_true(self):
        r = self.run_rule(speed=pieces((-99999, -3500, 30.0), (-3500, -2000, 0.0), default=10.0),
                          brake=on(True, -4000, -2000, base=False))
        self.assertTrue(r["determined"])
        self.assertIs(r["value"], True)
        self.assertEqual(r["field"], "parties.ego.slowed_before_entry")
        self.assertEqual(r["rule"], "slowed_v0")
        self.assertIs(r["facts"]["stopped_before_entry"], True)
        self.assertEqual(r["evidence"]["text"], "진입 전 1초 동안 멈췄어요")
        self.assertEqual(r["evidence"]["window"], {"from": T - 6000, "to": T - 500})

    def test_stop_needs_half_second(self):
        speed = pieces((-3000, -2600, 0.0), default=40.0)
        r = self.run_rule(speed=speed)
        self.assertNotIn("stopped_before_entry", r["facts"])
        speed = pieces((-3000, -2500, 0.0), default=40.0)
        self.assertIs(self.run_rule(speed=speed)["facts"]["stopped_before_entry"], True)

    def test_slowed_with_brake_true(self):
        r = self.run_rule(source="hard_brake",
                          speed=lambda x: 0.0 if x >= -1500 else ramp(38.0, 21.0, -3000, -2000)(x),
                          brake=lambda x: -3000 <= x < -1900 or x >= -1500)
        self.assertIs(r["value"], True)
        self.assertNotIn("stopped_before_entry", r["facts"])
        self.assertEqual(r["evidence"]["text"], "사고 3초 전 38km/h → 직전 21km/h로 줄였어요 (브레이크 1.1초)")
        self.assertEqual(r["evidence"]["window"], {"from": T - 6000, "to": T - 1500})

    def test_slowed_to_15_true(self):
        r = self.run_rule(speed=pieces((-3000, 99999, 15.0), default=20.0))
        self.assertIs(r["value"], True)
        self.assertEqual(r["evidence"]["text"], "사고 3초 전 20km/h → 직전 15km/h로 줄였어요")

    def test_no_slowdown_false(self):
        r = self.run_rule()
        self.assertTrue(r["determined"])
        self.assertIs(r["value"], False)
        self.assertEqual(r["evidence"]["text"], "사고 직전까지 브레이크 없이 40km/h 안팎으로 달렸어요")

    def test_false_boundary(self):
        """v_pre ≥ 0.9 × v_ref 경계"""
        self.assertIs(self.run_rule(speed=pieces((-3000, 99999, 36.0), default=40.0))["value"], False)
        r = self.run_rule(speed=pieces((-3000, 99999, 35.9), default=40.0))
        self.assertFalse(r["determined"])
        self.assertIs(r["model_guess"], True)
        self.assertEqual(r["guess_source"], "vehicle")
        self.assertEqual(r["guess_evidence"], "사고 3초 전 40km/h → 직전 36km/h로 줄였어요")
        # 20km/h 미만이면 false가 아님
        r = self.run_rule(speed=18.0)
        self.assertFalse(r["determined"])
        self.assertIs(r["model_guess"], False)
        self.assertEqual(r["guess_evidence"], "사고 직전까지 18km/h 안팎으로 달렸어요")

    def test_ambiguous_undetermined(self):
        """0.7배 아래로 줄였지만 브레이크가 0.5초 미만"""
        r = self.run_rule(speed=pieces((-3000, 99999, 25.0), default=40.0), brake=on(True, -3000, -2700, base=False))
        self.assertFalse(r["determined"])
        self.assertIs(r["model_guess"], True)
        self.assertEqual(r["guess_evidence"], "사고 3초 전 40km/h → 직전 25km/h로 줄였어요 (브레이크 0.3초)")
        r = self.run_rule(speed=pieces((-3000, 99999, 25.0), default=40.0), brake=on(True, -3000, -2500, base=False))
        self.assertIs(r["value"], True)

    def test_brake_unknown_not_false(self):
        r = self.run_rule(brake=None)
        self.assertFalse(r["determined"])
        self.assertIs(r["model_guess"], False)

    def test_hard_brake_excludes_last_1500(self):
        """충돌 직전 급제동(-1.5초부터 0km/h)은 hard_brake면 빼고, manual이면 진입 전 정지로 보임"""
        speed = pieces((-1500, 99999, 0.0), default=40.0)
        brake = on(True, -1500, 99999, base=False)
        hb = self.run_rule(source="hard_brake", speed=speed, brake=brake)
        self.assertIs(hb["value"], False)
        mn = self.run_rule(source="manual", speed=speed, brake=brake)
        self.assertIs(mn["value"], True)
        self.assertIs(mn["facts"]["stopped_before_entry"], True)

    def test_gap_undetermined(self):
        r = self.run_rule(drop=[(-5000, -2500)])
        self.assertFalse(r["determined"])
        self.assertEqual(r["guess_evidence"], "사고 전 기록이 2초 넘게 끊긴 곳이 있어요")

    def test_entry_speed_recorded(self):
        r = self.run_rule(speed=ramp(50.0, 20.0, -6000, 0))
        self.assertAlmostEqual(r["facts"]["intersection_entry_speed_kmh"], 35.0)


# ---------- reverse_v0 (4.2) ----------

class Reverse(unittest.TestCase):
    def run_rule(self, **kw):
        tl, ctx = setup(build(speed=5.0, **kw))
        return rules.reverse(tl, ctx)

    def test_confirmed(self):
        r = self.run_rule(gear=on("R", -2400, 9999, base="D"))
        self.assertTrue(r["determined"])
        self.assertEqual((r["field"], r["value"], r["rule"]), ("parties.ego.movement", "reverse", "reverse_v0"))
        self.assertEqual(r["evidence"]["text"], "사고 직전 3초 중 2.4초 동안 기어가 R(후진)이었어요")
        self.assertEqual(r["evidence"]["window"], {"from": T - 3000, "to": T})
        self.assertEqual(r["preselect"], {"situation.special": ["reverse:ego"]})

    def test_60_percent_boundary(self):
        self.assertTrue(self.run_rule(gear=on("R", -1800, 9999, base="D"))["determined"])
        r = self.run_rule(gear=on("R", -1700, 9999, base="D"))
        self.assertFalse(r["determined"])
        self.assertEqual(r["model_guess"], "reverse")
        self.assertEqual(r["guess_evidence"], "사고 직전 3초 중 1.7초 동안 기어가 R(후진)이었어요")

    def test_r_before_t_guess_only(self):
        """60% 넘게 R이어도 사고 때 R이 아니면 확정 안 함"""
        r = self.run_rule(gear=on("R", -3000, -200, base="D"))
        self.assertFalse(r["determined"])
        self.assertEqual(r["guess_evidence"], "사고 0.2초 전까지 후진 기어였어요")
        r = self.run_rule(gear=on("R", -5000, -2000, base="D"))
        self.assertFalse(r["determined"])
        self.assertEqual(r["model_guess"], "reverse")
        self.assertEqual(r["guess_source"], "vehicle")
        self.assertEqual(r["guess_evidence"], "사고 2초 전까지 후진 기어였어요")

    def test_no_r(self):
        self.assertIsNone(self.run_rule())
        self.assertIsNone(self.run_rule(gear=on("R", -5000, -3000, base="D")))   # 구간 밖

    def test_gap(self):
        r = self.run_rule(gear="R", drop=[(-3500, -1000)])
        self.assertFalse(r["determined"])
        self.assertIsNone(r["model_guess"])


# ---------- movement_v0 (4.3) ----------

class Movement(unittest.TestCase):
    def run_rule(self, **kw):
        tl, ctx = setup(build(**kw))
        return rules.movement(tl, ctx)

    def test_1_reverse_confirmed(self):
        r = self.run_rule(speed=5.0, gear=on("R", -2400, 9999, base="D"), turn=on("RIGHT", -6000, 9999))
        self.assertTrue(r["determined"])
        self.assertEqual((r["value"], r["rule"]), ("reverse", "reverse_v0"))

    def test_1b_reverse_guess_before_signal(self):
        r = self.run_rule(speed=5.0, gear=on("R", -5000, -2000, base="D"), turn=on("LEFT", -6000, 9999))
        self.assertFalse(r["determined"])
        self.assertEqual((r["model_guess"], r["rule"]), ("reverse", "movement_v0"))
        self.assertEqual(r["guess_evidence"], "사고 2초 전까지 후진 기어였어요")

    def test_2_left(self):
        r = self.run_rule(turn=on("LEFT", -6000, 9999))
        self.assertFalse(r["determined"])
        self.assertEqual(r["field"], "parties.ego.movement")
        self.assertEqual(r["model_guess"], "left_turn")
        self.assertEqual(r["guess_source"], "vehicle")
        self.assertEqual(r["guess_evidence"], "사고 6초 전부터 왼쪽 지시등이 켜져 있었어요")

    def test_2_left_needs_one_second_before_cut(self):
        """[-8000, -1500] 안에서 1초 이상"""
        self.assertEqual(self.run_rule(turn=on("LEFT", -2500, 9999))["model_guess"], "left_turn")
        self.assertIsNone(self.run_rule(turn=on("LEFT", -2400, 9999))["model_guess"])
        self.assertEqual(self.run_rule(turn=blink("LEFT", -6000, 9999))["model_guess"], "left_turn")

    def test_3_right(self):
        r = self.run_rule(turn=on("RIGHT", -6000, 9999))
        self.assertEqual(r["model_guess"], "right_turn")
        self.assertEqual(r["guess_evidence"], "사고 6초 전부터 오른쪽 지시등이 켜져 있었어요")

    def test_both_sides_no_guess(self):
        """좌우가 둘 다 1초 이상 켜졌으면 방향 추정 안 함 (비상등일 수 있음)"""
        for turn in (pieces((-7000, -5500, "RIGHT"), (-4000, 9999, "LEFT"), default="OFF"),
                     pieces((-7000, -5500, "LEFT"), (-4000, 9999, "RIGHT"), default="OFF")):
            r = self.run_rule(turn=turn)
            self.assertFalse(r["determined"])
            self.assertIsNone(r["model_guess"])
            self.assertIsNone(r["guess_source"])
            self.assertEqual(r["guess_evidence"], "양쪽 지시등이 함께 켜졌어요(비상등 가능성)")
        # 한쪽이 1초 미만이면 다른 쪽으로 추정
        turn = pieces((-7000, -6100, "RIGHT"), (-4000, 9999, "LEFT"), default="OFF")
        self.assertEqual(self.run_rule(turn=turn)["model_guess"], "left_turn")

    def test_both_sides_keeps_stationary_fact(self):
        """비상등 켜고 서 있던 경우: 방향 추정은 없고 서 있었음 사실은 넘김"""
        turn = pieces((-8000, -5000, "LEFT"), (-5000, 9999, "RIGHT"), default="OFF")
        r = self.run_rule(speed=0.0, turn=turn)
        self.assertIsNone(r["model_guess"])
        self.assertEqual(r["guess_evidence"], "양쪽 지시등이 함께 켜졌어요(비상등 가능성)")
        self.assertEqual(r["facts"], {"stationary_at_collision": True})

    def test_4_stationary(self):
        r = self.run_rule(speed=pieces((-3000, 99999, 1.5), default=30.0), gear="D")
        self.assertFalse(r["determined"])
        self.assertIsNone(r["model_guess"])
        self.assertEqual(r["facts"], {"stationary_at_collision": True})
        self.assertEqual(r["guess_evidence"], "사고 때 내 차는 서 있었어요")
        self.assertEqual(self.run_rule(speed=0.0, gear="P")["facts"], {"stationary_at_collision": True})
        # 2km/h 넘은 순간이 있으면 아님
        speed = pieces((-3000, -2900, 2.5), (-2900, 99999, 0.0), default=30.0)
        self.assertEqual(self.run_rule(speed=speed)["facts"], {})
        # 기어를 모르면 아님
        self.assertEqual(self.run_rule(speed=0.0, gear=None)["facts"], {})

    def test_4_before_5(self):
        """서 있었으면 지시등이 없어도 직진 추정 안 함"""
        r = self.run_rule(speed=pieces((-3000, 99999, 0.0), default=40.0))
        self.assertIsNone(r["model_guess"])

    def test_5_straight(self):
        r = self.run_rule(speed=15.0)
        self.assertEqual(r["model_guess"], "straight")
        self.assertEqual(r["guess_evidence"], "사고 전 8초 동안 지시등을 켜지 않고 달렸어요")
        self.assertIsNone(self.run_rule(speed=14.9)["model_guess"])
        # 마지막 1.5초에 켠 지시등도 직진 추정을 막음 ([-8000, 0])
        r = self.run_rule(turn=on("LEFT", -1000, 9999))
        self.assertIsNone(r["model_guess"])

    def test_6_other(self):
        r = self.run_rule(turn=None)
        self.assertFalse(r["determined"])
        self.assertIsNone(r["model_guess"])
        self.assertIsNone(r["guess_source"])
        self.assertEqual(r["rule"], "movement_v0")


# ---------- lane_change_dir_v0 (4.6) ----------

class LaneChangeDir(unittest.TestCase):
    def run_rule(self, movement="lane_change", **kw):
        tl, ctx = setup(build(**kw))
        return rules.lane_change_dir(tl, ctx, movement)

    def test_one_side(self):
        r = self.run_rule(turn=on("LEFT", -6000, 9999))
        self.assertTrue(r["determined"])
        self.assertEqual((r["field"], r["value"], r["rule"]),
                         ("parties.ego.lane_change_dir", "left", "lane_change_dir_v0"))
        self.assertEqual(r["evidence"]["text"], "사고 6초 전 왼쪽 지시등을 켰어요")
        self.assertEqual(r["evidence"]["window"], {"from": T - 8000, "to": T - 1500})
        self.assertEqual(self.run_rule(turn=on("RIGHT", -3000, 9999))["value"], "right")

    def test_both_or_none(self):
        turn = pieces((-7000, -6000, "LEFT"), (-4000, 9999, "RIGHT"), default="OFF")
        self.assertFalse(self.run_rule(turn=turn)["determined"])
        self.assertFalse(self.run_rule()["determined"])
        self.assertFalse(self.run_rule(turn=on("LEFT", -1000, 9999))["determined"])   # 구간 밖

    def test_not_lane_change(self):
        self.assertIsNone(self.run_rule("left_turn", turn=on("LEFT", -6000, 9999)))

    def test_gap(self):
        r = self.run_rule(turn=on("LEFT", -6000, 9999), drop=[(-6000, -3000)])
        self.assertFalse(r["determined"])
        self.assertEqual(r["guess_evidence"], "사고 전 기록이 2초 넘게 끊긴 곳이 있어요")


# ---------- 묶어 돌리기 ----------

class RunRules(unittest.TestCase):
    def test_turn_signal_needs_movement(self):
        tl, ctx = setup(build(turn=on("RIGHT", -6000, 9999)))
        by = {r["rule"]: r for r in rules.run_rules(tl, ctx)}
        self.assertEqual(by["movement_v0"]["model_guess"], "right_turn")
        self.assertNotIn("turn_signal_v0", by)     # 추정값만으로는 계산하지 않음
        self.assertIn("slowed_v0", by)
        by = {r["rule"]: r for r in rules.run_rules(tl, ctx, {"parties.ego.movement": "right_turn"})}
        self.assertIs(by["turn_signal_v0"]["value"], True)

    def test_lane_change_dir_feeds_turn_signal(self):
        tl, ctx = setup(build(turn=on("LEFT", -6000, 9999)))
        by = {r["rule"]: r for r in rules.run_rules(tl, ctx, {"parties.ego.movement": "lane_change"})}
        self.assertEqual(by["lane_change_dir_v0"]["value"], "left")
        self.assertIs(by["turn_signal_v0"]["value"], True)
        # 사용자가 방향을 다르게 답하면 사용자 답으로 계산
        by = {r["rule"]: r for r in rules.run_rules(tl, ctx, {"parties.ego.movement": "lane_change",
                                                              "parties.ego.lane_change_dir": "right"})}
        self.assertIs(by["turn_signal_v0"]["value"], False)

    def test_auto_answer_shape(self):
        """3절 자동 답변 모양"""
        tl, ctx = setup(build(turn=on("RIGHT", -6000, 9999)))
        a = rules.auto_answer(rules.turn_signal(tl, ctx, "right_turn"))
        self.assertEqual(set(a), {"field", "value", "source", "rule", "evidence"})
        self.assertEqual(set(a["evidence"]), {"text", "window", "points"})
        self.assertIsNone(rules.auto_answer(rules.turn_signal(Timeline(build(turn=None)), ctx, "right_turn")))


if __name__ == "__main__":
    unittest.main()
