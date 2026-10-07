import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { reconstructionPollInterval } from "../reconstructionPolling";
import { ProjectWorkspace } from "./ProjectWorkspace";

const ACCESS_TOKEN = "test-access-token";
const USER_ID = "0c3d60a8-5117-44e5-821b-abc1c0c8f3d0";
const PROJECT_ID = "eb4d4208-4c79-4bb4-a636-329a37ee5c24";
const SECOND_PROJECT_ID = "6e43e80d-9276-4d37-af4f-12f7f85d4f50";
const UPLOAD_ID = "6817a1e8-e37b-4565-a004-038e01fe8d3f";
const UPLOAD_URL = "https://storage.example.test/artifacts/blob.png?sig=secret";

const project = {
  id: PROJECT_ID,
  name: "Castle",
  createdAt: "2026-10-06T01:00:00Z",
  updatedAt: "2026-10-06T01:00:00Z",
};

function renderWorkspace() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ProjectWorkspace accessToken={ACCESS_TOKEN} userId={USER_ID} />
    </QueryClientProvider>,
  );
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const PNG_SIGNATURE = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

function makeImage(type = "image/png", bytes = PNG_SIGNATURE) {
  const content = new Uint8Array(bytes);
  const file = new File([content], "castle.png", { type });
  Object.defineProperty(file, "arrayBuffer", {
    value: vi.fn().mockResolvedValue(content.buffer),
  });
  return file;
}

function requestHeaders(init: RequestInit | undefined) {
  return new Headers(init?.headers);
}

describe("ProjectWorkspace", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    vi.stubGlobal("crypto", {
      subtle: {
        digest: vi.fn().mockResolvedValue(new Uint8Array(32).fill(0xab).buffer),
      },
      randomUUID: vi.fn().mockReturnValue("f8e8397b-2ed7-4b28-a9e1-8124c136347a"),
    });
    vi.stubGlobal(
      "createImageBitmap",
      vi.fn().mockResolvedValue({ width: 2, height: 2, close: vi.fn() }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("creates a project with the bearer token", async () => {
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/projects") && init?.method === "POST") {
        return jsonResponse(project, 201);
      }
      return jsonResponse([]);
    });
    renderWorkspace();

    fireEvent.change(await screen.findByLabelText("New project name"), {
      target: { value: "Castle" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create project" }));

    expect(await screen.findByRole("option", { name: "Castle" })).toBeInTheDocument();
    const createCall = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === "POST");
    expect(createCall).toBeDefined();
    expect(requestHeaders(createCall?.[1]).get("Authorization")).toBe(`Bearer ${ACCESS_TOKEN}`);
    expect(createCall?.[1]?.body).toBe(JSON.stringify({ name: "Castle" }));
  });

  it("allows the user to select a project", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse([
        project,
        { ...project, id: SECOND_PROJECT_ID, name: "Spaceship" },
      ]),
    );
    renderWorkspace();

    const select = await screen.findByLabelText("Project");
    fireEvent.change(select, { target: { value: SECOND_PROJECT_ID } });

    expect(select).toHaveValue(SECOND_PROJECT_ID);
  });

  it("rejects an unsupported file before upload initiation", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse([project]));
    renderWorkspace();

    fireEvent.change(await screen.findByLabelText("Image"), {
      target: { files: [makeImage("image/gif")] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a JPEG, PNG, or WebP image.");
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("rejects misleading image MIME types with invalid bytes before upload initiation", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse([project]));
    renderWorkspace();

    fireEvent.change(await screen.findByLabelText("Image"), {
      target: { files: [makeImage("image/png", new Uint8Array(8))] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Upload image" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The selected file does not match its declared image type.",
    );
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(createImageBitmap).not.toHaveBeenCalled();
  });

  it("rejects images whose decoded dimensions exceed the pixel limit", async () => {
    const close = vi.fn();
    vi.mocked(createImageBitmap).mockResolvedValueOnce({
      width: 10_000,
      height: 5_000,
      close,
    } as ImageBitmap);
    vi.mocked(fetch).mockResolvedValue(jsonResponse([project]));
    renderWorkspace();

    fireEvent.change(await screen.findByLabelText("Image"), {
      target: { files: [makeImage()] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Upload image" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("pixel limit");
    expect(close).toHaveBeenCalledOnce();
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("uploads directly to Blob and completes only after a successful PUT", async () => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/projects")) {
        return jsonResponse([project]);
      }
      if (url.endsWith("/api/v1/uploads")) {
        return jsonResponse({
          uploadId: UPLOAD_ID,
          projectId: PROJECT_ID,
          status: "pending",
          uploadUrl: UPLOAD_URL,
          uploadUrlExpiresAt: "2026-10-06T01:10:00Z",
          requiredHeaders: {
            "x-ms-blob-type": "BlockBlob",
            "Content-Type": "image/png",
            "x-ms-meta-sha256": "ab".repeat(32),
          },
        }, 201);
      }
      if (url === UPLOAD_URL) {
        return new Response(null, { status: 201 });
      }
      if (url.endsWith(`/api/v1/uploads/${UPLOAD_ID}/complete`)) {
        return jsonResponse({
          uploadId: UPLOAD_ID,
          projectId: PROJECT_ID,
          status: "ready",
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    renderWorkspace();

    fireEvent.change(await screen.findByLabelText("Image"), {
      target: { files: [makeImage()] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Upload image" }));

    expect(await screen.findByText("Image upload complete.")).toBeInTheDocument();
    expect(createImageBitmap).toHaveBeenCalledOnce();
    const calls = vi.mocked(fetch).mock.calls;
    const initiationIndex = calls.findIndex(([input]) => String(input).endsWith("/api/v1/uploads"));
    const blobIndex = calls.findIndex(([input]) => String(input) === UPLOAD_URL);
    const completionIndex = calls.findIndex(([input]) => String(input).endsWith("/complete"));
    expect(initiationIndex).toBeGreaterThan(-1);
    expect(blobIndex).toBeGreaterThan(initiationIndex);
    expect(completionIndex).toBeGreaterThan(blobIndex);
    expect(requestHeaders(calls[initiationIndex]?.[1]).get("Authorization")).toBe(
      `Bearer ${ACCESS_TOKEN}`,
    );
    expect(requestHeaders(calls[completionIndex]?.[1]).get("Authorization")).toBe(
      `Bearer ${ACCESS_TOKEN}`,
    );
    expect(calls[blobIndex]?.[1]).toEqual(expect.objectContaining({ method: "PUT" }));
  });

  it("stops polling after succeeded or failed jobs", () => {
    expect(reconstructionPollInterval("queued")).toBe(5_000);
    expect(reconstructionPollInterval("running")).toBe(5_000);
    expect(reconstructionPollInterval("succeeded")).toBe(false);
    expect(reconstructionPollInterval("failed")).toBe(false);
  });

  it("starts a reconstruction with an idempotency key after upload completion", async () => {
    const jobId = "f8e8397b-2ed7-4b28-a9e1-8124c136347a";
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/projects")) {
        return jsonResponse([project]);
      }
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
        return new Response(null, { status: 201 });
      }
      if (url.endsWith(`/api/v1/uploads/${UPLOAD_ID}/complete`)) {
        return jsonResponse({ uploadId: UPLOAD_ID, projectId: PROJECT_ID, status: "ready" });
      }
      if (url.endsWith("/api/v1/reconstructions") && init?.method === "POST") {
        return jsonResponse({ jobId, projectId: PROJECT_ID, type: "reconstruction", status: "queued" }, 201);
      }
      if (url.endsWith(`/api/v1/jobs/${jobId}`)) {
        return jsonResponse({
          jobId,
          projectId: PROJECT_ID,
          type: "reconstruction",
          status: "queued",
          outputArtifactId: null,
          errorCode: null,
          errorMessage: null,
          createdAt: "2026-10-06T01:00:00Z",
          updatedAt: "2026-10-06T01:00:00Z",
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    renderWorkspace();

    expect(screen.queryByRole("button", { name: "Generate 3D model" })).not.toBeInTheDocument();
    fireEvent.change(await screen.findByLabelText("Image"), { target: { files: [makeImage()] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload image" }));
    const generateButton = await screen.findByRole("button", { name: "Generate 3D model" });
    fireEvent.click(generateButton);

    await screen.findByText("Queued");
    expect(generateButton).toBeDisabled();
    fireEvent.click(generateButton);
    await waitFor(() => {
      const call = vi.mocked(fetch).mock.calls.find(
        ([input, request]) => String(input).endsWith("/api/v1/reconstructions")
          && request?.method === "POST",
      );
      expect(requestHeaders(call?.[1]).get("Idempotency-Key")).toBe(jobId);
    });
    expect(
      vi.mocked(fetch).mock.calls.filter(
        ([input, request]) => String(input).endsWith("/api/v1/reconstructions")
          && request?.method === "POST",
      ),
    ).toHaveLength(1);
  });

  it("does not install an initiation response after the source image changes", async () => {
    const jobId = "f8e8397b-2ed7-4b28-a9e1-8124c136347a";
    let resolveInitiation: ((response: Response) => void) | undefined;
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/projects")) {
        return jsonResponse([project]);
      }
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
        return new Response(null, { status: 201 });
      }
      if (url.endsWith(`/api/v1/uploads/${UPLOAD_ID}/complete`)) {
        return jsonResponse({ uploadId: UPLOAD_ID, projectId: PROJECT_ID, status: "ready" });
      }
      if (url.endsWith("/api/v1/reconstructions") && init?.method === "POST") {
        return new Promise<Response>((resolve) => {
          resolveInitiation = resolve;
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    renderWorkspace();

    fireEvent.change(await screen.findByLabelText("Image"), { target: { files: [makeImage()] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload image" }));
    fireEvent.click(await screen.findByRole("button", { name: "Generate 3D model" }));
    await waitFor(() => expect(resolveInitiation).toBeDefined());

    fireEvent.change(screen.getByLabelText("Image"), { target: { files: [makeImage()] } });
    resolveInitiation?.(
      jsonResponse({ jobId, projectId: PROJECT_ID, type: "reconstruction", status: "queued" }, 201),
    );

    await waitFor(() => expect(screen.queryByText("Queued")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Generate 3D model" })).not.toBeInTheDocument();
  });

  it("prevents project switching while reconstruction initiation is pending", async () => {
    let resolveInitiation: ((response: Response) => void) | undefined;
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/projects")) {
        return jsonResponse([project, { ...project, id: SECOND_PROJECT_ID, name: "Spaceship" }]);
      }
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
        return new Response(null, { status: 201 });
      }
      if (url.endsWith(`/api/v1/uploads/${UPLOAD_ID}/complete`)) {
        return jsonResponse({ uploadId: UPLOAD_ID, projectId: PROJECT_ID, status: "ready" });
      }
      if (url.endsWith("/api/v1/reconstructions") && init?.method === "POST") {
        return new Promise<Response>((resolve) => {
          resolveInitiation = resolve;
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    renderWorkspace();

    fireEvent.change(await screen.findByLabelText("Image"), { target: { files: [makeImage()] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload image" }));
    fireEvent.click(await screen.findByRole("button", { name: "Generate 3D model" }));
    await waitFor(() => expect(resolveInitiation).toBeDefined());
    expect(screen.getByLabelText("Project")).toBeDisabled();
  });

  it("surfaces a Blob upload failure and does not call completion", async () => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/projects")) {
        return jsonResponse([project]);
      }
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
    renderWorkspace();

    fireEvent.change(await screen.findByLabelText("Image"), {
      target: { files: [makeImage()] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Upload image" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The image upload could not be completed.",
    );
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).endsWith("/complete"))).toBe(false);
  });

  it("surfaces a completion verification failure", async () => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/projects")) {
        return jsonResponse([project]);
      }
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
        return new Response(null, { status: 201 });
      }
      if (url.endsWith("/complete")) {
        return jsonResponse({ detail: "The uploaded image was not found." }, 409);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    renderWorkspace();

    fireEvent.change(await screen.findByLabelText("Image"), {
      target: { files: [makeImage()] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Upload image" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The image upload could not be completed.",
    );
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).endsWith("/complete"))).toBe(true);
  });
});
