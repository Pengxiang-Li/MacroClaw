import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from macroclaw.logging import get_logger

log = get_logger(__name__, subsystem="predictions")

DB_PATH = Path.home() / ".macroclaw" / "predictions.db"

def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                asset str NOT NULL,
                ticker str NOT NULL,
                signal str NOT NULL,
                price_at_prediction REAL NOT NULL,
                executive_summary TEXT,
                key_events_json TEXT
            )
        """)
        conn.commit()

def save_prediction(asset: str, ticker: str, signal: str, price: float, brief: Any) -> None:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO predictions (timestamp, asset, ticker, signal, price_at_prediction, executive_summary, key_events_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                asset,
                ticker,
                signal,
                price,
                brief.executive_summary,
                json.dumps([{"event": e.event, "market_impact": e.market_impact} for e in brief.key_events])
            )
        )
        conn.commit()
    log.debug(f"Saved prediction for {asset}: {signal} at {price}")

def get_all_predictions() -> list[dict[str, Any]]:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM predictions ORDER BY timestamp DESC")
        return [dict(row) for row in cur.fetchall()]
