"""DHT11 polling example for Raspberry Pi 4 and RPi.GPIO."""
import argparse
import datetime
import json
import time


def decode(pulses):
    if len(pulses) != 40:
        raise ValueError("Expected 40 data pulses")
    data = [0] * 5
    for index, duration in enumerate(pulses):
        data[index // 8] = (data[index // 8] << 1) | int(duration > 50000)
    if sum(data[:4]) & 0xFF != data[4]:
        raise ValueError("Checksum failed; retrying next sample")
    humidity = data[0] + data[1] / 10.0
    temperature = data[2] + (data[3] & 0x7F) / 10.0
    if data[3] & 0x80:
        temperature = -temperature
    if not (0 <= humidity <= 100 and -20 <= temperature <= 80):
        raise ValueError("Out-of-range sensor reading")
    return temperature, humidity


def read_sensor(gpio, pin):
    gpio.setup(pin, gpio.OUT, initial=gpio.LOW)
    time.sleep(0.020)
    # Release the bus; an external pull-up supplies the high level.
    gpio.setup(pin, gpio.IN, pull_up_down=gpio.PUD_UP)

    def wait_while(level):
        start = time.perf_counter_ns()
        while gpio.input(pin) == level:
            if time.perf_counter_ns() - start > 1000000:
                raise TimeoutError("DHT11 response timeout; check DATA pin and wiring")
        return time.perf_counter_ns()

    wait_while(gpio.HIGH)
    wait_while(gpio.LOW)
    wait_while(gpio.HIGH)
    pulses = []
    for _ in range(40):
        rise = wait_while(gpio.LOW)
        fall = wait_while(gpio.HIGH)
        pulses.append(fall - rise)
    return decode(pulses)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pin", type=int, required=True, help="BCM GPIO number, not physical header pin")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between readings (minimum 2)")
    parser.add_argument("--count", type=int, default=0, help="Number of attempts; 0 means continuous")
    parser.add_argument("--json", action="store_true", help="Output JSON Lines")
    args = parser.parse_args()
    if args.pin not in range(2, 28):
        parser.error("Choose an exposed BCM GPIO between 2 and 27")
    if not 2 <= args.interval <= 3600 or args.count < 0:
        parser.error("interval must be 2..3600 and count must be nonnegative")

    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    attempts = 0
    try:
        GPIO.setup(args.pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        time.sleep(2)
        while args.count == 0 or attempts < args.count:
            started = time.monotonic()
            attempts += 1
            result = {"measuredAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), "pin": args.pin}
            try:
                temperature, humidity = read_sensor(GPIO, args.pin)
                result.update(temperature=temperature, humidity=humidity, ok=True)
            except (TimeoutError, ValueError) as error:
                result.update(ok=False, error=str(error))
            if args.json:
                print(json.dumps(result), flush=True)
            elif result["ok"]:
                print("{} | Temperature: {:.1f} C | Humidity: {:.1f} %".format(result["measuredAt"], temperature, humidity), flush=True)
            else:
                print("{} | Read failed: {}".format(result["measuredAt"], result["error"]), flush=True)
            if args.count == 0 or attempts < args.count:
                time.sleep(max(0, args.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        pass
    finally:
        GPIO.cleanup(args.pin)


if __name__ == "__main__":
    main()
