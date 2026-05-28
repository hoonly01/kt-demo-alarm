# 종로구 집회 알리미 서버 인수 Migration Runbook

## 0. 결론

이 문서는 개인 AWS EC2에서 운영 중인 `kt-demo-alarm` 서비스를 종로구 서버 `210.99.170.201`로 인수하기 위한 실제 작업 절차다.

최종 목표는 **개인 AWS 계정을 운영 경로에서 제거**하고, 카카오톡 채널/챗봇 요청이 아래 구조로 처리되게 만드는 것이다.

```text
카카오 / 사용자
  → https://www.jongno.go.kr/rally/
  → 종로구 앞단 프록시 / WAF / L7 장비
  → 210.99.170.201 내부 앱 또는 210 서버의 내부 Nginx
  → Docker Compose / FastAPI / SQLite / Scheduler
```

중요 원칙:

| 원칙 | 결정 |
|---|---|
| 개인 AWS | 최종 운영/배포/프록시/터널에 남기지 않는다. |
| GitHub 경유 | `.env`나 비밀값을 GitHub에 push한 뒤 pull하는 방식은 금지한다. |
| `.env` 이전 | 서버 간 직접 `scp`/`rsync` 또는 새 서버 직접 작성은 허용한다. |
| 데이터 이전 | 전체 서버를 통째로 복사하지 않고, 필요한 앱 산출물과 운영 데이터만 이전한다. |
| `/rally/` | 종로구 앞단에서 `https://www.jongno.go.kr/rally/`를 210 서버 쪽으로 프록시하는 전제다. |

---

## 1. 현재 repo 기준 운영 사실

| 항목 | 값 / 의미 | 근거 |
|---|---|---|
| 앱 런타임 | Docker Compose 서비스 `kt-demo-alarm` | `docker-compose.yml` |
| 앱 이미지 | `kt-demo-alarm:latest` | `docker-compose.yml` |
| 앱 포트 | host `127.0.0.1:8000` → container `8000` | `docker-compose.yml` |
| DB | SQLite, `/app/data/kt_demo_alarm.db` | `docker-compose.yml` |
| 운영 볼륨 | `data`, `logs`, `topis_cache`, `topis_attachments` | `docker-compose.yml` |
| healthcheck | `GET /` | `main.py` |
| 스케줄러 | 앱 시작 시 자동 시작 | `main.py` |
| 카카오 채널 웹훅 | `/kakao/webhook/channel` | `app/routers/kakao.py` |
| 카카오 fallback | `/kakao/chat` | `app/routers/kakao.py` |
| Skill Block | `/today-protests`, `/upcoming-protests`, `/check-route` 등 | `app/routers/kakao_skills.py` |

스케줄러가 앱 시작 시 자동 실행되므로, AWS 앱과 종로구 서버 앱을 동시에 운영 상태로 오래 켜두면 **중복 크롤링/중복 알림** 위험이 있다.

---

## 2. 용어와 변수

아래 값은 runbook에서 반복 사용한다.

```bash
# 기존 개인 AWS 운영 서버
SOURCE_HOST="54.116.172.170"
SOURCE_APP_DIR="/opt/kt-demo-alarm"

# 종로구 인수 대상 서버
TARGET_HOST="210.99.170.201"
TARGET_SSH_PORT="7022"
TARGET_APP_DIR="/opt/kt-demo-alarm"

# 종로구 공개 URL
PUBLIC_BASE_URL="https://www.jongno.go.kr/rally"
```

계정명은 실제 접속 가능한 계정으로 바꾼다.

```bash
SOURCE_USER="ec2-user"
TARGET_USER="<jongno-user>"
```

> 주의: 명령 예시의 `<jongno-user>`는 실제 계정으로 교체한다. 비밀번호, API key, SSH private key 원문은 이 문서에 기록하지 않는다.

---

## 3. 사전 준비물 체크리스트

| 준비물 | 확인 방법 |
|---|---|
| AWS 서버 접속 권한 | `ssh ${SOURCE_USER}@${SOURCE_HOST}` |
| 종로구 서버 접속 권한 | `ssh -p 7022 ${TARGET_USER}@210.99.170.201` |
| 종로구 서버에서 Docker 사용 가능 | `docker --version` |
| 종로구 서버에서 Compose 사용 가능 | `docker compose version` |
| 종로구 앞단 `/rally/` 프록시 담당자/경로 | 종로구 인프라 담당자 확인 |
| 카카오 관리자 권한 | 카카오 Developers / 챗봇 관리자센터 접근 가능 |
| 현재 AWS `/opt/kt-demo-alarm` 접근 가능 | `cd /opt/kt-demo-alarm && ls` |

접속 확인:

```bash
ssh -p 7022 "${TARGET_USER}@${TARGET_HOST}" 'whoami && hostname && pwd'
```

기대:

```text
<jongno-user>
<target-hostname>
<home-or-current-dir>
```

---

## 4. 0단계: `/rally/` ingress 확인 gate

이 단계는 최종 cutover 완료 판정을 위한 gate다. 실패해도 서버 준비와 데이터 이전 준비는 계속할 수 있다. 단, 실패 상태에서는 카카오 전환 완료나 AWS 종료 완료로 판정하면 안 된다.

외부 PC 또는 접근 가능한 네트워크에서 확인:

```bash
curl -k -i -L --max-time 15 "${PUBLIC_BASE_URL}/"
```

최종적으로 기대하는 정상 응답은 앱 healthcheck다.

```json
{
  "message": "KT Demo Alarm API is running!",
  "version": "1.0.0",
  "status": "healthy"
}
```

현재 `/rally/`가 종로구 오류 페이지, 503 페이지, 빈 페이지로 연결되면 아래처럼 기록한다.

```text
[RISK] yyyy-mm-dd hh:mm
https://www.jongno.go.kr/rally/ 가 아직 210 앱 healthcheck로 연결되지 않음.
서버/데이터 준비는 계속하되, 카카오 cutover 및 AWS 종료는 보류.
필요 조치: 종로구 앞단 프록시/WAF/L7에서 /rally/ → 210 앱으로 연결 필요.
```

현재 `docker-compose.yml`은 앱을 host `127.0.0.1:8000`에만 바인딩한다. 따라서 종로구 앞단 프록시가 **210 서버 안의 Nginx**라면 바로 `127.0.0.1:8000`으로 프록시하면 된다.

210 서버 내부 Nginx 예시:

```nginx
location /rally/ {
    proxy_pass http://127.0.0.1:8000/;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-Prefix /rally;

    proxy_connect_timeout 60s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;
}
```

반대로 종로구 앞단 프록시/WAF/L7 장비가 **210 서버 밖의 별도 장비**라면, 현재 compose의 `127.0.0.1:8000` 바인딩으로는 직접 접근할 수 없다. 이 경우 둘 중 하나가 필요하다.

| 선택지 | 설명 | 권장 |
|---|---|---|
| 210 서버 내부 Nginx 추가 | 별도 장비 → 210 서버 내부 Nginx 허용 포트 → `127.0.0.1:8000` | 권장 |
| compose 바인딩 변경 | `127.0.0.1:8000:8000`을 내부망에서만 접근 가능한 IP/포트로 변경 | 방화벽 통제가 명확할 때만 |

별도 앞단 장비에서 210 서버 내부 Nginx로 붙는 예시:

```nginx
location /rally/ {
    proxy_pass http://210.99.170.201:<JONGNO_INTERNAL_HTTP_PORT>/;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-Prefix /rally;
}
```

`<JONGNO_INTERNAL_HTTP_PORT>`는 공용 인터넷 전체에 여는 포트가 아니라, 종로구 앞단 장비에서만 접근 가능한 내부/방화벽 허용 포트여야 한다.

중요:

| 설정 | 이유 |
|---|---|
| `location /rally/` | 공개 URL prefix |
| `proxy_pass .../` 끝의 `/` | `/rally/kakao/chat` → 앱의 `/kakao/chat`로 전달 |
| `X-Forwarded-Prefix` | prefix 기반 운영 흔적을 남겨 추후 앱 수정 시 활용 |
| compose `127.0.0.1:8000` | 같은 서버 내부 프록시만 직접 접근 가능 |

---

## 5. 1단계: 종로구 서버 환경 확인

종로구 서버에서 실행:

```bash
ssh -p 7022 "${TARGET_USER}@${TARGET_HOST}"
```

OS 확인:

```bash
cat /etc/os-release
uname -a
```

Docker 확인:

```bash
docker --version
docker compose version
docker ps
```

외부 인터넷 outbound 확인:

```bash
ping -c 4 google.com
curl -I --max-time 15 https://download.docker.com
curl -I --max-time 15 https://mirror.centos.org
sudo dnf --setopt=timeout=15 makecache
```

판정:

| 결과 | 의미 | 다음 행동 |
|---|---|---|
| `ping`만 실패, `curl`/`dnf` 성공 | ICMP만 차단 | 패키지 설치 계속 가능 |
| `ping`, `curl`, `dnf` 모두 timeout | outbound 인터넷 차단 또는 프록시 필수 | 아래 “공공기관 내부망 분기”로 진행 |
| `curl`은 성공, `dnf`만 실패 | DNS/미러/repo 설정 문제 가능 | repo 설정 또는 내부 미러 확인 |

현재 관찰된 증상처럼 `ping google.com` 100% loss, `curl https://download.docker.com` timeout, `dnf baseos` metadata timeout이 같이 나오면 **DNF 문제가 아니라 네트워크 egress 정책 문제**로 판단한다.

### 공공기관 내부망 분기: 프록시 또는 오프라인 반입

이 서버가 외부 인터넷으로 직접 나갈 수 없다면 `dnf install nginx`, `dnf install podman`, Docker 공식 repo 설치는 계속 실패한다. 이때 가능한 경로는 셋 중 하나다.

| 경로 | 설명 | 권장 상황 |
|---|---|---|
| 기관 HTTP/HTTPS 프록시 | 기관이 제공하는 프록시를 `dnf`, `curl`, Docker에 설정 | 기관 표준 프록시가 있을 때 |
| 내부 Rocky/RHEL 미러 | `/etc/yum.repos.d/*.repo`가 외부가 아닌 기관 내부 미러를 보게 설정 | 기관 내부 패키지 미러가 있을 때 |
| 오프라인 RPM/이미지 반입 | 외부망에서 필요한 RPM/Docker image를 받아 `scp`로 반입 | 프록시/내부 미러가 없을 때 |

프록시가 있는 경우, 임시 테스트:

```bash
export http_proxy="http://<PROXY_HOST>:<PROXY_PORT>"
export https_proxy="http://<PROXY_HOST>:<PROXY_PORT>"

curl -I --max-time 15 https://download.docker.com
sudo dnf --setopt=proxy="http://<PROXY_HOST>:<PROXY_PORT>" makecache
```

DNF 영구 설정 예시:

```bash
sudo cp /etc/dnf/dnf.conf "/etc/dnf/dnf.conf.bak.$(date +%Y%m%d-%H%M%S)"
sudo tee -a /etc/dnf/dnf.conf >/dev/null <<'DNF_PROXY'
proxy=http://<PROXY_HOST>:<PROXY_PORT>
DNF_PROXY
```

프록시 인증이 필요하면 기관 보안 정책에 따라 아래 항목을 추가할 수 있다. 단, 프록시 비밀번호가 파일에 저장되므로 운영 계정/권한 정책 확인이 필요하다.

```ini
proxy_username=<PROXY_USER>
proxy_password=<PROXY_PASSWORD>
proxy_auth_method=any
```

프록시나 내부 미러가 없다면, Docker/Nginx 설치는 외부 repo 접근 방식이 아니라 **오프라인 RPM 반입 방식**으로 설계한다.

오프라인 반입 원칙:

```text
외부 인터넷 가능한 작업 PC 또는 기존 AWS
  → Rocky 9 호환 RPM/이미지 다운로드
  → tar로 묶음
  → scp -P 7022 로 210 서버 반입
  → dnf localinstall 또는 rpm 설치
```

Docker image는 이미 이 runbook에서 `docker image save` → `docker load` 방식으로 반입하므로, 문제는 **컨테이너 런타임(Docker/Podman)과 Nginx RPM을 어떻게 설치할지**다.

Docker가 없으면 OS별로 설치가 필요하다. 아래 명령은 사용자가 종로구 서버에서 직접 실행한다.

Ubuntu 계열:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
sudo sh /tmp/get-docker.sh
rm -f /tmp/get-docker.sh
sudo usermod -aG docker "$USER"
```

Amazon Linux 계열:

```bash
sudo dnf install -y docker
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker "$USER"
```

Docker 그룹 반영:

```bash
exit
ssh -p 7022 "${TARGET_USER}@${TARGET_HOST}"
docker ps
```

210 서버 내부 Nginx를 사용할 경우 설치 확인:

```bash
nginx -v
systemctl status nginx --no-pager
```

없으면 OS별로 설치한다.

Ubuntu 계열:

```bash
sudo apt-get update
sudo apt-get install -y nginx
```

Amazon Linux 계열:

```bash
sudo dnf install -y nginx
sudo systemctl enable nginx
sudo systemctl start nginx
```

---

## 6. 2단계: 종로구 서버 앱 디렉터리 준비

종로구 서버에서 실행:

```bash
sudo mkdir -p /opt/kt-demo-alarm/{data,logs,topis_cache,topis_attachments}
sudo chown -R "$USER":"$USER" /opt/kt-demo-alarm
chmod 755 /opt/kt-demo-alarm
cd /opt/kt-demo-alarm
```

확인:

```bash
pwd
find . -maxdepth 1 -type d -print | sort
```

기대:

```text
.
./data
./logs
./topis_attachments
./topis_cache
```

---

## 7. 3단계: 이전 대상 정리 — “scp로 통째로 옮기는가?”

결론: **전체 서버를 통째로 옮기지 않는다.**

옮길 대상:

| 대상 | 이전 여부 | 이유 |
|---|---:|---|
| `docker-compose.yml` | 필수 | 실행 정의 |
| `.env` | 필수 | API key, 카카오, admin 설정 |
| Docker image tar | 권장 | GitHub pull 없이 동일 앱 이미지 이전 |
| 210 서버 내부 Nginx 설정 | 조건부 | 종로구 앞단이 210 서버 외부 장비일 때 필요 |
| Docker/Podman/Nginx RPM bundle | 조건부 | 210 서버 outbound 인터넷이 차단된 경우 필요 |
| `data/` | 필수 | SQLite DB |
| `topis_cache/` | 권장 | 크롤링 cache |
| `topis_attachments/` | 필수 | 카카오 이미지/첨부 |
| `logs/` | 선택 | 감사/장애 분석용 |
| 전체 `/home`, `/etc`, Docker 시스템 디렉터리 | 금지 | 개인 계정 흔적/OS 상태/불필요 설정 이전 위험 |

`.env`는 서버 간 직접 `scp`/`rsync`로 옮겨도 된다. 금지되는 것은 `.env`를 GitHub 같은 원격 저장소에 올리고 pull하는 방식이다.

---

## 8. 4단계: AWS 운영 상태 점검

AWS 서버에서 실행:

```bash
ssh "${SOURCE_USER}@${SOURCE_HOST}"
cd /opt/kt-demo-alarm
pwd
docker compose ps
docker images | grep 'kt-demo-alarm' || true
du -sh data logs topis_cache topis_attachments 2>/dev/null || true
```

DB 파일 확인:

```bash
ls -lh data/kt_demo_alarm.db
```

`.env` 존재와 권한 확인:

```bash
test -f .env && ls -l .env
```

> 주의: `cat .env`처럼 원문을 터미널에 출력하지 않는다.

---

## 9. 5단계: AWS 앱 정지 및 최종 백업

SQLite 정합성을 위해 백업 전 앱을 정지한다.

AWS 서버에서 실행:

```bash
cd /opt/kt-demo-alarm
docker compose down
```

정지 확인:

```bash
docker compose ps
```

백업 디렉터리 생성:

```bash
BACKUP_TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="/opt/kt-demo-alarm-backup-${BACKUP_TS}"
mkdir -p "${BACKUP_DIR}"
```

Docker 이미지 저장:

```bash
docker image save kt-demo-alarm:latest | gzip > "${BACKUP_DIR}/kt-demo-alarm-image.tar.gz"
```

앱 실행 파일/설정/운영 데이터 묶기:

```bash
tar czf "${BACKUP_DIR}/kt-demo-alarm-runtime.tar.gz" \
  docker-compose.yml \
  .env \
  data \
  topis_cache \
  topis_attachments \
  logs
```

백업 확인:

```bash
ls -lh "${BACKUP_DIR}"
tar tzf "${BACKUP_DIR}/kt-demo-alarm-runtime.tar.gz" | sed -n '1,40p'
```

기대:

```text
kt-demo-alarm-image.tar.gz
kt-demo-alarm-runtime.tar.gz
```

---

## 10. 6단계: AWS에서 종로구 서버로 직접 전송

AWS에서 종로구 서버로 직접 전송한다. GitHub를 경유하지 않는다.

AWS 서버에서 실행:

```bash
scp -P 7022 \
  "${BACKUP_DIR}/kt-demo-alarm-image.tar.gz" \
  "${BACKUP_DIR}/kt-demo-alarm-runtime.tar.gz" \
  "${TARGET_USER}@${TARGET_HOST}:/opt/kt-demo-alarm/"
```

전송 확인:

```bash
ssh -p 7022 "${TARGET_USER}@${TARGET_HOST}" \
  'cd /opt/kt-demo-alarm && ls -lh kt-demo-alarm-image.tar.gz kt-demo-alarm-runtime.tar.gz'
```

대용량 전송이 불안정하면 `rsync`를 사용한다.

```bash
rsync -avP -e "ssh -p 7022" \
  "${BACKUP_DIR}/kt-demo-alarm-image.tar.gz" \
  "${BACKUP_DIR}/kt-demo-alarm-runtime.tar.gz" \
  "${TARGET_USER}@${TARGET_HOST}:/opt/kt-demo-alarm/"
```

---

## 11. 7단계: 종로구 서버에서 복구

종로구 서버에서 실행:

```bash
cd /opt/kt-demo-alarm
tar xzf kt-demo-alarm-runtime.tar.gz
gunzip -c kt-demo-alarm-image.tar.gz | docker load
```

권한 설정:

```bash
chmod 600 .env
chmod -R 755 data logs topis_cache topis_attachments
```

확인:

```bash
ls -lah
docker images | grep 'kt-demo-alarm'
test -f .env && ls -l .env
test -f data/kt_demo_alarm.db && ls -lh data/kt_demo_alarm.db
```

`.env`의 필수 키 존재 여부만 확인한다. 값을 출력하지 않는다.

```bash
for key in \
  KAKAO_EVENT_API_KEY \
  KAKAO_LOCATION_API_KEY \
  BOT_ID \
  API_KEY \
  SEOUL_BUS_API_KEY \
  TMAP_APP_KEY \
  RENDER_EXTERNAL_URL \
  ADMIN_USER \
  ADMIN_PASS
do
  if grep -q "^${key}=" .env; then
    echo "OK ${key}"
  else
    echo "MISSING ${key}"
  fi
done
```

`RENDER_EXTERNAL_URL`은 최종적으로 아래 값이어야 한다.

```bash
grep '^RENDER_EXTERNAL_URL=' .env
```

기대:

```text
RENDER_EXTERNAL_URL=https://www.jongno.go.kr/rally
```

다르면 편집한다.

```bash
cp .env ".env.bak.$(date +%Y%m%d-%H%M%S)"
python3 - <<'PY'
from pathlib import Path

path = Path(".env")
lines = path.read_text().splitlines()
key = "RENDER_EXTERNAL_URL"
value = "https://www.jongno.go.kr/rally"
updated = False
out = []
for line in lines:
    if line.startswith(f"{key}="):
        out.append(f"{key}={value}")
        updated = True
    else:
        out.append(line)
if not updated:
    out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n")
PY
chmod 600 .env
```

---

## 12. 8단계: 210 서버 내부 Nginx 설정이 필요한 경우

이 단계는 종로구 앞단 프록시가 210 서버 밖에 있고, 210 서버에서 내부 Nginx가 받아 `127.0.0.1:8000`으로 넘겨야 할 때만 수행한다.

내부 Nginx 설정 파일 예시:

```bash
cat > /tmp/kt-demo-alarm-rally.conf <<'NGINX'
server {
    listen <JONGNO_INTERNAL_HTTP_PORT>;
    server_name _;

    client_max_body_size 10M;

    location /rally/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Prefix /rally;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
NGINX
```

`<JONGNO_INTERNAL_HTTP_PORT>`를 종로구 내부에서 허용된 포트로 바꾼 뒤 적용한다.

Ubuntu 계열:

```bash
sudo cp /tmp/kt-demo-alarm-rally.conf /etc/nginx/sites-available/kt-demo-alarm-rally
sudo ln -sf /etc/nginx/sites-available/kt-demo-alarm-rally /etc/nginx/sites-enabled/kt-demo-alarm-rally
sudo nginx -t
sudo systemctl reload nginx
```

Amazon Linux 계열:

```bash
sudo cp /tmp/kt-demo-alarm-rally.conf /etc/nginx/conf.d/kt-demo-alarm-rally.conf
sudo nginx -t
sudo systemctl reload nginx
```

210 서버 내부에서 확인:

```bash
curl -i "http://127.0.0.1:<JONGNO_INTERNAL_HTTP_PORT>/rally/"
```

---

## 13. 9단계: 종로구 서버에서 앱 기동

종로구 서버에서 실행:

```bash
cd /opt/kt-demo-alarm
docker compose up -d --no-build
```

상태 확인:

```bash
docker compose ps
docker compose logs --tail=100
```

로컬 healthcheck:

```bash
curl -fsS http://127.0.0.1:8000/
```

기대:

```json
{"message":"KT Demo Alarm API is running!","version":"1.0.0","status":"healthy"}
```

컨테이너 health 상태:

```bash
docker inspect --format='{{json .State.Health}}' "$(docker compose ps -q kt-demo-alarm)" | python3 -m json.tool
```

---

## 14. 10단계: 종로구 앞단 `/rally/` 프록시 검증

외부 또는 카카오가 접근하는 네트워크에서 확인:

```bash
curl -k -i -L --max-time 15 https://www.jongno.go.kr/rally/
```

정상 기준:

| 검사 | 기대 |
|---|---|
| HTTP status | `200` |
| body | `KT Demo Alarm API is running!` |
| redirect | 종로구 오류 페이지로 가지 않음 |

추가 endpoint 검증:

```bash
curl -k -i -X POST https://www.jongno.go.kr/rally/kakao/webhook/channel \
  -H 'Content-Type: application/json' \
  -d '{"event":"added","id":"migration-smoke-test"}'
```

기대:

```json
{"status":"ok", ...}
```

> 주의: 위 webhook 테스트는 DB에 테스트 사용자를 만들 수 있다. 운영 데이터 오염이 우려되면 별도 테스트 시간에 수행하거나 테스트 후 DB에서 해당 레코드를 정리한다.

Skill Block endpoint는 카카오 요청 형식이 필요하므로, 실제 카카오 관리자센터 테스트 도구로 검증하는 것을 우선한다.

---

## 15. 11단계: 카카오 URL 전환 체크리스트

카카오 관리자센터에서 아래 URL을 종로구 공개 URL로 맞춘다.

| 용도 | 최종 URL |
|---|---|
| 채널 웹훅 | `https://www.jongno.go.kr/rally/kakao/webhook/channel` |
| 챗봇 fallback | `https://www.jongno.go.kr/rally/kakao/chat` |
| 오늘의 집회 | `https://www.jongno.go.kr/rally/today-protests` |
| 예정 집회 | `https://www.jongno.go.kr/rally/upcoming-protests` |
| 경로 확인 | `https://www.jongno.go.kr/rally/check-route` |
| 이동경로 관리 | `https://www.jongno.go.kr/rally/route-setting` |
| 이동경로 삭제 | `https://www.jongno.go.kr/rally/route-setting/delete` |
| 관심장소 | `https://www.jongno.go.kr/rally/favorite-zone` |
| 관심장소 저장 | `https://www.jongno.go.kr/rally/favorite-zone/save` |
| 알림 설정 | `https://www.jongno.go.kr/rally/alarm-setting` |
| 알림 설정 저장 | `https://www.jongno.go.kr/rally/alarm-setting/save` |
| 버스 정보 | `https://www.jongno.go.kr/rally/webhook/bus_info` |
| 버스 경로 확인 | `https://www.jongno.go.kr/rally/webhook/route_check` |

검증:

| 항목 | 기준 |
|---|---|
| 채널 추가/차단 webhook | 2xx 응답 |
| 챗봇 fallback | 카카오 simpleText 응답 |
| 오늘의 집회 | 오류 없이 응답 |
| 이미지 포함 응답 | URL이 `https://www.jongno.go.kr/rally/...`로 시작 |
| 사용자 경로/관심장소 설정 | 기존 사용자 데이터 기준 정상 동작 |

---

## 16. 12단계: AWS 의존성 제거 체크리스트

아래가 모두 참이어야 AWS 제거 단계로 갈 수 있다.

| 체크 | 명령 / 확인 |
|---|---|
| 종로구 서버 로컬 health 정상 | `curl -fsS http://127.0.0.1:8000/` |
| 공개 `/rally/` health 정상 | `curl -k -fsS https://www.jongno.go.kr/rally/` |
| 카카오 webhook 2xx | 카카오 관리자센터 또는 curl 테스트 |
| `RENDER_EXTERNAL_URL` 정상 | `.env`에서 `https://www.jongno.go.kr/rally` |
| AWS relay/tunnel 없음 | Nginx, systemd, crontab, ssh tunnel 확인 |
| GitHub Actions가 개인 AWS에 배포하지 않음 | workflow 비활성화 또는 secrets 제거 |
| AWS 앱 중지 상태에서도 서비스 정상 | AWS `docker compose down` 후 종로구 서비스 검증 |

AWS 서버에서 앱이 꺼져 있는지 확인:

```bash
ssh "${SOURCE_USER}@${SOURCE_HOST}" 'cd /opt/kt-demo-alarm && docker compose ps'
```

종로구 공개 URL이 계속 정상인지 확인:

```bash
curl -k -fsS https://www.jongno.go.kr/rally/
```

---

## 17. rollback / stop criteria

| 단계 | 중단 조건 | 조치 |
|---|---|---|
| 종로구 SSH | `ssh -p 7022` 실패 | 계정/방화벽/허용 IP 확인 전 진행 중단 |
| Docker 준비 | `docker compose version` 실패 | Docker/Compose 설치 후 재시도 |
| 외부 인터넷 | `ping`, `curl`, `dnf makecache` 모두 timeout | 프록시/내부 미러/오프라인 RPM 반입 중 하나 확정 전 패키지 설치 시도 중단 |
| AWS 백업 | DB 또는 tar 생성 실패 | AWS 앱 재기동하지 말고 원인 확인 |
| 전송 | `scp`/`rsync` 실패 | `rsync -avP`로 재시도, 디스크 용량 확인 |
| 복구 | DB 파일 없음 | 백업 tar 내용 확인 후 재전송 |
| 앱 기동 | `curl 127.0.0.1:8000` 실패 | `docker compose logs --tail=200` 확인 |
| `/rally/` | 공개 URL이 앱 health가 아님 | 리스크 기록, 종로구 프록시 담당자 조치 필요. 서버 준비는 계속 가능 |
| 외부 앞단 → 210 | 별도 앞단 장비가 `210.99.170.201:8000`에 직접 접근 실패 | compose가 `127.0.0.1` 바인딩이므로 정상이다. 210 내부 Nginx 또는 내부 허용 포트 설계를 확정한다. |
| 카카오 | webhook/Skill 2xx 실패 | 카카오 URL, `/rally/` prefix strip, 앱 로그 확인 |
| AWS 종료 | AWS 꺼도 공개 서비스 실패 | AWS 종료 보류, 종로구 ingress/app 원인 해결 |

---

## 18. 최종 완료 체크리스트

| 완료 | 항목 |
|---|---|
| [ ] | 종로구 서버 `210.99.170.201:7022` 접속 가능 |
| [ ] | `/opt/kt-demo-alarm` 디렉터리 준비 |
| [ ] | Docker image `kt-demo-alarm:latest` 로드 |
| [ ] | `docker-compose.yml` 배치 |
| [ ] | 종로구 앞단이 별도 장비라면 210 내부 Nginx 또는 내부 허용 포트 구성 완료 |
| [ ] | `.env` 직접 이전 또는 작성 완료 |
| [ ] | `.env` 권한 `600` |
| [ ] | `RENDER_EXTERNAL_URL=https://www.jongno.go.kr/rally` |
| [ ] | `data/kt_demo_alarm.db` 복구 |
| [ ] | `topis_cache` 복구 |
| [ ] | `topis_attachments` 복구 |
| [ ] | `docker compose up -d --no-build` 성공 |
| [ ] | 종로구 서버 로컬 healthcheck 성공 |
| [ ] | 공개 `/rally/` healthcheck 성공 |
| [ ] | 카카오 채널 웹훅 URL 전환 완료 |
| [ ] | 카카오 Skill Block URL 전환 완료 |
| [ ] | 이미지 URL이 `www.jongno.go.kr/rally` 기준으로 생성됨 |
| [ ] | AWS 앱 중지 상태에서도 서비스 정상 |
| [ ] | AWS relay/tunnel/systemd/crontab 의존성 없음 |
| [ ] | GitHub push/pull 방식으로 `.env`를 다루지 않음 |
| [ ] | 개인 AWS 종료 또는 장기 비활성화 판단 완료 |

---

## 19. 운영 메모

컷오버는 스케줄러 실행 시간대를 피해서 진행한다. 앱은 시작 시 scheduler를 자동 시작하므로 AWS와 종로구 서버가 동시에 active 상태인 시간을 최소화한다.

권장 순서:

```text
종로구 서버 준비
→ AWS 앱 정지
→ 최종 백업
→ 종로구 서버 복구/기동
→ 로컬 healthcheck
→ /rally/ 프록시 검증
→ 카카오 URL 전환
→ AWS 앱 중지 상태 유지
→ 24~48시간 모니터링
→ 개인 AWS 제거 판단
```

AWS를 최종 relay나 tunnel로 남기는 선택지는 이 runbook의 비범위다.
