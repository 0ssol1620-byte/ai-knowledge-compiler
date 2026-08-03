import { z } from "zod";

const uuid = z.string().uuid();

export const sceneSchema = z.object({
  schema_version: z.literal("1.0"),
  job_id: uuid,
  status: z.string(),
  terminal: z.boolean(),
  pages_total: z.number().int().nonnegative(),
  page_state_counts: z.record(z.string(), z.number().int().nonnegative()),
  accepted_blocks: z.number().int().nonnegative(),
  unresolved_recoveries: z.number().int().nonnegative(),
  progress: z.record(z.string(), z.unknown()),
  generated_at: z.string(),
});

export const qualitySummarySchema = z.object({
  schema_version: z.literal("1.0"),
  job_id: uuid,
  verified_count: z.number().int().nonnegative(),
  recovered_verified_count: z.number().int().nonnegative(),
  unresolved_count: z.number().int().nonnegative(),
  excluded_count: z.number().int().nonnegative(),
  critical_false_verified_count: z.number().int().nonnegative(),
  silent_omission_count: z.number().int().nonnegative(),
  verified_coverage: z.number().min(0).max(1),
  accepted_precision: z.number().min(0).max(1).nullable(),
  publishable: z.boolean(),
  reason_codes: z.array(z.string()),
  limitations: z.array(z.string()),
});

export const proofSchema = z.object({
  schema_version: z.literal("1.0"),
  proof_id: uuid,
  collection_id: uuid,
  status: z.string(),
  validator_revision: z.string(),
  target: z.object({
    collection_file_id: uuid.nullable(),
    region_id: uuid.nullable(),
  }),
  evidence: z.record(z.string(), z.unknown()),
  crop_url: z.string().startsWith("/v1/proofs/"),
  created_at: z.string(),
});

export const recoverySchema = z.object({
  schema_version: z.literal("1.0"),
  recovery_id: uuid,
  document_id: uuid,
  state: z.string(),
  recovery_level: z.string(),
  reason_code: z.string(),
  target: z.record(z.string(), z.unknown()),
  preprocessing_variants: z.array(z.string()),
  route_candidates: z.array(z.string()),
  source_attempt_id: uuid,
  result_attempt_id: uuid.nullable(),
  created_at: z.string(),
  completed_at: z.string().nullable(),
});

export const trustReceiptSchema = z.object({
  schema_version: z.literal("1.0"),
  package_id: uuid,
  collection_id: uuid,
  status: z.string(),
  signature_status: z.string(),
  manifest_sha256: z.string().length(64).nullable(),
  package_sha256: z.string().length(64).nullable(),
  file_count: z.number().int().nonnegative(),
  validation_status: z.string(),
  validation_evidence_sha256: z.string().length(64).nullable(),
  warnings: z.array(z.string()),
  issued_at: z.string(),
  receipt_sha256: z.string().length(64),
});

async function getJson<T>(path: string, schema: z.ZodType<T>): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Trust API ${response.status}`);
  return schema.parse(await response.json());
}

export const trustClient = {
  scene: (jobId: string) => getJson(`/v1/jobs/${jobId}/scene`, sceneSchema),
  qualitySummary: (jobId: string) =>
    getJson(`/v1/jobs/${jobId}/quality-summary`, qualitySummarySchema),
  proof: (proofId: string) => getJson(`/v1/proofs/${proofId}`, proofSchema),
  recovery: (recoveryId: string) =>
    getJson(`/v1/recovery/${recoveryId}`, recoverySchema),
  trustReceipt: (packageId: string) =>
    getJson(`/v1/packages/${packageId}/trust-receipt`, trustReceiptSchema),
};

export type SceneResponse = z.infer<typeof sceneSchema>;
export type QualitySummaryResponse = z.infer<typeof qualitySummarySchema>;
