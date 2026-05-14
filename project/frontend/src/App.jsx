import React from 'react';
import { useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts';

const API_URL = 'https://dacon-investment-dashboard.onrender.com/analyze';
const COLORS = ['#168a71', '#2563eb', '#f59e0b', '#dc2626', '#7c3aed', '#0f766e', '#be123c', '#4b5563'];

function App() {
  const [file, setFile] = useState(null);
  const [analyzedFileName, setAnalyzedFileName] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const warningMessages = result?.data_quality?.warning_messages ?? [];
  const normalizedIndicators = result ? normalizeIndicators(result.indicator_cards ?? result.indicators ?? []) : [];
  const orderedCharts = result ? orderReportCharts((result.charts ?? []).filter(hasRenderableChart), result.data_type) : [];
  const mainChart = result ? pickReportMainChart(orderedCharts, result.data_type) : null;
  const supportingCharts = result ? orderedCharts.filter((chart) => chart !== mainChart && (chart.chart_type ?? chart.type) !== 'table') : [];

  async function handleSubmit(event) {
    event.preventDefault();
    if (!file) {
      setError('CSV 파일을 선택해 주세요.');
      return;
    }

    setLoading(true);
    setError('');
    setResult(null);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch(API_URL, {
        method: 'POST',
        body: formData,
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || '분석 요청에 실패했습니다.');
      }
      setAnalyzedFileName(file.name);
      setResult(payload);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="app-shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">Skills 기반 대시보드</p>
          <h1>금융 투자 대시보드 생성기</h1>
        </div>
        <form className="upload-form" onSubmit={handleSubmit}>
          <label className="file-picker">
            <span>{file ? file.name : 'CSV 선택'}</span>
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <button type="submit" disabled={loading}>
            {loading ? '분석 중' : '분석 시작'}
          </button>
        </form>
      </section>

      {loading && <div className="notice loading">CSV를 분석하고 대시보드 지표를 계산하는 중입니다.</div>}
      {error && <div className="notice error">{error}</div>}

      {!result && !error && !loading && (
        <section className="empty-state">
          <div className="empty-panel">
            <strong>CSV 업로드 대기 중</strong>
            <span>CSV를 업로드하면 핵심 인사이트, 주요 지표, 우선 차트를 먼저 보여줍니다.</span>
          </div>
        </section>
      )}

      {result && (
        <section className={`dashboard-grid ${reportTypeClass(result.data_type)}`}>
          <InsightGrid insights={result.insights ?? []} dataType={result.data_type} />
          <DashboardSection title="핵심 지표" subtitle="감지된 데이터 유형에 맞춰 우선 확인해야 할 투자 지표를 4~6개로 압축했습니다.">
            <ReportKpiGrid result={result} indicators={normalizedIndicators} charts={orderedCharts} />
          </DashboardSection>
          <ReportMainVisualization chart={mainChart} result={result} />
          <ReportSupportingCharts charts={supportingCharts} result={result} />
          <ReportSupportingTables result={result} charts={orderedCharts} indicators={normalizedIndicators} />
          <ReportDataSummary result={result} fileName={analyzedFileName} indicators={normalizedIndicators} />
          <ReportDetectedType result={result} />
          {result.data_type === 'Unknown' && <ReportCandidateType result={result} />}
          <ReportAppliedRules result={result} charts={orderedCharts} indicators={normalizedIndicators} />
          <ReportDataQuality result={result} warnings={warningMessages} />
          <ReportPipeline />
          <ReportMetadataTransparency result={result} charts={orderedCharts} indicators={normalizedIndicators} />
          <ReportRawPreview rows={result.preview_rows ?? []} />
        </section>
      )}
    </main>
  );
}

function KeySummaryPanel({ result, warnings }) {
  const indicators = normalizeIndicators(result.indicator_cards ?? result.indicators ?? []);
  const keyMetric = pickKeyMetric(result.data_type, indicators, result.metadata ?? {});
  const qualityStatus = result.data_quality?.quality_level ?? result.data_quality?.status ?? 'Good';
  const missingRate = result.data_quality?.missing_rate ?? result.data_quality?.missing_ratio ?? 0;
  const marketRegime = getMarketRegime(result.metadata?.market_regime);
  const assetClass = getAssetClass(result.metadata?.asset_class);

  return (
    <section className="key-summary-grid">
      <article className="card key-summary-card">
        <span className="card-label">감지된 유형</span>
        <strong>{result.data_type}</strong>
        <div className="badge-row">
          {assetClass && <span className="type-badge">{assetClass}</span>}
          {marketRegime && <span className={`regime-badge ${badgeClass(marketRegime)}`}>{marketRegime}</span>}
        </div>
        <p>{result.metadata?.secondary_type ? `Secondary: ${result.metadata.secondary_type}` : result.metadata?.detection_reason}</p>
      </article>
      <article className="card key-summary-card">
        <span className="card-label">핵심 지표</span>
        <strong>{keyMetric ? formatValue(keyMetric.value, keyMetric.format) : '-'}</strong>
        <p>{keyMetric?.name ?? '계산된 핵심 지표 없음'}</p>
      </article>
      <article className={`card key-summary-card quality ${qualityStatus.toLowerCase()}`}>
        <span className="card-label">데이터 품질</span>
        <strong>{qualityStatus}</strong>
        <p>결측률 {formatValue(missingRate, 'percent')} · 경고 {formatInteger(warnings.length)}개</p>
      </article>
    </section>
  );
}

function WarningPanel({ warnings }) {
  if (!warnings?.length) return null;
  return (
    <section className="warning-strip">
      {warnings.slice(0, 4).map((warning) => (
        <article className="card warning-card" key={warning}>
          <span className="card-label">Warning</span>
          <p>{warning}</p>
        </article>
      ))}
    </section>
  );
}

function DashboardSection({ title, subtitle, children }) {
  return (
    <section className="dashboard-section">
      <SectionHeader title={title} subtitle={subtitle} />
      {children}
    </section>
  );
}

function SectionHeader({ title, subtitle }) {
  return (
    <div className="section-heading">
      <h2>{title}</h2>
      {subtitle && <p>{subtitle}</p>}
    </div>
  );
}

function ReportPipeline() {
  return (
    <section className="card process-card">
      <details>
        <summary>
          <strong>분석 과정</strong>
          <small>Skills.md 기준으로 수행된 자동 분석 흐름입니다.</small>
        </summary>
        <div className="pipeline-ribbon" aria-label="Skills.md 분석 과정">
          {['데이터 구조 해석', '규칙 기반 분석', '시각화 선택', '인사이트 생성', '투명한 출력'].map((step, index) => (
            <div className="pipeline-step" key={step}>
              <span>{index + 1}</span>
              <strong>{step}</strong>
            </div>
          ))}
        </div>
      </details>
    </section>
  );
}

function ReportDataSummary({ result, fileName, indicators }) {
  const metadata = result.metadata ?? {};
  const quality = result.data_quality ?? {};
  const dateRange = metadata.date_range
    ? `${metadata.date_range.start ?? '-'} ~ ${metadata.date_range.end ?? '-'}`
    : getReportIndicatorValue(indicators, ['date range']) ?? '-';
  const usedColumns = metadata.columns ?? metadata.original_columns ?? [];
  const rows = [
    { label: '파일명', value: fileName || '-' },
    { label: '감지된 유형', value: metadata.primary_type || result.data_type || '-' },
    { label: '자산군', value: getAssetClass(metadata.asset_class) || '-' },
    { label: '분석 기간', value: dateRange },
    { label: '행/열 수', value: `${formatInteger(quality.row_count ?? metadata.row_count)} / ${formatInteger(quality.column_count ?? metadata.column_count)}` },
    { label: '데이터 빈도', value: metadata.detected_frequency || 'unknown' },
    { label: '사용 컬럼', value: formatReportList(usedColumns, 12) },
    { label: '분석 목적', value: reportAnalysisObjective(result.data_type, metadata) },
  ];

  return (
    <section className="card data-summary-card">
      <div className="summary-copy">
        <span className="card-label">데이터 요약</span>
        <h2>{reportDatasetSentence(result.data_type, metadata)}</h2>
        <p>{reportAnalysisObjective(result.data_type, metadata)}</p>
      </div>
      <div className="summary-grid">
        {rows.map((row) => (
          <div className="summary-item" key={row.label}>
            <span>{row.label}</span>
            <strong>{row.value}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function ReportDetectedType({ result }) {
  const metadata = result.metadata ?? {};
  const assetClass = metadata.asset_class ?? {};
  const regime = metadata.market_regime ?? {};
  const rows = [
    { item: '주요 유형', value: metadata.primary_type || result.data_type || '-', detail: metadata.detection_reason || '-' },
    { item: '보조 유형', value: metadata.secondary_type || '-', detail: '복합 데이터 구조가 감지될 때 함께 기록됩니다.' },
    { item: '데이터 형식', value: metadata.data_format || '-', detail: 'long, wide, snapshot, event, unknown 중 하나로 기록됩니다.' },
    { item: '자산군', value: getAssetClass(assetClass) || '-', detail: formatObject(assetClass.evidence) },
    { item: '시장 국면', value: getMarketRegime(regime) || '-', detail: regime.evidence || regime.message || '-' },
  ];

  return (
    <DashboardSection title="데이터 유형 및 자산군" subtitle="Skills.md의 유형 감지 규칙에 따라 데이터 구조와 자산군을 정리했습니다.">
      <DataTable rows={rows} columns={['item', 'value', 'detail']} />
    </DashboardSection>
  );
}

function ReportDataQuality({ result, warnings }) {
  const quality = result.data_quality ?? {};
  const metadata = result.metadata ?? {};
  const qualityLevel = quality.quality_level ?? quality.status ?? 'Good';
  const cards = [
    { label: '품질 수준', value: qualityLevel, detail: `경고 메시지 ${formatInteger(warnings.length)}개` },
    { label: '결측률', value: formatValue(quality.missing_rate ?? quality.missing_ratio ?? 0, 'percent'), detail: `결측 셀 ${formatInteger(quality.missing_cell_count ?? 0)}개` },
    { label: '중복 행', value: formatInteger(metadata.duplicate_row_count ?? 0), detail: '중복 처리 내역은 메타데이터에 기록됩니다.' },
    { label: '이상치', value: formatInteger(quality.outlier_count ?? quality.outliers_count ?? 0), detail: formatObject(metadata.outliers) },
  ];

  return (
    <DashboardSection title="데이터 품질" subtitle="결측치, 중복, 이상치, 전처리 경고를 보조 정보로 확인합니다.">
      <div className="quality-grid">
        {cards.map((item) => (
          <article className={`card quality-card ${badgeClass(String(item.value))}`} key={item.label}>
            <span className="card-label">{item.label}</span>
            <strong>{item.value}</strong>
            <p>{item.detail}</p>
          </article>
        ))}
      </div>
      {warnings.length > 0 && (
        <div className="warning-list">
          {warnings.slice(0, 6).map((warning) => (
            <article className="warning-row" key={warning}>{warning}</article>
          ))}
        </div>
      )}
    </DashboardSection>
  );
}

function ReportCandidateType({ result }) {
  const candidate = result.metadata?.candidate_data_type ?? {};
  return (
    <DashboardSection title="후보 데이터 유형" subtitle="분류가 어려운 데이터는 탐색 분석을 유지하고 가능한 유형을 함께 제안합니다.">
      <article className="card candidate-card">
        <span className="card-label">후보 유형</span>
        <strong>{candidate.suggested_type || 'Unknown'}</strong>
        <p>{candidate.reason || result.metadata?.detection_reason || '-'}</p>
        <small>신뢰도: {candidate.confidence || 'low'}</small>
      </article>
    </DashboardSection>
  );
}

function ReportAppliedRules({ result, charts, indicators }) {
  const metadata = result.metadata ?? {};
  const calculated = indicators.filter(reportIsCalculatedIndicator).map((item) => item.name);
  const notCalculated = indicators.filter((item) => item.calculation_status === 'not_calculated').map((item) => item.name);
  const mainChart = pickReportMainChart(charts, result.data_type);
  const mainContext = mainChart ? getReportChartContext(mainChart, result) : null;
  const rows = [
    {
      rule: '유형 감지',
      applied: metadata.detection_reason || `감지된 컬럼과 값의 구조를 기준으로 ${result.data_type} 데이터로 분류했습니다.`,
    },
    {
      rule: '전처리',
      applied: formatReportList(metadata.preprocessing_actions, 5) || '컬럼 표준화, 날짜/숫자 변환, 결측률 점검을 수행했습니다.',
    },
    {
      rule: '지표 계산',
      applied: reportIndicatorRuleText(result.data_type, calculated, notCalculated),
    },
    {
      rule: '시각화 선택',
      applied: mainContext?.selectedByRule || mainChart?.reason || '표시 가능한 차트가 선택되지 않았습니다.',
    },
    {
      rule: '인사이트 생성',
      applied: `title, level, evidence, message, check_point 구조의 인사이트 카드 ${formatInteger((result.insights ?? []).length)}개가 생성되었습니다.`,
    },
  ];

  return (
    <DashboardSection title="적용된 Skills.md 규칙" subtitle="분석에 적용된 규칙은 보조 정보로 확인할 수 있습니다.">
      <div className="rule-grid">
        {rows.map((row) => (
          <article className="card rule-card" key={row.rule}>
            <span className="card-label">{row.rule}</span>
            <p>{row.applied}</p>
          </article>
        ))}
      </div>
    </DashboardSection>
  );
}

function ReportKpiGrid({ result, indicators, charts }) {
  const metrics = reportKpiMetrics(result, indicators, charts);
  return (
    <section className="indicator-grid">
      {metrics.map((metric) => (
        <article className={`card indicator-card ${metric.status === 'not_calculated' ? 'not-calculated' : ''}`} key={metric.label}>
          <span className="card-label">{metric.label}</span>
          <strong>{formatValue(metric.value, metric.format)}</strong>
          {metric.detail && <p>{metric.detail}</p>}
          {metric.status === 'not_calculated' && <small>{metric.reason || '현재 규칙 경로에서 계산되지 않았습니다.'}</small>}
        </article>
      ))}
    </section>
  );
}

function ReportMainVisualization({ chart, result }) {
  if (!chart) return null;
  return (
    <DashboardSection title="주요 시각화" subtitle="현재 데이터에서 가장 먼저 확인해야 할 핵심 차트입니다.">
      <ReportChartCard chart={chart} result={result} featured />
    </DashboardSection>
  );
}

function ReportSupportingCharts({ charts, result }) {
  if (!charts.length) return null;
  return (
    <DashboardSection title="보조 차트" subtitle="주요 차트를 보완하는 추가 분석 화면입니다.">
      <div className="chart-grid">
        {charts.map((chart, index) => (
          <ReportChartCard chart={chart} result={result} key={`${chart.chart_id ?? chart.title}-${index}`} />
        ))}
      </div>
    </DashboardSection>
  );
}

function ReportChartCard({ chart, result, featured = false }) {
  const chartType = chart.chart_type ?? chart.type;
  const context = getReportChartContext(chart, result);
  const chartClass = [
    'card',
    'chart-card',
    `${chartType}-chart`,
    featured ? 'main-chart-card' : '',
    isWideChart(chart, result.data_type) ? 'wide-chart' : '',
  ].filter(Boolean).join(' ');

  return (
    <article className={chartClass}>
      <div className="chart-heading">
        <div>
          <h2>{context.title}</h2>
          <p>{chart.reason}</p>
        </div>
      </div>
      <ReportChartContext context={context} />
      <ChartRenderer chart={chart} />
    </article>
  );
}

function ReportChartContext({ context }) {
  return (
    <div className="chart-context">
      <div>
        <span>차트 목적</span>
        <p>{context.purpose}</p>
      </div>
      <div>
        <span>해석 방법</span>
        <p>{context.howToRead}</p>
      </div>
      <div>
        <span>핵심 발견</span>
        <p>{context.keyFinding}</p>
      </div>
      <div>
        <span>선택 규칙</span>
        <p>{context.selectedByRule}</p>
      </div>
    </div>
  );
}

function ReportSupportingTables({ result, charts, indicators }) {
  const summary = buildReportSummaryTable(result, charts, indicators);
  const tableCharts = charts.filter((chart) => (chart.chart_type ?? chart.type) === 'table');

  if (!summary.rows.length && !tableCharts.length) return null;

  return (
    <DashboardSection title="보조 분석 테이블" subtitle="원본 테이블보다 해석에 필요한 요약 테이블을 우선 표시합니다.">
      <div className="table-section-grid">
        {summary.rows.length > 0 && (
          <article className="card table-card">
            <div className="chart-heading">
              <div>
                <h2>{summary.title}</h2>
                <p>{summary.subtitle}</p>
              </div>
            </div>
            <DataTable rows={summary.rows} columns={summary.columns} />
          </article>
        )}
        {tableCharts.map((chart, index) => (
          <article className="card table-card" key={`${chart.title}-${index}`}>
            <details>
              <summary>
                <strong>{displayReportChartTitle(chart)}</strong>
                <small>{chart.reason}</small>
              </summary>
              <ReportChartContext context={getReportChartContext(chart, result)} />
              <DataTable rows={chart.data} columns={chartTableColumns(chart)} />
            </details>
          </article>
        ))}
      </div>
    </DashboardSection>
  );
}

function ReportMetadataTransparency({ result, charts, indicators }) {
  const metadata = result.metadata ?? {};
  const quality = result.data_quality ?? {};
  const indicatorRows = indicators.map((item) => ({
    indicator: item.name,
    status: item.calculation_status || (item.value === null || item.value === undefined ? 'not_calculated' : 'calculated'),
    value: formatValue(item.value, item.format),
    reason: item.reason || '-',
  }));
  const chartRows = charts.map((chart) => {
    const context = getReportChartContext(chart, result);
    return {
      chart: context.title,
      type: chart.chart_type ?? chart.type,
      selected_by_rule: context.selectedByRule,
      reason: chart.reason || '-',
    };
  });

  return (
    <DashboardSection title="메타데이터 투명성" subtitle="가정, 전처리, 경고, 지표 계산 상태, 차트 선택 사유를 접어서 확인할 수 있습니다.">
      <article className="card metadata-card">
        <details className="metadata-details">
          <summary>
            <span>
              <strong>메타데이터 상세 보기</strong>
              <small>컬럼 매핑, 가정, 전처리, 경고, 지표 계산 상태, 차트 선택 사유</small>
            </span>
          </summary>
          <div className="metadata-block">
            <h3>컬럼 매핑 (metadata.column_mapping)</h3>
            <DataTable rows={metadata.column_mapping ?? []} columns={['original_column', 'standard_column']} />
          </div>
          <ReportMetadataList title="분석 가정 (metadata.assumptions)" items={metadata.assumptions ?? []} />
          <ReportMetadataList title="전처리 내역 (metadata.preprocessing_actions)" items={metadata.preprocessing_actions ?? []} />
          <ReportMetadataList title="품질 경고 (data_quality.warning_messages)" items={quality.warning_messages ?? []} />
          <div className="metadata-block">
            <h3>지표 계산 상태</h3>
            <DataTable rows={indicatorRows} columns={['indicator', 'status', 'value', 'reason']} />
          </div>
          <div className="metadata-block">
            <h3>차트 선택 사유</h3>
            <DataTable rows={chartRows} columns={['chart', 'type', 'selected_by_rule', 'reason']} />
          </div>
        </details>
      </article>
    </DashboardSection>
  );
}

function ReportMetadataList({ title, items }) {
  return (
    <div className="metadata-block">
      <h3>{title}</h3>
      {items.length ? (
        <ul className="metadata-list">
          {items.map((item, index) => <li key={`${title}-${index}`}>{item}</li>)}
        </ul>
      ) : (
        <p className="muted">기록된 항목이 없습니다.</p>
      )}
    </div>
  );
}

function ReportRawPreview({ rows }) {
  const columns = useMemo(() => {
    const firstRow = rows[0] ?? {};
    return Object.keys(firstRow);
  }, [rows]);

  if (!rows.length) return null;

  return (
    <section className="card preview-card">
      <details>
        <summary>
          <strong>원본/전처리 행 미리보기</strong>
          <small>요약 테이블과 핵심 분석 결과가 우선 보이도록 접어 두었습니다.</small>
        </summary>
        <DataTable rows={rows} columns={columns} />
      </details>
    </section>
  );
}

function TypeDetailsPanel({ result }) {
  if (result.data_type === 'Unknown') {
    return <UnknownPanel result={result} />;
  }
  return null;
}

function MainChart({ charts, dataType }) {
  const chart = charts[0];
  if (!chart) return null;
  return (
    <section className="main-chart-grid">
      <article className="card chart-card main-chart-card">
        <div className="chart-heading">
          <div>
            <h2>{chart.title}</h2>
            <p>{chart.reason}</p>
          </div>
        </div>
        <ChartRenderer chart={chart} dataType={dataType} />
      </article>
    </section>
  );
}

function UnknownPanel({ result }) {
  const metadata = result.metadata ?? {};
  const candidate = metadata.candidate_data_type ?? {};
  const unknown = metadata.unknown_profile ?? {};
  const rows = [
    {
      item: '후보 유형',
      value: candidate.suggested_type || 'Unknown',
      detail: candidate.reason || metadata.detection_reason || '-',
    },
    {
      item: '신뢰도',
      value: candidate.confidence || 'low',
      detail: metadata.detection_reason || '-',
    },
    {
      item: '탐색 수치형',
      value: formatInteger((unknown.numeric_columns_used ?? []).length),
      detail: formatList(unknown.numeric_columns_used),
    },
    {
      item: '비수치형',
      value: formatInteger((unknown.non_numeric_columns ?? []).length),
      detail: formatList(unknown.non_numeric_columns),
    },
  ];

  return (
    <section className="card type-detail-card unknown-detail-card">
      <div className="chart-heading">
        <div>
          <h2>분류 불가 데이터 프로파일</h2>
          <p>{metadata.detection_reason}</p>
        </div>
      </div>
      <DataTable rows={rows} columns={['item', 'value', 'detail']} />
    </section>
  );
}

function MetadataPanel({ result }) {
  const metadata = result.metadata ?? {};
  const dataQuality = result.data_quality ?? {};
  const candidate = metadata.candidate_data_type ?? {};
  const rows = [
    {
      item: '후보 유형',
      value: candidate.suggested_type || result.data_type || '-',
      detail: candidate.reason || metadata.detection_reason || '-',
    },
    {
      item: '시장 국면',
      value: getMarketRegime(metadata.market_regime) || '-',
      detail: metadata.market_regime?.evidence || metadata.market_regime?.message || '-',
    },
    {
      item: '자산군',
      value: getAssetClass(metadata.asset_class) || '-',
      detail: formatObject(metadata.asset_class?.evidence),
    },
    {
      item: '신뢰도',
      value: candidate.confidence || '-',
      detail: '자동 감지 규칙 기반',
    },
    {
      item: '수치형 컬럼',
      value: formatInteger(metadata.numeric_columns?.length ?? 0),
      detail: formatList(metadata.numeric_columns),
    },
    {
      item: '표준화 컬럼',
      value: formatInteger((metadata.column_mapping ?? []).length || Object.keys(metadata.standardized_columns ?? {}).length),
      detail: formatMapping(metadata.column_mapping) || formatObject(metadata.standardized_columns),
    },
    {
      item: '가정',
      value: formatInteger((metadata.assumptions ?? []).length),
      detail: formatList(metadata.assumptions),
    },
    {
      item: '전처리',
      value: formatInteger((metadata.preprocessing_actions ?? []).length),
      detail: formatList(metadata.preprocessing_actions),
    },
    {
      item: '경고',
      value: formatInteger((metadata.warning_messages ?? dataQuality.warning_messages ?? []).length),
      detail: formatList(metadata.warning_messages ?? dataQuality.warning_messages),
    },
    {
      item: '결측 비율',
      value: formatValue(dataQuality.missing_ratio ?? 0, 'percent'),
      detail: formatObject(metadata.missing_values),
    },
    {
      item: '이상치',
      value: formatInteger(dataQuality.outlier_count ?? dataQuality.outliers_count ?? 0),
      detail: formatObject(metadata.outliers),
    },
  ];

  return (
    <section className="card metadata-card">
      <details className="metadata-details">
        <summary>
          <span>
            <strong>메타데이터</strong>
            <small>감지 근거, 전처리, 가정, 품질 신호</small>
          </span>
        </summary>
        <DataTable rows={rows} columns={['item', 'value', 'detail']} />
      </details>
    </section>
  );
}

function IndicatorGrid({ indicators }) {
  if (!indicators.length) return null;

  return (
    <section className="indicator-grid">
      {indicators.map((item) => (
        <article className="card indicator-card" key={item.name}>
          <span className="card-label">{item.name}</span>
          <strong>{formatValue(item.value, item.format)}</strong>
        </article>
      ))}
    </section>
  );
}

function reportKpiMetrics(result, indicators, charts) {
  const type = result.data_type;
  if (type === 'Type-A') {
    return [
      reportKpiFromIndicator('최근 종가', indicators, ['latest close', '최신 종가']),
      reportKpiFromIndicator('누적 수익률', indicators, ['cumulative return', '누적 수익률']),
      reportKpiFromIndicator('연환산 변동성', indicators, ['annualized volatility', '연환산 변동성']),
      reportKpiFromIndicator('MDD', indicators, ['MDD']),
      reportKpiFromIndicator('RSI', indicators, ['RSI14', 'RSI']),
      reportKpiFromIndicator('VaR(95)', indicators, ['VaR 95%', 'var 95', 'var_95']),
    ];
  }
  if (type === 'Type-B') {
    const largestSector = getReportLargestSector(charts);
    return [
      reportKpiFromIndicator('자산 수', indicators, ['asset count', '자산 수']),
      reportKpiFromIndicator('Top1 비중', indicators, ['top1 weight', 'Top1 비중']),
      reportKpiFromIndicator('Top3 비중', indicators, ['top3 weight', 'Top3 비중']),
      reportKpiFromIndicator('HHI', indicators, ['HHI']),
      { label: '최대 섹터', value: largestSector?.label ?? '-', format: 'text', detail: largestSector ? formatValue(largestSector.value, 'percent') : '섹터 컬럼이 감지되지 않았습니다.' },
      { label: '집중도 수준', value: reportConcentrationLevel(indicators), format: 'text', detail: 'Top1, Top3, HHI 기준으로 판단했습니다.' },
    ];
  }
  if (type === 'Type-D') {
    const ranking = getReportTypeDRankingRows(charts);
    const best = ranking[0];
    const worst = ranking.length ? ranking[ranking.length - 1] : null;
    const avgVol = averageReportNumeric(ranking.map((row) => row.annualized_volatility));
    const maxPair = maxReportCorrelationPair(charts);
    return [
      reportKpiFromIndicator('자산 수', indicators, ['asset count', '종목 수']),
      { label: '최고 성과 자산', value: best ? `${best.asset ?? best.ticker}: ${formatValue(best.cumulative_return, 'percent')}` : '-', format: 'text' },
      { label: '최저 성과 자산', value: worst ? `${worst.asset ?? worst.ticker}: ${formatValue(worst.cumulative_return, 'percent')}` : '-', format: 'text' },
      { label: '평균 변동성', value: avgVol, format: 'percent', status: avgVol == null ? 'not_calculated' : 'calculated' },
      { label: '최대 상관 자산쌍', value: maxPair ? `${maxPair.left} / ${maxPair.right}: ${formatValue(maxPair.value, 'number')}` : '-', format: 'text' },
      reportKpiFromIndicator('평균 상관계수', indicators, ['average correlation', '평균 상관계수']),
    ];
  }
  return [
    reportKpiFromIndicator('행 수', indicators, ['row count', '행 수'], result.data_quality?.row_count, 'integer'),
    reportKpiFromIndicator('열 수', indicators, ['column count', '컬럼 수'], result.data_quality?.column_count, 'integer'),
    reportKpiFromIndicator('결측률', indicators, ['missing rate'], result.data_quality?.missing_rate, 'percent'),
    reportKpiFromIndicator('숫자 컬럼 수', indicators, ['numeric column count', '숫자 컬럼 수']),
    reportKpiFromIndicator('후보 유형', indicators, ['candidate type', '후보 유형'], result.metadata?.candidate_data_type?.suggested_type, 'text'),
  ];
}

function reportKpiFromIndicator(label, indicators, aliases, fallbackValue = undefined, fallbackFormat = 'number') {
  const item = findReportIndicator(indicators, aliases);
  if (!item && fallbackValue === undefined) {
    return { label, value: null, format: fallbackFormat, status: 'not_calculated', reason: '현재 분석 경로에서 해당 지표가 반환되지 않았습니다.' };
  }
  return {
    label,
    value: item?.value ?? fallbackValue,
    format: item?.format ?? fallbackFormat,
    status: item?.calculation_status ?? (fallbackValue === undefined ? 'not_calculated' : 'calculated'),
    reason: item?.reason,
    detail: item?.description && item.description !== item.name ? item.description : '',
  };
}

function findReportIndicator(indicators, aliases) {
  const normalizedAliases = aliases.map(reportNormalizeKey);
  return indicators.find((item) => normalizedAliases.includes(reportNormalizeKey(item.name)));
}

function getReportIndicatorValue(indicators, aliases) {
  return findReportIndicator(indicators, aliases)?.value;
}

function reportIsCalculatedIndicator(item) {
  return item.calculation_status !== 'not_calculated' && item.value !== null && item.value !== undefined && item.value !== 'not_calculated';
}

function reportIndicatorRuleText(dataType, calculated, notCalculated) {
  const base = {
    'Type-A': 'Type-A 규칙에 따라 가격 추세, 변동성, 낙폭, 이동평균, RSI, MACD, VaR를 계산 가능한 범위에서 확인했습니다.',
    'Type-B': 'Type-B 규칙에 따라 Top1/Top3 비중, HHI, 섹터 노출, 위험 기여도 계산 가능 여부를 확인했습니다.',
    'Type-D': 'Type-D 규칙에 따라 자산별 수익률, 변동성, 낙폭, 상관계수, 위험-수익 순위를 확인했습니다.',
    Unknown: '분류 불가 데이터 규칙에 따라 행/열 수, 결측률, 숫자 컬럼, 후보 유형을 확인했습니다.',
  }[dataType] ?? '감지된 데이터 유형에 맞는 Skills.md 지표 규칙을 적용했습니다.';
  const calculatedText = calculated.length ? ` 계산 지표: ${formatReportList(calculated, 8)}.` : '';
  const notCalculatedText = notCalculated.length ? ` 미계산 지표: ${formatReportList(notCalculated, 5)}.` : '';
  return `${base}${calculatedText}${notCalculatedText}`;
}

function orderReportCharts(charts, dataType) {
  const rules = {
    'Type-A': [
      ['candlestick', 0],
      ['closevsma20', 1],
      ['movingaverages', 2],
      ['drawdown', 3],
      ['rsi', 4],
      ['macd', 5],
      ['rollingvolatility', 6],
      ['cumulativereturn', 7],
      ['volume', 8],
    ],
    'Type-B': [
      ['portfolioweights', 0],
      ['sectorweights', 1],
      ['portfolioweighttable', 2],
    ],
    'Type-D': [
      ['cumulativereturncomparison', 0],
      ['correlationheatmap', 1],
      ['riskreturnscatter', 2],
      ['riskreturnrank', 3],
    ],
    Unknown: [
      ['columnsummary', 0],
      ['numericsummary', 1],
      ['histogram', 2],
      ['correlationheatmap', 3],
      ['missing', 4],
    ],
  }[dataType] ?? [];
  return [...charts].sort((left, right) => reportChartOrder(left, rules) - reportChartOrder(right, rules));
}

function reportChartOrder(chart, rules) {
  const text = reportNormalizeKey(`${chart.title ?? ''} ${chart.chart_type ?? chart.type ?? ''}`);
  const match = rules.find(([token]) => text.includes(token));
  return match ? match[1] : 99;
}

function pickReportMainChart(charts, dataType) {
  if (!charts.length) return null;
  if (dataType === 'Unknown') return charts[0];
  return charts.find((chart) => (chart.chart_type ?? chart.type) !== 'table') ?? charts[0];
}

function getReportChartContext(chart, result) {
  return {
    title: displayReportChartTitle(chart),
    purpose: reportChartPurpose(chart, result.data_type),
    howToRead: reportHowToReadChart(chart.chart_type ?? chart.type, chart),
    keyFinding: reportChartKeyFinding(chart),
    selectedByRule: reportSelectedByRule(chart, result.data_type),
  };
}

function displayReportChartTitle(chart) {
  const title = chart?.title ?? '차트';
  const titleMap = {
    'OHLC Candlestick': '가격 OHLC 캔들스틱',
    'Close vs MA20': '종가와 MA20 추세',
    'Moving Averages': '이동평균 추세',
    Drawdown: '최대 낙폭 추이',
    'RSI(14)': 'RSI 모멘텀 지표',
    'MACD(12/26/9)': 'MACD 모멘텀 지표',
    'Rolling Volatility 20D': '20일 이동 변동성',
    'Cumulative Return': '단일 자산 누적 수익률',
    Volume: '거래량 추이',
    'Portfolio Weights': '포트폴리오 자산 배분',
    'Portfolio Weight Table': '집중도 분석 테이블',
    'Sector Weights': '섹터 노출도',
    'Type-D Cumulative Return Comparison': '다중 자산 누적 수익률 비교',
    'Type-D Correlation Heatmap': '상관관계 히트맵',
    'Risk Return Scatter': '위험-수익 산점도',
    'Risk Return Rank': '자산 순위 테이블',
    'Column Summary': '컬럼 프로파일 테이블',
    'Numeric Summary': '수치형 분포 요약',
    'Numeric Correlation Heatmap': '수치형 상관관계 히트맵',
    'Missing Values by Column': '컬럼별 결측치',
    'Missing Summary': '결측치 요약 테이블',
  };
  return titleMap[title] ?? title.replace(/^Type-D\s+/, '').replace(/\bRisk Return\b/g, '위험-수익');
}

function reportChartPurpose(chart, dataType) {
  const title = displayReportChartTitle(chart).toLowerCase();
  if (title.includes('누적 수익률')) return '분석 기간 동안 자산별 성과가 어떻게 누적되었는지 비교합니다.';
  if (title.includes('상관관계')) return '자산 간 동조화 정도를 확인해 분산 효과와 상관관계 리스크를 평가합니다.';
  if (title.includes('위험-수익')) return '각 자산의 누적 수익률과 변동성을 함께 비교합니다.';
  if (title.includes('배분') || title.includes('비중')) return '포트폴리오 구성과 특정 자산 쏠림 정도를 보여줍니다.';
  if (title.includes('섹터')) return '포트폴리오가 어떤 섹터에 노출되어 있는지 확인합니다.';
  if (title.includes('캔들')) return '시가, 고가, 저가, 종가를 함께 보여 가격 움직임을 요약합니다.';
  if (title.includes('낙폭')) return '고점 대비 하락 폭을 통해 하방 리스크를 확인합니다.';
  if (title.includes('rsi')) return '과매수 또는 과매도 가능성을 판단하는 모멘텀 지표입니다.';
  if (title.includes('macd')) return 'MACD, Signal, Histogram으로 추세 모멘텀을 확인합니다.';
  if (title.includes('컬럼') || dataType === 'Unknown') return '투자 데이터 유형이 확정되지 않은 경우 데이터 구조를 먼저 점검합니다.';
  return chart.reason || 'Skills.md 규칙에 따라 선택된 금융 분석 화면입니다.';
}

function reportHowToReadChart(chartType, chart) {
  if (chartType === 'line') return '선이 높을수록 해당 날짜의 지표 값이 큽니다. 여러 선은 같은 기간의 상대 흐름을 비교합니다.';
  if (chartType === 'candlestick') return '상승/하락 캔들과 고가-저가 범위를 함께 보며 가격 변동 폭을 확인합니다.';
  if (chartType === 'heatmap') return '진한 양수 색상은 높은 양의 상관관계, 음수 색상은 반대 방향 움직임을 의미합니다.';
  if (chartType === 'scatter') return '오른쪽일수록 변동성이 크고, 위쪽일수록 누적 수익률이 높습니다.';
  if (chartType === 'donut' || chartType === 'pie') return '조각이 클수록 포트폴리오 내 비중이 큽니다.';
  if (chartType === 'bar' || chartType === 'histogram') return '막대가 길수록 해당 항목의 값 또는 빈도가 큽니다.';
  if (chartType === 'table') return 'Skills.md 선택 규칙에 따라 필요한 항목만 요약한 표입니다.';
  return chart.reason || '축과 범례를 기준으로 값의 크기와 방향을 해석합니다.';
}

function reportSelectedByRule(chart, dataType) {
  const chartType = chart.chart_type ?? chart.type;
  const title = displayReportChartTitle(chart).toLowerCase();
  if (dataType === 'Type-A' && chartType === 'candlestick') return 'Type-A 데이터에서 OHLC 컬럼이 감지되어 캔들스틱 차트를 우선 선택했습니다.';
  if (dataType === 'Type-A' && title.includes('낙폭')) return 'Type-A 하방 리스크 규칙에 따라 낙폭 차트를 선택했습니다.';
  if (dataType === 'Type-A' && (title.includes('rsi') || title.includes('macd'))) return 'Type-A 기술적 지표 규칙에 따라 RSI/MACD 차트를 선택했습니다.';
  if (dataType === 'Type-B' && (chartType === 'donut' || title.includes('배분'))) return 'Type-B 포트폴리오 구성 규칙에 따라 자산 배분 차트를 선택했습니다.';
  if (dataType === 'Type-B' && title.includes('섹터')) return 'Type-B 데이터에서 sector 컬럼이 감지되어 섹터 노출 차트를 선택했습니다.';
  if (dataType === 'Type-D' && title.includes('누적')) return 'Type-D 다중 자산 시계열 규칙에 따라 누적 수익률 비교 차트를 선택했습니다.';
  if (dataType === 'Type-D' && chartType === 'heatmap') return 'Type-D 상관계수 행렬 규칙에 따라 상관관계 히트맵을 선택했습니다.';
  if (dataType === 'Type-D' && chartType === 'scatter') return 'Type-D 수익률·변동성 비교 규칙에 따라 위험-수익 산점도를 선택했습니다.';
  if (dataType === 'Unknown') return '분류 불가 데이터 규칙에 따라 컬럼 프로파일, 분포, 요약 표를 선택했습니다.';
  return chart.reason || `${dataType} 시각화 규칙에 따라 ${chartType} 차트를 선택했습니다.`;
}

function reportChartKeyFinding(chart) {
  const chartType = chart.chart_type ?? chart.type;
  const xKey = chart.x_key ?? chart.x_column ?? chart.x;
  const yKeys = chart.y_keys ?? chart.y_columns ?? chart.y ?? [];
  const rows = chart.data ?? [];
  if (!rows.length) return 'No renderable records returned.';

  if (chartType === 'heatmap') {
    const pair = maxReportCorrelationPairFromChart(chart);
    return pair ? `${pair.left}와 ${pair.right}의 표시된 상관관계가 가장 큽니다(${formatValue(pair.value, 'number')}).` : '해석 가능한 비대각 상관계수 값이 없습니다.';
  }
  if (chartType === 'scatter') {
    const yKey = yKeys[0];
    const best = rows
      .filter((row) => Number.isFinite(Number(row[yKey])))
      .sort((left, right) => Number(right[yKey]) - Number(left[yKey]))[0];
    return best ? `${best.asset ?? best.ticker ?? '상위 자산'}의 표시된 ${yKey} 값이 가장 큽니다: ${formatPercentMaybe(Number(best[yKey]), yKey)}.` : '해석 가능한 위험-수익 좌표가 없습니다.';
  }
  if (chartType === 'donut' || chartType === 'pie' || chartType === 'bar' || chartType === 'histogram') {
    const yKey = yKeys[0];
    const top = rows
      .filter((row) => Number.isFinite(Number(row[yKey])))
      .sort((left, right) => Number(right[yKey]) - Number(left[yKey]))[0];
    return top ? `${top[xKey]} 항목이 가장 큰 값으로 표시됩니다: ${formatPercentMaybe(Number(top[yKey]), yKey)}.` : '해석 가능한 막대 또는 비중 값이 없습니다.';
  }
  if (chartType === 'line') {
    const latest = rows[rows.length - 1];
    const numericKeys = yKeys.filter((key) => Number.isFinite(Number(latest?.[key])));
    if (numericKeys.length > 1) {
      const leader = numericKeys.sort((left, right) => Number(latest[right]) - Number(latest[left]))[0];
      return `최근 시점에서 ${leader} 값이 가장 높습니다: ${formatPercentMaybe(Number(latest[leader]), leader)}.`;
    }
    if (numericKeys.length === 1) {
      return `최근 표시된 ${numericKeys[0]} 값은 ${formatPercentMaybe(Number(latest[numericKeys[0]]), numericKeys[0])}입니다.`;
    }
  }
  if (chartType === 'candlestick') {
    const latest = [...rows].reverse().find((row) => Number.isFinite(Number(row.close)));
    return latest ? `최근 표시된 종가는 ${formatValue(Number(latest.close), 'number')}입니다.` : '유효한 OHLC 종가 값이 없습니다.';
  }
  return `이 규칙 기반 화면에 ${formatInteger(rows.length)}개 행이 사용되었습니다.`;
}

function buildReportSummaryTable(result, charts, indicators) {
  if (result.data_type === 'Type-A') return buildReportTypeASummary(charts);
  if (result.data_type === 'Type-B') return buildReportTypeBSummary(charts, result.preview_rows ?? [], indicators);
  if (result.data_type === 'Type-D') return buildReportTypeDSummary(charts);
  return buildReportUnknownSummary(charts);
}

function buildReportTypeASummary(charts) {
  const priceChart = charts.find((chart) => ['candlestick', 'line'].includes(chart.chart_type ?? chart.type) && (chart.y_keys ?? chart.y ?? []).some((key) => key === 'close'));
  const cumulativeChart = charts.find((chart) => reportNormalizeKey(chart.title).includes('cumulativereturn'));
  const drawdownChart = charts.find((chart) => reportNormalizeKey(chart.title).includes('drawdown'));
  const volumeChart = charts.find((chart) => reportNormalizeKey(chart.title).includes('volume'));
  const byDate = new Map();

  for (const row of priceChart?.data ?? []) {
    if (!row.date) continue;
    byDate.set(row.date, { ...(byDate.get(row.date) ?? {}), date: row.date, close: row.close });
  }
  for (const row of cumulativeChart?.data ?? []) {
    byDate.set(row.date, { ...(byDate.get(row.date) ?? {}), date: row.date, cumulative_return: row.cumulative_return });
  }
  for (const row of drawdownChart?.data ?? []) {
    byDate.set(row.date, { ...(byDate.get(row.date) ?? {}), date: row.date, drawdown: row.drawdown });
  }
  for (const row of volumeChart?.data ?? []) {
    byDate.set(row.date, { ...(byDate.get(row.date) ?? {}), date: row.date, volume: row.volume });
  }

  const sorted = [...byDate.values()].sort((left, right) => String(left.date).localeCompare(String(right.date)));
  for (let index = 0; index < sorted.length; index += 1) {
    const previous = sorted[index - 1];
    const current = sorted[index];
    current.daily_return = Number.isFinite(Number(current.close)) && Number.isFinite(Number(previous?.close)) && Number(previous.close) !== 0
      ? Number(current.close) / Number(previous.close) - 1
      : null;
  }

  return {
    title: '최근 관측치 요약',
    subtitle: 'Type-A 요약 표: 날짜, 종가, 일간 수익률, 누적 수익률, 낙폭, 거래량을 표시합니다.',
    columns: ['date', 'close', 'daily_return', 'cumulative_return', 'drawdown', 'volume'],
    rows: sorted.slice(-10).reverse(),
  };
}

function buildReportTypeBSummary(charts, previewRows, indicators) {
  const allocationChart = charts.find((chart) => ['Portfolio Weights', 'Portfolio Weight Table'].includes(chart.title));
  const sectorByAsset = new Map();
  for (const row of previewRows) {
    const asset = row.asset ?? row.ticker ?? row.asset_name;
    if (asset && row.sector) sectorByAsset.set(String(asset), row.sector);
  }
  const top3 = findReportIndicator(indicators, ['top3 weight'])?.value;
  const rows = (allocationChart?.data ?? []).map((row, index) => {
    const asset = row.asset ?? row.ticker ?? row.asset_name;
    const weight = row.weight;
    let flag = 'normal';
    if (index === 0 && Number(weight) >= 0.40) flag = 'single_asset_concentration';
    else if (index < 3 && Number(top3) >= 0.70) flag = 'top3_concentration';
    return {
      ticker: asset,
      asset_name: asset,
      weight,
      sector: sectorByAsset.get(String(asset)) ?? '-',
      concentration_flag: flag,
    };
  });
  return {
    title: '포트폴리오 집중도 요약',
    subtitle: 'Type-B 요약 표: 자산명, 비중, 섹터, 집중도 플래그를 표시합니다.',
    columns: ['ticker', 'asset_name', 'weight', 'sector', 'concentration_flag'],
    rows: rows.slice(0, 15),
  };
}

function buildReportTypeDSummary(charts) {
  const rows = getReportTypeDRankingRows(charts).map((row) => ({
    ticker: row.asset ?? row.ticker,
    cumulative_return: row.cumulative_return,
    annualized_volatility: row.annualized_volatility,
    MDD: row.mdd,
    sharpe_ratio: row.sharpe_ratio ?? 'not_calculated',
    correlation_note: reportCorrelationNoteForAsset(row.asset ?? row.ticker, charts),
  }));
  return {
    title: '자산별 성과 순위',
    subtitle: 'Type-D 요약 표: 자산, 누적 수익률, 연환산 변동성, MDD, 샤프비율, 상관관계 메모를 표시합니다.',
    columns: ['ticker', 'cumulative_return', 'annualized_volatility', 'MDD', 'sharpe_ratio', 'correlation_note'],
    rows,
  };
}

function buildReportUnknownSummary(charts) {
  const columnChart = charts.find((chart) => reportNormalizeKey(chart.title).includes('columnsummary')) ?? charts.find((chart) => (chart.chart_type ?? chart.type) === 'table');
  return {
    title: '컬럼 프로파일 테이블',
    subtitle: '분류 불가 데이터의 컬럼 타입, 결측 개수, 고유값 개수를 요약합니다.',
    columns: chartTableColumns(columnChart ?? {}),
    rows: columnChart?.data ?? [],
  };
}

function getReportTypeDRankingRows(charts) {
  const rankChart = charts.find((chart) => reportNormalizeKey(chart.title).includes('riskreturnrank'))
    ?? charts.find((chart) => (chart.chart_type ?? chart.type) === 'scatter');
  return [...(rankChart?.data ?? [])].sort((left, right) => Number(right.cumulative_return ?? -Infinity) - Number(left.cumulative_return ?? -Infinity));
}

function getReportLargestSector(charts) {
  const sectorChart = charts.find((chart) => reportNormalizeKey(chart.title).includes('sector'));
  if (!sectorChart?.data?.length) return null;
  const yKey = (sectorChart.y_keys ?? sectorChart.y ?? ['weight'])[0];
  const xKey = sectorChart.x_key ?? sectorChart.x ?? 'sector';
  const top = [...sectorChart.data].sort((left, right) => Number(right[yKey]) - Number(left[yKey]))[0];
  return top ? { label: top[xKey], value: top[yKey] } : null;
}

function reportConcentrationLevel(indicators) {
  const top1 = Number(findReportIndicator(indicators, ['top1 weight'])?.value);
  const top3 = Number(findReportIndicator(indicators, ['top3 weight'])?.value);
  const hhi = Number(findReportIndicator(indicators, ['HHI'])?.value);
  if (Number.isFinite(top1) && top1 >= 0.40) return '단일 자산 집중';
  if (Number.isFinite(top3) && top3 >= 0.70) return '상위 3개 자산 집중';
  if (Number.isFinite(hhi) && hhi >= 0.25) return '높은 집중도';
  if (Number.isFinite(hhi) && hhi < 0.10) return '분산도 높음';
  return '보통';
}

function maxReportCorrelationPair(charts) {
  const heatmap = charts.find((chart) => (chart.chart_type ?? chart.type) === 'heatmap' && reportNormalizeKey(chart.title).includes('correlation'));
  return heatmap ? maxReportCorrelationPairFromChart(heatmap) : null;
}

function maxReportCorrelationPairFromChart(chart) {
  const xKey = chart.x_key ?? chart.x ?? 'asset';
  const yKeys = chart.y_keys ?? chart.y ?? [];
  let best = null;
  for (const row of chart.data ?? []) {
    const left = row[xKey];
    for (const right of yKeys) {
      if (String(left) === String(right)) continue;
      const value = Number(row[right]);
      if (!Number.isFinite(value)) continue;
      if (!best || Math.abs(value) > Math.abs(best.value)) {
        best = { left, right, value };
      }
    }
  }
  return best;
}

function reportCorrelationNoteForAsset(asset, charts) {
  if (!asset) return '-';
  const heatmap = charts.find((chart) => (chart.chart_type ?? chart.type) === 'heatmap' && reportNormalizeKey(chart.title).includes('correlation'));
  if (!heatmap) return 'correlation_not_available';
  const xKey = heatmap.x_key ?? heatmap.x ?? 'asset';
  const yKeys = heatmap.y_keys ?? heatmap.y ?? [];
  const row = (heatmap.data ?? []).find((item) => String(item[xKey]) === String(asset));
  if (!row) return 'correlation_not_available';
  const peers = yKeys
    .filter((key) => String(key) !== String(asset) && Number.isFinite(Number(row[key])))
    .sort((left, right) => Math.abs(Number(row[right])) - Math.abs(Number(row[left])));
  if (!peers.length) return 'correlation_not_available';
  return `highest_with_${peers[0]}=${formatValue(Number(row[peers[0]]), 'number')}`;
}

function averageReportNumeric(values) {
  const numeric = values.map(Number).filter(Number.isFinite);
  if (!numeric.length) return null;
  return numeric.reduce((sum, value) => sum + value, 0) / numeric.length;
}

function reportAnalysisObjective(dataType, metadata) {
  const assetClass = getAssetClass(metadata.asset_class);
  if (dataType === 'Type-A') return `이 데이터는 단일 자산의 가격 흐름을 분석할 수 있는 Type-A ${assetClass || '투자'} 시계열 데이터로 감지되었습니다. 분석은 가격 추세, 변동성, 최대 낙폭, 기술적 지표를 중심으로 수행됩니다.`;
  if (dataType === 'Type-B') return '이 데이터는 포트폴리오 보유 구성을 분석할 수 있는 Type-B 단면 데이터로 감지되었습니다. 분석은 자산 배분, 섹터 노출, 집중도, 분산 수준을 중심으로 수행됩니다.';
  if (dataType === 'Type-D') return '이 데이터는 여러 자산의 가격 흐름을 비교할 수 있는 Type-D 다중 자산 시계열 데이터로 감지되었습니다. 분석은 자산별 누적 수익률, 변동성, 최대 낙폭, 상관관계 리스크를 중심으로 수행됩니다.';
  if (dataType === 'Type-C') return '이 데이터는 이벤트 또는 뉴스 흐름을 요약할 수 있는 구조로 감지되었습니다. 현재 분석은 이벤트 빈도와 감성 분포를 중심으로 수행됩니다.';
  return '이 데이터는 표준 투자 데이터 유형으로 확정되지 않아 데이터 품질, 컬럼 구조, 수치형 분포, 후보 유형 제안을 중심으로 분석합니다.';
}

function reportDatasetSentence(dataType, metadata) {
  const assetClass = getAssetClass(metadata.asset_class) || '미확정 자산군';
  const format = metadata.data_format || '형식 미확정';
  return `${dataType || 'Unknown'} ${assetClass} 데이터로 감지되었습니다 (${format}).`;
}

function reportTypeClass(dataType) {
  return `type-${String(dataType || 'unknown').toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
}

function reportNormalizeKey(value) {
  return String(value ?? '').toLowerCase().replace(/[^a-z0-9가-힣]+/g, '');
}

function formatReportList(value, limit = 8) {
  if (!Array.isArray(value) || value.length === 0) return '-';
  return value.slice(0, limit).join(', ') + (value.length > limit ? ` 외 ${value.length - limit}개` : '');
}

function normalizeIndicators(indicators) {
  if (Array.isArray(indicators)) return indicators;
  if (!indicators || typeof indicators !== 'object') return [];
  return Object.entries(indicators).map(([name, value]) => ({
    name,
    value,
    format: typeof value === 'number' ? 'number' : 'text',
  }));
}

function pickKeyMetric(dataType, indicators, metadata) {
  const preferredByType = {
    'Type-A': ['annualized volatility', 'VaR 95%', 'MDD', 'cumulative return'],
    'Type-B': ['HHI', 'top1 weight', 'top3 weight'],
    'Type-C': ['support status', 'row count'],
    'Type-D': ['portfolio volatility', 'average correlation', 'portfolio cumulative return'],
    Unknown: ['missing rate', 'numeric column count', 'column count'],
  };
  const preferred = preferredByType[dataType] ?? [];
  return preferred.map((name) => indicators.find((item) => item.name === name)).find(Boolean)
    ?? indicators.find((item) => item.value !== null && item.value !== undefined)
    ?? null;
}

function ChartGrid({ charts, dataType }) {
  const visibleCharts = charts.filter(hasRenderableChart);
  if (!visibleCharts.length) return null;

  return (
    <section className="dashboard-section">
      <SectionHeader title="보조 화면" subtitle="데이터 구조와 품질에 따라 선택된 보조 차트입니다." />
      <div className="chart-grid">
      {visibleCharts.map((chart, index) => {
        const chartType = chart.chart_type ?? chart.type;
        const chartClass = [
          'card',
          'chart-card',
          `${chartType}-chart`,
          isWideChart(chart, dataType) ? 'wide-chart' : '',
        ]
          .filter(Boolean)
          .join(' ');

        return (
          <article className={chartClass} key={`${chart.title}-${index}`}>
            <div className="chart-heading">
              <div>
                <h2>{chart.title}</h2>
                <p>{chart.reason}</p>
              </div>
            </div>
            <ChartRenderer chart={chart} />
          </article>
        );
      })}
      </div>
    </section>
  );
}

function ChartRenderer({ chart }) {
  if (!chart.data?.length) {
    return <div className="empty-chart">표시할 데이터가 없습니다.</div>;
  }
  const chartType = chart.chart_type ?? chart.type;
  const xKey = chart.x_key ?? chart.x_column ?? chart.x;
  const yKeys = chart.y_keys ?? chart.y_columns ?? chart.y ?? [];

  if (chartType === 'candlestick') {
    return <CandlestickChart chart={chart} />;
  }

  if (chartType === 'line') {
    return (
      <div className="chart-box">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chart.data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#d7dde5" />
            <XAxis dataKey={xKey} tick={{ fontSize: 12 }} minTickGap={24} />
            <YAxis tick={{ fontSize: 12 }} tickFormatter={compactNumber} />
            <Tooltip formatter={(value) => formatTooltipValue(value)} />
            <Legend />
            {yKeys.map((key, index) => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                stroke={COLORS[index % COLORS.length]}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    );
  }

  if (chartType === 'pie' || chartType === 'donut') {
    const valueKey = yKeys?.[0] ?? 'value';
    return (
      <div className="chart-box">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={chart.data}
              dataKey={valueKey}
              nameKey={xKey}
              innerRadius={56}
              outerRadius={96}
              paddingAngle={2}
              label={({ name, percent }) => `${name} ${(percent * 100).toFixed(1)}%`}
            >
              {chart.data.map((entry, index) => (
                <Cell key={`${entry[xKey]}-${index}`} fill={COLORS[index % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip formatter={(value) => formatPercentMaybe(value, valueKey)} />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      </div>
    );
  }

  if (chartType === 'bar' || chartType === 'histogram') {
    const yKey = yKeys?.[0] ?? 'value';
    return (
      <div className="chart-box">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chart.data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#d7dde5" />
            <XAxis dataKey={xKey} tick={{ fontSize: 12 }} minTickGap={12} />
            <YAxis tick={{ fontSize: 12 }} tickFormatter={compactNumber} />
            <Tooltip formatter={(value) => formatPercentMaybe(value, yKey)} />
            <Bar dataKey={yKey} fill="#168a71" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  }

  if (chartType === 'heatmap') {
    return <MatrixTable chart={chart} />;
  }

  if (chartType === 'scatter') {
    const yKey = yKeys?.[0] ?? 'value';
    return (
      <div className="chart-box">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 16, right: 24, bottom: 20, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#d7dde5" />
            <XAxis type="number" dataKey={xKey} tick={{ fontSize: 12 }} tickFormatter={(value) => formatPercentMaybe(value, xKey)} name={xKey} />
            <YAxis type="number" dataKey={yKey} tick={{ fontSize: 12 }} tickFormatter={(value) => formatPercentMaybe(value, yKey)} name={yKey} />
            <ZAxis range={[70, 220]} />
            <Tooltip
              cursor={{ strokeDasharray: '3 3' }}
              formatter={(value, name) => [formatPercentMaybe(value, name), name]}
              labelFormatter={() => ''}
            />
            <Scatter data={chart.data} fill="#168a71" name={chart.title} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    );
  }

  return <DataTable rows={chart.data} columns={chartTableColumns(chart)} />;
}

function MatrixTable({ chart }) {
  const xKey = chart.x_key ?? chart.x_column ?? chart.x;
  const yKeys = chart.y_keys ?? chart.y_columns ?? chart.y ?? [];
  return (
    <div className="table-wrap matrix-wrap">
      <table>
        <thead>
          <tr>
            <th>{xKey}</th>
            {yKeys.map((key) => (
              <th key={key}>{key}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {chart.data.map((row) => (
            <tr key={row[xKey]}>
              <th>{row[xKey]}</th>
              {yKeys.map((key) => (
                <td key={key} style={{ backgroundColor: correlationColor(row[key]) }}>
                  {formatValue(row[key], 'number')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CandlestickChart({ chart }) {
  const rows = chart.data
    .filter((row) => ['open', 'high', 'low', 'close'].every((key) => Number.isFinite(Number(row[key]))))
    .slice(-90);
  if (!rows.length) {
    return <DataTable rows={chart.data} columns={chartTableColumns(chart)} />;
  }

  const width = 960;
  const height = 330;
  const padding = { top: 18, right: 56, bottom: 34, left: 56 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const lows = rows.map((row) => Number(row.low));
  const highs = rows.map((row) => Number(row.high));
  const minValue = Math.min(...lows);
  const maxValue = Math.max(...highs);
  const valueRange = maxValue - minValue || 1;
  const xFor = (index) => padding.left + (rows.length === 1 ? plotWidth / 2 : (index * plotWidth) / (rows.length - 1));
  const yFor = (value) => padding.top + ((maxValue - value) / valueRange) * plotHeight;
  const candleWidth = Math.max(3, Math.min(10, plotWidth / rows.length * 0.58));
  const labelRows = rows.filter((_, index) => index === 0 || index === rows.length - 1 || index % Math.ceil(rows.length / 4) === 0);
  const latestRows = rows.slice(-8).reverse();

  return (
    <div className="candlestick-wrap">
      <svg className="candlestick-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={chart.title}>
        <line x1={padding.left} y1={padding.top} x2={padding.left} y2={height - padding.bottom} />
        <line x1={padding.left} y1={height - padding.bottom} x2={width - padding.right} y2={height - padding.bottom} />
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
          const value = maxValue - valueRange * ratio;
          const y = yFor(value);
          return (
            <g key={ratio}>
              <line className="grid-line" x1={padding.left} y1={y} x2={width - padding.right} y2={y} />
              <text x={width - padding.right + 8} y={y + 4}>{compactNumber(value)}</text>
            </g>
          );
        })}
        {rows.map((row, index) => {
          const open = Number(row.open);
          const high = Number(row.high);
          const low = Number(row.low);
          const close = Number(row.close);
          const x = xFor(index);
          const up = close >= open;
          const top = yFor(Math.max(open, close));
          const bottom = yFor(Math.min(open, close));
          const bodyHeight = Math.max(2, bottom - top);
          return (
            <g key={`${row.date}-${index}`} className={up ? 'candle-up' : 'candle-down'}>
              <line x1={x} y1={yFor(high)} x2={x} y2={yFor(low)} />
              <rect x={x - candleWidth / 2} y={top} width={candleWidth} height={bodyHeight} rx="1" />
            </g>
          );
        })}
        {labelRows.map((row, index) => (
          <text key={`${row.date}-${index}`} className="x-label" x={xFor(rows.indexOf(row))} y={height - 10}>
            {String(row.date).slice(5)}
          </text>
        ))}
      </svg>
      <DataTable rows={latestRows} columns={['date', 'open', 'high', 'low', 'close']} />
    </div>
  );
}

function InsightGrid({ insights, dataType }) {
  if (!insights.length) return null;
  const typeClass = dataType === 'Unknown' ? 'unknown-insights' : '';
  const sortedInsights = insights
    .map(normalizeInsight)
    .sort((left, right) => insightLevelRank(left.level) - insightLevelRank(right.level));

  return (
    <section className="dashboard-section">
      <SectionHeader title="핵심 인사이트" subtitle="투자 판단 전에 먼저 확인해야 할 위험, 경고, 긍정 신호를 우선순위대로 보여줍니다." />
      <div className={`insight-grid ${typeClass}`}>
        {sortedInsights.slice(0, 6).map((normalized, index) => {
          return (
            <article className={`card insight-card ${typeClass} ${normalized.level.toLowerCase()}`} key={`${normalized.title}-${index}`}>
              <span className="insight-level">{translateInsightLevel(normalized.level)}</span>
              <strong>{normalized.title}</strong>
              <p>{normalized.message}</p>
              <small>근거: {normalized.evidence}</small>
              <small>확인 포인트: {normalized.check_point}</small>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function insightLevelRank(level) {
  const ranks = { Risk: 0, Warning: 1, Positive: 2, Info: 3, Neutral: 4 };
  return ranks[level] ?? 9;
}

function translateInsightLevel(level) {
  const labels = {
    Risk: '위험',
    Warning: '경고',
    Positive: '긍정',
    Info: '정보',
    Neutral: '중립',
  };
  return labels[level] ?? level;
}

function normalizeInsight(item) {
  if (item && typeof item === 'object') {
    return {
      title: item.title || '인사이트',
      level: item.level || 'Info',
      message: item.message || '',
      evidence: item.evidence || '-',
      check_point: item.check_point || '관련 지표 확인',
    };
  }
  return {
    title: '데이터 해석',
    level: 'Info',
    message: String(item),
    evidence: '-',
    check_point: '관련 지표와 차트 확인',
  };
}

function PreviewTable({ rows }) {
  const columns = useMemo(() => {
    const firstRow = rows[0] ?? {};
    return Object.keys(firstRow);
  }, [rows]);

  if (!rows.length) return null;

  return (
    <section className="card preview-card">
      <div className="chart-heading">
        <div>
          <h2>Preview</h2>
          <p>표준화 및 전처리 후 상위 행입니다.</p>
        </div>
      </div>
      <DataTable rows={rows} columns={columns} />
    </section>
  );
}

function DataTable({ rows, columns }) {
  const visibleColumns = columns ?? Object.keys(rows[0] ?? {});

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {visibleColumns.map((column) => (
              <th key={column}>{displayColumnLabel(column)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {visibleColumns.map((column) => (
                <td key={column}>{formatCell(row[column], column)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function displayColumnLabel(column) {
  const labels = {
    item: '항목',
    label: '항목',
    value: '값',
    detail: '설명',
    rule: '규칙',
    applied: '적용 내용',
    indicator: '지표',
    status: '상태',
    reason: '사유',
    chart: '차트',
    type: '유형',
    selected_by_rule: '선택 규칙',
    original_column: '원본 컬럼',
    standard_column: '표준 컬럼',
    date: '날짜',
    close: '종가',
    daily_return: '일간 수익률',
    cumulative_return: '누적 수익률',
    drawdown: '낙폭',
    volume: '거래량',
    ticker: '티커',
    asset: '자산',
    asset_name: '자산명',
    weight: '비중',
    sector: '섹터',
    concentration_flag: '집중도 플래그',
    annualized_volatility: '연환산 변동성',
    MDD: 'MDD',
    mdd: 'MDD',
    sharpe_ratio: '샤프비율',
    correlation_note: '상관관계 메모',
    column: '컬럼',
    dtype: '데이터 타입',
    non_null: '유효 값',
    missing: '결측치',
    unique: '고유값',
    missing_ratio: '결측률',
    mean: '평균',
    std: '표준편차',
    min: '최솟값',
    p25: '25%',
    median: '중앙값',
    p75: '75%',
    max: '최댓값',
  };
  return labels[column] ?? column;
}

function isWideChart(chart, dataType) {
  const chartType = chart.chart_type ?? chart.type;
  if (chartType === 'table' || chartType === 'heatmap') return true;
  if (dataType === 'Unknown' && chartType === 'bar' && chart.data?.length > 8) return true;
  return false;
}

function hasRenderableChart(chart) {
  if (!chart || !Array.isArray(chart.data) || chart.data.length === 0) return false;
  const chartType = chart.chart_type ?? chart.type;
  if (chartType === 'table' || chartType === 'heatmap' || chartType === 'candlestick') return true;
  const yKeys = chart.y_keys ?? chart.y_columns ?? chart.y ?? [];
  if (!yKeys.length) return true;
  return chart.data.some((row) => yKeys.some((key) => Number.isFinite(Number(row[key]))));
}

function getMarketRegime(marketRegime) {
  if (!marketRegime) return '';
  if (typeof marketRegime === 'string') return marketRegime;
  return marketRegime.label || '';
}

function getAssetClass(assetClass) {
  if (!assetClass) return '';
  if (typeof assetClass === 'string') return assetClass;
  return assetClass.primary || '';
}

function badgeClass(value) {
  return String(value).toLowerCase().replace(/[^a-z0-9]+/g, '-');
}

function chartTableColumns(chart) {
  const rowKeys = Object.keys(chart.data?.[0] ?? {});
  const preferred = [chart.x_key ?? chart.x_column ?? chart.x, ...((chart.y_keys ?? chart.y_columns ?? chart.y) ?? [])].filter(Boolean);
  return [...new Set([...preferred, ...rowKeys])].filter((key) => rowKeys.includes(key));
}

function formatValue(value, valueFormat) {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  if (valueFormat === 'text') return translateDisplayValue(value);
  if (valueFormat === 'integer') return formatInteger(value);
  if (valueFormat === 'percent') return `${(Number(value) * 100).toFixed(2)}%`;
  if (typeof value === 'number') return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
  return translateDisplayValue(value);
}

function formatCell(value, column) {
  if (value === null || value === undefined) return '-';
  const lowered = String(column).toLowerCase();
  if (
    typeof value === 'number'
    && (lowered.includes('ratio')
      || lowered.includes('weight')
      || lowered.includes('return')
      || lowered.includes('volatility')
      || lowered.includes('mdd')
      || lowered.includes('drawdown')
      || lowered.includes('var'))
  ) return formatValue(value, 'percent');
  if (typeof value === 'number') return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
  if (Array.isArray(value)) return formatList(value);
  if (typeof value === 'object') return formatObject(value);
  return translateDisplayValue(value);
}

function translateDisplayValue(value) {
  const text = String(value);
  const labels = {
    calculated: '계산됨',
    not_calculated: '계산 불가',
    warning: '경고',
    Good: '양호',
    Warning: '경고',
    Risk: '위험',
    Invalid: '유효하지 않음',
    Unknown: '분류 불가',
    unknown: '알 수 없음',
    high: '높음',
    medium: '보통',
    low: '낮음',
    normal: '보통',
    single_asset_concentration: '단일 자산 집중',
    top3_concentration: '상위 3개 자산 집중',
    correlation_not_available: '상관관계 계산 불가',
    partially_supported: '부분 지원',
  };
  return labels[text] ?? text;
}

function formatList(value) {
  if (!Array.isArray(value) || value.length === 0) return '-';
  return value.slice(0, 8).join(', ') + (value.length > 8 ? ` 외 ${value.length - 8}개` : '');
}

function formatObject(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return '-';
  const entries = Object.entries(value);
  if (!entries.length) return '-';
  return entries
    .slice(0, 6)
    .map(([key, item]) => `${key}: ${item}`)
    .join(', ') + (entries.length > 6 ? ` 외 ${entries.length - 6}개` : '');
}

function formatMapping(value) {
  if (!Array.isArray(value) || !value.length) return '';
  return value
    .slice(0, 8)
    .map((item) => `${item.original_column}→${item.standard_column}`)
    .join(', ') + (value.length > 8 ? ` 외 ${value.length - 8}개` : '');
}

function formatInteger(value) {
  const numberValue = Number(value ?? 0);
  return Number.isFinite(numberValue) ? numberValue.toLocaleString() : '-';
}

function compactNumber(value) {
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue)) return '';
  if (Math.abs(numberValue) >= 1000000) return `${(numberValue / 1000000).toFixed(1)}M`;
  if (Math.abs(numberValue) >= 1000) return `${(numberValue / 1000).toFixed(1)}K`;
  return numberValue.toFixed(Math.abs(numberValue) < 1 ? 2 : 0);
}

function formatTooltipValue(value) {
  if (typeof value !== 'number') return value;
  return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function formatPercentMaybe(value, key) {
  if (typeof value !== 'number') return value;
  if (String(key).includes('weight') || String(key).includes('return') || String(key).includes('volatility') || String(key).toLowerCase().includes('mdd') || String(key).includes('drawdown')) {
    return `${(value * 100).toFixed(2)}%`;
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function correlationColor(value) {
  if (typeof value !== 'number') return '#f5f7fa';
  const normalized = Math.max(-1, Math.min(1, value));
  if (normalized >= 0) {
    const alpha = 0.12 + normalized * 0.48;
    return `rgba(22, 138, 113, ${alpha})`;
  }
  const alpha = 0.12 + Math.abs(normalized) * 0.48;
  return `rgba(220, 38, 38, ${alpha})`;
}

export default App;
