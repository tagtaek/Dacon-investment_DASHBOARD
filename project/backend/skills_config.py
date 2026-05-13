DATA_TYPES = {
    "TYPE_A": "Type-A",
    "TYPE_B": "Type-B",
    "TYPE_C": "Type-C",
    "TYPE_D": "Type-D",
    "UNKNOWN": "Unknown",
    "INVALID": "Invalid",
}

COLUMN_ALIASES = {
    "date": ["date", "datetime", "timestamp", "날짜", "일자", "기준일"],
    "open": ["open", "opening_price", "open_price", "시가"],
    "high": ["high", "high_price", "최고가", "고가"],
    "low": ["low", "low_price", "최저가", "저가"],
    "close": ["close", "adj_close", "adjusted_close", "price", "last_price", "종가", "가격", "현재가"],
    "volume": ["volume", "trading_volume", "거래량"],
    "ticker": ["ticker", "symbol", "code", "asset", "stock", "종목", "종목코드"],
    "asset_name": ["name", "asset_name", "stock_name", "security_name", "종목명", "자산명"],
    "sector": ["sector", "industry", "category", "섹터", "산업", "업종"],
    "weight": ["weight", "ratio", "allocation", "allocation_pct", "비중", "구성비"],
    "value": ["value", "amount", "market_value", "평가금액", "보유금액"],
    "return": ["return", "daily_return", "ret", "yield", "수익률", "일간수익률"],
    "sentiment": ["sentiment", "polarity", "sentiment_score", "감성", "감성점수"],
    "event": ["event", "event_type", "disclosure_type", "이벤트", "공시유형"],
    "title": ["title", "headline", "news_title", "제목", "뉴스제목"],
    "text": ["text", "content", "body", "article", "기사내용", "본문"],
    "source": ["source", "publisher", "media", "언론사", "출처"],
    "keyword": ["keyword", "tag", "topic", "키워드", "태그"],
}

NUMERIC_SKIP_COLUMNS = {"date", "ticker", "asset_name", "sector", "title", "text", "event", "source", "keyword"}
PERCENT_COLUMNS = {"weight", "return"}

PREVIEW_ROW_LIMIT = 10
MAX_CHART_POINTS = 500
MAX_FALLBACK_NUMERIC_COLUMNS = 6
MAX_DISTRIBUTION_BINS = 8
ANNUAL_TRADING_DAYS = 252
OUTLIER_IQR_MULTIPLIER = 1.5

QUALITY_LEVELS = {
    "GOOD": "Good",
    "WARNING": "Warning",
    "RISK": "Risk",
}

SKILL_VERSION = "1.2.0"

ASSET_CLASS_KEYWORDS = {
    "crypto": ["btc", "bitcoin", "eth", "ethereum", "crypto", "coin", "sol", "xrp"],
    "bond": ["bond", "treasury", "yield", "국채", "채권", "회사채"],
    "macro": [
        "cpi",
        "inflation",
        "interest_rate",
        "rate",
        "unemployment",
        "exchange_rate",
        "fed",
        "macro",
        "물가",
        "금리",
        "실업률",
        "환율",
    ],
    "etf": ["etf", "fund", "spy", "qqq", "ivv", "voo", "tlt", "xlk"],
    "equity": ["equity", "stock", "share", "common", "aapl", "msft", "nvda", "tsla", "005930", "삼성전자"],
}

MARKET_REGIME_LABELS = {
    "STABLE_BULLISH": "Stable Bullish",
    "VOLATILE_BULLISH": "Volatile Bullish",
    "HIGH_RISK_BEARISH": "High Risk Bearish",
    "WEAK_BEARISH": "Weak Bearish",
    "SIDEWAYS_STABLE": "Sideways Stable",
    "UNKNOWN": "Unknown",
}

INSIGHT_MESSAGES = {
    "strong_uptrend": "단기 및 장기 이동평균선이 정배열되어 강력한 상승 추세에 있습니다.",
    "short_uptrend": "단기 상승 추세가 관찰됩니다.",
    "short_downtrend": "단기 약세 추세가 관찰됩니다.",
    "rsi_overbought": "RSI가 70을 초과하여 기술적 과매수 가능성이 관찰됩니다.",
    "rsi_oversold": "RSI가 30 미만으로 단기 과매도 가능성이 관찰됩니다.",
    "high_volatility": "가격 변동성이 높아 리스크 관리가 필요합니다.",
    "concentrated_top1": "단일 자산 비중이 40%를 초과하여 해당 자산 변동성에 포트폴리오가 취약할 수 있습니다.",
    "concentrated_top3": "상위 3개 자산 비중이 높아 포트폴리오가 집중되어 있습니다.",
    "high_hhi": "포트폴리오 집중도(HHI)가 매우 높습니다. 특정 자산에 과도하게 쏠려있어 분산 투자가 필요합니다.",
    "low_hhi": "자산이 이상적으로 다변화되어 있어 개별 종목 리스크가 낮습니다.",
    "high_correlation": "자산 간 상관관계가 높아 분산 효과가 제한될 수 있습니다.",
    "negative_correlation": "일부 자산 쌍은 음의 상관관계를 보여 상호 헤징(Hedging) 수단으로 적합합니다.",
    "type_c_scope": "뉴스/이벤트 데이터의 빈도와 감성 분포를 기준으로 시장 관심도와 단기 센티먼트를 요약했습니다.",
    "unknown": "본 데이터는 표준 투자 데이터 템플릿에 속하지 않는 범용 데이터셋입니다. 기술 통계 및 컬럼 간 상관관계를 바탕으로 탐색적 분석을 권장합니다.",
    "missing_values": "결측치가 있어 일부 지표와 차트 해석에 주의가 필요합니다.",
    "outliers": "이상치가 감지되어 평균, 변동성, 분포 해석이 왜곡될 수 있습니다.",
    "numeric_coverage": "수치형 컬럼이 부족해 정량 분석 범위가 제한됩니다.",
    "unknown_next_steps": "표준 컬럼명을 보강하면 더 구체적인 투자 유형 분석으로 전환할 수 있습니다.",
    "no_signal": "현재 규칙 기준에서 뚜렷한 위험 신호는 제한적입니다.",
}

THRESHOLDS = {
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    "high_volatility": 0.30,
    "top1_weight": 0.40,
    "top3_weight": 0.70,
    "hhi": 0.25,
    "low_hhi": 0.10,
    "avg_correlation": 0.70,
    "negative_correlation": -0.30,
    "feature_trend_change": 0.03,
}

FINANCIAL_FEATURE_KEYWORDS = {
    "amount",
    "assets",
    "close",
    "debt",
    "dividend",
    "eps",
    "equity",
    "factor",
    "growth",
    "high",
    "income",
    "low",
    "margin",
    "momentum",
    "open",
    "price",
    "profit",
    "ratio",
    "return",
    "revenue",
    "risk",
    "roe",
    "sales",
    "score",
    "value",
    "volatility",
    "volume",
    "거래량",
    "매출",
    "수익",
    "수익률",
    "이익",
    "점수",
    "지표",
    "평가금액",
}
