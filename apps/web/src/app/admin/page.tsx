import {
  ArrowClockwise,
  CheckCircle,
  Database,
  Queue,
  Warning,
} from "@phosphor-icons/react/dist/ssr";
import type { Metadata } from "next";

import { AdminLive } from "@/components/admin-live";

export const metadata: Metadata = {
  title: "Operations console",
};

export default function AdminPage() {
  if (process.env.NEXT_PUBLIC_AKC_DEMO_MODE !== "true") {
    return <AdminLive />;
  }
  return <DemoAdminPage />;
}

function DemoAdminPage() {
  return (
    <div className="simple-page admin-page">
      <h1>Operations console</h1>
      <p>
        Illustrative operations snapshot. Connect an authorized control plane to
        retry jobs or change durable state; document content is never shown
        here.
      </p>
      <section className="admin-health-grid">
        <article>
          <Database size={18} weight="fill" />
          <span>PostgreSQL</span>
          <strong>Healthy</strong>
        </article>
        <article>
          <Queue size={18} weight="fill" />
          <span>Oldest queue age</span>
          <strong>4.2s</strong>
        </article>
        <article>
          <CheckCircle size={18} weight="fill" />
          <span>Terminal success</span>
          <strong>99.7%</strong>
        </article>
        <article>
          <Warning size={18} weight="fill" />
          <span>DLQ</span>
          <strong>2</strong>
        </article>
      </section>
      <section className="panel admin-table-panel">
        <div className="panel-heading">
          <div>
            <h2>Jobs requiring intervention</h2>
            <p>
              Content, filenames, and email addresses never appear in this view
              or its logs.
            </p>
          </div>
        </div>
        <table className="admin-table">
          <thead>
            <tr>
              <th>Job</th>
              <th>Error</th>
              <th>Route history</th>
              <th>Attempts</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <code>job_28c9…</code>
              </td>
              <td>PROVIDER_TIMEOUT</td>
              <td>native → paddle</td>
              <td>2 / 3</td>
              <td>
                <button
                  className="secondary-button compact"
                  type="button"
                  disabled
                  title="Retry requires an authorized live control plane."
                  data-demo-static-control
                >
                  <ArrowClockwise size={13} />
                  Retry page
                </button>
              </td>
            </tr>
            <tr>
              <td>
                <code>job_1ac4…</code>
              </td>
              <td>DELETE_OBJECT_RETRY</td>
              <td>purging</td>
              <td>3 / 5</td>
              <td>
                <button
                  className="secondary-button compact"
                  type="button"
                  disabled
                  title="Purge recovery requires an authorized live control plane."
                  data-demo-static-control
                >
                  <ArrowClockwise size={13} />
                  Resume purge
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>
  );
}
