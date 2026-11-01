import { Dialog } from "./Dialog";
import { BrickIcon, CubeIcon, ImageIcon, InfoIcon, PlusIcon } from "./Icons";

const STEPS = [
  {
    title: "Add a photo",
    label: "Upload",
    description: "Choose a clear JPEG, PNG or WebP photo of one object. Good lighting and a simple background work best.",
    Icon: ImageIcon,
  },
  {
    title: "Generate a 3D model",
    label: "Reconstruct",
    description: "Generate an approximate 3D model with AI, then rotate it to explore the result. Processing can take a few minutes.",
    Icon: CubeIcon,
  },
  {
    title: "Build it in LEGO",
    label: "Convert & build",
    description: "Choose your build complexity and convert the model to LEGO. Explore the result, review your parts list, and follow the build guide.",
    Icon: BrickIcon,
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
      description="From your first photo to your next LEGO creation."
      className="workflow-dialog"
    >
      <ol className="how-it-works">
        {STEPS.map(({ title, label, description, Icon }, index) => (
          <li key={title} className="how-it-works__step">
            <span className={`how-it-works__icon how-it-works__icon--${index + 1}`} aria-hidden="true">
              <Icon size={26} />
            </span>
            <div className="how-it-works__copy">
              <p className="how-it-works__label">0{index + 1} / {label}</p>
              <h3>{title}</h3>
              <p>{description}</p>
            </div>
          </li>
        ))}
      </ol>
      <p className="how-it-works__note"><InfoIcon size={18} />You can leave while a model is processing and return to your project later.</p>
      <div className="dialog__actions">
        <button type="button" className="button button--secondary" onClick={onClose}>Got it</button>
        <button type="button" className="button" onClick={onStartProject}><PlusIcon />New project</button>
      </div>
    </Dialog>
  );
}
