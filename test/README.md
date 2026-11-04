# 하드웨어 테스트

`/home/ubuntu/on-jan` 폴더에서 실행합니다. 가상환경은 `.venv`가 아닌 `venv/bin/python`을 사용합니다.

## DHT11 온습도 센서

자세한 배선과 사용법은 [DHT11.md](DHT11.md)를 참고하세요. DATA에 사용하는 BCM GPIO4는 물리 7번 핀입니다.

```sh
sudo ./venv/bin/python test/dht11_gpio.py --pin 4
```

## MG996R 서보 모터 2개

이 예제는 일반적인 각도 제어형 MG996R용이며, 연속 회전형으로 개조된 모터용이 아닙니다. 지정 각도는 명목값으로, 실제 각도는 모터별 보정에 따라 달라집니다. RPi.GPIO의 50Hz 소프트웨어 PWM을 사용하므로 Linux 시스템 부하에 따라 떨림이 발생할 수 있습니다. 추후 안정적인 동시 제어가 필요하면 PCA9685 같은 하드웨어 PWM 제어기를 사용할 수 있습니다.

### 배선 (전원을 끈 상태에서 연결)

| 연결선 | 연결 위치 |
| --- | --- |
| 1번 모터 신호선 (보통 주황색/노란색) | Pi 물리 12번 핀 / BCM GPIO18 |
| 2번 모터 신호선 (보통 주황색/노란색) | Pi 물리 33번 핀 / BCM GPIO13 |
| 두 모터의 전원선 (보통 빨간색) | 모듈 사양에 맞는 별도의 5–6V 정전압 전원 |
| 두 모터의 접지선 (보통 갈색/검은색) | 외부 전원 GND |
| Pi 물리 6번 핀 / GND | 같은 외부 전원 GND |

선 색상만 믿지 말고 실제 모듈의 표시를 확인하세요. GPIO나 Pi의 3.3V 핀으로 모터에 전원을 공급하지 마세요. 외부 전원은 두 모터의 기동 전류와 축이 멈춰 있을 때의 최대 전류를 합한 값을 감당해야 합니다. 수 암페어 수준이 필요할 수 있으므로 실제 모듈 사양을 확인하세요. 외부 전원의 양극은 Pi 전원 핀과 분리하고, GND는 공통으로 연결합니다.

처음에는 기계적 부하를 분리하고 서보 암이 자유롭게 움직일 공간을 확보하세요. 첫 명령은 중앙 위치로 이동하며, 이 코드는 현재 축 위치를 읽을 수 없습니다. 기본 순서는 중앙 → 75° → 90° → 105° → 90°이며 두 번 반복합니다. 정상 종료나 Ctrl+C 시 PWM을 중단하고 선택한 핀만 해제하므로, 종료 후 위치를 유지하는 힘은 보장되지 않습니다.

### 실행 명령

```sh
# GPIO 접근이나 실제 움직임 없이 동작 순서만 확인
./venv/bin/python test/mg996r_test.py --servo both --dry-run

# 한 개씩 확인한 다음 두 개를 동시에 테스트
sudo ./venv/bin/python test/mg996r_test.py --servo 1
sudo ./venv/bin/python test/mg996r_test.py --servo 2
sudo ./venv/bin/python test/mg996r_test.py --servo both

# BCM 신호 핀을 지정하고 각 위치에서 2초씩 대기하며 한 번 반복
sudo ./venv/bin/python test/mg996r_test.py --pins 18 13 --servo both --hold 2 --cycles 1

# 하드웨어 없이 제어 로직 검증
./venv/bin/python -m unittest discover -s test -p 'test_*.py' -v
```

테스트 각도는 명목상 60–120°로 제한하며, 보수적인 1–2ms 펄스 범위에 대응시키는 계산을 사용합니다. 기본 동작 범위는 75–105°입니다. 모터가 기계적 한계에 걸려 윙윙거리거나 전원 전압이 떨어지면 중단하세요. 다른 프로세스에서 같은 GPIO 핀을 동시에 제어하지 마세요.

## 온습도 + 빛 통합 테스트

`environment_test.py`: DHT11과 KY-018의 측정값을 이용한 환경 판단입니다. KY-018은 MCP3008 ADC가 필요합니다. 배선과 실행 방법은 [ENVIRONMENT.md](ENVIRONMENT.md)를 참고하세요.
