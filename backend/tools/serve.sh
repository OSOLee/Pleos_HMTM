#!/usr/bin/env bash
# API 서버 + 작업자를 같이 띄움 (Ctrl+C로 둘 다 끔). .env가 있으면 읽음
#   cd ~/MTM && bash tools/serve.sh            # 포트 8000, 다른 기기(에뮬레이터·폰)에서도 접속
#   cd ~/MTM && PORT=8011 bash tools/serve.sh
cd "$(dirname "$0")/.."
# .env에서 서버 설정(MTM_으로 시작하는 줄)만 읽음. AI Hub 키 줄은 "키 = 값" 모양이라 셸로 읽으면 오류가 나서
if [ -f .env ]; then
  while IFS='=' read -r k v; do export "$k=$v"; done < <(grep -E '^MTM_[A-Z_]+=' .env | tr -d '\r')
fi
PORT="${PORT:-8000}"
.venv/bin/python -m src.server.worker &
WORKER=$!
trap 'kill $WORKER 2>/dev/null' EXIT
.venv/bin/uvicorn src.server.app:app --host 0.0.0.0 --port "$PORT"
