import { useEffect, useId, useRef, useState } from "react";

import {
  colorLabel,
  createPurchaseReadyPartsList,
  type LegoPartsListResult,
  type LegoPartGroup,
  partColorVerificationLabel,
  partLabel,
  serializePartsListCsv,
} from "../legoPartsList";
import { legoColorHex } from "../legoColors";
import { LegoPartThumbnail } from "./LegoPartThumbnail";

interface PartsListSummaryProps {
  partsList: LegoPartsListResult;
  onViewFullPartsList: () => void;
}

export function PartsListSummary({ partsList, onViewFullPartsList }: PartsListSummaryProps) {
  if (!partsList.valid) {
    return <p className="form-error" role="alert">The parts list could not be verified because the LEGO model inventory is inconsistent.</p>;
  }

  return (
    <section className="parts-list-summary" aria-labelledby="parts-list-summary-title">
      <div>
        <h3 id="parts-list-summary-title" className="side-panel__title">Parts list</h3>
        <p className="side-panel__hint">{partsList.totalPartCount} total parts</p>
        <p className="side-panel__hint">{partsList.uniquePartTypeCount} unique part types</p>
      </div>
      <div className="side-panel__actions parts-list-summary__actions">
        <button type="button" className="button button--secondary" onClick={onViewFullPartsList}>View full parts list</button>
        <PartsListDownloadButton parts={partsList.parts} />
      </div>
    </section>
  );
}

export function PartsListWorkspace({
  partsList,
  algorithmVersion,
  partColorVerificationVersion,
}: {
  partsList: LegoPartsListResult;
  algorithmVersion?: string;
  partColorVerificationVersion?: string;
}) {
  if (!partsList.valid) {
    return <p className="form-error" role="alert">The parts list could not be verified because the LEGO model inventory is inconsistent.</p>;
  }

  return (
    <section className="parts-list-workspace" aria-labelledby="parts-list-title">
      <div className="parts-list-workspace__heading">
        <div>
          <div className="parts-list-title-row">
            <h2 id="parts-list-title">Parts list</h2>
            <PartsListInfo parts={partsList.parts} algorithmVersion={algorithmVersion} partColorVerificationVersion={partColorVerificationVersion} />
          </div>
          <p>{partsList.totalPartCount} total parts · {partsList.uniquePartTypeCount} unique part types</p>
        </div>
        <PartsListDownloadButton parts={partsList.parts} />
      </div>
      <div className="parts-list__table-wrap" role="region" aria-label="Parts inventory" tabIndex={0}>
        <table className="parts-list__table">
          <colgroup>
            <col className="parts-list__preview-column" />
            <col className="parts-list__part-id-column" />
            <col className="parts-list__part-name-column" />
            <col className="parts-list__color-column" />
            <col className="parts-list__color-id-column" />
            <col className="parts-list__verification-column" />
            <col className="parts-list__quantity-column" />
          </colgroup>
          <thead><tr><th scope="col">Preview</th><th scope="col">Part ID</th><th scope="col">Part name</th><th scope="col">Color</th><th scope="col">Color ID</th><th scope="col">Verification</th><th scope="col">Quantity</th></tr></thead>
          <tbody>{partsList.parts.map((part) => <PartsListRow key={partKey(part)} part={part} />)}</tbody>
        </table>
      </div>
    </section>
  );
}

function PartsListInfo({ parts, algorithmVersion, partColorVerificationVersion }: {
  parts: LegoPartGroup[];
  algorithmVersion?: string;
  partColorVerificationVersion?: string;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLSpanElement>(null);
  const tooltipId = useId();
  const unresolvedCount = createPurchaseReadyPartsList(parts, algorithmVersion, partColorVerificationVersion).unresolvedParts.length;

  useEffect(() => {
    if (!isOpen) return;
    function onPointerDown(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setIsOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setIsOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isOpen]);

  return (
    <span className="parts-list-info" ref={containerRef}
      onMouseEnter={() => setIsOpen(true)}
      onMouseLeave={(event) => {
        if (!event.currentTarget.contains(document.activeElement)) setIsOpen(false);
      }}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setIsOpen(false);
      }}>
      <button type="button" className="parts-list-info__trigger" aria-label="About parts list verification" aria-expanded={isOpen} aria-describedby={isOpen ? tooltipId : undefined} onFocus={() => setIsOpen(true)} onClick={() => setIsOpen(true)}>
        <span aria-hidden="true">!</span>
      </button>
      {isOpen ? (
        <span id={tooltipId} className="parts-list-info__tooltip" role="tooltip">
          The CSV includes the complete model inventory. Only verified manufactured part/color pairs should be used for sourcing. Verification does not confirm current availability, stock, pricing, or sellers.
          {unresolvedCount > 0 ? <span>{unresolvedCount} part/color {unresolvedCount === 1 ? "row needs" : "rows need"} additional verification. Check the Verification column.</span> : null}
        </span>
      ) : null}
    </span>
  );
}

function PartsListDownloadButton({ parts }: { parts: LegoPartGroup[] }) {
  function handleDownload() {
    const csv = serializePartsListCsv(parts);
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "lego-parts-list.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  return <button type="button" className="button button--secondary" onClick={handleDownload}>Download parts list (.csv)</button>;
}

function PartsListRow({ part }: { part: LegoPartGroup }) {
  return (
    <tr>
      <td data-label="Preview"><LegoPartThumbnail part={part} variant="illustration" /></td>
      <td data-label="Part ID">{part.partId ?? "Legacy part"}</td>
      <td data-label="Part name">{partLabel(part)}</td>
      <td data-label="Color">
        <span className="color-swatch" style={{ backgroundColor: part.colorHex ?? legoColorHex(part.color) }} aria-hidden="true" />
        {part.colorName ?? colorLabel(part.color)}
      </td>
      <td data-label="Color ID">{part.colorId ?? "Legacy color"}</td>
      <td data-label="Verification">{partColorVerificationLabel(part)}</td>
      <td data-label="Quantity">{part.quantity}</td>
    </tr>
  );
}

function partKey(part: LegoPartGroup): string {
  return `${part.partId ?? part.brickType}-${part.colorId ?? part.color}`;
}
