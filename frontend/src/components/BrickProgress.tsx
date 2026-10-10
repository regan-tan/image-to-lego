import type { ProjectStatus } from "../schemas/projects";
import type { ConversionStatus } from "../schemas/conversions";
import { AlertIcon, CheckIcon, SpinnerIcon } from "./Icons";

type StepState = "done" | "current" | "failed" | "upcoming";

const STEP_LABELS = ["Photo", "3D model", "LEGO build"] as const;

const STEP_STATES: Record<ProjectStatus, [StepState, StepState, StepState]> = {
  needs_photo: ["current", "upcoming", "upcoming"],
  photo_ready: ["done", "current", "upcoming"],
  generating: ["done", "current", "upcoming"],
  model_ready: ["done", "done", "current"],
  failed: ["done", "failed", "upcoming"],
};

const SCREEN_READER_STATE: Record<StepState, string> = {
  done: "completed",
  current: "current step",
  failed: "failed",
  upcoming: "not started",
};

/** The three project steps drawn as LEGO bricks that fill in as each step completes. */
export function BrickProgress({
  status,
  conversionStatus,
}: {
  status: ProjectStatus;
  conversionStatus: ConversionStatus | null;
}) {
  const states = conversionStatus === "queued" || conversionStatus === "running"
    ? ["done", "done", "current"] as const
    : STEP_STATES[status];
  return (
    <ol className="brick-progress" aria-label="Progress">
      {STEP_LABELS.map((label, index) => {
        const state = states[index];
        return (
          <li
            key={label}
            className={`brick-step brick-step--${state}`}
            aria-current={state === "current" || state === "failed" ? "step" : undefined}
          >
            <span className="brick-step__stud brick-step__stud--left" aria-hidden="true" />
            <span className="brick-step__stud brick-step__stud--right" aria-hidden="true" />
            {state === "done" ? <CheckIcon size={15} /> : null}
            {state === "failed" ? <AlertIcon size={15} /> : null}
            {state === "current" && status === "generating" ? <SpinnerIcon size={15} /> : null}
            {label}
            <span className="visually-hidden">, {SCREEN_READER_STATE[state]}</span>
          </li>
        );
      })}
    </ol>
  );
}
