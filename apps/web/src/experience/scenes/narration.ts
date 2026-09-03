/**
 * §18.3 — the sequence as text.
 *
 * This lives apart from the component that renders it because the text
 * equivalent is the *argument*, and the argument has to be checkable on its
 * own: a test can assert that all 24 beats are narrated without booting a DOM.
 * It also means the accessibility path cannot quietly drift behind the visual
 * one, because both read this file.
 */

import { SHOT_COPY } from "../manifest/copy";
import type { Shot } from "../manifest/shots";

/**
 * The beats whose whole content is a mechanism still owe the reader the claim
 * that mechanism makes. Falling back to the beat name would give a screen
 * reader "COMPILED KNOWLEDGE OBJECT" — a label, not an argument.
 */
const MECHANISM_NARRATION: Readonly<Record<string, string>> = {
  H00: "The sequence begins in near darkness. Nothing is legible yet.",
  H06:
    "A single knowledge object assembles from six layers: its value, its type, " +
    "the source document it came from, that source's revision, the time it " +
    "applies to, and the authority that approved it.",
};

/**
 * Beats whose on-screen content *is* the evidence carry a detail line. "The
 * documents disagree" is a complete sentence and a useless one to a reader who
 * cannot see the four candidates it is talking about; §18.3 asks for the
 * argument, and the argument here is which documents and by how much.
 */
const DETAIL: Readonly<Record<string, string>> = {
  H05:
    "Four documents give a launch date: a superseded launch plan says " +
    "September 1, an unapproved meeting note says September 15, and both the " +
    "approved product plan and the launch calendar say October 15.",
  H10:
    "The same four sources are on screen with their dates, and two of them " +
    "contradict the other two.",
  // H13 and H14 are one sentence split across two beats. Read aloud on its
  // own, "when something changes," announces nothing at all.
  H13:
    "The approved product plan is revised: the launch date moves from " +
    "October 15 to November 3.",
  H14:
    "The change is read as a change in meaning, not as a new file to " +
    "re-index.",
  H11:
    "The approved, currently effective source wins; the others stay visible " +
    "and inspectable rather than being deleted.",
  H15:
    "The readiness review, the marketing freeze and the EU rollout window all " +
    "depend on the launch date. The rest of the sample workspace does not.",
  H17: "World state SAMPLE-018291 is replaced by SAMPLE-018292, in one step.",
};

export function narrate(shot: Shot): string {
  const copy = SHOT_COPY[shot.id];
  const detail = DETAIL[shot.id];

  if (copy?.statement) {
    const parts = [copy.statement.replace(/\n/g, " ")];
    if (copy.support) parts.push(copy.support.replace(/\n/g, " "));
    if (detail) parts.push(detail);
    return parts.join(" ");
  }
  return MECHANISM_NARRATION[shot.id] ?? detail ?? shot.beat;
}
