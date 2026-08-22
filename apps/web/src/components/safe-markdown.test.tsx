import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SafeMarkdown } from "@/components/safe-markdown";

describe("SafeMarkdown", () => {
  it("renders sanitized markdown on the initial render", () => {
    const { container } = render(
      <SafeMarkdown
        source={'# Evidence\n\n**Verified**\n\n<script>alert("xss")</script>'}
      />,
    );

    expect(container.querySelector("h2")?.textContent).toBe("Evidence");
    expect(container.querySelector("strong")?.textContent).toBe("Verified");
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector(".markdown-rendered")?.textContent).not.toBe(
      "",
    );
  });

  it("updates synchronously when the markdown source changes", () => {
    const { container, rerender } = render(<SafeMarkdown source="First" />);

    rerender(<SafeMarkdown source="Second" />);

    expect(container.querySelector("p")?.textContent).toBe("Second");
  });
});
