import type { Metadata } from "next";

import { BillingManagement } from "@/components/billing-management";

export const metadata: Metadata = { title: "Usage & billing" };

export default function UsagePage() {
  return (
    <div className="simple-page usage-page">
      <h1>Usage and credits</h1>
      <p>
        Review credits by processing method, storage, and purchases against the
        verified ledger.
      </p>
      <BillingManagement />
    </div>
  );
}
