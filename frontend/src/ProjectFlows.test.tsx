import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { Session } from "@supabase/supabase-js";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import type { ProjectDetail } from "./schemas/projects";

const authMock = vi.hoisted(() => ({
  getSession: vi.fn(),
  onAuthStateChange: vi.fn(),
  signOut: vi.fn(),
}));

vi.mock("./lib/supabase", () => ({
  isSupabaseConfigured: true,
  supabase: { auth: authMock },
}));

const session = {
  access_token: "test-access-token",
  user: { id: "user-123", email: "builder@example.com" },
} as Session;

const PROJECT_ID = "eb4d4208-4c79-4bb4-a636-329a37ee5c24";
const ARTIFACT_ID = "6817a1e8-e37b-4565-a004-038e01fe8d3f";
const JOB_ID = "f8e8397b-2ed7-4b28-a9e1-8124c136347a";
const UPLOAD_URL = "https://storage.example.test/artifacts/blob.png?sig=secret";
const PNG_SIGNATURE = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

const READY_SOURCE_IMAGE = {
  artifactId: ARTIFACT_ID,
  mimeType: "image/png",
  sizeBytes: 2_400_000,
  createdAt: "2026-10-08T09:01:00Z",
};

function projectDetail(overrides: Partial<ProjectDetail> = {}): ProjectDetail {
  return {
    id: PROJECT_ID,
    name: "Castle",
    status: "needs_photo",
    createdAt: "2026-10-08T09:00:00Z",
    updatedAt: "2026-10-08T09:00:00Z",
    sourceImage: null,
    latestReconstruction: null,
    ...overrides,
  };
}

function reconstruction(
  status: "queued" | "running" | "succeeded" | "failed",
  errorMessage: string | null = null,
): ProjectDetail["latestReconstruction"] {
  return {
    jobId: JOB_ID,
    status,
    outputArtifactId: status === "succeeded" ? "9a1c0e1e-3a7a-4d6b-9a37-5f0c2f2b7b11" : null,
    errorCode: errorMessage ? "provider_timeout" : null,
    errorMessage,
    createdAt: "2026-10-08T09:02:00Z",
    updatedAt: "2026-10-08T09:03:00Z",
  };
}

function makeImage(type = "image/png", name = "castle.png") {
  const content = new Uint8Array(PNG_SIGNATURE);
  const file = new File([content], name, { type });
  Object.defineProperty(file, "arrayBuffer", { value: vi.fn().mockResolvedValue(content.buffer) });
  return file;
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

interface FakeApiOptions {
  project?: ProjectDetail | null;
  blobUploadFailures?: number;
  generationStartFailures?: number;
}

/** A tiny in-memory stand-in for the backend that changes state the way the real API does. */
function installFakeApi({ project = null, blobUploadFailures = 0, generationStartFailures = 0 }: FakeApiOptions = {}) {
  let current = project;
  let blobFailuresLeft = blobUploadFailures;
  let generationFailuresLeft = generationStartFailures;
  const requests: { method: string; path: string; init?: RequestInit }[] = [];

  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url === UPLOAD_URL) {
      requests.push({ method, path: "blob", init });
      if (blobFailuresLeft > 0) {
        blobFailuresLeft -= 1;
        return new Response(null, { status: 500 });
      }
      return new Response(null, { status: 201 });
    }

    const path = new URL(url).pathname;
    requests.push({ method, path, init });
    const summary = (detail: ProjectDetail) => ({
      id: detail.id,
      name: detail.name,
      status: detail.status,
      createdAt: detail.createdAt,
      updatedAt: detail.updatedAt,
    });

    if (path === "/api/v1/projects" && method === "POST") {
      current = projectDetail({ name: JSON.parse(String(init?.body)).name as string });
      return jsonResponse(summary(current), 201);
    }
    if (path === "/api/v1/projects") {
      return jsonResponse(current ? [summary(current)] : []);
    }
    if (path === `/api/v1/projects/${PROJECT_ID}`) {
      return current ? jsonResponse(current) : jsonResponse({ detail: "The project does not exist." }, 404);
    }
    if (path === "/api/v1/uploads") {
      return jsonResponse({
        uploadId: ARTIFACT_ID,
        projectId: PROJECT_ID,
        status: "pending",
        uploadUrl: UPLOAD_URL,
        uploadUrlExpiresAt: "2026-10-08T09:10:00Z",
        requiredHeaders: {},
      }, 201);
    }
    if (path === `/api/v1/uploads/${ARTIFACT_ID}/complete` && current) {
      current = { ...current, status: "photo_ready", sourceImage: READY_SOURCE_IMAGE, latestReconstruction: null };
      return jsonResponse({ uploadId: ARTIFACT_ID, projectId: PROJECT_ID, status: "ready" });
    }
    if (path === "/api/v1/reconstructions" && current) {
      if (generationFailuresLeft > 0) {
        generationFailuresLeft -= 1;
        return jsonResponse({ detail: "Temporarily unavailable." }, 503);
      }
      current = { ...current, status: "generating", latestReconstruction: reconstruction("queued") };
      return jsonResponse({ jobId: JOB_ID, projectId: PROJECT_ID, type: "reconstruction", status: "queued" }, 201);
    }
    throw new Error(`Unexpected request: ${method} ${url}`);
  });

  return {
    posts: (path: string) => requests.filter((request) => request.method === "POST" && request.path === path),
  };
}

function renderApp(route: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[route]}>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

function idempotencyKey(init: RequestInit | undefined) {
  return new Headers(init?.headers).get("Idempotency-Key");
}

describe("project flows", () => {
  let uuidCounter = 0;

  beforeEach(() => {
    uuidCounter = 0;
    vi.stubGlobal("fetch", vi.fn());
    vi.stubGlobal("crypto", {
      subtle: { digest: vi.fn().mockResolvedValue(new Uint8Array(32).fill(0xab).buffer) },
      randomUUID: vi.fn(() => `00000000-0000-4000-8000-${String(++uuidCounter).padStart(12, "0")}`),
    });
    vi.stubGlobal("createImageBitmap", vi.fn().mockResolvedValue({ width: 2, height: 2, close: vi.fn() }));
    URL.createObjectURL = vi.fn(() => "blob:preview");
    URL.revokeObjectURL = vi.fn();
    authMock.getSession.mockResolvedValue({ data: { session } });
    authMock.onAuthStateChange.mockReturnValue({ data: { subscription: { unsubscribe: vi.fn() } } });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("creates a project from a photo, names it after the file and opens it ready to generate", async () => {
    const api = installFakeApi();
    renderApp("/");

    fireEvent.click(await screen.findByRole("button", { name: "New project" }));
    const dialog = screen.getByRole("dialog", { name: "New project" });
    fireEvent.change(within(dialog).getByLabelText(/Drag a photo here/), { target: { files: [makeImage()] } });

    expect(within(dialog).getByLabelText(/Project name/)).toHaveAttribute("placeholder", "Castle");
    fireEvent.click(within(dialog).getByRole("button", { name: "Create project" }));

    expect(await screen.findByRole("heading", { name: "Ready to make a 3D model" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Castle", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("Photo ready")).toBeInTheDocument();
    expect(api.posts("/api/v1/projects")).toHaveLength(1);
    expect(api.posts("/api/v1/projects")[0]?.init?.body).toBe(JSON.stringify({ name: "Castle" }));
    expect(api.posts("/api/v1/reconstructions")).toHaveLength(0);
  });

  it("rejects an unsupported photo before creating anything", async () => {
    const api = installFakeApi();
    renderApp("/");

    fireEvent.click(await screen.findByRole("button", { name: "New project" }));
    const dialog = screen.getByRole("dialog", { name: "New project" });
    fireEvent.change(within(dialog).getByLabelText(/Drag a photo here/), {
      target: { files: [makeImage("image/gif", "castle.gif")] },
    });

    expect(within(dialog).getByRole("alert")).toHaveTextContent("Choose a JPEG, PNG, or WebP image.");
    expect(within(dialog).getByRole("button", { name: "Create project" })).toBeDisabled();
    expect(api.posts("/api/v1/projects")).toHaveLength(0);
  });

  it("retries a failed photo upload without creating a second project", async () => {
    const api = installFakeApi({ blobUploadFailures: 1 });
    renderApp("/");

    fireEvent.click(await screen.findByRole("button", { name: "New project" }));
    const dialog = screen.getByRole("dialog", { name: "New project" });
    fireEvent.change(within(dialog).getByLabelText(/Drag a photo here/), { target: { files: [makeImage()] } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create project" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Your project was created, but the photo did not upload.",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("heading", { name: "Ready to make a 3D model" })).toBeInTheDocument();
    expect(api.posts("/api/v1/projects")).toHaveLength(1);
  });

  it("starts generation only when asked and reuses the idempotency key when retrying the same attempt", async () => {
    const api = installFakeApi({
      project: projectDetail({ status: "photo_ready", sourceImage: READY_SOURCE_IMAGE }),
      generationStartFailures: 1,
    });
    renderApp(`/projects/${PROJECT_ID}`);

    const generateButton = await screen.findByRole("button", { name: "Generate 3D model" });
    expect(api.posts("/api/v1/reconstructions")).toHaveLength(0);

    fireEvent.click(generateButton);
    expect(await screen.findByRole("alert")).toHaveTextContent("We could not start generating.");
    fireEvent.click(screen.getByRole("button", { name: "Generate 3D model" }));

    expect(await screen.findByRole("heading", { name: "Building your 3D model" })).toBeInTheDocument();
    const attempts = api.posts("/api/v1/reconstructions");
    expect(attempts).toHaveLength(2);
    expect(idempotencyKey(attempts[0]?.init)).toBe(idempotencyKey(attempts[1]?.init));
    expect(JSON.parse(String(attempts[0]?.init?.body))).toEqual({
      projectId: PROJECT_ID,
      sourceArtifactId: ARTIFACT_ID,
    });
  });

  it("shows queue progress and the current brick while generating", async () => {
    installFakeApi({
      project: projectDetail({
        status: "generating",
        sourceImage: READY_SOURCE_IMAGE,
        latestReconstruction: reconstruction("running"),
      }),
    });
    renderApp(`/projects/${PROJECT_ID}`);

    expect(await screen.findByRole("heading", { name: "Building your 3D model" })).toBeInTheDocument();
    expect(screen.getByText("Generating the 3D model")).toBeInTheDocument();
    const progress = screen.getByRole("list", { name: "Progress" });
    expect(within(progress).getByText("3D model").closest("li")).toHaveAttribute("aria-current", "step");
    expect(screen.queryByRole("button", { name: "Generate 3D model" })).not.toBeInTheDocument();
  });

  it("explains a failed generation and lets the user try again with a new attempt", async () => {
    const api = installFakeApi({
      project: projectDetail({
        status: "failed",
        sourceImage: READY_SOURCE_IMAGE,
        latestReconstruction: reconstruction("failed", "The generation did not finish in time."),
      }),
    });
    renderApp(`/projects/${PROJECT_ID}`);

    expect(await screen.findByRole("alert")).toHaveTextContent("The generation did not finish in time.");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("heading", { name: "Building your 3D model" })).toBeInTheDocument();
    expect(api.posts("/api/v1/reconstructions")).toHaveLength(1);
    expect(idempotencyKey(api.posts("/api/v1/reconstructions")[0]?.init)).toBeTruthy();
  });

  it("offers LEGO conversion as coming soon once the 3D model is ready", async () => {
    installFakeApi({
      project: projectDetail({
        status: "model_ready",
        sourceImage: READY_SOURCE_IMAGE,
        latestReconstruction: reconstruction("succeeded"),
      }),
    });
    renderApp(`/projects/${PROJECT_ID}`);

    expect(await screen.findByRole("heading", { name: "Your 3D model is ready" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Convert to LEGO/ })).toBeDisabled();
    expect(screen.getByText("3D model ready", { selector: ".badge" })).toBeInTheDocument();
  });

  it("lets a project without a photo upload one from its page", async () => {
    installFakeApi({ project: projectDetail() });
    renderApp(`/projects/${PROJECT_ID}`);

    expect(await screen.findByRole("heading", { name: "Add a photo" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Drag a photo here/), { target: { files: [makeImage()] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload photo" }));

    expect(await screen.findByRole("heading", { name: "Ready to make a 3D model" })).toBeInTheDocument();
  });

  it("shows a not found message for a project the user does not have", async () => {
    installFakeApi();
    renderApp(`/projects/${PROJECT_ID}`);

    expect(await screen.findByRole("heading", { name: "Project not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All projects" })).toHaveAttribute("href", "/");
  });

  it("shows each project's status as a brick badge on its card", async () => {
    installFakeApi({ project: projectDetail({ status: "generating" }) });
    renderApp("/");

    const card = await screen.findByRole("link", { name: /Castle/ });
    expect(within(card).getByText("Generating 3D")).toBeInTheDocument();
  });
});

describe("waiting for a slow generation start", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    vi.stubGlobal("crypto", { randomUUID: vi.fn(() => "00000000-0000-4000-8000-000000000001") });
    authMock.getSession.mockResolvedValue({ data: { session } });
    authMock.onAuthStateChange.mockReturnValue({ data: { subscription: { unsubscribe: vi.fn() } } });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("disables the generate button while the request is in flight", async () => {
    let generationRequests = 0;
    vi.mocked(fetch).mockImplementation(async (input) => {
      const path = new URL(String(input)).pathname;
      if (path === "/api/v1/reconstructions") {
        generationRequests += 1;
        return new Promise<Response>(() => undefined);
      }
      return jsonResponse(projectDetail({ status: "photo_ready", sourceImage: READY_SOURCE_IMAGE }));
    });
    renderApp(`/projects/${PROJECT_ID}`);

    fireEvent.click(await screen.findByRole("button", { name: "Generate 3D model" }));
    const startingButton = await screen.findByRole("button", { name: "Starting…" });
    fireEvent.click(startingButton);

    expect(startingButton).toBeDisabled();
    await waitFor(() => expect(generationRequests).toBe(1));
  });
});
