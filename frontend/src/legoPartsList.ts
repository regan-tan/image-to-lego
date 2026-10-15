import { heightInPlates, type LegoModel } from "./schemas/legoModels";
import { legoColorLabel } from "./legoColors";

export interface LegoPartGroup {
  brickType: string;
  partId?: string;
  partName?: string;
  lengthStuds: number;
  widthStuds: number;
  heightPlates: number;
  color: string;
  colorId?: string;
  colorName?: string;
  colorHex?: string;
  quantity: number;
}

export type LegoPartsListResult =
  | { valid: true; parts: LegoPartGroup[]; totalPartCount: number; uniquePartTypeCount: number }
  | { valid: false };

export function aggregateLegoPlacements(
  placements: LegoModel["placements"],
): LegoPartGroup[] {
  const groups = new Map<string, LegoPartGroup>();
  for (const placement of placements) {
    const { brickType, partId, partName, dimensions, color, colorId, colorName, colorHex } = placement;
    const heightPlates = heightInPlates(dimensions);
    const partIdentity = partId ?? [brickType, dimensions.lengthStuds, dimensions.widthStuds, heightPlates].join(":");
    const key = [partIdentity, colorId ?? color].join("|");
    const existing = groups.get(key);
    if (existing) {
      existing.quantity += 1;
      continue;
    }
    groups.set(key, { brickType, partId, partName, lengthStuds: dimensions.lengthStuds, widthStuds: dimensions.widthStuds, heightPlates, color, colorId, colorName, colorHex, quantity: 1 });
  }
  return [...groups.values()].sort(compareParts);
}

export function createLegoPartsList(model: LegoModel): LegoPartsListResult {
  const parts = aggregateLegoPlacements(model.placements);
  const totalPartCount = parts.reduce((total, part) => total + part.quantity, 0);
  if (totalPartCount !== model.partCount) return { valid: false };
  return { valid: true, parts, totalPartCount, uniquePartTypeCount: parts.length };
}

function compareParts(left: LegoPartGroup, right: LegoPartGroup): number {
  const footprintDifference = right.lengthStuds * right.widthStuds - left.lengthStuds * left.widthStuds;
  if (footprintDifference !== 0) return footprintDifference;
  if (left.lengthStuds !== right.lengthStuds) return right.lengthStuds - left.lengthStuds;
  if (left.widthStuds !== right.widthStuds) return right.widthStuds - left.widthStuds;
  const brickTypeDifference = left.brickType.localeCompare(right.brickType);
  return brickTypeDifference !== 0 ? brickTypeDifference : left.color.localeCompare(right.color);
}

export function partLabel(part: LegoPartGroup): string {
  if (part.partName) return part.partName;
  const partKind = part.brickType.startsWith("plate_") ? "plate" : "brick";
  return `${part.lengthStuds}×${part.widthStuds} ${partKind}`;
}

export function colorLabel(color: string): string {
  return legoColorLabel(color);
}

export function serializePartsListCsv(parts: LegoPartGroup[]): string {
  const rows = [["Part ID", "Part Name", "Color", "Color ID", "Quantity"], ...parts.map((part) => [part.partId ?? "", partLabel(part), part.colorName ?? colorLabel(part.color), part.colorId ?? "", String(part.quantity)])];
  return rows.map((row) => row.map(escapeCsvValue).join(",")).join("\r\n");
}

function escapeCsvValue(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
}
