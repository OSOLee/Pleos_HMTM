"""시계 차이 경고 (docs/api-spec.md 6.1, 7절 "시계 차이 경고")

앱(차량) 시계·블랙박스 시계는 서버 시계와 비교하지 않고 그대로 쓰지만, 서버 시각과 하루 넘게 다르면 경고를 남긴다 (오류는 아님).
차량 사건과 블랙박스 사건이 같이 쓴다.

  warnings(server_ms, video_start_ms=, video_source=, vehicle_range=)  → [경고]

경고 한 줄: {"kind", "source", "t_ms", "server_ms", "diff_ms", "direction", "message"}
  kind       video_clock(영상 촬영 시각) / vehicle_clock(차량 기록 구간. 차량 사건의 t_event도 이 구간 안)
  source     시각 출처 (영상: filename / metadata / app / user / mtime, 차량: app)
  t_ms       비교한 시각. 차량 기록은 서버에 가까운 쪽 끝 (기록 구간이 서버 시각을 덮으면 경고 없음)
  diff_ms    t_ms − server_ms (앞서면 양수)
  direction  ahead(서버보다 미래) / behind(과거)
"""
DAY_MS = 86_400_000
LIMIT_MS = DAY_MS            # 이보다 크게 다르면 경고 (6.1 "하루 넘게")

SOURCE_TEXT = {"filename": "파일 이름", "metadata": "영상 정보", "app": "앱이 보낸 값", "user": "직접 고친 값",
               "mtime": "파일 수정 시각"}


def _days(ms):
    d = abs(ms) / DAY_MS
    return f"{d:.0f}일" if d >= 2 else f"{abs(ms) / 3_600_000:.0f}시간"


def _one(kind, source, t_ms, server_ms):
    diff = t_ms - server_ms
    if abs(diff) <= LIMIT_MS:
        return None
    ahead = diff > 0
    gap = _days(diff)
    if kind == "video_clock":
        where = f"영상 촬영 시각({SOURCE_TEXT.get(source, source)})"
        why = "블랙박스 시계가 틀렸을 수 있어요" if ahead else "오래된 영상이거나 블랙박스 시계가 틀렸을 수 있어요"
    else:
        where = "차량 기록 시각"
        why = "기기 시계가 틀렸을 수 있어요" if ahead else "오래된 기록이거나 기기 시계가 틀렸을 수 있어요"
    text = f"{where}이 서버 시각보다 {gap} {'미래예요' if ahead else '전이에요'}. {why}"
    return {"kind": kind, "source": source, "t_ms": t_ms, "server_ms": server_ms, "diff_ms": diff,
            "direction": "ahead" if ahead else "behind", "message": text}


def _nearest(rng, server_ms):
    """구간에서 서버 시각에 가장 가까운 끝 (구간 안이면 서버 시각 그대로 → 경고 없음)"""
    return min(max(server_ms, rng["from"]), rng["to"])


def warnings(server_ms, video_start_ms=None, video_source=None, vehicle_range=None):
    """서버 시각(ms)과 하루 넘게 다른 시각들. server_ms가 없으면 []"""
    if server_ms is None:
        return []
    out = []
    if video_start_ms is not None:
        out.append(_one("video_clock", video_source, video_start_ms, server_ms))
    if vehicle_range:
        out.append(_one("vehicle_clock", "app", _nearest(vehicle_range, server_ms), server_ms))
    return [w for w in out if w]
