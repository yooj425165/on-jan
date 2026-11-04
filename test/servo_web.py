"""Single-process Flask servo workbench, port 5006."""
import atexit
import fcntl
import math
import os
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 4096
lock = threading.Lock()
cancel = threading.Event()
state = dict(running=False, phase='대기', step=0, total=0, duty=None, target='both', error=None)
state['motors'] = {key: dict(command_angle=None, active=False) for key in ('1', '2')}
worker = None
gpio = None
gpio_lock = None


def validate(data):
    if not isinstance(data, dict):
        raise ValueError('설정값이 필요합니다.')
    target, mode = data.get('target'), data.get('mode')
    if target not in ('1', '2', 'both') or mode not in ('hold', 'sweep', 'angle', 'center'):
        raise ValueError('모터와 실행 방식을 선택하세요.')
    if mode in ('angle', 'center'):
        angle = 90 if mode == 'center' else data.get('angle')
        if isinstance(angle, bool) or not isinstance(angle, (float, int)) or not math.isfinite(angle) or not 0 <= angle <= 180:
            raise ValueError('명령 각도는 0~180도 범위여야 합니다.')
        data = dict(data, duty=5 + angle / 36, low=7.1, high=7.9, cycles=1)
    values = {}
    for name, low, high in [('duty', 5, 10), ('low', 5, 10), ('high', 5, 10), ('seconds', 0.3, 10), ('cycles', 1, 100)]:
        value = data.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{name}: {low}~{high} 범위를 입력하세요.')
        values[name] = value
    if int(values['cycles']) != values['cycles'] or values['low'] >= values['high']:
        raise ValueError('반복 횟수는 정수이며 시작 Duty는 끝 Duty보다 작아야 합니다.')
    return dict(values, target=target, mode=mode)


def execute(config):
    global gpio, gpio_lock
    channels, pins = [], []
    try:
        if gpio is None:
            # Hold a process-wide lock before importing or configuring GPIO.
            gpio_lock = open('/run/lock/onjan-servo-web.lock', 'w')
            fcntl.flock(gpio_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            import RPi.GPIO as driver
            gpio = driver
            gpio.setmode(gpio.BCM)
        selected = [18, 13] if config['target'] == 'both' else [18 if config['target'] == '1' else 13]
        for pin in selected:
            if cancel.is_set():
                return
            gpio.setup(pin, gpio.OUT, initial=gpio.LOW)
            pins.append(pin)
            pwm = gpio.PWM(pin, 50)
            channels.append(pwm)
            pwm.start(0)
        sequence = [config['duty']] if config['mode'] != 'sweep' else [config['low'], config['high'], config['low']] * int(config['cycles'])
        for index, duty in enumerate(sequence, 1):
            if cancel.is_set():
                break
            for channel in channels:
                channel.ChangeDutyCycle(duty)
            with lock:
                state.update(phase='구동 중', step=index, total=len(sequence), duty=duty)
                for pin in selected:
                    state['motors']['1' if pin == 18 else '2'].update(command_angle=round((duty - 5) * 36, 1), active=True)
            if cancel.wait(config['seconds']):
                break
    except Exception as error:
        with lock:
            state['error'] = f'{type(error).__name__}: {error}'
    finally:
        for channel in channels:
            try:
                channel.stop()
            except Exception:
                pass
        try:
            if gpio and pins:
                gpio.cleanup(pins)
        except Exception as error:
            with lock:
                state['error'] = f'GPIO cleanup: {error}'
        with lock:
            for motor in state['motors'].values():
                motor['active'] = False
            state.update(running=False, duty=None, phase='오류' if state['error'] else '정지됨' if cancel.is_set() else '완료')


@app.get('/')
def index():
    return send_from_directory(Path(__file__).parent, 'servo_web.html')


@app.get('/api/status')
def status():
    with lock:
        return jsonify(dict(state, gpio_access=os.access('/dev/gpiomem', os.R_OK | os.W_OK)))


@app.before_request
def same_origin():
    if request.method == 'POST' and request.headers.get('Origin') != request.host_url.rstrip('/'):
        return jsonify(error='같은 웹 화면에서 실행해주세요.'), 403


@app.post('/api/start')
def start():
    global worker
    try:
        config = validate(request.get_json(silent=True))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    with lock:
        if state['running']:
            return jsonify(error='현재 테스트를 정지한 뒤 다시 실행하세요.'), 409
        if not os.access('/dev/gpiomem', os.R_OK | os.W_OK):
            return jsonify(error='GPIO 권한이 없습니다. sudo로 서버를 실행해주세요.'), 503
        cancel.clear()
        state.update(running=True, phase='준비 중', error=None, step=0, total=int(config['cycles']) * 3 if config['mode'] == 'sweep' else 1, target=config['target'])
        worker = threading.Thread(target=execute, args=(config,), daemon=True)
        worker.start()
    return jsonify(ok=True)


@app.post('/api/stop')
def stop():
    with lock:
        cancel.set()
    return jsonify(ok=True)


def cleanup():
    cancel.set()
    if worker:
        worker.join(timeout=3)


atexit.register(cleanup)
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5006, debug=False, use_reloader=False, threaded=True)
