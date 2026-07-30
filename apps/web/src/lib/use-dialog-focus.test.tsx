import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useRef, useState } from "react";
import { describe, expect, it } from "vitest";

import { useDialogFocus } from "@/lib/use-dialog-focus";

function DialogHarness() {
  const [open, setOpen] = useState(false);
  const firstRef = useRef<HTMLInputElement>(null);
  const dialogRef = useDialogFocus<HTMLElement>({
    open,
    onClose: () => setOpen(false),
    initialFocusRef: firstRef,
  });

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      {open && (
        <section
          ref={dialogRef}
          role="dialog"
          aria-label="Example"
          tabIndex={-1}
        >
          <input ref={firstRef} aria-label="First" />
          <button type="button" onClick={() => setOpen(false)}>
            Close
          </button>
        </section>
      )}
    </>
  );
}

describe("useDialogFocus", () => {
  it("sets initial focus, traps Tab, closes on Escape, and restores focus", async () => {
    render(<DialogHarness />);
    const trigger = screen.getByRole("button", { name: "Open" });
    trigger.focus();
    fireEvent.click(trigger);

    const first = await screen.findByRole("textbox", { name: "First" });
    const close = screen.getByRole("button", { name: "Close" });
    await waitFor(() => expect(first).toHaveFocus());

    close.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(first).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Example" })).toBeNull(),
    );
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});
