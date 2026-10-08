import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ChangeEvent, type FormEvent, useRef, useState } from "react";

import {
  completeUpload,
  getJob,
  initiateUpload,
  startReconstruction,
  uploadFileToBlob,
} from "../api/client";
import { reconstructionPollInterval } from "../reconstructionPolling";

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

interface SourceImagePanelProps {
  accessToken: string;
  userId: string;
  projectId: string;
}

interface ReconstructionInitiationVariables {
  sourceArtifactId: string;
  idempotencyKey: string;
  stateVersion: number;
}

/** Uploads a project's source photo and starts the paid image-to-3D generation on request. */
export function SourceImagePanel({ accessToken, userId, projectId }: SourceImagePanelProps) {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadStage, setUploadStage] = useState<UploadStage>("idle");
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [readySourceArtifactId, setReadySourceArtifactId] = useState<string | null>(null);
  const [reconstructionJobId, setReconstructionJobId] = useState<string | null>(null);
  const reconstructionAttemptKey = useRef<string | null>(null);
  const reconstructionStateVersion = useRef(0);

  const isUploadBusy = !["idle", "success"].includes(uploadStage);
  const reconstruction = useQuery({
    queryKey: ["reconstruction-job", userId, projectId, reconstructionJobId],
    queryFn: ({ signal }) => getJob(accessToken, reconstructionJobId ?? "", signal),
    enabled: reconstructionJobId !== null,
    refetchInterval: (query) => reconstructionPollInterval(query.state.data?.status),
  });
  const startReconstructionMutation = useMutation({
    mutationFn: (variables: ReconstructionInitiationVariables) => startReconstruction(
      accessToken,
      { projectId, sourceArtifactId: variables.sourceArtifactId },
      variables.idempotencyKey,
    ),
    onSuccess: (job, variables) => {
      if (variables.stateVersion !== reconstructionStateVersion.current) {
        return;
      }
      setReconstructionJobId(job.jobId);
      queryClient.setQueryData(["reconstruction-job", userId, projectId, job.jobId], job);
    },
  });
  const reconstructionStatus = reconstruction.data?.status;
  const isGenerationActive = startReconstructionMutation.isPending
    || reconstructionStatus === "queued"
    || reconstructionStatus === "running";

  function resetReconstructionState() {
    setReadySourceArtifactId(null);
    setReconstructionJobId(null);
    reconstructionAttemptKey.current = null;
    reconstructionStateVersion.current += 1;
    startReconstructionMutation.reset();
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setUploadStage("idle");
    setUploadError(null);
    setSelectedFile(null);
    resetReconstructionState();
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
    if (!selectedFile || isUploadBusy) {
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
        projectId,
        fileName: selectedFile.name,
        mimeType: selectedFile.type,
        sizeBytes: selectedFile.size,
        sha256,
      });
      setUploadStage("uploading");
      await uploadFileToBlob(initiation.uploadUrl, selectedFile, initiation.requiredHeaders);
      setUploadStage("completing");
      const completed = await completeUpload(accessToken, initiation.uploadId);
      setReadySourceArtifactId(completed.uploadId);
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

  function handleStartReconstruction() {
    if (!readySourceArtifactId || isGenerationActive) {
      return;
    }
    if (["succeeded", "failed", "canceled"].includes(reconstructionStatus ?? "")) {
      reconstructionAttemptKey.current = null;
      setReconstructionJobId(null);
    }
    const idempotencyKey = reconstructionAttemptKey.current ?? crypto.randomUUID();
    reconstructionAttemptKey.current = idempotencyKey;
    startReconstructionMutation.mutate({
      sourceArtifactId: readySourceArtifactId,
      idempotencyKey,
      stateVersion: reconstructionStateVersion.current,
    });
  }

  return (
    <section className="panel" aria-labelledby="source-image-title">
      <h2 id="source-image-title" className="panel__title">Photo and 3D model</h2>

      <form className="stacked-form upload-form" onSubmit={(event) => void handleUpload(event)}>
        <label htmlFor="source-image">Image</label>
        <input
          ref={fileInput}
          id="source-image"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          onChange={handleFileChange}
          disabled={isUploadBusy}
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
        <button className="button" type="submit" disabled={!selectedFile || isUploadBusy}>
          Upload image
        </button>
        {readySourceArtifactId ? (
          <div className="stacked-form">
            <button
              className="button"
              type="button"
              onClick={handleStartReconstruction}
              disabled={isGenerationActive}
            >
              Generate 3D model
            </button>
            {startReconstructionMutation.isPending ? (
              <p className="status status--pending" role="status">Preparing generation…</p>
            ) : null}
            {startReconstructionMutation.isError ? (
              <p className="form-error" role="alert">Generation could not be started. Please try again.</p>
            ) : null}
            {reconstruction.data?.status === "queued" ? (
              <p className="status status--pending" role="status">Queued</p>
            ) : null}
            {reconstruction.data?.status === "running" ? (
              <p className="status status--pending" role="status">Generating 3D model…</p>
            ) : null}
            {reconstruction.data?.status === "succeeded" ? (
              <p className="status status--success" role="status">3D model generated</p>
            ) : null}
            {reconstruction.data?.status === "failed" || reconstruction.data?.status === "canceled" ? (
              <p className="form-error" role="alert">Generation failed</p>
            ) : null}
          </div>
        ) : null}
      </form>
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
