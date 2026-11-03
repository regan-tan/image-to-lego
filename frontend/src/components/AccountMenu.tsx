import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { HelpIcon, SignOutIcon, UserIcon } from "./Icons";

interface AccountMenuProps {
  email: string | undefined;
  name?: string;
  onAbout: () => void;
  onSignOut: () => void;
}

export function AccountMenu({ email, name, onAbout, onSignOut }: AccountMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const displayName = name?.trim() || email?.split("@")[0] || "Your account";
  const initials = displayName.split(/\s+/).slice(0, 2).map((word) => word.charAt(0)).join("").toUpperCase();

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    containerRef.current?.querySelector<HTMLAnchorElement>("a")?.focus();

    function handlePointerDown(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsOpen(false);
        triggerRef.current?.focus();
      }
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  return (
    <div className="account-menu" ref={containerRef} onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) setIsOpen(false);
    }}>
      <button
        ref={triggerRef}
        type="button"
        className="account-menu__trigger"
        aria-label="Account menu"
        aria-expanded={isOpen}
        aria-controls={panelId}
        onClick={() => setIsOpen((current) => !current)}
      >
        <span className="account-menu__avatar" aria-hidden="true">{initials}</span>
        <span className="account-menu__name">{displayName}</span>
        <span className="account-menu__chevron" aria-hidden="true">⌃</span>
      </button>
      {isOpen ? (
        <div id={panelId} className="account-menu__panel">
          <p className="account-menu__identity">
            <span className="account-menu__label">Signed in as</span>
            <span className="account-menu__email">{email ?? "Unknown email"}</span>
          </p>
          <div className="account-menu__divider" />
          <Link to="/profile" className="account-menu__item" onClick={() => setIsOpen(false)}>
            <UserIcon />
            My profile
          </Link>
          <button type="button" className="account-menu__item" onClick={() => {
            setIsOpen(false);
            triggerRef.current?.focus();
            onAbout();
          }}>
            <HelpIcon />
            About this app
          </button>
          <div className="account-menu__divider" />
          <button type="button" className="account-menu__item" onClick={() => {
            setIsOpen(false);
            triggerRef.current?.focus();
            onSignOut();
          }}>
            <SignOutIcon />
            Sign out
          </button>
        </div>
      ) : null}
    </div>
  );
}
