#!/bin/bash
# 다른 탐지 모델(재학습 모델)로 평가 24개를 처음부터 다시 돌려 지금 결과와 비교한다
#
#   MTM_DETECTOR=models/cctv.pt [MTM_IMGSZ=960] bash tools/evaluate/compare_detector.sh cctv
#   → outputs/eval_cctv_auto, outputs/eval_cctv_tap, outputs/결과표_cctv_자동.md, outputs/결과표_cctv_답반영.md
#
# 자동: 저장된 모서리(scene.json)만 가져와서 탐지부터 다시 돈다.
# 답 반영: 지금 답(outputs/eval_tap/<영상>/answers.json)을 새 궤적 번호로 옮기고(tools/evaluate/remap_answers.py),
#          남은 질문은 정답 라벨로 채운다(tools/evaluate/gt_answer.py, 최대 3번). 영상 하나에 30초~1분.
set -u
TAG=${1:?"이름을 주세요 (예: cctv)"}
[ -n "${MTM_DETECTOR:-}" ] || { echo "MTM_DETECTOR=<모델 파일>을 지정해 주세요"; exit 1; }
[ -f "$MTM_DETECTOR" ] || { echo "모델 파일이 없어요: $MTM_DETECTOR"; exit 1; }
cd "$(dirname "$0")/../.."   # tools/evaluate → 저장소 루트
export PATH="$PWD/.venv/bin:$PATH"
AUTO=outputs/eval_${TAG}_auto; TAP=outputs/eval_${TAG}_tap
mkdir -p $AUTO $TAP
echo "탐지 모델: $MTM_DETECTOR"
for d in outputs/eval_auto/cc_*; do
  v=$(basename $d); a=$AUTO/$v; t=$TAP/$v
  [ -n "${RESUME:-}" ] && [ -f $t/app.json ] && continue   # RESUME=1: 이미 끝난 영상은 건너뜀 (중간에 끊겼을 때)
  rm -rf $a $t; mkdir -p $a; cp $d/scene.json $a/
  python run_app.py data/videos/cc/$v.mp4 --out $a > $a/run.log 2>&1 || echo "$v 자동 실패: $(tail -1 $a/run.log)"
  [ -f $a/tracks_final.json ] || continue
  cp -r $a $t; rm -f $t/run.log $t/app.json
  python tools/evaluate/remap_answers.py outputs/eval_tap/$v $t
  for i in 1 2 3 4; do
    python run_app.py data/videos/cc/$v.mp4 --answers $t/answers.json --out $t > $t/run.log 2>&1 \
      || { echo "$v 답 실패: $(tail -1 $t/run.log)"; break; }
    [ $i = 4 ] && break
    python3 -c "import json,sys; a=json.load(open('$t/app.json')); sys.exit(0 if a.get('questions') else 1)" || break
    python tools/evaluate/gt_answer.py $t > /dev/null 2>&1
  done
  rm -f $a/run.log $t/run.log
done
python tools/evaluate/results_table.py $AUTO > outputs/결과표_${TAG}_자동.md
python tools/evaluate/results_table.py $TAP > outputs/결과표_${TAG}_답반영.md
echo "== 지금 모델";   tail -1 outputs/결과표_자동.md; tail -1 outputs/결과표_답반영.md
echo "== $TAG 모델";   tail -1 outputs/결과표_${TAG}_자동.md; tail -1 outputs/결과표_${TAG}_답반영.md
