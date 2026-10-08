import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  checkImageFileBasics,
  defaultProjectName,
  type UploadStage,
  uploadSourceImage,
  validateSourceImage,
} from "./sourceImageUpload";

const ACCESS_TOKEN = "test-access-token";
const PROJECT_ID = "eb4d4208-4c79-4bb4-a636-329a37ee5c24";
const UPLOAD_ID = "6817a1e8-e37b-4565-a004-038e01fe8d3f";
const UPLOAD_URL = "https://storage.example.test/artifacts/blob.png?sig=secret";
const PNG_SIGNATURE = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

function makeImage(type = "image/png", bytes = PNG_SIGNATURE, name = "castle.png") {
  const content = new Uint8Array(bytes);
  const file = new File([content], name, { type });
  Object.defineProperty(file, "arrayBuffer", { value: vi.fn().mockResolvedValue(content.buffer) });
  return file;
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function requestHeaders(init: RequestInit | undefined) {
  return new Headers(init?.headers);
}

describe("source image validation", () => {
  beforeEach(() => {
    vi.stubGlobal("createImageBitmap", vi.fn().mockResolvedValue({ width: 2, height: 2, close: vi.fn() }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("rejects unsupported types and empty files instantly", () => {
    expect(checkImageFileBasics(makeImage("image/gif"))).toBe("Choose a JPEG, PNG, or WebP image.");
    expect(checkImageFileBasics(makeImage("image/png", new Uint8Array()))).toContain("between 1 byte");
    expect(checkImageFileBasics(makeImage())).toBeNull();
  });

  it("rejects a file whose bytes do not match its declared type without decoding it", async () => {
    expect(await validateSourceImage(makeImage("image/png", new Uint8Array(8)))).toBe(
      "The selected file does not match its declared image type.",
    );
    expect(createImageBitmap).not.toHaveBeenCalled();
  });

  it("rejects images over the pixel limit and releases the decoded bitmap", async () => {
    const close = vi.fn();
    vi.mocked(createImageBitmap).mockResolvedValueOnce({ width: 10_000, height: 5_000, close } as ImageBitmap);

    expect(await validateSourceImage(makeImage())).toContain("pixel limit");
    expect(close).toHaveBeenCalledOnce();
  });

  it("accepts a valid image", async () => {
    expect(await validateSourceImage(makeImage())).toBeNull();
  });
});

describe("source image upload", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    vi.stubGlobal("crypto", {
      subtle: { digest: vi.fn().mockResolvedValue(new Uint8Array(32).fill(0xab).buffer) },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("uploads directly to Blob and completes only after a successful PUT", async () => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/uploads")) {
        return jsonResponse({
          uploadId: UPLOAD_ID,
          projectId: PROJECT_ID,
          status: "pending",
          uploadUrl: UPLOAD_URL,
          uploadUrlExpiresAt: "2026-10-06T01:10:00Z",
          requiredHeaders: { "x-ms-blob-type": "BlockBlob" },
        }, 201);
      }
      if (url === UPLOAD_URL) {
        return new Response(null, { status: 201 });
      }
      if (url.endsWith(`/api/v1/uploads/${UPLOAD_ID}/complete`)) {
        return jsonResponse({ uploadId: UPLOAD_ID, projectId: PROJECT_ID, status: "ready" });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    const stages: UploadStage[] = [];

    const artifactId = await uploadSourceImage({
      accessToken: ACCESS_TOKEN,
      projectId: PROJECT_ID,
      file: makeImage(),
      onStage: (stage) => stages.push(stage),
    });

    expect(artifactId).toBe(UPLOAD_ID);
    expect(stages).toEqual(["hashing", "initiating", "uploading", "completing"]);
    const calls = vi.mocked(fetch).mock.calls;
    expect(calls.map(([input]) => String(input))).toEqual([
      "http://localhost:8000/api/v1/uploads",
      UPLOAD_URL,
      `http://localhost:8000/api/v1/uploads/${UPLOAD_ID}/complete`,
    ]);
    expect(JSON.parse(String(calls[0]?.[1]?.body))).toEqual({
      projectId: PROJECT_ID,
      fileName: "castle.png",
      mimeType: "image/png",
      sizeBytes: 8,
      sha256: "ab".repeat(32),
    });
    expect(requestHeaders(calls[0]?.[1]).get("Authorization")).toBe(`Bearer ${ACCESS_TOKEN}`);
    expect(calls[1]?.[1]).toEqual(expect.objectContaining({ method: "PUT" }));
    expect(requestHeaders(calls[1]?.[1]).get("Authorization")).toBeNull();
  });

  it("does not confirm the upload when the Blob PUT fails", async () => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/uploads")) {
        return jsonResponse({
          uploadId: UPLOAD_ID,
          projectId: PROJECT_ID,
          status: "pending",
          uploadUrl: UPLOAD_URL,
          uploadUrlExpiresAt: "2026-10-06T01:10:00Z",
          requiredHeaders: {},
        }, 201);
      }
      if (url === UPLOAD_URL) {
        return new Response(null, { status: 500 });
      }
      throw new Error(`Completion should not be called: ${url}`);
    });

    await expect(uploadSourceImage({
      accessToken: ACCESS_TOKEN,
      projectId: PROJECT_ID,
      file: makeImage(),
      onStage: vi.fn(),
    })).rejects.toThrow("Blob upload failed");
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).endsWith("/complete"))).toBe(false);
  });
});

describe("defaultProjectName", () => {
  it("turns a file name into a readable project name", () => {
    expect(defaultProjectName("toy-robot_v2.JPG")).toBe("Toy robot v2");
    expect(defaultProjectName("ceramic mug.png")).toBe("Ceramic mug");
    expect(defaultProjectName(".png")).toBe("Untitled project");
    expect(defaultProjectName(`${"a".repeat(150)}.png`)).toHaveLength(100);
  });
});
