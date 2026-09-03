import { ExperienceHome } from "@/experience/scenes/experience-home";

export const metadata = {
  title: "TAVONEL — The Knowledge Compiler",
  description:
    "TAVONEL turns scattered digital information into connected knowledge—and keeps it current as things change.",
};

/**
 * The cinematic Home, at `/experience` while the existing marketing `/` stands.
 *
 * Whether this replaces `/` is a founder call, not an agent's: the current home
 * page is live surface. Building it here means the two can be compared at the
 * same time on the same build rather than one being overwritten to find out.
 */
export default function ExperiencePage() {
  return <ExperienceHome />;
}
