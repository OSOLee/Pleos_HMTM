"""근거 화면 데이터 (GET /api/cases/{id}/evidence): 부딪힌 두 당사자의 궤적 박스와 사건 기록을 시간(초)으로.
앱이 영상 위에 박스·지나온 길을 겹쳐 그리고, 사건 기록을 누르면 그 장면으로 감 (B 앱 Evidence 모델과 같은 모양).
원본 영상은 내주지 않음 (개인정보). 앱은 휴대폰에 있는 원본을 틀고 그 위에 그림"""
import os

from src.app import pipeline


def load_if(path):
    return pipeline.load(path) if os.path.exists(path) else None


def build(case_dir, size):
    """size: (가로, 세로) 픽셀 (분석한 영상 기준). 판정 전이면 None"""
    app = load_if(os.path.join(case_dir, "app.json"))
    tf = load_if(os.path.join(case_dir, "tracks_final.json"))
    col = (app or {}).get("collision")
    if not col or tf is None:
        return None
    fps = tf["fps"]
    zones = load_if(os.path.join(case_dir, "zones.json")) or {}
    facts = load_if(os.path.join(case_dir, "facts.json")) or {}
    tracks, events = [], []
    for role, tid in (("a", col["a"]), ("b", col["b"])):
        tr = tf["tracks"].get(tid)
        if tr is None:   # 직접 표시한 당사자(9001~)는 궤적이 없을 수 있음
            continue
        tracks.append({"id": tid, "role": role, "cls": (facts.get("parties", {}).get(tid) or {}).get("cls", tr["cls"]),
                       "frames": [{"t": r["t"], "box": r["bbox"]} for r in tr["frames"]]})
        events.append({"t": tr["frames"][0]["t"], "type": "appear", "track": tid, "text": "화면에 나타남"})
        ent = zones.get("intersection_entries", {}).get(tid)
        if isinstance(ent, dict):
            events.append({"t": round(ent["frame"] / fps, 3), "type": "enter", "track": tid, "text": "교차로에 들어감"})
        stop = (facts.get("parties", {}).get(tid) or {}).get("stop_frame")
        if stop is not None and stop < col["frame"]:   # 부딪히기 전에 멈춘 것만 (부딪힌 뒤 멈춤은 당연해서 뺌)
            events.append({"t": round(stop / fps, 3), "type": "stop", "track": tid, "text": "멈춤"})
    events.append({"t": col["t"], "type": "collision", "track": None, "text": "충돌"})
    events.sort(key=lambda e: e["t"])
    last = max((tr["frames"][-1]["t"] for tr in tf["tracks"].values() if tr["frames"]), default=col["t"])
    w, h = size
    return {"duration": last, "fps": fps, "width": w, "height": h, "aspect": round(w / h, 4) if h else None,
            "collision_t": col["t"], "collision_frame": col["frame"], "tracks": tracks, "events": events}
