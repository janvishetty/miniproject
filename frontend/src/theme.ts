export const LIGHT = {
  // Backgrounds
  bg:        "#f1f5f9",
  nav:       "#ffffff",
  card:      "#ffffff",
  cardHover: "#f8fafc",
  input:     "#f8fafc",
  badge:     "#f1f5f9",

  // Text
  text:      "#0f172a",
  textSub:   "#475569",
  textMuted: "#94a3b8",
  textInv:   "#ffffff",

  // Brand / accents
  blue:      "#2563eb",
  blueDim:   "#eff6ff",
  blueBorder:"#bfdbfe",
  green:     "#059669",
  greenDim:  "#ecfdf5",
  greenBorder:"#a7f3d0",
  amber:     "#d97706",
  amberDim:  "#fffbeb",
  amberBorder:"#fde68a",
  red:       "#dc2626",
  redDim:    "#fef2f2",
  redBorder: "#fecaca",
  purple:    "#7c3aed",
  purpleDim: "#f5f3ff",

  // Structure
  border:    "#e2e8f0",
  shadow:    "0 1px 3px rgba(0,0,0,0.07), 0 1px 2px rgba(0,0,0,0.05)",
  shadowMd:  "0 4px 16px rgba(0,0,0,0.08), 0 2px 6px rgba(0,0,0,0.05)",
  shadowLg:  "0 12px 40px rgba(0,0,0,0.12), 0 4px 12px rgba(0,0,0,0.06)",
  radius:    "12px",
  radiusSm:  "8px",
  radiusLg:  "16px",
};

export const DARK = {
  bg:        "#0F1017",
  nav:       "#171923",
  card:      "#171923",
  cardHover: "#1D1F2B",
  input:     "#0F1017",
  badge:     "#1D1F2B",

  text:      "#F3F4F6",
  textSub:   "#A7ACB8",
  textMuted: "#5A5F70",
  textInv:   "#ffffff",

  // accent → purple in dark mode (the "primary interactive" color)
  blue:      "#8B7CF6",
  blueDim:   "#1E1B3A",
  blueBorder:"#3D3580",

  // semantic status colors — kept readable, not neon
  green:     "#34D399",
  greenDim:  "#052E1A",
  greenBorder:"#065f46",
  amber:     "#FBBF24",
  amberDim:  "#2D1A00",
  amberBorder:"#92400e",
  red:       "#F87171",
  redDim:    "#2A0A0A",
  redBorder: "#7f1d1d",
  purple:    "#8B7CF6",
  purpleDim: "#1E1B3A",

  border:    "#2A2D3A",
  shadow:    "0 1px 3px rgba(0,0,0,0.4), 0 1px 2px rgba(0,0,0,0.3)",
  shadowMd:  "0 4px 16px rgba(0,0,0,0.5), 0 2px 6px rgba(0,0,0,0.4)",
  shadowLg:  "0 12px 40px rgba(0,0,0,0.6), 0 4px 12px rgba(0,0,0,0.4)",
  radius:    "12px",
  radiusSm:  "8px",
  radiusLg:  "16px",
};

export type Theme = typeof LIGHT;

export function sevColor(sev: string, t: Theme) {
  const s = sev.toLowerCase();
  if (s === "critical") return { text: t.red,   bg: t.redDim,    border: t.redBorder   };
  if (s === "high")     return { text: t.amber,  bg: t.amberDim,  border: t.amberBorder };
  if (s === "medium")   return { text: t.blue,   bg: t.blueDim,   border: t.blueBorder  };
  return                       { text: t.green,  bg: t.greenDim,  border: t.greenBorder };
}

export function statusColor(s: string, t: Theme) {
  if (s === "OPEN")           return { text: t.red,   bg: t.redDim,   border: t.redBorder   };
  if (s === "INVESTIGATING")  return { text: t.amber,  bg: t.amberDim, border: t.amberBorder };
  if (s === "CONTAINED")      return { text: t.blue,   bg: t.blueDim,  border: t.blueBorder  };
  if (s === "RESOLVED")       return { text: t.green,  bg: t.greenDim, border: t.greenBorder };
  return                             { text: t.textMuted, bg: t.badge,  border: t.border       };
}
