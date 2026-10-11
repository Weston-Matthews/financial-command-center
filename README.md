# Finance Command Center

Local cash-flow command center: account balances, bill book, payout calendar, projected running balance, leftover monthly budget, and rule-based advice.

## Requirements

- **Python 3.10 or newer** (3.12 recommended). The code uses modern type syntax (`float | None`) and standard library only besides FastAPI/Uvicorn.
- [Poetry](https://python-poetry.org/) for the project virtualenv (preferred), or plain `venv` + pip.

## Setup with Poetry (recommended)

```bash
cd command-center

# Install Poetry once if you do not have it:
# curl -sSL https://install.python-poetry.org | python3 -

poetry install
```

Poetry creates an isolated virtualenv and installs FastAPI + Uvicorn from `pyproject.toml` / `poetry.lock`.

## Run

```bash
cd command-center
poetry run uvicorn server:app --host 127.0.0.1 --port 8765
```

Open http://127.0.0.1:8765

### Alternative: plain venv

```bash
cd command-center
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn server:app --host 127.0.0.1 --port 8765
```

## Data

SQLite database: `data/app.db`. First launch seeds a demo household so the calendar is populated. Use **Start empty** on the Command tab to replace it with your accounts and bills, or **Reload demo** to restore sample data.
