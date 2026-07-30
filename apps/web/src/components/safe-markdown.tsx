"use client";

import { useEffect, useState } from "react";
import rehypeSanitize from "rehype-sanitize";
import rehypeStringify from "rehype-stringify";
import remarkGfm from "remark-gfm";
import remarkParse from "remark-parse";
import remarkRehype from "remark-rehype";
import { unified } from "unified";

export function SafeMarkdown({ source }: { source: string }) {
  const [html, setHtml] = useState("");

  useEffect(() => {
    let cancelled = false;
    void unified()
      .use(remarkParse)
      .use(remarkGfm)
      .use(remarkRehype)
      .use(rehypeSanitize)
      .use(rehypeStringify)
      .process(source)
      .then((result) => {
        if (!cancelled) setHtml(String(result));
      });
    return () => {
      cancelled = true;
    };
  }, [source]);

  return (
    <div
      className="markdown-rendered"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
