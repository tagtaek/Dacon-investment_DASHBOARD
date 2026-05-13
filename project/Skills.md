# Skills.md - 투자 데이터 자동 분석 및 대시보드 생성 규칙

## 0. 문서 개요

문서 버전: `1.2.0`

본 문서는 투자 데이터 자동 분석 및 대시보드 생성 시스템이 데이터를 해석하고, 분석 지표를 계산하며, 시각화를 선택하고, 자연어 인사이트를 생성하기 위한 규칙 명세서이다.

바이브코딩 과정에서는 코드 생성 기준으로, 완성된 서비스에서는 분석·시각화·인사이트 생성 로직의 기준으로 사용한다.

본 수정본은 실제 구현 안정성을 높이기 위해 데이터 타입 분류 조건, Wide-format 다중 시계열 처리, 수익률 단위 변환, 기술적 지표 예외 처리, 차트 선택 조건, 출력 Schema의 투명성 항목을 보강한다.

---

## 1. Skill의 목적

1. 다양한 투자 데이터 구조를 자동으로 판별한다.
2. 데이터 유형에 따라 적절한 투자 분석 지표를 계산한다.
3. 분석 목적과 데이터 구조에 맞는 시각화 방식을 자동 선택한다.
4. 사용자가 투자 데이터를 직관적으로 이해할 수 있도록 자연어 인사이트를 생성한다.
5. 데이터 구조가 바뀌어도 재사용 가능한 규칙 기반 대시보드 생성 체계를 제공한다.
6. 시스템이 수행한 컬럼 매핑, 단위 변환, 데이터 형식 변환, 계산 불가 지표를 사용자에게 투명하게 표시한다.

---

## 2. 전체 분석 파이프라인

```text
데이터 업로드 → 구조 분석 → 컬럼명 표준화 → 타입 자동 분류 → 품질 진단
→ 공통 전처리 및 단위 보정 → 분석 지표 계산 → 시각화 선택
→ 인사이트 생성 → 레이아웃 구성 → 출력
```

---

## 3. 입력 데이터 기본 원칙

지원 형식: CSV, Excel, JSON, Pandas DataFrame으로 변환 가능한 정형 데이터

시스템은 컬럼명만으로 판단하지 않고, 실제 데이터 값의 형태를 함께 확인한다.

- 값이 날짜 형식이면 날짜 후보 컬럼으로 판단한다.
- 값이 연속적인 숫자이고 시간 순서와 함께 존재하면 가격 후보 컬럼으로 판단한다.
- 값의 합이 1 또는 100에 가까우면 비중 후보 컬럼으로 판단한다.
- `date + ticker + close`처럼 종목 컬럼이 별도로 존재하는 Long-format 다중 시계열을 지원한다.
- `date + AAPL + MSFT + NVDA`처럼 종목명이 컬럼으로 펼쳐진 Wide-format 다중 시계열을 지원한다.
- 자동 변환 또는 추정이 발생한 경우 반드시 `metadata.assumptions`, `metadata.preprocessing_actions`, `data_quality.warning_messages`에 기록한다.

---

## 4. 컬럼명 표준화 규칙

분석 전 모든 컬럼명을 소문자 변환, 앞뒤 공백 제거, 공백·하이픈·슬래시 → 언더스코어 변환, 한글 컬럼명 의미 기반 매핑 순서로 표준화한다.

| 표준 컬럼명 | 매핑 대상 예시 |
|---|---|
| `date` | date, datetime, timestamp, 날짜, 일자, 기준일 |
| `open` | open, opening_price, open_price, 시가 |
| `high` | high, high_price, 최고가, 고가 |
| `low` | low, low_price, 최저가, 저가 |
| `close` | close, adj_close, adjusted_close, price, last_price, 종가, 가격, 현재가 |
| `volume` | volume, trading_volume, 거래량 |
| `ticker` | ticker, symbol, code, asset, stock, 종목, 종목코드 |
| `asset_name` | name, asset_name, stock_name, security_name, 종목명, 자산명 |
| `sector` | sector, industry, category, 섹터, 산업, 업종 |
| `weight` | weight, ratio, allocation, allocation_pct, 비중, 구성비 |
| `value` | value, amount, market_value, 평가금액, 보유금액 |
| `return` | return, daily_return, ret, yield, 수익률, 일간수익률 |
| `sentiment` | sentiment, polarity, sentiment_score, 감성, 감성점수 |
| `event` | event, event_type, disclosure_type, 이벤트, 공시유형 |
| `title` | title, headline, news_title, 제목, 뉴스제목 |
| `text` | text, content, body, article, 기사내용, 본문 |
| `source` | source, publisher, media, 언론사, 출처 |
| `keyword` | keyword, tag, topic, 키워드, 태그 |

컬럼 표준화 결과는 출력 Schema의 `metadata.column_mapping`에 원본 컬럼명과 표준 컬럼명 쌍으로 저장한다.

---

## 5. 데이터 타입 자동 분류

### 5.1 타입 분류 원칙 및 우선순위

타입 분류는 단순 컬럼명 매칭이 아니라 컬럼 조합, 값의 형태, 고유 자산 수, 수치형 컬럼의 의미를 함께 확인하여 수행한다.

```text
Type-D(Long-format) → Type-D(Wide-format) → Type-A → Type-B → Type-C → Unknown
```

단, Type-D는 반드시 가격(`close`) 또는 수익률(`return`) 시계열이 확인되는 경우에만 적용한다. `date + ticker + weight` 또는 `date + asset_name + value`처럼 비중·금액 중심 데이터가 존재하고 `close`/`return` 시계열이 없으면 Type-D가 아니라 Type-B로 분류한다.

`ticker` 컬럼이 없을 경우 기본적으로 단일 종목으로 간주하되, `date`와 2개 이상의 수치형 가격·수익률 후보 컬럼이 있으면 Wide-format Type-D 후보로 판단한다.

복합 구조가 확인되는 경우에는 기본 타입과 보조 타입을 함께 기록한다.

```text
예: date + ticker + close + weight 존재, ticker 2개 이상
→ primary_type = Type-D
→ secondary_type = Type-B 후보
→ assumption = "가격 시계열과 포트폴리오 비중 정보가 함께 존재함"
```

### 5.2 타입 분류 조건

| 타입 | 설명 | 분류 조건 | 필수 컬럼 |
|---|---|---|---|
| **Type-A** | 단일 자산 시계열 | `date + close` 존재, 단일 종목 또는 종목 식별 컬럼 없음 | date, close |
| **Type-B** | 단면 비중/포트폴리오 | 자산 식별 컬럼 + 비중·금액 컬럼 존재. `close`/`return` 시계열이 없거나 분석 목적이 보유 구성일 때 적용 | asset_name 또는 ticker, weight 또는 value |
| **Type-C** | 이벤트/뉴스/감성 | `title`, `text`, `event`, `sentiment` 중 하나 이상 존재 | 없음. 선택적으로 date, ticker, source, keyword |
| **Type-D** | 패널 및 다중 시계열 | Long-format: `date + 자산 식별 컬럼 + close 또는 return` 존재, 고유 자산 2개 이상. Wide-format: `date + 2개 이상 수치형 가격·수익률 후보 컬럼` 존재 | date, ticker 또는 asset_name 또는 2개 이상 자산별 수치형 컬럼, close 또는 return |
| **Unknown** | 분류 불가 | 위 조건 미충족 | - |

### 5.3 Wide-format Type-D 처리 규칙

다음 구조는 Wide-format Type-D 후보로 판단한다.

```text
date | AAPL | MSFT | NVDA
2024-01-01 | 100 | 200 | 300
2024-01-02 | 101 | 198 | 310
```

Wide-format Type-D는 분석 전 Long-format으로 변환한다.

```text
변환 전:
date | AAPL | MSFT | NVDA

변환 후:
date | ticker | close
```

변환 규칙:

1. `date`를 제외한 수치형 컬럼 중 비중·금액·집계값으로 판단되는 컬럼은 제외한다.
2. 컬럼명이 `return`, `ret`, `yield`, `수익률` 등을 포함하거나 값의 범위가 수익률 형태로 보이면 변환 후 값 컬럼명을 `return`으로 둔다.
3. 그 외에는 기본적으로 값 컬럼명을 `close`로 둔다.
4. 변환된 종목명은 원래 컬럼명을 `ticker` 값으로 사용한다.
5. Wide-format 변환 사실은 `metadata.assumptions`와 `metadata.preprocessing_actions`에 기록한다.

### 5.4 Unknown 처리

Unknown은 분석을 중단하지 않고 다음 탐색적 분석을 수행한다.

1. 데이터 샘플 5행 및 컬럼 목록 표시
2. 컬럼별 데이터 타입, 결측치 비율, 고유값 개수 표시
3. 수치형 컬럼 분포 차트, 범주형 컬럼 빈도 차트 생성
4. 후보 타입 제안 후 임시 분석 규칙 선택 안내

후보 타입 제안 규칙:

```text
날짜형 + 가격 후보 수치형 컬럼 존재 → Type-A 후보
자산명 + 비중/금액 컬럼 존재 → Type-B 후보
텍스트/이벤트/감성 + 날짜 컬럼 존재 → Type-C 후보
날짜형 + 자산 식별 + close/return 후보 컬럼 존재 → Type-D(Long-format) 후보
날짜형 + 2개 이상 가격/수익률 후보 수치형 컬럼 존재 → Type-D(Wide-format) 후보
```

## 5.5 Asset Class Detection

시스템은 자산명을 기반으로 자산군(asset class)을 추정할 수 있다.

추정 결과는 `metadata.asset_class`에 기록한다.

지원 자산군:

| Asset Class | 예시 |
|---|---|
| equity | stock, equity, common stock, 주식 |
| etf | ETF, index ETF |
| bond | treasury, bond, 국채, 회사채 |
| commodity | gold, silver, oil, commodity |
| crypto | BTC, ETH, cryptocurrency |
| fx | USDKRW, EURUSD, 환율 |
| macro | CPI, unemployment, interest_rate, treasury_yield |

예시 규칙:

```text
ticker contains "BTC" or "ETH"
→ asset_class = crypto

column contains "yield" or "treasury"
→ asset_class = bond or macro

column contains "CPI" or "interest_rate"
→ asset_class = macro
```

Asset Class는 시각화 및 인사이트 생성에 활용할 수 있다.

---

## 6. 공통 전처리 규칙

### 6.1 기본 전처리 순서

컬럼명 표준화 → 중복 행 제거 → 날짜 컬럼 datetime 변환 → 숫자형 컬럼 변환 → 단위 보정 → Wide-format 변환 여부 확인 → 결측치 비율 계산 → 필수 컬럼 존재 여부 확인 → 품질 경고 생성

### 6.2 숫자형 변환 및 단위 보정

쉼표, 통화 기호, 공백 제거 후 숫자 변환. 퍼센트 기호는 컬럼 용도에 따라 다르게 처리한다.

- 비중 컬럼(`weight`)인 경우: `12.5%` → `0.125`
- 수익률 컬럼(`return`)인 경우: `12.5%` → `0.125`
- 수익률 컬럼에 `%` 기호가 없더라도 절대값 중앙값이 1보다 크고 100 이하이면 퍼센트 단위로 입력된 것으로 추정하여 100으로 나눈다.
- 수익률 컬럼의 절대값 중앙값이 100을 초과하면 자동 변환하지 않고 품질 경고를 생성한다.
- 단위 변환 여부는 `data_quality.warning_messages`, `metadata.assumptions`, `metadata.preprocessing_actions`에 기록한다.

비중 컬럼 범위 판단:

```text
sum(weight)가 0.99~1.01 → 0~1 기준으로 판단
sum(weight)가 99~101 → 100으로 나누어 0~1 기준으로 정규화
그 외 → 정규화 전 warning 생성 후 normalized_weight 계산
```

수익률 및 비중 관련 모든 계산은 기본적으로 0~1 소수 기준을 사용한다.

### 6.3 날짜 처리

`date`는 datetime 형식으로 변환 후 오름차순 정렬한다. 변환 실패 비율이 30% 이상이면 해당 컬럼을 날짜 컬럼으로 사용하지 않는다.

동일 날짜 중복 처리:

- Type-A: 마지막 관측값 사용
- Type-D Long-format: `date + ticker` 기준으로 중복 확인 후 마지막 관측값 사용
- Type-D Wide-format: `date` 기준으로 중복 확인 후 마지막 관측값 사용
- Type-B: 동일 자산 중복 시 `weight` 또는 `value`를 합산하되, 중복 합산 사실을 경고에 기록

데이터 빈도 자동 판별 기준:

- 날짜 간격 중앙값 1일 → 일간 데이터 (연환산 계수 252)
- 날짜 간격 중앙값 7일 → 주간 데이터 (연환산 계수 52)
- 날짜 간격 중앙값 28~31일 → 월간 데이터 (연환산 계수 12)
- 그 외 → 빈도 unknown, 연환산 지표 계산 시 warning 표시

### 6.4 결측치 처리

- 핵심 필수 컬럼 결측치 30% 이상이면 Warning 또는 Risk 출력
- Type-A, Type-D 가격 결측치: forward fill. 시작 구간은 backward fill 허용
- Type-D 수익률 결측치: 기본 보간하지 않고 상관계수·순위 계산 시 관측 가능한 날짜만 사용
- Type-B 비중 결측치: 0으로 대체하지 않고 Unknown 또는 Missing으로 표시
- Type-C 텍스트 결측치: 빈 문자열로 대체하지 않고 결측 상태로 기록

### 6.5 이상치 처리

수익률 평균 ±3표준편차 초과, 가격 0 이하, 거래량 음수인 행은 경고로 표시하되 기본 삭제하지 않고 대시보드에서 강조 표시한다.

가격 0 이하가 발견된 경우 해당 행의 수익률 계산은 제외한다. 거래량 음수는 품질 경고로 기록하고 거래량 기반 인사이트에서 제외한다.

### 6.6 Type-D 패널 정렬 및 상관계수 전처리

Type-D 상관계수 계산 전 모든 자산 수익률은 동일 날짜 기준으로 정렬한다.

Long-format 가격 데이터:

```text
price_panel  = df.pivot(index=date, columns=ticker, values=close)
return_panel = price_panel.pct_change()
```

Long-format 수익률 데이터:

```text
return_panel = df.pivot(index=date, columns=ticker, values=return)
```

Wide-format 데이터는 5.3에 따라 Long-format으로 변환한 후 동일한 방식으로 `return_panel`을 생성한다.

상관계수는 동일 날짜에 관측된 수익률 쌍을 기준으로 계산한다. 공통 관측치 수가 20개 미만인 자산 쌍은 상관계수 표에 표시하되 `correlation warning`을 생성한다.

---

## 7. 공통 투자 지표 계산 (Type-A, Type-D 공통)

가격(`close`)이 있는 경우:

```text
daily_return              = close.pct_change()
valid_return              = daily_return.dropna()
period_count              = count(valid_return)
cumulative_return         = (1 + valid_return).cumprod() - 1
cumulative_return_last    = (1 + valid_return).prod() - 1
annualized_return         = (1 + cumulative_return_last) ^ (N / period_count) - 1
mean_based_annualized_ret = (1 + valid_return.mean()) ^ N - 1  # 보조 지표
annualized_vol            = valid_return.std() * sqrt(N)
running_max               = close.cummax()
MDD                       = (close / running_max - 1).min()
sharpe_ratio              = (annualized_return - risk_free_rate) / annualized_vol
win_rate                  = count(valid_return > 0) / count(valid_return)
```

수익률(`return`)만 있는 경우:

```text
valid_return              = return.dropna()
synthetic_nav             = (1 + valid_return).cumprod()
cumulative_return         = synthetic_nav - 1
cumulative_return_last    = synthetic_nav.iloc[-1] - 1
annualized_return         = (1 + cumulative_return_last) ^ (N / period_count) - 1
annualized_vol            = valid_return.std() * sqrt(N)
running_max               = synthetic_nav.cummax()
MDD                       = (synthetic_nav / running_max - 1).min()
sharpe_ratio              = (annualized_return - risk_free_rate) / annualized_vol
win_rate                  = count(valid_return > 0) / count(valid_return)
```

계산 예외:

- `period_count == 0`이면 수익률 기반 지표를 계산하지 않는다.
- `annualized_vol == 0`이면 Sharpe Ratio는 계산하지 않고 `not_calculated`로 표시한다.
- 빈도(`N`)가 unknown이면 연환산 수익률, 연환산 변동성, Sharpe Ratio 계산 결과에 warning을 부여한다.
- 기본 `risk_free_rate = 0`으로 둔다. 별도 값이 제공되면 해당 값을 사용하고 `metadata.assumptions`에 기록한다.

## 7.1 Additional Risk Metrics

추가 리스크 지표는 데이터 품질 및 기간 조건을 만족할 경우 계산한다.

### Downside Volatility

```text
negative_return = valid_return[valid_return < 0]
downside_volatility = negative_return.std() * sqrt(N)
```

### Historical VaR (95%)

```text
VaR_95 = quantile(valid_return, 0.05)
```

### Rolling Volatility

```text
rolling_volatility_20 =
valid_return.rolling(20).std() * sqrt(N)
```

### Rolling Correlation (Type-D)

```text
rolling_corr =
return_panel[ticker_a].rolling(20).corr(return_panel[ticker_b])
```

추가 리스크 지표는 Risk 카드 또는 하단 보조 차트에 표시할 수 있다.

---

## 8. 타입별 분석 규칙

### 8.1 타입별 분석 목표 및 필수 지표

| 타입 | 분석 목표 | 필수 계산 지표 |
|---|---|---|
| **Type-A** | 단일 자산 가격 흐름, 추세, 변동성, 기술적 지표 | 일간·누적·연환산 수익률, 연환산 변동성, MDD, MA5/20/60, RSI(14), MACD(12/26/9), 거래량 변화율 |
| **Type-B** | 포트폴리오 구성, 집중도, 섹터 노출, 분산 수준 | Top1/Top3 비중, HHI, 섹터별 비중. 위험 기여도는 수익률 패널 또는 공분산 행렬이 있을 때만 계산 |
| **Type-C** | 뉴스·이벤트·감성 흐름 요약. MVP에서는 기본 요약만 제공 | 이벤트 빈도, 감성 분포(긍정/중립/부정 비율), 키워드 빈도 |
| **Type-D** | 다중 자산 수익률·변동성·상관관계 비교 | 자산별 섹션 7 지표 전부, 상관계수 행렬, 수익률·변동성 순위, 공통 관측치 수 |

### 8.2 기술적 지표 계산 (Type-A)

**이동평균선**

```text
MA_n = close.rolling(window=n).mean()   # n = 5, 20, 60
```

**골든크로스/데드크로스 판정**

```text
골든크로스 = previous_MA20 <= previous_MA60 and current_MA20 > current_MA60
데드크로스 = previous_MA20 >= previous_MA60 and current_MA20 < current_MA60
```

**RSI (14일)**

```text
change = close.diff()
gain   = change.clip(lower=0).rolling(14).mean()
loss   = change.clip(upper=0).abs().rolling(14).mean()
RS     = gain / loss
RSI    = 100 - (100 / (1 + RS))

if loss == 0 and gain > 0: RSI = 100
if loss == 0 and gain == 0: RSI = 50
```

| RSI 구간 | 해석 |
|---|---|
| >= 70 | 과매수 가능성 |
| <= 30 | 과매도 가능성 |
| 30 < RSI < 70 | 중립 |

**MACD (12/26/9)**

```text
EMA12     = close.ewm(span=12, adjust=False).mean()
EMA26     = close.ewm(span=26, adjust=False).mean()
MACD      = EMA12 - EMA26
Signal    = MACD.ewm(span=9, adjust=False).mean()
Histogram = MACD - Signal
```

**변동성 상태 분류**

| 연환산 변동성 | 상태 |
|---|---|
| < 0.15 | Low |
| 0.15 ~ 0.30 | Normal |
| >= 0.30 | High |

### 8.3 Type-B 집중도 및 위험 기여도 계산

```text
weight_i (value만 있는 경우) = value_i / sum(value_i)
normalized_weight_i          = weight_i / sum(weight_i)
top1_weight                  = max(normalized_weight)
top3_weight                  = sum(top 3 normalized_weight)
HHI                          = sum(normalized_weight_i ^ 2)
sector_weight                = groupby(sector).sum(normalized_weight)
```

위험 기여도는 자산별 수익률 시계열 또는 공분산 행렬이 제공된 경우에만 계산한다.

```text
portfolio_variance           = w.T * Cov * w
marginal_risk_i              = (Cov * w)_i
risk_contribution_i          = weight_i * marginal_risk_i / portfolio_variance
```

수익률 데이터나 공분산 행렬이 없는 Type-B 데이터에서는 위험 기여도를 계산하지 않는다. 이 경우 `risk_contribution`은 `not_calculated`로 표시하고, 대신 비중 기반 집중도 지표인 Top1, Top3, HHI, sector_weight를 제공한다.

| 조건 | 해석 |
|---|---|
| top1_weight >= 0.40 | 단일 자산 집중 위험 |
| top3_weight >= 0.70 | 상위 자산 집중 위험 |
| HHI >= 0.25 | 집중도 높음 |
| HHI < 0.10 | 분산도 높음 |
| sector_weight >= 0.50 | 섹터 집중 경고 |

### 8.4 Type-C 감성 해석 기준

| 범위 | 긍정 | 중립 | 부정 |
|---|---|---|---|
| -1 ~ 1 | >= 0.2 | -0.2 ~ 0.2 | <= -0.2 |
| 0 ~ 100 | >= 60 | 40 ~ 60 | <= 40 |

Type-C는 MVP에서 기본 요약 기능으로만 제공한다. 외부 뉴스·공시 API 연동, 가격 변동과 이벤트의 인과 해석, 정교한 자연어 감성 분석은 확장 기능으로 둔다.

### 8.5 Type-D 상관계수 해석

```text
return_panel       = date를 index로, ticker를 columns로 정렬한 수익률 패널
observation_count  = 각 자산 쌍의 공통 관측치 수
correlation_matrix = return_panel.corr(min_periods=20)
```

공통 관측치 수가 20개 미만인 자산 쌍은 상관계수 값을 해석하지 않고 warning을 표시한다.

| 조건 | 해석 |
|---|---|
| corr >= 0.70 | 높은 양의 상관관계 |
| 0.30 <= corr < 0.70 | 보통 수준의 양의 상관관계 |
| -0.30 < corr < 0.30 | 낮은 상관관계 |
| corr <= -0.30 | 분산 효과 가능성 |


## 8.6 Macro and Yield Data Interpretation

금리, 환율, CPI, 실업률 등 거시경제 데이터는 일반 주가 데이터와 다른 방식으로 해석한다.

Macro/Yield 후보 조건:

```text
column name contains:
yield, treasury, rate, cpi, inflation,
interest_rate, unemployment, exchange_rate
```

Macro/Yield 데이터에서는 다음 규칙을 적용한다.

- RSI, MACD와 같은 기술적 지표는 기본적으로 계산하지 않는다.
- 이동평균(MA)은 추세 확인 용도로만 사용한다.
- 변동성 및 변화율 중심으로 해석한다.
- YoY 또는 MoM 계산이 가능하면 우선 제공한다.

예시 인사이트:

| 조건 | 레벨 | 메시지 |
|---|---|---|
| 금리 급등 | Warning | 금리 상승 흐름이 관찰됩니다. |
| CPI 상승률 확대 | Warning | 인플레이션 압력이 확대될 가능성이 있습니다. |
| 환율 변동성 확대 | Warning | 환율 변동성이 높아졌습니다. |
| 장기 안정 구간 | Info | 비교적 안정적인 흐름이 관찰됩니다. |

---

## 9. 타입별 시각화 및 레이아웃

### 9.1 차트 자동 선택 매트릭스

캔들스틱 차트는 `open`, `high`, `low`, `close`가 모두 존재할 때만 선택한다. 변동성이 높더라도 OHLC 컬럼이 없으면 캔들스틱을 선택하지 않는다.

| 데이터 조건 | 우선 차트 | 보조 차트 |
|---|---|---|
| 단일 시계열 + close만 | Line Chart | MA Overlay |
| 단일 시계열 + OHLC | Candlestick Chart | Volume Bar |
| High Volatility + OHLC | Candlestick Chart | RSI/MACD |
| High Volatility + close만 | Line Chart | Drawdown Chart 또는 Volatility Band |
| volume 존재 | Bar Chart | Volume MA |
| 포트폴리오 자산 <= 10 | Donut Chart | Table |
| 포트폴리오 자산 > 10 | Horizontal Bar Chart | Treemap |
| sector + asset 계층 | Sunburst Chart | Treemap |
| 다중 종목 시계열 | Multi-Line Chart | Rank Table |
| 상관계수 행렬 | Heatmap | Correlation Table |
| 수익률 + 변동성 | Risk-Return Scatter Plot | Quadrant Analysis |
| 이벤트/뉴스 | Timeline Chart | Sentiment Bar |
| 분류 불가 | Summary Table | Histogram |

차트 개수 기준: 메인 1개, 보조 2~4개, 요약 테이블 1~2개, 인사이트 카드 3~6개.

### 9.2 타입별 레이아웃

| 타입 | 상단 | 중단 | 하단 |
|---|---|---|---|
| **Type-A** | 종가 라인 또는 캔들스틱 | 누적 수익률, 변동성, MDD, RSI KPI | 거래량, RSI, MACD 차트 |
| **Type-B** | 도넛 또는 Sunburst | Top1 비중, Top3 비중, HHI, 자산 수 KPI | 섹터별 차트, 비중 테이블, 위험 기여도(계산 가능 시) |
| **Type-C** | 이벤트 타임라인 또는 빈도 차트 | 긍정/중립/부정 비율 KPI | 키워드 빈도 테이블, 종목별 이벤트 차트 |
| **Type-D** | 누적 수익률 Multi-Line | 수익률·변동성·MDD 순위 KPI | Correlation Heatmap, Scatter Plot, Rank Table |
| **Unknown** | 데이터 구조 요약 | 컬럼 타입, 결측치 비율, 고유값 수 | 분포 차트, 빈도 차트, 후보 타입 제안 |

모든 타입 하단/우측에는 자연어 인사이트 카드를 표시한다.

## 9.3 Dashboard Priority Rules

시스템은 모든 차트를 동시에 출력하지 않고,
데이터 구조와 분석 목적에 따라 우선순위를 조정한다.

우선순위 규칙:

```text
IF Type-A and OHLC exists:
    prioritize candlestick chart

IF Type-D and asset_count >= 5:
    prioritize correlation heatmap

IF Type-B and sector exists:
    prioritize sector exposure chart

IF volatility is high:
    prioritize drawdown and volatility charts

IF data quality is low:
    prioritize warning cards and summary tables
```

차트 수가 많을 경우 핵심 차트를 우선 표시하고,
나머지는 접기(expandable section) 형태로 제공할 수 있다.

---

## 10. 자연어 인사이트 생성 규칙

### 10.1 인사이트 원칙 및 투자 안전 원칙

인사이트는 데이터 기반 관찰 결과로만 작성하며, 투자 자문·매매 추천·확정적 예측은 절대 사용하지 않는다.

| 금지 표현 | 허용 표현 |
|---|---|
| 매수/매도해야 합니다 | 상승/약세 흐름이 관찰됩니다 |
| 수익이 보장됩니다 | 변동성이 확대되었습니다 |
| 앞으로 상승할 것입니다 | 추가 확인이 필요합니다 |
| 반드시 투자하세요 | 데이터상 특정 패턴이 확인됩니다 |

### 10.2 인사이트 카드 형식

```text
제목: 핵심 이슈 요약
레벨: Positive | Info | Neutral | Warning | Risk
근거 수치: 계산된 지표 값
해석: 자연어 설명
확인 항목: 사용자가 추가로 살펴볼 항목
```

인사이트 우선순위: `Risk > Warning > Positive > Info > Neutral`
동일 레벨 내에서는 근거 수치의 절대값이 큰 항목을 우선 표시한다.

### 10.3 타입별 인사이트 생성 조건

| 타입 | 조건 | 레벨 | 메시지 |
|---|---|---|---|
| **A** | 최근 종가 > MA20 | Positive | 단기 이동평균선보다 높은 가격 흐름이 관찰됩니다. |
| **A** | 최근 종가 < MA20 | Warning | 단기 이동평균선보다 낮은 가격 흐름이 관찰됩니다. |
| **A** | previous_MA20 <= previous_MA60 and current_MA20 > current_MA60 | Positive | 중기 골든크로스 가능성이 관찰됩니다. |
| **A** | previous_MA20 >= previous_MA60 and current_MA20 < current_MA60 | Warning | 중기 데드크로스 가능성이 관찰됩니다. |
| **A** | RSI >= 70 | Warning | RSI 기준 과매수 가능성이 관찰됩니다. |
| **A** | RSI <= 30 | Info | RSI 기준 과매도 가능성이 관찰됩니다. |
| **A** | MDD <= -0.20 | Risk | 최근 분석 구간에서 큰 낙폭이 발생했습니다. |
| **A** | annualized_vol >= 0.30 | Warning | 연환산 변동성이 높은 수준으로 관찰됩니다. |
| **A** | 거래량 최근 20일 평균의 2배 이상 | Info | 거래량 급증이 관찰됩니다. |
| **B** | top1_weight >= 0.40 | Risk | 단일 자산 쏠림이 관찰됩니다. |
| **B** | top3_weight >= 0.70 | Warning | 상위 3개 자산 집중 포트폴리오입니다. |
| **B** | HHI >= 0.25 | Warning | 포트폴리오 집중도가 높은 수준입니다. |
| **B** | HHI < 0.10 | Positive | 자산이 비교적 고르게 분산되어 있습니다. |
| **B** | sector_weight >= 0.50 | Warning | 특정 섹터 노출도가 높게 나타납니다. |
| **B** | risk_contribution == not_calculated | Info | 수익률 또는 공분산 데이터가 없어 위험 기여도는 계산하지 않았습니다. |
| **C** | 부정 감성 비율 >= 0.50 | Warning | 부정적 감성 비중이 높게 관찰됩니다. |
| **C** | 긍정 감성 비율 >= 0.50 | Positive | 긍정적 감성 비중이 높게 관찰됩니다. |
| **C** | 특정 날짜 이벤트 급증 | Info | 특정 시점에 이벤트 발생 빈도가 증가했습니다. |
| **D** | 특정 자산 누적 수익률 최고 | Positive | 분석 기간 동안 가장 높은 누적 수익률을 기록한 자산이 확인됩니다. |
| **D** | 특정 자산 MDD 최대 | Risk | 특정 자산에서 가장 큰 낙폭이 관찰됩니다. |
| **D** | corr >= 0.70인 자산 쌍 | Warning | 일부 자산 간 높은 상관관계로 분산 효과가 제한될 수 있습니다. |
| **D** | corr <= -0.30인 자산 쌍 | Info | 일부 자산 간 음의 상관관계로 분산 효과 가능성이 있습니다. |
| **D** | 공통 관측치 수 < 20인 자산 쌍 | Warning | 일부 자산 쌍은 공통 관측치가 부족해 상관계수 해석에 주의가 필요합니다. |
| **D** | 고수익·고변동성 자산 | Warning | 높은 수익률과 높은 변동성을 동시에 보이는 자산이 있습니다. |
| **D** | 저수익·고변동성 자산 | Risk | 위험 대비 성과가 낮은 자산이 관찰됩니다. |


## 10.4 Market Regime Analysis

시스템은 수익률과 변동성을 기반으로 시장 상태(Market Regime)를 추정할 수 있다.

Regime 판별 기준:

| 조건 | Regime |
|---|---|
| cumulative_return > 0 and annualized_vol < 0.15 | Stable Bullish |
| cumulative_return > 0 and annualized_vol >= 0.30 | Volatile Bullish |
| cumulative_return < 0 and annualized_vol >= 0.30 | High Risk Bearish |
| cumulative_return < 0 and annualized_vol < 0.15 | Weak Bearish |
| abs(cumulative_return) < 0.05 and annualized_vol < 0.15 | Sideways Stable |

Regime 결과는 다음 위치에 표시한다.

```text
metadata.market_regime
```

예시 인사이트:

| Regime | 메시지 |
|---|---|
| Stable Bullish | 안정적인 상승 흐름이 관찰됩니다. |
| Volatile Bullish | 상승 흐름과 함께 높은 변동성이 관찰됩니다. |
| High Risk Bearish | 높은 변동성을 동반한 약세 흐름이 관찰됩니다. |
| Sideways Stable | 방향성이 제한된 횡보 구간으로 해석될 수 있습니다. |


---


## 11. 데이터 품질 진단

| 조건 | 품질 레벨 |
|---|---|
| 필수 컬럼 존재, 결측치 10% 미만 | Good |
| 필수 컬럼 존재, 결측치 10~30% | Warning |
| 필수 컬럼 결측치 30% 이상 | Risk |
| 필수 컬럼 누락 | Invalid |

진단 항목:

- 전체 행/컬럼 수
- 컬럼별 결측치 비율
- 중복 행 수
- 날짜·숫자형 변환 성공률
- 이상치 개수
- 수익률·비중 단위 자동 변환 여부
- Wide-format → Long-format 변환 여부
- Type-D 상관계수 계산 시 공통 관측치 수 부족 여부
- 계산 불가 지표 목록

품질 문제는 숨기지 않고 `data_quality.warning_messages`와 인사이트 카드에 표시한다.

---

## 12. 출력 Schema

```json
{
  "metadata": {
    "skill_version": "1.1.0",
    "detected_frequency": "daily | weekly | monthly | unknown",
    "date_range": {
      "start": "",
      "end": ""
    },
    "data_format": "long | wide | unknown",
    "primary_type": "Type-A | Type-B | Type-C | Type-D | Unknown",
    "secondary_type": "Type-A | Type-B | Type-C | Type-D | null",
    "column_mapping": [
      { "original_column": "원본 컬럼명", "standard_column": "표준 컬럼명" }
    ],
    "assumptions": [
      "return 컬럼은 퍼센트 단위로 추정되어 100으로 나누어 변환됨"
    ],
    "preprocessing_actions": [
      "Wide-format 다중 시계열을 Long-format으로 변환함"
    ]
  },
  "data_type": "Type-A | Type-B | Type-C | Type-D | Unknown",
  "data_quality": {
    "row_count": 0,
    "column_count": 0,
    "missing_rate": 0.0,
    "quality_level": "Good | Warning | Risk | Invalid",
    "warning_messages": []
  },
  "indicators": [
    {
      "name": "annualized_volatility",
      "value": 0.0,
      "unit": "%",
      "description": "연환산 변동성",
      "calculation_status": "calculated | not_calculated | warning",
      "reason": "계산 불가 또는 경고 사유"
    }
  ],
  "charts": [
    {
      "chart_type": "candlestick | line | donut | heatmap | scatter | table | histogram",
      "title": "차트 제목",
      "x": "date",
      "y": ["close"],
      "reason": "차트 선택 이유"
    }
  ],
  "insights": [
    {
      "title": "인사이트 제목",
      "level": "Positive | Info | Neutral | Warning | Risk",
      "message": "자연어 인사이트 메시지",
      "evidence": "근거 수치",
      "check_point": "추가 확인 항목"
    }
  ],
  "layout": {
    "top": [],
    "middle": [],
    "bottom": [],
    "side": []
  }
}
```

---

## 13. 바이브코딩 구현 지침

```text
data_loader.py      : 파일 업로드 및 DataFrame 변환
schema_detector.py  : 컬럼 표준화, Wide-format 감지, 데이터 타입 분류
preprocessor.py     : 결측치, 숫자형, 날짜형, 단위 보정 전처리
indicators.py       : 투자 지표 계산
visualizer.py       : 차트 생성
insight_engine.py   : 자연어 인사이트 생성
dashboard.py        : UI 레이아웃 구성
```

MVP 구현 우선순위:

```text
Type-A → Type-B → Unknown 예외 처리 → Type-D → Type-C 기본 요약
```

MVP 범위:

- 필수 구현: Type-A, Type-B, Unknown 기본 진단
- 선택 구현: Type-D
- 확장 구현: Type-C

```python
def standardize_columns(df): ...       # 원본 컬럼명과 표준 컬럼명 매핑 생성
def detect_data_type(df): ...          # 컬럼 구조와 값 형태 기반 Type 판별
def detect_frequency(df): ...          # 날짜 간격 기반 빈도 판별
def normalize_wide_format(df): ...     # Wide-format Type-D를 Long-format으로 변환
def preprocess_units(df): ...          # 비중·수익률 단위 보정 및 assumption 기록
def calculate_indicators(df, data_type): ...  # 데이터 타입별 투자 지표 계산
def select_charts(df, indicators, data_type): ...  # 차트 선택. OHLC 없으면 캔들스틱 제외
def generate_insights(indicators, data_type): ...  # 자연어 인사이트 생성
def build_dashboard(df, indicators, charts, insights): ...  # 대시보드 구성
```

---

## 14. 확장 기능 (향후 로드맵)

- **뉴스·공시 연동**: 종목별 뉴스 API 연동, 가격 변동과 이벤트 시점 시각화
- **실시간 데이터**: 주기적 지표 재계산, 급등락 알림
- **리포트 추출**: PDF/이미지 저장, 핵심 지표·차트·인사이트 요약 리포트
- **복합 타입 분석**: Type-A + C (이벤트 기반 가격 분석), Type-B + D (포트폴리오 구성 + 성과 분석)
- **사용자 설정형 위험 기준**: 변동성, MDD, 집중도 임계값을 사용자 또는 기관 기준에 맞게 조정

---

## 15. 최종 출력 원칙 및 면책 고지

대시보드는 다음 기준을 만족해야 한다.

1. 데이터 타입 판별 결과가 명확히 표시되어야 한다.
2. 핵심 지표가 카드 형태로 요약되어야 한다.
3. 차트 선택 이유가 설명되어야 한다.
4. 인사이트는 근거 수치와 함께 제공되어야 한다.
5. 예외 또는 데이터 품질 문제는 숨기지 않고 표시해야 한다.
6. 모든 투자 해석은 데이터 기반 관찰 표현으로 작성해야 한다.
7. 시스템이 추정한 단위 변환, 컬럼 매핑, Wide-format 변환, 계산 불가 지표는 사용자에게 표시해야 한다.

대시보드 하단 고정 문구:

```text
본 대시보드는 업로드된 데이터에 기반한 분석 결과를 제공하며, 투자 자문 또는 매매 추천을 의미하지 않습니다.
실제 투자 판단은 추가적인 정보와 리스크 검토를 바탕으로 이루어져야 합니다.
```
