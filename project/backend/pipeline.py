from __future__ import annotations

import io
import math
import re
from typing import Any

import numpy as np
import pandas as pd

from skills_config import (
    ANNUAL_TRADING_DAYS,
    ASSET_CLASS_KEYWORDS,
    COLUMN_ALIASES,
    DATA_TYPES,
    FINANCIAL_FEATURE_KEYWORDS,
    INSIGHT_MESSAGES,
    MARKET_REGIME_LABELS,
    MAX_DISTRIBUTION_BINS,
    MAX_FALLBACK_NUMERIC_COLUMNS,
    MAX_CHART_POINTS,
    NUMERIC_SKIP_COLUMNS,
    OUTLIER_IQR_MULTIPLIER,
    PERCENT_COLUMNS,
    PREVIEW_ROW_LIMIT,
    QUALITY_LEVELS,
    SKILL_VERSION,
    THRESHOLDS,
)


def analyze_csv_bytes(content: bytes) -> dict[str, Any]:
    """Read uploaded CSV bytes and return the dashboard analysis schema."""
    df = _read_csv_bytes(content)
    return analyze_dataframe(df)


def analyze_dataframe(raw_df: pd.DataFrame) -> dict[str, Any]:
    return analyze_dataframe_mvp(raw_df)


def _read_csv_bytes(content: bytes) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return pd.read_csv(io.BytesIO(content), encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise ValueError("CSV 인코딩을 읽을 수 없습니다. UTF-8 또는 CP949 CSV를 사용해 주세요.") from last_error
    raise ValueError("CSV 파일을 읽을 수 없습니다.")


def standardize_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, str]], dict[str, str]]:
    alias_lookup: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            alias_lookup[normalize_column_name(alias)] = canonical

    rename_map: dict[Any, str] = {}
    renamed_columns: dict[str, str] = {}
    column_mapping: list[dict[str, str]] = []
    used_canonical: set[str] = set()

    for column in df.columns:
        original_name = str(column)
        normalized = normalize_column_name(original_name)
        canonical = alias_lookup.get(normalized)

        if canonical and canonical not in used_canonical:
            rename_map[column] = canonical
            used_canonical.add(canonical)
            column_mapping.append({"original_column": original_name, "standard_column": canonical})
            if original_name != canonical:
                renamed_columns[original_name] = canonical
        else:
            stripped = original_name.strip()
            if stripped != original_name:
                rename_map[column] = stripped
                renamed_columns[original_name] = stripped
                column_mapping.append({"original_column": original_name, "standard_column": stripped})
            else:
                column_mapping.append({"original_column": original_name, "standard_column": original_name})

    return df.rename(columns=rename_map), column_mapping, renamed_columns


def normalize_column_name(value: str) -> str:
    return re.sub(r"[\s\-/]+", "_", str(value).strip().lower())


def preprocess_dataframe(
    df: pd.DataFrame,
    warnings: list[str],
    metadata: dict[str, Any],
) -> pd.DataFrame:
    duplicate_count = int(df.duplicated().sum())
    metadata["duplicate_row_count"] = duplicate_count
    if duplicate_count:
        df = df.drop_duplicates().copy()
        metadata["preprocessing_actions"].append(f"중복 행 {duplicate_count}개를 제거했습니다.")
        warnings.append(f"중복 행 {duplicate_count}개가 제거되었습니다.")

    if "date" in df.columns:
        original_non_null = int(df["date"].notna().sum())
        converted = pd.to_datetime(df["date"], errors="coerce")
        invalid_count = int(original_non_null - converted.notna().sum())
        invalid_ratio = float(invalid_count / max(original_non_null, 1))
        df["date"] = converted
        metadata["date_conversion"] = {
            "attempted": True,
            "source_non_null": original_non_null,
            "converted_non_null": int(converted.notna().sum()),
            "invalid_count": invalid_count,
            "invalid_ratio": invalid_ratio,
        }
        metadata["preprocessing_actions"].append("date 컬럼을 datetime 형식으로 변환했습니다.")
        if invalid_count > 0:
            warnings.append(f"date 컬럼에서 날짜로 변환되지 않은 값이 {invalid_count}개 있습니다.")
        if invalid_ratio >= 0.30:
            warnings.append("date 컬럼의 변환 실패 비율이 30% 이상입니다. 날짜 기반 분석 신뢰도가 낮습니다.")
            metadata["assumptions"].append("date 변환 실패 비율이 높아 날짜 기반 지표 해석에 주의가 필요합니다.")
    else:
        metadata["date_conversion"] = {"attempted": False}

    converted_numeric_columns: list[str] = []
    percent_columns: list[str] = []
    numeric_conversion: dict[str, dict[str, Any]] = {}
    for column in list(df.columns):
        if str(column) in NUMERIC_SKIP_COLUMNS:
            continue
        source_non_null = int(df[column].notna().sum())
        converted, did_convert, used_percent = convert_numeric_like_series(df[column], str(column))
        if did_convert:
            df[column] = converted
            column_name = str(column)
            converted_numeric_columns.append(column_name)
            numeric_conversion[column_name] = {
                "source_non_null": source_non_null,
                "converted_non_null": int(converted.notna().sum()),
                "percent_to_decimal": bool(used_percent),
            }
        if used_percent:
            percent_columns.append(str(column))

    metadata["converted_numeric_columns"] = converted_numeric_columns
    metadata["percent_columns_converted_to_decimal"] = percent_columns
    metadata["numeric_conversion"] = numeric_conversion
    if converted_numeric_columns:
        metadata["preprocessing_actions"].append(
            "숫자형 문자열 컬럼을 수치형으로 변환했습니다: " + ", ".join(converted_numeric_columns[:8])
        )
    if percent_columns:
        message = "퍼센트 단위 컬럼을 0~1 소수 기준으로 변환했습니다: " + ", ".join(percent_columns[:8])
        metadata["preprocessing_actions"].append(message)
        metadata["assumptions"].append(message)
        warnings.append(message)

    if 0 < len(df) < 2:
        warnings.append("행이 2개 미만이라 추세, 분포, 상관관계 해석이 제한됩니다.")

    missing_counts = df.isna().sum()
    metadata["missing_values"] = {
        str(column): int(count) for column, count in missing_counts.items() if int(count) > 0
    }
    if metadata["missing_values"]:
        parts = [f"{column} {count}개" for column, count in metadata["missing_values"].items()]
        warnings.append("결측치가 감지되었습니다: " + ", ".join(parts[:6]))
        metadata["preprocessing_actions"].append("컬럼별 결측치 비율과 개수를 계산했습니다.")

    outliers = detect_outliers(df)
    metadata["outliers"] = outliers
    if outliers:
        parts = [f"{column} {count}개" for column, count in outliers.items()]
        warnings.append("단순 IQR 기준 이상치가 감지되었습니다: " + ", ".join(parts[:6]))
        metadata["preprocessing_actions"].append("IQR 기준 이상치를 탐지해 metadata.outliers에 기록했습니다.")

    if "date" in df.columns and df["date"].notna().any():
        metadata["date_range"] = {
            "start": df["date"].min().date().isoformat(),
            "end": df["date"].max().date().isoformat(),
        }
        metadata["detected_frequency"] = detect_frequency(df["date"], warnings, metadata)
    else:
        metadata["detected_frequency"] = "unknown"

    metadata["numeric_columns"] = [str(column) for column in df.select_dtypes(include=[np.number]).columns]
    return df


def convert_numeric_like_series(series: pd.Series, column_name: str = "") -> tuple[pd.Series, bool, bool]:
    if pd.api.types.is_numeric_dtype(series):
        normalized, scaled_percent = normalize_percent_series(series, column_name)
        return normalized, scaled_percent, scaled_percent

    non_null = series.dropna()
    if non_null.empty:
        return series, False, False

    as_text = non_null.astype(str).str.strip()
    cleaned = clean_numeric_text(as_text)
    parsed = pd.to_numeric(cleaned, errors="coerce")
    parse_ratio = float(parsed.notna().mean())
    if parse_ratio < 0.8:
        return series, False, False

    full_text = series.astype("string").str.strip()
    percent_mask = full_text.str.contains("%", na=False)
    full_cleaned = clean_numeric_text(full_text)
    numeric = pd.to_numeric(full_cleaned, errors="coerce").astype("float64")
    scaled_percent = False
    if bool(percent_mask.any()):
        numeric.loc[percent_mask] = numeric.loc[percent_mask] / 100
        scaled_percent = True
    numeric, scaled_no_symbol = normalize_percent_series(numeric, column_name, exclude_mask=percent_mask)
    return numeric, True, bool(scaled_percent or scaled_no_symbol)


def normalize_percent_series(
    series: pd.Series,
    column_name: str,
    exclude_mask: pd.Series | None = None,
) -> tuple[pd.Series, bool]:
    if column_name not in PERCENT_COLUMNS:
        return series, False

    numeric = pd.to_numeric(series, errors="coerce").astype("float64")
    valid = numeric.dropna()
    if valid.empty:
        return series, False

    if column_name == "return":
        median_abs = float(valid.abs().median())
        if median_abs > 100:
            return series, False
        mask = numeric.abs() > 1
    elif column_name == "weight":
        total = float(valid.sum())
        if 99 <= total <= 101:
            mask = numeric.notna()
        else:
            mask = numeric.abs() > 1
    else:
        mask = numeric.abs() > 1
    if exclude_mask is not None:
        mask = mask & ~exclude_mask.reindex(numeric.index, fill_value=False)
    if not bool(mask.any()):
        return series, False
    numeric.loc[mask] = numeric.loc[mask] / 100
    return numeric, True


def detect_frequency(
    date_series: pd.Series,
    warnings: list[str],
    metadata: dict[str, Any],
) -> str:
    dates = pd.to_datetime(date_series, errors="coerce").dropna().sort_values().drop_duplicates()
    if len(dates) < 2:
        metadata["assumptions"].append("날짜 관측치가 부족해 데이터 빈도를 unknown으로 설정했습니다.")
        return "unknown"

    median_days = float(dates.diff().dropna().dt.days.median())
    if 0.5 <= median_days <= 1.5:
        return "daily"
    if 5 <= median_days <= 9:
        return "weekly"
    if 28 <= median_days <= 31:
        return "monthly"

    warnings.append("날짜 간격이 일간/주간/월간으로 명확하지 않아 빈도를 unknown으로 처리했습니다.")
    metadata["assumptions"].append("데이터 빈도가 unknown이므로 연환산 지표 해석에 주의가 필요합니다.")
    return "unknown"


def clean_numeric_text(values: pd.Series) -> pd.Series:
    return (
        values.astype("string")
        .str.replace(",", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.replace("₩", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace("원", "", regex=False)
        .str.replace(r"^\((.*)\)$", r"-\1", regex=True)
        .str.strip()
    )


def detect_outliers(df: pd.DataFrame) -> dict[str, int]:
    outliers: dict[str, int] = {}
    numeric_df = df.select_dtypes(include=[np.number])
    for column in numeric_df.columns:
        series = numeric_df[column].replace([np.inf, -np.inf], np.nan).dropna()
        if len(series) < 8:
            continue
        q1 = float(series.quantile(0.25))
        q3 = float(series.quantile(0.75))
        iqr = q3 - q1
        if iqr == 0:
            continue
        lower = q1 - OUTLIER_IQR_MULTIPLIER * iqr
        upper = q3 + OUTLIER_IQR_MULTIPLIER * iqr
        count = int(((series < lower) | (series > upper)).sum())
        if count > 0:
            outliers[str(column)] = count
    return outliers


def numeric_columns(df: pd.DataFrame, exclude: set[str] | None = None) -> list[str]:
    excluded = exclude or set()
    return [
        str(column)
        for column in df.select_dtypes(include=[np.number]).columns
        if str(column) not in excluded
    ]


def apply_missing_value_policy(
    df: pd.DataFrame,
    data_type: str,
    metadata: dict[str, Any],
    warnings: list[str],
) -> pd.DataFrame:
    work = df.copy()
    filled_columns: list[str] = []

    if data_type == DATA_TYPES["TYPE_B"]:
        metadata["preprocessing_actions"].append("Type-B 비중/금액 결측치는 0으로 대체하지 않고 결측 상태로 유지했습니다.")
    elif "date" in work.columns and work["date"].notna().any():
        work = work.sort_values("date")
        if data_type == DATA_TYPES["TYPE_D"] and "return" in work.columns and "close" not in work.columns:
            fill_targets = []
            metadata["preprocessing_actions"].append("Type-D 수익률 결측치는 상관계수 계산 시 관측 가능한 날짜만 사용하도록 유지했습니다.")
        elif data_type in {DATA_TYPES["TYPE_A"], DATA_TYPES["TYPE_D"]}:
            fill_targets = [column for column in numeric_columns(work, exclude={"date"}) if column != "return"]
        else:
            fill_targets = []
        for column in fill_targets:
            if work[column].isna().any():
                work[column] = work[column].ffill().bfill()
                filled_columns.append(column)
        if filled_columns:
            warnings.append("시계열 수치형 결측치는 forward fill 후 backward fill로 보정했습니다: " + ", ".join(filled_columns[:6]))
            metadata["preprocessing_actions"].append("시계열 수치형 결측치를 forward fill 후 backward fill로 보정했습니다: " + ", ".join(filled_columns[:6]))

    metadata["missing_value_policy"] = {
        "data_type": data_type,
        "filled_columns": filled_columns,
    }
    metadata["numeric_columns"] = [str(column) for column in work.select_dtypes(include=[np.number]).columns]
    return work


def column_has_values(df: pd.DataFrame, column: str) -> bool:
    return column in df.columns and df[column].notna().any()


def is_asset_like_column(column: str) -> bool:
    name = str(column).strip()
    lowered = name.lower()
    if lowered in FINANCIAL_FEATURE_KEYWORDS:
        return False
    if re.fullmatch(r"\d{4,8}", name):
        return True
    if re.fullmatch(r"[A-Z0-9._-]{1,10}", name) and any(char.isalpha() for char in name):
        return True
    return False


def has_financial_feature_columns(columns: list[str]) -> bool:
    if len(columns) < 2:
        return False
    lowered_columns = [column.lower() for column in columns]
    return any(
        any(keyword in lowered for keyword in FINANCIAL_FEATURE_KEYWORDS)
        for lowered in lowered_columns
    )


def choose_asset_identifier_column(df: pd.DataFrame) -> str | None:
    for column in ("ticker", "asset_name"):
        if column in df.columns and df[column].notna().any():
            return column
    return None


def wide_time_series_value_columns(df: pd.DataFrame) -> list[str]:
    candidates: list[str] = []
    excluded = {"date", "weight", "value", "volume", "sentiment"}
    for column in numeric_columns(df, exclude=excluded):
        lowered = column.lower()
        values = pd.to_numeric(df[column], errors="coerce").dropna()
        if values.empty:
            continue
        is_return_like = any(token in lowered for token in ("return", "ret", "yield", "수익률"))
        is_asset_name_like = is_asset_like_column(column)
        if is_return_like or is_asset_name_like:
            candidates.append(column)
    return candidates


def detect_secondary_type(df: pd.DataFrame, primary_type: str) -> str | None:
    asset_column = choose_asset_identifier_column(df)
    has_weight_or_value = any(column in df.columns for column in ("weight", "value"))
    if primary_type == DATA_TYPES["TYPE_D"] and asset_column and has_weight_or_value:
        return DATA_TYPES["TYPE_B"]
    if primary_type != DATA_TYPES["TYPE_C"] and any(column in df.columns for column in ("title", "text", "event", "sentiment")):
        return DATA_TYPES["TYPE_C"]
    return None


def detect_data_type(df: pd.DataFrame, metadata: dict[str, Any] | None = None) -> tuple[str, str]:
    has_date = "date" in df.columns and df["date"].notna().any()
    has_close = "close" in df.columns and pd.to_numeric(df["close"], errors="coerce").notna().any()
    has_return = "return" in df.columns and pd.to_numeric(df["return"], errors="coerce").notna().any()
    asset_column = choose_asset_identifier_column(df)
    has_asset_identifier = asset_column is not None
    has_weight = "weight" in df.columns and pd.to_numeric(df["weight"], errors="coerce").notna().any()
    has_value = "value" in df.columns and pd.to_numeric(df["value"], errors="coerce").notna().any()
    has_title = "title" in df.columns and df["title"].notna().any()
    has_text = "text" in df.columns and df["text"].notna().any()
    has_event = "event" in df.columns and df["event"].notna().any()
    has_sentiment = "sentiment" in df.columns and df["sentiment"].notna().any()
    numeric_cols = numeric_columns(df, exclude={"date"})

    asset_count = 0
    if has_asset_identifier:
        asset_count = int(df[asset_column].dropna().astype(str).nunique())

    if has_date and has_asset_identifier and asset_count >= 2 and (has_close or has_return):
        if metadata is not None:
            metadata["data_format"] = "long"
        return DATA_TYPES["TYPE_D"], f"Long-format Type-D: date + {asset_column} + close/return 구조와 2개 이상 자산이 감지되었습니다."

    wide_cols = wide_time_series_value_columns(df)
    if has_date and len(wide_cols) >= 2:
        if metadata is not None:
            metadata["data_format"] = "wide"
            metadata["assumptions"].append("date + 복수 수치형 가격/수익률 후보 컬럼을 Wide-format Type-D로 해석했습니다.")
            metadata["preprocessing_actions"].append("Wide-format 다중 시계열을 분석 단계에서 자산별 패널로 변환했습니다.")
        return DATA_TYPES["TYPE_D"], "Wide-format Type-D: date + 2개 이상 가격/수익률 후보 수치형 컬럼이 감지되었습니다."

    if has_date and has_close and (not has_asset_identifier or asset_count <= 1):
        if metadata is not None:
            metadata["data_format"] = "long"
        return DATA_TYPES["TYPE_A"], "date + close 컬럼과 단일 자산 구조가 감지되었습니다."

    if has_asset_identifier and (has_weight or has_value):
        if metadata is not None:
            metadata["data_format"] = "snapshot"
        return DATA_TYPES["TYPE_B"], f"{asset_column} + weight/value 컬럼이 감지되었습니다."

    if has_title or has_text or has_event or has_sentiment:
        if metadata is not None:
            metadata["data_format"] = "event"
        return DATA_TYPES["TYPE_C"], "title/text/event/sentiment 중 하나 이상이 감지되었습니다."

    if has_date and len(numeric_cols) >= 2:
        if metadata is not None:
            metadata["data_format"] = "unknown"
            metadata["assumptions"].append("date + 복수 수치형 컬럼은 v1.2.0 MVP 범위에서 Unknown 탐색 분석으로 처리합니다.")
        return DATA_TYPES["UNKNOWN"], "date + 2개 이상 수치형 컬럼이 있으나 Type-A/B/D 필수 구조가 없어 Unknown으로 처리합니다."

    if metadata is not None:
        metadata["data_format"] = "unknown"
    return DATA_TYPES["UNKNOWN"], "지원되는 필수 컬럼 조합이 감지되지 않았습니다."


def suggest_candidate_data_type(df: pd.DataFrame, data_type: str) -> dict[str, Any]:
    if data_type != DATA_TYPES["UNKNOWN"]:
        return {
            "suggested_type": data_type,
            "confidence": "high",
            "reason": "현재 규칙으로 데이터 유형이 확정되었습니다.",
        }

    has_date = "date" in df.columns and df["date"].notna().any()
    asset_column = choose_asset_identifier_column(df)
    has_asset = asset_column is not None
    has_title = "title" in df.columns and df["title"].notna().any()
    has_text = "text" in df.columns and df["text"].notna().any()
    has_event = "event" in df.columns and df["event"].notna().any()
    has_sentiment = "sentiment" in df.columns and df["sentiment"].notna().any()
    numeric_cols = numeric_columns(df, exclude={"date"})

    if has_date and has_asset and any(column in df.columns for column in ("close", "return")):
        return {
            "suggested_type": DATA_TYPES["TYPE_D"],
            "confidence": "medium",
            "reason": "date, 자산 식별자, close/return 후보가 있어 Type-D Long-format 후보입니다.",
        }
    if has_date and len(wide_time_series_value_columns(df)) >= 2:
        return {
            "suggested_type": DATA_TYPES["TYPE_D"],
            "confidence": "medium",
            "reason": "date와 복수 가격/수익률 후보 컬럼이 있어 Type-D Wide-format 후보입니다.",
        }
    if has_date and len(numeric_cols) >= 2:
        return {
            "suggested_type": DATA_TYPES["UNKNOWN"],
            "confidence": "low",
            "reason": "date와 2개 이상 수치형 컬럼이 있으나 v1.2.0 MVP에서는 Unknown 탐색 분석 후보입니다.",
        }
    if has_date and len(numeric_cols) == 1:
        return {
            "suggested_type": DATA_TYPES["TYPE_A"],
            "confidence": "medium",
            "reason": "date와 단일 수치형 컬럼이 있어 가격 컬럼명을 close 또는 price로 맞추면 Type-A 분석이 가능합니다.",
        }
    if has_asset:
        return {
            "suggested_type": DATA_TYPES["TYPE_B"],
            "confidence": "medium",
            "reason": f"{asset_column}가 있어 weight 또는 value 컬럼이 추가되면 포트폴리오 분석이 가능합니다.",
        }
    if has_title or has_text or has_event or has_sentiment:
        return {
            "suggested_type": DATA_TYPES["TYPE_C"],
            "confidence": "medium",
            "reason": "텍스트 또는 감성 컬럼이 있어 이벤트/뉴스 데이터 후보입니다.",
        }
    if len(numeric_cols) >= 2:
        return {
            "suggested_type": "NumericSummary",
            "confidence": "low",
            "reason": "복수 수치형 컬럼은 있으나 날짜나 자산 식별자가 없어 탐색적 통계 분석에 적합합니다.",
        }
    return {
        "suggested_type": DATA_TYPES["UNKNOWN"],
        "confidence": "low",
        "reason": "표준 투자 데이터 유형을 추정할 핵심 컬럼이 부족합니다.",
    }


def choose_type_a_price_column(df: pd.DataFrame) -> str | None:
    for column in ("close", "open"):
        if column in df.columns and pd.to_numeric(df[column], errors="coerce").notna().any():
            return column
    return None


def analyze_type_a(df: pd.DataFrame, warnings: list[str]) -> dict[str, Any]:
    price_column = choose_type_a_price_column(df)
    if price_column is None:
        warnings.append("Type-A 분석에 사용할 close/open 가격 컬럼이 없습니다.")
        return {
            "indicators": [indicator("유효 행 수", 0, "integer")],
            "charts": [],
            "insights": ["유효한 시계열 가격 데이터가 부족합니다."],
        }

    work = df[["date", price_column]].copy().rename(columns={price_column: "close"})
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    work = work.dropna(subset=["date", "close"]).sort_values("date")

    if work.empty:
        warnings.append("Type-A 분석에 필요한 유효한 date/close 행이 없습니다.")
        return {
            "indicators": [indicator("유효 행 수", 0, "integer")],
            "charts": [],
            "insights": ["유효한 시계열 가격 데이터가 부족합니다."],
        }

    work["MA5"] = work["close"].rolling(window=5, min_periods=1).mean()
    work["MA20"] = work["close"].rolling(window=20, min_periods=1).mean()
    work["MA60"] = work["close"].rolling(window=60, min_periods=1).mean()
    work["RSI14"] = compute_rsi(work["close"], 14)
    work["MACD"] = work["close"].ewm(span=12, adjust=False).mean() - work["close"].ewm(span=26, adjust=False).mean()
    work["MACD_signal"] = work["MACD"].ewm(span=9, adjust=False).mean()
    work["MACD_histogram"] = work["MACD"] - work["MACD_signal"]
    metrics = compute_return_metrics_from_price(work["close"], ANNUAL_TRADING_DAYS)
    work["daily_return"] = metrics["returns"]
    work["cumulative_return"] = metrics["cumulative_returns"]
    work["drawdown"] = metrics["drawdown"]
    annualized_volatility = metrics["annualized_volatility"]

    latest_close = latest_number(work["close"])
    latest_ma20 = latest_number(work["MA20"])
    latest_ma5 = latest_number(work["MA5"])
    latest_ma60 = latest_number(work["MA60"])
    latest_rsi = latest_number(work["RSI14"])

    insights: list[Any] = []
    if latest_close is not None and latest_ma20 is not None:
        if latest_close > latest_ma20:
            insights.append(insight("단기 추세", "Positive", "최근 종가가 MA20 위에 있어 단기 이동평균선보다 높은 가격 흐름이 관찰됩니다.", f"종가 {latest_close:.4g}, MA20 {latest_ma20:.4g}", "MA20 이탈 여부 확인"))
        elif latest_close < latest_ma20:
            insights.append(insight("단기 추세", "Warning", "최근 종가가 MA20 아래에 있어 단기 이동평균선보다 낮은 가격 흐름이 관찰됩니다.", f"종가 {latest_close:.4g}, MA20 {latest_ma20:.4g}", "가격 회복 여부 확인"))

    if len(work) >= 2 and latest_ma20 is not None and latest_ma60 is not None:
        prev_ma20 = latest_number(work["MA20"].iloc[:-1])
        prev_ma60 = latest_number(work["MA60"].iloc[:-1])
        if prev_ma20 is not None and prev_ma60 is not None:
            if prev_ma20 <= prev_ma60 and latest_ma20 > latest_ma60:
                insights.append(insight("이동평균 교차", "Positive", "중기 골든크로스 가능성이 관찰됩니다.", f"MA20 {latest_ma20:.4g}, MA60 {latest_ma60:.4g}", "교차 이후 거래량 동반 여부 확인"))
            elif prev_ma20 >= prev_ma60 and latest_ma20 < latest_ma60:
                insights.append(insight("이동평균 교차", "Warning", "중기 데드크로스 가능성이 관찰됩니다.", f"MA20 {latest_ma20:.4g}, MA60 {latest_ma60:.4g}", "추세 약화 지속 여부 확인"))

    if latest_rsi is not None:
        if latest_rsi >= THRESHOLDS["rsi_overbought"]:
            insights.append(insight("RSI", "Warning", "RSI 기준 과매수 가능성이 관찰됩니다.", f"RSI14 {latest_rsi:.2f}", "가격과 RSI 둔화 여부 확인"))
        elif latest_rsi <= THRESHOLDS["rsi_oversold"]:
            insights.append(insight("RSI", "Info", "RSI 기준 과매도 가능성이 관찰됩니다.", f"RSI14 {latest_rsi:.2f}", "반등 신호와 거래량 확인"))

    if annualized_volatility is not None and annualized_volatility > THRESHOLDS["high_volatility"]:
        insights.append(insight("변동성", "Warning", "연환산 변동성이 높은 수준으로 관찰됩니다.", f"{annualized_volatility:.2%}", "포지션 크기와 손실 허용 범위 확인"))
    if metrics["mdd"] is not None and metrics["mdd"] <= -0.20:
        insights.append(insight("낙폭", "Risk", "최근 분석 구간에서 큰 낙폭이 발생했습니다.", f"MDD {metrics['mdd']:.2%}", "최대 낙폭 발생 구간 확인"))

    chart_df = sample_chart_rows(work[["date", "close", "MA5", "MA20", "MA60"]])
    chart_data = dataframe_to_records(chart_df)
    charts = [
        chart(
            "line",
            "가격 추이 및 이동평균선",
            chart_data,
            "date",
            ["close", "MA5", "MA20", "MA60"],
            "가격과 5일/20일/60일 이동평균선으로 추세를 비교합니다.",
        ),
        chart(
            "line",
            "누적 수익률",
            dataframe_to_records(sample_chart_rows(work[["date", "cumulative_return"]])),
            "date",
            ["cumulative_return"],
            "분석 기간의 누적 수익률 경로를 확인합니다.",
        ),
        chart(
            "line",
            "Drawdown",
            dataframe_to_records(sample_chart_rows(work[["date", "drawdown"]])),
            "date",
            ["drawdown"],
            "최고점 대비 낙폭으로 하방 위험을 확인합니다.",
        ),
        chart(
            "line",
            "RSI14",
            dataframe_to_records(sample_chart_rows(work[["date", "RSI14"]])),
            "date",
            ["RSI14"],
            "상대강도지수로 과매수와 과매도 구간을 확인합니다.",
        ),
    ]
    if "volume" in df.columns and df["volume"].notna().any():
        volume_work = df[["date", "volume"]].copy().dropna(subset=["date"])
        volume_work["volume"] = pd.to_numeric(volume_work["volume"], errors="coerce")
        volume_work = volume_work.dropna(subset=["volume"]).sort_values("date")
        if not volume_work.empty:
            charts.append(
                chart(
                    "bar",
                    "거래량",
                    dataframe_to_records(sample_chart_rows(volume_work)),
                    "date",
                    ["volume"],
                    "가격 흐름과 함께 거래량 변화를 확인합니다.",
                )
            )

    return {
        "indicators": [
            indicator("최신 종가", latest_close, "number"),
            indicator("누적 수익률", metrics["cumulative_return_last"], "percent"),
            indicator("연환산 수익률", metrics["annualized_return"], "percent"),
            indicator("MA20", latest_ma20, "number"),
            indicator("MA60", latest_ma60, "number"),
            indicator("RSI14", latest_rsi, "number"),
            indicator("연환산 변동성", annualized_volatility, "percent"),
            indicator("MDD", metrics["mdd"], "percent"),
            indicator("승률", metrics["win_rate"], "percent"),
        ],
        "charts": charts,
        "insights": insights,
    }


def analyze_type_b(df: pd.DataFrame, warnings: list[str]) -> dict[str, Any]:
    source_column = "weight" if "weight" in df.columns else "value"
    asset_column = choose_asset_identifier_column(df) or "ticker"
    if asset_column not in df.columns:
        warnings.append("Type-B 분석에 필요한 자산 식별 컬럼이 없습니다.")
        return {
            "indicators": [indicator("자산 수", 0, "integer")],
            "charts": [],
            "insights": [insight("포트폴리오 분석 불가", "Risk", "자산 식별 컬럼이 없어 포트폴리오 구성을 계산할 수 없습니다.", "asset identifier missing", "ticker 또는 asset_name 컬럼 확인")],
        }
    work = df[[asset_column, source_column, *(["sector"] if "sector" in df.columns else [])]].copy()
    work[asset_column] = work[asset_column].astype(str).str.strip()
    work[source_column] = pd.to_numeric(work[source_column], errors="coerce")
    work = work.dropna(subset=[asset_column, source_column])
    work = work[work[asset_column] != ""]

    negative_count = int((work[source_column] < 0).sum())
    if negative_count:
        warnings.append(f"음수 {source_column} 값 {negative_count}개는 포트폴리오 비중 계산에서 제외했습니다.")
        work = work[work[source_column] >= 0]

    allocation = work.groupby(asset_column, as_index=False)[source_column].sum().rename(columns={asset_column: "ticker"})
    total = float(allocation[source_column].sum()) if not allocation.empty else 0.0

    if total <= 0:
        warnings.append("Type-B 분석에 필요한 양수 weight/value 합계가 없습니다.")
        return {
            "indicators": [indicator("자산 수", 0, "integer")],
            "charts": [],
            "insights": ["포트폴리오 비중을 계산할 수 있는 유효 데이터가 부족합니다."],
        }

    allocation["weight"] = allocation[source_column] / total
    allocation = allocation.sort_values("weight", ascending=False)

    top1_weight = float(allocation["weight"].iloc[0]) if not allocation.empty else None
    top3_weight = float(allocation["weight"].head(3).sum()) if not allocation.empty else None
    hhi = float(np.square(allocation["weight"]).sum()) if not allocation.empty else None

    insights: list[Any] = []
    if top1_weight is not None and top1_weight >= THRESHOLDS["top1_weight"]:
        insights.append(insight("단일 자산 집중", "Risk", "단일 자산 쏠림이 관찰됩니다.", f"Top1 {top1_weight:.2%}", "최상위 보유 자산 리스크 확인"))
    if top3_weight is not None and top3_weight >= THRESHOLDS["top3_weight"]:
        insights.append(insight("상위 자산 집중", "Warning", "상위 3개 자산 집중 포트폴리오입니다.", f"Top3 {top3_weight:.2%}", "상위 보유 자산 간 상관관계 확인"))
    if hhi is not None and hhi >= THRESHOLDS["hhi"]:
        insights.append(insight("HHI 집중도", "Warning", "포트폴리오 집중도가 높은 수준입니다.", f"HHI {hhi:.4f}", "분산 효과와 섹터 편중 확인"))
    elif hhi is not None and hhi < THRESHOLDS["low_hhi"]:
        insights.append(insight("분산도", "Positive", "자산이 비교적 고르게 분산되어 있습니다.", f"HHI {hhi:.4f}", "개별 자산 리스크와 섹터 노출 확인"))
    insights.append(insight("위험 기여도", "Info", "수익률 또는 공분산 데이터가 없어 위험 기여도는 계산하지 않았습니다.", "risk_contribution = not_calculated", "자산별 수익률 패널 또는 공분산 행렬 추가"))

    allocation_records = dataframe_to_records(allocation[["ticker", "weight"]])
    sector_chart = None
    sector_weight = None
    if "sector" in work.columns:
        sector_work = work.copy()
        sector_work["weight"] = sector_work[source_column] / total
        sector_weight_df = sector_work.groupby("sector", as_index=False)["weight"].sum().sort_values("weight", ascending=False)
        if not sector_weight_df.empty:
            sector_weight = float(sector_weight_df["weight"].iloc[0])
            sector_chart = chart(
                "bar",
                "섹터별 비중",
                dataframe_to_records(sector_weight_df),
                "sector",
                ["weight"],
                "섹터별 포트폴리오 노출도를 비교합니다.",
            )
            if sector_weight >= 0.50:
                insights.append(insight("섹터 집중", "Warning", "특정 섹터 노출도가 높게 나타납니다.", f"최대 섹터 비중 {sector_weight:.2%}", "섹터별 리스크 요인 확인"))
    allocation_charts: list[dict[str, Any]]
    if len(allocation) <= 10:
        allocation_charts = [
            chart(
                "donut",
                "포트폴리오 비중",
                allocation_records,
                "ticker",
                ["weight"],
                "자산 종류가 10개 이하인 포트폴리오의 자산별 투자 비중을 보여줍니다.",
            )
        ]
    else:
        allocation_charts = [
            chart(
                "bar",
                "자산 비중 순위",
                allocation_records[:20],
                "ticker",
                ["weight"],
                "자산 종류가 많은 포트폴리오를 비중이 높은 순서로 비교합니다.",
            )
        ]
    if sector_chart:
        allocation_charts.append(sector_chart)

    return {
        "indicators": [
            indicator("자산 수", int(len(allocation)), "integer"),
            indicator("Top1 비중", top1_weight, "percent"),
            indicator("Top3 비중", top3_weight, "percent"),
            indicator("HHI", hhi, "number"),
            indicator("최대 섹터 비중", sector_weight, "percent"),
            indicator("risk_contribution", "not_calculated", "text", status="not_calculated", reason="수익률 또는 공분산 데이터가 없습니다."),
        ],
        "charts": allocation_charts,
        "insights": insights,
    }


def analyze_type_c(df: pd.DataFrame, warnings: list[str]) -> dict[str, Any]:
    indicators = [indicator("행 수", int(len(df)), "integer")]
    charts: list[dict[str, Any]] = []
    insights: list[Any] = [
        insight("이벤트 요약", "Info", INSIGHT_MESSAGES["type_c_scope"], f"rows={len(df)}", "이벤트 집중일과 감성 분포 확인")
    ]

    if "date" in df.columns and df["date"].notna().any():
        start = df["date"].min().date().isoformat()
        end = df["date"].max().date().isoformat()
        indicators.append(indicator("기간", f"{start} ~ {end}", "text"))
        event_counts = (
            df.dropna(subset=["date"])
            .assign(date=lambda data: data["date"].dt.strftime("%Y-%m-%d"))
            .groupby("date", as_index=False)
            .size()
            .rename(columns={"size": "count"})
            .sort_values("date")
        )
        if not event_counts.empty:
            max_row = event_counts.sort_values("count", ascending=False).iloc[0]
            indicators.append(indicator("최다 이벤트 날짜", str(max_row["date"]), "text"))
            insights.append(insight("이벤트 집중일", "Info", "특정 시점에 이벤트 발생 빈도가 증가했습니다.", f"{max_row['date']} count={int(max_row['count'])}", "해당 날짜의 뉴스/공시 내용 확인"))
            charts.append(
                chart(
                    "bar",
                    "일자별 이벤트 빈도",
                    dataframe_to_records(event_counts),
                    "date",
                    ["count"],
                    "뉴스/이벤트가 집중된 날짜를 확인합니다.",
                )
            )

    if "sentiment" in df.columns and df["sentiment"].notna().any():
        sentiment_labels = normalize_sentiment(df["sentiment"])
        distribution = (
            sentiment_labels.value_counts(dropna=False)
            .rename_axis("sentiment")
            .reset_index(name="count")
            .sort_values("count", ascending=False)
        )
        charts.append(
            chart(
                "bar",
                "감성 분포",
                dataframe_to_records(distribution),
                "sentiment",
                ["count"],
                "뉴스/이벤트 데이터의 감성 분포를 요약합니다.",
            )
        )
        if not distribution.empty:
            top_share = float(distribution["count"].iloc[0] / distribution["count"].sum())
            indicators.append(indicator("최대 감성 비중", top_share, "percent"))
            if top_share > 0.6:
                insights.append(insight("감성 편중", "Info", "특정 감성 라벨의 비중이 높아 이벤트 흐름이 한쪽으로 치우쳐 있습니다.", f"{distribution['sentiment'].iloc[0]} {top_share:.2%}", "감성 라벨 산출 기준 확인"))
        numeric_sentiment = pd.to_numeric(df["sentiment"], errors="coerce")
        if numeric_sentiment.notna().any():
            avg_sentiment = float(numeric_sentiment.mean())
            indicators.append(indicator("평균 Sentiment", avg_sentiment, "number"))
            if avg_sentiment < -0.2:
                insights.append(insight("부정 감성", "Warning", "부정적 감성 비중이 높게 관찰됩니다.", f"avg_sentiment={avg_sentiment:.3f}", "부정 이벤트의 원문과 출처 확인"))
    else:
        warnings.append("Type-C 데이터에 sentiment 컬럼이 없어 감성 분포는 생략했습니다.")

    return {
        "indicators": indicators,
        "charts": charts,
        "insights": insights,
    }


def analyze_type_d(df: pd.DataFrame, warnings: list[str]) -> dict[str, Any]:
    pivot, source_description, value_kind = build_multi_asset_pivot(df, warnings)

    if pivot.empty:
        warnings.append("Type-D 분석에 필요한 유효한 다중 시계열 행이 없습니다.")
        return {
            "indicators": [indicator("종목 수", 0, "integer")],
            "charts": [],
            "insights": ["유효한 다중 시계열 가격 데이터가 부족합니다."],
        }
    pivot = pivot.sort_index()
    if value_kind == "close":
        pivot = pivot.ffill().bfill()
    tickers = [str(column) for column in pivot.columns]

    if len(tickers) < 2:
        warnings.append("복수 ticker가 부족하여 Type-D 비교 분석 범위가 제한됩니다.")

    if value_kind == "return":
        returns = pivot.replace([np.inf, -np.inf], np.nan)
        cumulative = (1 + returns.fillna(0)).cumprod() - 1
        synthetic_nav = 1 + cumulative
        drawdowns = synthetic_nav / synthetic_nav.cummax() - 1
    else:
        returns = pivot.pct_change().replace([np.inf, -np.inf], np.nan)
        cumulative = (1 + returns.fillna(0)).cumprod() - 1
        drawdowns = pivot / pivot.cummax() - 1
    latest_returns = cumulative.apply(latest_number).dropna().sort_values(ascending=False)
    volatility = (returns.std() * math.sqrt(ANNUAL_TRADING_DAYS)).dropna().sort_values(ascending=False)
    mdd = drawdowns.min().dropna().sort_values()
    low_observation_pairs = correlation_observation_warnings(returns, warnings)
    corr = returns.corr(min_periods=20)
    avg_corr = average_off_diagonal(corr)

    best_text = None
    worst_text = None
    if not latest_returns.empty:
        best_text = f"{latest_returns.index[0]} ({latest_returns.iloc[0]:.2%})"
        worst_text = f"{latest_returns.index[-1]} ({latest_returns.iloc[-1]:.2%})"

    insights: list[Any] = []
    if low_observation_pairs:
        insights.append(insight("상관계수 관측치", "Warning", "일부 자산 쌍은 공통 관측치가 부족해 상관계수 해석에 주의가 필요합니다.", f"{len(low_observation_pairs)} pairs < 20 observations", "관측 기간을 늘리거나 결측 원인을 확인"))
    if avg_corr is not None and avg_corr > THRESHOLDS["avg_correlation"]:
        insights.append(INSIGHT_MESSAGES["high_correlation"])
    insights.extend(correlation_pair_insights(corr))
    if not volatility.empty and float(volatility.iloc[0]) > THRESHOLDS["high_volatility"]:
        insights.append(insight("변동성", "Warning", "높은 변동성을 보이는 자산이 있습니다.", f"{volatility.index[0]} {volatility.iloc[0]:.2%}", "고변동 자산의 포트폴리오 비중 확인"))
    if best_text:
        insights.append(insight("상대 성과", "Positive", "분석 기간 동안 가장 높은 누적 수익률을 기록한 자산이 확인됩니다.", best_text, "성과 원인과 지속성 확인"))
    if not mdd.empty:
        insights.append(insight("최대 낙폭", "Risk" if float(mdd.iloc[0]) <= -0.20 else "Info", "특정 자산에서 가장 큰 낙폭이 관찰됩니다.", f"{mdd.index[0]} {mdd.iloc[0]:.2%}", "낙폭 발생 기간 확인"))

    cumulative_chart_df = sample_chart_rows(cumulative.reset_index().rename(columns={"date": "date"}))
    performance_data = [
        {"ticker": str(ticker), "cumulative_return": float(value)}
        for ticker, value in latest_returns.items()
    ]
    volatility_data = [
        {"ticker": str(ticker), "volatility": float(value)}
        for ticker, value in volatility.items()
    ]
    mdd_data = [
        {"ticker": str(ticker), "mdd": float(value)}
        for ticker, value in mdd.items()
    ]

    return {
        "indicators": [
            indicator("종목 수", int(len(tickers)), "integer"),
            indicator("데이터 구조", source_description, "text"),
            indicator("최고 수익 종목", best_text, "text"),
            indicator("최저 수익 종목", worst_text, "text"),
            indicator("평균 상관계수", avg_corr, "number"),
            indicator("평균 변동성", float(volatility.mean()) if not volatility.empty else None, "percent"),
            indicator("최대 MDD 자산", str(mdd.index[0]) if not mdd.empty else None, "text"),
            indicator("최대 MDD", float(mdd.iloc[0]) if not mdd.empty else None, "percent"),
        ],
        "charts": [
            chart(
                "line",
                "종목별 누적 수익률",
                dataframe_to_records(cumulative_chart_df),
                "date",
                tickers,
                "각 종목의 기준일 대비 상대 성과를 비교합니다.",
            ),
            chart(
                "bar",
                "상대 성과 순위",
                performance_data,
                "ticker",
                ["cumulative_return"],
                "누적 수익률 기준 상대 성과 순위입니다.",
            ),
            chart(
                "heatmap",
                "수익률 상관관계",
                correlation_to_records(corr, index_key="ticker"),
                "ticker",
                tickers,
                "종목 간 일간 수익률 상관관계를 보여줍니다.",
            ),
            chart(
                "bar",
                "종목별 변동성",
                volatility_data,
                "ticker",
                ["volatility"],
                "종목별 연환산 변동성을 비교합니다.",
            ),
            chart(
                "bar",
                "종목별 MDD",
                mdd_data,
                "ticker",
                ["mdd"],
                "자산별 최고점 대비 최대 낙폭을 비교합니다.",
            ),
        ],
        "insights": insights,
    }


def build_multi_asset_pivot(df: pd.DataFrame, warnings: list[str]) -> tuple[pd.DataFrame, str, str]:
    if "date" not in df.columns or not df["date"].notna().any():
        return pd.DataFrame(), "date 컬럼 없음", "close"

    asset_column = choose_asset_identifier_column(df)
    if asset_column and df[asset_column].notna().any():
        value_column = choose_time_series_value_column(df)
        if value_column is None:
            warnings.append("date + ticker 구조는 감지됐지만 사용할 수 있는 수치형 값 컬럼이 없습니다.")
            return pd.DataFrame(), "long format", "close"
        work = df[["date", asset_column, value_column]].copy()
        work[asset_column] = work[asset_column].astype(str).str.strip()
        work[value_column] = pd.to_numeric(work[value_column], errors="coerce")
        work = work.dropna(subset=["date", asset_column, value_column])
        work = work[work[asset_column] != ""]
        if work.empty:
            return pd.DataFrame(), f"long format: {value_column}", value_column
        pivot = (
            work.groupby(["date", asset_column])[value_column]
            .last()
            .unstack(asset_column)
            .dropna(axis=1, how="all")
        )
        return pivot, f"long format: {value_column}", "return" if value_column == "return" else "close"

    selected_cols = wide_time_series_value_columns(df)
    if len(selected_cols) < 2:
        return pd.DataFrame(), "wide format", "close"
    work = df[["date", *selected_cols]].copy()
    work = work.dropna(subset=["date"])
    if work.empty:
        return pd.DataFrame(), "wide format", "close"
    pivot = work.groupby("date")[selected_cols].last().dropna(axis=1, how="all")
    value_kind = "return" if all("return" in column.lower() or "ret" in column.lower() or "yield" in column.lower() or "수익률" in column for column in selected_cols) else "close"
    return pivot, f"wide format: {value_kind}", value_kind


def choose_time_series_value_column(df: pd.DataFrame) -> str | None:
    numeric_cols = numeric_columns(df, exclude={"date"})
    for preferred in ("close", "return"):
        if preferred in numeric_cols:
            return preferred
    non_weight_cols = [column for column in numeric_cols if column not in {"weight", "value"}]
    if non_weight_cols:
        return non_weight_cols[0]
    return numeric_cols[0] if numeric_cols else None


def analyze_unknown(df: pd.DataFrame, metadata: dict[str, Any]) -> dict[str, Any]:
    numeric_cols = numeric_columns(df, exclude={"date"})[:MAX_FALLBACK_NUMERIC_COLUMNS]
    all_numeric_cols = set(numeric_columns(df, exclude=set()))
    candidate = metadata.get("candidate_data_type", {})
    metadata["unknown_profile"] = {
        "numeric_columns_used": numeric_cols,
        "non_numeric_columns": [
            str(column)
            for column in df.columns
            if str(column) not in all_numeric_cols
        ],
        "candidate": candidate,
    }
    charts = [
        chart(
            "table",
            "컬럼 구조 요약",
            column_summary_rows(df),
            "column",
            ["dtype", "non_null", "missing", "unique"],
            "미분류 데이터의 컬럼 구조를 확인합니다.",
        )
    ]
    charts.append(
        chart(
            "table",
            "결측치 비율 요약",
            missing_ratio_rows(df, metadata),
            "column",
            ["missing", "missing_ratio"],
            "컬럼별 결측치 개수와 비율을 요약합니다.",
        )
    )

    numeric_summary = numeric_summary_rows(df, numeric_cols)
    if numeric_summary:
        charts.append(
            chart(
                "table",
                "수치형 기본 통계",
                numeric_summary,
                "column",
                ["mean", "std", "min", "p25", "median", "p75", "max"],
                "수치형 컬럼의 기본 분포 특성을 요약합니다.",
            )
        )
        corr_chart = build_correlation_chart(
            df,
            numeric_cols,
            "수치형 상관관계",
            "미분류 데이터의 수치형 컬럼 간 상관관계를 탐색합니다.",
        )
        if corr_chart:
            charts.append(corr_chart)
        else:
            charts.append(empty_correlation_chart())
    else:
        charts.append(empty_correlation_chart())
        charts.append(categorical_cardinality_chart(df))

    missing_rows = missing_value_rows(df)
    if missing_rows:
        charts.append(
            chart(
                "bar",
                "컬럼별 결측치",
                missing_rows,
                "column",
                ["missing"],
                "결측치가 많은 컬럼을 확인합니다.",
            )
        )

    insights: list[Any] = [
        insight(
            "탐색적 분석",
            "Info",
            INSIGHT_MESSAGES["unknown"],
            f"numeric_columns={len(numeric_cols)}, missing_cells={sum(metadata.get('missing_values', {}).values())}",
            "컬럼 구조 요약과 후보 타입을 확인",
        ),
        insight(
            "후보 타입",
            "Neutral",
            f"후보 데이터 유형은 {candidate.get('suggested_type', 'Unknown')}입니다.",
            candidate.get("reason", "추가 정보가 필요합니다."),
            "표준 컬럼명을 보강해 재분석",
        ),
    ]
    insights.extend(build_data_quality_insights(metadata))
    if not numeric_cols:
        insights.append(INSIGHT_MESSAGES["numeric_coverage"])
    insights.append(INSIGHT_MESSAGES["unknown_next_steps"])

    return {
        "indicators": [
            indicator("행 수", int(len(df)), "integer"),
            indicator("컬럼 수", int(len(df.columns)), "integer"),
            indicator("숫자 컬럼 수", int(len(numeric_cols)), "integer"),
            indicator("결측 셀 수", int(sum(metadata.get("missing_values", {}).values())), "integer"),
            indicator("후보 유형", candidate.get("suggested_type", "Unknown"), "text"),
        ],
        "charts": charts,
        "insights": insights,
    }


def column_summary_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for column in df.columns:
        rows.append(
            {
                "column": str(column),
                "dtype": str(df[column].dtype),
                "non_null": int(df[column].notna().sum()),
                "missing": int(df[column].isna().sum()),
                "unique": int(df[column].nunique(dropna=True)),
            }
        )
    return rows


def numeric_summary_rows(df: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for column in columns:
        series = pd.to_numeric(df[column], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if series.empty:
            continue
        rows.append(
            {
                "column": column,
                "mean": float(series.mean()),
                "std": float(series.std()) if len(series) > 1 else 0.0,
                "min": float(series.min()),
                "p25": float(series.quantile(0.25)),
                "median": float(series.median()),
                "p75": float(series.quantile(0.75)),
                "max": float(series.max()),
            }
        )
    return rows


def numeric_distribution_charts(df: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    charts: list[dict[str, Any]] = []
    for column in columns:
        data = numeric_distribution_records(df[column])
        if not data:
            continue
        charts.append(
            chart(
                "histogram",
                f"{column} 히스토그램",
                data,
                "range",
                ["count"],
                f"{column} 값의 구간별 분포를 보여줍니다.",
            )
        )
    return charts


def numeric_distribution_records(series: pd.Series) -> list[dict[str, Any]]:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return []
    if values.nunique(dropna=True) <= MAX_DISTRIBUTION_BINS:
        counts = values.value_counts().sort_index()
        return [{"range": format_number(value), "count": int(count)} for value, count in counts.items()]

    bins = min(MAX_DISTRIBUTION_BINS, max(2, int(values.nunique(dropna=True))))
    bucketed = pd.cut(values, bins=bins, duplicates="drop")
    counts = bucketed.value_counts().sort_index()
    return [
        {"range": format_interval(interval), "count": int(count)}
        for interval, count in counts.items()
    ]


def missing_value_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = [
        {"column": str(column), "missing": int(count)}
        for column, count in df.isna().sum().items()
        if int(count) > 0
    ]
    return sorted(rows, key=lambda row: row["missing"], reverse=True)


def missing_ratio_rows(df: pd.DataFrame, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    original_missing = metadata.get("missing_values", {})
    row_count = max(int(metadata.get("row_count", len(df))), 1)
    rows = []
    for column in df.columns:
        missing = int(original_missing.get(str(column), 0))
        rows.append(
            {
                "column": str(column),
                "missing": missing,
                "missing_ratio": float(missing / row_count),
            }
        )
    return sorted(rows, key=lambda row: row["missing"], reverse=True)


def categorical_cardinality_chart(df: pd.DataFrame) -> dict[str, Any]:
    rows = [
        {
            "column": str(column),
            "unique": int(df[column].nunique(dropna=True)),
        }
        for column in df.columns
    ]
    rows = sorted(rows, key=lambda row: row["unique"], reverse=True)[:20]
    return chart(
        "bar",
        "컬럼별 고유값 수",
        rows,
        "column",
        ["unique"],
        "수치형 분포가 어려운 경우 컬럼별 고유값 수를 대체 지표로 제공합니다.",
    )


def build_correlation_chart(
    df: pd.DataFrame,
    columns: list[str],
    title: str,
    reason: str,
) -> dict[str, Any] | None:
    if len(columns) < 2:
        return None
    corr = df[columns].corr()
    if corr.empty:
        return None
    return chart(
        "heatmap",
        title,
        correlation_to_records(corr, index_key="feature"),
        "feature",
        [str(column) for column in corr.columns],
        reason,
    )


def empty_correlation_chart() -> dict[str, Any]:
    return chart(
        "heatmap",
        "수치형 상관관계",
        [],
        "feature",
        [],
        "상관관계를 계산할 수 있는 수치형 컬럼이 2개 미만입니다.",
    )


def build_data_quality_insights(metadata: dict[str, Any]) -> list[Any]:
    insights: list[Any] = []
    if metadata.get("missing_values"):
        insights.append(insight("결측치", "Warning", INSIGHT_MESSAGES["missing_values"], f"{sum(metadata['missing_values'].values())} cells", "결측 컬럼과 보정 방식 확인"))
    if metadata.get("outliers"):
        insights.append(insight("이상치", "Warning", INSIGHT_MESSAGES["outliers"], f"{sum(metadata['outliers'].values())} rows", "이상치 발생 컬럼 확인"))
    return insights


def format_interval(interval: pd.Interval) -> str:
    return f"{format_number(interval.left)} - {format_number(interval.right)}"


def format_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number) >= 100:
        return f"{number:.0f}"
    if abs(number) >= 1:
        return f"{number:.2f}"
    return f"{number:.4f}"


def compute_rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=window, min_periods=window).mean()
    avg_loss = loss.rolling(window=window, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain == 0), 50)
    return rsi


def cumulative_return_series(series: pd.Series) -> pd.Series:
    non_null = series.dropna()
    if non_null.empty:
        return series * np.nan
    return series / float(non_null.iloc[0]) - 1


def compute_return_metrics_from_price(
    price: pd.Series,
    annualization_factor: int,
) -> dict[str, Any]:
    cleaned_price = pd.to_numeric(price, errors="coerce").where(lambda values: values > 0)
    returns = cleaned_price.pct_change().replace([np.inf, -np.inf], np.nan)
    valid_return = returns.dropna()
    cumulative_returns = (1 + returns.fillna(0)).cumprod() - 1
    running_max = cleaned_price.cummax()
    drawdown = cleaned_price / running_max - 1
    return finalize_return_metrics(returns, cumulative_returns, drawdown, annualization_factor)


def compute_return_metrics_from_returns(
    returns: pd.Series,
    annualization_factor: int,
) -> dict[str, Any]:
    clean_returns = pd.to_numeric(returns, errors="coerce").replace([np.inf, -np.inf], np.nan)
    cumulative_nav = (1 + clean_returns.fillna(0)).cumprod()
    cumulative_returns = cumulative_nav - 1
    drawdown = cumulative_nav / cumulative_nav.cummax() - 1
    return finalize_return_metrics(clean_returns, cumulative_returns, drawdown, annualization_factor)


def finalize_return_metrics(
    returns: pd.Series,
    cumulative_returns: pd.Series,
    drawdown: pd.Series,
    annualization_factor: int,
) -> dict[str, Any]:
    valid_return = returns.dropna()
    period_count = int(len(valid_return))
    cumulative_return_last = latest_number(cumulative_returns)
    annualized_return = None
    annualized_volatility = None
    sharpe_ratio = None
    win_rate = None
    if period_count > 0 and cumulative_return_last is not None:
        annualized_return = float((1 + cumulative_return_last) ** (annualization_factor / period_count) - 1)
        win_rate = float((valid_return > 0).mean())
    if period_count >= 2:
        annualized_volatility = float(valid_return.std() * math.sqrt(annualization_factor))
    if annualized_return is not None and annualized_volatility not in (None, 0):
        sharpe_ratio = float(annualized_return / annualized_volatility)

    return {
        "returns": returns,
        "cumulative_returns": cumulative_returns,
        "drawdown": drawdown,
        "period_count": period_count,
        "cumulative_return_last": cumulative_return_last,
        "annualized_return": annualized_return,
        "annualized_volatility": annualized_volatility,
        "mdd": latest_number(drawdown.expanding().min()),
        "sharpe_ratio": sharpe_ratio,
        "win_rate": win_rate,
    }


def normalize_sentiment(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().mean() >= 0.8:
        labels = pd.Series("neutral", index=series.index, dtype="object")
        labels[numeric > 0.05] = "positive"
        labels[numeric < -0.05] = "negative"
        labels[numeric.isna()] = "unknown"
        return labels

    normalized = series.astype("string").str.strip().str.lower()
    mapped = pd.Series("neutral", index=series.index, dtype="object")
    mapped[normalized.str.contains("pos|positive|bull|good|긍정|호재", na=False)] = "positive"
    mapped[normalized.str.contains("neg|negative|bear|bad|부정|악재", na=False)] = "negative"
    mapped[normalized.isna() | (normalized == "")] = "unknown"
    other_mask = ~(mapped.isin(["positive", "negative", "neutral", "unknown"]))
    mapped[other_mask] = normalized[other_mask]
    return mapped


def latest_number(series: pd.Series) -> float | None:
    valid = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if valid.empty:
        return None
    return float(valid.iloc[-1])


def average_off_diagonal(corr: pd.DataFrame) -> float | None:
    if corr.empty or len(corr.columns) < 2:
        return None
    mask = ~np.eye(len(corr), dtype=bool)
    values = corr.where(mask).stack().dropna()
    if values.empty:
        return None
    return float(values.mean())


def correlation_pair_insights(corr: pd.DataFrame) -> list[str]:
    if corr.empty or len(corr.columns) < 2:
        return []

    high_pair: tuple[str, str, float] | None = None
    negative_pair: tuple[str, str, float] | None = None
    columns = [str(column) for column in corr.columns]
    for i, left in enumerate(columns):
        for right in columns[i + 1:]:
            value = corr.loc[left, right]
            if pd.isna(value):
                continue
            corr_value = float(value)
            if corr_value > THRESHOLDS["avg_correlation"] and (
                high_pair is None or corr_value > high_pair[2]
            ):
                high_pair = (left, right, corr_value)
            if corr_value < THRESHOLDS["negative_correlation"] and (
                negative_pair is None or corr_value < negative_pair[2]
            ):
                negative_pair = (left, right, corr_value)

    insights: list[str] = []
    if high_pair:
        insights.append(f"{high_pair[0]}과 {high_pair[1]}는 동조화 현상이 강해 동시에 보유 시 분산 효과가 떨어집니다.")
    if negative_pair:
        insights.append(f"{negative_pair[0]}과 {negative_pair[1]}는 음의 상관관계를 보여 상호 헤징(Hedging) 수단으로 적합합니다.")
    return insights


def correlation_observation_warnings(returns: pd.DataFrame, warnings: list[str]) -> list[tuple[str, str, int]]:
    pairs: list[tuple[str, str, int]] = []
    columns = [str(column) for column in returns.columns]
    for i, left in enumerate(columns):
        for right in columns[i + 1:]:
            count = int(returns[[left, right]].dropna().shape[0])
            if count < 20:
                pairs.append((left, right, count))
    if pairs:
        warnings.append(f"Type-D 상관계수 계산에서 공통 관측치 20개 미만인 자산 쌍이 {len(pairs)}개 있습니다.")
    return pairs


def build_quality_report(
    df: pd.DataFrame,
    warnings: list[str],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    warning_messages = list(dict.fromkeys(warnings))
    if metadata and metadata.get("missing_values"):
        missing_cell_count = int(sum(metadata["missing_values"].values()))
    else:
        missing_cell_count = int(df.isna().sum().sum())
    missing_ratio = float(missing_cell_count / max(df.size, 1))
    if metadata and metadata.get("outliers"):
        outlier_count = int(sum(metadata["outliers"].values()))
    else:
        outlier_count = int(sum(detect_outliers(df).values()))
    risk_signals = [
        df.empty,
        missing_ratio > 0.30,
        len(warning_messages) >= 5,
    ]

    if any(risk_signals):
        level = QUALITY_LEVELS["RISK"]
    elif warning_messages:
        level = QUALITY_LEVELS["WARNING"]
    else:
        level = QUALITY_LEVELS["GOOD"]

    return {
        "row_count": int(metadata.get("row_count", len(df))) if metadata else int(len(df)),
        "column_count": int(metadata.get("column_count", len(df.columns))) if metadata else int(len(df.columns)),
        "status": level,
        "quality_level": level,
        "missing_rate": missing_ratio,
        "warning_messages": warning_messages,
        "missing_cell_count": missing_cell_count,
        "missing_ratio": missing_ratio,
        "outliers_count": outlier_count,
        "outlier_count": outlier_count,
    }


def ensure_insights(insights: list[Any]) -> list[dict[str, Any]]:
    cleaned = [normalize_insight(item) for item in insights if item]
    return cleaned or [insight("요약", "Neutral", INSIGHT_MESSAGES["no_signal"], "-", "추가 데이터 확인")]


def normalize_insight(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return {
            "title": item.get("title", "인사이트"),
            "level": item.get("level", "Info"),
            "message": item.get("message", ""),
            "evidence": item.get("evidence", "-"),
            "check_point": item.get("check_point", "원본 데이터와 전처리 기록 확인"),
        }
    return insight("데이터 해석", "Info", str(item), "-", "관련 지표와 차트를 함께 확인")


def insight(
    title: str,
    level: str,
    message: str,
    evidence: Any,
    check_point: str,
) -> dict[str, Any]:
    return {
        "title": title,
        "level": level,
        "message": message,
        "evidence": str(evidence) if evidence is not None else "-",
        "check_point": check_point,
    }


def indicator(
    name: str,
    value: Any,
    value_format: str = "number",
    description: str | None = None,
    status: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    calculation_status = status or ("not_calculated" if value is None else "calculated")
    return {
        "name": name,
        "value": value,
        "format": value_format,
        "unit": "%" if value_format == "percent" else "",
        "description": description or name,
        "calculation_status": calculation_status,
        "reason": reason,
    }


def indicators_to_schema(indicators: list[dict[str, Any]]) -> dict[str, Any]:
    return {str(item.get("name", index)): item.get("value") for index, item in enumerate(indicators)}


def chart(
    chart_type: str,
    title: str,
    data: list[dict[str, Any]],
    x_key: str,
    y_keys: list[str],
    reason: str,
) -> dict[str, Any]:
    chart_id = normalize_column_name(title) or chart_type
    return {
        "chart_id": chart_id,
        "type": chart_type,
        "chart_type": chart_type,
        "title": title,
        "data": data,
        "x": x_key,
        "x_column": x_key,
        "x_key": x_key,
        "y": y_keys,
        "y_columns": y_keys,
        "y_keys": y_keys,
        "reason": reason,
    }


def build_layout(charts: list[dict[str, Any]], data_type: str) -> dict[str, list[str]]:
    chart_ids = [chart_item.get("chart_id", "") for chart_item in charts]
    top = chart_ids[:1]
    middle = chart_ids[1:5]
    bottom = chart_ids[5:]
    return {
        "top": top,
        "middle": middle,
        "bottom": bottom,
        "side": ["insights", "metadata", "data_quality"] if data_type != DATA_TYPES["UNKNOWN"] else ["candidate_type", "metadata", "data_quality"],
    }


def sample_chart_rows(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) <= MAX_CHART_POINTS:
        return df
    positions = np.linspace(0, len(df) - 1, MAX_CHART_POINTS).round().astype(int)
    return df.iloc[positions]


def correlation_to_records(corr: pd.DataFrame, index_key: str = "ticker") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row_key in corr.index:
        row = {index_key: str(row_key)}
        for column in corr.columns:
            value = corr.loc[row_key, column]
            row[str(column)] = None if pd.isna(value) else float(value)
        rows.append(row)
    return rows


def dataframe_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    output = df.copy()
    for column in output.columns:
        if pd.api.types.is_datetime64_any_dtype(output[column]):
            output[column] = output[column].dt.strftime("%Y-%m-%d")
    output = output.replace([np.inf, -np.inf], np.nan)
    output = output.where(pd.notna(output), None)
    return make_json_safe(output.to_dict(orient="records"))


def make_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): make_json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [make_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [make_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.isoformat()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, np.bool_):
        return bool(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


# ---------------------------------------------------------------------------
# Stable MVP path
# ---------------------------------------------------------------------------


def analyze_dataframe_mvp(raw_df: pd.DataFrame) -> dict[str, Any]:
    warnings: list[str] = []
    metadata = mvp_base_metadata(raw_df, warnings)
    df, column_mapping, renamed_columns = standardize_columns(raw_df.copy())
    metadata["column_mapping"] = column_mapping
    metadata["standardized_columns"] = renamed_columns
    metadata["mapped_columns"] = renamed_columns
    metadata["columns"] = [str(column) for column in df.columns]
    metadata["preprocessing_actions"].append("컬럼명을 Skills.md alias mapping 기준으로 표준화했습니다.")

    if df.empty:
        warnings.append("업로드된 CSV에 분석 가능한 행이 없습니다.")

    df = mvp_preprocess(df, metadata, warnings)
    data_type, detection_reason = mvp_detect_data_type(df)
    metadata["primary_type"] = data_type
    metadata["secondary_type"] = None
    metadata["detection_reason"] = detection_reason
    metadata["asset_class"] = mvp_detect_asset_class(df, data_type)
    metadata["candidate_data_type"] = mvp_suggest_candidate_type(df, data_type)

    if data_type == DATA_TYPES["TYPE_A"]:
        analysis = mvp_analyze_type_a(df, metadata, warnings)
    elif data_type == DATA_TYPES["TYPE_B"]:
        analysis = mvp_analyze_type_b(df, metadata, warnings)
    elif data_type == DATA_TYPES["TYPE_D"]:
        analysis = mvp_analyze_type_d_partial(df, metadata, warnings)
    elif data_type == DATA_TYPES["TYPE_C"]:
        analysis = mvp_analyze_planned(df, data_type, metadata, warnings)
    else:
        analysis = mvp_analyze_unknown(df, metadata, warnings)

    metadata.setdefault("market_regime", {"label": MARKET_REGIME_LABELS["UNKNOWN"], "evidence": "수익률 시계열이 없어 시장 국면을 계산하지 않았습니다."})
    metadata["warning_messages"] = list(dict.fromkeys(warnings))
    result = {
        "data_type": data_type,
        "charts": analysis["charts"],
        "indicators": analysis["indicators"],
        "insights": ensure_insights(analysis["insights"]),
        "metadata": metadata,
        "data_quality": mvp_quality_report(metadata, warnings),
        "layout": build_layout(analysis["charts"], data_type),
        "preview_rows": dataframe_to_records(df.head(PREVIEW_ROW_LIMIT)),
    }
    return make_json_safe(result)


def mvp_base_metadata(raw_df: pd.DataFrame, warnings: list[str]) -> dict[str, Any]:
    return {
        "skill_version": SKILL_VERSION,
        "row_count": int(len(raw_df)),
        "column_count": int(len(raw_df.columns)),
        "original_columns": [str(column) for column in raw_df.columns],
        "column_mapping": [],
        "assumptions": ["risk_free_rate는 별도 입력이 없어 0으로 가정했습니다."],
        "preprocessing_actions": [],
        "warning_messages": warnings,
        "data_format": "unknown",
        "primary_type": None,
        "secondary_type": None,
    }


def mvp_preprocess(
    df: pd.DataFrame,
    metadata: dict[str, Any],
    warnings: list[str],
) -> pd.DataFrame:
    work = df.copy()
    duplicate_count = int(work.duplicated().sum())
    metadata["duplicate_row_count"] = duplicate_count
    if duplicate_count:
        work = work.drop_duplicates().copy()
        metadata["preprocessing_actions"].append(f"중복 행 {duplicate_count}개를 제거했습니다.")
        warnings.append(f"중복 행 {duplicate_count}개가 제거되었습니다.")

    if "date" in work.columns:
        source_non_null = int(work["date"].notna().sum())
        converted = pd.to_datetime(work["date"], errors="coerce")
        invalid_count = int(source_non_null - converted.notna().sum())
        work["date"] = converted
        metadata["date_conversion"] = {
            "attempted": True,
            "source_non_null": source_non_null,
            "converted_non_null": int(converted.notna().sum()),
            "invalid_count": invalid_count,
        }
        metadata["preprocessing_actions"].append("date 컬럼을 datetime으로 변환했습니다.")
        if invalid_count:
            warnings.append(f"date 컬럼에서 날짜로 변환되지 않은 값이 {invalid_count}개 있습니다.")
        if converted.notna().any():
            metadata["date_range"] = {
                "start": converted.min().date().isoformat(),
                "end": converted.max().date().isoformat(),
            }
            metadata["detected_frequency"] = detect_frequency(converted, warnings, metadata)
    else:
        metadata["date_conversion"] = {"attempted": False}
        metadata["detected_frequency"] = "unknown"

    converted_columns: list[str] = []
    percent_columns: list[str] = []
    for column in list(work.columns):
        if str(column) in NUMERIC_SKIP_COLUMNS:
            continue
        converted, did_convert, used_percent = convert_numeric_like_series(work[column], str(column))
        if did_convert:
            work[column] = converted
            converted_columns.append(str(column))
        if used_percent:
            percent_columns.append(str(column))

    metadata["converted_numeric_columns"] = converted_columns
    metadata["percent_columns_converted_to_decimal"] = percent_columns
    if converted_columns:
        metadata["preprocessing_actions"].append("숫자형 문자열을 수치형으로 변환했습니다: " + ", ".join(converted_columns[:8]))
    if percent_columns:
        message = "퍼센트 단위를 0~1 소수 기준으로 변환했습니다: " + ", ".join(percent_columns[:8])
        metadata["preprocessing_actions"].append(message)
        metadata["assumptions"].append(message)
        warnings.append(message)

    missing_counts = work.isna().sum()
    metadata["missing_values"] = {
        str(column): int(count) for column, count in missing_counts.items() if int(count) > 0
    }
    metadata["missing_cell_count"] = int(missing_counts.sum())
    metadata["missing_ratio"] = float(metadata["missing_cell_count"] / max(work.size, 1))
    metadata["preprocessing_actions"].append("결측치 비율을 계산했습니다.")
    if metadata["missing_values"]:
        warnings.append("결측치가 감지되었습니다: " + ", ".join(f"{k} {v}개" for k, v in list(metadata["missing_values"].items())[:6]))

    metadata["outliers"] = detect_outliers(work)
    if metadata["outliers"]:
        metadata["preprocessing_actions"].append("IQR 기준 이상치를 탐지했습니다.")
        warnings.append("IQR 기준 이상치가 감지되었습니다: " + ", ".join(f"{k} {v}개" for k, v in list(metadata["outliers"].items())[:6]))

    metadata["numeric_columns"] = [str(column) for column in work.select_dtypes(include=[np.number]).columns]
    return work


def mvp_detect_asset_class(df: pd.DataFrame, data_type: str) -> dict[str, Any]:
    text_items = [str(column) for column in df.columns]
    for column in ("ticker", "asset_name", "sector", "title", "text", "event", "source"):
        if column not in df.columns:
            continue
        values = df[column].dropna().astype(str).str.lower().unique().tolist()
        text_items.extend(values[:80])

    haystack = " ".join(text_items).lower()
    scores: dict[str, int] = {}
    evidence: dict[str, list[str]] = {}
    for asset_class, keywords in ASSET_CLASS_KEYWORDS.items():
        matches = [keyword for keyword in keywords if keyword.lower() in haystack]
        if matches:
            scores[asset_class] = len(matches)
            evidence[asset_class] = matches[:6]

    priority = ["crypto", "macro", "bond", "etf", "equity"]
    primary = None
    if scores:
        primary = sorted(scores, key=lambda item: (-scores[item], priority.index(item) if item in priority else 99))[0]
    elif data_type in {DATA_TYPES["TYPE_A"], DATA_TYPES["TYPE_B"], DATA_TYPES["TYPE_D"]}:
        primary = "equity"
        evidence["equity"] = ["price_or_portfolio_structure"]
    else:
        primary = "unknown"

    return {
        "primary": primary,
        "detected": [item for item in priority if item in evidence],
        "evidence": evidence,
    }


def mvp_classify_market_regime(cumulative_return: float | None, annualized_volatility: float | None) -> dict[str, Any]:
    if cumulative_return is None or annualized_volatility is None:
        return {
            "label": MARKET_REGIME_LABELS["UNKNOWN"],
            "evidence": "cumulative_return 또는 annualized_volatility가 부족합니다.",
        }

    if abs(cumulative_return) < 0.05 and annualized_volatility < 0.15:
        label = MARKET_REGIME_LABELS["SIDEWAYS_STABLE"]
        message = "방향성이 제한된 횡보 구간으로 해석될 수 있습니다."
    elif cumulative_return > 0 and annualized_volatility < 0.15:
        label = MARKET_REGIME_LABELS["STABLE_BULLISH"]
        message = "안정적인 상승 흐름이 관찰됩니다."
    elif cumulative_return > 0 and annualized_volatility >= 0.30:
        label = MARKET_REGIME_LABELS["VOLATILE_BULLISH"]
        message = "상승 흐름과 함께 높은 변동성이 관찰됩니다."
    elif cumulative_return < 0 and annualized_volatility >= 0.30:
        label = MARKET_REGIME_LABELS["HIGH_RISK_BEARISH"]
        message = "높은 변동성을 동반한 약세 흐름이 관찰됩니다."
    elif cumulative_return < 0 and annualized_volatility < 0.15:
        label = MARKET_REGIME_LABELS["WEAK_BEARISH"]
        message = "낮은 변동성의 약세 흐름이 관찰됩니다."
    elif cumulative_return > 0:
        label = MARKET_REGIME_LABELS["VOLATILE_BULLISH"]
        message = "상승 흐름이 있으나 변동성이 안정 구간을 벗어났습니다."
    else:
        label = MARKET_REGIME_LABELS["HIGH_RISK_BEARISH"]
        message = "약세 흐름과 변동성 부담이 함께 관찰됩니다."

    return {
        "label": label,
        "message": message,
        "evidence": f"cumulative_return={cumulative_return:.2%}, annualized_volatility={annualized_volatility:.2%}",
    }


def format_percent_for_evidence(value: Any) -> str:
    if value is None:
        return "not_calculated"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(numeric):
        return "not_calculated"
    return f"{numeric:.2%}"


def mvp_detect_data_type(df: pd.DataFrame) -> tuple[str, str]:
    has_date = "date" in df.columns and df["date"].notna().any()
    has_close = "close" in df.columns and pd.to_numeric(df["close"], errors="coerce").notna().any()
    has_return = "return" in df.columns and pd.to_numeric(df["return"], errors="coerce").notna().any()
    asset_column = choose_asset_identifier_column(df)
    has_asset = asset_column is not None
    asset_count = int(df[asset_column].dropna().astype(str).nunique()) if has_asset else 0
    has_weight_or_value = any(
        column in df.columns and pd.to_numeric(df[column], errors="coerce").notna().any()
        for column in ("weight", "value")
    )
    has_event_data = any(column in df.columns and df[column].notna().any() for column in ("title", "text", "event", "sentiment"))

    if has_date and has_asset and asset_count >= 2 and (has_close or has_return):
        return DATA_TYPES["TYPE_D"], "Long-format Type-D 구조가 감지되어 MVP 부분 지원 분석을 적용합니다."
    if has_date and len(wide_time_series_value_columns(df)) >= 2:
        return DATA_TYPES["TYPE_D"], "Wide-format Type-D 후보가 감지되어 MVP 부분 지원 분석을 적용합니다."
    if has_date and has_close:
        return DATA_TYPES["TYPE_A"], "date + close 컬럼이 감지되어 Type-A 단일 가격 시계열로 분석합니다."
    if has_asset and has_weight_or_value:
        return DATA_TYPES["TYPE_B"], f"{asset_column} + weight/value 컬럼이 감지되어 Type-B 포트폴리오로 분석합니다."
    if has_event_data:
        return DATA_TYPES["TYPE_C"], "뉴스/이벤트/감성 컬럼이 감지되었지만 MVP에서는 계획/부분 지원으로 표시합니다."
    return DATA_TYPES["UNKNOWN"], "Type-A 또는 Type-B 필수 컬럼 조합이 없어 Unknown 탐색 분석으로 처리합니다."


def mvp_suggest_candidate_type(df: pd.DataFrame, data_type: str) -> dict[str, Any]:
    if data_type in {DATA_TYPES["TYPE_A"], DATA_TYPES["TYPE_B"], DATA_TYPES["TYPE_D"]}:
        return {
            "suggested_type": data_type,
            "confidence": "high",
            "reason": "MVP 규칙으로 분석 타입이 확정되었습니다.",
        }
    if data_type == DATA_TYPES["TYPE_C"]:
        return {
            "suggested_type": data_type,
            "confidence": "medium",
            "reason": "뉴스/이벤트/감성 컬럼이 감지되었지만 MVP에서는 planned 상태입니다.",
        }

    has_date = "date" in df.columns and df["date"].notna().any()
    has_close = "close" in df.columns
    asset_column = choose_asset_identifier_column(df)
    has_weight_or_value = any(column in df.columns for column in ("weight", "value"))
    has_text_like = any(column in df.columns for column in ("title", "text", "event", "sentiment"))
    numeric_cols = numeric_columns(df, exclude={"date"})
    asset_class = mvp_detect_asset_class(df, data_type)

    if has_date and has_close:
        return {"suggested_type": DATA_TYPES["TYPE_A"], "confidence": "medium", "reason": "date와 close가 있어 Type-A 후보입니다."}
    if asset_column and has_weight_or_value:
        return {"suggested_type": DATA_TYPES["TYPE_B"], "confidence": "medium", "reason": "자산 식별자와 weight/value가 있어 Type-B 후보입니다."}
    if has_text_like:
        return {"suggested_type": DATA_TYPES["TYPE_C"], "confidence": "low", "reason": "텍스트/이벤트/감성 컬럼이 있어 향후 Type-C 후보입니다."}
    if asset_class.get("primary") == "macro":
        return {"suggested_type": DATA_TYPES["UNKNOWN"], "confidence": "medium", "reason": "macro/yield 키워드가 감지되어 탐색적 거시 지표 분석으로 처리합니다."}
    if has_date and len(numeric_cols) >= 1:
        return {"suggested_type": DATA_TYPES["TYPE_A"], "confidence": "low", "reason": "date와 수치형 컬럼이 있어 close 컬럼명을 보강하면 Type-A 분석이 가능합니다."}
    return {"suggested_type": DATA_TYPES["UNKNOWN"], "confidence": "low", "reason": "투자 데이터 타입을 추정할 핵심 컬럼이 부족합니다."}


def mvp_analyze_type_a(
    df: pd.DataFrame,
    metadata: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    metadata["data_format"] = "long"
    value_columns = ["close"] + [column for column in ("open", "high", "low", "volume") if column in df.columns]
    work = df[["date", *value_columns]].copy()
    for column in value_columns:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(subset=["date"]).sort_values("date")
    if work["close"].isna().any():
        work["close"] = work["close"].ffill().bfill()
        metadata["preprocessing_actions"].append("Type-A close 결측치를 forward fill 후 backward fill로 보정했습니다.")
    for column in ("open", "high", "low", "volume"):
        if column in work.columns and work[column].isna().any():
            work[column] = work[column].ffill().bfill()
            metadata["preprocessing_actions"].append(f"Type-A {column} 결측치를 forward fill 후 backward fill로 보정했습니다.")
    work = work.dropna(subset=["close"]).groupby("date", as_index=False).last()

    if work.empty:
        warnings.append("Type-A 분석에 필요한 유효한 date/close 데이터가 없습니다.")
        metadata["market_regime"] = mvp_classify_market_regime(None, None)
        return {
            "indicators": [indicator("유효 행 수", 0, "integer")],
            "charts": [],
            "insights": [insight("Type-A 분석 불가", "Risk", "유효한 date/close 데이터가 부족합니다.", "valid_rows=0", "CSV 컬럼과 결측치를 확인")],
        }

    work["daily_return"] = work["close"].pct_change()
    work["cumulative_return"] = (1 + work["daily_return"].fillna(0)).cumprod() - 1
    work["MA5"] = work["close"].rolling(5, min_periods=1).mean()
    work["MA20"] = work["close"].rolling(20, min_periods=1).mean()
    work["MA60"] = work["close"].rolling(60, min_periods=1).mean()
    work["RSI14"] = compute_rsi(work["close"], 14)
    work["MACD"] = work["close"].ewm(span=12, adjust=False).mean() - work["close"].ewm(span=26, adjust=False).mean()
    work["MACD_signal"] = work["MACD"].ewm(span=9, adjust=False).mean()
    work["MACD_histogram"] = work["MACD"] - work["MACD_signal"]
    work["drawdown"] = work["close"] / work["close"].cummax() - 1
    work["rolling_volatility_20"] = work["daily_return"].rolling(20).std() * math.sqrt(ANNUAL_TRADING_DAYS)
    if "volume" in work.columns:
        work["volume_change"] = work["volume"].pct_change()
        work["volume_ratio_20"] = work["volume"] / work["volume"].rolling(20, min_periods=1).mean()

    returns = work["daily_return"].dropna()
    latest_close = latest_number(work["close"])
    latest_return = latest_number(work["daily_return"])
    cumulative_return_last = latest_number(work["cumulative_return"])
    annualized_vol = float(returns.std() * math.sqrt(ANNUAL_TRADING_DAYS)) if len(returns) >= 2 else None
    negative_returns = returns[returns < 0]
    downside_vol = float(negative_returns.std() * math.sqrt(ANNUAL_TRADING_DAYS)) if len(negative_returns) >= 2 else None
    var95 = float(returns.quantile(0.05)) if len(returns) >= 5 else None
    mdd = float(work["drawdown"].min()) if work["drawdown"].notna().any() else None
    latest_ma5 = latest_number(work["MA5"])
    latest_ma20 = latest_number(work["MA20"])
    latest_ma60 = latest_number(work["MA60"])
    latest_rsi = latest_number(work["RSI14"])
    latest_macd = latest_number(work["MACD"])
    latest_macd_signal = latest_number(work["MACD_signal"])
    latest_rolling_vol = latest_number(work["rolling_volatility_20"])
    latest_volume_change = latest_number(work["volume_change"]) if "volume_change" in work.columns else None
    latest_volume_ratio = latest_number(work["volume_ratio_20"]) if "volume_ratio_20" in work.columns else None
    metadata["market_regime"] = mvp_classify_market_regime(cumulative_return_last, annualized_vol)
    metadata["technical_indicators"] = {
        "ohlc_available": all(column in work.columns for column in ("open", "high", "low", "close")),
        "macd": latest_macd,
        "macd_signal": latest_macd_signal,
        "rolling_volatility_20": latest_rolling_vol,
        "var_95": var95,
        "downside_volatility": downside_vol,
    }

    insights: list[Any] = []
    regime = metadata["market_regime"]
    if regime.get("label") != MARKET_REGIME_LABELS["UNKNOWN"]:
        insights.append(insight("시장 국면", "Info", regime.get("message", "시장 국면을 계산했습니다."), regime.get("evidence"), "누적 수익률과 변동성 동시 확인"))
    if latest_close is not None and latest_ma20 is not None:
        if latest_close >= latest_ma20:
            insights.append(insight("가격 추세", "Positive", "최근 종가가 MA20 위에 있어 단기 추세가 양호합니다.", f"close={latest_close:.4g}, MA20={latest_ma20:.4g}", "MA20 유지 여부 확인"))
        else:
            insights.append(insight("가격 추세", "Warning", "최근 종가가 MA20 아래에 있어 단기 추세 약화가 관찰됩니다.", f"close={latest_close:.4g}, MA20={latest_ma20:.4g}", "MA20 회복 여부 확인"))
    if len(work) >= 2 and work[["MA20", "MA60"]].iloc[-2:].notna().all().all():
        previous_ma20 = float(work["MA20"].iloc[-2])
        previous_ma60 = float(work["MA60"].iloc[-2])
        current_ma20 = float(work["MA20"].iloc[-1])
        current_ma60 = float(work["MA60"].iloc[-1])
        if previous_ma20 <= previous_ma60 and current_ma20 > current_ma60:
            insights.append(insight("이동평균 교차", "Positive", "MA20이 MA60을 상향 돌파하는 골든크로스 가능성이 관찰됩니다.", f"MA20={current_ma20:.4g}, MA60={current_ma60:.4g}", "교차 이후 가격 유지 여부 확인"))
        elif previous_ma20 >= previous_ma60 and current_ma20 < current_ma60:
            insights.append(insight("이동평균 교차", "Warning", "MA20이 MA60을 하향 이탈하는 데드크로스 가능성이 관찰됩니다.", f"MA20={current_ma20:.4g}, MA60={current_ma60:.4g}", "추세 약화 지속 여부 확인"))
    if annualized_vol is not None:
        level = "Warning" if annualized_vol >= 0.30 else "Info"
        insights.append(insight("변동성", level, "연환산 변동성으로 가격 변동 위험을 확인했습니다.", f"annualized_vol={annualized_vol:.2%}", "변동성 확대 구간 확인"))
    if var95 is not None:
        insights.append(insight("VaR 95%", "Info", "과거 일간 수익률 기준 하위 5% 손실 구간을 계산했습니다.", f"VaR95={var95:.2%}", "꼬리 위험과 급락일 확인"))
    if mdd is not None:
        level = "Risk" if mdd <= -0.20 else "Info"
        insights.append(insight("최대 낙폭", level, "최고점 대비 최대 낙폭을 계산했습니다.", f"MDD={mdd:.2%}", "낙폭 발생 기간 확인"))
    if latest_rsi is not None:
        if latest_rsi >= 70:
            insights.append(insight("RSI", "Warning", "RSI 기준 과매수 가능성이 관찰됩니다.", f"RSI14={latest_rsi:.2f}", "가격 둔화 여부 확인"))
        elif latest_rsi <= 30:
            insights.append(insight("RSI", "Info", "RSI 기준 과매도 가능성이 관찰됩니다.", f"RSI14={latest_rsi:.2f}", "반등 여부 확인"))
    if latest_volume_ratio is not None and latest_volume_ratio >= 2:
        insights.append(insight("거래량 변화", "Info", "최근 거래량이 20일 평균 대비 2배 이상으로 증가했습니다.", f"volume/MA20={latest_volume_ratio:.2f}", "가격 변화와 동반 여부 확인"))

    charts: list[dict[str, Any]] = []
    if all(column in work.columns for column in ("open", "high", "low", "close")):
        charts.append(
            chart(
                "candlestick",
                "OHLC Candlestick",
                dataframe_to_records(sample_chart_rows(work[["date", "open", "high", "low", "close"]])),
                "date",
                ["open", "high", "low", "close"],
                "open/high/low/close 컬럼이 모두 있어 캔들스틱 차트를 우선 표시합니다.",
            )
        )
    else:
        charts.append(
            chart(
                "line",
                "Close vs MA20",
                dataframe_to_records(sample_chart_rows(work[["date", "close", "MA20"]])),
                "date",
                ["close", "MA20"],
                "Type-A 핵심 차트: 종가와 20일 이동평균을 비교합니다.",
            )
        )

    charts.extend(
        [
            chart("line", "Moving Averages", dataframe_to_records(sample_chart_rows(work[["date", "close", "MA5", "MA20", "MA60"]])), "date", ["close", "MA5", "MA20", "MA60"], "MA5/20/60으로 단기와 중기 추세를 비교합니다."),
            chart("line", "Drawdown", dataframe_to_records(sample_chart_rows(work[["date", "drawdown"]])), "date", ["drawdown"], "최고점 대비 낙폭을 확인합니다."),
            chart("line", "RSI(14)", dataframe_to_records(sample_chart_rows(work[["date", "RSI14"]])), "date", ["RSI14"], "RSI(14) 과매수/과매도 가능성을 확인합니다."),
            chart("line", "MACD(12/26/9)", dataframe_to_records(sample_chart_rows(work[["date", "MACD", "MACD_signal", "MACD_histogram"]])), "date", ["MACD", "MACD_signal", "MACD_histogram"], "MACD와 Signal, Histogram으로 추세 모멘텀을 확인합니다."),
            chart("line", "Rolling Volatility 20D", dataframe_to_records(sample_chart_rows(work[["date", "rolling_volatility_20"]])), "date", ["rolling_volatility_20"], "20일 rolling volatility로 변동성 확대 구간을 확인합니다."),
            chart("line", "Cumulative Return", dataframe_to_records(sample_chart_rows(work[["date", "cumulative_return"]])), "date", ["cumulative_return"], "누적 수익률 흐름을 확인합니다."),
        ]
    )
    if "volume" in work.columns:
        charts.append(chart("bar", "Volume", dataframe_to_records(sample_chart_rows(work[["date", "volume"]])), "date", ["volume"], "거래량 컬럼이 있어 기간별 거래량을 표시합니다."))

    return {
        "indicators": [
            indicator("date range", f"{work['date'].min().date().isoformat()} ~ {work['date'].max().date().isoformat()}", "text"),
            indicator("latest close", latest_close, "number"),
            indicator("daily return", latest_return, "percent"),
            indicator("cumulative return", cumulative_return_last, "percent"),
            indicator("annualized volatility", annualized_vol, "percent"),
            indicator("VaR 95%", var95, "percent"),
            indicator("downside volatility", downside_vol, "percent"),
            indicator("rolling volatility 20D", latest_rolling_vol, "percent"),
            indicator("MDD", mdd, "percent"),
            indicator("MA5", latest_ma5, "number"),
            indicator("MA20", latest_ma20, "number"),
            indicator("MA60", latest_ma60, "number"),
            indicator("RSI14", latest_rsi, "number"),
            indicator("MACD", latest_macd, "number"),
            indicator("MACD signal", latest_macd_signal, "number"),
            indicator("volume change", latest_volume_change, "percent"),
        ],
        "charts": charts,
        "insights": insights,
    }


def mvp_analyze_type_b(
    df: pd.DataFrame,
    metadata: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    metadata["data_format"] = "portfolio_snapshot"
    asset_column = choose_asset_identifier_column(df)
    source_column = "weight" if "weight" in df.columns else "value" if "value" in df.columns else None
    if not asset_column or not source_column:
        warnings.append("Type-B 분석에 필요한 자산 식별자와 weight/value 컬럼이 부족합니다.")
        return mvp_analyze_unknown(df, metadata, warnings)

    columns = [asset_column, source_column] + (["sector"] if "sector" in df.columns else [])
    work = df[columns].copy()
    work[asset_column] = work[asset_column].astype(str).str.strip()
    work[source_column] = pd.to_numeric(work[source_column], errors="coerce")
    work = work.dropna(subset=[asset_column, source_column])
    work = work[work[asset_column] != ""]

    if work.empty or float(work[source_column].sum()) <= 0:
        warnings.append("Type-B 분석에 사용할 양수 weight/value 데이터가 없습니다.")
        return mvp_analyze_unknown(df, metadata, warnings)

    source_total = float(work[source_column].sum())
    if source_column == "weight" and not math.isclose(source_total, 1.0, rel_tol=0.02, abs_tol=0.02):
        message = f"weight 합계가 {source_total:.4g}이므로 합계 1 기준으로 정규화했습니다."
        metadata["preprocessing_actions"].append(message)
        metadata["assumptions"].append(message)

    allocation = work.groupby(asset_column, as_index=False)[source_column].sum()
    allocation = allocation.rename(columns={asset_column: "asset"})
    allocation["weight"] = allocation[source_column] / float(allocation[source_column].sum())
    allocation = allocation.sort_values("weight", ascending=False)
    top1 = float(allocation["weight"].iloc[0])
    top3 = float(allocation["weight"].head(3).sum())
    hhi = float(np.square(allocation["weight"]).sum())

    insights: list[Any] = []
    if top1 >= 0.40:
        insights.append(insight("단일 자산 집중", "Risk", "Top1 비중이 40% 이상으로 단일 자산 집중 위험이 있습니다.", f"top1={top1:.2%}", "최대 보유 자산의 리스크 확인"))
    if top3 >= 0.70:
        insights.append(insight("상위 자산 집중", "Warning", "상위 3개 자산 비중이 70% 이상입니다.", f"top3={top3:.2%}", "상위 자산 간 상관관계 확인"))
    if hhi >= 0.25:
        insights.append(insight("HHI 집중도", "Warning", "HHI 기준 포트폴리오 집중도가 높습니다.", f"HHI={hhi:.4f}", "분산 필요성 확인"))
    elif hhi < 0.10:
        insights.append(insight("분산도", "Positive", "HHI 기준 자산이 비교적 고르게 분산되어 있습니다.", f"HHI={hhi:.4f}", "섹터 편중 여부 확인"))
    insights.append(insight("위험 기여도", "Info", "수익률 패널 또는 공분산 행렬이 없어 위험 기여도는 계산하지 않았습니다.", "risk_contribution=not_calculated", "수익률 시계열이 있는 Type-D 데이터로 보강"))

    charts = [
        chart("donut" if len(allocation) <= 10 else "bar", "Portfolio Weights", dataframe_to_records(allocation[["asset", "weight"]]), "asset", ["weight"], "정규화된 자산별 비중을 표시합니다."),
        chart("table", "Portfolio Weight Table", dataframe_to_records(allocation[["asset", "weight"]].head(20)), "asset", ["weight"], "상위 보유 자산의 정규화 비중을 표로 표시합니다."),
    ]

    sector_weight_value = None
    if "sector" in work.columns:
        sector = work.copy()
        sector["weight"] = sector[source_column] / float(work[source_column].sum())
        sector_weights = sector.groupby("sector", as_index=False)["weight"].sum().sort_values("weight", ascending=False)
        if not sector_weights.empty:
            sector_weight_value = float(sector_weights["weight"].iloc[0])
            charts.append(chart("bar", "Sector Weights", dataframe_to_records(sector_weights), "sector", ["weight"], "섹터 컬럼이 있어 섹터별 비중을 표시합니다."))
            if sector_weight_value >= 0.50:
                insights.append(insight("섹터 집중", "Warning", "특정 섹터 비중이 50% 이상입니다.", f"max_sector={sector_weight_value:.2%}", "섹터별 위험 요인 확인"))

    return {
        "indicators": [
            indicator("asset count", int(len(allocation)), "integer"),
            indicator("top1 weight", top1, "percent"),
            indicator("top3 weight", top3, "percent"),
            indicator("HHI", hhi, "number"),
            indicator("max sector weight", sector_weight_value, "percent"),
            indicator("risk contribution", "not_calculated", "text", status="not_calculated", reason="수익률 패널 또는 공분산 행렬이 없습니다."),
        ],
        "charts": charts,
        "insights": insights,
    }


def mvp_analyze_type_d_partial(
    df: pd.DataFrame,
    metadata: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    pivot, source_description, value_kind = build_multi_asset_pivot(df, warnings)
    metadata["data_format"] = "long" if source_description.startswith("long") else "wide"
    metadata["assumptions"].append("Type-D는 MVP에서 누적수익률, 상관관계, 위험-수익 산점도까지 부분 지원합니다.")
    metadata["type_d"] = {
        "source_description": source_description,
        "value_kind": value_kind,
        "support_status": "partially_supported",
    }

    if pivot.empty or len(pivot.columns) < 2:
        warnings.append("Type-D 부분 분석에 필요한 2개 이상 자산 시계열이 부족합니다.")
        return mvp_analyze_planned(df, DATA_TYPES["TYPE_D"], metadata, warnings)

    pivot = pivot.sort_index().apply(pd.to_numeric, errors="coerce").ffill().bfill()
    if value_kind == "return":
        returns = pivot.replace([np.inf, -np.inf], np.nan)
        cumulative = (1 + returns.fillna(0)).cumprod() - 1
    else:
        returns = pivot.pct_change().replace([np.inf, -np.inf], np.nan)
        cumulative = (1 + returns.fillna(0)).cumprod() - 1

    common_observations = int(returns.dropna(how="all").shape[0])
    min_periods = 20 if common_observations >= 20 else 2
    if common_observations < 20:
        warnings.append("Type-D 상관계수 해석에는 공통 관측치 20개 이상이 권장됩니다.")
    corr = returns.corr(min_periods=min_periods)
    corr_pairs = correlation_observation_warnings(returns, warnings)
    avg_corr = average_off_diagonal(corr)

    metric_rows: list[dict[str, Any]] = []
    for column in pivot.columns:
        asset_return = returns[column].dropna()
        asset_cumulative = latest_number(cumulative[column])
        asset_vol = float(asset_return.std() * math.sqrt(ANNUAL_TRADING_DAYS)) if len(asset_return) >= 2 else None
        wealth = 1 + cumulative[column].fillna(0)
        asset_drawdown = wealth / wealth.cummax() - 1
        asset_mdd = float(asset_drawdown.min()) if asset_drawdown.notna().any() else None
        metric_rows.append(
            {
                "asset": str(column),
                "cumulative_return": asset_cumulative,
                "annualized_volatility": asset_vol,
                "mdd": asset_mdd,
            }
        )

    metric_rows = sorted(
        metric_rows,
        key=lambda row: row["cumulative_return"] if row["cumulative_return"] is not None else -math.inf,
        reverse=True,
    )
    portfolio_returns = returns.mean(axis=1, skipna=True).dropna()
    portfolio_cumulative = float((1 + portfolio_returns.fillna(0)).cumprod().iloc[-1] - 1) if not portfolio_returns.empty else None
    portfolio_vol = float(portfolio_returns.std() * math.sqrt(ANNUAL_TRADING_DAYS)) if len(portfolio_returns) >= 2 else None
    metadata["market_regime"] = mvp_classify_market_regime(portfolio_cumulative, portfolio_vol)
    metadata["type_d"].update(
        {
            "asset_count": int(len(pivot.columns)),
            "common_observations": common_observations,
            "average_correlation": avg_corr,
            "low_observation_pairs": len(corr_pairs),
        }
    )

    cumulative_frame = cumulative.reset_index()
    cumulative_frame = cumulative_frame.rename(columns={cumulative_frame.columns[0]: "date"})
    cumulative_records = dataframe_to_records(sample_chart_rows(cumulative_frame))

    charts = [
        chart("line", "Type-D Cumulative Return Comparison", cumulative_records, "date", [str(column) for column in pivot.columns], "자산별 누적 수익률을 비교합니다."),
        chart("heatmap", "Type-D Correlation Heatmap", correlation_to_records(corr, "asset"), "asset", [str(column) for column in corr.columns], "자산별 수익률 상관계수를 표시합니다."),
        chart("scatter", "Risk Return Scatter", metric_rows, "annualized_volatility", ["cumulative_return"], "자산별 변동성과 누적 수익률을 함께 비교합니다."),
        chart("table", "Risk Return Rank", metric_rows, "asset", ["cumulative_return", "annualized_volatility", "mdd"], "자산별 수익률, 변동성, 낙폭 순위를 표시합니다."),
    ]

    insights: list[dict[str, Any]] = []
    regime = metadata["market_regime"]
    if regime.get("label") != MARKET_REGIME_LABELS["UNKNOWN"]:
        insights.append(insight("시장 국면", "Info", regime.get("message", "시장 국면을 계산했습니다."), regime.get("evidence"), "동일가중 평균 수익률 기준임을 확인"))
    if metric_rows:
        best = metric_rows[0]
        insights.append(insight("최고 누적 수익률", "Positive", "분석 기간 중 가장 높은 누적 수익률 자산이 확인됩니다.", f"{best['asset']}={format_percent_for_evidence(best['cumulative_return'])}", "해당 자산의 변동성과 MDD 동시 확인"))
        worst_mdd = min(metric_rows, key=lambda row: row["mdd"] if row["mdd"] is not None else math.inf)
        insights.append(insight("최대 낙폭 자산", "Risk" if (worst_mdd.get("mdd") or 0) <= -0.20 else "Info", "가장 큰 낙폭을 보인 자산을 확인했습니다.", f"{worst_mdd['asset']} MDD={format_percent_for_evidence(worst_mdd.get('mdd'))}", "낙폭 발생 시점 확인"))
    if avg_corr is not None and avg_corr >= 0.70:
        insights.append(insight("상관관계 집중", "Warning", "평균 상관계수가 높아 분산 효과가 제한될 수 있습니다.", f"avg_corr={avg_corr:.2f}", "상관관계 heatmap 확인"))
    if corr_pairs:
        insights.append(insight("상관계수 관측치", "Warning", "일부 자산 쌍은 공통 관측치가 20개 미만입니다.", f"pairs={len(corr_pairs)}", "기간이 겹치는 데이터 보강"))

    return {
        "indicators": [
            indicator("asset count", int(len(pivot.columns)), "integer"),
            indicator("common observations", common_observations, "integer"),
            indicator("portfolio cumulative return", portfolio_cumulative, "percent"),
            indicator("portfolio volatility", portfolio_vol, "percent"),
            indicator("average correlation", avg_corr, "number"),
            indicator("support status", "partially_supported", "text"),
        ],
        "charts": charts,
        "insights": insights,
    }


def mvp_analyze_unknown(
    df: pd.DataFrame,
    metadata: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    metadata["data_format"] = "unknown"
    candidate = mvp_suggest_candidate_type(df, DATA_TYPES["UNKNOWN"])
    metadata["candidate_data_type"] = candidate
    numeric_cols = numeric_columns(df, exclude={"date"})[:MAX_FALLBACK_NUMERIC_COLUMNS]
    metadata["unknown_profile"] = {
        "numeric_columns_used": numeric_cols,
        "non_numeric_columns": [str(column) for column in df.columns if str(column) not in numeric_columns(df, exclude=set())],
    }

    charts = [
        chart("table", "Column Summary", column_summary_rows(df), "column", ["dtype", "non_null", "missing", "unique"], "Unknown fallback: 컬럼 타입, 결측치, 고유값 수를 요약합니다."),
    ]
    numeric_summary = numeric_summary_rows(df, numeric_cols)
    if numeric_summary:
        charts.append(chart("table", "Numeric Summary", numeric_summary, "column", ["mean", "std", "min", "p25", "median", "p75", "max"], "수치형 컬럼의 기술통계를 표시합니다."))
        charts.extend(numeric_distribution_charts(df, numeric_cols))
        if len(numeric_cols) >= 2:
            corr = df[numeric_cols].apply(pd.to_numeric, errors="coerce").corr()
            charts.append(chart("heatmap", "Numeric Correlation Heatmap", correlation_to_records(corr, "column"), "column", [str(column) for column in corr.columns], "수치형 컬럼 간 상관관계를 탐색적으로 표시합니다."))
    else:
        charts.append(categorical_cardinality_chart(df))

    missing_rows = missing_ratio_rows(df, metadata)
    missing_nonzero_rows = [row for row in missing_rows if row["missing"] > 0]
    if missing_nonzero_rows:
        charts.append(chart("bar", "Missing Values by Column", missing_nonzero_rows, "column", ["missing"], "결측치가 있는 컬럼을 막대 차트로 표시합니다."))
    charts.append(chart("table", "Missing Summary", missing_rows, "column", ["missing", "missing_ratio"], "컬럼별 결측 비율을 표시합니다."))

    asset_primary = (metadata.get("asset_class") or {}).get("primary")
    insight_rows = [
        insight("탐색적 분석", "Info", "MVP 규칙으로 Type-A/Type-B/Type-D를 확정할 수 없어 Unknown fallback을 제공합니다.", f"candidate={candidate.get('suggested_type')}, confidence={candidate.get('confidence')}", "컬럼명을 Skills.md 표준명에 맞춰 보강"),
        insight("데이터 품질", "Warning" if metadata.get("missing_ratio", 0) >= 0.10 else "Info", "결측률과 컬럼 구조를 먼저 확인해야 합니다.", f"missing_rate={metadata.get('missing_ratio', 0):.2%}", "Missing Summary 확인"),
    ]
    if asset_primary == "macro":
        insight_rows.append(insight("Macro/Yield 후보", "Info", "금리, CPI, 환율 같은 거시 지표 후보가 감지되어 기술적 매매 지표 대신 변화율과 분포 중심으로 해석합니다.", f"asset_class={asset_primary}", "YoY/MoM 계산에 필요한 주기 확인"))

    return {
        "indicators": [
            indicator("row count", int(len(df)), "integer"),
            indicator("column count", int(len(df.columns)), "integer"),
            indicator("missing rate", float(metadata.get("missing_ratio", 0)), "percent"),
            indicator("numeric column count", int(len(numeric_columns(df, exclude={"date"}))), "integer"),
            indicator("candidate type", candidate.get("suggested_type", "Unknown"), "text"),
        ],
        "charts": charts,
        "insights": insight_rows,
    }


def mvp_analyze_planned(
    df: pd.DataFrame,
    data_type: str,
    metadata: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    warnings.append(f"{data_type}는 MVP에서 계획/부분 지원 상태입니다. 전체 분석은 아직 구현하지 않았습니다.")
    metadata["assumptions"].append(f"{data_type} 구조는 감지했지만 MVP 범위 밖이라 계획/부분 지원으로 표시합니다.")
    return {
        "indicators": [
            indicator("row count", int(len(df)), "integer"),
            indicator("column count", int(len(df.columns)), "integer"),
            indicator("support status", "planned / partially supported", "text"),
        ],
        "charts": [
            chart("table", f"{data_type} Column Summary", column_summary_rows(df), "column", ["dtype", "non_null", "missing", "unique"], f"{data_type} 구조를 감지했지만 MVP에서는 컬럼 요약만 표시합니다.")
        ],
        "insights": [
            insight("부분 지원", "Info", f"{data_type}는 현재 MVP에서 전체 analytics를 제공하지 않습니다.", "support_status=planned", "Type-A, Type-B, Unknown 분석을 우선 사용"),
        ],
    }


def mvp_quality_report(metadata: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    missing_ratio = float(metadata.get("missing_ratio", 0))
    outliers_count = int(sum(metadata.get("outliers", {}).values()))
    if metadata.get("row_count", 0) == 0 or missing_ratio >= 0.30:
        status = QUALITY_LEVELS["RISK"]
    elif warnings or missing_ratio >= 0.10:
        status = QUALITY_LEVELS["WARNING"]
    else:
        status = QUALITY_LEVELS["GOOD"]

    return {
        "row_count": int(metadata.get("row_count", 0)),
        "column_count": int(metadata.get("column_count", 0)),
        "missing_rate": missing_ratio,
        "missing_ratio": missing_ratio,
        "outliers_count": outliers_count,
        "outlier_count": outliers_count,
        "status": status,
        "quality_level": status,
        "warning_messages": list(dict.fromkeys(warnings)),
    }
