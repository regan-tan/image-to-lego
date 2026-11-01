import { PROJECT_STATUS_LABELS } from "../projectStatus";
import type { ProjectStatus } from "../schemas/projects";
import type { ConversionStatus } from "../schemas/conversions";

export function StatusBadge({
  status,
  conversionStatus = null,
  legoModelReady = false,
}: {
  status: ProjectStatus;
  conversionStatus?: ConversionStatus | null;
  legoModelReady?: boolean;
}) {
  const converting = conversionStatus === "queued" || conversionStatus === "running";
  const conversionFailed = conversionStatus === "failed";
  const currentStatus = converting ? "generating" : conversionFailed ? "failed" : legoModelReady ? "model_ready" : status;
  const detail = converting || conversionFailed ? "LEGO conversion" : null;

  return (
    <span className="project-status">
      <span className="project-status__dot" data-status={currentStatus} aria-hidden="true" />
      <span>{PROJECT_STATUS_LABELS[currentStatus]}</span>
      {detail ? <span className="project-status__detail">· {detail}</span> : null}
    </span>
  );
}
