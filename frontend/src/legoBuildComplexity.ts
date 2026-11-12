export type BuildComplexity = "simple" | "balanced" | "detailed";

export interface BuildComplexityPreset {
  id: BuildComplexity;
  label: string;
  description: string;
  targetParts: number;
}

export const BUILD_COMPLEXITY_PRESETS: readonly BuildComplexityPreset[] = [
  { id: "simple", label: "Simple", description: "Fewer parts", targetParts: 100 },
  { id: "balanced", label: "Balanced", description: "Balanced detail", targetParts: 300 },
  { id: "detailed", label: "Detailed", description: "More detail", targetParts: 600 },
];

export const DEFAULT_BUILD_COMPLEXITY: BuildComplexity = "balanced";
export const MAX_CONVERSION_PARTS = 10_000;

export type ConversionAlgorithmVersion =
  | "surface-grid-v4"
  | "surface-grid-v6-shape-aware"
  | "surface-grid-v7-connectivity-aware";

export interface ConversionMode {
  algorithmVersion: ConversionAlgorithmVersion;
  label: string;
  description: string;
  requiresMaxParts: boolean;
}

export const CONVERSION_MODES: readonly ConversionMode[] = [
  {
    algorithmVersion: "surface-grid-v4",
    label: "Classic — V4",
    description: "Existing conversion behavior. Detail is a preference, not a maximum-piece guarantee.",
    requiresMaxParts: false,
  },
  {
    algorithmVersion: "surface-grid-v6-shape-aware",
    label: "Reliable — V6",
    description: "Shape-aware conversion with a verified maximum-piece limit and conservative checks.",
    requiresMaxParts: true,
  },
  {
    algorithmVersion: "surface-grid-v7-connectivity-aware",
    label: "Experimental connectivity — V7",
    description: "May improve stud-connected components, takes longer, and can return a V6-equivalent result.",
    requiresMaxParts: true,
  },
];

export const DEFAULT_CONVERSION_ALGORITHM: ConversionAlgorithmVersion = "surface-grid-v4";

export function targetPartsForBuildComplexity(complexity: BuildComplexity): number {
  const preset = BUILD_COMPLEXITY_PRESETS.find((candidate) => candidate.id === complexity);
  if (!preset) {
    throw new Error(`Unknown build complexity: ${complexity}`);
  }
  return preset.targetParts;
}

export function buildComplexityForTargetParts(targetParts: number | undefined): BuildComplexity | undefined {
  return BUILD_COMPLEXITY_PRESETS.find((preset) => preset.targetParts === targetParts)?.id;
}

export function buildComplexityLabel(targetParts: number | undefined): string | undefined {
  return BUILD_COMPLEXITY_PRESETS.find((preset) => preset.targetParts === targetParts)?.label;
}
