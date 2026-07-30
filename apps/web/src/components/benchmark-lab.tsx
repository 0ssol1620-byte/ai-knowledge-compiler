import {
  CheckCircle,
  Database,
  Gauge,
  LockKey,
  MagnifyingGlass,
} from "@phosphor-icons/react/dist/ssr";

import {
  formatBenchmarkCost,
  formatBenchmarkLatency,
  formatBenchmarkPercent,
  publicBenchmarkSnapshot,
} from "@/lib/benchmark-public";

const statusLabel = {
  available: "검증 완료",
  source_adapter_ready: "수집기 검증 완료",
  evidence_required: "코퍼스 필요",
} as const;

export function BenchmarkLab() {
  const snapshot = publicBenchmarkSnapshot;
  const isAvailable = snapshot.status === "available";

  return (
    <main className="simple-page benchmark-lab-page" id="main-content">
      <header className="benchmark-lab-heading">
        <div>
          <h1>Benchmark Lab</h1>
          <p>
            문서 유형별 텍스트·숫자·표·출처 정확도와 처리 지연, 페이지당 비용을
            같은 코퍼스와 평가기로 비교합니다.
          </p>
        </div>
        <span className="benchmark-release-state" data-ready={isAvailable}>
          {isAvailable ? (
            <CheckCircle size={17} weight="fill" aria-hidden="true" />
          ) : (
            <LockKey size={17} aria-hidden="true" />
          )}
          {isAvailable ? "공개 가능한 증거 번들" : "공개 성능 수치 잠금"}
        </span>
      </header>

      {!isAvailable && (
        <section
          className="benchmark-evidence-notice"
          aria-labelledby="benchmark-evidence-title"
        >
          <MagnifyingGlass size={22} aria-hidden="true" />
          <div>
            <h2 id="benchmark-evidence-title">
              아직 공개할 수 있는 성능 수치가 없습니다.
            </h2>
            <p>
              DART 수집기와 평가 계약은 준비됐습니다. 권리가 확인된 골든 코퍼스,
              독립 라벨 검수, 실제 모델·하드웨어 실행과 승인된 증거 번들이
              갖춰질 때까지 숫자를 만들거나 0으로 대체하지 않습니다.
            </p>
          </div>
        </section>
      )}

      <section
        className="benchmark-results-region"
        aria-labelledby="benchmark-results-title"
      >
        <div className="benchmark-results-heading">
          <div>
            <h2 id="benchmark-results-title">문서 유형별 결과</h2>
            <p>측정되지 않은 셀은 ‘측정 전’으로 유지됩니다.</p>
          </div>
          <span>Evaluator {snapshot.evaluator_version}</span>
        </div>
        <div className="benchmark-table-frame">
          <table>
            <caption className="sr-only">
              공개 가능한 문서 유형별 벤치마크 결과
            </caption>
            <thead>
              <tr>
                <th scope="col">문서 유형</th>
                <th scope="col">상태</th>
                <th scope="col">텍스트</th>
                <th scope="col">숫자</th>
                <th scope="col">표</th>
                <th scope="col">출처</th>
                <th scope="col">p95 지연</th>
                <th scope="col">페이지 비용</th>
              </tr>
            </thead>
            <tbody>
              {snapshot.datasets.map((dataset) => (
                <tr key={dataset.id}>
                  <th scope="row">
                    <strong>{dataset.label}</strong>
                    <span>{dataset.source}</span>
                  </th>
                  <td>
                    <span className={`benchmark-status ${dataset.status}`}>
                      {statusLabel[dataset.status]}
                    </span>
                  </td>
                  <td>{formatBenchmarkPercent(dataset.metrics.text)}</td>
                  <td>{formatBenchmarkPercent(dataset.metrics.numbers)}</td>
                  <td>{formatBenchmarkPercent(dataset.metrics.tables)}</td>
                  <td>{formatBenchmarkPercent(dataset.metrics.provenance)}</td>
                  <td>
                    {formatBenchmarkLatency(dataset.metrics.p95_latency_ms)}
                  </td>
                  <td>
                    {formatBenchmarkCost(dataset.metrics.cost_per_page_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section
        className="benchmark-methodology"
        aria-labelledby="benchmark-method-title"
      >
        <div className="benchmark-method-intro">
          <Gauge size={22} aria-hidden="true" />
          <div>
            <h2 id="benchmark-method-title">점수보다 먼저 고정하는 것</h2>
            <p>
              평균값 하나로 실패 사례를 숨기지 않습니다. 결과에는 코퍼스,
              평가기, 모델, 실행 환경과 원시 실패가 함께 묶입니다.
            </p>
          </div>
        </div>
        <dl>
          <div>
            <dt>코퍼스</dt>
            <dd>권리 확인, 분할 해시, 홀드아웃 격리, 라벨 검수</dd>
          </div>
          <div>
            <dt>평가</dt>
            <dd>문자·숫자·표·수식·읽기 순서·출처를 별도 측정</dd>
          </div>
          <div>
            <dt>실행</dt>
            <dd>모델 리비전, 이미지 다이제스트, GPU와 cold/warm 반복</dd>
          </div>
          <div>
            <dt>공개</dt>
            <dd>원시 실패 포함, 증거 번들 SHA-256과 승인 기록 필요</dd>
          </div>
        </dl>
      </section>

      <section className="benchmark-source-note" aria-label="DART 데이터 경계">
        <Database size={20} aria-hidden="true" />
        <p>
          OpenDART는 공개 원문 수집에만 사용합니다. 수집된 사업보고서는 자동으로
          정답 데이터가 되지 않으며, 사용자 문서나 고객 데이터는 벤치마크에
          사용하지 않습니다.
        </p>
      </section>
    </main>
  );
}
