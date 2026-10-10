import { colorLabel, type LegoPartsListResult, type LegoPartGroup, partLabel, serializePartsListCsv } from "../legoPartsList";
import { legoColorHex } from "../legoColors";

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
        <p className="side-panel__hint">Most common: <span>{partLabel(partsList.parts[0])}</span></p>
      </div>
      <div className="side-panel__actions">
        <button type="button" className="button button--secondary" onClick={onViewFullPartsList}>View full parts list</button>
        <PartsListDownloadButton parts={partsList.parts} />
      </div>
    </section>
  );
}

export function PartsListWorkspace({ partsList }: { partsList: LegoPartsListResult }) {
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
      <div className="parts-list__table-wrap">
        <table className="parts-list__table">
          <thead><tr><th scope="col">Part</th><th scope="col">Size</th><th scope="col">Color</th><th scope="col">Quantity</th></tr></thead>
          <tbody>{partsList.parts.map((part) => <PartsListRow key={partKey(part)} part={part} />)}</tbody>
        </table>
      </div>
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
      <td data-label="Part">{partLabel(part)}</td>
      <td data-label="Size">{part.lengthStuds} × {part.widthStuds}</td>
      <td data-label="Color">
        <span className="color-swatch" style={{ backgroundColor: legoColorHex(part.color) }} aria-hidden="true" />
        {colorLabel(part.color)}
      </td>
      <td data-label="Quantity">{part.quantity}</td>
    </tr>
  );
}

function partKey(part: LegoPartGroup): string {
  return `${part.brickType}-${part.lengthStuds}-${part.widthStuds}-${part.heightBricks}-${part.color}`;
}
