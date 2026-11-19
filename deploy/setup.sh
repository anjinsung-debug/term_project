#!/usr/bin/env bash
# JCloud 인스턴스(Ubuntu 24.04)에서 앱을 설치하거나 갱신하고 서비스로 실행한다.
# 처음 설치와 갱신 모두 이 스크립트 하나로 한다 (README "JCloud 배포와 복구").
#
#   cd ~/term_project && git pull && bash deploy/setup.sh
#
# 앱은 3000 포트로 뜬다. JCloud는 3000 포트를 외부 s.jedutools.io:4XXXX로 연결한다 (인스턴스 세부 정보의 "접속 주소").
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE=pacs
PORT=3000
cd "$APP_DIR"

# 1) 비밀 값과 영상 저장 폴더 확인. 저장소에는 없으므로 scp로 따로 올려야 한다.
if [ ! -f .streamlit/secrets.toml ]; then
  echo "오류: .streamlit/secrets.toml이 없습니다. README 'JCloud 배포와 복구'의 2단계를 먼저 하세요." >&2
  exit 1
fi
DATA_DIR=$(python3 -c "import tomllib; print(tomllib.load(open('.streamlit/secrets.toml','rb')).get('storage',{}).get('data_dir',''))")
case "$DATA_DIR" in
  /*) mkdir -p "$DATA_DIR" ;;
  *) echo "오류: secrets.toml의 [storage] data_dir를 절대 경로로 지정하세요 (예: /home/ubuntu/pacs-data). 코드를 갱신해도 영상이 남게 하기 위해서입니다." >&2
     exit 1 ;;
esac

# 2) 파이썬 환경. Ubuntu 24.04의 Python 3.12에서 requirements.txt가 설치되는 것을 확인했다 (22.04의 3.10은 안 됨).
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

# 3) 서비스 등록. SSH를 끊거나 서버를 다시 켜도 앱이 계속 떠 있게 한다.
sed -e "s#__APP_DIR__#$APP_DIR#g" -e "s#__USER__#$(id -un)#g" -e "s#__PORT__#$PORT#g" \
  deploy/pacs.service | sudo tee /etc/systemd/system/$SERVICE.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable -q $SERVICE
sudo systemctl restart $SERVICE

# 4) 확인
sleep 5
if curl -fsS "http://127.0.0.1:$PORT/_stcore/health" > /dev/null; then
  echo "실행 중: 내부 http://$(hostname -I | awk '{print $1}'):$PORT"
  echo "외부 주소: JCloud 인스턴스 세부 정보 → 접속 주소에서 내부 포트 $PORT 행 (예: http://s.jedutools.io:40048)"
  echo "배포 커밋: $(git rev-parse --short HEAD)"
else
  echo "앱이 응답하지 않습니다. 로그를 확인하세요: journalctl -u $SERVICE -n 50" >&2
  exit 1
fi
