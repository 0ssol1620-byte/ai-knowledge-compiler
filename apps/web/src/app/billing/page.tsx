import type { Metadata } from "next";

import { BillingManagement } from "@/components/billing-management";

export const metadata: Metadata = { title: "Billing" };

export default function BillingPage() {
  return (
    <div className="simple-page billing-page">
      <h1>Billing</h1>
      <p>
        Credit packs, checkout, and your server-confirmed payment history for
        this workspace.
      </p>
      <BillingManagement />
    </div>
  );
}
