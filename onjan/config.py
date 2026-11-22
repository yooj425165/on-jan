"""BCM pins and adjustable measurement policies (not component specifications)."""
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Config:
    i2c_bus: int = 1
    dout: int = 5
    clock: int = 6
    trig: int = 23
    echo: int = 24
    intervals: dict = field(default_factory=lambda: {
        "light": 1.0, "weight": 0.5, "distance": 0.3, "pca": 5.0})
    near_cm: float = 15.0
    change_g: float = 5.0
    calibration_path: Path = ROOT / "data" / "hardware-calibration.json"
    audio_device: str = "plughw:CARD=UACDemoV10,DEV=0"
    # Set both only after checking external supply, common ground and mechanics.
    servo_power_confirmed: bool = False
    servo_enabled: bool = False
    servo_min_us: int = 1000
    servo_max_us: int = 2000
    servo_min_angle: float = 0.0
    servo_max_angle: float = 180.0
    servo_travel_deg: int = 180
    servo_initial_angle: float = 90.0
