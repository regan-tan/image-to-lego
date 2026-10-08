import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { SignOutIcon, UserIcon } from "./Icons";

interface AccountMenuProps {
  email: string | undefined;
  onSignOut: () => void;
}

export function AccountMenu({ email, onSignOut }: AccountMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const initial = email?.charAt(0).toUpperCase() || "?";

  useEffect(() => {
    if (!isOpen) {
      return;
    }

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
    <div className="account-menu" ref={containerRef}>
      <button
        ref={triggerRef}
        type="button"
        className="account-menu__trigger"
        aria-label="Account menu"
        aria-expanded={isOpen}
        aria-controls={panelId}
        onClick={() => setIsOpen((current) => !current)}
      >
        {initial}
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
            Profile
          </Link>
          <button type="button" className="account-menu__item" onClick={onSignOut}>
            <SignOutIcon />
            Sign out
          </button>
        </div>
      ) : null}
    </div>
  );
}
