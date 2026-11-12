import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { getArtifactReadUrl, getJob, getLegoModel, startConversion, startReconstruction } from "../api/client";
import { startBrowserDownload } from "../browserDownload";
import { conversionPollInterval } from "../conversionPolling";
import { projectQueryKey, projectsQueryKey } from "../hooks/useProjects";
import { useArtifactReadUrl } from "../hooks/useArtifactReadUrl";
import {
  BUILD_COMPLEXITY_PRESETS,
  CONVERSION_MODES,
  DEFAULT_CONVERSION_ALGORITHM,
  MAX_CONVERSION_PARTS,
  buildComplexityLabel,
  targetPartsForBuildComplexity,
  type BuildComplexity,
  type ConversionAlgorithmVersion,
} from "../legoBuildComplexity";
import type { LegoPartsListResult } from "../legoPartsList";
import type { Conversion, ConversionStatus } from "../schemas/conversions";
import { heightInPlates, type LegoModel } from "../schemas/legoModels";
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
  buildComplexity: BuildComplexity;
  onBuildComplexityChange: (complexity: BuildComplexity) => void;
  onViewFullPartsList: () => void;
  onOpenBuildGuide: () => void;
  isVisible: boolean;
}

interface GenerationRequest {
  sourceArtifactId: string;
  idempotencyKey: string;
}

interface ConversionAttempt extends GenerationRequest {
  targetParts: number;
  maxParts?: number;
  algorithmVersion: ConversionAlgorithmVersion;
  upAxis: "y";
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
  buildComplexity,
  onBuildComplexityChange,
  onViewFullPartsList,
  onOpenBuildGuide,
  isVisible,
}: ProjectStatusPanelProps) {
  const queryClient = useQueryClient();
  const [isReplacingPhoto, setIsReplacingPhoto] = useState(false);
  const generationAttempt = useRef<{ scope: string; key: string } | null>(null);
  const conversionAttempt = useRef<ConversionAttempt | null>(null);
  const [conversionJob, setConversionJob] = useState<Conversion | null>(null);
  const [algorithmVersion, setAlgorithmVersion] = useState<ConversionAlgorithmVersion>(
    DEFAULT_CONVERSION_ALGORITHM,
  );
  const [maxParts, setMaxParts] = useState(targetPartsForBuildComplexity(buildComplexity));
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
    mutationFn: ({ sourceArtifactId, targetParts, maxParts, algorithmVersion, upAxis, idempotencyKey }: ConversionAttempt) => startConversion(
      accessToken,
      {
        projectId: project.id,
        sourceArtifactId,
        targetParts,
        ...(maxParts === undefined ? {} : { maxParts }),
        algorithmVersion,
        upAxis,
      },
      idempotencyKey,
    ),
    onSuccess: setConversionJob,
  });

  const legoResult = activeConversion?.status === "succeeded" && activeConversion.outputArtifactId ? (
    <LegoResult
      accessToken={accessToken}
      userId={userId}
      artifactId={activeConversion.outputArtifactId}
      onLoaded={onLegoModelLoaded}
      isVisible={isVisible}
    />
  ) : null;

  if (!isVisible) {
    return <>{legoResult}</>;
  }

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
    const targetParts = targetPartsForBuildComplexity(buildComplexity);
    const selectedMode = CONVERSION_MODES.find((mode) => mode.algorithmVersion === algorithmVersion);
    if (!selectedMode) return;
    const requestedMaxParts = selectedMode.requiresMaxParts ? maxParts : undefined;
    const requestedAttempt = {
      sourceArtifactId,
      targetParts,
      ...(requestedMaxParts === undefined ? {} : { maxParts: requestedMaxParts }),
      algorithmVersion,
      upAxis: "y" as const,
    };
    const isRetryingSameRequest = conversion.isError
      && conversionAttempt.current !== null
      && sameConversionRequest(conversionAttempt.current, requestedAttempt);
    if (!isRetryingSameRequest && (
      activeConversion?.status === "failed"
      || activeConversion?.status === "canceled"
      || activeConversion?.status === "succeeded"
    )) {
      conversionAttempt.current = null;
      setConversionJob(null);
    }
    if (!isRetryingSameRequest) {
      conversionAttempt.current = {
        ...requestedAttempt,
        idempotencyKey: crypto.randomUUID(),
      };
    }
    const attempt = conversionAttempt.current;
    if (attempt) conversion.mutate(attempt);
  }

  function handleBuildComplexityChange(nextBuildComplexity: BuildComplexity) {
    onBuildComplexityChange(nextBuildComplexity);
    if (algorithmVersion !== "surface-grid-v4") {
      setMaxParts(targetPartsForBuildComplexity(nextBuildComplexity));
    }
  }

  function handleAlgorithmChange(nextAlgorithmVersion: ConversionAlgorithmVersion) {
    setAlgorithmVersion(nextAlgorithmVersion);
    if (nextAlgorithmVersion !== "surface-grid-v4") {
      setMaxParts(targetPartsForBuildComplexity(buildComplexity));
    }
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
    <>
      {legoResult}
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
            title={legoModel ? "Your LEGO build" : "Your 3D model is ready"}
            text={legoModel
              ? "Explore your model, review the parts, or follow your build guide."
              : "Choose a build complexity, then convert your model to LEGO."}
          />
          {legoModel ? <h3 className="visually-hidden">Your LEGO model is ready</h3> : null}
          {legoModel ? <LegoMetrics model={legoModel} partsList={partsList} /> : null}
          {legoModel ? (
            <button type="button" className="button button--yellow side-panel__open-guide" onClick={onOpenBuildGuide}>
              Open build guide
            </button>
          ) : null}
          <BuildComplexitySelector
            value={buildComplexity}
            onChange={handleBuildComplexityChange}
            disabled={conversionIsRunning || isRehydratingLegoModel}
            helpId={complexityHelpId}
            compact={legoModel !== null}
          />
          <ConversionModeSelector
            algorithmVersion={algorithmVersion}
            maxParts={maxParts}
            onAlgorithmChange={handleAlgorithmChange}
            onMaxPartsChange={setMaxParts}
            disabled={conversionIsRunning || isRehydratingLegoModel}
          />
          <div className="side-panel__actions">
            <button
              type="button"
              className={`button button--large${legoModel ? " button--secondary" : ""}`}
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
                className={legoModel ? "model-download-action" : "button button--secondary"}
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
          {legoModel ? <ProjectInspectorSummary project={project} accessToken={accessToken} userId={userId} /> : null}
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

      {project.sourceImage && !legoModel ? <PhotoDetails sourceImage={project.sourceImage} /> : null}
      </aside>
    </>
  );
}

function LegoResult({
  accessToken,
  userId,
  artifactId,
  onLoaded,
  isVisible,
}: {
  accessToken: string;
  userId: string;
  artifactId: string;
  onLoaded: (model: LegoModel) => void;
  isVisible: boolean;
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
  if (!isVisible) return null;
  if (legoModel.isPending) return <p className="status status--pending" role="status">Loading LEGO model...</p>;
  if (legoModel.isError || !legoModel.data) {
    return <p className="form-error" role="alert">The LEGO model could not be loaded safely. Please try again.</p>;
  }
  return null;
}

function LegoMetrics({
  model,
  partsList,
}: {
  model: LegoModel;
  partsList: LegoPartsListResult | null;
}) {
  const { dimensions } = model;
  const complexityLabel = buildComplexityLabel(model.metadata.targetParts) ?? "Custom";
  const buildability = model.metadata.buildability;
  return (
    <section className="lego-result" aria-labelledby="lego-result-title">
      <h2 id="lego-result-title" className="side-panel__title visually-hidden">Build summary</h2>
      <p className="visually-hidden">{model.partCount} parts · {dimensions.widthStuds} × {dimensions.depthStuds} studs · {heightInPlates(dimensions)} plates tall · {complexityLabel} target</p>
      <div className="lego-metrics" aria-label="Model metrics">
        <div><strong>{model.partCount}</strong><span>Total parts</span></div>
        <div><strong>{partsList?.valid ? partsList.uniquePartTypeCount : "—"}</strong><span>Part types</span></div>
        <div><strong>{heightInPlates(dimensions)}</strong><span>Plates tall</span></div>
      </div>
      <p className="side-panel__hint">
        {algorithmLabel(model.metadata.algorithmVersion)} · {complexityLabel} detail target
        {model.metadata.maxParts ? ` · maximum ${model.metadata.maxParts} parts` : ""}
      </p>
      {buildability ? (
        <p className="side-panel__hint">
          Stud-connected components: {buildability.connectedComponents} · Unsupported placements: {buildability.unsupportedPlacements}
        </p>
      ) : null}
      {model.metadata.shapeAware ? (
        <p className="side-panel__hint">
          Shape-aware collision pairs: {model.metadata.shapeAware.physicalCollisionPairs}
          {model.metadata.shapeAware.fallbackReason ? ` · ${model.metadata.shapeAware.fallbackReason}` : ""}
        </p>
      ) : null}
      {model.metadata.connectivityAware ? (
        <p className="side-panel__hint">
          Connectivity optimization {model.metadata.connectivityAware.accepted ? "was applied" : "fell back to V6-equivalent output"}.
        </p>
      ) : null}
    </section>
  );
}

function algorithmLabel(algorithmVersion: string): string {
  return CONVERSION_MODES.find((mode) => mode.algorithmVersion === algorithmVersion)?.label
    ?? algorithmVersion;
}

function ProjectInspectorSummary({
  project,
  accessToken,
  userId,
}: {
  project: ProjectDetail;
  accessToken: string;
  userId: string;
}) {
  const sourceImage = project.sourceImage;
  const sourceImageUrl = useArtifactReadUrl(accessToken, userId, sourceImage?.artifactId ?? null);
  const sourceType = sourceImage ? (IMAGE_TYPE_LABELS[sourceImage.mimeType] ?? sourceImage.mimeType) : "No source";

  return (
    <section className="project-summary" aria-label="Project summary">
      {sourceImageUrl.data?.url ? (
        <img src={sourceImageUrl.data.url} alt="Source image" />
      ) : (
        <span className="project-summary__placeholder"><BrickIcon size={25} /></span>
      )}
      <dl>
        <div><dt>Uploaded</dt><dd>{sourceImage ? uploadDateFormat.format(new Date(sourceImage.createdAt)) : "—"}</dd></div>
        <div><dt>Source</dt><dd>{sourceImage ? `${sourceType} · ${fileSizeFormat.format(sourceImage.sizeBytes / 1_000_000)}` : sourceType}</dd></div>
      </dl>
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
      <p id={helpId}>{compact ? "Changes apply when you convert again. Final part count may vary." : "Choose how detailed you want the LEGO build to be. Final part count may vary."}</p>
    </fieldset>
  );
}

function ConversionModeSelector({
  algorithmVersion,
  maxParts,
  onAlgorithmChange,
  onMaxPartsChange,
  disabled,
}: {
  algorithmVersion: ConversionAlgorithmVersion;
  maxParts: number;
  onAlgorithmChange: (algorithmVersion: ConversionAlgorithmVersion) => void;
  onMaxPartsChange: (maxParts: number) => void;
  disabled: boolean;
}) {
  const selectedMode = CONVERSION_MODES.find((mode) => mode.algorithmVersion === algorithmVersion);
  if (!selectedMode) return null;

  return (
    <fieldset className="complexity-selector" disabled={disabled}>
      <legend>Conversion mode</legend>
      <div className="complexity-selector__options">
        {CONVERSION_MODES.map((mode) => (
          <label key={mode.algorithmVersion} className="complexity-option">
            <input
              type="radio"
              name="conversion-mode"
              value={mode.algorithmVersion}
              checked={algorithmVersion === mode.algorithmVersion}
              onChange={() => onAlgorithmChange(mode.algorithmVersion)}
            />
            <span>
              <strong>{mode.label}</strong>
              <small>{mode.description}</small>
            </span>
          </label>
        ))}
      </div>
      {selectedMode.requiresMaxParts ? (
        <div className="form-field">
          <label htmlFor="conversion-max-parts">Maximum parts</label>
          <input
            id="conversion-max-parts"
            type="number"
            min={1}
            max={MAX_CONVERSION_PARTS}
            value={maxParts}
            onChange={(event) => onMaxPartsChange(Number(event.target.value))}
          />
          <small>This is enforced. Your detail target is still a preference, not an exact piece count.</small>
        </div>
      ) : (
        <p>Build complexity is a preferred detail target. Classic mode does not enforce a maximum-piece limit.</p>
      )}
    </fieldset>
  );
}

function sameConversionRequest(
  attempt: ConversionAttempt,
  request: Omit<ConversionAttempt, "idempotencyKey">,
): boolean {
  return attempt.sourceArtifactId === request.sourceArtifactId
    && attempt.targetParts === request.targetParts
    && attempt.maxParts === request.maxParts
    && attempt.algorithmVersion === request.algorithmVersion
    && attempt.upAxis === request.upAxis;
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
