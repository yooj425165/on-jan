from math import isfinite
from pathlib import Path

import pandas as pd


FEATURE_COLUMNS = ["temperature", "humidity", "illuminance", "noise"]
TARGET_COLUMNS = ["calmness", "energy", "comfort"]


def validate_environment(environment):
    required_columns = ["environment_id", "participant_id"] + FEATURE_COLUMNS + TARGET_COLUMNS
    missing_columns = [column for column in required_columns if column not in environment.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")
    if environment.empty:
        raise ValueError("The CSV contains no data rows.")

    for column in required_columns:
        values = environment[column]
        if values.isna().any() or values.astype(str).str.strip().eq("").any():
            raise ValueError(f"Column '{column}' contains missing or blank values.")

    for column in FEATURE_COLUMNS + TARGET_COLUMNS:
        values = environment[column]
        if not pd.api.types.is_numeric_dtype(values) or pd.api.types.is_bool_dtype(values):
            raise ValueError(f"Column '{column}' must contain numbers only.")
        if not values.map(isfinite).all():
            raise ValueError(f"Column '{column}' contains infinite or invalid numbers.")

    for column in TARGET_COLUMNS:
        if not environment[column].between(0, 1).all():
            raise ValueError(f"Column '{column}' must be between 0 and 1.")

    if not environment["humidity"].between(0, 100).all():
        raise ValueError("Column 'humidity' must be between 0 and 100 percent.")
    for column in ["illuminance", "noise"]:
        if (environment[column] < 0).any():
            raise ValueError(f"Column '{column}' must be non-negative.")


def main():
    csv_path = Path(__file__).resolve().parent / "data" / "examples" / "environment.csv"
    environment = pd.read_csv(csv_path)

    print("SYNTHETIC EXAMPLE DATA - not real measurements or participant ratings.")
    validate_environment(environment)
    print("Data format checks passed. This does not verify real-world accuracy.")
    print("\nEnvironment data:")
    print(environment.to_string(index=False))

    print("\nColumn types:")
    print(environment.dtypes)

    print("\nMissing values per column:")
    print(environment.isna().sum())

    # IDs identify observations and participants; they are not sensor features.
    X = environment[FEATURE_COLUMNS]
    y = environment[TARGET_COLUMNS]

    print("\nX: sensor inputs")
    print(X.to_string(index=False))
    print(f"X shape (rows, features): {X.shape}")

    print("\ny: participant rating targets")
    print(y.to_string(index=False))
    print(f"y shape (rows, targets): {y.shape}")

    summary_columns = ["count", "mean", "std", "min", "max"]
    print("\nX summary: statistics across CSV rows, not a 30-second sensor window")
    print(X.describe().T[summary_columns].round(3).to_string())

    print("\ny summary: synthetic participant ratings")
    print(y.describe().T[summary_columns].round(3).to_string())


if __name__ == "__main__":
    main()
