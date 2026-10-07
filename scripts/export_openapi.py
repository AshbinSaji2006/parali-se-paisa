"""Export the FastAPI contract used for generated frontend request types."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.api.main import create_app
app=create_app("sqlite:///:memory:")
try:
    target=ROOT/"frontend/openapi.json"
    target.write_text(json.dumps(app.openapi(),indent=2),encoding="utf-8")
    print(f"Wrote {target}")
finally:
    app.state.engine.dispose()
