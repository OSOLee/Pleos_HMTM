"""B의 판정 모듈(judge/)을 불러 facts.json을 판정한다

judge/는 backend/judge에 있다. 그 폴더를 경로로 넘긴다.
  judge_dir = backend/judge   (pipeline.JUDGE_DIR)
"""
import os
import sys


def load(judge_dir):
    judge_dir = os.path.abspath(judge_dir)
    if not os.path.exists(os.path.join(judge_dir, "fault_engine.py")):
        raise SystemExit(f"판정 모듈을 찾지 못했어요: {judge_dir}")
    if judge_dir not in sys.path:
        sys.path.insert(0, judge_dir)
    import adapter
    import fault_engine
    with open(os.path.join(judge_dir, "VERSION"), encoding="utf-8") as f:
        version = f.read().strip()
    return adapter, fault_engine, version


def thresholds(judge_dir):
    """판정 모듈의 기준값 {이름: 값} (예: clear_lead_sec). A가 같은 숫자를 따로 갖지 않고 B 값을 따르려고 씀"""
    _, engine, _ = load(judge_dir)
    return {k: v.get("value") if isinstance(v, dict) else v for k, v in engine.load_rules().get("thresholds", {}).items()}


def judge(facts_path, assumptions, judge_dir):
    adapter, engine, version = load(judge_dir)
    raw = adapter.load_json(facts_path)
    facts, assumed = adapter.to_engine_facts(raw, assumptions)
    result = engine.judge(facts)   # 사고 유형(차대차·보행자·자전거)은 엔진이 충돌 당사자 차종으로 정함
    return {
        "video": facts.get("video"),
        "judge_version": version,
        "status": "ok" if result["supported"] else "no_rule",
        "assumptions": assumed,
        "result": result,
    }
