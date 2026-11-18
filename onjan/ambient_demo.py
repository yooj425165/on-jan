"""Train the synthetic light + sound model: python -m onjan.ambient_demo."""
import math

import joblib
import numpy as np
from sklearn.ensemble import RandomForestRegressor

from .config import ROOT

MODEL = ROOT / 'artifacts' / 'ambient-v1.joblib'
FEATURES = ['illuminance_lux', 'rms_dbfs']


def train():
    rng = np.random.default_rng(42)
    light, sound = rng.random((2, 1200))
    energy = 0.35 * light + 0.65 * sound
    scores = np.column_stack((1 - energy, energy, 0.9 - 0.5 * abs(energy - 0.35)))
    x = np.column_stack((light * 1000, -90 + 90 * sound))
    model = RandomForestRegressor(n_estimators=64, min_samples_leaf=4, random_state=42)
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({'features': FEATURES, 'model': model.fit(x, scores)}, MODEL)
    print(f'가상 조도·음량 규칙으로 학습한 데모 모델: {MODEL}')


def predict(lux, rms):
    if not all(math.isfinite(n) for n in (lux, rms)) or lux < 0 or rms > 0:
        raise ValueError('유효하지 않은 lux/dBFS 입력입니다.')
    if not MODEL.exists():
        raise ValueError('먼저 python -m onjan.ambient_demo 로 모델을 생성하세요.')
    bundle = joblib.load(MODEL)
    if bundle['features'] != FEATURES:
        raise ValueError('ambient 모델 입력 형식 불일치')
    x = [min(lux, 1000), max(rms, -90)]
    return bundle['model'].predict([x])[0].tolist(), dict(zip(FEATURES, x))


if __name__ == '__main__':
    train()
