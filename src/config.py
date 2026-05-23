import json
from pathlib import Path

def load_config(path: str = "config.json") -> dict:
    config_path = Path(path) 

    if not config_path.exists():
        raise FileNotFoundError(f"Brak pliku config: {config_path}")

    with config_path.open("r", encoding="utf-8") as file:
        return json.load(file)
