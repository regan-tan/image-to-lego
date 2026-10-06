import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ChangeEvent, type FormEvent, useRef, useState } from "react";

import {
  completeUpload,
  createProject,
  getProjects,
  initiateUpload,
  uploadFileToBlob,
} from "../api/client";

const ALLOWED_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const DEFAULT_MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024;
const DEFAULT_MAX_IMAGE_PIXEL_COUNT = 40_000_000;
const configuredMaxImageSize = Number(import.meta.env.VITE_UPLOAD_MAX_IMAGE_SIZE_BYTES);
const configuredMaxImagePixels = Number(import.meta.env.VITE_UPLOAD_MAX_PIXEL_COUNT);
const MAX_IMAGE_SIZE_BYTES = Number.isSafeInteger(configuredMaxImageSize) && configuredMaxImageSize > 0
  ? configuredMaxImageSize
  : DEFAULT_MAX_IMAGE_SIZE_BYTES;
const MAX_IMAGE_PIXEL_COUNT = Number.isSafeInteger(configuredMaxImagePixels)
  && configuredMaxImagePixels > 0
  ? configuredMaxImagePixels
  : DEFAULT_MAX_IMAGE_PIXEL_COUNT;

type UploadStage = "idle" | "validating" | "hashing" | "initiating" | "uploading" | "completing" | "success";

interface ProjectWorkspaceProps {
  accessToken: string;
  userId: string;
}

export function ProjectWorkspace({ accessToken, userId }: ProjectWorkspaceProps) {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [newProjectName, setNewProjectName] = useState("");
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadStage, setUploadStage] = useState<UploadStage>("idle");
  const [uploadError, setUploadError] = useState<string | null>(null);

  const projects = useQuery({
    queryKey: ["projects", userId],
    queryFn: ({ signal }) => getProjects(accessToken, signal),
  });
  const createProjectMutation = useMutation({
    mutationFn: (name: string) => createProject(accessToken, name),
    onSuccess: (project) => {
      queryClient.setQueryData(["projects", userId], (current: typeof projects.data) => [
        project,
        ...(current ?? []),
      ]);
      setSelectedProjectId(project.id);
      setNewProjectName("");
    },
  });

  const availableProjects = projects.data ?? [];
  const activeProjectId = availableProjects.some((project) => project.id === selectedProjectId)
    ? selectedProjectId
    : (availableProjects[0]?.id ?? "");
  const isUploadBusy = !["idle", "success"].includes(uploadStage);

  function handleCreateProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = newProjectName.trim();
    if (normalizedName) {
      createProjectMutation.mutate(normalizedName);
    }
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setUploadStage("idle");
    setUploadError(null);
    setSelectedFile(null);
    if (!file) {
      return;
    }
    if (!ALLOWED_IMAGE_TYPES.has(file.type)) {
      setUploadError("Choose a JPEG, PNG, or WebP image.");
      event.target.value = "";
      return;
    }
    if (file.size <= 0 || file.size > MAX_IMAGE_SIZE_BYTES) {
      setUploadError(`Choose an image between 1 byte and ${formatBytes(MAX_IMAGE_SIZE_BYTES)}.`);
      event.target.value = "";
      return;
    }
    setSelectedFile(file);
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedFile || !activeProjectId || isUploadBusy) {
      return;
    }

    setUploadError(null);
    setUploadStage("validating");
    const validationError = await validateImageFile(selectedFile);
    if (validationError) {
      setUploadStage("idle");
      setUploadError(validationError);
      return;
    }

    try {
      setUploadStage("hashing");
      const sha256 = await computeSha256(selectedFile);
      setUploadStage("initiating");
      const initiation = await initiateUpload(accessToken, {
        projectId: activeProjectId,
        fileName: selectedFile.name,
        mimeType: selectedFile.type,
        sizeBytes: selectedFile.size,
        sha256,
      });
      setUploadStage("uploading");
      await uploadFileToBlob(initiation.uploadUrl, selectedFile, initiation.requiredHeaders);
      setUploadStage("completing");
      await completeUpload(accessToken, initiation.uploadId);
      setUploadStage("success");
      setSelectedFile(null);
      if (fileInput.current) {
        fileInput.current.value = "";
      }
    } catch {
      setUploadStage("idle");
      setUploadError("The image upload could not be completed. Please try again.");
    }
  }

  return (
    <section className="panel workspace" aria-labelledby="workspace-title">
      <p className="eyebrow">Source images</p>
      <h2 id="workspace-title">Projects and uploads</h2>

      <form className="stacked-form" onSubmit={handleCreateProject}>
        <label htmlFor="project-name">New project name</label>
        <div className="inline-form">
          <input
            id="project-name"
            value={newProjectName}
            maxLength={100}
            onChange={(event) => setNewProjectName(event.target.value)}
            required
          />
          <button className="button" type="submit" disabled={createProjectMutation.isPending}>
            {createProjectMutation.isPending ? "Creating…" : "Create project"}
          </button>
        </div>
        {createProjectMutation.isError ? (
          <p className="form-error" role="alert">We could not create the project.</p>
        ) : null}
      </form>

      {projects.isPending ? <p className="status status--pending">Loading projects…</p> : null}
      {projects.isError ? (
        <div className="form-error" role="alert">
          <p>We could not load your projects.</p>
          <button className="text-button" type="button" onClick={() => void projects.refetch()}>
            Try again
          </button>
        </div>
      ) : null}

      {projects.isSuccess ? (
        <form className="stacked-form upload-form" onSubmit={(event) => void handleUpload(event)}>
          <label htmlFor="project-select">Project</label>
          <select
            id="project-select"
            value={activeProjectId}
            onChange={(event) => {
              setSelectedProjectId(event.target.value);
              setUploadError(null);
              setUploadStage("idle");
            }}
            disabled={availableProjects.length === 0 || isUploadBusy}
          >
            {availableProjects.length === 0 ? <option value="">Create a project first</option> : null}
            {availableProjects.map((project) => (
              <option key={project.id} value={project.id}>{project.name}</option>
            ))}
          </select>

          <label htmlFor="source-image">Image</label>
          <input
            ref={fileInput}
            id="source-image"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={handleFileChange}
            disabled={!activeProjectId || isUploadBusy}
          />
          <p className="field-help">
            JPEG, PNG, or WebP. Maximum {formatBytes(MAX_IMAGE_SIZE_BYTES)} and {MAX_IMAGE_PIXEL_COUNT.toLocaleString()} pixels.
          </p>
          {uploadError ? <p className="form-error" role="alert">{uploadError}</p> : null}
          {uploadStage === "success" ? (
            <p className="status status--success" role="status">Image upload complete.</p>
          ) : null}
          {isUploadBusy ? (
            <p className="status status--pending" role="status">{stageMessage(uploadStage)}</p>
          ) : null}
          <button
            className="button"
            type="submit"
            disabled={!selectedFile || !activeProjectId || isUploadBusy}
          >
            Upload image
          </button>
        </form>
      ) : null}
    </section>
  );
}

async function computeSha256(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function validateImageFile(file: File): Promise<string | null> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (!hasExpectedImageSignature(file.type, bytes)) {
    return "The selected file does not match its declared image type.";
  }

  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    return "The selected file could not be decoded as an image.";
  }

  try {
    if (!Number.isSafeInteger(bitmap.width) || !Number.isSafeInteger(bitmap.height)
      || bitmap.width <= 0 || bitmap.height <= 0) {
      return "The selected image has invalid dimensions.";
    }
    if (bitmap.width * bitmap.height > MAX_IMAGE_PIXEL_COUNT) {
      return `The selected image exceeds the ${MAX_IMAGE_PIXEL_COUNT.toLocaleString()} pixel limit.`;
    }
  } finally {
    bitmap.close();
  }
  return null;
}

function hasExpectedImageSignature(mimeType: string, bytes: Uint8Array): boolean {
  if (mimeType === "image/jpeg") {
    return bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff;
  }
  if (mimeType === "image/png") {
    return bytes.length >= 8
      && bytes[0] === 0x89
      && bytes[1] === 0x50
      && bytes[2] === 0x4e
      && bytes[3] === 0x47
      && bytes[4] === 0x0d
      && bytes[5] === 0x0a
      && bytes[6] === 0x1a
      && bytes[7] === 0x0a;
  }
  if (mimeType !== "image/webp") {
    return false;
  }
  return bytes.length >= 12
    && bytes[0] === 0x52
    && bytes[1] === 0x49
    && bytes[2] === 0x46
    && bytes[3] === 0x46
    && bytes[8] === 0x57
    && bytes[9] === 0x45
    && bytes[10] === 0x42
    && bytes[11] === 0x50;
}

function formatBytes(sizeBytes: number): string {
  return `${Math.round(sizeBytes / (1024 * 1024))} MiB`;
}

function stageMessage(stage: UploadStage): string {
  if (stage === "validating") {
    return "Validating image…";
  }
  if (stage === "hashing") {
    return "Checking image integrity…";
  }
  if (stage === "initiating") {
    return "Preparing secure upload…";
  }
  if (stage === "uploading") {
    return "Uploading directly to storage…";
  }
  return "Verifying upload…";
}
