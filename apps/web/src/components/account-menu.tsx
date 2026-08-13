"use client";

import { CaretDown, CreditCard, SignOut, UserCircle } from "@phosphor-icons/react";
import clsx from "clsx";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import styles from "@/components/account-menu.module.css";
import { useLogout } from "@/lib/use-logout";

export interface AccountMenuProps {
  workspaceName?: string;
  userRole?: string;
  userInitials: string;
}

/**
 * Compact account/profile dropdown for the topbar account affordance.
 *
 * Replaces the plain `Link` to `/settings` (see
 * docs/commercial/COMMERCIAL_SHELL_INTEGRATION_REQUIREMENTS.md §3) whose
 * CaretDown implied a menu that did not open anything. This is that menu:
 * Account (/account), Billing (/billing), Sign out (real POST
 * /v1/auth/logout via the shared useLogout hook).
 *
 * No separate "Developer/API" entry — API key management already lives on
 * /account (see account-page.tsx), so a dedicated nav entry for it would be
 * a redundant second click to the same page.
 *
 * Not wired into app-shell.tsx in this pass — app-shell.tsx is on the
 * shared-file freeze list for this track. See
 * docs/commercial/PROPOSED_SHARED_CHANGES.md for the exact wiring.
 */
export function AccountMenu({
  workspaceName,
  userRole,
  userInitials,
}: AccountMenuProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const logout = useLogout();

  useEffect(() => {
    if (!open) return;

    function onPointerDown(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div className={styles.root} ref={containerRef}>
      <button
        type="button"
        className="account-button"
        aria-haspopup="menu"
        aria-expanded={open}
        data-shell-action="account"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="avatar" aria-hidden="true">
          {userInitials}
        </span>
        <span className="account-copy">
          <strong>{workspaceName ?? "Workspace"}</strong>
          <small>{userRole ?? "Member"}</small>
        </span>
        <CaretDown size={14} aria-hidden="true" />
      </button>
      {open && (
        <div className={styles.menu} role="menu" aria-label="Account menu">
          <Link
            href="/account"
            role="menuitem"
            className={styles.item}
            onClick={() => setOpen(false)}
          >
            <UserCircle size={16} aria-hidden="true" />
            Account
          </Link>
          <Link
            href="/billing"
            role="menuitem"
            className={styles.item}
            onClick={() => setOpen(false)}
          >
            <CreditCard size={16} aria-hidden="true" />
            Billing
          </Link>
          <button
            type="button"
            role="menuitem"
            className={clsx(styles.item, styles.signOut)}
            disabled={logout.isPending}
            onClick={() => {
              setOpen(false);
              logout.mutate();
            }}
          >
            <SignOut size={16} aria-hidden="true" />
            {logout.isPending ? "Signing out…" : "Sign out"}
          </button>
        </div>
      )}
    </div>
  );
}
