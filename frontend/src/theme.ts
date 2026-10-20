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
  textMuted: "#465163",
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
  // FILL tokens: for bars, rings and dots. The text colours above are tuned for 4.5:1 text and look muddy as fills.
  // Light fills target >= 3:1 against the inset track (red 3.7, amber 3.2, medium 4.1, green 3.2).
  redFill:   "#E11D48",
  amberFill: "#C2640A",
  mediumFill:"#2563EB",
  greenFill: "#04916A",
  // Do NOT pass t.accent as a bar fill in light (2.0:1 against the track): use accentGrad or a fill token there.
  accentGrad:"linear-gradient(90deg, #2563EB, #0E7490)",   // neutral accent bars: blue to cyan, not emerald (indigo is dark-theme only); both ends >= 3:1 on the inset track (4.1, 4.2)
  // Neutral accent for incident ids, links, selected rows. Emerald (t.blue / t.primary / t.green) is kept for the primary action, active tab and success.
  link:      "#334155",
  linkDim:   "#E2E8F0",
  linkBorder:"#94A3B8",
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
  // Selection highlight (selected filter chip, selected list row): the ring is decorative, selection is also conveyed by the inset surface, weight and aria-pressed
  selBorder:   "rgba(16,185,129,0.65)",
  selGlow:     "0 0 14px rgba(16,185,129,0.30)",
  selText:     "#065F46",
  glass:       "rgba(255,255,255,0.46)",
  glassBorder: "rgba(255,255,255,0.9)",
  blur:        "blur(20px)",
  raised:      "8px 8px 16px #A3B1C6, -8px -8px 16px rgba(255,255,255,0.9)",
  raisedSm:    "4px 4px 8px #A3B1C6, -4px -4px 8px rgba(255,255,255,0.9)",
  inset:       "inset 6px 6px 12px #A3B1C6, inset -6px -6px 12px rgba(255,255,255,0.9)",
  btn:         "#E0E5EC",
  btnBorder:   "rgba(255,255,255,0.6)",
  primaryShadow:"6px 8px 18px rgba(4,120,87,0.35), -4px -4px 10px rgba(255,255,255,0.8)",
  cyan:        "#0891B2",   // decorative only (dots, rings)
  heroRing:    "rgba(16,185,129,0.4)",
  heroGlow:    "rgba(16,185,129,0.22)",
  heroDash:    "rgba(13,148,136,0.4)",
  heroConic:   "conic-gradient(from 0deg, rgba(16,185,129,0) 0deg, #10B981 140deg, #0891B2 300deg, rgba(8,145,178,0) 360deg)",
  ambient:     "radial-gradient(1100px 760px at 8% -8%, rgba(16,185,129,0.34), transparent 60%), radial-gradient(900px 640px at 96% 4%, rgba(59,130,246,0.30), transparent 60%), radial-gradient(1100px 800px at 56% 112%, rgba(14,165,233,0.32), transparent 60%), radial-gradient(900px 700px at 0% 100%, rgba(99,102,241,0.16), transparent 60%), radial-gradient(800px 600px at 100% 96%, rgba(59,130,246,0.18), transparent 60%)",
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
  textMuted: "#9AA3BC",
  textInv:   "#ffffff",

  // accent as text: #8E98F9 (>= 4.8:1 even on glass over the strongest glow). The spec indigo #6366F1 is only 4.3:1 on the canvas, so it is used for fills (t.accent) only.
  blue:      "#8E98F9",
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
  purple:    "#B4A0FB",
  purpleDim: "#221B3F",
  medium:    "#60A5FA",
  mediumDim: "#12233D",
  mediumBorder:"#2A5594",
  redFill:   "#FB7185",
  amberFill: "#FBBF24",
  mediumFill:"#60A5FA",
  greenFill: "#34D399",
  accentGrad:"linear-gradient(90deg, #6366F1, #22D3EE)",
  link:      "#8E98F9",
  linkDim:   "#1C1F45",
  linkBorder:"#3F4290",
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

  selBorder:   "rgba(142,152,249,0.65)",
  selGlow:     "0 0 14px rgba(142,152,249,0.30)",
  selText:     "#8E98F9",
  glass:       "rgba(255,255,255,0.04)",
  glassBorder: "rgba(255,255,255,0.08)",
  blur:        "blur(20px)",
  raised:      "9px 9px 20px rgba(0,0,0,0.5), -6px -6px 16px rgba(255,255,255,0.03)",
  raisedSm:    "4px 4px 10px rgba(0,0,0,0.5), -3px -3px 8px rgba(255,255,255,0.03)",
  inset:       "inset 5px 5px 11px rgba(0,0,0,0.65), inset -4px -4px 10px rgba(255,255,255,0.03)",
  btn:         "#0E1321",
  btnBorder:   "rgba(255,255,255,0.06)",
  primaryShadow:"6px 8px 20px rgba(79,70,229,0.45), -4px -4px 10px rgba(255,255,255,0.03)",
  cyan:        "#22D3EE",
  heroRing:    "rgba(99,102,241,0.4)",
  heroGlow:    "rgba(99,102,241,0.25)",
  heroDash:    "rgba(34,211,238,0.4)",
  heroConic:   "conic-gradient(from 0deg, rgba(99,102,241,0) 0deg, #6366F1 140deg, #22D3EE 300deg, rgba(34,211,238,0) 360deg)",
  ambient:     "radial-gradient(1100px 760px at 8% -8%, rgba(99,102,241,0.30), transparent 60%), radial-gradient(900px 640px at 96% 4%, rgba(34,211,238,0.18), transparent 60%), radial-gradient(1100px 800px at 62% 112%, rgba(139,92,246,0.26), transparent 60%), radial-gradient(900px 700px at 2% 100%, rgba(99,102,241,0.20), transparent 60%), radial-gradient(800px 600px at 100% 96%, rgba(34,211,238,0.14), transparent 60%)",
};

export type Theme = typeof LIGHT;

export function sevColor(sev: string, t: Theme) {
  const s = sev.toLowerCase();
  if (s === "critical") return { text: t.red,   bg: t.redDim,    border: t.redBorder,    fill: t.redFill    };
  if (s === "high")     return { text: t.amber,  bg: t.amberDim,  border: t.amberBorder,  fill: t.amberFill  };
  if (s === "medium")   return { text: t.medium, bg: t.mediumDim, border: t.mediumBorder, fill: t.mediumFill };
  return                       { text: t.green,  bg: t.greenDim,  border: t.greenBorder,  fill: t.greenFill  };
}

// Bars receive a status TEXT colour from their callers; this maps it to the matching FILL (plus a soft glow) so
// bars are never drawn in dark text colours. In the light theme t.blue and t.green are the same hex, so green wins;
// accent bars should pass t.link (-> accent gradient). Unknown colours pass through unchanged.
// Pass `fill` (e.g. t.accent, t.redFill) to bypass the mapping.
export function fillOf(color: string, t: Theme, fill?: string): { bg: string; glow: string } {
  const hit = fill !== undefined ? undefined : ([[t.red, t.redFill], [t.amber, t.amberFill], [t.medium, t.mediumFill], [t.green, t.greenFill], [t.link, t.accentGrad], [t.blue, t.accentGrad]] as [string, string][]).find(([k]) => k === color);
  const bg = fill ?? (hit ? hit[1] : color);
  return { bg, glow: (bg.match(/#[0-9a-fA-F]{6}/)?.[0] ?? t.link) + "4d" };
}

export function statusColor(s: string, t: Theme) {
  if (s === "OPEN")           return { text: t.red,   bg: t.redDim,   border: t.redBorder   };
  if (s === "INVESTIGATING")  return { text: t.amber,  bg: t.amberDim, border: t.amberBorder };
  if (s === "CONTAINED")      return { text: t.medium, bg: t.mediumDim, border: t.mediumBorder };
  if (s === "RESOLVED")       return { text: t.green,  bg: t.greenDim, border: t.greenBorder };
  return                             { text: t.textMuted, bg: t.badge,  border: t.border       };
}
