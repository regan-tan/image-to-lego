const LEGO_COLORS: Record<string, string> = {
  black: "#05131D",
  white: "#F4F4F4",
  light_bluish_gray: "#A0A5A9",
  dark_bluish_gray: "#6C6E68",
  red: "#C91A09",
  dark_red: "#720E0F",
  orange: "#FE8A18",
  yellow: "#F2CD37",
  tan: "#E4CD9E",
  reddish_brown: "#582A12",
  dark_brown: "#352100",
  green: "#237841",
  dark_green: "#184632",
  lime: "#BBE90B",
  blue: "#0055BF",
  dark_blue: "#0A3463",
};

const DEFAULT_LEGO_COLOR = LEGO_COLORS.light_bluish_gray;

export function legoColorHex(color: string): string {
  return LEGO_COLORS[color] ?? DEFAULT_LEGO_COLOR;
}

export function legoColorLabel(color: string): string {
  return color.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
