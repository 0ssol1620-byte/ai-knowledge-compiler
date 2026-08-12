"use client";

/**
 * Source-adopted from shadcn/ui `resizable` at
 * cb2bcd88d93b2f9bddb030e9136f1f8773e7eac4 (MIT).
 * Adaptation: FOLYNTA CSS module, Phosphor grip, react-resizable-panels v4 API.
 */
import { DotsSixVertical } from "@phosphor-icons/react";
import clsx from "clsx";
import * as ResizablePrimitive from "react-resizable-panels";

import styles from "./resizable.module.css";

export function ResizablePanelGroup({
  className,
  ...props
}: React.ComponentProps<typeof ResizablePrimitive.Group>) {
  return (
    <ResizablePrimitive.Group
      className={clsx(styles.group, className)}
      {...props}
    />
  );
}

export const ResizablePanel = ResizablePrimitive.Panel;

export function ResizableHandle({
  withHandle,
  className,
  ...props
}: React.ComponentProps<typeof ResizablePrimitive.Separator> & {
  withHandle?: boolean;
}) {
  return (
    <ResizablePrimitive.Separator
      className={clsx(styles.handle, className)}
      {...props}
    >
      {withHandle ? (
        <span className={styles.grip} aria-hidden="true">
          <DotsSixVertical size={13} weight="bold" />
        </span>
      ) : null}
    </ResizablePrimitive.Separator>
  );
}
