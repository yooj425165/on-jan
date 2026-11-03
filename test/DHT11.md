# DHT11 GPIO 예제

원격 경로: `/home/ubuntu/on-jan`. RPi.GPIO가 설치된 환경은 `venv`입니다 (`.venv` 아님).

## 배선

전원을 끈 상태에서 연결하세요. 아래는 DATA에 BCM GPIO4를 사용하는 예시이며 실제 연결한 핀에 맞춰 실행 인자를 바꿉니다.

| DHT11 표시 | 물리 핀 | 역할 |
| --- | --- | --- |
| VCC / + | 1 | 3.3V |
| DATA / OUT / S | 7 | BCM GPIO4 |
| GND / - | 6 | GND |

제품마다 핀 배치가 다르므로 모듈의 표시를 확인합니다. bare 4핀 DHT11의 NC는 연결하지 않습니다. DATA와 3.3V 사이에 4.7~10kΩ 풀업 저항을 사용합니다 (모듈은 이미 내장될 수 있음). 내부 풀업만으로는 신뢰성이 낮을 수 있습니다. GPIO에 5V 신호를 입력하지 마세요.

## 실행

```sh
cd ~/on-jan
sudo ./venv/bin/python test/dht11_gpio.py --pin 4
```

`--pin 4`는 물리 4번이 아니라 **BCM GPIO4 / 물리 7번**입니다. DATA 배선을 확인한 다음 실행하세요. 2초마다 측정하며 Ctrl+C로 종료합니다.

```sh
# 5회 시도 후 종료
sudo ./venv/bin/python test/dht11_gpio.py --pin 4 --count 5
# 다른 SW가 처리할 수 있는 JSON Lines
sudo ./venv/bin/python test/dht11_gpio.py --pin 4 --json
```

GPIO 권한 때문에 sudo를 사용하되 가상환경 Python 경로를 직접 지정합니다. 성공 시 섭씨 온도, 상대습도, UTC 시각을 출력합니다. 실패 시 오류를 출력하고 다음 주기에 다시 시도합니다. 실패값을 정상값이나 0으로 바꾸지 않습니다.

Linux/Python의 스케줄링 때문에 DHT11의 마이크로초 신호를 놓칠 수 있습니다. 체크섬 오류는 버리고 재측정합니다. 반복적인 timeout은 핀 번호, 전원, 접지, 풀업을 확인하세요. 이 코드는 RPi.GPIO 학습용 폴링 예제이며 실시간성이 보장되는 드라이버가 아닙니다. 다른 프로세스에서 동일 핀을 동시에 사용하지 마세요.

온잔 서버의 기존 센서 API는 조도도 필수로 받으므로 이 예제는 측정 출력까지만 수행합니다. 조도 센서 연결 후 전송 어댑터에서 두 값을 합칠 수 있습니다.
