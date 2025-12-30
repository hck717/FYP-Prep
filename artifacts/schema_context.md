# SQLite schema context

Use only these tables/columns. Prefer explicit column names.

## dim_company

- ticker: TEXT PK
- short_name: TEXT
- long_name: TEXT
- sector: TEXT
- industry: TEXT
- country: TEXT
- currency: TEXT
- exchange: TEXT
- source: TEXT
- ingested_at: TEXT

## prices_daily

- ticker: TEXT PK
- date: TEXT PK
- open: REAL
- high: REAL
- low: REAL
- close: REAL
- adj_close: REAL
- volume: REAL
- dividends: REAL
- stock_splits: REAL
- source: TEXT
- ingested_at: TEXT

## fundamentals

- ticker: TEXT PK
- statement_type: TEXT PK
- period_type: TEXT PK
- period_end: TEXT PK
- line_item: TEXT PK
- value: REAL
- source: TEXT
- ingested_at: TEXT

## snapshot_kv

- ticker: TEXT PK
- key: TEXT PK
- value: TEXT
- source: TEXT
- ingested_at: TEXT
