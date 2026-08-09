import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export function GET() {
  const revision = deploymentRevision();
  return NextResponse.json(
    {
      status: "ok",
      service: "akc-web",
      revision: revision.value,
      revision_source: revision.source,
      deployment_id: process.env.VERCEL_DEPLOYMENT_ID ?? null,
      environment:
        process.env.VERCEL_ENV ?? process.env.NODE_ENV ?? "unknown",
      generated_at: new Date().toISOString(),
    },
    {
      headers: {
        "Cache-Control": "no-store",
      },
    },
  );
}

function deploymentRevision(): {
  value: string | null;
  source: "vercel" | "github" | "configured" | null;
} {
  const candidates = [
    [process.env.VERCEL_GIT_COMMIT_SHA, "vercel"],
    [process.env.GITHUB_SHA, "github"],
    [process.env.AKC_DEPLOYMENT_REVISION, "configured"],
  ] as const;
  for (const [value, source] of candidates) {
    const normalized = value?.trim().toLowerCase();
    if (normalized && /^[0-9a-f]{40}$/.test(normalized)) {
      return { value: normalized, source };
    }
  }
  return { value: null, source: null };
}
