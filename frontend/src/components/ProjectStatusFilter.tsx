import { useEffect, useId, useRef, useState } from "react";

import { CheckIcon } from "./Icons";
import { PROJECT_STATUS_LABELS } from "../projectStatus";

const OPTIONS = [
  { value: "all", label: "All projects" },
  ...Object.entries(PROJECT_STATUS_LABELS).map(([value, label]) => ({ value, label })),
];

interface ProjectStatusFilterProps {
  value: string;
  onChange: (value: string) => void;
}

export function ProjectStatusFilter({ value, onChange }: ProjectStatusFilterProps) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const selected = OPTIONS.find((option) => option.value === value) ?? OPTIONS[0];

  useEffect(() => {
    if (!isOpen) return;
    menuRef.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
    function onPointerDown(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setIsOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [isOpen]);

  return (
    <div className="project-filter" ref={containerRef} onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) setIsOpen(false);
    }}>
      <button ref={triggerRef} type="button" className="project-filter__trigger" aria-label="Filter projects" aria-haspopup="menu" aria-expanded={isOpen} aria-controls={menuId}
        onClick={() => setIsOpen((open) => !open)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setIsOpen(true);
          }
        }}>
        {selected.label}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
      </button>
      {isOpen ? (
        <div id={menuId} ref={menuRef} className="project-filter__menu" role="menu" aria-label="Project status" onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            setIsOpen(false);
            triggerRef.current?.focus();
          }
          const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("button"));
          const current = items.indexOf(document.activeElement as HTMLButtonElement);
          let next: number;
          switch (event.key) {
            case "ArrowDown": next = (current + 1) % items.length; break;
            case "ArrowUp": next = (current - 1 + items.length) % items.length; break;
            case "Home": next = 0; break;
            case "End": next = items.length - 1; break;
            default: return;
          }
          event.preventDefault();
          items[next]?.focus();
        }}>
          {OPTIONS.map((option) => (
            <button key={option.value} type="button" tabIndex={-1} className="project-filter__option" role="menuitemradio" aria-checked={value === option.value} onClick={() => {
              onChange(option.value);
              setIsOpen(false);
              triggerRef.current?.focus();
            }}>
              <span className="project-status__dot" data-status={option.value} aria-hidden="true" />
              {option.label}
              {value === option.value ? <CheckIcon size={16} /> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
