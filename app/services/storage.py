import json
from pathlib import Path

DATA_DIR = Path(__file__).parents[1].parent / 'data'
DATA_FILE = DATA_DIR / 'items.json'

def save_items(items):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

def load_items():
    if not DATA_FILE.exists():
        return []
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)
