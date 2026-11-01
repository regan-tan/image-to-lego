import { heightInPlates, type LegoModel } from "./schemas/legoModels";
import { legoColorLabel } from "./legoColors";

const PURCHASE_READY_ALGORITHM_VERSION = "surface-grid-v4";

export interface LegoPartGroup {
  brickType: string;
  partId?: string;
  partName?: string;
  shape?: "rectangular" | "slope_33_3x1";
  geometryAsset?: string;
  lengthStuds: number;
  widthStuds: number;
  heightPlates: number;
  color: string;
  colorId?: string;
  colorName?: string;
  colorHex?: string;
  externalIds?: {
    bricklink?: {
      partId: string | null;
      colorId: number | null;
    };
  };
  partColorVerified?: boolean;
  quantity: number;
}

export interface PurchaseReadyPart {
  partId: string;
  colorId: string;
  quantity: number;
  partName: string;
  colorName: string;
  partColorVerified: true;
  partColorVerificationVersion: string;
  externalIds: {
    bricklink: {
      partId: string | null;
      colorId: number | null;
    };
  };
}

export interface UnresolvedPurchasePart {
  part: LegoPartGroup;
  reason:
    | "unsupported_algorithm_version"
    | "missing_part_id"
    | "missing_color_id"
    | "unverified_part_color"
    | "missing_verification_metadata"
    | "missing_verification_version";
}

export interface PurchaseReadyPartsList {
  parts: PurchaseReadyPart[];
  unresolvedParts: UnresolvedPurchasePart[];
}

export type LegoPartsListResult =
  | { valid: true; parts: LegoPartGroup[]; totalPartCount: number; uniquePartTypeCount: number }
  | { valid: false };

export function aggregateLegoPlacements(
  placements: LegoModel["placements"],
): LegoPartGroup[] {
  const groups = new Map<string, LegoPartGroup>();
  for (const placement of placements) {
    const { brickType, partId, partName, shape, geometryAsset, dimensions, color, colorId, colorName, colorHex, externalIds, partColorVerified } = placement;
    const heightPlates = heightInPlates(dimensions);
    const partIdentity = partId ?? [brickType, dimensions.lengthStuds, dimensions.widthStuds, heightPlates].join(":");
    const key = [partIdentity, colorId ?? color].join("|");
    const existing = groups.get(key);
    if (existing) {
      existing.quantity += 1;
      existing.partColorVerified = existing.partColorVerified && partColorVerified;
      if (existing.externalIds?.bricklink?.partId !== externalIds?.bricklink?.partId) {
        existing.externalIds = undefined;
      }
      if (existing.externalIds?.bricklink?.colorId !== externalIds?.bricklink?.colorId) {
        existing.externalIds = undefined;
      }
      continue;
    }
    groups.set(key, { brickType, partId, partName, shape, geometryAsset, lengthStuds: dimensions.lengthStuds, widthStuds: dimensions.widthStuds, heightPlates, color, colorId, colorName, colorHex, externalIds, partColorVerified, quantity: 1 });
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
  const rows = [["Part ID", "Part Name", "Color", "Color ID", "Verified part/color", "Quantity"], ...parts.map((part) => [part.partId ?? "", partLabel(part), part.colorName ?? colorLabel(part.color), part.colorId ?? "", partColorVerificationLabel(part), String(part.quantity)])];
  return rows.map((row) => row.map(escapeCsvValue).join(",")).join("\r\n");
}

export function createPurchaseReadyPartsList(
  parts: LegoPartGroup[],
  algorithmVersion: string | undefined,
  partColorVerificationVersion: string | undefined,
): PurchaseReadyPartsList {
  const purchaseReadyParts: PurchaseReadyPart[] = [];
  const unresolvedParts: UnresolvedPurchasePart[] = [];

  for (const part of parts) {
    const partId = part.partId;
    const colorId = part.colorId;
    const verificationVersion = partColorVerificationVersion;
    const reason = purchaseReadinessIssue(part, algorithmVersion, partColorVerificationVersion);
    if (reason || !partId || !colorId || !verificationVersion) {
      unresolvedParts.push({ part, reason: reason ?? "missing_verification_version" });
      continue;
    }
    purchaseReadyParts.push({
      partId,
      colorId,
      quantity: part.quantity,
      partName: partLabel(part),
      colorName: part.colorName ?? colorLabel(part.color),
      partColorVerified: true,
      partColorVerificationVersion: verificationVersion,
      externalIds: {
        bricklink: {
          partId: part.externalIds?.bricklink?.partId ?? null,
          colorId: part.externalIds?.bricklink?.colorId ?? null,
        },
      },
    });
  }

  purchaseReadyParts.sort((left, right) => {
    const partDifference = left.partId.localeCompare(right.partId);
    return partDifference !== 0 ? partDifference : left.colorId.localeCompare(right.colorId);
  });
  return { parts: purchaseReadyParts, unresolvedParts };
}

export function serializePurchaseReadyPartsCsv(parts: PurchaseReadyPart[]): string {
  const rows = [
    [
      "Part ID",
      "BrickLink Part ID",
      "Color ID",
      "BrickLink Color ID",
      "Quantity",
      "Part Name",
      "Color Name",
      "Verified part/color",
      "Verification version",
    ],
    ...parts.map((part) => [
      part.partId,
      part.externalIds.bricklink.partId ?? "",
      part.colorId,
      part.externalIds.bricklink.colorId?.toString() ?? "",
      String(part.quantity),
      part.partName,
      part.colorName,
      "Verified",
      part.partColorVerificationVersion,
    ]),
  ];
  return rows.map((row) => row.map(escapeCsvValue).join(",")).join("\r\n");
}

export function partColorVerificationLabel(part: LegoPartGroup): string {
  if (part.partColorVerified === true) return "Verified";
  if (part.partColorVerified === false) return "Unsupported";
  return "Unresolved";
}

export function purchaseReadinessReasonLabel(reason: UnresolvedPurchasePart["reason"]): string {
  switch (reason) {
    case "unsupported_algorithm_version":
      return `Purchase-ready export requires a ${PURCHASE_READY_ALGORITHM_VERSION} model artifact.`;
    case "missing_part_id":
      return "No catalog part ID was recorded.";
    case "missing_color_id":
      return "No catalog color ID was recorded.";
    case "unverified_part_color":
      return "The generated geometry or part/color pair is not catalog verified.";
    case "missing_verification_metadata":
      return "This legacy model has no catalog verification metadata.";
    case "missing_verification_version":
      return "The catalog verification version is not recorded.";
  }
}

function escapeCsvValue(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
}

function purchaseReadinessIssue(
  part: LegoPartGroup,
  algorithmVersion: string | undefined,
  partColorVerificationVersion: string | undefined,
): UnresolvedPurchasePart["reason"] | null {
  if (algorithmVersion !== PURCHASE_READY_ALGORITHM_VERSION) return "unsupported_algorithm_version";
  if (!part.partId) return "missing_part_id";
  if (!part.colorId) return "missing_color_id";
  if (part.partColorVerified === false || part.quantity <= 0) return "unverified_part_color";
  if (part.partColorVerified !== true) return "missing_verification_metadata";
  if (!partColorVerificationVersion) return "missing_verification_version";
  return null;
}
