import type { ReactNode } from "react";

import type { ProjectStatus } from "../schemas/projects";
import type { ConversionStatus } from "../schemas/conversions";
import { AlertIcon, CheckIcon, ImageIcon, SpinnerIcon } from "./Icons";

const BADGES: Record<Exclude<ProjectStatus, "needs_photo">, { label: string; variant: string; icon: ReactNode }> = {
  photo_ready: { label: "Photo ready", variant: "neutral", icon: <ImageIcon size={13} /> },
  generating: { label: "Generating 3D", variant: "blue", icon: <SpinnerIcon size={13} /> },
  model_ready: { label: "3D model ready", variant: "green", icon: <CheckIcon size={13} /> },
  failed: { label: "Failed", variant: "red", icon: <AlertIcon size={13} /> },
};

/** Solid "brick" badge for a project's status. Projects that still need a photo show no badge. */
export function StatusBadge({
  status,
  conversionStatus = null,
  legoModelReady = false,
}: {
  status: ProjectStatus;
  conversionStatus?: ConversionStatus | null;
  legoModelReady?: boolean;
}) {
  if (status === "needs_photo") {
    return null;
  }
  if (legoModelReady) {
    return <span className="badge badge--green"><CheckIcon size={13} />LEGO model ready</span>;
  }
  if (conversionStatus === "queued" || conversionStatus === "running") {
    return <span className="badge badge--blue"><SpinnerIcon size={13} />Converting LEGO</span>;
  }
  const badge = BADGES[status];
  return (
    <span className={`badge badge--${badge.variant}`}>
      {badge.icon}
      {badge.label}
    </span>
  );
}
