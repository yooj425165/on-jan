"""Bounded MG996R position-servo test using RPi.GPIO software PWM."""
import argparse
import math
import time


def duty_cycle(angle):
    # Conservative nominal 1-2 ms pulses at 50 Hz; actual angles vary by servo.
    return (1.0 + angle / 180.0) / 20.0 * 100.0


def run(args, gpio=None, sleep=time.sleep):
    pins = args.pins
    selected = pins if args.servo == "both" else [pins[int(args.servo) - 1]]
    pwms = []
    configured = []
    try:
        if gpio:
            gpio.setmode(gpio.BCM)
            for pin in selected:
                gpio.setup(pin, gpio.OUT, initial=gpio.LOW)
                configured.append(pin)
                pwm = gpio.PWM(pin, 50)
                pwms.append(pwm)
                pwm.start(0)
        def position(angle):
            duty = duty_cycle(angle)
            print("BCM {} -> nominal {} deg | {:.3f}% duty".format(selected, angle, duty), flush=True)
            for pwm in pwms:
                pwm.ChangeDutyCycle(duty)
            sleep(args.hold if gpio else 0)

        position(90)
        for _ in range(args.cycles):
            for angle in (args.low, 90, args.high, 90):
                position(angle)
    finally:
        # Remove pulses even when interrupted; do not command a new position.
        for pwm in pwms:
            pwm.stop()
        if gpio and configured:
            gpio.cleanup(configured)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pins", nargs=2, type=int, default=[18, 13], metavar=("SERVO1_BCM", "SERVO2_BCM"))
    parser.add_argument("--servo", choices=["1", "2", "both"], default="1")
    parser.add_argument("--low", type=float, default=75)
    parser.add_argument("--high", type=float, default=105)
    parser.add_argument("--hold", type=float, default=1.0, help="Seconds per position")
    parser.add_argument("--cycles", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true", help="Print sequence without importing GPIO or moving motors")
    args = parser.parse_args()
    if len(set(args.pins)) != 2 or any(pin not in range(2, 28) for pin in args.pins):
        parser.error("Use two distinct BCM pins in 2..27")
    if not all(math.isfinite(v) for v in (args.low, args.high, args.hold)):
        parser.error("Angles and hold time must be finite")
    if not 60 <= args.low < 90 < args.high <= 120:
        parser.error("Test range must satisfy 60 <= low < 90 < high <= 120")
    if not 0.3 <= args.hold <= 10 or not 1 <= args.cycles <= 100:
        parser.error("hold must be 0.3..10 seconds; cycles must be 1..100")
    gpio = None
    if not args.dry_run:
        import RPi.GPIO as gpio
    try:
        run(args, gpio)
    except KeyboardInterrupt:
        print("Stopped; PWM released.", flush=True)


if __name__ == "__main__":
    main()
