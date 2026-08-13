import { redirect } from "next/navigation";

/**
 * Founder decision: /billing is the canonical route for the billing/credits
 * surface. /usage rendered the identical BillingManagement component with
 * no distinct content — see docs/commercial/COMMERCIAL_SHELL_CURRENT_STATE.md.
 *
 * The /usage concept is deliberately kept, not deleted: the founder wants it
 * available again as a distinct usage-analytics surface once that capability
 * exists. Until then it is a live redirect, not a dead route.
 */
export default function UsagePage(): never {
  redirect("/billing");
}
