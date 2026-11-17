# ONJAN Raspberry Pi 하드웨어 테스트

## 1. 전체 시스템 구조

Raspberry Pi 4에서 `python -m onjan.web`을 실행하고 같은 네트워크의 휴대폰/PC에서
접속합니다. 센서 데이터는 Pi에서 수집하며 음악도 **Pi에 연결한 USB 스피커**에서
재생됩니다. 브라우저에서 소리가 나는 방식이 아닙니다.

- 센서별 스레드: 조도 1초, 무게 0.5초, 거리 0.3초, PCA 통신 5초. 측정 자체가
  주기보다 오래 걸리면 중복 측정하지 않습니다. HX711 평균화는 실제로 0.5초 이상 걸릴 수 있습니다.
- 공유 I2C에 잠금 적용. 한 센서 측정 실패는 해당 상태만 오류로 바뀌며 다음 주기에 재시도합니다.
- 하드웨어 초기화 실패는 원인을 로그와 웹에 표시합니다. 배선을 고친 뒤 서버를 재시작하세요.
- `HardwareService.snapshot()` / `GET /api/status`: 측정 시각, 지연 여부, 단위별 데이터와
  오류를 제공하므로 향후 AI/FastAPI에서 동일 서비스를 사용할 수 있습니다.
- 센서 수집은 모터를 자동으로 움직이지 않습니다. 마이크는 비활성화되어 있으며 가짜 센서값은 없습니다.
- 웹의 서보 제어는 항상 잠겨 있습니다. 시작/종료 시 가능한 경우 PCA9685 출력을 OFF로 합니다.
  V+ 전압을 측정할 하드웨어가 없으므로 전원 존재 여부를 소프트웨어로 감지할 수 없습니다.
- 무게 변화는 직전 평균값 대비 변화량입니다. 기본 변화 기준 5g, 접근 기준 15cm는
  앱의 조정 가능한 정책이며 부품의 정확도/해상도 보증이 아닙니다.

## 2. 디렉터리 및 Python 파일 역할

```text
onjan/
  __init__.py       패키지
  config.py         최종 BCM 핀, 주기, 서보 잠금과 정책
  i2c.py            공유 I2C 버스, 장치 탐색, 잠금
  sensors.py        BH1750 / HX711 / HC-SR04P 드라이버
  weight.py         평균값의 g 환산, 영점, 실측 보정 저장
  servo.py          PCA9685 채널 0/1 개별 제어, 범위 제한, 부드러운 이동
  music.py          기존 test/music_web.py의 Player 재사용
  service.py        초기화, 독립 수집, 통합 객체, 종료 정리
  web.py            Flask API, 실행 진입점
  templates/index.html
  static/style.css
  static/app.js
tests/test_hardware.py
requirements-hardware.txt
data/hardware-calibration.json  # 실측 후 생성, Git 제외
music/*.wav                    # 기존 파일 사용, Git 제외
```

각 Python 파일의 전체 구현은 위 경로에 저장되어 있습니다. 기존 음악 테스트 파일은
수정하지 않고 재사용하므로 Pi에도 `test/music_web.py`를 함께 가져가세요.

## 3. 라이브러리와 설치

Raspberry Pi 4 + Raspberry Pi OS에서 실행합니다. BCM 번호를 사용합니다.
`pigpiod`의 DMA 파형과 타임스탬프를 사용하여 Linux/Python 스케줄링에 의한
HX711 클럭 HIGH 연장 및 초음파 타이밍 오차를 줄입니다. Pi 5용 코드가 아닙니다.

```bash
sudo apt update
sudo apt install python3-venv python3-dev pigpio i2c-tools alsa-utils
sudo raspi-config
# Interface Options -> I2C -> Enable
sudo systemctl enable --now pigpiod
sudo usermod -aG i2c,audio "$USER"
# 그룹 변경 적용을 위해 로그아웃 후 다시 로그인
cd ~/on-jan  # Pi에 복사/clone한 실제 프로젝트 경로
python3 -m venv .venv-pi
source .venv-pi/bin/activate
python -m pip install -r requirements-hardware.txt
```

배포판 저장소에 `pigpio`가 없으면 Pi OS 버전의 pigpio 패키지/공식 설치 방법을 확인하세요.
`pip install pigpio`는 클라이언트만 설치하므로 데몬 설치를 대체하지 않습니다.
실행 중에는 다른 GPIO 테스트, 다른 HX711 프로그램, pigpio waveform 프로그램을 종료하세요.
pigpiod는 기본 5us 샘플링을 사용하세요. 이 코드는 20us HIGH/LOW 펄스를 씁니다.

## 4. 최종 핀 연결과 확인 사항

| 장치 | 신호 | BCM | 물리 핀 |
| --- | --- | --- | --- |
| PCA9685 + BH1750 | SDA | 2 | 3 |
| PCA9685 + BH1750 | SCL | 3 | 5 |
| HX711 | DOUT | 5 | 29 |
| HX711 | SCK | 6 | 31 |
| HC-SR04P | TRIG | 23 | 16 |
| HC-SR04P | ECHO | 24 | 18 |
| INMP441 | SCK / BCLK | 18 | 12 |
| INMP441 | WS / LRCL | 19 | 35 |
| INMP441 | SD (Pi의 PCM_DIN으로 입력) | 20 | 38 |
| INMP441 | VDD / VCC (3.3V) | - | 17 |
| INMP441 | GND | - | 20 |
| INMP441 | L/R (왼쪽 채널 선택) | - | 20 또는 공통 GND |
| 센서 + PCA 로직 | 3.3V | - | 1 |
| 공통 접지 | GND | - | 6 등 GND 핀 |

### INMP441 추가 배선 계획

위 INMP441 배치는 기존 I2C(GPIO2/3), HX711(GPIO5/6), 초음파(GPIO23/24)를
유지하면서 추가하는 배선 계획입니다. **현재 마이크 드라이버와 AI 입력 연동은
미구현이며, 실제 녹음도 미검증입니다.** 기존 코드에서는 마이크가 비활성화되어 있습니다.

- 마이크 전원은 3.3V입니다. 모듈에 인쇄된 핀 이름을 기준으로 연결하세요.
- **BCM GPIO20(물리 38번)**은 마이크 SD 입력입니다.
  **물리 20번**은 GND이므로 두 번호를 혼동하지 마세요.
- L/R은 GND에 연결해 왼쪽 채널을 선택합니다. ALSA의 실제 채널 배치는 녹음으로 확인해야 합니다.
- GPIO21(PCM_DOUT)은 사용하지 않습니다. USB 스피커는 USB 연결을 유지합니다.
- Ubuntu에서는 커널에 맞는 I2S/ALSA 캡처 드라이버와 Device Tree 설정이 필요합니다.
  `dtparam=i2s=on`만으로 녹음 장치 등록이 완료되지는 않습니다.
- 핀 번호는 겹치지 않지만, 현재 HX711이 사용하는 pigpio DMA 파형과 I2S가
  PCM/PWM 타이밍 자원을 공유할 가능성이 있습니다. 마이크와 HX711의 동시 동작을
  검증한 뒤 사용해야 하며, 충돌하면 HX711 클럭 생성 방식 등을 조정해야 합니다.
- 서보 배선은 계속 PCA9685 채널 0/1이고, 외부 전원 준비 전에는 V+ 미연결 및 구동 잠금을 유지합니다.

Ubuntu에서 마이크 설정 전에 확인할 정보:

```bash
uname -r
arecord -l
ls /boot/firmware/overlays/*i2s*
ls /boot/firmware/overlays/*googlevoice*
```

오버레이 파일이 없다는 결과도 진단 정보입니다. 위 명령은 설정을 변경하지 않습니다.

- PCA9685 VCC는 3.3V **로직 전원**, V+는 별도 **서보 전원**입니다. 현재 V+ 미연결 유지.
- SDA와 SCL 각각 병렬 연결. 시작 시 0x08~0x77 주소를 읽기 탐색합니다.
  이 탐색은 현재 구성용이며 임의의 다른 I2C 장치가 있는 버스에서는 해당 장치의 탐색 지원을 확인하세요.
- PCA 기본 주소 0x40, BH1750은 0x23/0x5C 자동 시도. PCA의 0x70 all-call 주소도 보일 수 있습니다.
- MG996R 두 개는 채널 0/1. 외부 전원은 두 모터의 기동/정지 전류를 감당하는 제품을 선정하고
  전압·배선 용량은 실제 모터 사양에서 확인하세요. **Pi 5V 핀이나 브레드보드 레일로 서보 전원을 공급하지 마세요.**
- 외부 전원 GND와 Pi GND는 공통 연결. 서보 색상은 보통 갈색/검정 GND, 빨강 전원,
  주황/노랑 PWM이나 실제 제품을 확인하세요.
- HX711 E+/E-/A+/A-는 로드셀 제품 사양 기준입니다. 색상만으로 결정하지 마세요.
- HC-SR04P의 3.3V 동작과 ECHO 전압을 실제 모듈에서 확인하세요. ECHO가 5V라면 분압/레벨 변환이 필요합니다.
- 코드의 거리 허용 범위 2~400cm, 음속 343m/s는 일반적인 측정 필터/실온 근사입니다.
  모듈의 실제 범위와 환경에 맞춰 `sensors.py`를 조정하세요. 온도 보정 센서는 사용하지 않습니다.
- HX711 gain=128 / channel A, BH1750 기본 MTreg 기준입니다. 노이즈는 5개 샘플의
  median/MAD 이상값 제거 후 평균으로 줄이지만 설치/접지 문제를 보정해 주지는 않습니다.

## 5. 실행

```bash
source .venv-pi/bin/activate
i2cdetect -y 1
aplay -l
aplay -L
python -m onjan.web
```

같은 네트워크에서 `http://<Pi-IP>:5008` 접속. IP는 `hostname -I`로 확인합니다.
인터넷에 포트를 공개하지 않는 로컬 테스트용 Flask 서버입니다. 단일 프로세스로 실행하세요.
개발 리로더/여러 worker는 GPIO 중복 제어를 일으키므로 사용하지 않습니다.

```bash
# 기존 음악 테스트와 같은 기본 장치명. Pi의 aplay -L 결과가 다르면 변경
python -m onjan.web --audio-device 'plughw:CARD=UACDemoV10,DEV=0'
# 주기 변경
python -m onjan.web --light-interval 2 --weight-interval 1 --distance-interval 0.5
```

WAV 파일은 Git에서 제외되어 있으므로 Pi의 `music/`로 별도로 복사하세요.
현재 개발 폴더의 `bach_aria.wav`, `bach_gavotte.wav`를 그대로 사용할 수 있습니다.
기존 다운로드 절차는 `test/MUSIC_WEB.md`를 참고하세요.

종료: Ctrl+C 또는 SIGTERM. 측정 종료를 기다리고 음악 정지, PCA 출력 OFF,
소유한 GPIO 입력 전환, I2C 종료, pigpio 연결 해제를 수행합니다.
전원 차단/SIGKILL 상황에서는 소프트웨어 정리가 실행되지 않습니다.

## 6. 센서별 단독 확인

웹은 연결되지 않은 센서가 있어도 실행되므로 한 부품씩 연결하고 해당 카드만 확인할 수 있습니다.
배선 변경은 전원을 끄고 하세요. 센서 측정 실패 시 숫자 대신 오류를 표시합니다.

1. **BH1750**: I2C 탐색 주소 확인 → 웹 밝기 카드 확인 → 손으로 가리고 lux 감소 확인.
2. **HX711**: 로드셀 배선 확인 → RAW 변화 확인 → 플랫폼을 비우고 Tare → 실제 무게추를
   올리고 정확한 g 입력 후 보정 저장 → 제거했을 때 약 0g → 다시 올려 실제 무게와 비교.
   다른 무게추로 선형성과 반복성을 확인하세요. 보정 전에는 RAW만 표시하고 g를 지어내지 않습니다.
   부호가 반대인 배선에서는 음수 counts/g 계수가 정상일 수 있습니다.
3. **음료 무게**: 플랫폼 영점으로 측정하면 컵+내용물 무게입니다. 빈 컵을 올리고 Tare하면
   내용물 순질량을 얻습니다. 이를 바로 ml나 잔량 %로 환산하지 않습니다. 밀도/컵 용량이 필요합니다.
4. **초음파**: 평평한 물체를 10cm, 20cm 등에 놓고 실제 자와 비교. 15cm 이내 `near=true`
   확인. 대상이 없을 때 시간 초과가 날 수 있으며 유효한 0cm로 표시하지 않습니다.
5. **PCA9685**: V+ 없이 0x40 탐색 및 통신 정상/PWM OFF만 확인. 모터 움직임은 테스트하지 않습니다.
6. **음악**: WAV 선택 → 재생 → USB 스피커 소리 확인 → 정지. 오류는 음악 카드에 표시됩니다.

보정 계수는 실제 측정값에서 `(loaded_raw - tare_raw) / known_grams`로 계산하고 로컬 파일에 저장합니다.
영점은 설치/온도/전원 상태에 따라 변하므로 저장하지 않으며 매번 다시 맞춥니다.
이미 검증한 계수 설정은 `Weight.set_factor(counts_per_g)` 또는 웹 페이지 토큰을 사용하는
`POST /api/factor` JSON `{"counts_per_g": 실제계수}`로 가능합니다. 웹 UI는 무게추 기반 절차를 권장합니다.

## 7. 통합 확인과 향후 모터 테스트

- 센서 3개의 값을 동시에 보면서 WAV 재생. 무게를 바꾸고 물체를 이동해 각각 갱신되는지 확인.
- 오류가 있는 센서의 카드만 오류로 표시되고 다른 센서/음악이 유지되는지 확인.
- JSON에서 `ok`, `stale`, `updated_at`, `data`를 함께 사용하세요. 오류 시 `data=null`입니다.
- 페이지 재접속, 음악 종료, Ctrl+C 후 재실행, 저장된 보정 계수와 재영점 필요 상태 확인.
- 실제 센서/스피커는 개발 Mac에서 검증할 수 없습니다. 아래 소프트웨어 검사는 실측을 대체하지 않습니다.

```bash
python -m unittest discover -s tests -v
python -m unittest discover -s test -p 'test_music_web.py' -v
curl http://127.0.0.1:5008/api/status
```

**외부 전원 구매 후에만**: 실제 MG996R의 펄스/각도 범위, 링크 기구의 충돌 범위,
전압/전류와 공통 GND를 확인한 뒤 `Config`의 범위를 설정하고 코드에서
`servo_enabled=True`, `servo_power_confirmed=True`를 모두 명시해야 합니다.
현재 1000~2000us/0~180도 설정은 출고 보정된 MG996R 사양이 아니라 변경용 템플릿입니다.
확인 없이 활성화하지 마세요. `Servos.motor_1`, `motor_2`, `home`, `move`를 제공합니다.
모터 역할은 `Servos.roles`에서 변경할 수 있습니다. 웹에는 활성화 버튼/API를 제공하지 않습니다.
위치 피드백이 없으므로 최초 명령은 실제 위치에서 부드럽게 이동한다고 보장할 수 없습니다.
후속 명령만 마지막 명령 각도 기준으로 20ms 간격 보간합니다. home은 자동 호출하지 않습니다.

## 8. 오류와 해결

| 증상 | 확인/해결 |
| --- | --- |
| No module named flask/smbus2/pigpio | `.venv-pi` 활성화 후 requirements 설치 |
| `/dev/i2c-1` 없음 | raspi-config I2C 활성화 후 재부팅 |
| I2C Permission denied | i2c 그룹 등록 후 다시 로그인 |
| BH1750 주소 응답 없음 | SDA/SCL 혼선, 3.3V/GND, ADDR 점퍼 확인 |
| PCA9685 통신 실패 | VCC 3.3V와 GND, 주소 점퍼 확인. V+는 로직 통신에 필요 없음 |
| pigpiod 연결 실패 | `systemctl status pigpiod`, 데몬 설치 및 실행 확인 |
| HX711 DOUT 준비 시간 초과 | BCM5/6과 전원, HX711 준비 신호 확인 |
| HX711 포화/불안정/항상 0 | E+/E-/A+/A- 사양, 로드셀 고정, 과부하, 공통 접지 확인 |
| 보정 파일 오류 | `data/hardware-calibration.json`을 백업 후 제거하고 실제 무게추로 재보정 |
| g가 표시되지 않음 | 실제 무게추 보정 및 이번 실행에서 Tare가 모두 필요 |
| 초음파 ECHO 시간 초과/HIGH | TRIG/ECHO 배선, 동작 전압, 반사 대상 및 측정 범위 확인 |
| WAV 목록 없음 | Git에서 제외된 `.wav`를 Pi의 `music/`에 직접 복사 |
| Unknown PCM / 소리 없음 | `aplay -L`, `--audio-device`, `alsamixer` 출력/음소거 확인 |
| Device or resource busy | 다른 aplay/음악 테스트/사운드 프로그램 종료 |
| 웹 접속 불가 | 같은 LAN, Pi IP, 5008 포트, 서버 로그 확인 |
| 센서 초기화 실패 후 복구 안 됨 | 전원을 끄고 배선 수정 후 서버 재시작 |

기존 온습도/서보 직접 GPIO 테스트는 과거 배선용입니다. 최종 배선에서는 이 웹만 실행하세요.
