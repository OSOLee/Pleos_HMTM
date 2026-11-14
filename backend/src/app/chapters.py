"""당사자 종류로 본 과실비율 인정기준의 장 (자동차와 보행자 / 자동차와 자동차(이륜차 포함) / 자동차와 자전거(농기계 포함))

장을 골라 도표를 고르는 일은 판정 모듈(B)이 한다. B는 도표를 장별 파일(rules_vehicle.json, rules_bicycle.json,
rules_pedestrian.json)로 나눌 예정이다. A는 이 대응을 두 가지에만 쓴다.
  1. 그 장의 도표 파일이 판정 모듈에 있는지 보고, 없으면 판정 결과가 참고값이라고 알린다
     (지금은 자전거·보행자 사고도 자동차끼리 도표로 판정됨)
  2. 그 장의 도표가 생기면 보행자·자전거 사고에 필요한 사실(어디서 부딪혔는지, 보행자 신호)을 묻는다
"""
import os

CHAPTER_OF = {"pedestrian": "pedestrian", "bicycle": "bicycle", "farm_machine": "bicycle"}   # 나머지는 vehicle
NAMES = {"vehicle": "자동차와 자동차(이륜차 포함)", "bicycle": "자동차와 자전거(농기계 포함)",
         "pedestrian": "자동차와 보행자"}

PLACE_OPTIONS = ["on_crosswalk", "near_crosswalk", "carriageway", "sidewalk"]
PLACE_CHOICES = ["횡단보도 위", "횡단보도 부근", "횡단보도 없는 차도", "보도·길 가장자리"]
PED_SIGNAL_OPTIONS = ["green", "green_flashing", "red"]
PED_SIGNAL_CHOICES = ["초록", "초록 점멸", "빨강"]


def chapter(classes):
    """두 당사자 종류 → 장. 보행자가 있으면 보행자 장, 자전거·농기계가 있으면 자전거 장, 아니면 자동차 장"""
    found = {CHAPTER_OF.get(c, "vehicle") for c in classes}
    for ch in ("pedestrian", "bicycle"):
        if ch in found:
            return ch
    return "vehicle"


def ready(judge_dir, ch):
    """그 장의 도표가 판정 모듈에 있는지. 자동차 장은 지금 rules.json. 시험할 때는 MTM_CHAPTERS=bicycle,pedestrian"""
    if ch == "vehicle":
        return True
    forced = os.environ.get("MTM_CHAPTERS", "").split(",")
    return ch in forced or os.path.exists(os.path.join(judge_dir, f"rules_{ch}.json"))


def questions(tid, f0):
    """보행자·자전거·농기계 당사자에게 묻는 사실. 보행자 신호 색은 신호등이 있고 횡단보도 위·부근일 때만"""
    return [
        {"field": f"parties.{tid}.crossing_place",
         "question": "부딪힌 곳은 어디였나요?",
         "answer_type": "choice", "options": PLACE_OPTIONS, "choices": PLACE_CHOICES,
         "evidence_frame": f0},
        {"field": f"parties.{tid}.ped_signal_at_crossing",
         "question": "그때 보행자 신호는 무슨 색이었나요?",
         "answer_type": "choice", "options": PED_SIGNAL_OPTIONS, "choices": PED_SIGNAL_CHOICES,
         "depends_on": {"road.signal_present": True, f"parties.{tid}.crossing_place": ["on_crosswalk", "near_crosswalk"]},
         "evidence_frame": f0},
    ]
