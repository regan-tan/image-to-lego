import { Dialog } from "./Dialog";
import { PlusIcon } from "./Icons";

type BrickColor = "yellow" | "blue" | "red";

interface Step {
  title: string;
  description: string;
  brickColor: BrickColor;
  isComingSoon: boolean;
}

const STEPS: Step[] = [
  {
    title: "Add a photo",
    description: "One object on a plain background, in good light. JPEG, PNG or WebP up to 10 MB.",
    brickColor: "yellow",
    isComingSoon: false,
  },
  {
    title: "Generate a 3D model",
    description: "AI rebuilds your object in 3D. It takes a few minutes, and you can leave while it works.",
    brickColor: "blue",
    isComingSoon: false,
  },
  {
    title: "Build it in LEGO",
    description: "Get the brick model, a parts list and step-by-step building instructions.",
    brickColor: "red",
    isComingSoon: true,
  },
];

interface HowItWorksDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onStartProject: () => void;
}

export function HowItWorksDialog({ isOpen, onClose, onStartProject }: HowItWorksDialogProps) {
  return (
    <Dialog
      isOpen={isOpen}
      onClose={onClose}
      title="How it works"
      description="Three steps from a photo to bricks."
      size="large"
    >
      <ol className="how-it-works">
        {STEPS.map((step, index) => (
          <li key={step.title} className="how-it-works__step">
            <div className="how-it-works__step-top">
              <StepBrick number={index + 1} color={step.brickColor} />
              {step.isComingSoon ? <span className="badge badge--neutral">Coming soon</span> : null}
            </div>
            <div>
              <h3>{step.title}</h3>
              <p>{step.description}</p>
            </div>
          </li>
        ))}
      </ol>
      <div className="dialog__actions">
        <button type="button" className="button button--secondary" onClick={onClose}>
          Got it
        </button>
        <button type="button" className="button" onClick={onStartProject}>
          <PlusIcon />
          New project
        </button>
      </div>
    </Dialog>
  );
}

function StepBrick({ number, color }: { number: number; color: BrickColor }) {
  return (
    <svg
      className={`step-brick step-brick--${color}`}
      width="64"
      height="50"
      viewBox="0 0 64 50"
      aria-hidden="true"
      focusable="false"
    >
      <rect className="step-brick__body" x="12" y="2" width="14" height="9" rx="2.5" />
      <rect className="step-brick__body" x="38" y="2" width="14" height="9" rx="2.5" />
      <rect className="step-brick__body" x="2" y="9" width="60" height="39" rx="6" />
      <rect className="step-brick__edge" x="2" y="40" width="60" height="8" rx="4" />
      <text className="step-brick__label" x="32" y="32" textAnchor="middle">{number}</text>
    </svg>
  );
}
