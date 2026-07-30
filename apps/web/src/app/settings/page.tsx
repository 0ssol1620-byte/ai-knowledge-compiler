import {
  Buildings,
  Check,
  CreditCard,
  Database,
  Key,
  LockKey,
  ShieldCheck,
  UsersThree,
} from "@phosphor-icons/react/dist/ssr";
import type { Metadata } from "next";

import { SettingsLive } from "@/components/settings-live";

export const metadata: Metadata = {
  title: "Settings",
};

export default function SettingsPage() {
  if (process.env.NEXT_PUBLIC_AKC_DEMO_MODE !== "true") {
    return <SettingsLive />;
  }
  return <DemoSettingsPage />;
}

function DemoSettingsPage() {
  return (
    <div className="simple-page settings-page">
      <h1>Settings</h1>
      <p>
        Manage retention, external processing, roles, and credit policy for this
        workspace.
      </p>

      <div className="settings-layout">
        <nav className="settings-nav" aria-label="Settings sections">
          <a href="#privacy" className="active">
            <ShieldCheck size={16} weight="fill" />
            Privacy & processing
          </a>
          <a href="#retention">
            <Database size={16} />
            Retention & deletion
          </a>
          <a href="#members">
            <UsersThree size={16} />
            Members & roles
          </a>
          <a href="#api">
            <Key size={16} />
            API·Webhook
          </a>
          <a href="#billing">
            <CreditCard size={16} />
            Plan & credits
          </a>
        </nav>

        <div className="settings-content">
          <section className="settings-section" id="privacy">
            <header>
              <div>
                <h2>External processing policy</h2>
                <p>Sending pages to model providers is off by default.</p>
              </div>
              <span className="policy-state safe">
                <LockKey size={13} weight="fill" />
                Private default
              </span>
            </header>
            <label className="setting-row">
              <span>
                <strong>External model API fallback</strong>
                <small>
                  Used only for the minimum set of pages that internal parsers
                  cannot process, with notice before every use.
                </small>
              </span>
              <input type="checkbox" className="switch" />
            </label>
            <label className="setting-row">
              <span>
                <strong>Product improvement data</strong>
                <small>
                  No document or correction enters a training pool before
                  explicit opt-in.
                </small>
              </span>
              <input type="checkbox" className="switch" />
            </label>
            <label className="setting-row">
              <span>
                <strong>Mask detected secrets in previews</strong>
                <small>
                  Preserve the source and mask only the UI and external transfer
                  candidates.
                </small>
              </span>
              <input type="checkbox" className="switch" defaultChecked />
            </label>
          </section>

          <section className="settings-section" id="retention">
            <header>
              <div>
                <h2>Retention & deletion</h2>
                <p>Manage source and derived-data lifecycles separately.</p>
              </div>
            </header>
            <div className="retention-grid">
              <label>
                <span>Verified sources</span>
                <select defaultValue="7">
                  <option value="1">24 hours</option>
                  <option value="7">7 days</option>
                  <option value="30">30 days</option>
                  <option value="project">Project lifetime</option>
                </select>
              </label>
              <label>
                <span>Raw model response</span>
                <select defaultValue="7">
                  <option value="1">24 hours</option>
                  <option value="7">7 days</option>
                  <option value="30">30 days</option>
                </select>
              </label>
              <label>
                <span>Final exports</span>
                <select defaultValue="30">
                  <option value="7">7 days</option>
                  <option value="30">30 days</option>
                  <option value="project">Project lifetime</option>
                </select>
              </label>
            </div>
            <div className="deletion-assurance">
              <Check size={15} weight="bold" />
              Deletion checks source, render, crop, raw response, export, vector
              index, and cache before issuing a content-free deletion receipt.
            </div>
          </section>

          <section className="settings-section" id="members">
            <header>
              <div>
                <h2>Workspace</h2>
                <p>
                  Separate project, review, and billing permissions by role.
                </p>
              </div>
              <button type="button" className="secondary-button compact">
                <Buildings size={14} />
                Invite member
              </button>
            </header>
            <div className="member-row">
              <span className="avatar">YS</span>
              <span>
                <strong>Workspace owner</strong>
                <small>you@example.com</small>
              </span>
              <span className="status-badge neutral">Owner</span>
            </div>
          </section>

          <div className="settings-save">
            <span>Changes are recorded in the audit log.</span>
            <button className="primary-button" type="button">
              Save settings
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
