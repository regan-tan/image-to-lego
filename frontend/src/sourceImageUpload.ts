import { completeUpload, initiateUpload, uploadFileToBlob } from "./api/client";

export const ACCEPTED_IMAGE_TYPES = "image/jpeg,image/png,image/webp";
const ALLOWED_IMAGE_TYPES = new Set(ACCEPTED_IMAGE_TYPES.split(","));
const DEFAULT_MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024;
const DEFAULT_MAX_IMAGE_PIXEL_COUNT = 40_000_000;
const MAX_PROJECT_NAME_LENGTH = 100;
const configuredMaxImageSize = Number(import.meta.env.VITE_UPLOAD_MAX_IMAGE_SIZE_BYTES);
const configuredMaxImagePixels = Number(import.meta.env.VITE_UPLOAD_MAX_PIXEL_COUNT);

// Client-side limits are UX only; the API enforces the authoritative ones.
export const MAX_IMAGE_SIZE_BYTES = Number.isSafeInteger(configuredMaxImageSize) && configuredMaxImageSize > 0
  ? configuredMaxImageSize
  : DEFAULT_MAX_IMAGE_SIZE_BYTES;
export const MAX_IMAGE_PIXEL_COUNT = Number.isSafeInteger(configuredMaxImagePixels)
  && configuredMaxImagePixels > 0
  ? configuredMaxImagePixels
  : DEFAULT_MAX_IMAGE_PIXEL_COUNT;

export type UploadStage = "validating" | "hashing" | "initiating" | "uploading" | "completing";

/** Instant checks that run as soon as a file is chosen. */
export function checkImageFileBasics(file: File): string | null {
  if (!ALLOWED_IMAGE_TYPES.has(file.type)) {
    return "Choose a JPEG, PNG, or WebP image.";
  }
  if (file.size <= 0 || file.size > MAX_IMAGE_SIZE_BYTES) {
    return `Choose an image between 1 byte and ${formatMaxImageSize()}.`;
  }
  return null;
}

/** Full checks (type, size, file signature, decodable pixels) to run before any upload starts. */
export async function validateSourceImage(file: File): Promise<string | null> {
  const basicProblem = checkImageFileBasics(file);
  if (basicProblem) {
    return basicProblem;
  }

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

interface UploadSourceImageOptions {
  accessToken: string;
  projectId: string;
  file: File;
  onStage: (stage: UploadStage) => void;
}

/**
 * Uploads an already validated image: the API issues a single-blob SAS, the browser PUTs the bytes
 * straight to Azure Blob Storage, then the API confirms the upload. Returns the ready artifact ID.
 */
export async function uploadSourceImage({
  accessToken,
  projectId,
  file,
  onStage,
}: UploadSourceImageOptions): Promise<string> {
  onStage("hashing");
  const sha256 = await computeSha256(file);
  onStage("initiating");
  const initiation = await initiateUpload(accessToken, {
    projectId,
    fileName: file.name,
    mimeType: file.type,
    sizeBytes: file.size,
    sha256,
  });
  onStage("uploading");
  await uploadFileToBlob(initiation.uploadUrl, file, initiation.requiredHeaders);
  onStage("completing");
  const completed = await completeUpload(accessToken, initiation.uploadId);
  return completed.uploadId;
}

export function uploadStageMessage(stage: UploadStage): string {
  if (stage === "validating") {
    return "Checking your photo…";
  }
  if (stage === "hashing") {
    return "Checking image integrity…";
  }
  if (stage === "initiating") {
    return "Preparing secure upload…";
  }
  if (stage === "uploading") {
    return "Uploading your photo…";
  }
  return "Verifying upload…";
}

/** Turns "toy-robot_v2.JPG" into "Toy robot v2" for projects created without a name. */
export function defaultProjectName(fileName: string): string {
  const baseName = fileName.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ").replace(/\s+/g, " ").trim();
  if (!baseName) {
    return "Untitled project";
  }
  const capitalized = baseName.charAt(0).toUpperCase() + baseName.slice(1);
  return capitalized.slice(0, MAX_PROJECT_NAME_LENGTH);
}

export function formatMaxImageSize(): string {
  return `${Math.round(MAX_IMAGE_SIZE_BYTES / (1024 * 1024))} MiB`;
}

async function computeSha256(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
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
