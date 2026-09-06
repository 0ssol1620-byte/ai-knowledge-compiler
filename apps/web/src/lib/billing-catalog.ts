export type CanonicalPlan = {
  code: "evaluation" | "developer" | "team" | "scale" | "enterprise";
  name: string;
  price: string;
  cadence: string;
  includedPages: number | null;
  commerciallyQualified: boolean;
  includes: readonly string[];
};

export const CANONICAL_PLANS: readonly CanonicalPlan[] = [
  { code: "evaluation", name: "Evaluation", price: "$0", cadence: "no card", includedPages: 500, commerciallyQualified: true, includes: ["1 workspace", "Manual upload", "World + Ask", "Short retention"] },
  { code: "developer", name: "Developer", price: "$29", cadence: "per month", includedPages: 500, commerciallyQualified: true, includes: ["1 workspace", "API + MCP", "1 active connector", "Usage overage"] },
  { code: "team", name: "Team", price: "$99", cadence: "per month", includedPages: 2_500, commerciallyQualified: true, includes: ["Up to 5 seats", "Review workflow", "Version history", "Budget controls"] },
  { code: "scale", name: "Scale", price: "Qualification", cadence: "COGS gate required", includedPages: null, commerciallyQualified: false, includes: ["Multiple workspaces", "Higher concurrency", "Priority processing", "Team roles"] },
  { code: "enterprise", name: "Enterprise", price: "Custom", cadence: "qualified scope", includedPages: null, commerciallyQualified: false, includes: ["SSO / SAML / SCIM", "Audit export", "Region + retention", "VPC / BYOC / dedicated"] },
] as const;
