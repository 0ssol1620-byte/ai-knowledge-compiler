import type { ReactNode } from "react";

/**
 * The cinematic experience runs on its own token layer.
 *
 * CINEMATIC_DESIGN_MASTER_SPEC §0.1 rules that the current implementation is
 * evidence for fixtures and ids, but is *not* a visual or motion baseline. This
 * import is the practical form of that ruling: tvx.css lands after the eight
 * legacy stylesheets and scopes everything under [data-tvx], so the experience
 * is built from the spec's tokens rather than inheriting the old page's.
 */
import "@/styles/tvx.css";

export default function ExperienceLayout({
  children,
}: {
  children: ReactNode;
}) {
  return children;
}
