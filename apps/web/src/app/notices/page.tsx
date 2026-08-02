import {
  ArrowSquareOut,
  FileText,
  Scales,
  ShieldCheck,
} from "@phosphor-icons/react/dist/ssr";
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Help & notices",
};

export default function NoticesPage() {
  return (
    <div className="simple-page notices-page">
      <h1>Help and notices</h1>
      <p>
        Clear documentation of our technology, data handling, accuracy limits,
        and support process.
      </p>
      <div className="notice-grid">
        <article className="panel notice-card" id="privacy">
          <ShieldCheck size={20} weight="fill" />
          <h2>Security and privacy</h2>
          <p>
            Inspect external-transfer consent, retention and deletion, incident
            response, and subprocessor policies.
          </p>
          <Link href="/legal/privacy">
            Privacy and data handling
            <ArrowSquareOut size={14} />
          </Link>
        </article>
        <article className="panel notice-card" id="opensource">
          <Scales size={20} weight="fill" />
          <h2>Open Source Notices</h2>
          <p>
            Inspect model weights, code, runtime, and dataset licenses
            separately.
          </p>
          <Link href="/legal/third-party-notices">
            Dependency notices
            <ArrowSquareOut size={14} />
          </Link>
        </article>
        <article className="panel notice-card">
          <FileText size={20} weight="fill" />
          <h2>Output accuracy and integrity</h2>
          <p>
            We show evidence links and numeric or table warnings—not synthetic
            confidence scores.
          </p>
          <Link href="/integrity">
            Open Integrity Console
            <ArrowSquareOut size={14} />
          </Link>
        </article>
      </div>
    </div>
  );
}
