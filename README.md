# ONJAN

Environment-aware music recommendation project for ROBOFEST.

## Step 1: Read a CSV

This first exercise loads a small synthetic CSV with Pandas. No model is
trained, and no sensor hardware is required.

Use Python 3.11 on both Mac and Ubuntu. Create a separate virtual environment
on each machine; do not copy or commit `.venv`.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python load_environment.py
```

Run these commands from the repository root. On the development Mac, Python
3.11 is also available at `/opt/homebrew/bin/python3.11`. Ubuntu must have
Python 3.11 and its venv support installed before running these commands.

The script prints the example rows, column types, and missing-value counts.
It resolves the CSV path relative to the script, not the terminal directory.

## Step 2: Separate inputs and targets

Run `python load_environment.py` to also display the two tables used to
describe the environment model's learning task:

- `X`: temperature, humidity, illuminance, and noise (sensor inputs).
- `y`: calmness, energy, and comfort (participant rating targets).

The example produces `X.shape == (3, 4)` and `y.shape == (3, 3)`.
Each row of X corresponds to the same row of y. Selecting these columns
does not train a model or split the data into training and evaluation sets.

Environment and participant IDs stay in the original table for tracking and
future grouped evaluation. They are not included as predictive inputs.
At inference time, the trained model will receive X and predict the three
ratings; it will not receive the actual y values.

## Example data

`data/examples/environment.csv` contains **invented values only**. They do not
demonstrate real relationships between sensor readings and human perception.
Do not use them to report model performance.

For this exercise, one row represents one participant's atmosphere evaluation
of one environment observation. IDs are fictional. This is a learning schema,
not the finalized collection format.

| Column | Meaning |
| --- | --- |
| environment_id | Environment observation identifier |
| participant_id | Anonymous participant identifier |
| temperature | Temperature in degrees Celsius |
| humidity | Relative humidity in percent |
| illuminance | Illuminance in lux |
| noise | Placeholder relative sound amplitude, not decibels |
| calmness | Participant's calmness rating, represented from 0 to 1 |
| energy | Participant's liveliness rating, represented from 0 to 1 |
| comfort | Participant's comfort rating, represented from 0 to 1 |

Before real collection, define the sound measurement procedure, time-window
statistics, timestamps, and participant rating scale. Repeated ratings of the
same environment should share an environment ID.

## Workflow

Changes are pushed to `main` from the Mac. On Ubuntu, pull them and install
dependencies into Ubuntu's own virtual environment:

```bash
git pull origin main
source .venv/bin/activate
python -m pip install -r requirements.txt
python load_environment.py
```

The existing `test/` directory is outside the scope of this work.
