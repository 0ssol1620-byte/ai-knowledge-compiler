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
          <h1>API & workflows</h1>
          <p>
            Compose uploads, processing profiles, knowledge outputs, and
            webhooks into one auditable pipeline.
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
          <small>Set scopes and expiration</small>
        </div>
        <ArrowRight size={16} aria-hidden="true" />
        <div>
          <span>02</span>
          <BracketsCurly size={20} weight="duotone" aria-hidden="true" />
          <strong>Upload & compile</strong>
          <small>Submit safely with an idempotency key</small>
        </div>
        <ArrowRight size={16} aria-hidden="true" />
        <div>
          <span>03</span>
          <WebhooksLogo size={20} weight="duotone" aria-hidden="true" />
          <strong>Webhook</strong>
          <small>Receive signed completion events</small>
        </div>
      </section>

      <div className="workflow-grid">
        <section className="panel workflow-builder">
          <div className="panel-heading">
            <div>
              <h2>Workflow</h2>
              <p>
                Configure the four operational steps you need—without a complex
                DAG.
              </p>
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
              <p>Example request with no sensitive data</p>
            </div>
            <button
              className="icon-button compact"
              type="button"
              aria-label="Copy code"
              disabled
              title="Copy is available in the connected developer workspace."
              data-sample-static-control
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
                ? "The rows below illustrate the interface and are not live jobs."
                : "Only live jobs within the current permission scope are shown."}
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
            <p>Live rows appear after the Jobs API is connected.</p>
          </div>
        )}
      </section>
    </div>
  );
}
