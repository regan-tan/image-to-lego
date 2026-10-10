import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { getArtifactReadUrl, getJob, getLegoModel, startConversion, startReconstruction } from "../api/client";
import { startBrowserDownload } from "../browserDownload";
import { conversionPollInterval } from "../conversionPolling";
import { projectQueryKey, projectsQueryKey } from "../hooks/useProjects";
import {
  BUILD_COMPLEXITY_PRESETS,
  DEFAULT_BUILD_COMPLEXITY,
  buildComplexityForTargetParts,
  buildComplexityLabel,
  targetPartsForBuildComplexity,
  type BuildComplexity,
} from "../legoBuildComplexity";
import type { LegoPartsListResult } from "../legoPartsList";
import type { Conversion, ConversionStatus } from "../schemas/conversions";
import type { LegoModel } from "../schemas/legoModels";
import type { ProjectDetail } from "../schemas/projects";
import {
  checkImageFileBasics,
  type UploadStage,
  uploadSourceImage,
  uploadStageMessage,
  validateSourceImage,
} from "../sourceImageUpload";
import {
  AlertIcon,
  BrickIcon,
  CheckIcon,
  CubeIcon,
  DownloadIcon,
  InfoIcon,
  RetryIcon,
  SpinnerIcon,
} from "./Icons";
import { PhotoPicker } from "./PhotoPicker";
import { PartsListSummary } from "./PartsListWorkspace";

interface ProjectStatusPanelProps {
  project: ProjectDetail;
  accessToken: string;
  userId: string;
  onConversionStatusChange: (status: ConversionStatus | null) => void;
  legoModel: LegoModel | null;
  partsList: LegoPartsListResult | null;
  onLegoModelLoaded: (model: LegoModel) => void;
  isRehydratingLegoModel: boolean;
  hasPersistedLegoModelError: boolean;
  onViewFullPartsList: () => void;
  buildComplexity: BuildComplexity;
  onBuildComplexityChange: (complexity: BuildComplexity) => void;
}

interface GenerationRequest {
  sourceArtifactId: string;
  idempotencyKey: string;
}

interface ConversionAttempt extends GenerationRequest {
  targetParts: number;
}

/** The project page's side panel: explains the current state and offers the one next action. */
export function ProjectStatusPanel({
  project,
  accessToken,
  userId,
  onConversionStatusChange,
  legoModel,
  partsList,
  onLegoModelLoaded,
  isRehydratingLegoModel,
  hasPersistedLegoModelError,
  onViewFullPartsList,
  buildComplexity,
  onBuildComplexityChange,
}: ProjectStatusPanelProps) {
  const queryClient = useQueryClient();
  const [isReplacingPhoto, setIsReplacingPhoto] = useState(false);
  const generationAttempt = useRef<{ scope: string; key: string } | null>(null);
  const conversionAttempt = useRef<ConversionAttempt | null>(null);
  const [conversionJob, setConversionJob] = useState<Conversion | null>(null);
  const complexityHelpId = useId();

  async function refreshProject() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: projectQueryKey(userId, project.id) }),
      queryClient.invalidateQueries({ queryKey: projectsQueryKey(userId) }),
    ]);
  }

  const generation = useMutation({
    mutationFn: ({ sourceArtifactId, idempotencyKey }: GenerationRequest) => startReconstruction(
      accessToken,
      { projectId: project.id, sourceArtifactId },
      idempotencyKey,
    ),
    onSuccess: refreshProject,
  });

  // Fetched at click time: download links are short-lived, so they are never kept around.
  const modelDownload = useMutation({
    mutationFn: (artifactId: string) => getArtifactReadUrl(accessToken, artifactId, { download: true }),
    onSuccess: (readUrl) => startBrowserDownload(readUrl.url),
  });

  const conversionStatus = useQuery({
    queryKey: ["conversion-job", userId, conversionJob?.jobId],
    queryFn: ({ signal }) => getJob(accessToken, conversionJob?.jobId ?? "", signal),
    enabled: conversionJob !== null,
    refetchInterval: (query) => conversionPollInterval(query.state.data?.status ?? conversionJob?.status),
  });
  const activeConversion = conversionStatus.data ?? conversionJob;
  useEffect(() => {
    onConversionStatusChange(activeConversion?.status ?? null);
  }, [activeConversion?.status, onConversionStatusChange]);
  const conversion = useMutation({
    mutationFn: ({ sourceArtifactId, targetParts, idempotencyKey }: ConversionAttempt) => startConversion(
      accessToken,
      { projectId: project.id, sourceArtifactId, targetParts, upAxis: "y" },
      idempotencyKey,
    ),
    onSuccess: setConversionJob,
  });

  function handleGenerate() {
    const sourceImage = project.sourceImage;
    if (!sourceImage || generation.isPending) {
      return;
    }
    // Paid work is only started by this explicit click. Every request for the same photo and
    // previous job reuses one idempotency key, so repeated clicks or retries cannot start a second
    // paid generation; a new photo or a finished job starts a new attempt with a new key.
    const scope = `${sourceImage.artifactId}:${project.latestReconstruction?.jobId ?? "none"}`;
    if (generationAttempt.current?.scope !== scope) {
      generationAttempt.current = { scope, key: crypto.randomUUID() };
    }
    generation.mutate({
      sourceArtifactId: sourceImage.artifactId,
      idempotencyKey: generationAttempt.current.key,
    });
  }

  function handleConvert() {
    const sourceArtifactId = project.latestReconstruction?.outputArtifactId;
    if (!sourceArtifactId || conversion.isPending) return;
    const isRetryingSameRequest = conversion.isError
      && conversionAttempt.current?.sourceArtifactId === sourceArtifactId;
    if (!isRetryingSameRequest && (
      activeConversion?.status === "failed"
      || activeConversion?.status === "canceled"
      || activeConversion?.status === "succeeded"
    )) {
      conversionAttempt.current = null;
      setConversionJob(null);
    }
    if (conversionAttempt.current?.sourceArtifactId !== sourceArtifactId) {
      conversionAttempt.current = {
        sourceArtifactId,
        targetParts: targetPartsForBuildComplexity(buildComplexity),
        idempotencyKey: crypto.randomUUID(),
      };
    } else if (isRetryingSameRequest) {
      onBuildComplexityChange(
        buildComplexityForTargetParts(conversionAttempt.current.targetParts) ?? DEFAULT_BUILD_COMPLEXITY,
      );
    }
    conversion.mutate(conversionAttempt.current);
  }

  if (project.status === "needs_photo" || isReplacingPhoto) {
    return (
      <aside className="side-panel" aria-labelledby="panel-title">
        <PanelIntro
          title={isReplacingPhoto ? "Use a different photo" : "Add a photo"}
          text={
            isReplacingPhoto
              ? "We’ll use the new photo for your next 3D model."
              : "Upload a photo of the object you want to turn into LEGO."
          }
        />
        <PhotoUploadForm
          accessToken={accessToken}
          projectId={project.id}
          onUploaded={async () => {
            await refreshProject();
            setIsReplacingPhoto(false);
          }}
          onCancel={isReplacingPhoto ? () => setIsReplacingPhoto(false) : undefined}
        />
      </aside>
    );
  }

  const modelArtifactId = project.latestReconstruction?.outputArtifactId ?? null;
  const generationStartError = generation.isError ? (
    <p className="form-error" role="alert">We could not start generating. Please try again.</p>
  ) : null;
  const conversionIsRunning = conversion.isPending
    || activeConversion?.status === "queued"
    || activeConversion?.status === "running";
  const activeBuildLabel = conversion.variables
    ? buildComplexityLabel(conversion.variables.targetParts)
    : undefined;

  return (
    <aside className={`side-panel${legoModel ? " side-panel--completed" : ""}`} aria-labelledby="panel-title">
      {project.status === "photo_ready" ? (
        <>
          <PanelIntro
            title="Ready to make a 3D model"
            text="We’ll turn this photo into a 3D model. It takes a few minutes, and you can leave this page while it works."
          />
          <div className="side-panel__actions">
            <button
              type="button"
              className="button button--large"
              onClick={handleGenerate}
              disabled={generation.isPending}
            >
              <CubeIcon />
              {generation.isPending ? "Starting…" : "Generate 3D model"}
            </button>
            {generationStartError}
            <button
              type="button"
              className="button button--secondary"
              onClick={() => setIsReplacingPhoto(true)}
              disabled={generation.isPending}
            >
              Replace photo
            </button>
          </div>
        </>
      ) : null}

      {project.status === "generating" ? (
        <>
          <PanelIntro title="Building your 3D model" text="This can take a few minutes." />
          <div className="progress-bar" aria-hidden="true">
            <div className="progress-bar__fill" />
          </div>
          <ol className="generation-steps" role="status">
            {project.latestReconstruction?.status === "queued" ? (
              <li className="generation-steps__item generation-steps__item--current">
                <SpinnerIcon size={16} />
                In the queue
              </li>
            ) : (
              <>
                <li className="generation-steps__item">
                  <CheckIcon size={16} />
                  In the queue
                </li>
                <li className="generation-steps__item generation-steps__item--current">
                  <SpinnerIcon size={16} />
                  Generating the 3D model
                </li>
              </>
            )}
          </ol>
          <p className="callout">
            <InfoIcon />
            <span>You can close this page. We’ll keep working, and your model will be here when you come back.</span>
          </p>
          <Link to="/" className="button button--secondary">Back to projects</Link>
        </>
      ) : null}

      {project.status === "model_ready" ? (
        <>
          <PanelIntro
            title={legoModel ? "Your LEGO model is ready" : "Your 3D model is ready"}
            text={legoModel
              ? "Explore the LEGO model, review its parts list, or convert it again."
              : "Next, you’ll be able to turn it into a LEGO build with a parts list and building steps."}
          />
          {legoModel ? <LegoSummary model={legoModel} /> : null}
          <BuildComplexitySelector
            value={buildComplexity}
            onChange={onBuildComplexityChange}
            disabled={conversionIsRunning || isRehydratingLegoModel}
            helpId={complexityHelpId}
            compact={legoModel !== null}
          />
          <div className="side-panel__actions">
            <button
              type="button"
              className="button button--large"
              onClick={handleConvert}
              disabled={!modelArtifactId || isRehydratingLegoModel || conversionIsRunning}
            >
              <BrickIcon />
              {conversion.isPending || activeConversion?.status === "queued" ? "Starting conversion..." : null}
              {activeConversion?.status === "running" ? "Converting to LEGO..." : null}
              {!conversion.isPending && activeConversion?.status !== "queued" && activeConversion?.status !== "running"
                ? legoModel ? "Convert again" : "Convert to LEGO"
                : null}
            </button>
            {modelArtifactId ? (
              <button
                type="button"
                className="button button--secondary"
                onClick={() => modelDownload.mutate(modelArtifactId)}
                disabled={modelDownload.isPending}
              >
                <DownloadIcon />
                {modelDownload.isPending ? "Preparing download…" : "Download 3D model (.glb)"}
              </button>
            ) : null}
            {modelDownload.isError ? (
              <p className="form-error" role="alert">The download could not be started. Please try again.</p>
            ) : null}
          </div>
          {conversion.isError ? <p className="form-error" role="alert">We could not start the conversion. Please try again.</p> : null}
          {isRehydratingLegoModel ? (
            <p className="status status--pending" role="status">Loading saved LEGO model...</p>
          ) : null}
          {hasPersistedLegoModelError ? (
            <p className="form-error" role="alert">We couldn't load the saved LEGO model. You can convert it again.</p>
          ) : null}
          {conversionIsRunning ? (
            <p className="status status--pending" role="status">
              <SpinnerIcon size={16} />
              {legoModel
                ? `Creating a${activeBuildLabel ? ` ${activeBuildLabel}` : " replacement"} LEGO build. Your current model stays available.`
                : `Creating a${activeBuildLabel ? ` ${activeBuildLabel}` : ""} LEGO build...`}
            </p>
          ) : null}
          {activeConversion?.status === "failed" || activeConversion?.status === "canceled" ? (
            <div className="alert" role="alert">
              <p>{activeConversion.errorMessage ?? "The LEGO conversion did not finish. Try again when you are ready."}</p>
              <button type="button" className="button button--secondary" onClick={handleConvert}>Try conversion again</button>
            </div>
          ) : null}
          {activeConversion?.status === "succeeded" && activeConversion.outputArtifactId ? (
            <LegoResult
              accessToken={accessToken}
              userId={userId}
              artifactId={activeConversion.outputArtifactId}
              onLoaded={onLegoModelLoaded}
            />
          ) : null}
          {legoModel && partsList ? (
            <PartsListSummary partsList={partsList} onViewFullPartsList={onViewFullPartsList} />
          ) : null}
        </>
      ) : null}

      {project.status === "failed" ? (
        <>
          <div className="alert" role="alert">
            <div className="alert__title-row">
              <span className="alert__icon"><AlertIcon size={16} /></span>
              <h2 id="panel-title" className="side-panel__title">We couldn’t make a 3D model</h2>
            </div>
            <p>{project.latestReconstruction?.errorMessage ?? "Something went wrong while generating."}</p>
          </div>
          <div className="side-panel__actions">
            <button
              type="button"
              className="button button--large"
              onClick={handleGenerate}
              disabled={generation.isPending}
            >
              <RetryIcon />
              {generation.isPending ? "Starting…" : "Try again"}
            </button>
            {generationStartError}
            <button
              type="button"
              className="button button--secondary"
              onClick={() => setIsReplacingPhoto(true)}
              disabled={generation.isPending}
            >
              Use a different photo
            </button>
          </div>
          <p className="side-panel__hint">
            Still failing? A photo of one object on a plain background with even light works best.
          </p>
        </>
      ) : null}

      {project.sourceImage ? <PhotoDetails sourceImage={project.sourceImage} /> : null}
    </aside>
  );
}

function LegoResult({
  accessToken,
  userId,
  artifactId,
  onLoaded,
}: {
  accessToken: string;
  userId: string;
  artifactId: string;
  onLoaded: (model: LegoModel) => void;
}) {
  const legoModel = useQuery({
    queryKey: ["lego-model", userId, artifactId],
    queryFn: ({ signal }) => getLegoModel(accessToken, artifactId, signal),
  });
  useEffect(() => {
    if (legoModel.data) {
      onLoaded(legoModel.data);
    }
  }, [legoModel.data, onLoaded]);
  if (legoModel.isPending) return <p className="status status--pending" role="status">Loading LEGO model...</p>;
  if (legoModel.isError || !legoModel.data) {
    return <p className="form-error" role="alert">The LEGO model could not be loaded safely. Please try again.</p>;
  }
  return null;
}

function LegoSummary({ model }: { model: LegoModel }) {
  const { dimensions } = model;
  const complexityLabel = buildComplexityLabel(model.metadata.targetParts) ?? "Custom";
  return (
    <section className="lego-result" aria-labelledby="lego-result-title">
      <h2 id="lego-result-title" className="side-panel__title">Build summary</h2>
      <p className="side-panel__hint">{model.partCount} parts · {dimensions.widthStuds} × {dimensions.depthStuds} studs · {dimensions.heightBricks} bricks tall · {complexityLabel} target</p>
    </section>
  );
}

function BuildComplexitySelector({
  value,
  onChange,
  disabled,
  helpId,
  compact,
}: {
  value: BuildComplexity;
  onChange: (value: BuildComplexity) => void;
  disabled: boolean;
  helpId: string;
  compact: boolean;
}) {
  return (
    <fieldset
      className={`complexity-selector${compact ? " complexity-selector--compact" : ""}`}
      aria-describedby={helpId}
      disabled={disabled}
    >
      <legend>Build complexity</legend>
      <div className="complexity-selector__options">
        {BUILD_COMPLEXITY_PRESETS.map((preset) => (
          <label key={preset.id} className="complexity-option">
            <input
              type="radio"
              name="build-complexity"
              value={preset.id}
              checked={value === preset.id}
              onChange={() => onChange(preset.id)}
            />
            <span>
              <strong>{preset.label}</strong>
              <small>{preset.description}</small>
            </span>
          </label>
        ))}
      </div>
      <p id={helpId}>{compact ? "Final part count may vary." : "Choose how detailed you want the LEGO build to be. Final part count may vary."}</p>
    </fieldset>
  );
}

function PanelIntro({ title, text }: { title: string; text: string }) {
  return (
    <div className="side-panel__intro">
      <h2 id="panel-title" className="side-panel__title">{title}</h2>
      <p>{text}</p>
    </div>
  );
}

interface PhotoUploadFormProps {
  accessToken: string;
  projectId: string;
  onUploaded: () => Promise<void>;
  onCancel?: () => void;
}

function PhotoUploadForm({ accessToken, projectId, onUploaded, onCancel }: PhotoUploadFormProps) {
  const inputId = useId();
  const [photo, setPhoto] = useState<File | null>(null);
  const [stage, setStage] = useState<UploadStage | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!photo || stage) {
      return;
    }

    setErrorMessage(null);
    setStage("validating");
    const validationProblem = await validateSourceImage(photo);
    if (validationProblem) {
      setStage(null);
      setErrorMessage(validationProblem);
      return;
    }
    try {
      await uploadSourceImage({ accessToken, projectId, file: photo, onStage: setStage });
      await onUploaded();
    } catch {
      setErrorMessage("The photo could not be uploaded. Please try again.");
    } finally {
      setStage(null);
    }
  }

  return (
    <form className="side-panel__form" onSubmit={(event) => void handleSubmit(event)}>
      <PhotoPicker
        inputId={inputId}
        file={photo}
        onSelect={(selected) => {
          const problem = checkImageFileBasics(selected);
          setErrorMessage(problem);
          setPhoto(problem ? null : selected);
        }}
        disabled={stage !== null}
      />
      {errorMessage ? <p className="form-error" role="alert">{errorMessage}</p> : null}
      {stage ? <p className="status status--pending" role="status">{uploadStageMessage(stage)}</p> : null}
      <div className="side-panel__actions">
        <button type="submit" className="button button--large" disabled={!photo || stage !== null}>
          Upload photo
        </button>
        {onCancel ? (
          <button type="button" className="button button--secondary" onClick={onCancel} disabled={stage !== null}>
            Cancel
          </button>
        ) : null}
      </div>
    </form>
  );
}

const IMAGE_TYPE_LABELS: Record<string, string> = {
  "image/jpeg": "JPEG",
  "image/png": "PNG",
  "image/webp": "WebP",
};

const fileSizeFormat = new Intl.NumberFormat(undefined, {
  style: "unit",
  unit: "megabyte",
  maximumFractionDigits: 1,
});

const uploadDateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function PhotoDetails({ sourceImage }: { sourceImage: NonNullable<ProjectDetail["sourceImage"]> }) {
  return (
    <dl className="detail-list">
      <div>
        <dt>Photo</dt>
        <dd>{IMAGE_TYPE_LABELS[sourceImage.mimeType] ?? sourceImage.mimeType}</dd>
      </div>
      <div>
        <dt>Size</dt>
        <dd>{fileSizeFormat.format(sourceImage.sizeBytes / 1_000_000)}</dd>
      </div>
      <div>
        <dt>Uploaded</dt>
        <dd>{uploadDateFormat.format(new Date(sourceImage.createdAt))}</dd>
      </div>
    </dl>
  );
}
