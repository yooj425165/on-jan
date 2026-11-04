from pathlib import Path

import pandas as pd


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


if __name__ == "__main__":
    main()
