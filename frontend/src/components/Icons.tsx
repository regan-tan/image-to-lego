import type { ReactNode } from "react";

interface IconProps {
  size?: number;
  className?: string;
}

function StrokeIcon({ size = 18, className, children }: IconProps & { children: ReactNode }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

export function PlusIcon(props: IconProps) {
  return <StrokeIcon {...props}><path d="M12 5v14M5 12h14" /></StrokeIcon>;
}

export function CloseIcon(props: IconProps) {
  return <StrokeIcon {...props}><path d="M18 6 6 18M6 6l12 12" /></StrokeIcon>;
}

export function ArrowLeftIcon(props: IconProps) {
  return <StrokeIcon {...props}><path d="M19 12H5" /><path d="m11 18-6-6 6-6" /></StrokeIcon>;
}

export function HelpIcon(props: IconProps) {
  return (
    <StrokeIcon {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.6 9.2a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.5" />
      <path d="M12 16.8v.4" />
    </StrokeIcon>
  );
}

export function UserIcon(props: IconProps) {
  return <StrokeIcon {...props}><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></StrokeIcon>;
}

export function SignOutIcon(props: IconProps) {
  return (
    <StrokeIcon {...props}>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="m16 17 5-5-5-5" />
      <path d="M21 12H9" />
    </StrokeIcon>
  );
}

export function ImageIcon(props: IconProps) {
  return (
    <StrokeIcon {...props}>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="9" cy="9" r="2" />
      <path d="m21 15-5-5L5 21" />
    </StrokeIcon>
  );
}

export function CheckIcon(props: IconProps) {
  return <StrokeIcon {...props}><path d="M20 6 9 17l-5-5" /></StrokeIcon>;
}

export function AlertIcon(props: IconProps) {
  return (
    <StrokeIcon {...props}>
      <path d="M12 3 22 21H2L12 3z" />
      <path d="M12 10v4" />
      <path d="M12 17.5v.5" />
    </StrokeIcon>
  );
}

export function InfoIcon(props: IconProps) {
  return <StrokeIcon {...props}><circle cx="12" cy="12" r="9" /><path d="M12 11v5" /><path d="M12 7.5v.5" /></StrokeIcon>;
}

export function SpinnerIcon({ className, ...props }: IconProps) {
  return (
    <StrokeIcon {...props} className={["spinner", className].filter(Boolean).join(" ")}>
      <path d="M21 12a9 9 0 1 1-6.2-8.6" />
    </StrokeIcon>
  );
}

export function CubeIcon(props: IconProps) {
  return (
    <StrokeIcon {...props}>
      <path d="M21 8 12 3 3 8l9 5 9-5z" />
      <path d="M3 8v8l9 5 9-5V8" />
      <path d="M12 13v8" />
    </StrokeIcon>
  );
}

export function BrickIcon(props: IconProps) {
  return (
    <StrokeIcon {...props}>
      <rect x="3" y="9" width="18" height="11" rx="1.5" />
      <rect x="6" y="5" width="4" height="4" rx="1" />
      <rect x="14" y="5" width="4" height="4" rx="1" />
    </StrokeIcon>
  );
}

export function RetryIcon(props: IconProps) {
  return <StrokeIcon {...props}><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" /></StrokeIcon>;
}

export function UploadIcon(props: IconProps) {
  return (
    <StrokeIcon {...props}>
      <path d="M12 16V4" />
      <path d="m7 9 5-5 5 5" />
      <path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
    </StrokeIcon>
  );
}

export function LogoMark() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true" focusable="false">
      <rect width="28" height="28" rx="7" fill="#ffcd00" />
      <g fill="none" stroke="#101820" strokeOpacity="0.45" strokeWidth="1.6">
        <circle cx="9.5" cy="9.5" r="3.2" />
        <circle cx="18.5" cy="9.5" r="3.2" />
        <circle cx="9.5" cy="18.5" r="3.2" />
        <circle cx="18.5" cy="18.5" r="3.2" />
      </g>
    </svg>
  );
}
