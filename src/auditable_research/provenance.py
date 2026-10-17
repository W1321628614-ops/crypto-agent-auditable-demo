"""Portable integrity and append-only provenance primitives, adapted from tested research code."""
from __future__ import annotations
import copy,hashlib,json,math,os
from contextlib import contextmanager
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
from typing import Any
CONTRACT_VERSION = "offline_integrity_v1"
FIXED_INTERVAL_MS = {"15m":900000,"1h":3600000,"4h":14400000,"1d":86400000}
WEEK_ALIGNMENT_MS = 345600000
class MarketDataIntegrityError(RuntimeError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def normalize_cutoff_utc(value: str | datetime) -> tuple[str, int]:
    if isinstance(value, str):
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as error:
            raise MarketDataIntegrityError(
                f"INVALID_OBSERVATION_CUTOFF: {value}"
            ) from error
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise MarketDataIntegrityError("OBSERVATION_CUTOFF_REQUIRED")

    if parsed.tzinfo is None:
        raise MarketDataIntegrityError("OBSERVATION_CUTOFF_TIMEZONE_REQUIRED")
    parsed = parsed.astimezone(timezone.utc)
    cutoff_ms = int(parsed.timestamp() * 1000)
    canonical = datetime.fromtimestamp(
        cutoff_ms / 1000,
        timezone.utc,
    ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return canonical, cutoff_ms


def utc_iso_from_ms(value: int) -> str:
    return datetime.fromtimestamp(
        value / 1000,
        timezone.utc,
    ).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _next_month_start_ms(open_time_ms: int) -> int:
    opened = datetime.fromtimestamp(open_time_ms / 1000, timezone.utc)
    if opened.day != 1 or any((opened.hour, opened.minute, opened.second, opened.microsecond)):
        raise MarketDataIntegrityError("MONTHLY_CANDLE_BOUNDARY_INVALID")
    year = opened.year + (1 if opened.month == 12 else 0)
    month = 1 if opened.month == 12 else opened.month + 1
    return int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp() * 1000)


def expected_close_time_ms(interval: str, open_time_ms: int) -> int:
    if interval == "1M":
        return _next_month_start_ms(open_time_ms) - 1
    duration = FIXED_INTERVAL_MS.get(interval)
    if duration is None:
        raise MarketDataIntegrityError(f"UNSUPPORTED_INTERVAL: {interval}")
    return open_time_ms + duration - 1


def closed_candle_query_end_time_ms(interval: str, cutoff_ms: int) -> int:
    """Largest candle open time that can have closed at or before cutoff."""
    if interval == "1M":
        cutoff = datetime.fromtimestamp(cutoff_ms / 1000, timezone.utc)
        current_month_start = datetime(cutoff.year, cutoff.month, 1, tzinfo=timezone.utc)
        next_year = cutoff.year + (1 if cutoff.month == 12 else 0)
        next_month = 1 if cutoff.month == 12 else cutoff.month + 1
        next_month_start = datetime(next_year, next_month, 1, tzinfo=timezone.utc)
        if cutoff_ms >= int(next_month_start.timestamp() * 1000) - 1:
            return int(current_month_start.timestamp() * 1000)
        previous_end = int(current_month_start.timestamp() * 1000) - 1
        previous = datetime.fromtimestamp(previous_end / 1000, timezone.utc)
        return int(datetime(previous.year, previous.month, 1, tzinfo=timezone.utc).timestamp() * 1000)
    duration = FIXED_INTERVAL_MS.get(interval)
    if duration is None:
        raise MarketDataIntegrityError(f"UNSUPPORTED_INTERVAL: {interval}")
    return cutoff_ms - duration + 1


def _is_open_boundary_aligned(interval: str, open_time_ms: int) -> bool:
    if interval == "1M":
        opened = datetime.fromtimestamp(open_time_ms / 1000, timezone.utc)
        return (
            opened.day == 1
            and opened.hour == 0
            and opened.minute == 0
            and opened.second == 0
            and opened.microsecond == 0
        )
    duration = FIXED_INTERVAL_MS.get(interval)
    if duration is None:
        return False
    anchor = WEEK_ALIGNMENT_MS if interval == "1w" else 0
    return (open_time_ms - anchor) % duration == 0


def _finite_decimal(value: Any, field: str, index: int) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise MarketDataIntegrityError(
            f"NON_NUMERIC_{field.upper()}_AT_INDEX_{index}"
        ) from error
    if not parsed.is_finite():
        raise MarketDataIntegrityError(
            f"NON_FINITE_{field.upper()}_AT_INDEX_{index}"
        )
    return parsed


def validate_and_partition_klines(
    result: dict[str, Any],
    *,
    symbol: str,
    interval: str,
    requested_limit: int,
    observation_cutoff_utc: str | datetime,
    historical: bool,
) -> dict[str, Any]:
    cutoff_utc, cutoff_ms = normalize_cutoff_utc(observation_cutoff_utc)
    if not isinstance(result, dict):
        raise MarketDataIntegrityError("KLINE_RESULT_NOT_OBJECT")
    if str(result.get("symbol", "")).upper() != symbol.upper():
        raise MarketDataIntegrityError("KLINE_SYMBOL_MISMATCH")
    if result.get("interval") != interval:
        raise MarketDataIntegrityError("KLINE_INTERVAL_MISMATCH")

    candles = result.get("candles")
    if not isinstance(candles, list) or not candles:
        raise MarketDataIntegrityError("KLINE_CANDLES_EMPTY")
    if result.get("returned") != len(candles):
        raise MarketDataIntegrityError("KLINE_RETURNED_COUNT_MISMATCH")

    confirmed = []
    unconfirmed = []
    seen_open_times = set()
    prior_open = None
    prior_close = None

    required = {
        "open_time_ms", "close_time_ms", "open", "high", "low", "close", "volume"
    }
    for index, candle in enumerate(candles):
        if not isinstance(candle, dict) or not required.issubset(candle):
            raise MarketDataIntegrityError(f"INCOMPLETE_CANDLE_AT_INDEX_{index}")
        open_time = int(candle["open_time_ms"])
        close_time = int(candle["close_time_ms"])
        if open_time in seen_open_times:
            raise MarketDataIntegrityError(f"DUPLICATE_CANDLE_AT_INDEX_{index}")
        seen_open_times.add(open_time)
        if prior_open is not None and open_time <= prior_open:
            raise MarketDataIntegrityError(f"NON_MONOTONIC_CANDLE_AT_INDEX_{index}")
        if not _is_open_boundary_aligned(interval, open_time):
            raise MarketDataIntegrityError(f"OPEN_TIME_BOUNDARY_INVALID_AT_INDEX_{index}")
        if close_time != expected_close_time_ms(interval, open_time):
            raise MarketDataIntegrityError(f"CLOSE_TIME_BOUNDARY_INVALID_AT_INDEX_{index}")
        if prior_close is not None and open_time != prior_close + 1:
            raise MarketDataIntegrityError(f"CANDLE_GAP_AT_INDEX_{index}")

        open_value = _finite_decimal(candle["open"], "open", index)
        high_value = _finite_decimal(candle["high"], "high", index)
        low_value = _finite_decimal(candle["low"], "low", index)
        close_value = _finite_decimal(candle["close"], "close", index)
        volume_value = _finite_decimal(candle["volume"], "volume", index)
        if high_value < max(open_value, close_value) or low_value > min(open_value, close_value):
            raise MarketDataIntegrityError(f"OHLC_RELATION_INVALID_AT_INDEX_{index}")
        if high_value < low_value:
            raise MarketDataIntegrityError(f"HIGH_BELOW_LOW_AT_INDEX_{index}")
        if volume_value < 0:
            raise MarketDataIntegrityError(f"NEGATIVE_VOLUME_AT_INDEX_{index}")

        normalized = dict(candle)
        normalized["is_closed"] = close_time <= cutoff_ms
        if close_time <= cutoff_ms:
            confirmed.append(normalized)
        elif open_time <= cutoff_ms:
            unconfirmed.append(normalized)
        else:
            raise MarketDataIntegrityError(f"FUTURE_CANDLE_AT_INDEX_{index}")
        prior_open = open_time
        prior_close = close_time

    if historical and unconfirmed:
        raise MarketDataIntegrityError("HISTORICAL_UNCONFIRMED_CANDLE_PRESENT")
    if not confirmed:
        raise MarketDataIntegrityError("NO_CONFIRMED_CANDLES")

    warnings = []
    if len(candles) < requested_limit:
        warnings.append(
            f"RETURNED_FEWER_THAN_REQUESTED:{len(candles)}/{requested_limit}"
        )
    if unconfirmed:
        warnings.append(f"UNCONFIRMED_CANDLES_EXCLUDED:{len(unconfirmed)}")
    quality_status = "complete" if not warnings else "incomplete"

    model_payload = {
        "symbol": symbol,
        "interval": interval,
        "observation_cutoff_utc": cutoff_utc,
        "confirmed_candles": confirmed,
        "unconfirmed_candle_count": len(unconfirmed),
        "data_quality_status": quality_status,
        "data_quality_warnings": warnings,
    }
    return {
        "contract_version": CONTRACT_VERSION,
        "symbol": symbol,
        "interval": interval,
        "observation_cutoff_utc": cutoff_utc,
        "historical": historical,
        "requested_limit": requested_limit,
        "returned_count": len(candles),
        "confirmed_count": len(confirmed),
        "unconfirmed_count": len(unconfirmed),
        "latest_confirmed_close_time_utc": utc_iso_from_ms(
            int(confirmed[-1]["close_time_ms"])
        ),
        "raw_data_start_utc": utc_iso_from_ms(int(candles[0]["open_time_ms"])),
        "raw_data_end_utc": utc_iso_from_ms(int(candles[-1]["close_time_ms"])),
        "data_quality_status": quality_status,
        "data_quality_warnings": warnings,
        "normalized_payload_sha256": canonical_json_sha256(model_payload),
        "model_payload": model_payload,
        "unconfirmed_candles": unconfirmed,
    }
def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    """Exclusive + fsync; incomplete/crashed writes cause fail-closed reload."""
    with Path(path).open("xb") as f:
        f.write(canonical_json_bytes(value))
        f.flush()
        os.fsync(f.fileno())


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
