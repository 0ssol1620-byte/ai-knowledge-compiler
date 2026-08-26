import { ArrowLeft, ShieldCheck } from "lucide-react";
import "../legal.css";

type LegalDocument = "privacy" | "terms";

const COPY: Record<LegalDocument, { eyebrow: string; title: string; summary: string; sections: Array<{ heading: string; body: string }> }> = {
  privacy: {
    eyebrow: "TAVONEL / PRIVACY NOTICE",
    title: "Privacy follows the source boundary.",
    summary: "This notice explains how TAVONEL handles account data, customer source material, and a customer-approved cloud connection.",
    sections: [
      { heading: "What we process", body: "TAVONEL processes the account information needed to provide the workspace, project metadata, source metadata, and the source bytes that a customer explicitly uploads or explicitly authorizes through a connector. A connection approval is project-scoped; it does not grant access to unrelated projects." },
      { heading: "Cloud connections", body: "When a customer approves a Google Drive connection, TAVONEL requests the declared read-only scope. OAuth access and refresh tokens are retained server-side in encrypted form and are never displayed in the customer interface. TAVONEL does not request permission to delete, move, rename, or share the customer’s Drive content." },
      { heading: "Storage and review", body: "Original source bytes are stored outside SQL in a private object store. TAVONEL preserves visible provenance, duplicate relationships, and review states. AI-assisted proposals are derived outputs for review; they are not a replacement for the original source." },
      { heading: "Retention and control", body: "A customer can disconnect a cloud connection to revoke TAVONEL’s retained connector credentials. Retention and deletion of project sources are controlled through the customer workspace and applicable service agreement. We do not silently remove source material as part of duplicate detection." },
      { heading: "Contact", body: "For privacy or OAuth-connection questions, contact the TAVONEL operator through the support address shown on the relevant consent screen. This notice is dated 26 August 2026 (KST)." },
    ],
  },
  terms: {
    eyebrow: "TAVONEL / SERVICE TERMS",
    title: "Compile with review intact.",
    summary: "These terms set the operating boundary for TAVONEL’s source-bound knowledge compilation workspace.",
    sections: [
      { heading: "The service", body: "TAVONEL helps a customer collect explicitly authorized sources, preserve original records, surface duplicate relationships, and generate reviewable organization proposals. Product outputs are proposals, not independently verified facts, legal advice, financial advice, or an instruction to alter an original source." },
      { heading: "Customer authority", body: "The customer represents that it has authority to upload or connect the selected content. The customer selects any cloud account or folder at the provider’s consent screen and remains responsible for reviewing proposed classifications, authority selection, and later use of compiled context." },
      { heading: "Connection boundary", body: "A connector begins only after customer approval. TAVONEL requests the stated least-privilege scope and preserves source originals. A connector does not authorize TAVONEL to delete, move, rename, or share customer content." },
      { heading: "Review-first output", body: "AI-assisted maps, entities, directories, and duplicate indications must be reviewed before operational use. TAVONEL deliberately distinguishes source facts from generated structure and will show unavailable or failed sources rather than inventing their content." },
      { heading: "Changes and contact", body: "We may update these terms as the service matures; the current version is dated 26 August 2026 (KST). Questions about a workspace or connector can be directed to the TAVONEL operator through the support address shown on the consent screen." },
    ],
  },
};

export function LegalPage({ document }: { document: LegalDocument }) {
  const content = COPY[document];
  return <main className="legal-shell"><header className="legal-top"><a href="/"><ArrowLeft size={15} /> TAVONEL</a><span>PUBLIC RECORD / {document === "privacy" ? "PRIVACY" : "TERMS"}</span></header><section className="legal-hero"><div><p>{content.eyebrow}</p><h1>{content.title}</h1></div><ShieldCheck aria-hidden="true" size={32} /><p>{content.summary}</p></section><section className="legal-body">{content.sections.map((section, index) => <article key={section.heading}><span>{String(index + 1).padStart(2, "0")}</span><div><h2>{section.heading}</h2><p>{section.body}</p></div></article>)}</section><footer className="legal-footer"><span>© 2026 TAVONEL</span><div><a href="/privacy">Privacy</a><a href="/terms">Terms</a></div></footer></main>;
}
