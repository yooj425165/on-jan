from pathlib import Path

import pandas as pd


FEATURE_COLUMNS = ["temperature", "humidity", "illuminance", "noise"]
TARGET_COLUMNS = ["calmness", "energy", "comfort"]


def main():
    csv_path = Path(__file__).resolve().parent / "data" / "examples" / "environment.csv"
    environment = pd.read_csv(csv_path)

    print("SYNTHETIC EXAMPLE DATA - not real measurements or participant ratings.")
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


if __name__ == "__main__":
    main()
