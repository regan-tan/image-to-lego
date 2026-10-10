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

// jsdom has no WebGL, so the lazily loaded Three.js viewer is replaced by a stand-in.
vi.mock("./components/ModelViewer", () => ({
  default: ({ url }: { url: string }) => <div data-testid="model-viewer" data-url={url} />,
}));
vi.mock("./components/LegoModelViewer", () => ({
  default: () => <div data-testid="lego-model-viewer" />,
}));

const downloadMock = vi.hoisted(() => ({ startBrowserDownload: vi.fn() }));
vi.mock("./browserDownload", () => downloadMock);

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

const MODEL_ARTIFACT_ID = "9a1c0e1e-3a7a-4d6b-9a37-5f0c2f2b7b11";
const LEGO_ARTIFACT_ID = "1a1c0e1e-3a7a-4d6b-9a37-5f0c2f2b7b12";
const REPLACEMENT_LEGO_ARTIFACT_ID = "2a1c0e1e-3a7a-4d6b-9a37-5f0c2f2b7b12";
const REPLACEMENT_JOB_ID = "f8d8397b-2ed7-4b28-a9e1-8124c136347a";

function projectDetail(overrides: Partial<ProjectDetail> = {}): ProjectDetail {
  const detail: ProjectDetail = {
    id: PROJECT_ID,
    name: "Castle",
    status: "needs_photo",
    sourceImageArtifactId: null,
    createdAt: "2026-10-08T09:00:00Z",
    updatedAt: "2026-10-08T09:00:00Z",
    sourceImage: null,
    latestReconstruction: null,
    latestLegoModel: null,
    ...overrides,
  };
  return { ...detail, sourceImageArtifactId: detail.sourceImage?.artifactId ?? null };
}

function readUrlFor(artifactId: string, download = false) {
  return `https://storage.example.test/${artifactId}?sp=r${download ? "&rscd=attachment" : ""}&sig=read`;
}

function reconstruction(
  status: "queued" | "running" | "succeeded" | "failed",
  errorMessage: string | null = null,
): ProjectDetail["latestReconstruction"] {
  return {
    jobId: JOB_ID,
    status,
    outputArtifactId: status === "succeeded" ? MODEL_ARTIFACT_ID : null,
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
  conversionStartFailures?: number;
  conversionResults?: FakeConversionResult[];
  delayedLegoArtifactId?: string;
  invalidLegoArtifactId?: string;
  legoTargetPartsByArtifact?: Record<string, number | null>;
}

interface FakeConversionResult {
  jobId: string;
  status: "queued" | "running" | "succeeded" | "failed" | "canceled";
  outputArtifactId?: string;
  errorMessage?: string;
}

function legoModelResponse(partCount: number, targetParts: number | null = 300) {
  const placements = Array.from({ length: partCount }, (_, index) => ({
    brickType: "brick_2x2",
    dimensions: { lengthStuds: 2, widthStuds: 2, heightBricks: 1 },
    position: { x: index * 2, y: 0, z: 0 },
    orientationDegrees: index % 2 === 0 ? 0 : 90,
    color: "light_bluish_gray",
  }));
  return {
    partCount,
    dimensions: { widthStuds: 2, depthStuds: 2, heightBricks: 1, widthMm: 16, depthMm: 16, heightMm: 9.6 },
    metadata: {
      algorithmVersion: "surface-grid-v1",
      sourceSha256: "a",
      ...(targetParts === null ? {} : { targetParts }),
      occupiedCellCount: 4,
      gridSize: { widthStuds: 2, depthStuds: 2, heightBricks: 1 },
      candidateCount: 1,
      occupancyMode: "surface",
    },
    placements,
  };
}

/** A tiny in-memory stand-in for the backend that changes state the way the real API does. */
function installFakeApi({
  project = null,
  blobUploadFailures = 0,
  generationStartFailures = 0,
  conversionStartFailures = 0,
  conversionResults = [],
  delayedLegoArtifactId,
  invalidLegoArtifactId,
  legoTargetPartsByArtifact = {},
}: FakeApiOptions = {}) {
  let current = project;
  let blobFailuresLeft = blobUploadFailures;
  let generationFailuresLeft = generationStartFailures;
  let conversionFailuresLeft = conversionStartFailures;
  let conversionResult: FakeConversionResult = {
    jobId: JOB_ID,
    status: "succeeded",
    outputArtifactId: LEGO_ARTIFACT_ID,
  };
  let conversionStarts = 0;
  let resolveDelayedLegoModel: ((response: Response) => void) | null = null;
  const requests: { method: string; path: string; init?: RequestInit }[] = [];

  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url === readUrlFor(LEGO_ARTIFACT_ID) || url === readUrlFor(REPLACEMENT_LEGO_ARTIFACT_ID)) {
      if (url === readUrlFor(delayedLegoArtifactId ?? "")) {
        return new Promise<Response>((resolve) => {
          resolveDelayedLegoModel = resolve;
        });
      }
      if (url === readUrlFor(invalidLegoArtifactId ?? "")) {
        return jsonResponse({ partCount: "not a number" });
      }
      const artifactId = url === readUrlFor(LEGO_ARTIFACT_ID)
        ? LEGO_ARTIFACT_ID
        : REPLACEMENT_LEGO_ARTIFACT_ID;
      const targetParts = Object.hasOwn(legoTargetPartsByArtifact, artifactId)
        ? legoTargetPartsByArtifact[artifactId]
        : 300;
      return jsonResponse(legoModelResponse(artifactId === LEGO_ARTIFACT_ID ? 1 : 2, targetParts));
    }
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
      sourceImageArtifactId: detail.sourceImageArtifactId,
      createdAt: detail.createdAt,
      updatedAt: detail.updatedAt,
    });

    const readUrlMatch = /^\/api\/v1\/artifacts\/([^/]+)\/read-url$/.exec(path);
    if (readUrlMatch?.[1]) {
      const download = new URL(url).searchParams.get("download") === "true";
      return jsonResponse({ url: readUrlFor(readUrlMatch[1], download), expiresAt: "2099-01-01T00:00:00Z" });
    }

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
      current = {
        ...current,
        status: "photo_ready",
        sourceImageArtifactId: ARTIFACT_ID,
        sourceImage: READY_SOURCE_IMAGE,
        latestReconstruction: null,
      };
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
    if (path === "/api/v1/conversions" && current) {
      if (conversionFailuresLeft > 0) {
        conversionFailuresLeft -= 1;
        return jsonResponse({ detail: "Temporarily unavailable." }, 503);
      }
      conversionResult = conversionResults[conversionStarts] ?? conversionResult;
      conversionStarts += 1;
      return jsonResponse({ projectId: PROJECT_ID, type: "conversion", ...conversionResult }, 201);
    }
    if (path === `/api/v1/jobs/${conversionResult.jobId}`) {
      return jsonResponse({ projectId: PROJECT_ID, type: "conversion", ...conversionResult });
    }
    throw new Error(`Unexpected request: ${method} ${url}`);
  });

  return {
    posts: (path: string) => requests.filter((request) => request.method === "POST" && request.path === path),
    readUrlRequests: (artifactId: string) => requests.filter(
      (request) => request.path === `/api/v1/artifacts/${artifactId}/read-url`,
    ),
    resolveDelayedLegoModel: () => resolveDelayedLegoModel?.(jsonResponse(legoModelResponse(
      2,
      delayedLegoArtifactId && Object.hasOwn(legoTargetPartsByArtifact, delayedLegoArtifactId)
        ? legoTargetPartsByArtifact[delayedLegoArtifactId]
        : 300,
    ))),
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

function conversionRequestBody(init: RequestInit | undefined) {
  return JSON.parse(String(init?.body)) as {
    projectId: string;
    sourceArtifactId: string;
    targetParts: number;
    upAxis: "y";
  };
}

function complexityRadio(label: "Simple" | "Balanced" | "Detailed") {
  return screen.getByRole("radio", { name: new RegExp(label) });
}

function legoSummary() {
  const summary = screen.getByRole("heading", { name: "Build summary" }).parentElement;
  if (!summary) throw new Error("LEGO summary is missing its content container.");
  return summary;
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

  it("defaults the next LEGO build to Balanced without starting a conversion", async () => {
    const api = installFakeApi({
      project: projectDetail({
        status: "model_ready",
        sourceImage: READY_SOURCE_IMAGE,
        latestReconstruction: reconstruction("succeeded"),
      }),
    });
    renderApp(`/projects/${PROJECT_ID}`);

    await screen.findByRole("heading", { name: "Your 3D model is ready" });

    expect(complexityRadio("Balanced")).toBeChecked();
    expect(complexityRadio("Simple")).not.toBeChecked();
    expect(complexityRadio("Detailed")).not.toBeChecked();
    expect(api.posts("/api/v1/conversions")).toHaveLength(0);
  });

  it.each([
    ["Simple", 100],
    ["Balanced", 300],
    ["Detailed", 600],
  ] as const)("sends the %s target only after Convert to LEGO is clicked", async (label, targetParts) => {
    const api = installFakeApi({
      project: projectDetail({
        status: "model_ready",
        sourceImage: READY_SOURCE_IMAGE,
        latestReconstruction: reconstruction("succeeded"),
      }),
    });
    renderApp(`/projects/${PROJECT_ID}`);

    fireEvent.click(await screen.findByRole("radio", { name: new RegExp(label) }));
    expect(api.posts("/api/v1/conversions")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Convert to LEGO" }));

    await waitFor(() => expect(api.posts("/api/v1/conversions")).toHaveLength(1));
    expect(conversionRequestBody(api.posts("/api/v1/conversions")[0]?.init)).toEqual({
      projectId: PROJECT_ID,
      sourceArtifactId: MODEL_ARTIFACT_ID,
      targetParts,
      upAxis: "y",
    });
    expect(await screen.findByRole("heading", { name: "Your LEGO model is ready" })).toBeInTheDocument();
  });

  it("freezes the Detailed request body and idempotency key for an ambiguous retry", async () => {
    const api = installFakeApi({
      project: projectDetail({
        status: "model_ready",
        sourceImage: READY_SOURCE_IMAGE,
        latestReconstruction: reconstruction("succeeded"),
      }),
      conversionStartFailures: 1,
    });
    renderApp(`/projects/${PROJECT_ID}`);

    fireEvent.click(await screen.findByRole("radio", { name: /Detailed/ }));
    fireEvent.click(screen.getByRole("button", { name: "Convert to LEGO" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("We could not start the conversion.");

    fireEvent.click(complexityRadio("Simple"));
    fireEvent.click(screen.getByRole("button", { name: "Convert to LEGO" }));

    await waitFor(() => expect(api.posts("/api/v1/conversions")).toHaveLength(2));
    const attempts = api.posts("/api/v1/conversions");
    expect(idempotencyKey(attempts[0]?.init)).toBe(idempotencyKey(attempts[1]?.init));
    expect(conversionRequestBody(attempts[0]?.init).targetParts).toBe(600);
    expect(conversionRequestBody(attempts[1]?.init).targetParts).toBe(600);
  });

  it("disables the selected complexity while conversion is queued", async () => {
    installFakeApi({
      project: projectDetail({
        status: "model_ready",
        sourceImage: READY_SOURCE_IMAGE,
        latestReconstruction: reconstruction("succeeded"),
      }),
      conversionResults: [{ jobId: JOB_ID, status: "queued" }],
    });
    renderApp(`/projects/${PROJECT_ID}`);

    fireEvent.click(await screen.findByRole("radio", { name: /Detailed/ }));
    fireEvent.click(screen.getByRole("button", { name: "Convert to LEGO" }));

    expect(await screen.findByText("Creating a Detailed LEGO build...")).toBeInTheDocument();
    expect(complexityRadio("Simple")).toBeDisabled();
    expect(complexityRadio("Balanced")).toBeDisabled();
    expect(complexityRadio("Detailed")).toBeDisabled();
  });

  it("shows a completed LEGO build in the primary preview and lets the user switch views", async () => {
    const api = installFakeApi({
      project: projectDetail({
        status: "model_ready",
        sourceImage: READY_SOURCE_IMAGE,
        latestReconstruction: reconstruction("succeeded"),
      }),
    });
    renderApp(`/projects/${PROJECT_ID}`);

    expect(await screen.findByRole("heading", { name: "Your 3D model is ready" })).toBeInTheDocument();
    expect(screen.getByText("Next, you’ll be able to turn it into a LEGO build with a parts list and building steps.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "LEGO model" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Convert to LEGO" }));
    expect(await screen.findByRole("heading", { name: "Build summary" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Your LEGO model is ready" })).toBeInTheDocument();
    expect(screen.getByText("Explore the LEGO model, review its parts list, or convert it again.")).toBeInTheDocument();
    expect(screen.queryByText("Next, you’ll be able to turn it into a LEGO build with a parts list and building steps.")).not.toBeInTheDocument();
    expect(screen.getByTestId("lego-model-viewer")).toBeInTheDocument();
    const completedBuildView = screen.getByRole("group", { name: "Completed build view" });
    expect(within(completedBuildView).getByRole("button", { name: "LEGO model" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("1 total parts")).toBeInTheDocument();
    expect(screen.getByText("1 unique part types")).toBeInTheDocument();
    const summary = screen.getByRole("heading", { name: "Build summary" });
    const complexity = screen.getByRole("group", { name: "Build complexity" });
    expect(summary.compareDocumentPosition(complexity) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "View full parts list" }));
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "2×2 brick" })).toBeInTheDocument();
    expect(api.posts("/api/v1/conversions")).toHaveLength(1);
    fireEvent.click(within(completedBuildView).getByRole("button", { name: "LEGO model" }));
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("LEGO model ready", { selector: ".badge" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Progress" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "3D model" }));
    expect(await screen.findByTestId("model-viewer")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Photo" }));
    expect(await screen.findByRole("img", { name: "Photo of Castle" })).toBeInTheDocument();

    const conversion = api.posts("/api/v1/conversions")[0];
    expect(JSON.parse(String(conversion?.init?.body))).toEqual({ projectId: PROJECT_ID, sourceArtifactId: MODEL_ARTIFACT_ID, targetParts: 300, upAxis: "y" });
    expect(idempotencyKey(conversion?.init)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Convert again" }));
    await waitFor(() => expect(api.posts("/api/v1/conversions")).toHaveLength(2));
    expect(idempotencyKey(api.posts("/api/v1/conversions")[1]?.init)).not.toBe(idempotencyKey(conversion?.init));
  });

  it("does not show a LEGO result or start conversion for an existing project without one", async () => {
    const api = installFakeApi({
      project: projectDetail({
        status: "model_ready",
        sourceImage: READY_SOURCE_IMAGE,
        latestReconstruction: reconstruction("succeeded"),
      }),
    });
    renderApp(`/projects/${PROJECT_ID}`);

    await screen.findByRole("heading", { name: "Your 3D model is ready" });

    const progress = screen.getByRole("list", { name: "Progress" });
    expect(within(progress).getByText("LEGO build")).toHaveTextContent("current step");
    expect(screen.queryByRole("button", { name: "LEGO model" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Build summary" })).not.toBeInTheDocument();
    expect(api.posts("/api/v1/conversions")).toHaveLength(0);
  });

  it("rehydrates a saved LEGO model without starting a conversion", async () => {
    const api = installFakeApi({
      project: projectDetail({
        status: "model_ready",
        sourceImage: READY_SOURCE_IMAGE,
        latestReconstruction: reconstruction("succeeded"),
        latestLegoModel: { artifactId: LEGO_ARTIFACT_ID },
      }),
    });
    renderApp(`/projects/${PROJECT_ID}`);

    expect(await screen.findByRole("heading", { name: "Build summary" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Your LEGO model is ready" })).toBeInTheDocument();
    expect(screen.getByText("Explore the LEGO model, review its parts list, or convert it again.")).toBeInTheDocument();
    expect(api.readUrlRequests(LEGO_ARTIFACT_ID)).toHaveLength(1);
    expect(api.posts("/api/v1/conversions")).toHaveLength(0);
    expect(screen.getByText("LEGO model ready", { selector: ".badge" })).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Completed build view" })).getByRole("button", { name: "LEGO model" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("lego-model-viewer")).toBeInTheDocument();
    expect(legoSummary()).toHaveTextContent("1 parts");
    expect(screen.getByRole("heading", { name: "Parts list" })).toBeInTheDocument();
    expect(screen.getByText("1 total parts")).toBeInTheDocument();
    expect(screen.getByText("1 unique part types")).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("group", { name: "Completed build view" })).getByRole("button", { name: "Parts list" }));
    expect(screen.getByRole("table")).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("group", { name: "Completed build view" })).getByRole("button", { name: "LEGO model" }));
    fireEvent.click(screen.getByRole("button", { name: "Download parts list (.csv)" }));
    const csvBlob = vi.mocked(URL.createObjectURL).mock.calls.at(-1)?.[0];
    expect(csvBlob).toBeInstanceOf(Blob);
    if (!(csvBlob instanceof Blob)) throw new Error("The parts list download did not create a Blob.");
    expect(csvBlob.type).toBe("text/csv");
    await expect(csvBlob.text()).resolves.toBe("Part,Length Studs,Width Studs,Height Bricks,Color,Quantity\r\n2×2 brick,2,2,1,Light Bluish Gray,1");
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview");
    expect(legoSummary()).toHaveTextContent("2 × 2 studs");
    expect(screen.queryByRole("list", { name: "Progress" })).not.toBeInTheDocument();
  });

  it.each([
    [100, "Simple", "Simple target"],
    [300, "Balanced", "Balanced target"],
    [600, "Detailed", "Detailed target"],
    [450, "Balanced", "Custom target"],
  ] as const)(
    "rehydrates target %i with %s selected for the next build",
    async (targetParts, expectedSelection, summaryLabel) => {
      const api = installFakeApi({
        project: projectDetail({
          status: "model_ready",
          sourceImage: READY_SOURCE_IMAGE,
          latestReconstruction: reconstruction("succeeded"),
          latestLegoModel: { artifactId: LEGO_ARTIFACT_ID },
        }),
        legoTargetPartsByArtifact: { [LEGO_ARTIFACT_ID]: targetParts },
      });
      renderApp(`/projects/${PROJECT_ID}`);

      await screen.findByRole("heading", { name: "Build summary" });

      await waitFor(() => expect(complexityRadio(expectedSelection)).toBeChecked());
      expect(legoSummary()).toHaveTextContent(summaryLabel);
      expect(api.posts("/api/v1/conversions")).toHaveLength(0);
    },
  );

  it("defaults the next build to Balanced when saved target metadata is missing", async () => {
    const api = installFakeApi({
      project: projectDetail({
        status: "model_ready",
        sourceImage: READY_SOURCE_IMAGE,
        latestReconstruction: reconstruction("succeeded"),
        latestLegoModel: { artifactId: LEGO_ARTIFACT_ID },
      }),
      legoTargetPartsByArtifact: { [LEGO_ARTIFACT_ID]: null },
    });
    renderApp(`/projects/${PROJECT_ID}`);

    await screen.findByRole("heading", { name: "Build summary" });

    expect(complexityRadio("Balanced")).toBeChecked();
    expect(legoSummary()).toHaveTextContent("Custom target");
    expect(api.posts("/api/v1/conversions")).toHaveLength(0);
  });

  it("keeps the 3D project usable when a saved LEGO model is invalid", async () => {
    const api = installFakeApi({
      project: projectDetail({
        status: "model_ready",
        sourceImage: READY_SOURCE_IMAGE,
        latestReconstruction: reconstruction("succeeded"),
        latestLegoModel: { artifactId: LEGO_ARTIFACT_ID },
      }),
      invalidLegoArtifactId: LEGO_ARTIFACT_ID,
    });
    renderApp(`/projects/${PROJECT_ID}`);

    expect(await screen.findByRole("alert")).toHaveTextContent("We couldn't load the saved LEGO model. You can convert it again.");
    expect(await screen.findByTestId("model-viewer")).toHaveAttribute("data-url", readUrlFor(MODEL_ARTIFACT_ID));
    expect(screen.queryByRole("button", { name: "LEGO model" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Convert to LEGO" }));
    await waitFor(() => expect(api.posts("/api/v1/conversions")).toHaveLength(1));
  });

  it("keeps the last LEGO model visible while a replacement conversion is running", async () => {
    const api = installFakeApi({
      project: projectDetail({
        status: "model_ready",
        sourceImage: READY_SOURCE_IMAGE,
        latestReconstruction: reconstruction("succeeded"),
      }),
      conversionResults: [
        { jobId: JOB_ID, status: "succeeded", outputArtifactId: LEGO_ARTIFACT_ID },
        { jobId: REPLACEMENT_JOB_ID, status: "running" },
      ],
    });
    renderApp(`/projects/${PROJECT_ID}`);

    fireEvent.click(await screen.findByRole("button", { name: "Convert to LEGO" }));
    await screen.findByRole("heading", { name: "Build summary" });
    expect(legoSummary()).toHaveTextContent("1 parts");
    expect(legoSummary()).toHaveTextContent("Balanced target");
    expect(screen.getByRole("heading", { name: "Parts list" })).toBeInTheDocument();
    const firstAttempt = api.posts("/api/v1/conversions")[0];

    fireEvent.click(complexityRadio("Detailed"));
    expect(api.posts("/api/v1/conversions")).toHaveLength(1);
    expect(legoSummary()).toHaveTextContent("1 parts");
    expect(screen.getByText("1 total parts")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Convert again" }));

    expect(await screen.findByText("Creating a Detailed LEGO build. Your current model stays available.")).toBeInTheDocument();
    expect(screen.getByTestId("lego-model-viewer")).toBeInTheDocument();
    expect(legoSummary()).toHaveTextContent("1 parts");
    expect(legoSummary()).toHaveTextContent("Balanced target");
    expect(screen.getByRole("heading", { name: "Parts list" })).toBeInTheDocument();
    expect(conversionRequestBody(api.posts("/api/v1/conversions")[1]?.init).targetParts).toBe(600);
    expect(idempotencyKey(api.posts("/api/v1/conversions")[1]?.init)).not.toBe(idempotencyKey(firstAttempt?.init));
  });

  it("preserves the last LEGO model when a replacement conversion fails", async () => {
    installFakeApi({
      project: projectDetail({
        status: "model_ready",
        sourceImage: READY_SOURCE_IMAGE,
        latestReconstruction: reconstruction("succeeded"),
      }),
      conversionResults: [
        { jobId: JOB_ID, status: "succeeded", outputArtifactId: LEGO_ARTIFACT_ID },
        { jobId: REPLACEMENT_JOB_ID, status: "failed", errorMessage: "The replacement could not be built." },
      ],
    });
    renderApp(`/projects/${PROJECT_ID}`);

    fireEvent.click(await screen.findByRole("button", { name: "Convert to LEGO" }));
    await screen.findByRole("heading", { name: "Build summary" });
    expect(legoSummary()).toHaveTextContent("1 parts");
    fireEvent.click(complexityRadio("Detailed"));
    fireEvent.click(screen.getByRole("button", { name: "Convert again" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The replacement could not be built.");
    expect(screen.getByTestId("lego-model-viewer")).toBeInTheDocument();
    expect(legoSummary()).toHaveTextContent("1 parts");
    expect(legoSummary()).toHaveTextContent("Balanced target");
    expect(complexityRadio("Detailed")).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "View full parts list" }));
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("1 total parts")).toBeInTheDocument();
  });

  it("replaces the LEGO model only after the replacement artifact loads", async () => {
    const api = installFakeApi({
      project: projectDetail({
        status: "model_ready",
        sourceImage: READY_SOURCE_IMAGE,
        latestReconstruction: reconstruction("succeeded"),
      }),
      conversionResults: [
        { jobId: JOB_ID, status: "succeeded", outputArtifactId: LEGO_ARTIFACT_ID },
        { jobId: REPLACEMENT_JOB_ID, status: "succeeded", outputArtifactId: REPLACEMENT_LEGO_ARTIFACT_ID },
      ],
      delayedLegoArtifactId: REPLACEMENT_LEGO_ARTIFACT_ID,
      legoTargetPartsByArtifact: { [REPLACEMENT_LEGO_ARTIFACT_ID]: 100 },
    });
    renderApp(`/projects/${PROJECT_ID}`);

    fireEvent.click(await screen.findByRole("button", { name: "Convert to LEGO" }));
    await screen.findByRole("heading", { name: "Build summary" });
    expect(legoSummary()).toHaveTextContent("1 parts");
    fireEvent.click(complexityRadio("Detailed"));
    fireEvent.click(screen.getByRole("button", { name: "Convert again" }));

    expect(await screen.findByText("Loading LEGO model...")).toBeInTheDocument();
    expect(screen.getByTestId("lego-model-viewer")).toBeInTheDocument();
    expect(legoSummary()).toHaveTextContent("1 parts");
    expect(complexityRadio("Detailed")).toBeChecked();
    expect(conversionRequestBody(api.posts("/api/v1/conversions")[1]?.init).targetParts).toBe(600);

    api.resolveDelayedLegoModel();

    await waitFor(() => expect(legoSummary()).toHaveTextContent("2 parts"));
    expect(legoSummary()).toHaveTextContent("Simple target");
    expect(complexityRadio("Simple")).toBeChecked();
    expect(screen.getByText("2 total parts")).toBeInTheDocument();
    expect(screen.getByText("1 unique part types")).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Completed build view" })).getByRole("button", { name: "LEGO model" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "View full parts list" }));
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("2 total parts")).toBeInTheDocument();
    expect(screen.getByText("1 unique part types")).toBeInTheDocument();
  });

  it("shows the uploaded photo through a short-lived read link", async () => {
    installFakeApi({ project: projectDetail({ status: "photo_ready", sourceImage: READY_SOURCE_IMAGE }) });
    renderApp(`/projects/${PROJECT_ID}`);

    const photo = await screen.findByRole("img", { name: "Photo of Castle" });
    expect(photo).toHaveAttribute("src", readUrlFor(ARTIFACT_ID));
  });

  it("falls back to a message when the photo cannot be loaded", async () => {
    installFakeApi({ project: projectDetail({ status: "photo_ready", sourceImage: READY_SOURCE_IMAGE }) });
    renderApp(`/projects/${PROJECT_ID}`);

    fireEvent.error(await screen.findByRole("img", { name: "Photo of Castle" }));

    expect(screen.getByText("The photo could not be loaded.")).toBeInTheDocument();
  });

  it("shows the 3D model in the viewer and can switch back to the photo", async () => {
    installFakeApi({
      project: projectDetail({
        status: "model_ready",
        sourceImage: READY_SOURCE_IMAGE,
        latestReconstruction: reconstruction("succeeded"),
      }),
    });
    renderApp(`/projects/${PROJECT_ID}`);

    expect(await screen.findByTestId("model-viewer")).toHaveAttribute("data-url", readUrlFor(MODEL_ARTIFACT_ID));
    expect(screen.getByRole("button", { name: "3D model" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "LEGO model" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Photo" }));

    expect(await screen.findByRole("img", { name: "Photo of Castle" })).toBeInTheDocument();
    expect(screen.queryByTestId("model-viewer")).not.toBeInTheDocument();
  });

  it("downloads the 3D model through a fresh download link", async () => {
    installFakeApi({
      project: projectDetail({
        status: "model_ready",
        sourceImage: READY_SOURCE_IMAGE,
        latestReconstruction: reconstruction("succeeded"),
      }),
    });
    renderApp(`/projects/${PROJECT_ID}`);

    fireEvent.click(await screen.findByRole("button", { name: "Download 3D model (.glb)" }));

    await waitFor(() => expect(downloadMock.startBrowserDownload).toHaveBeenCalledWith(
      readUrlFor(MODEL_ARTIFACT_ID, true),
    ));
    const downloadRequest = vi.mocked(fetch).mock.calls.find(([input]) => String(input).includes("download=true"));
    expect(new Headers(downloadRequest?.[1]?.headers).get("Authorization")).toBe("Bearer test-access-token");
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

  it("shows each project's status badge and photo thumbnail on its card", async () => {
    installFakeApi({ project: projectDetail({ status: "generating", sourceImage: READY_SOURCE_IMAGE }) });
    renderApp("/");

    const card = await screen.findByRole("link", { name: /Castle/ });
    expect(within(card).getByText("Generating 3D")).toBeInTheDocument();
    await waitFor(() => expect(card.querySelector("img")).toHaveAttribute("src", readUrlFor(ARTIFACT_ID)));
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
