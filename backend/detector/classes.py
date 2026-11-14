"""탐지 클래스 정의 (M1 객체 탐지: 움직이는 4종). aihub_classes.json과 같은 순서

신호등은 M3(신호등 색 판별), 표지판은 M4, 횡단보도·차선은 M5(SegFormer) 담당이다.
차량은 승용차·트럭·버스를 하나로 묶는다 (차종은 M2 차종 분류 담당). 판정 모듈 변환기는 vehicle을 car로 읽는다.
"""

CLASSES = ["vehicle", "two_wheeler", "bicycle", "person"]
CLASS_ID = {name: i for i, name in enumerate(CLASSES)}

# COCO 사전학습 모델의 클래스 번호 -> 우리 클래스 번호 (학습 전 비교용)
COCO_TO_OURS = {
    2: CLASS_ID["vehicle"],      # car
    7: CLASS_ID["vehicle"],      # truck
    5: CLASS_ID["vehicle"],      # bus
    3: CLASS_ID["two_wheeler"],  # motorcycle
    1: CLASS_ID["bicycle"],      # bicycle
    0: CLASS_ID["person"],       # person
}
