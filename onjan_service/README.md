# ONJAN 통합 서비스

기존 `onjan/` 센서·서보·보정·AI 코드와 기존 WAV 플레이어를 재사용하는 새 진입점입니다.
저장소 전체가 필요하며 이 폴더만 복사해서 실행하는 구조는 아닙니다.
로컬 네트워크용 단일 프로세스 서비스입니다. 기존 테스트 웹과 동시에 실행하지 마세요.

## 실행

### Pi 복사본 무결성 확인

`runtime.py`가 0바이트이고 `git log`가 `bad object HEAD`라면 이름 변경으로 복구할 수 없습니다.
Pi에만 있는 `data/`와 작업물을 먼저 백업하고, 안정적인 저장장치에 새 폴더로 복제하세요.
새 프로젝트 루트에서 `git fsck --full`로 Git 객체를 검사하고, 의존성을 설치한 가상환경에서
`python -m onjan_service --help`로 하드웨어를 열지 않고 `Runtime` import를 확인할 수 있습니다.

```bash
cd ~/on-jan
source .venv-pi/bin/activate
python -m pip install -r requirements-hardware.txt
python -m onjan_service
```

Pi 브라우저: `http://127.0.0.1:5008`, 다른 기기: `http://<Pi-IP>:5008`.
Ubuntu UFW를 사용하면 `sudo ufw allow 5008/tcp`.
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

### Pi 4: GPIO 커널 드라이버 전환 (Ubuntu, os_prefix=current/)

버튼은 시스템 서비스를 제어하지 않습니다. 조도/I2S만 사용할 경우에도 이전에 설치한
pigpiod는 다음 부팅에서 시작하지 않게 설정해야 합니다. Pi의 전원/저장장치 상태가 안정된 뒤 진행하세요.
커널 지원부터 읽기 전용으로 확인: `grep -E 'CONFIG_(HX711|SRF04)=' /boot/config-$(uname -r)`.
두 드라이버가 y 또는 m이어야 해당 센서를 쓸 수 있습니다. m이면 `modinfo hx711`, `modinfo srf04`도 확인하세요.
없으면 해당 커널 모듈이 필요합니다. 누락된 센서는 오류로 표시되며 I2C·마이크는 독립적입니다.

```bash
# 통합 웹을 종료한 후 프로젝트 루트에서. 실행 중인 데몬을 강제 종료하지 않습니다.
sudo systemctl disable onjan-pigpio.service
sudo apt install device-tree-compiler
dtc -@ -I dts -O dtb -o /tmp/onjan-iio.dtbo onjan_service/onjan-iio.dts
sudo install -m 644 /tmp/onjan-iio.dtbo /boot/firmware/current/overlays/
sudo cp -n /boot/firmware/config.txt /boot/firmware/config.txt.before-onjan-iio
sudo nano /boot/firmware/config.txt
```

끝의 `[all]` 아래 `dtoverlay=onjan-iio` 한 줄을 추가하세요. 마이크용 기존 오버레이는 유지합니다.
정상 재부팅한 뒤 `pgrep -x pigpiod`가 비어 있고 `cat /sys/bus/iio/devices/iio:device*/name`에
hx711/srf04가 있는지 확인합니다. 별도 pigpiod 자동시작과 과거 pigpio 테스트를 함께 사용하지 마세요.
이전 온잔 전용 sudoers 규칙은 더 이상 필요하지 않습니다. HX711은 새 파일로 영점·보정을 다시 진행하세요.
이 커널/HC-SR04P 조합은 실제 Pi에서 검증이 필요합니다. 되돌리려면 추가한 dtoverlay 줄을 제거한 후 재부팅하세요.

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
- 통합 홈의 **모터 수동 테스트**에서 PCA9685 통신을 확인합니다. 기본 실행은 출력 잠금입니다.
  외부 V+와 공통 GND를 확인하고 부하를 분리한 뒤 `python -m onjan_service --confirm-external-power`로 실행하면
  선택한 채널 하나에 80/90/100°를 명령하고 0.6초 후 PWM을 끕니다. 컵 자동화는 시뮬레이션입니다.
- 마이크는 선택적 ALSA 2초 녹음과 dBFS/포화율 측정을 지원합니다. S32_LE, 48kHz,
  스테레오의 왼쪽 채널을 사용하므로 실제 드라이버 지원과 정렬 확인이 필요합니다.
  마이크 추가 핀은 `HARDWARE.md`를 참고하세요. OS의 I2S 드라이버 설정은 별도로 필요합니다.
- 녹음 중에도 커널 센서 수집은 계속됩니다. 녹음 직전 상태와 특징은 `data/measurement-rounds.jsonl`에 저장됩니다.
- Ctrl+C/SIGTERM으로 작업과 센서 종료를 기다린 뒤 자원을 정리합니다. 기존 HX711 평균화 등
  진행 중인 I/O는 즉시 취소되지 않으므로 종료에 수 초 걸릴 수 있습니다.

## 확인 순서

1. `--no-hardware`: 분위기 직접 선택 및 연속 재생 확인.
2. WAV 재생/정지와 실제 USB 출력 확인.
3. 기본 모드: 센서 상태, Tare/실제 무게추 보정 및 응답 중 상태 API 갱신 확인.
4. 모터 감지 시작: 빈 플랫폼 → 200g 이상 → 유지 → 제거하며 상태 전이 확인.
5. 마이크 측정: 소리 크기 변화, 왼쪽 채널, 포화율 확인.

실제 사용자 검증, 실물 모터 동작, I2S/pigpio 동시 사용, 학습된 음악 적합도 모델은
완료되지 않았습니다. 웹에 가상 AI·모터 시뮬레이션 표시를 유지합니다.
