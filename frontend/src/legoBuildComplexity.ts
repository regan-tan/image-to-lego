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
