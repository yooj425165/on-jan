"""DHT11 + KY-018 (via MCP3008) environment example."""
import argparse
import datetime
import json
import math
import time

from dht11_gpio import read_sensor

DHT_PIN = 4
CLK, MISO, MOSI, CS = 11, 9, 10, 8


def classify(temperature=None, humidity=None, brightness=None):
    labels = []
    if humidity is not None:
        if humidity >= 70:
            labels.append("습하다")
        else:
            labels.append("습도 보통")
    if temperature is not None:
        if temperature >= 28:
            labels.append("덥다")
        elif temperature >= 24:
            labels.append("따뜻하다")
        elif temperature < 18:
            labels.append("춥다")
        else:
            labels.append("쾌적하다")
    if brightness is not None:
        if brightness >= 70:
            labels.append("밝다")
        elif brightness < 30:
            labels.append("어둡다")
        else:
            labels.append("은은하다")
    return labels


def relative_brightness(raw, dark, bright):
    return max(0.0, min(100.0, (raw - dark) / (bright - dark) * 100))


def read_adc(gpio):
    # Software SPI mode 0: start bit, single-ended CH0, then 10-bit result.
    received = []
    gpio.output(CLK, False)
    gpio.output(CS, False)
    try:
        for byte in (0x01, 0x80, 0x00):
            value = 0
            for bit in range(7, -1, -1):
                gpio.output(MOSI, bool(byte & (1 << bit)))
                time.sleep(0.00001)
                gpio.output(CLK, True)
                value = (value << 1) | gpio.input(MISO)
                time.sleep(0.00001)
                gpio.output(CLK, False)
            received.append(value)
    finally:
        gpio.output(CS, True)
    return ((received[1] & 3) << 8) | received[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--light', choices=['none', 'mcp3008'], default='none')
    parser.add_argument('--dark-raw', type=int, help='ADC reading with sensor covered')
    parser.add_argument('--bright-raw', type=int, help='ADC reading in reference bright light')
    parser.add_argument('--interval', type=float, default=2)
    parser.add_argument('--count', type=int, default=0, help='0 = continuous')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    if not math.isfinite(args.interval) or not 2 <= args.interval <= 3600 or args.count < 0:
        parser.error('interval: 2..3600 seconds; count: nonnegative')
    calibration = args.dark_raw is not None and args.bright_raw is not None
    if (args.dark_raw is None) != (args.bright_raw is None):
        parser.error('Provide both --dark-raw and --bright-raw')
    if calibration and (not all(0 <= n <= 1023 for n in (args.dark_raw, args.bright_raw)) or args.dark_raw == args.bright_raw):
        parser.error('Calibration values must be distinct numbers in 0..1023')

    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    pins = []
    try:
        GPIO.setup(DHT_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        pins.append(DHT_PIN)
        if args.light == 'mcp3008':
            for pin, initial in ((CS, GPIO.HIGH), (CLK, GPIO.LOW), (MOSI, GPIO.LOW)):
                GPIO.setup(pin, GPIO.OUT, initial=initial)
                pins.append(pin)
            GPIO.setup(MISO, GPIO.IN)
            pins.append(MISO)
        time.sleep(2)
        attempt = 0
        while args.count == 0 or attempt < args.count:
            started = time.monotonic()
            attempt += 1
            result = dict(measuredAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), temperature=None, humidity=None, light_raw=None, brightness_percent=None, errors=[])
            try:
                result['temperature'], result['humidity'] = read_sensor(GPIO, DHT_PIN)
            except (TimeoutError, ValueError) as error:
                result['errors'].append('DHT11: ' + str(error))
            if args.light == 'mcp3008':
                raw = read_adc(GPIO)
                result['light_raw'] = raw
                if calibration:
                    result['brightness_percent'] = round(relative_brightness(raw, args.dark_raw, args.bright_raw), 1)
                else:
                    result['errors'].append('조도 보정 필요: dark-raw와 bright-raw를 지정하세요.')
                if raw in (0, 1023):
                    result['errors'].append('ADC 끝값: 포화 또는 배선/연결 상태를 확인하세요.')
            else:
                result['errors'].append('조도 미연결: KY-018에는 별도 ADC가 필요합니다.')
            result['labels'] = classify(result['temperature'], result['humidity'], result['brightness_percent'])
            if args.json:
                print(json.dumps(result, ensure_ascii=False), flush=True)
            else:
                def display(value, unit):
                    return '미측정' if value is None else f'{value}{unit}'
                print('{} | 온도 {} | 습도 {} | 빛 {} (ADC {}) | {}'.format(result['measuredAt'], display(result['temperature'], '°C'), display(result['humidity'], '%'), display(result['brightness_percent'], '%'), result['light_raw'], ' / '.join(result['labels']) or '판단 불가'), flush=True)
                for error in result['errors']:
                    print('  참고: ' + error, flush=True)
            if args.count == 0 or attempt < args.count:
                time.sleep(max(0, args.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        pass
    finally:
        if pins:
            GPIO.cleanup(pins)


if __name__ == '__main__':
    main()
