"""XtQuant field name → project standard English column name mappings.

Centralizes all column renaming dictionaries used by the QMT data adapter
to translate XtQuant SDK field names to the project's standard schema.
"""

# xtdata.get_market_data_ex / get_full_tick realtime quote fields
REALTIME_QUOTE_FIELD_MAP: dict[str, str] = {
    "lastPrice": "price",
    "open": "open",
    "high": "high",
    "low": "low",
    "lastClose": "prev_close",
    "volume": "volume",
    "amount": "amount",
    "pctChg": "pct_change",
}

# xtdata daily/minute K-line fields
KLINE_FIELD_MAP: dict[str, str] = {
    "time": "date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "amount": "amount",
}

# xtdata tick data fields
TICK_FIELD_MAP: dict[str, str] = {
    "time": "time",
    "lastPrice": "price",
    "volume": "volume",
    "amount": "amount",
    "askPrice": "ask_prices",
    "bidPrice": "bid_prices",
    "askVol": "ask_volumes",
    "bidVol": "bid_volumes",
}
