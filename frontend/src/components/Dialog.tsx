import { type ReactNode, useEffect, useId, useRef } from "react";

import { CloseIcon } from "./Icons";

interface DialogProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  size?: "medium" | "large";
  children: ReactNode;
}

/**
 * Modal built on the native <dialog> element, which provides focus trapping, Escape to close,
 * an inert background and focus restoration without extra code.
 */
export function Dialog({ isOpen, onClose, title, description, size = "medium", children }: DialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) {
      return;
    }
    if (isOpen && !dialog.open) {
      dialog.showModal();
    } else if (!isOpen && dialog.open) {
      dialog.close();
    }
  }, [isOpen]);

  return (
    <dialog
      ref={dialogRef}
      className={`dialog dialog--${size}`}
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      onClose={onClose}
      onClick={(event) => {
        // The dialog element itself only receives clicks on its backdrop; content sits in a child.
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      {isOpen ? (
        <div className="dialog__content">
          <div className="dialog__header">
            <h2 id={titleId} className="dialog__title">{title}</h2>
            {description ? <p id={descriptionId} className="dialog__description">{description}</p> : null}
          </div>
          {children}
          {/* Last in source order so the first form field, not this button, receives initial focus. */}
          <button type="button" className="icon-button dialog__close" aria-label="Close" onClick={onClose}>
            <CloseIcon size={20} />
          </button>
        </div>
      ) : null}
    </dialog>
  );
}
