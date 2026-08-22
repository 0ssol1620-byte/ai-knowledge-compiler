export const PROCESSING_EVENT_BATCH_MS = 100;

export const PROCESSING_THEATER_STAGES = [
  {
    id: "collect",
    label: "COLLECT",
    members: ["upload", "security_scan", "preflight"],
  },
  {
    id: "understand",
    label: "UNDERSTAND",
    members: ["extract", "normalize"],
  },
  { id: "verify", label: "VERIFY", members: ["validate"] },
  { id: "compile", label: "COMPILE", members: ["knowledge"] },
  { id: "architect", label: "ARCHITECT", members: ["architecture"] },
  { id: "package", label: "PACKAGE", members: ["package"] },
] as const;

export type ProcessingTheaterStageId =
  (typeof PROCESSING_THEATER_STAGES)[number]["id"];

export function localizedProcessingStageLabel(
  stage: ProcessingTheaterStageId,
  locale: "en" | "ko",
): string {
  if (locale === "en") {
    return PROCESSING_THEATER_STAGES.find((item) => item.id === stage)!.label;
  }
  return {
    collect: "수집",
    understand: "이해",
    verify: "검증",
    compile: "컴파일",
    architect: "설계",
    package: "패키지",
  }[stage];
}

const EVENT_STAGE_PREFIXES: ReadonlyArray<
  readonly [string, ProcessingTheaterStageId]
> = [
  ["collection.", "collect"],
  ["file.", "collect"],
  ["preflight.", "collect"],
  ["estimate.", "collect"],
  ["credits.reserved.", "collect"],
  ["processing.started.", "understand"],
  ["page.route.", "understand"],
  ["page.rendered.", "understand"],
  ["region.detected.", "understand"],
  ["region.route.", "understand"],
  ["block.completed.", "understand"],
  ["table.reconstructed.", "understand"],
  ["numeric.authority.", "verify"],
  ["verification.", "verify"],
  ["repair.", "verify"],
  ["output.quarantined.", "verify"],
  ["note.created.", "compile"],
  ["entity.resolved.", "compile"],
  ["relation.created.", "compile"],
  ["architecture.", "architect"],
  ["export.", "package"],
  ["package.", "package"],
  ["credits.consumed.", "package"],
  ["credits.released.", "package"],
];

export function collectionEventStage(
  eventType: string,
): ProcessingTheaterStageId | undefined {
  return EVENT_STAGE_PREFIXES.find(([prefix]) =>
    eventType.startsWith(prefix),
  )?.[1];
}

export function groupedProcessingStageFraction(
  progress: Record<string, { done: number; total: number }>,
  members: readonly string[],
): number {
  const allMembersReported = members.every(
    (member) => (progress[member]?.total ?? 0) > 0,
  );
  const totals = members.reduce(
    (result, member) => {
      const value = progress[member];
      if (value && value.total > 0) {
        result.done += value.done;
        result.total += value.total;
      }
      return result;
    },
    { done: 0, total: 0 },
  );
  if (totals.total === 0) return 0;
  const fraction = Math.max(0, Math.min(1, totals.done / totals.total));
  return allMembersReported ? fraction : Math.min(fraction, 0.99);
}
