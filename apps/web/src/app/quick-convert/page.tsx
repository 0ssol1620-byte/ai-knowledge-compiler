import {
  FileText,
  LockKey,
  Receipt,
  ShieldCheck,
  Timer,
} from "@phosphor-icons/react/dist/ssr";
import type { Metadata } from "next";

import { UploadPanel } from "@/components/upload-panel";

export const metadata: Metadata = { title: "Quick convert" };

export default function QuickConvertPage() {
  return (
    <div className="page-shell quick-convert-page">
      <nav className="page-breadcrumb" aria-label="Breadcrumb">
        <span>Jobs</span>
        <span aria-hidden="true">/</span>
        <strong>Quick convert</strong>
      </nav>
      <section className="quick-convert-intro">
        <div>
          <h1>Start a new conversion</h1>
          <p>
            Add documents to run security checks and page analysis first.
            Processing does not begin until you review the time range and
            maximum credit reservation.
          </p>
        </div>
        <div className="quick-convert-policy">
          <LockKey size={18} aria-hidden="true" />
          <span>
            <strong>External APIs off</strong>
            <small>Current workspace default</small>
          </span>
        </div>
      </section>
      <div className="quick-convert-workbench">
        <UploadPanel showPolicy={false} />
        <aside className="preflight-explainer">
          <header>
            <p>After you select files</p>
            <h2>Review the preflight first</h2>
            <span>
              Inspect the analysis, then choose the processing route and output
              formats yourself.
            </span>
          </header>
          <ul>
            <li>
              <ShieldCheck size={19} aria-hidden="true" />
              <span>
                <strong>File safety</strong>
                <small>
                  Integrity, malware, encryption, and supported formats
                </small>
              </span>
            </li>
            <li>
              <FileText size={19} aria-hidden="true" />
              <span>
                <strong>Page composition</strong>
                <small>Native text, OCR, tables, and formula pages</small>
              </span>
            </li>
            <li>
              <Timer size={19} aria-hidden="true" />
              <span>
                <strong>Processing time</strong>
                <small>Estimated completion range and page-level routes</small>
              </span>
            </li>
            <li>
              <Receipt size={19} aria-hidden="true" />
              <span>
                <strong>Credit ceiling</strong>
                <small>
                  Estimated use, maximum reservation, and unused return
                </small>
              </span>
            </li>
          </ul>
        </aside>
      </div>
    </div>
  );
}
