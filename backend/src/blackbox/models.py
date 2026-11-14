"""가중치 목록(backend/models.json, 형식 hmtm-models-1) 검사 (docs/design-blackbox.md 1.6)

  report = check()          # {역할: {"status", "path", "message", ...}}
  ready, message = detector_ready(report)

역할마다 실제로 쓸 파일(video_analyzer의 환경변수·기본 경로)을 목록의 sha256·크기와 대조한다.
  ok             목록에 등록돼 있고(sha256·version이 있음) 파일이 있으며 크기·sha256이 같음
  missing        등록돼 있는데 파일이 없음
  mismatch       파일은 있는데 크기나 sha256이 다름
  unregistered   목록에 version이나 sha256이 null (아직 전달 안 된 모델) → 그 모델을 쓰는 단계만 건너뜀

탐지(detector)가 ok가 아니면 분석기는 "준비 안 됨"(AnalyzerNotReady). 나머지 등록된 모델이 missing·mismatch여도 준비 안 됨
(목록과 다른 가중치로 결과를 내지 않음). sha256은 (경로, 크기, 수정 시각)이 같으면 다시 계산하지 않는다.
HMTM_BB_MODEL_CHECK=0이면 검사하지 않는다 (A가 목록에 없는 가중치로 실험할 때만).
"""
import hashlib
import json
import os
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # backend/
LIST_PATH = os.path.join(ROOT, "models.json")
SCHEMA = "hmtm-models-1"
ROLES = ("detector", "kind", "scene", "crosswalk")
ROLE_NAMES = {"detector": "탐지 모델", "kind": "상대 종류 모델", "scene": "교차로 형태 모델(M6)", "crosswalk": "횡단보도 모델(M5)"}
REQUIRED = ("detector",)        # 없으면 분석 자체를 못 함
CHECK_ENV = "HMTM_BB_MODEL_CHECK"
# 역할 → video_analyzer 모듈 전역 (경로). 환경변수로 바꾼 경로도 이 전역에 들어 있다
ATTRS = {"detector": "BB_MODEL", "kind": "KIND_MODEL", "scene": "SCENE_MODEL", "crosswalk": "CROSSWALK_MODEL"}
SKIPPED_PATH = os.path.join(ROOT, "models", "__unregistered__.pt")   # 등록 안 된 모델 자리 (없는 파일 → 그 단계가 건너뜀)

_hash_cache = {}
_lock = threading.Lock()


class ListInvalid(Exception):
    pass


def load(path=None):
    """models.json 읽기 + 모양 검사. 틀리면 ListInvalid"""
    path = path or LIST_PATH
    try:
        with open(path, encoding="utf-8") as fp:
            d = json.load(fp)
    except (OSError, ValueError) as e:
        raise ListInvalid(f"가중치 목록을 읽지 못했어요: {e}")
    if not isinstance(d, dict) or d.get("schema") != SCHEMA or not isinstance(d.get("models"), dict):
        raise ListInvalid(f"가중치 목록 형식이 {SCHEMA}가 아니에요")
    for role in ROLES:
        m = d["models"].get(role)
        if not isinstance(m, dict) or not m.get("file"):
            raise ListInvalid(f"가중치 목록에 {role}.file이 없어요")
    return d


def registered(entry):
    return bool(entry.get("version")) and bool(entry.get("sha256"))


def sha256(path):
    st = os.stat(path)
    key = (os.path.abspath(path), st.st_size, st.st_mtime_ns)
    with _lock:
        if key in _hash_cache:
            return _hash_cache[key]
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    with _lock:
        _hash_cache[key] = h.hexdigest()
    return _hash_cache[key]


def check_one(role, entry, path):
    name = ROLE_NAMES.get(role, role)
    out = {"role": role, "file": entry.get("file"), "version": entry.get("version"), "path": path}
    if not registered(entry):
        return dict(out, status="unregistered", message=f"{name}은 아직 목록에 등록되지 않았어요 (그 단계는 건너뜀)")
    if not path or not os.path.isfile(path):
        return dict(out, status="missing", message=f"{name} 파일({path})이 없어요")
    size = os.path.getsize(path)
    if entry.get("size_bytes") is not None and size != entry["size_bytes"]:
        return dict(out, status="mismatch",
                    message=f"{name} 파일({path}) 크기가 목록과 달라요 ({size:,} ≠ {entry['size_bytes']:,}바이트)")
    if sha256(path) != entry["sha256"]:
        return dict(out, status="mismatch", message=f"{name} 파일({path})의 sha256이 목록과 달라요")
    return dict(out, status="ok", message=None)


def check(paths, list_path=None):
    """paths: {역할: 실제로 쓸 파일 경로}. 반환 {역할: 결과}. 목록이 틀리면 ListInvalid"""
    d = load(list_path)
    return {role: check_one(role, d["models"][role], paths.get(role)) for role in ROLES}


def problems(report):
    """준비 안 됨 이유 (없으면 []). 필수 모델은 ok여야 하고, 등록된 나머지는 ok여야 함"""
    out = []
    for role, r in report.items():
        if r["status"] in ("missing", "mismatch") or (role in REQUIRED and r["status"] != "ok"):
            out.append(r["message"])
    return out


def enabled():
    return os.environ.get(CHECK_ENV, "1") != "0"
