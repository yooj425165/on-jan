"""Hardware-free checks for the servo example."""
import unittest
from argparse import Namespace
from mg996r_test import duty_cycle, run


class GPIOStub:
    BCM, OUT, LOW = 11, 0, 0

    def __init__(self):
        self.channels = {}
        self.cleaned = []

    def setmode(self, mode):
        pass

    def setup(self, pin, mode, initial):
        pass

    def PWM(self, pin, frequency):
        assert frequency == 50
        channel = self.Channel()
        self.channels[pin] = channel
        return channel

    def cleanup(self, pins):
        self.cleaned = pins

    class Channel:
        def __init__(self):
            self.values = []
            self.stopped = False

        def start(self, value):
            self.values.append(value)

        def ChangeDutyCycle(self, value):
            self.values.append(value)

        def stop(self):
            self.stopped = True


class ServoTests(unittest.TestCase):
    def args(self, servo):
        return Namespace(pins=[18, 13], servo=servo, low=75, high=105, cycles=1, hold=1)

    def test_nominal_pulses(self):
        self.assertEqual(duty_cycle(0), 5)
        self.assertEqual(duty_cycle(90), 7.5)
        self.assertEqual(duty_cycle(180), 10)

    def test_two_channels_and_cleanup(self):
        gpio = GPIOStub()
        run(self.args("both"), gpio, lambda _: None)
        self.assertEqual(gpio.channels[18].values, gpio.channels[13].values)
        self.assertEqual(len(gpio.channels[18].values), 6)
        self.assertEqual(gpio.cleaned, [18, 13])
        self.assertTrue(all(channel.stopped for channel in gpio.channels.values()))

    def test_interrupt_releases_only_selected_pin(self):
        gpio = GPIOStub()
        def interrupt(_):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            run(self.args("2"), gpio, interrupt)
        self.assertEqual(list(gpio.channels), [13])
        self.assertTrue(gpio.channels[13].stopped)
        self.assertEqual(gpio.cleaned, [13])


if __name__ == "__main__":
    unittest.main()
