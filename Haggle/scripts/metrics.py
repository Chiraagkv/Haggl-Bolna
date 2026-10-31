#!/usr/bin/env python3
"""Print the pitch numbers from whatever is in the database (DATABASE_URL from .env)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, metrics  # noqa: E402

if __name__ == "__main__":
    db.init_db()
    print(json.dumps(metrics.compute(next(db.get_session())), indent=2))
