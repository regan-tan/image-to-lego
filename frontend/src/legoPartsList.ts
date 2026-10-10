import type { LegoModel } from "./schemas/legoModels";

export interface LegoPartGroup {
  brickType: string;
  lengthStuds: number;
  widthStuds: number;
  heightBricks: number;
  color: string;
  quantity: number;
}

export type LegoPartsListResult =
  | { valid: true; parts: LegoPartGroup[]; totalPartCount: number; uniquePartTypeCount: number }
  | { valid: false };

export function createLegoPartsList(model: LegoModel): LegoPartsListResult {
  const groups = new Map<string, LegoPartGroup>();
  for (const placement of model.placements) {
    const { brickType, dimensions, color } = placement;
    const key = [brickType, dimensions.lengthStuds, dimensions.widthStuds, dimensions.heightBricks, color].join("|");
    const existing = groups.get(key);
    if (existing) {
      existing.quantity += 1;
      continue;
    }
    groups.set(key, { brickType, lengthStuds: dimensions.lengthStuds, widthStuds: dimensions.widthStuds, heightBricks: dimensions.heightBricks, color, quantity: 1 });
  }
  const parts = [...groups.values()].sort(compareParts);
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
  return `${part.lengthStuds}×${part.widthStuds} brick`;
}

export function colorLabel(color: string): string {
  return color.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function serializePartsListCsv(parts: LegoPartGroup[]): string {
  const rows = [["Part", "Length Studs", "Width Studs", "Height Bricks", "Color", "Quantity"], ...parts.map((part) => [partLabel(part), String(part.lengthStuds), String(part.widthStuds), String(part.heightBricks), colorLabel(part.color), String(part.quantity)])];
  return rows.map((row) => row.map(escapeCsvValue).join(",")).join("\r\n");
}

function escapeCsvValue(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
}
