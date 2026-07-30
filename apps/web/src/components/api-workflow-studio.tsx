import {
  ArrowRight,
  BracketsCurly,
  CheckCircle,
  Copy,
  Database,
  FlowArrow,
  Key,
  WebhooksLogo,
} from "@phosphor-icons/react/dist/ssr";

export function ApiWorkflowStudio() {
  const demoMode = process.env.NEXT_PUBLIC_AKC_DEMO_MODE === "true";
  return (
    <div className="simple-page api-workflow-page">
      <div className="developer-title">
        <div>
          <h1>API & 워크플로</h1>
          <p>
            업로드, 처리 profile, 지식 출력과 webhook을 하나의 검증 가능한
            파이프라인으로 구성합니다.
          </p>
        </div>
        <span className="demo-sample-chip">
          {demoMode ? "Sample workflow" : "Live configuration"}
        </span>
      </div>

      <section className="panel developer-quickstart">
        <div>
          <span>01</span>
          <Key size={20} weight="duotone" aria-hidden="true" />
          <strong>API key</strong>
          <small>권한 범위와 만료를 지정</small>
        </div>
        <ArrowRight size={16} aria-hidden="true" />
        <div>
          <span>02</span>
          <BracketsCurly size={20} weight="duotone" aria-hidden="true" />
          <strong>Upload & compile</strong>
          <small>idempotency key로 안전하게 요청</small>
        </div>
        <ArrowRight size={16} aria-hidden="true" />
        <div>
          <span>03</span>
          <WebhooksLogo size={20} weight="duotone" aria-hidden="true" />
          <strong>Webhook</strong>
          <small>서명된 완료 이벤트 수신</small>
        </div>
      </section>

      <div className="workflow-grid">
        <section className="panel workflow-builder">
          <div className="panel-heading">
            <div>
              <h2>Workflow</h2>
              <p>복잡한 DAG 대신 운영에 필요한 네 단계만 구성합니다.</p>
            </div>
          </div>
          <div className="workflow-lane">
            {[
              [Database, "Source", "Multipart upload"],
              [FlowArrow, "Parse profile", "Balanced"],
              [BracketsCurly, "Knowledge", "Grounded notes"],
              [WebhooksLogo, "Destination", "Webhook + export"],
            ].map(([Icon, title, value], index) => {
              const WorkflowIcon = Icon as typeof Database;
              return (
                <div className="workflow-node-wrap" key={String(title)}>
                  <article>
                    <WorkflowIcon
                      size={18}
                      weight="duotone"
                      aria-hidden="true"
                    />
                    <span>{String(title)}</span>
                    <strong>{String(value)}</strong>
                  </article>
                  {index < 3 && <ArrowRight size={16} aria-hidden="true" />}
                </div>
              );
            })}
          </div>
        </section>
        <section className="panel code-sample-panel">
          <div className="panel-heading">
            <div>
              <h2>Quickstart</h2>
              <p>민감 데이터가 없는 요청 예시</p>
            </div>
            <button
              className="icon-button compact"
              type="button"
              aria-label="코드 복사"
            >
              <Copy size={15} />
            </button>
          </div>
          <pre>
            <code>{`curl -X POST /v1/documents/{id}/compile \\
  -H "Idempotency-Key: <unique-key>" \\
  -d '{
    "route_profile": "parse_balanced_v1",
    "output_profiles": ["portable", "rag"]
  }'`}</code>
          </pre>
        </section>
      </div>

      <section className="panel jobs-preview-panel">
        <div className="panel-heading">
          <div>
            <h2>Recent jobs</h2>
            <p>
              {demoMode
                ? "아래 행은 인터페이스 예시이며 실제 작업이 아닙니다."
                : "현재 권한 범위의 라이브 작업만 표시합니다."}
            </p>
          </div>
        </div>
        {demoMode ? (
          <div className="admin-table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Job ID</th>
                  <th>Profile</th>
                  <th>Status</th>
                  <th>Duration</th>
                  <th>Credits</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>
                    <code>sample_job_01</code>
                  </td>
                  <td>Balanced</td>
                  <td>
                    <span className="status-badge green">
                      <CheckCircle size={12} weight="fill" />
                      Sample completed
                    </span>
                  </td>
                  <td>2m 14s</td>
                  <td>38 sample</td>
                </tr>
              </tbody>
            </table>
          </div>
        ) : (
          <div className="honest-state compact">
            <p>작업 API 연결 후 라이브 행이 표시됩니다.</p>
          </div>
        )}
      </section>
    </div>
  );
}
