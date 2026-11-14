"""질문의 근거 프레임을 JPG로 저장한다 (앱이 질문과 함께 보여 줌)"""
import os
import cv2
import numpy as np


PARTY_COLORS = [(0, 0, 255), (255, 128, 0)]   # 충돌 당사자 a 빨강, b 파랑 (BGR)
OTHER_COLOR = (0, 200, 0)                     # 그 밖의 객체 (부딪힌 쌍 질문의 보기) 초록


def draw_box(img, rec, label, color, placed):
    """궤적 한 프레임(rec)의 박스와 이름표를 그린다. 이름표는 박스 위(화면 밖이면 박스 안)에 두되,
    이미 그린 이름표(placed)와 겹치면 아래로 비켜 놓는다. 멀리 있는 차들이 몰려 있으면 이름표가 겹쳐서"""
    h, w = img.shape[:2]
    x, y, bw, bh = rec["bbox"]
    p1, p2 = (int(x * w), int(y * h)), (int((x + bw) * w), int((y + bh) * h))
    cv2.rectangle(img, p1, p2, color, 3)
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
    ty = p1[1] - 8 if p1[1] - th - 12 > 0 else p1[1] + th + 8
    box = lambda ty: (p1[0], ty - th - 6, p1[0] + tw + 8, ty + 6)
    hit = lambda b: any(b[0] < q[2] and q[0] < b[2] and b[1] < q[3] and q[1] < b[3] for q in placed)
    while hit(box(ty)) and ty < h - 6:
        ty += th + 14
    placed.append(box(ty))
    cv2.rectangle(img, box(ty)[:2], box(ty)[2:], color, -1)
    cv2.putText(img, label, (p1[0] + 4, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)


def save(video, frames, out_dir, tracks=None, show=None, parties=(), cls=None):
    """frames: 프레임 번호 목록. 반환: {프레임 번호: 저장 경로(out_dir 기준 상대 경로)}
    tracks·show를 주면 프레임마다 show[프레임]에 든 궤적의 박스와 "#id 종류"를 그린다
    (질문이 "1번 차량은..."이라고 부르는데 그림에 번호가 없으면 누군지 알 수 없어서).
    parties: 충돌 당사자 (a, b). 모든 그림에서 같은 색으로, 다른 객체보다 나중에(위에) 그린다
    cls: {궤적 id: 종류} 또는 {(프레임, 궤적 id): 글자}. 사용자가 종류를 답했거나 신호등 색을 적을 때 (없으면 궤적의 cls)"""
    os.makedirs(os.path.join(out_dir, "frames"), exist_ok=True)
    colors = dict(zip(parties, PARTY_COLORS))
    cap = cv2.VideoCapture(video)
    saved = {}
    for f in sorted(set(frames)):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, img = cap.read()
        if not ok:
            continue
        placed = []
        for tid in sorted((show or {}).get(f, []), key=lambda t: t in colors):   # 당사자를 마지막에
            rec = next((r for r in tracks[tid]["frames"] if r["frame"] == f), None)
            if rec:   # 그 프레임에 안 보이는 궤적은 그리지 않음
                name = (cls or {}).get((f, tid), (cls or {}).get(tid, tracks[tid]["cls"]))
                draw_box(img, rec, f"#{tid} {name}", colors.get(tid, OTHER_COLOR), placed)
        rel = os.path.join("frames", f"f{f:05d}.jpg")
        cv2.imwrite(os.path.join(out_dir, rel), img)
        saved[f] = rel
    cap.release()
    return saved


ZONE_COLORS = [(80, 200, 255), (120, 230, 120), (255, 180, 90), (220, 140, 255)]   # 진입로 4개 (BGR)


def zones_overlay(img, scene, zone_names):
    """진입로 영역을 반투명으로 칠하고 교차로 테두리를 그림. 반환: (그림, 이름표 목록). 이름표는 마지막에 그리도록
    따로 돌려줌 (위에 그리는 선·화살표에 가리지 않게)"""
    h, w = img.shape[:2]
    px = lambda p: (int(p[0] * w), int(p[1] * h))
    layer = img.copy()
    labels = []
    approaches = [z for z in scene["zones"] if z["type"] == "approach"]
    for k, z in enumerate(approaches):
        pts = np.array([px(p) for p in z["polygon"]], np.int32)
        cv2.fillPoly(layer, [pts], ZONE_COLORS[k % len(ZONE_COLORS)])
        # 이름표는 영역 안 화면에 보이는 점들의 가운데에
        inner = [p for p in z["polygon"] if 0 <= p[0] <= 1 and 0 <= p[1] <= 1] or z["polygon"]
        cx = min(max(sum(p[0] for p in inner) / len(inner), 0.05), 0.85)
        cy = min(max(sum(p[1] for p in inner) / len(inner), 0.05), 0.95)
        labels.append((zone_names.get(z.get("direction"), z["id"]), px((cx, cy)), ZONE_COLORS[k % len(ZONE_COLORS)]))
    img = cv2.addWeighted(layer, 0.35, img, 0.65, 0)
    for z in scene["zones"]:
        if z["type"] == "intersection":
            cv2.polylines(img, [np.array([px(p) for p in z["polygon"]], np.int32)], True, (0, 255, 255), 2)
    return img, labels


def draw_labels(img, labels):
    for text, (x, y), c in labels:
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
        cv2.rectangle(img, (x - 4, y - th - 8), (x + tw + 4, y + 6), (0, 0, 0), -1)
        cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, c, 2)


def read_frame(video, frame):
    cap = cv2.VideoCapture(video)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
    ok, img = cap.read()
    cap.release()
    return img if ok else None


def path_image(video, frame, scene, track, tid, color, zone_names, out_dir):
    """"어느 쪽 길에서 왔나요?", "어느 방향으로 가나요?" 질문용 그림. 진입로 영역을 반투명으로 칠하고 보기 이름
    (zone_names: {방위: "화면 위쪽 길"})을 적은 뒤, 그 당사자가 지나간 길을 화살표로 그린다.
    보기가 화면 기준 방위라서, 길이 대각선이면 어느 길이 "위쪽 길"인지 그림 없이는 알 수 없었음 (cc_190106, 180420)"""
    img = read_frame(video, frame)
    if img is None:
        return None
    h, w = img.shape[:2]
    px = lambda p: (int(p[0] * w), int(p[1] * h))
    img, labels = zones_overlay(img, scene, zone_names)
    pts = [px(r["pos"]) for r in track["frames"]]
    for a, b in zip(pts, pts[1:]):
        cv2.line(img, a, b, color, 4)
    if len(pts) >= 2:
        cv2.circle(img, pts[0], 10, color, -1)
        tail = pts[max(0, len(pts) - 6)]
        if tail != pts[-1]:
            cv2.arrowedLine(img, tail, pts[-1], color, 5, tipLength=0.6)
    draw_labels(img, labels)
    rec = next((r for r in track["frames"] if r["frame"] == frame), None)
    if rec:
        draw_box(img, rec, f"#{tid}", color, [])
    os.makedirs(os.path.join(out_dir, "frames"), exist_ok=True)
    rel = os.path.join("frames", f"path_{tid}.jpg")
    cv2.imwrite(os.path.join(out_dir, rel), img)
    return rel


LIGHT_COLOR = (255, 0, 255)   # 신호등 연결 질문에서 그 신호등 (자홍)
INSET_W = 0.22                # 확대 그림 폭 (화면 폭 비율)


def light_image(video, frame, scene, track, tid, zone_names, out_dir):
    """"N번 신호등은 어느 길의 신호인가요?" 질문용 그림. 진입로를 칠하고 이름을 적은 뒤, 그 신호등 박스를 표시하고
    오른쪽 위에 신호등 부분을 크게 확대해 붙인다. 신호등은 화면에서 아주 작아서(박스 수십 픽셀) 그대로는
    어느 쪽을 향하는지 알아보기 어려웠음 (cc_210819)"""
    img = read_frame(video, frame)
    rec = next((r for r in track["frames"] if r["frame"] == frame), None)
    if img is None or rec is None:
        return None
    h, w = img.shape[:2]
    raw = img.copy()
    img, labels = zones_overlay(img, scene, zone_names)
    draw_labels(img, labels)
    x, y, bw, bh = rec["bbox"]
    # 확대할 부분: 신호등 박스를 가운데 두고 박스의 4배 (주변 기둥·길이 같이 보이게)
    cx, cy, half = x + bw / 2, y + bh / 2, max(bw, bh) * 2
    x1, y1 = int(max(cx - half, 0) * w), int(max(cy - half, 0) * h)
    x2, y2 = int(min(cx + half, 1) * w), int(min(cy + half, 1) * h)
    crop = raw[y1:y2, x1:x2]
    p1, p2 = (int(x * w), int(y * h)), (int((x + bw) * w), int((y + bh) * h))
    cv2.rectangle(img, p1, p2, LIGHT_COLOR, 3)
    cv2.rectangle(img, (x1, y1), (x2, y2), LIGHT_COLOR, 1)
    if crop.size:
        iw = int(w * INSET_W)
        ih = max(1, int(iw * crop.shape[0] / crop.shape[1]))
        inset = cv2.resize(crop, (iw, ih), interpolation=cv2.INTER_CUBIC)
        ox, oy = w - iw - 10, 10
        ih = min(ih, h - oy - 10)
        img[oy:oy + ih, ox:ox + iw] = inset[:ih]
        cv2.rectangle(img, (ox, oy), (ox + iw, oy + ih), LIGHT_COLOR, 4)
        cv2.line(img, ((x1 + x2) // 2, y2), (ox, oy + ih), LIGHT_COLOR, 2)   # 확대 그림과 원래 자리를 이음
    draw_box(img, rec, f"light #{tid}", LIGHT_COLOR, [])
    os.makedirs(os.path.join(out_dir, "frames"), exist_ok=True)
    rel = os.path.join("frames", f"light_{tid}.jpg")
    cv2.imwrite(os.path.join(out_dir, rel), img)
    return rel


def objects_frame(video, tracks, out_dir):
    """움직이는 객체가 가장 많이 보이는 프레임에 객체마다 박스와 id를 그려 저장한다.
    충돌을 못 찾았을 때 사용자가 부딪힌 두 객체를 고르는 화면에 쓴다.
    반환: (저장 경로, 프레임 번호, 객체 목록)"""
    moving = {t: tr for t, tr in tracks.items() if tr["moving"] and tr["cls"] != "traffic_light"}
    by_f = {}
    for t, tr in moving.items():
        for r in tr["frames"]:
            by_f.setdefault(r["frame"], []).append((t, r))
    if not by_f:
        return None, None, []
    f = max(sorted(by_f), key=lambda k: len(by_f[k]))

    cap = cv2.VideoCapture(video)
    cap.set(cv2.CAP_PROP_POS_FRAMES, f)
    ok, img = cap.read()
    cap.release()
    if not ok:
        return None, f, []
    h, w = img.shape[:2]
    for t, r in by_f[f]:
        x, y, bw, bh = r["bbox"]
        p1, p2 = (int(x * w), int(y * h)), (int((x + bw) * w), int((y + bh) * h))
        cv2.rectangle(img, p1, p2, (0, 0, 255), 3)
        cv2.putText(img, t, (p1[0], max(p1[1] - 8, 30)), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
    os.makedirs(os.path.join(out_dir, "frames"), exist_ok=True)
    rel = os.path.join("frames", f"objects_f{f:05d}.jpg")
    cv2.imwrite(os.path.join(out_dir, rel), img)
    objs = [{"id": t, "cls": tr["cls"], "first_frame": tr["frames"][0]["frame"],
             "last_frame": tr["frames"][-1]["frame"], "in_image": t in dict(by_f[f])}
            for t, tr in sorted(moving.items(), key=lambda kv: int(kv[0]))]
    return rel, f, objs
