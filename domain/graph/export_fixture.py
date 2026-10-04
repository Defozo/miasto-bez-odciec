from pathlib import Path
import json
from .fixture import build_fixture

if __name__ == "__main__":
    target = Path(__file__).resolve().parents[2] / "fixtures" / "smart-city.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build_fixture(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(target)
