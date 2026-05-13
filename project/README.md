# Skills Financial Investment Dashboard Generator

React + FastAPI 기반의 로컬 CSV 투자 분석 대시보드입니다. `project/Skills.md` v1.2.0을 제품 규칙의 단일 기준으로 사용하며, 해커톤 데모에 필요한 안정적인 MVP 범위만 구현합니다. 외부 유료 API, 로그인, 데이터베이스는 사용하지 않습니다.

## Architecture

- Backend: FastAPI, pandas 기반 CSV 업로드 및 규칙 기반 분석
- Frontend: React + Vite, Recharts 기반 대시보드 렌더링
- API: 기존 `POST /analyze` endpoint 유지
- Data flow: CSV upload → column alias standardization → preprocessing → type detection → indicators/charts/insights/metadata JSON → dashboard rendering

## Skills.md Usage

백엔드는 `project/Skills.md`의 규칙을 다음 범위에서 반영합니다.

- 컬럼 alias mapping 및 `metadata.column_mapping`
- 날짜/숫자/퍼센트 정규화와 전처리 기록
- Type-A, Type-B, Type-D, Type-C, Unknown 감지 우선순위
- Type-A 위험/기술 지표, Type-B 집중도, Type-D 부분 비교 분석, Unknown 탐색 분석
- `metadata.assumptions`, `metadata.preprocessing_actions`, `metadata.warning_messages`, `metadata.asset_class`, `metadata.market_regime`
- `data_quality` 경고와 상태 표시

## Supported Data Types

| Type | Status | Detection | Analytics |
|---|---|---|---|
| Type-A | MVP supported | `date + close` | close/MA, OHLC candlestick when available, return, cumulative return, volatility, VaR(95), downside volatility, rolling volatility, MDD, RSI, MACD |
| Type-B | MVP supported | `ticker`/`asset_name` + `weight` or `value` | normalized weights, Top1/Top3, HHI, sector exposure when available |
| Type-D | Partially supported | `date + ticker + close/return` or wide multi-asset columns | cumulative return comparison, correlation heatmap, risk-return scatter |
| Type-C | Planned | text/event/sentiment columns | planned/partially supported summary only |
| Unknown | MVP fallback | no supported required column combination | row/column profile, column types, missing values, numeric summaries, histograms, correlation heatmap, candidate type suggestion |

Asset class detection covers `equity`, `etf`, `bond`, `crypto`, and `macro` keyword evidence. Market regime is estimated from cumulative return and annualized volatility when a return series is available.

## Run Backend

```bash
cd project/backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

API:

- `GET /health`
- `POST /analyze`
- form-data field: `file`

The frontend API URL is intentionally unchanged: `http://163.180.117.216:8000/analyze`.

## Run Frontend

```bash
cd project/frontend
npm install
npm run dev
```

Default Vite URL: `http://localhost:5173`.

## Sample CSVs

Sample files are in `project/sample_data`.

- `type_a_stock.csv`: Type-A OHLCV stock time series
- `type_b_portfolio.csv`: Type-B portfolio weights with sector exposure
- `type_d_multi_asset.csv`: partial Type-D multi-asset price panel in long format
- `macro_interest_rate.csv`: macro/yield-style Unknown fallback with macro asset class evidence
- `unknown_sample.csv`: generic fallback data with missing values and numeric columns

## Validation

Static checks used for this MVP:

```bash
python -m py_compile project/backend/*.py
cd project/frontend
npm run build
```

Build artifacts such as `frontend/dist` and backend `__pycache__` should be removed after validation when preparing a clean submission.

## Screenshots

Add screenshots here for the final hackathon submission:

- Type-A OHLC dashboard
- Type-B portfolio concentration dashboard
- Type-D multi-asset comparison dashboard
- Unknown fallback dashboard
