"""Shared I2C lock prevents sensor and servo transactions from interleaving."""
import threading


class I2C:
    def __init__(self, number):
        from smbus2 import SMBus
        self.bus = SMBus(number)
        self.lock = threading.RLock()

    def scan(self):
        found = []
        with self.lock:
            for address in range(0x08, 0x78):
                try:
                    self.bus.read_byte(address)
                    found.append(address)
                except OSError:
                    pass
        return found

    def close(self):
        self.bus.close()
