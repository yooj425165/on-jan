"""Synthetic learning demonstration, not a validated mood inference model.

Run: python -m onjan.ai_demo
Predict: python -m onjan.ai_demo predict --lux 100 --weight-g 250 --distance-cm 15
"""
import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "artifacts" / "ai-demo.joblib"
FEATURES = ["illuminance_lux", "cup_weight_g", "distance_cm"]
TARGETS = ["calmness", "energy", "comfort"]
NOTICE = "가상 데이터 학습 실습: 실제 감정·쾌적함·음악 적합도를 검증한 모델이 아닙니다."


def make_data(seed=42, count=600):
    """Invent labels to demonstrate learning. Weight/distance are distractors.

    These equations deliberately encode a brightness preference. They are not
    scientific relationships or participant ratings, and must not train production.
    """
    rng = np.random.default_rng(seed)
    lux = rng.uniform(0, 1000, count)
    frame = pd.DataFrame({
        "illuminance_lux": lux,
        "cup_weight_g": rng.uniform(0, 600, count),
        "distance_cm": rng.uniform(2, 150, count),
    })
    brightness = lux / 1000
    targets = np.column_stack([
        0.9 - 0.7 * brightness,
        0.1 + 0.8 * brightness,
        0.85 - 0.65 * np.abs(brightness - 0.35),
    ])
    targets = np.clip(targets + rng.normal(0, 0.04, targets.shape), 0, 1)
    frame[TARGETS] = targets
    frame.insert(0, "sample_id", [f"SYNTH-{i:04d}" for i in range(count)])
    frame.insert(1, "source", "synthetic_rule_demo")
    return frame


def inputs(lux, weight, distance):
    values = np.asarray([lux, weight, distance], dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("입력은 유한한 숫자여야 합니다.")
    for value, low, high, name in zip(values, [0, 0, 2], [1000, 600, 150], FEATURES):
        if not low <= value <= high:
            raise ValueError(f"{name}: 실습 범위 {low}~{high} 안으로 입력하세요.")
    return pd.DataFrame([values], columns=FEATURES)


def load_model(path):
    # joblib uses pickle: load only artifacts you created or explicitly trust.
    bundle = joblib.load(path)
    if (bundle.get("schema_version") != 1 or bundle.get("source") != "synthetic_rule_demo"
            or bundle.get("features") != FEATURES or bundle.get("targets") != TARGETS):
        raise ValueError("이 실습과 호환되지 않는 모델 파일입니다.")
    return bundle["model"]


def show_prediction(model, label, lux, weight, distance):
    prediction = model.predict(inputs(lux, weight, distance))[0]
    print(f"\n{label}: 조도 {lux:g} lux / 무게 {weight:g} g / 거리 {distance:g} cm")
    for name, value in zip(TARGETS, prediction):
        bar = "#" * round(float(value) * 20)
        print(f"  {name:9s} [{bar:<20s}] {value:.3f}")
    return prediction


def train(path=MODEL):
    print(NOTICE)
    frame = make_data()
    csv = ROOT / "data" / "examples" / "ai-demo-generated.csv"
    frame.to_csv(csv, index=False)
    print(f"\n[1/5] 가상 데이터 {len(frame)}행 생성: {csv}")
    print("연습 규칙: 밝을수록 energy 증가, calmness 감소; comfort는 350 lux 부근에서 높음.")
    print("무게·거리는 입력 형식 연습용이며, 가상 정답 생성에는 사용하지 않습니다.")
    X_train, X_test, y_train, y_test = train_test_split(
        frame[FEATURES], frame[TARGETS], test_size=0.25, random_state=42)
    print(f"\n[2/5] 학습 {len(X_train)}행 / 평가 {len(X_test)}행 분리")
    baseline = DummyRegressor(strategy="mean").fit(X_train, y_train)
    model = RandomForestRegressor(n_estimators=120, max_depth=10,
                                  min_samples_leaf=3, random_state=42, n_jobs=1)
    model.fit(X_train, y_train)
    print("\n[3/5] 처음 보는 가상 평가 데이터의 MAE (작을수록 좋음, 정답 범위 0~1)")
    for label, estimator in [("항상 학습 평균값", baseline), ("Random Forest", model)]:
        errors = mean_absolute_error(y_test, estimator.predict(X_test), multioutput="raw_values")
        print(f"  {label}: " + ", ".join(f"{key}={value:.4f}" for key, value in zip(TARGETS, errors)))
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"schema_version": 1, "source": "synthetic_rule_demo", "features": FEATURES,
                 "targets": TARGETS, "model": model}, path)
    restored = load_model(path)
    np.testing.assert_allclose(model.predict(X_test), restored.predict(X_test), rtol=0, atol=0)
    print(f"\n[4/5] 모델 저장 → 디스크에서 다시 로드 → 예측 동일 확인: {path}")
    print("\n[5/5] 재학습 없이 저장 모델로 새 입력 예측 (막대는 확률/정확도가 아닌 예측 점수)")
    for label, lux in [("어두운 환경", 50), ("중간 밝기", 350), ("밝은 환경", 900)]:
        show_prediction(restored, label, lux, 250, 15)
    print("\n이 결과는 우리가 만든 규칙을 배웠다는 뜻이지, 사람의 분위기를 알아냈다는 뜻은 아닙니다.")
    print("실제 데이터는 환경 세션/참가자를 고려해 분리해야 합니다. 음악 추천 학습은 별도 단계입니다.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=["train", "predict"], default="train")
    parser.add_argument("--model", type=Path, default=MODEL, help="직접 만든 신뢰할 수 있는 모델만 사용")
    parser.add_argument("--lux", type=float, default=100)
    parser.add_argument("--weight-g", type=float, default=250)
    parser.add_argument("--distance-cm", type=float, default=15)
    args = parser.parse_args()
    try:
        if args.action == "train":
            train(args.model)
        else:
            print(NOTICE)
            inputs(args.lux, args.weight_g, args.distance_cm)
            if not args.model.exists():
                parser.error("저장 모델이 없습니다. 먼저 python -m onjan.ai_demo 를 실행하세요.")
            show_prediction(load_model(args.model), "새 입력 예측", args.lux, args.weight_g, args.distance_cm)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
