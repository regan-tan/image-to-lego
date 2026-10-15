import {
  colorLabel,
  createPurchaseReadyPartsList,
  type LegoPartsListResult,
  type LegoPartGroup,
  partColorVerificationLabel,
  partLabel,
  serializePartsListCsv,
  serializePurchaseReadyPartsCsv,
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
  partColorVerificationVersion,
}: {
  partsList: LegoPartsListResult;
  partColorVerificationVersion?: string;
}) {
  if (!partsList.valid) {
    return <p className="form-error" role="alert">The parts list could not be verified because the LEGO model inventory is inconsistent.</p>;
  }

  return (
    <section className="parts-list-workspace" aria-labelledby="parts-list-title">
      <div className="parts-list-workspace__heading">
        <div>
          <h2 id="parts-list-title">Parts list</h2>
          <p>{partsList.totalPartCount} total parts · {partsList.uniquePartTypeCount} unique part types</p>
        </div>
        <PartsListDownloadButton parts={partsList.parts} />
      </div>
      <PurchaseReadyPartsExport
        parts={partsList.parts}
        partColorVerificationVersion={partColorVerificationVersion}
      />
      <div className="parts-list__table-wrap">
        <table className="parts-list__table">
          <thead><tr><th scope="col">Preview</th><th scope="col">Part ID</th><th scope="col">Part name</th><th scope="col">Color</th><th scope="col">Color ID</th><th scope="col">Verification</th><th scope="col">Quantity</th></tr></thead>
          <tbody>{partsList.parts.map((part) => <PartsListRow key={partKey(part)} part={part} />)}</tbody>
        </table>
      </div>
    </section>
  );
}

function PurchaseReadyPartsExport({
  parts,
  partColorVerificationVersion,
}: {
  parts: LegoPartGroup[];
  partColorVerificationVersion?: string;
}) {
  const purchaseReady = createPurchaseReadyPartsList(parts, partColorVerificationVersion);

  function handleDownload() {
    const csv = serializePurchaseReadyPartsCsv(purchaseReady.parts);
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "lego-purchase-ready-parts.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section className="parts-list-sourcing" aria-labelledby="parts-list-sourcing-title">
      <div>
        <h3 id="parts-list-sourcing-title">Sourcing export</h3>
        <p>
          Exports verified manufactured part/color pairs only. It does not confirm current
          availability, stock, pricing, or sellers.
        </p>
        {purchaseReady.unresolvedParts.length > 0 ? (
          <p className="form-error" role="alert">
            {purchaseReady.unresolvedParts.length} part/color row
            {purchaseReady.unresolvedParts.length === 1 ? " is" : "s are"} excluded because it is
            not purchase-ready.
          </p>
        ) : null}
      </div>
      <button
        type="button"
        className="button button--secondary"
        onClick={handleDownload}
        disabled={purchaseReady.parts.length === 0}
      >
        Download purchase-ready CSV
      </button>
    </section>
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
      <td data-label="Preview"><LegoPartThumbnail part={part} /></td>
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
