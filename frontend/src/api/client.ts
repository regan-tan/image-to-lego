import { profileResponseSchema, type ProfileResponse } from "../schemas/profile";
import {
  projectDetailSchema,
  projectSchema,
  projectsSchema,
  type Project,
  type ProjectDetail,
} from "../schemas/projects";
import {
  uploadCompletionSchema,
  uploadInitiationSchema,
  type UploadCompletion,
  type UploadInitiation,
} from "../schemas/uploads";
import { reconstructionSchema, type Reconstruction } from "../schemas/reconstructions";

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

/** A non-2xx API response; callers can branch on `status` (for example 404 Not Found). */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`API request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function getProfile(accessToken: string, signal?: AbortSignal): Promise<ProfileResponse> {
  const response = await fetch(`${apiBaseUrl}/api/v1/profile`, {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Profile request failed with status ${response.status}`);
  }

  return profileResponseSchema.parse(await response.json());
}

export async function getProjects(accessToken: string, signal?: AbortSignal): Promise<Project[]> {
  const response = await authenticatedRequest("/api/v1/projects", accessToken, { signal });
  return projectsSchema.parse(await response.json());
}

export async function getProject(
  accessToken: string,
  projectId: string,
  signal?: AbortSignal,
): Promise<ProjectDetail> {
  const response = await authenticatedRequest(
    `/api/v1/projects/${encodeURIComponent(projectId)}`,
    accessToken,
    { signal },
  );
  return projectDetailSchema.parse(await response.json());
}

export async function createProject(accessToken: string, name: string): Promise<Project> {
  const response = await authenticatedRequest("/api/v1/projects", accessToken, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  return projectSchema.parse(await response.json());
}

interface InitiateUploadRequest {
  projectId: string;
  fileName: string;
  mimeType: string;
  sizeBytes: number;
  sha256: string;
}

export async function initiateUpload(
  accessToken: string,
  request: InitiateUploadRequest,
): Promise<UploadInitiation> {
  const response = await authenticatedRequest("/api/v1/uploads", accessToken, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return uploadInitiationSchema.parse(await response.json());
}

export async function uploadFileToBlob(
  uploadUrl: string,
  file: File,
  requiredHeaders: Record<string, string>,
): Promise<void> {
  const response = await fetch(uploadUrl, {
    method: "PUT",
    headers: requiredHeaders,
    body: file,
  });
  if (!response.ok) {
    throw new Error(`Blob upload failed with status ${response.status}`);
  }
}

export async function completeUpload(
  accessToken: string,
  uploadId: string,
): Promise<UploadCompletion> {
  const response = await authenticatedRequest(
    `/api/v1/uploads/${encodeURIComponent(uploadId)}/complete`,
    accessToken,
    { method: "POST" },
  );
  return uploadCompletionSchema.parse(await response.json());
}

export async function startReconstruction(
  accessToken: string,
  request: { projectId: string; sourceArtifactId: string },
  idempotencyKey: string,
): Promise<Reconstruction> {
  const response = await authenticatedRequest("/api/v1/reconstructions", accessToken, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify(request),
  });
  return reconstructionSchema.parse(await response.json());
}

async function authenticatedRequest(
  path: string,
  accessToken: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  headers.set("Authorization", `Bearer ${accessToken}`);
  const response = await fetch(`${apiBaseUrl}${path}`, { ...init, headers });
  if (!response.ok) {
    throw new ApiError(response.status);
  }
  return response;
}

