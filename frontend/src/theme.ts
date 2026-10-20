// Glass + neumorphic palettes. Token NAMES are unchanged; new tokens are marked "new".
// Rule of thumb: t.blue is the accent as TEXT/ICON colour (always ≥ 4.5:1); t.accent is the accent as a FILL;
// t.primary is a fill that carries white text. Status colours stay 6-digit hex so callers can append alpha ("18", "cc").
export const LIGHT = {
  // Backgrounds
  bg:        "#E0E5EC",
  nav:       "#E6EAF0",
  card:      "#E9EDF3",   // solid surface (side panels, menus, modals, toasts); <Card> uses t.glass instead
  cardHover: "#F1F4F8",
  input:     "#E0E5EC",
  badge:     "#DDE3EB",

  // Text
  text:      "#1F2937",
  textSub:   "#3F4856",
  textMuted: "#566070",
  textInv:   "#ffffff",

  // Brand / accents
  blue:      "#065F46",   // accent as text
  blueDim:   "#D1F2E4",
  blueBorder:"#8ED6B9",
  green:     "#065F46",
  greenDim:  "#D1F2E4",
  greenBorder:"#8ED6B9",
  amber:     "#92400E",
  amberDim:  "#FDEBC8",
  amberBorder:"#E0B777",
  red:       "#BE123C",
  redDim:    "#FDE0E7",
  redBorder: "#EE9DB2",
  purple:    "#5B21B6",
  purpleDim: "#E9E1FA",
  medium:    "#1D4ED8",   // new: "medium" severity / contained status (was t.blue)
  mediumDim: "#DCE7FD",
  mediumBorder:"#9DB8F2",
  accent:    "#10B981",   // new: accent as fill
  primary:   "#047857",   // new: primary button / user bubble, white text
  primaryHover:"#065F46",
  brandGrad: "linear-gradient(135deg, #047857, #065F46)",
  focus:     "#065F46",

  // Structure
  border:    "rgba(163,177,198,0.6)",   // hairlines and dividers
  shadow:    "0 8px 24px rgba(163,177,198,0.45), inset 0 1px 0 rgba(255,255,255,0.6)",
  shadowMd:  "0 12px 32px rgba(163,177,198,0.6), inset 0 1px 0 rgba(255,255,255,0.7)",
  shadowLg:  "0 24px 56px rgba(120,134,158,0.5), inset 0 1px 0 rgba(255,255,255,0.7)",
  radius:    "12px",
  radiusSm:  "8px",
  radiusLg:  "16px",

  // Glass + neumorphism (new)
  glass:       "rgba(255,255,255,0.42)",
  glassBorder: "rgba(255,255,255,0.78)",
  blur:        "blur(20px)",
  raised:      "8px 8px 16px #A3B1C6, -8px -8px 16px rgba(255,255,255,0.9)",
  raisedSm:    "4px 4px 8px #A3B1C6, -4px -4px 8px rgba(255,255,255,0.9)",
  inset:       "inset 8px 8px 16px #A3B1C6, inset -8px -8px 16px rgba(255,255,255,0.9)",
  btn:         "#E0E5EC",
  btnBorder:   "rgba(255,255,255,0.6)",
  ambient:     "radial-gradient(900px 600px at 10% -10%, rgba(16,185,129,0.20), transparent 60%), radial-gradient(800px 560px at 95% 5%, rgba(59,130,246,0.16), transparent 60%), radial-gradient(900px 700px at 65% 115%, rgba(16,185,129,0.12), transparent 60%)",
};

export const DARK: typeof LIGHT = {
  bg:        "#0B0F19",
  nav:       "#0F1422",
  card:      "#141A2A",
  cardHover: "#1A2135",
  input:     "#080B13",
  badge:     "#1A2033",

  text:      "#E8ECF6",
  textSub:   "#A9B2C8",
  textMuted: "#8F99B3",
  textInv:   "#ffffff",

  // accent as text: #818CF8 (6.4:1). The spec indigo #6366F1 is only 4.3:1 on the canvas, so it is used for fills (t.accent) only.
  blue:      "#818CF8",
  blueDim:   "#1C1F45",
  blueBorder:"#3F4290",

  green:     "#34D399",
  greenDim:  "#0F2A24",
  greenBorder:"#1B6B52",
  amber:     "#FBBF24",
  amberDim:  "#2B2111",
  amberBorder:"#6B5217",
  red:       "#FB7185",
  redDim:    "#2B1320",
  redBorder: "#6B2437",
  purple:    "#A78BFA",
  purpleDim: "#221B3F",
  medium:    "#60A5FA",
  mediumDim: "#12233D",
  mediumBorder:"#2A5594",
  accent:    "#6366F1",
  primary:   "#4F46E5",
  primaryHover:"#4338CA",
  brandGrad: "linear-gradient(135deg, #4F46E5, #7C3AED)",
  focus:     "#A5B4FC",

  border:    "rgba(255,255,255,0.08)",
  shadow:    "0 8px 32px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.05)",
  shadowMd:  "0 12px 40px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.06)",
  shadowLg:  "0 24px 64px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.06)",
  radius:    "12px",
  radiusSm:  "8px",
  radiusLg:  "16px",

  glass:       "rgba(255,255,255,0.04)",
  glassBorder: "rgba(255,255,255,0.08)",
  blur:        "blur(20px)",
  raised:      "9px 9px 20px rgba(0,0,0,0.5), -6px -6px 16px rgba(255,255,255,0.03)",
  raisedSm:    "4px 4px 10px rgba(0,0,0,0.5), -3px -3px 8px rgba(255,255,255,0.03)",
  inset:       "inset 5px 5px 11px rgba(0,0,0,0.65), inset -4px -4px 10px rgba(255,255,255,0.03)",
  btn:         "#0E1321",
  btnBorder:   "rgba(255,255,255,0.06)",
  ambient:     "radial-gradient(900px 600px at 10% -10%, rgba(99,102,241,0.22), transparent 60%), radial-gradient(800px 560px at 95% 5%, rgba(34,211,238,0.12), transparent 60%), radial-gradient(900px 700px at 65% 115%, rgba(139,92,246,0.18), transparent 60%)",
};

export type Theme = typeof LIGHT;

export function sevColor(sev: string, t: Theme) {
  const s = sev.toLowerCase();
  if (s === "critical") return { text: t.red,   bg: t.redDim,    border: t.redBorder   };
  if (s === "high")     return { text: t.amber,  bg: t.amberDim,  border: t.amberBorder };
  if (s === "medium")   return { text: t.medium, bg: t.mediumDim, border: t.mediumBorder };
  return                       { text: t.green,  bg: t.greenDim,  border: t.greenBorder };
}

export function statusColor(s: string, t: Theme) {
  if (s === "OPEN")           return { text: t.red,   bg: t.redDim,   border: t.redBorder   };
  if (s === "INVESTIGATING")  return { text: t.amber,  bg: t.amberDim, border: t.amberBorder };
  if (s === "CONTAINED")      return { text: t.medium, bg: t.mediumDim, border: t.mediumBorder };
  if (s === "RESOLVED")       return { text: t.green,  bg: t.greenDim, border: t.greenBorder };
  return                             { text: t.textMuted, bg: t.badge,  border: t.border       };
}
