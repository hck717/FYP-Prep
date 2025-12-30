from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

import pandas as pd
import yfinance as yf


# -----------------------------
# Config
# -----------------------------
@dataclass(frozen=True)
class IngestConfig:
    db_path: str
    ticker: str
    start_date: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# -----------------------------
# SQLite schema
# -----------------------------
SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS dim_company (
    ticker TEXT PRIMARY KEY,
    short_name TEXT,
    long_name TEXT,
    sector TEXT,
    industry TEXT,
    country TEXT,
    currency TEXT,
    exchange TEXT,
    source TEXT,
    ingested_at TEXT
);

CREATE TABLE IF NOT EXISTS prices_daily (
    ticker TEXT,
    date TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    adj_close REAL,
    volume REAL,
    dividends REAL,
    stock_splits REAL,
    source TEXT,
    ingested_at TEXT,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS fundamentals (
    ticker TEXT,
    statement_type TEXT,   -- 'is' | 'bs' | 'cf'
    period_type TEXT,      -- 'annual' | 'quarterly'
    period_end TEXT,
    line_item TEXT,
    value REAL,
    source TEXT,
    ingested_at TEXT,
    PRIMARY KEY (ticker, statement_type, period_type, period_end, line_item)
);

CREATE TABLE IF NOT EXISTS snapshot_kv (
    ticker TEXT,
    key TEXT,
    value TEXT,
    source TEXT,
    ingested_at TEXT,
    PRIMARY KEY (ticker, key)
);

CREATE INDEX IF NOT EXISTS idx_prices_ticker_date ON prices_daily (ticker, date);
CREATE INDEX IF NOT EXISTS idx_fund_ticker_period ON fundamentals (ticker, period_type, period_end);
"""


def connect_and_init(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


# -----------------------------
# yfinance helpers
# -----------------------------
def safe_info(t: yf.Ticker) -> Dict[str, Any]:
    try:
        info = t.info or {}
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}


def statement_to_long(
    df: Optional[pd.DataFrame],
    *,
    ticker: str,
    statement_type: str,
    period_type: str,
    ingested_at: str,
    source: str = "yfinance",
) -> pd.DataFrame:
    """
    yfinance statements are commonly: rows=line items, cols=period end dates.
    Convert to long format for SQL friendliness.
    """
    cols = [
        "ticker", "statement_type", "period_type", "period_end",
        "line_item", "value", "source", "ingested_at"
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)

    out = (
        df.copy()
        .rename_axis("line_item")
        .reset_index()
        .melt(id_vars=["line_item"], var_name="period_end", value_name="value")
    )

    out["period_end"] = pd.to_datetime(out["period_end"], errors="coerce").dt.date.astype(str)
    out.insert(0, "ticker", ticker)
    out.insert(1, "statement_type", statement_type)
    out.insert(2, "period_type", period_type)
    out["source"] = source
    out["ingested_at"] = ingested_at
    return out[cols]


def prices_to_df(
    t: yf.Ticker,
    *,
    ticker: str,
    start_date: str,
    ingested_at: str,
    source: str = "yfinance",
) -> pd.DataFrame:
    px = t.history(start=start_date, auto_adjust=False)
    if px is None or px.empty:
        return pd.DataFrame(columns=[
            "ticker", "date", "open", "high", "low", "close", "adj_close",
            "volume", "dividends", "stock_splits", "source", "ingested_at"
        ])

    px = px.reset_index()
    # yfinance may return index 'Date' or 'Datetime' depending on interval
    date_col = "Date" if "Date" in px.columns else px.columns[0]
    px[date_col] = pd.to_datetime(px[date_col]).dt.date.astype(str)

    out = pd.DataFrame({
        "ticker": ticker,
        "date": px[date_col],
        "open": px.get("Open"),
        "high": px.get("High"),
        "low": px.get("Low"),
        "close": px.get("Close"),
        "adj_close": px.get("Adj Close"),
        "volume": px.get("Volume"),
        "dividends": px.get("Dividends", 0.0),
        "stock_splits": px.get("Stock Splits", 0.0),
        "source": source,
        "ingested_at": ingested_at,
    })
    return out


def snapshot_rows(
    info: Dict[str, Any],
    *,
    ticker: str,
    ingested_at: str,
    keys: Iterable[str],
    source: str = "yfinance",
) -> pd.DataFrame:
    rows = []
    for k in keys:
        if k not in info or info.get(k) is None:
            continue
        rows.append({
            "ticker": ticker,
            "key": k,
            "value": json.dumps(info.get(k)),
            "source": source,
            "ingested_at": ingested_at,
        })
    return pd.DataFrame(rows, columns=["ticker", "key", "value", "source", "ingested_at"])


# -----------------------------
# Write helpers
# -----------------------------
def insert_ignore(conn: sqlite3.Connection, df: pd.DataFrame, table: str) -> None:
    """
    SQLite-friendly insert that won't crash on duplicates.
    Uses executemany with INSERT OR IGNORE.
    """
    if df is None or df.empty:
        return

    cols = list(df.columns)
    placeholders = ",".join(["?"] * len(cols))
    col_sql = ",".join(cols)
    sql = f"INSERT OR IGNORE INTO {table} ({col_sql}) VALUES ({placeholders})"

    conn.executemany(sql, df.itertuples(index=False, name=None))


def ingest_one_ticker(cfg: IngestConfig) -> None:
    ingested_at = utc_now_iso()

    t = yf.Ticker(cfg.ticker)
    info = safe_info(t)

    conn = connect_and_init(cfg.db_path)

    # dim_company
    company = pd.DataFrame([{
        "ticker": cfg.ticker,
        "short_name": info.get("shortName"),
        "long_name": info.get("longName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "country": info.get("country"),
        "currency": info.get("currency"),
        "exchange": info.get("exchange"),
        "source": "yfinance",
        "ingested_at": ingested_at,
    }])
    insert_ignore(conn, company, "dim_company")

    # prices
    prices = prices_to_df(t, ticker=cfg.ticker, start_date=cfg.start_date, ingested_at=ingested_at)
    insert_ignore(conn, prices, "prices_daily")

    # fundamentals (annual + quarterly)
    fundamentals = pd.concat([
        statement_to_long(t.financials, ticker=cfg.ticker, statement_type="is", period_type="annual", ingested_at=ingested_at),
        statement_to_long(t.balance_sheet, ticker=cfg.ticker, statement_type="bs", period_type="annual", ingested_at=ingested_at),
        statement_to_long(t.cashflow, ticker=cfg.ticker, statement_type="cf", period_type="annual", ingested_at=ingested_at),
        statement_to_long(t.quarterly_financials, ticker=cfg.ticker, statement_type="is", period_type="quarterly", ingested_at=ingested_at),
        statement_to_long(t.quarterly_balance_sheet, ticker=cfg.ticker, statement_type="bs", period_type="quarterly", ingested_at=ingested_at),
        statement_to_long(t.quarterly_cashflow, ticker=cfg.ticker, statement_type="cf", period_type="quarterly", ingested_at=ingested_at),
    ], ignore_index=True)

    insert_ignore(conn, fundamentals, "fundamentals")

    # snapshot (optional; availability varies)
    snapshot_keys = [
        "marketCap", "enterpriseValue", "sharesOutstanding",
        "trailingPE", "forwardPE", "priceToBook",
        "beta", "dividendYield",
        "trailingEps", "forwardEps",
        "totalRevenue", "grossMargins", "operatingMargins", "profitMargins",
    ]
    snap = snapshot_rows(info, ticker=cfg.ticker, ingested_at=ingested_at, keys=snapshot_keys)
    insert_ignore(conn, snap, "snapshot_kv")

    conn.commit()
    conn.close()


def parse_args() -> IngestConfig:
    p = argparse.ArgumentParser(description="Ingest yfinance data into a local SQLite database.")
    p.add_argument("--db", dest="db_path", default="research.db", help="Path to SQLite db file.")
    p.add_argument("--ticker", default="AAPL", help="Ticker symbol (default: AAPL).")
    p.add_argument("--start", dest="start_date", default="2015-01-01", help="Price history start date (YYYY-MM-DD).")
    args = p.parse_args()
    return IngestConfig(db_path=args.db_path, ticker=args.ticker.upper(), start_date=args.start_date)


if __name__ == "__main__":
    cfg = parse_args()
    ingest_one_ticker(cfg)
    print(f"Done. Wrote {cfg.ticker} to {cfg.db_path}")
