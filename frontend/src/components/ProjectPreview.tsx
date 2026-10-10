import { lazy, type ReactNode, Suspense, useRef, useState } from "react";

import { useArtifactReadUrl } from "../hooks/useArtifactReadUrl";
import type { ProjectDetail } from "../schemas/projects";
import type { LegoModel } from "../schemas/legoModels";
import { ErrorBoundary } from "./ErrorBoundary";
import { CubeIcon, ImageIcon, MaximizeIcon, RetryIcon, SpinnerIcon } from "./Icons";
import LegoModelViewer from "./LegoModelViewer";

const ModelViewer = lazy(() => import("./ModelViewer"));

interface ProjectPreviewProps {
  project: ProjectDetail;
  accessToken: string;
  userId: string;
  legoModel: LegoModel | null;
  view: PreviewView;
  onViewChange: (view: PreviewView) => void;
}

export type PreviewView = "model" | "photo" | "lego";

/** The large preview area of the project page: the 3D model once ready, otherwise the photo. */
export function ProjectPreview({
  project,
  accessToken,
  userId,
  legoModel,
  view,
  onViewChange,
}: ProjectPreviewProps) {
  const modelArtifactId = project.status === "model_ready"
    ? project.latestReconstruction?.outputArtifactId ?? null
    : null;
  const showModel = modelArtifactId !== null && view === "model";

  return (
    <div className="project-preview baseplate">
      {modelArtifactId !== null || legoModel !== null ? (
        <div className="segmented-control" role="group" aria-label="Preview">
          {project.sourceImage ? (
            <button type="button" aria-pressed={view === "photo"} onClick={() => onViewChange("photo")}>
              Photo
            </button>
          ) : null}
          {modelArtifactId !== null ? (
            <button type="button" aria-pressed={view === "model"} onClick={() => onViewChange("model")}>
              3D model
            </button>
          ) : null}
          {legoModel ? (
            <button type="button" aria-label="LEGO model preview" aria-pressed={view === "lego"} onClick={() => onViewChange("lego")}>
              LEGO model
            </button>
          ) : null}
        </div>
      ) : null}

      {view === "lego" && legoModel ? (
        <LegoModelViewer model={legoModel} />
      ) : showModel ? (
        <ModelPreview artifactId={modelArtifactId} accessToken={accessToken} userId={userId} />
      ) : (
        <PhotoPreview
          artifactId={project.sourceImage?.artifactId ?? null}
          projectName={project.name}
          accessToken={accessToken}
          userId={userId}
        />
      )}

      {project.status === "generating" ? (
        <span className="project-preview__overlay">
          <SpinnerIcon size={16} />
          Generating 3D model from this photo
        </span>
      ) : null}
    </div>
  );
}

interface PhotoPreviewProps {
  artifactId: string | null;
  projectName: string;
  accessToken: string;
  userId: string;
}

function PhotoPreview({ artifactId, projectName, accessToken, userId }: PhotoPreviewProps) {
  const readUrl = useArtifactReadUrl(accessToken, userId, artifactId);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const url = readUrl.data?.url;

  if (artifactId === null) {
    return <PreviewPlaceholder icon={<ImageIcon size={44} />} caption="No photo yet" />;
  }
  if (!url || readUrl.isError || failedUrl === url) {
    return (
      <PreviewPlaceholder
        icon={readUrl.isPending ? <SpinnerIcon size={32} /> : <ImageIcon size={44} />}
        caption={readUrl.isPending ? "Loading photo…" : "The photo could not be loaded."}
      />
    );
  }
  return (
    <img
      className="project-preview__photo"
      src={url}
      alt={`Photo of ${projectName}`}
      onError={() => setFailedUrl(url)}
    />
  );
}

interface ModelPreviewProps {
  artifactId: string;
  accessToken: string;
  userId: string;
}

function ModelPreview({ artifactId, accessToken, userId }: ModelPreviewProps) {
  const readUrl = useArtifactReadUrl(accessToken, userId, artifactId);
  const containerRef = useRef<HTMLDivElement>(null);
  // Changing the key remounts the viewer, which puts the camera back to its starting position.
  const [viewerKey, setViewerKey] = useState(0);
  const url = readUrl.data?.url ?? null;

  if (url === null) {
    return (
      <PreviewPlaceholder
        icon={readUrl.isError ? <CubeIcon size={56} /> : <SpinnerIcon size={32} />}
        caption={readUrl.isError ? "The 3D model could not be loaded." : "Loading 3D model…"}
      />
    );
  }

  const viewerFailed = (
    <PreviewPlaceholder
      icon={<CubeIcon size={56} />}
      caption="The 3D model could not be displayed. You can still download it."
    />
  );

  return (
    <div className="model-stage" ref={containerRef}>
      <ErrorBoundary key={viewerKey} fallback={viewerFailed}>
        <Suspense fallback={<PreviewPlaceholder icon={<SpinnerIcon size={32} />} caption="Loading 3D model…" />}>
          <ModelViewer url={url} />
        </Suspense>
      </ErrorBoundary>
      <div className="model-stage__toolbar">
        <span className="model-stage__hint">Drag to rotate · Scroll to zoom</span>
        <div className="model-stage__actions">
          <button
            type="button"
            className="icon-button icon-button--overlay"
            aria-label="Reset view"
            onClick={() => setViewerKey((current) => current + 1)}
          >
            <RetryIcon />
          </button>
          {document.fullscreenEnabled ? (
            <button
              type="button"
              className="icon-button icon-button--overlay"
              aria-label="Full screen"
              onClick={() => void containerRef.current?.requestFullscreen()}
            >
              <MaximizeIcon />
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function PreviewPlaceholder({ icon, caption }: { icon: ReactNode; caption: string }) {
  return (
    <div className="project-preview__placeholder">
      <span className="project-preview__icon">{icon}</span>
      <span className="project-preview__caption">{caption}</span>
    </div>
  );
}
