# Hardware tests

Run from `/home/ubuntu/on-jan`. Use `venv/bin/python`, not `.venv`.

## DHT11

See [DHT11.md](DHT11.md). DATA BCM4 is physical pin 7.

```sh
sudo ./venv/bin/python test/dht11_gpio.py --pin 4
```

## MG996R x 2

This example is for standard positional MG996R servos, not continuous-rotation modifications. Nominal angles are approximate and depend on calibration. It uses RPi.GPIO software PWM at 50 Hz, which can jitter under Linux load. For stable simultaneous servo control, a hardware PWM controller such as PCA9685 is a future option.

### Wiring (power off first)

| Connection | Destination |
| --- | --- |
| Servo 1 signal (usually orange/yellow) | Pi physical pin 12 / BCM18 |
| Servo 2 signal (usually orange/yellow) | Pi physical pin 33 / BCM13 |
| Both servo power wires (usually red) | Separate regulated 5-6 V supply, per module specification |
| Both servo ground wires (usually brown/black) | External supply GND |
| Pi physical pin 6 / GND | Same external supply GND |

Confirm wire labels for your modules. Do not power motors from GPIO or the Pi 3.3V rail. Use an external supply sized for the combined startup/stall current of both servos (several amperes; check the actual module specifications). Keep the external positive rail separate from the Pi power pins. Common ground is required.

Remove mechanical loads for the initial test and keep the horn clear. The first command moves to nominal center; the script cannot read the current shaft position. The default sequence is center -> 75 -> 90 -> 105 -> 90 degrees, repeated twice. It stops PWM and releases only the selected pins on completion or Ctrl+C, so holding torque is not guaranteed afterward.

### Commands

```sh
# No GPIO access or movement
./venv/bin/python test/mg996r_test.py --servo both --dry-run

# Test one motor at a time, then both
sudo ./venv/bin/python test/mg996r_test.py --servo 1
sudo ./venv/bin/python test/mg996r_test.py --servo 2
sudo ./venv/bin/python test/mg996r_test.py --servo both

# Custom BCM signal pins and a slower cycle
sudo ./venv/bin/python test/mg996r_test.py --pins 18 13 --servo both --hold 2 --cycles 1

# Hardware-free logic checks
./venv/bin/python -m unittest discover -s test -p 'test_*.py' -v
```

The supported test range is deliberately limited to 60..120 nominal degrees, using a conservative 1-2 ms nominal pulse mapping. Defaults stay within 75..105. Stop if the servo buzzes against a mechanical stop or the supply voltage drops. Do not run another process driving the same GPIO pins concurrently.
