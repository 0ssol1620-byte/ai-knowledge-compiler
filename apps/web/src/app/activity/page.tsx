import {
  ArrowRight,
  CheckCircle,
  Clock,
  Warning,
} from "@phosphor-icons/react/dist/ssr";
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Activity" };

export default function ActivityPage() {
  return (
    <div className="simple-page activity-page">
      <h1>Activity</h1>
      <p>
        Track active jobs, review queues, and recent completions in one place.
      </p>
      <div className="activity-status-grid">
        <Link href="/workspace" className="panel">
          <Clock size={20} weight="duotone" aria-hidden="true" />
          <span>
            <strong>Processing jobs</strong>
            <small>Inspect page-level status and events</small>
          </span>
          <ArrowRight size={16} aria-hidden="true" />
        </Link>
        <Link href="/review" className="panel">
          <Warning size={20} weight="duotone" aria-hidden="true" />
          <span>
            <strong>Review Studio</strong>
            <small>Resolve issues by risk and impact</small>
          </span>
          <ArrowRight size={16} aria-hidden="true" />
        </Link>
        <Link href="/home" className="panel">
          <CheckCircle size={20} weight="duotone" aria-hidden="true" />
          <span>
            <strong>Recent projects</strong>
            <small>Check completion and export status</small>
          </span>
          <ArrowRight size={16} aria-hidden="true" />
        </Link>
      </div>
    </div>
  );
}
