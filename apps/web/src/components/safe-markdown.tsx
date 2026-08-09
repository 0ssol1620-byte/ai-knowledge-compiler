"use client";

import rehypeSanitize from "rehype-sanitize";
import rehypeStringify from "rehype-stringify";
import remarkGfm from "remark-gfm";
import remarkParse from "remark-parse";
import remarkRehype from "remark-rehype";
import { unified } from "unified";

const safeMarkdownProcessor = unified()
  .use(remarkParse)
  .use(remarkGfm)
  .use(remarkRehype)
  .use(rehypeSanitize)
  .use(rehypeStringify);

export function SafeMarkdown({ source }: { source: string }) {
  // All plugins in this pipeline are synchronous. Rendering the sanitized
  // result during SSR and the first client render keeps the block's geometry
  // stable; deferring it to an effect caused a visible post-hydration reflow.
  const html = demoteEmbeddedDocumentHeadings(
    String(safeMarkdownProcessor.processSync(source)),
  );

  return (
    <div
      className="markdown-rendered"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function demoteEmbeddedDocumentHeadings(html: string): string {
  return html.replace(
    /<(\/?)h([1-5])(?=[\s>])/g,
    (_match, slash: string, level: string) => `<${slash}h${Number(level) + 1}`,
  );
}
