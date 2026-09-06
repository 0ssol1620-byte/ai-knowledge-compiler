/**
 * Canonical public copy — §5.
 *
 * This is the only place public strings live. §1.6 fixes the order in which a
 * visitor meets them: scene first, then the plain sentence, then the technical
 * name. Reversing that order is a defect, so plain and technical text are kept
 * as separate fields rather than one blob a component might render together.
 */

/** §5.1 — hero copy sequence, in reveal order. */
export const HERO_SEQUENCE = [
  "YOUR WORK IS EVERYWHERE.",
  "Files. Email. Meetings. Code. Decisions.",
  "TAVONEL UNDERSTANDS WHAT THEY MEAN.",
  "People. Projects. Decisions. Facts.",
  "YOUR DIGITAL WORLD, COMPILED.",
] as const;

export const BRAND_LOCK = {
  name: "TAVONEL",
  category: "THE KNOWLEDGE COMPILER",
} as const;

/** §1.3 — the popular definition. One sentence, no jargon. */
export const THESIS =
  "TAVONEL turns scattered digital information into connected knowledge—and keeps it current as things change.";

/** §5.2 — truth proof. */
export const TRUTH_COPY = {
  question: "WHEN IS PROJECT ATLAS LAUNCHING?",
  candidates: [
    "SEP 01 · superseded launch plan",
    "SEP 15 · meeting note · unapproved",
    "OCT 15 · approved product plan · active",
    "OCT 15 · launch calendar · active",
  ],
  result: { value: "OCTOBER 15", state: "CURRENT · APPROVED · EFFECTIVE" },
  human: "TAVONEL DOESN'T JUST FIND AN ANSWER.\nIT KNOWS WHICH ANSWER IS CURRENT.",
  technical: "AUTHORITY · APPLICABILITY · TEMPORAL VALIDITY",
} as const;

/** §5.3 — change and recompilation. */
export const CHANGE_COPY = {
  field: "Launch date",
  transition: { from: "OCT 15", to: "NOV 03" },
  human: [
    "WHEN SOMETHING CHANGES,\nTAVONEL KNOWS WHAT IT AFFECTS.",
    "ONLY AFFECTED KNOWLEDGE IS UPDATED.",
  ],
  /** §5.3 marks this punchline optional; it is not required for comprehension. */
  optionalPunchline: "NOT RE-INDEXED.\nRECOMPILED.",
  technical: "SEMANTIC DIFF · IMPACT GRAPH · SELECTIVE RECOMPILATION",
} as const;

/** §5.4 — answer and evidence. */
export const ANSWER_COPY = {
  question: "WHAT IS THE CURRENT LAUNCH DATE?",
  value: "NOVEMBER 3",
  state: "CURRENT · APPROVED · EFFECTIVE",
  evidenceClose: "EVERY ANSWER HAS A WAY HOME.",
  promiseClose:
    "KNOW WHAT IS TRUE NOW.\nSEE WHAT CHANGED.\nRETURN EVERY ANSWER TO EVIDENCE.",
} as const;

/** §5.5 — scale copy. Same world, three scales; never three SaaS tabs. */
export const SCALE_COPY = {
  personal: {
    headline: "YOUR PC ALREADY CONTAINS A WORLD.\nTAVONEL COMPILES IT.",
    body: "Your projects. Your people. Your decisions.\nAlways connected. Always current.",
  },
  team: {
    headline: "ONE PERSON HAS CONTEXT.\nA TEAM NEEDS SHARED TRUTH.",
    body: "Shared context. Shared decisions. Shared truth.",
  },
  enterprise: {
    headline: "NOW CONNECT THE COMPANY.",
    body: "One continuously updated view\nof what your organization knows.",
  },
} as const;

/**
 * §5.6 — final CTA. `Try your files` is deliberately absent: it may not become
 * primary until privacy, security, upload boundaries and deletion/retention
 * behaviour are ready *and visible*.
 */
export const CTA = {
  primary: "COMPILE A SAMPLE WORKSPACE →",
  secondary: "SEE THE EVIDENCE PROOF →",
} as const;

/** §4.4 — quiet navigation. It must not compete with the stage. */
export const NAV = {
  brand: "TAVONEL",
  links: [
    { label: "Product", href: "/product" },
    { label: "Evidence", href: "/evidence" },
    { label: "Research", href: "/research" },
  ],
  signIn: { label: "Sign in", href: "/login" },
} as const;

/**
 * §1.6 — plain sentence first, technical name second. A component renders
 * `plain` at full editorial weight and `technical` as a small annotation; it
 * may never render `technical` alone.
 */
export const PLAIN_TO_TECHNICAL = [
  {
    plain: "Alice, A. Kim and alice@company.com are the same person.",
    technical: "Stable identity resolution",
  },
  {
    plain: "It knows which of several documents is valid today.",
    technical: "Authority · applicability · temporal validity",
  },
  {
    plain: "When one sentence changes, it knows what that affects.",
    technical: "Semantic diff · dependency/impact graph",
  },
  {
    plain: "Only the related knowledge is updated.",
    technical: "Selective recompilation",
  },
  {
    plain: "Every answer goes back to its source.",
    technical: "Verifiable provenance",
  },
  {
    plain: "The current state is published as a version.",
    technical: "Versioned world state",
  },
] as const;

/**
 * Per-shot editorial copy — §5.4, distributed across the §5.3 board.
 *
 * §5.4 gives the copy as four blocks; §5.3 gives 24 beats. Mapping one onto the
 * other is this table, and it is the only place that mapping exists. A shot
 * with no entry shows no editorial copy, which is the correct answer for the
 * beats whose whole job is a mechanism — §A-07's public copy field is
 * explicitly "none", and the same holds for its successor H06.
 *
 * `technical` is the quiet instrument annotation that §1.6 allows only *after*
 * the plain sentence. No component may render it alone.
 */
export type ShotCopy = {
  /** Rendered at editorial weight. */
  readonly statement?: string;
  /** Small supporting line under the statement. */
  readonly support?: string;
  /** Instrument-voice annotation. Never rendered without a statement. */
  readonly technical?: string;
};

export const SHOT_COPY: Readonly<Record<string, ShotCopy>> = {
  H01: {
    statement: "YOUR WORK IS EVERYWHERE.",
    support: "Files. Email. Meetings. Code. Decisions.",
  },
  H02: { statement: "TAVONEL READS THE SOURCE, NOT THE FILE NAME." },
  H03: {
    statement: "TAVONEL UNDERSTANDS WHAT THEY MEAN.",
    support: "People. Projects. Decisions. Facts.",
  },
  H04: {
    statement: "ALICE, A. KIM AND ALICE@COMPANY.COM\nARE THE SAME PERSON.",
    technical: "STABLE IDENTITY RESOLUTION",
  },
  H05: {
    statement: "IT KNOWS WHICH VERSION STILL APPLIES.",
    technical: "AUTHORITY · APPLICABILITY · TEMPORAL VALIDITY",
  },
  // H06 carries no copy. The object is the argument.
  H07: { statement: "YOUR DIGITAL WORLD, COMPILED." },
  H08: {
    statement: "TAVONEL",
    support:
      "It turns scattered digital information into a living, connected knowledge system.",
  },
  H09: { statement: "WHEN IS PROJECT ATLAS LAUNCHING?" },
  H10: { statement: "THE DOCUMENTS DISAGREE." },
  H11: {
    statement: "TAVONEL DOESN'T JUST FIND AN ANSWER.\nIT KNOWS WHICH ANSWER IS CURRENT.",
    technical: "AUTHORITY · APPLICABILITY · TEMPORAL VALIDITY",
  },
  H12: { statement: "AND IT KNOWS WHERE THAT ANSWER CAME FROM." },
  H13: { statement: "WHEN SOMETHING CHANGES," },
  H14: {
    statement: "TAVONEL KNOWS WHAT IT AFFECTS.",
    technical: "SEMANTIC DIFF",
  },
  H15: {
    statement: "FOUR THINGS DEPEND ON THAT DATE.\nNOTHING ELSE DOES.",
    technical: "DEPENDENCY · IMPACT GRAPH",
  },
  H16: {
    statement: "ONLY AFFECTED KNOWLEDGE IS UPDATED.",
    support: "NOT RE-INDEXED. RECOMPILED.",
    technical: "SEMANTIC DIFF · IMPACT GRAPH · SELECTIVE RECOMPILATION",
  },
  H17: { statement: "A NEW CURRENT STATE IS ACTIVE." },
  H18: { statement: "WHAT IS THE CURRENT LAUNCH DATE?" },
  H19: {
    statement: "EVERY ANSWER HAS A WAY HOME.",
    technical: "VERIFIABLE PROVENANCE",
  },
  H20: {
    statement: "PERSONAL",
    support: "Your work, connected and current.",
  },
  H21: {
    statement: "TEAM",
    support: "Shared context without losing boundaries.",
  },
  H22: {
    statement: "ENTERPRISE",
    support: "One continuously updated view of what your organization knows.",
  },
  H23: {
    statement: "KNOW WHAT IS TRUE NOW.\nSEE WHAT CHANGED.\nRETURN EVERY ANSWER TO EVIDENCE.",
  },
};

/** §14.1 — quiet status strip content. No filled badge backgrounds. */
export const QUIET_STATUS = {
  sample: "SAMPLE WORKSPACE · SYNTHETIC DATA",
  worldState: (id: string) => `WORLD STATE ${id} · CURRENT`,
  /**
   * §21.3 — while a recompilation is in flight the world state is *not*
   * current, and saying so is the whole difference between an honest
   * instrument and a progress bar. The strip must never read CURRENT over a
   * frame that is already showing recompiled values.
   */
  worldStateRecompiling: (id: string) => `WORLD STATE ${id} · RECOMPILING`,
  sourceLinked: "SOURCE LINKED",
  motion: (mode: "FULL" | "REDUCED") => `MOTION: ${mode}`,
} as const;

/** §18.2 — user controls, in the order they take focus. */
export const CONTROLS = [
  { id: "skip", label: "Skip motion" },
  { id: "pause", label: "Pause cinematic" },
  { id: "replay", label: "Replay current step" },
  { id: "back", label: "Back to prior step" },
  { id: "explore", label: "Explore now" },
] as const;

export type ControlId = (typeof CONTROLS)[number]["id"];
