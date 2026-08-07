import { headers } from "next/headers";

import { jsonLdDocument, type JsonLdNode } from "@/lib/structured-data";

/**
 * Renders a schema.org graph as a JSON-LD data block.
 *
 * The nonce comes from src/proxy.ts, which mints one per request; the layout is
 * force-dynamic so it is never a stale value. dangerouslySetInnerHTML is the
 * only way to emit a data block, and the payload is JSON.stringify output from
 * our own typed nodes, never user input.
 *
 * suppressHydrationWarning is required, not cosmetic: browsers blank the nonce
 * content attribute once the document is parsed, so the client always reads ""
 * where the server wrote a value, and React reports a mismatch on every page
 * load. The alternative — dropping the nonce — would leave the block at the
 * mercy of any user agent that does apply script-src to data blocks.
 */
export async function JsonLd({ nodes }: { nodes: JsonLdNode[] }) {
  if (nodes.length === 0) return null;
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <script
      type="application/ld+json"
      nonce={nonce}
      suppressHydrationWarning
      dangerouslySetInnerHTML={{ __html: jsonLdDocument(nodes) }}
    />
  );
}
