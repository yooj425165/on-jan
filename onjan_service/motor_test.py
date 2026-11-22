"""Standalone PCA9685 bench test. No GPIO sensor or audio workers."""
import argparse
import secrets
import threading
import time

from flask import Flask, jsonify, render_template, request

from onjan.config import Config
from onjan.i2c import I2C
from onjan.servo import Servos


def create_app(bus, config):
    app = Flask(__name__)
    token = secrets.token_urlsafe(32)
    lock = threading.Lock()
    servos = Servos(bus, config)
    powered = config.servo_enabled and config.servo_power_confirmed

    @app.get('/')
    def index():
        return render_template('motor.html', token=token, powered=powered, config=config)

    @app.post('/test')
    def test():
        if request.headers.get('X-Onjan-Token') != token:
            return jsonify(error='페이지를 새로고침하세요.'), 403
        if not lock.acquire(False):
            return jsonify(error='이미 테스트 중입니다.'), 409
        try:
            data = request.get_json()
            if not isinstance(data, dict):
                return jsonify(error='잘못된 요청'), 400
            # Read only MODE1; an ACK is not evidence that V+ is powered.
            mode = bus.bus.read_byte_data(0x40, 0)
            if data.get('action') == 'probe':
                return jsonify(message=f'0x40 통신 정상 (MODE1={mode:#04x}). V+는 별도 확인하세요.')
            if not powered:
                return jsonify(error='외부 전원 미확인: 출력 잠금'), 403
            ch, angle = data.get('channel'), data.get('angle')
            if (data.get('action') != 'pulse' or type(ch) is not int or ch not in (0, 1)
                    or type(angle) not in (int, float)
                    or not config.servo_min_angle <= angle <= config.servo_max_angle):
                return jsonify(error=f'채널 0/1, 목표 각도 {config.servo_min_angle:g}~{config.servo_max_angle:g}°를 입력하세요.'), 400
            try:
                servos.move(ch, angle, duration=0)
                time.sleep(.6)
            finally:
                servos.disable()
            return jsonify(message=f'CH{ch} {angle}° 명령 완료 · PWM OFF (위치 피드백 없음)')
        except OSError as exc:
            return jsonify(error=f'I2C 오류: {exc}. 출력 상태 확인 필요'), 503
        finally:
            lock.release()

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-external-power', action='store_true')
    parser.add_argument('--travel', type=int, choices=(180, 360), default=180,
                        help='위치 제어 서보의 실제 작동 범위(도)')
    parser.add_argument('--port', type=int, default=5008)
    args = parser.parse_args()
    config = Config(servo_enabled=args.confirm_external_power,
                    servo_power_confirmed=args.confirm_external_power,
                    servo_max_angle=args.travel, servo_travel_deg=args.travel,
                    servo_initial_angle=args.travel / 2)
    bus = I2C(config.i2c_bus)
    try:
        if args.confirm_external_power:
            Servos(bus, config).disable()
        create_app(bus, config).run(host='0.0.0.0', port=args.port, use_reloader=False)
    finally:
        try:
            if args.confirm_external_power:
                Servos(bus, config).disable()
        finally:
            bus.close()


if __name__ == '__main__':
    main()
