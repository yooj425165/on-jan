# ONJAN 통합 서비스

기존 `onjan/` 센서·서보·보정·AI 코드와 기존 WAV 플레이어를 재사용하는 새 진입점입니다.
저장소 전체가 필요하며 이 폴더만 복사해서 실행하는 구조는 아닙니다.
로컬 네트워크용 단일 프로세스 서비스입니다. 기존 테스트 웹과 동시에 실행하지 마세요.

## 실행

```bash
cd ~/on-jan
source .venv-pi/bin/activate
python -m pip install -r requirements-hardware.txt
python -m onjan_service
```

Pi 브라우저: `http://127.0.0.1:5008`, 다른 기기: `http://<Pi-IP>:5008`.
Ubuntu UFW를 사용하면 `sudo ufw allow 5008/tcp`. GPIO는 실행 중인 pigpiod가 필요합니다.
버튼으로 GPIO와 I2S를 교대할 때는 아래 **1회 설정**으로 데몬을 온잔 전용 서비스로 관리합니다.
바흐 피아노 실연 두 곡(골드베르크 변주곡 아리아, 프랑스 모음곡 5번 가보트)은
`git pull`하면 `music/`에 함께 받아집니다. 연주: eldüendesüarez, CC BY-SA 4.0.
원본 출처와 라이선스 링크는 `music/sources.json`을 참고하세요.

```bash
# 하드웨어 없이 UI/AI 시험 (음악 출력은 실행 컴퓨터의 aplay)
python -m onjan_service --no-hardware
# USB 출력 장치 변경
python -m onjan_service --audio-device 'plughw:CARD=UACDemoV10,DEV=0'
# 기본 마이크(sndrpigooglevoi) 대신 다른 ALSA 장치 선택
python -m onjan_service --microphone 'plughw:CARD=YOUR_MIC,DEV=0'
```

## 구현 범위

### Pi 최초 1회: 소스로 설치한 pigpiod를 systemd로 관리

기존 웹과 GPIO 테스트를 종료하세요. 다른 앱이 데몬을 사용 중이면 먼저 종료해야 합니다.
이 명령은 이전 안내대로 수동 실행했던 `/usr/local/bin/pigpiod`를 사용하는 Pi 기준입니다.
다른 pigpiod.service가 있다면 동시에 실행하지 마세요.

```bash
cd ~/on-jan
sudo pkill -x pigpiod   # 기존 수동 데몬이 없으면 생략
sudo install -m 644 onjan_service/onjan-pigpio.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now onjan-pigpio.service
sudo visudo -f /etc/sudoers.d/onjan-pigpio
```

다음 한 줄만 등록합니다(계정이 ubuntu가 아니면 교체). 서버 자체는 sudo로 실행하지 않습니다.

```text
ubuntu ALL=(root) NOPASSWD: /usr/bin/systemctl stop onjan-pigpio.service, /usr/bin/systemctl start onjan-pigpio.service
```

- 웹을 먼저 실행하고 센서 초기화는 별도 스레드에서 진행합니다.
- 영점·보정·AI 추론·녹음은 작업 큐에서 수행합니다. POST는 작업 ID와 202를 즉시 반환하고
  상태 조회는 계속 응답합니다. 중복 명령은 거부합니다.
- 조도와 RMS를 기준으로 네 가지 플레이리스트 중 하나를 선택합니다. 기준 및 30곡의 순서는 `music/playlists.json`에 있으며 방에 맞춰 조정한 뒤 재시작하세요.
- 다같이 측정하기는 기존 음악을 정지하고 측정한 뒤 선택 이유를 표시하고 목록을 순서대로 한 번 재생합니다. 측정 실패 시 직접 선택합니다. 무게·거리는 선곡에 사용하지 않습니다.
- 무게 감지는 시뮬레이션 전용입니다. 활성화 후 150g 이하 1초로 재준비,
  200~300g이면서 초음파 15cm 이내 감지가 1초 유지되면 목표 위치로 이동합니다.
  이동은 1초, 이후 목표 위치를 유지하며 무게 증가를 감시합니다.
  이동/유지 중 **300g 초과** 시 1초 복귀 시뮬레이션 후 컵 제거까지 재동작하지 않습니다.
  정확히 300g에서는 복귀하지 않으며, 처음부터 300g을 초과하면 시작하지 않습니다.
  동작 중 접근 해제, 무게 150g 이하, 센서 오류/오래된 값, 동작 시작 후 30초 경과도
  복귀 조건입니다. 복귀 사유는 `automation.return_reason`에 표시됩니다.
  이 값들은 임의의 데모 정책이며, 실제 모터 동작/각도 피드백은 아닙니다.
- 외부 V+가 없으므로 실제 서보 구동은 잠겨 있습니다. 실물 PWM 활성화 API는 없습니다.
- 마이크는 선택적 ALSA 2초 녹음과 dBFS/포화율 측정을 지원합니다. S32_LE, 48kHz,
  스테레오의 왼쪽 채널을 사용하므로 실제 드라이버 지원과 정렬 확인이 필요합니다.
  마이크 추가 핀은 `HARDWARE.md`를 참고하세요. OS의 I2S 드라이버 설정은 별도로 필요합니다.
- **다같이 측정하기**는 직전 센서값과 시각을 확보하고 GPIO 두 작업을 종료한 뒤 전용 데몬을 중지합니다.
  조도는 계속 수집합니다. 2초 녹음 후 특징과 직전 센서 상태를 `data/measurement-rounds.jsonl`에
  저장하고, 실패 시에도 데몬 재시작과 센서 재연결을 시도합니다. 같은 순간의 측정은 아닙니다.
  센서 오류는 0으로 대체하지 않습니다. 전환 중에는 컵 자동화에 이전 값을 재사용하지 않습니다.
- Ctrl+C/SIGTERM으로 작업과 센서 종료를 기다린 뒤 자원을 정리합니다. 기존 HX711 평균화 등
  진행 중인 I/O는 즉시 취소되지 않으므로 종료에 수 초 걸릴 수 있습니다.

## 확인 순서

1. `--no-hardware`: 분위기 직접 선택 및 연속 재생 확인.
2. WAV 재생/정지와 실제 USB 출력 확인.
3. 기본 모드: 센서 상태, Tare/실제 무게추 보정 및 응답 중 상태 API 갱신 확인.
4. 모터 감지 시작: 빈 플랫폼 → 200g 이상 → 유지 → 제거하며 상태 전이 확인.
5. 마이크 격리 모드: 소리 크기 변화, 왼쪽 채널, 포화율 확인.

실제 사용자 검증, 실물 모터 동작, I2S/pigpio 동시 사용, 학습된 음악 적합도 모델은
완료되지 않았습니다. 웹에 가상 AI·모터 시뮬레이션 표시를 유지합니다.
