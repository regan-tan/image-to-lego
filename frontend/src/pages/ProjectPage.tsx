import { Link, useParams } from "react-router-dom";
import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getLegoModel } from "../api/client";
import { useAppLayout } from "../components/appLayoutContext";
import { BrickProgress } from "../components/BrickProgress";
import { BuildGuideWorkspace } from "../components/BuildGuideWorkspace";
import { DeleteProjectDialog } from "../components/DeleteProjectDialog";
import { TrashIcon } from "../components/Icons";
import { ProjectPreview } from "../components/ProjectPreview";
import type { PreviewView } from "../components/ProjectPreview";
import { ProjectStatusPanel } from "../components/ProjectStatusPanel";
import { PartsListWorkspace } from "../components/PartsListWorkspace";
import { StatusBadge } from "../components/StatusBadge";
import { isNotFound, useProject } from "../hooks/useProjects";
import {
  DEFAULT_BUILD_COMPLEXITY,
  buildComplexityForTargetParts,
  type BuildComplexity,
} from "../legoBuildComplexity";
import { deriveLegoBuildSteps } from "../legoBuildInstructions";
import { createLegoPartsList } from "../legoPartsList";
import type { ConversionStatus } from "../schemas/conversions";
import type { LegoModel } from "../schemas/legoModels";

type ResultView = "model" | "parts" | "guide";

export function ProjectPage() {
  const { projectId = "" } = useParams();

  return <ProjectPageContent key={projectId} projectId={projectId} />;
}

function ProjectPageContent({ projectId }: { projectId: string }) {
  const { session } = useAppLayout();
  const project = useProject(session.access_token, session.user.id, projectId);
  const [conversionStatus, setConversionStatus] = useState<ConversionStatus | null>(null);
  const [legoModel, setLegoModel] = useState<LegoModel | null>(null);
  const [previewView, setPreviewView] = useState<PreviewView | null>(null);
  const [resultView, setResultView] = useState<ResultView>("model");
  const [buildStepIndex, setBuildStepIndex] = useState(0);
  const [selectedBuildComplexity, setSelectedBuildComplexity] = useState<BuildComplexity | null>(null);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const persistedLegoArtifactId = project.data?.latestLegoModel?.artifactId ?? null;
  const persistedLegoModel = useQuery({
    queryKey: ["lego-model", session.user.id, persistedLegoArtifactId],
    queryFn: ({ signal }) => getLegoModel(session.access_token, persistedLegoArtifactId ?? "", signal),
    enabled: persistedLegoArtifactId !== null,
    retry: false,
  });
  const handleLegoModelLoaded = useCallback((model: LegoModel) => {
    setLegoModel(model);
    setPreviewView("lego");
    setBuildStepIndex(0);
    setSelectedBuildComplexity(
      buildComplexityForTargetParts(model.metadata.targetParts) ?? DEFAULT_BUILD_COMPLEXITY,
    );
  }, []);
  const currentLegoModel = legoModel ?? persistedLegoModel.data ?? null;
  const buildComplexity = selectedBuildComplexity
    ?? (currentLegoModel
      ? buildComplexityForTargetParts(currentLegoModel.metadata.targetParts)
      : undefined)
    ?? DEFAULT_BUILD_COMPLEXITY;
  const currentPreviewView = previewView ?? (currentLegoModel ? "lego" : "model");
  const partsList = currentLegoModel ? createLegoPartsList(currentLegoModel) : null;
  const buildSteps = useMemo(
    () => currentLegoModel ? deriveLegoBuildSteps(currentLegoModel) : [],
    [currentLegoModel],
  );

  return (
    <div className={`page__container studio-page${currentLegoModel ? " page__container--completed" : ""}${currentLegoModel && resultView === "model" ? " studio-page--overview" : ""}${resultView === "guide" ? " studio-page--guide" : ""}${resultView === "parts" ? " studio-page--parts" : ""}`}>
      <nav className="project-breadcrumb" aria-label="Breadcrumb">
        <ol>
          <li><Link to="/workspace" className="back-link">All projects</Link></li>
          {project.data ? (
            <li>
              <span aria-hidden="true">/</span>
              <span aria-current="page">{project.data.name}</span>
            </li>
          ) : null}
        </ol>
      </nav>

      {project.isPending ? <p className="status status--pending" role="status">Loading project…</p> : null}

      {!project.data && isNotFound(project.error) ? (
        <div className="page-heading">
          <div>
            <h1>Project not found</h1>
            <p className="page-heading__meta">It may have been deleted, or the link may be wrong.</p>
          </div>
        </div>
      ) : null}

      {!project.data && project.isError && !isNotFound(project.error) ? (
        <div className="form-error" role="alert">
          <p>We could not load this project.</p>
          <button className="text-button" type="button" onClick={() => void project.refetch()}>
            Try again
          </button>
        </div>
      ) : null}

      {project.data ? (
        <>
          <div className="page-heading studio-page__heading">
            <div className="page-heading__title-row">
              <div><h1>{project.data.name}</h1><p className="page-heading__meta">From your photo to your next LEGO creation.</p></div>
              <StatusBadge
                status={project.data.status}
                conversionStatus={conversionStatus}
                legoModelReady={currentLegoModel !== null}
              />
            </div>
            <button
              type="button"
              className="button button--secondary button--compact"
              onClick={() => setIsDeleteDialogOpen(true)}
            >
              <TrashIcon size={16} />
              Delete project
            </button>
          </div>
          <DeleteProjectDialog
            isOpen={isDeleteDialogOpen}
            onClose={() => setIsDeleteDialogOpen(false)}
            accessToken={session.access_token}
            userId={session.user.id}
            projectId={project.data.id}
            projectName={project.data.name}
          />
          {currentLegoModel ? null : (
            <BrickProgress
              status={project.data.status}
              conversionStatus={conversionStatus}
            />
          )}
          {currentLegoModel ? (
            <div className="result-view-toggle project-tabs" role="group" aria-label="Completed build view">
              <button type="button" aria-pressed={resultView === "model"} onClick={() => setResultView("model")}>Overview</button>
              <button type="button" aria-pressed={resultView === "parts"} onClick={() => setResultView("parts")}>Parts list</button>
              <button type="button" aria-pressed={resultView === "guide"} onClick={() => setResultView("guide")}>Build guide</button>
            </div>
          ) : null}
          <div className={`project-layout${currentLegoModel && resultView === "model" ? " project-layout--completed" : ""}${currentLegoModel && resultView !== "model" ? " project-layout--hidden" : ""}`}>
            {currentLegoModel === null || resultView === "model" ? (
              <ProjectPreview
                key={`preview-${project.data.id}`}
                project={project.data}
                accessToken={session.access_token}
                userId={session.user.id}
                legoModel={currentLegoModel}
                view={currentPreviewView}
                onViewChange={setPreviewView}
              />
            ) : null}
            {/* Keyed by project so panel state (replacing a photo, retry keys) never leaks between projects. */}
            <ProjectStatusPanel
              key={`status-${project.data.id}`}
              project={project.data}
              accessToken={session.access_token}
              userId={session.user.id}
              onConversionStatusChange={setConversionStatus}
              legoModel={currentLegoModel}
              partsList={partsList}
              onLegoModelLoaded={handleLegoModelLoaded}
              isRehydratingLegoModel={persistedLegoArtifactId !== null && persistedLegoModel.isPending}
              hasPersistedLegoModelError={persistedLegoModel.isError && legoModel === null}
              buildComplexity={buildComplexity}
              onBuildComplexityChange={setSelectedBuildComplexity}
              onViewFullPartsList={() => setResultView("parts")}
              onOpenBuildGuide={() => setResultView("guide")}
              isVisible={currentLegoModel === null || resultView === "model"}
            />
          </div>
          {currentLegoModel && resultView === "parts" && partsList ? (
            <PartsListWorkspace
              partsList={partsList}
              algorithmVersion={currentLegoModel.metadata.algorithmVersion}
              partColorVerificationVersion={currentLegoModel.metadata.partColorVerificationVersion}
            />
          ) : null}
          {currentLegoModel && resultView === "guide" ? (
            <BuildGuideWorkspace
              model={currentLegoModel}
              steps={buildSteps}
              currentStepIndex={buildStepIndex}
              onStepChange={setBuildStepIndex}
            />
          ) : null}
        </>
      ) : null}
    </div>
  );
}
