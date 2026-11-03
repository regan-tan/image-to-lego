import type { ProjectStatus } from "./schemas/projects";

export const PROJECT_STATUS_LABELS: Record<ProjectStatus, string> = {
  needs_photo: "Needs photo",
  photo_ready: "Photo ready",
  generating: "Generating",
  model_ready: "Model ready",
  failed: "Failed",
};
