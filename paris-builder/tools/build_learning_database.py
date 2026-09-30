"""Rebuild the layered learning database from source evidence."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from paris_builder.learning import build_database

if __name__ == '__main__':
    meta = build_database()
    print(json.dumps(meta, ensure_ascii=False, indent=2))
