"""변환기(adapter.py)가 규칙·수정요소 파일이 쓰는 사실값을 모두 엔진에 넘기는지 — hmtm-0.1.0

변환기는 OPTIONAL_PARTY_FIELDS(당사자)와 SCENE_FIELDS(장소)에 있는 이름만 넘긴다.
규칙 파일이 새 fact를 쓰는데 목록에 없으면 영상·사용자 값이 엔진에 닿지 않아 늘 "판단 불가"가 된다.
"""
import json
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import adapter  # noqa: E402
from fault_engine import CATEGORIES, detect_category  # noqa: E402

# 변환기가 OPTIONAL_PARTY_FIELDS 밖에서 직접 만드는 당사자 필드
ADAPTER_PARTY_FIELDS = {"track_id", "cls", "origin_zone", "movement", "heading", "intersection_entry_t",
                        "entry_speed", "entry_lead_sec", "entry_speed_ratio", "entry_speed_to_limit",
                        "speed_over_limit_kmh", "entry_from"}
# 변환기가 SCENE_FIELDS 밖에서 직접 만드는 facts 수준 경로
ADAPTER_FACTS_PATHS = {"scene.road_class", "signal.state"}


def _walk(x, out, facts_level=False):
    """조건 안의 (facts 수준인지, fact 이름)을 모두 모은다. 도표 applies_when.scene은 facts 수준"""
    if isinstance(x, dict):
        if isinstance(x.get("fact"), str):
            out.add((facts_level or x.get("of") == "facts", x["fact"]))
        for k, v in x.items():
            _walk(v, out, facts_level or k == "scene")
    elif isinstance(x, list):
        for v in x:
            _walk(v, out, facts_level)


def used_facts(names):
    out = set()
    for name in names:
        doc = json.loads((BASE / name).read_text(encoding="utf-8"))
        for key in ("rules", "global_modifiers", "modifiers"):
            _walk(doc.get(key, []), out)
    return out


def category_files():
    files = ["modifiers.json"]
    for spec in CATEGORIES.values():
        files.append(spec["rules"])
        if spec.get("extra_modifiers"):
            files.append(spec["extra_modifiers"])
    return files


class AdapterFieldsTest(unittest.TestCase):
    def test_party_fields_passed(self):
        passed = set(adapter.OPTIONAL_PARTY_FIELDS) | ADAPTER_PARTY_FIELDS
        missing = sorted({f for lvl, f in used_facts(category_files()) if not lvl and f.split(".")[0] not in passed})
        self.assertEqual(missing, [], "OPTIONAL_PARTY_FIELDS에 없는 당사자 fact")

    def test_scene_fields_passed(self):
        passed = {f"scene.{k}" for k in adapter.SCENE_FIELDS} | ADAPTER_FACTS_PATHS
        missing = sorted({f for lvl, f in used_facts(category_files()) if lvl and f not in passed})
        self.assertEqual(missing, [], "SCENE_FIELDS에 없는 장소 fact")

    def test_no_duplicate_names(self):
        self.assertEqual(len(adapter.OPTIONAL_PARTY_FIELDS), len(set(adapter.OPTIONAL_PARTY_FIELDS)))
        self.assertEqual(len(adapter.SCENE_FIELDS), len(set(adapter.SCENE_FIELDS)))

    def _raw(self, cls_b, road=None, party_b=None):
        return {"schema_version": "0.3", "video": "t", "road": road or {},
                "parties": {"1": {"cls": "car"}, "2": {"cls": cls_b, **(party_b or {})}},
                "collision": {"a": 1, "b": 2}}

    def test_pedestrian_cls_reaches_engine(self):
        # A의 클래스 이름은 pedestrian, 엔진은 person
        facts, _ = adapter.to_engine_facts(self._raw("pedestrian"))
        self.assertEqual(facts["vehicles"][1]["cls"], "person")
        self.assertEqual(detect_category(facts)[0], "car_pedestrian")

    def test_bicycle_and_farm_machine_cls(self):
        for cls in ("bicycle", "farm_machine"):
            facts, _ = adapter.to_engine_facts(self._raw(cls))
            self.assertEqual(detect_category(facts)[0], "car_bicycle", cls)

    def test_new_fields_pass_through(self):
        facts, _ = adapter.to_engine_facts(self._raw(
            "pedestrian", road={"crosswalk_signal": {"value": True, "source": "model"}, "protection_zone": "child"},
            party_b={"ped_place": {"value": "crosswalk", "source": "user"}, "vulnerable_type": "child"}))
        self.assertEqual(facts["scene"]["crosswalk_signal"], True)
        self.assertEqual(facts["scene"]["protection_zone"], "child")
        b = facts["vehicles"][1]
        self.assertEqual((b["ped_place"], b["vulnerable_type"]), ("crosswalk", "child"))
        self.assertEqual(b["_sources"]["ped_place"], "user")


class ChapterAnswersTest(unittest.TestCase):
    """A 질문(src/app/chapters.py) 답 → 엔진 이름 (hmtm-0.1.1)"""

    def convert(self, cls_b="pedestrian", **answers):
        raw = {"schema_version": "0.3", "video": "t",
               "parties": {"1": {"cls": "car"}, "2": {"cls": cls_b}}, "collision": {"a": 1, "b": 2}}
        facts, _ = adapter.to_engine_facts(raw, {"parties": {"2": answers}})
        return facts["vehicles"][1]

    def test_crossing_place_to_ped_place(self):
        for place, expect in (("on_crosswalk", "crosswalk"), ("near_crosswalk", "near_crosswalk")):
            b = self.convert(crossing_place=place)
            self.assertEqual(b["ped_place"], expect, place)
            self.assertEqual(b["_sources"]["ped_place"], "user")

    def test_ambiguous_places_left_unknown(self):
        # 횡단보도 없는 차도(교차로·단일로·차도 보행), 보도·길 가장자리는 엔진 값 하나로 못 정함 → 추측하지 않음
        for place in ("carriageway", "sidewalk"):
            self.assertIsNone(self.convert(crossing_place=place)["ped_place"], place)

    def test_not_for_bicycle(self):
        self.assertIsNone(self.convert("bicycle", crossing_place="on_crosswalk")["ped_place"])

    def test_engine_name_wins(self):
        self.assertEqual(self.convert(crossing_place="on_crosswalk", ped_place="near_crosswalk")["ped_place"],
                         "near_crosswalk")

    def test_ped_signal_value(self):
        self.assertEqual(self.convert(ped_signal_at_crossing="green_flashing")["ped_signal_at_crossing"], "flashing_green")
        self.assertEqual(self.convert(ped_signal_at_crossing="red")["ped_signal_at_crossing"], "red")   # 차53-1
        # 하나의 답을 횡단 시작·충격 때 신호 둘로 나누지 않음 (A 요청 사항)
        b = self.convert(ped_signal_at_crossing="red")
        self.assertIsNone(b["ped_signal_at_start"])
        self.assertIsNone(b["ped_signal_at_impact"])


if __name__ == "__main__":
    unittest.main()
