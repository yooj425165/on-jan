class CupLights:
    GREEN, RED = 17, 27

    def __init__(self):
        import gpiod
        from gpiod.line import Direction, Value
        self.value = Value
        self.lines = gpiod.request_lines('/dev/gpiochip0', consumer='onjan-cup', config={
            pin: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=value)
            for pin, value in ((self.GREEN, Value.INACTIVE), (self.RED, Value.ACTIVE))})
        self.ready = False

    def show(self, ready):
        if ready != self.ready:
            self.lines.set_values({self.GREEN: self.value.ACTIVE if ready else self.value.INACTIVE,
                                   self.RED: self.value.INACTIVE if ready else self.value.ACTIVE})
            self.ready = ready

    def close(self):
        try:
            self.show(False)
        finally:
            self.lines.release()
