import { placementBuildStagesForStep, type LegoBuildStep } from "../legoBuildInstructions";
import { colorLabel, partLabel } from "../legoPartsList";
import { legoColorHex } from "../legoColors";
import type { LegoModel } from "../schemas/legoModels";
import { LegoPartThumbnail } from "./LegoPartThumbnail";
import LegoModelViewer from "./LegoModelViewer";

interface BuildGuideWorkspaceProps {
  model: LegoModel;
  steps: LegoBuildStep[];
  currentStepIndex: number;
  onStepChange: (stepIndex: number) => void;
}

export function BuildGuideWorkspace({
  model,
  steps,
  currentStepIndex,
  onStepChange,
}: BuildGuideWorkspaceProps) {
  if (steps.length === 0) {
    return (
      <section className="build-guide" aria-labelledby="build-guide-title">
        <h2 id="build-guide-title">Build guide</h2>
        <p>No build steps are available for this model.</p>
      </section>
    );
  }

  const selectedStepIndex = Math.max(0, Math.min(currentStepIndex, steps.length - 1));
  const step = steps[selectedStepIndex];
  if (!step) return null;

  const placementStages = placementBuildStagesForStep(model, steps, selectedStepIndex);
  const isFirstStep = selectedStepIndex === 0;
  const isLastStep = selectedStepIndex === steps.length - 1;

  return (
    <section className="build-guide" aria-labelledby="build-guide-title">
      <div className="build-guide__workspace">
        <div className="build-guide__viewer baseplate" data-testid="build-guide-viewer">
          <div className="build-guide__viewer-header">
            <h2>Assembly preview</h2>
            <p>Drag to rotate · Scroll to zoom</p>
          </div>
          <LegoModelViewer model={model} placementStages={placementStages} />
          <span className="model-stage__hint build-guide__viewer-hint">Selected step in context</span>
        </div>

        <aside className="build-guide__step-panel" aria-label="Current build step">
          <div className="build-guide__guide-header" aria-live="polite" aria-atomic="true">
            <p className="eyebrow">Build guide / draft</p>
            <h2 id="build-guide-title">Build guide</h2>
            <div className="build-guide__step-status">
              <h3>Step {step.stepNumber}</h3>
              <p>Add {step.partCount} {step.partCount === 1 ? "brick" : "bricks"}</p>
            </div>
            <div className="build-guide__progress-summary">
              <p>Step {step.stepNumber} of {steps.length}</p>
              <p>{step.partCount} added this step · {step.cumulativePartCount} of {step.totalModelPartCount} parts built</p>
            </div>
            <progress
              className="build-guide__progress"
              aria-label={`Build progress: step ${step.stepNumber} of ${steps.length}`}
              value={step.stepNumber}
              max={steps.length}
            />
            <ol className="build-guide__step-list" aria-label="Build steps">
              {steps.map((buildStep, index) => (
                <li key={buildStep.stepNumber}>
                  <button
                    type="button"
                    className={index === selectedStepIndex ? "is-selected" : ""}
                    aria-current={index === selectedStepIndex ? "step" : undefined}
                    onClick={() => onStepChange(index)}
                  >
                    {String(buildStep.stepNumber).padStart(2, "0")}
                  </button>
                </li>
              ))}
            </ol>
          </div>

          <div className="build-guide__parts">
            <h4>
              Parts needed this step
              <span aria-hidden="true">{step.parts.length} {step.parts.length === 1 ? "type" : "types"}</span>
            </h4>
            <ul>
              {step.parts.map((part) => (
                <li key={`${part.partId ?? part.brickType}-${part.colorId ?? part.color}`}>
                  <LegoPartThumbnail part={part} />
                  <span className="build-guide__part-description">
                    <strong>{part.partId ? `${part.partId} — ${partLabel(part)}` : partLabel(part)}</strong>
                    <span>
                      <span
                        className="color-swatch"
                        style={{ backgroundColor: part.colorHex ?? legoColorHex(part.color) }}
                        aria-hidden="true"
                      />
                      {part.colorName ?? colorLabel(part.color)}
                    </span>
                  </span>
                  <strong className="build-guide__part-quantity">×{part.quantity}</strong>
                </li>
              ))}
            </ul>
          </div>

          <div className="build-guide__footer">
            <div className="build-guide__navigation">
              <button
                type="button"
                className="button button--secondary"
                disabled={isFirstStep}
                onClick={() => onStepChange(selectedStepIndex - 1)}
              >
                Previous
              </button>
              <button
                type="button"
                className="button"
                disabled={isLastStep}
                onClick={() => onStepChange(selectedStepIndex + 1)}
              >
                {isLastStep ? "Build complete" : "Next"}
              </button>
            </div>
            <p>Draft instructions · Physical assembly is not validated.</p>
          </div>
        </aside>
      </div>
    </section>
  );
}
