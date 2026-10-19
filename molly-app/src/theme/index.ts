// Molly design tokens.
// Direction: soft and elegant, ChatGPT-app inspired — a warm ivory canvas,
// white cards lifted with gentle shadow instead of hairline borders, a
// confident violet accent, and pill-shaped buttons throughout.

export const color = {
  bg: '#F7F4EF',
  bgElevated: '#FFFFFF',
  surface: '#FFFFFF',
  surfaceHigh: '#F1EDE6',
  border: 'rgba(31, 26, 19, 0.05)',
  borderStrong: 'rgba(31, 26, 19, 0.09)',

  textPrimary: '#211C15',
  textSecondary: '#726B60',
  textTertiary: '#A79E90',

  accent: '#7C5CFC',
  accentSoft: 'rgba(124, 92, 252, 0.12)',
  accentPressed: '#6544DE',

  success: '#3EB27E',
  successSoft: 'rgba(62, 178, 126, 0.14)',
  warning: '#E8A33D',
  warningSoft: 'rgba(232, 163, 61, 0.14)',
  danger: '#E8594B',
  dangerSoft: 'rgba(232, 89, 75, 0.12)',

  overlay: 'rgba(33, 27, 20, 0.45)',
  white: '#FFFFFF',
  black: '#000000',
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 28,
  xxxl: 40,
} as const;

export const radius = {
  sm: 10,
  md: 16,
  lg: 20,
  xl: 26,
  pill: 999,
} as const;

export const font = {
  display: 'Inter_600SemiBold',
  heading: 'Inter_600SemiBold',
  body: 'Inter_400Regular',
  bodyMedium: 'Inter_500Medium',
  mono: 'JetBrainsMono_500Medium',
} as const;

// Default type scale — kept as a static export for any spot that hasn't been
// wired up to the user's typography preferences yet. Anything reachable from
// a screen should prefer `useTypography()` from '@/context/TypographyContext'
// instead, since that reflects the Settings > Text & Display choices.
export const type = {
  title: { fontFamily: font.display, fontSize: 28, lineHeight: 34 },
  h1: { fontFamily: font.heading, fontSize: 20, lineHeight: 26 },
  h2: { fontFamily: font.heading, fontSize: 17, lineHeight: 22 },
  body: { fontFamily: font.body, fontSize: 15, lineHeight: 21 },
  bodyMedium: { fontFamily: font.bodyMedium, fontSize: 15, lineHeight: 21 },
  caption: { fontFamily: font.body, fontSize: 13, lineHeight: 18 },
  captionMedium: { fontFamily: font.bodyMedium, fontSize: 13, lineHeight: 18 },
  micro: { fontFamily: font.bodyMedium, fontSize: 11, lineHeight: 14 },
  mono: { fontFamily: font.mono, fontSize: 13, lineHeight: 19 },
} as const;

// ---------------------------------------------------------------------------
// User-configurable typography
// ---------------------------------------------------------------------------

export type FontChoice = 'inter' | 'system' | 'mono';
export type TypeSizeChoice = 'small' | 'medium' | 'large' | 'xlarge';
export type TypeWeightChoice = 'regular' | 'bold';

export const FONT_CHOICES: { id: FontChoice; label: string; sample: string }[] = [
  { id: 'inter', label: 'Inter', sample: 'Default, clean and neutral' },
  { id: 'system', label: 'System', sample: "Your device's native font" },
  { id: 'mono', label: 'JetBrains Mono', sample: 'Monospaced, operator style' },
];

export const TYPE_SIZE_CHOICES: { id: TypeSizeChoice; label: string; scale: number }[] = [
  { id: 'small', label: 'Small', scale: 0.9 },
  { id: 'medium', label: 'Default', scale: 1.0 },
  { id: 'large', label: 'Large', scale: 1.15 },
  { id: 'xlarge', label: 'Extra Large', scale: 1.3 },
];

export const TYPE_WEIGHT_CHOICES: { id: TypeWeightChoice; label: string }[] = [
  { id: 'regular', label: 'Regular' },
  { id: 'bold', label: 'Bold' },
];

// Font family definitions per role, per choice. `system` intentionally omits
// fontFamily (falls back to the OS default) and leans on fontWeight instead.
const FAMILY_MAP: Record<
  FontChoice,
  Record<TypeWeightChoice, { display: string | undefined; heading: string | undefined; body: string | undefined; bodyMedium: string | undefined; mono: string | undefined }>
> = {
  inter: {
    regular: {
      display: 'Inter_600SemiBold',
      heading: 'Inter_600SemiBold',
      body: 'Inter_400Regular',
      bodyMedium: 'Inter_500Medium',
      mono: 'JetBrainsMono_500Medium',
    },
    bold: {
      display: 'Inter_700Bold',
      heading: 'Inter_700Bold',
      body: 'Inter_500Medium',
      bodyMedium: 'Inter_600SemiBold',
      mono: 'JetBrainsMono_700Bold',
    },
  },
  system: {
    regular: { display: undefined, heading: undefined, body: undefined, bodyMedium: undefined, mono: 'JetBrainsMono_500Medium' },
    bold: { display: undefined, heading: undefined, body: undefined, bodyMedium: undefined, mono: 'JetBrainsMono_700Bold' },
  },
  mono: {
    regular: {
      display: 'JetBrainsMono_600SemiBold',
      heading: 'JetBrainsMono_600SemiBold',
      body: 'JetBrainsMono_400Regular',
      bodyMedium: 'JetBrainsMono_500Medium',
      mono: 'JetBrainsMono_500Medium',
    },
    bold: {
      display: 'JetBrainsMono_700Bold',
      heading: 'JetBrainsMono_700Bold',
      body: 'JetBrainsMono_500Medium',
      bodyMedium: 'JetBrainsMono_700Bold',
      mono: 'JetBrainsMono_700Bold',
    },
  },
};

// `fontWeight` is only meaningful when fontFamily is left undefined (the
// 'system' choice) — RN otherwise ignores it in favor of the named font file.
const SYSTEM_WEIGHT: Record<TypeWeightChoice, { display: any; heading: any; body: any; bodyMedium: any }> = {
  regular: { display: '600', heading: '600', body: '400', bodyMedium: '500' },
  bold: { display: '800', heading: '700', body: '600', bodyMedium: '700' },
};

const BASE_SIZES = {
  title: { fontSize: 28, lineHeight: 34 },
  h1: { fontSize: 20, lineHeight: 26 },
  h2: { fontSize: 17, lineHeight: 22 },
  body: { fontSize: 15, lineHeight: 21 },
  bodyMedium: { fontSize: 15, lineHeight: 21 },
  caption: { fontSize: 13, lineHeight: 18 },
  captionMedium: { fontSize: 13, lineHeight: 18 },
  micro: { fontSize: 11, lineHeight: 14 },
  mono: { fontSize: 13, lineHeight: 19 },
} as const;

function scaled(fontSize: number, lineHeight: number, scale: number) {
  const size = Math.round(fontSize * scale);
  // Keep a little extra breathing room proportionally as text grows.
  const lh = Math.round(lineHeight * scale);
  return { fontSize: size, lineHeight: lh };
}

/** Builds a full `type` scale from the user's font/size/weight preferences. */
export function buildTypeScale(fontChoice: FontChoice, sizeChoice: TypeSizeChoice, weightChoice: TypeWeightChoice) {
  const families = FAMILY_MAP[fontChoice][weightChoice];
  const sysWeight = SYSTEM_WEIGHT[weightChoice];
  const scale = TYPE_SIZE_CHOICES.find((s) => s.id === sizeChoice)?.scale ?? 1;
  const isSystem = fontChoice === 'system';

  const withRole = (role: keyof typeof BASE_SIZES, family: string | undefined, weightRole?: keyof typeof sysWeight) => ({
    fontFamily: family,
    ...(isSystem && weightRole ? { fontWeight: sysWeight[weightRole] } : null),
    ...scaled(BASE_SIZES[role].fontSize, BASE_SIZES[role].lineHeight, scale),
  });

  return {
    title: withRole('title', families.display, 'display'),
    h1: withRole('h1', families.heading, 'heading'),
    h2: withRole('h2', families.heading, 'heading'),
    body: withRole('body', families.body, 'body'),
    bodyMedium: withRole('bodyMedium', families.bodyMedium, 'bodyMedium'),
    caption: withRole('caption', families.body, 'body'),
    captionMedium: withRole('captionMedium', families.bodyMedium, 'bodyMedium'),
    micro: withRole('micro', families.bodyMedium, 'bodyMedium'),
    mono: withRole('mono', families.mono),
  } as const;
}

export type TypeScale = ReturnType<typeof buildTypeScale>;

// Shadow tokens replace hairline borders as the way surfaces separate from
// the canvas — soft, diffuse, and low-contrast rather than a hard edge.
export const shadow = {
  card: {
    shadowColor: '#211C15',
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.06,
    shadowRadius: 18,
    elevation: 3,
  },
  soft: {
    shadowColor: '#211C15',
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.05,
    shadowRadius: 10,
    elevation: 2,
  },
  pill: {
    shadowColor: '#211C15',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.10,
    shadowRadius: 14,
    elevation: 3,
  },
  accentPill: {
    shadowColor: '#7C5CFC',
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.24,
    shadowRadius: 16,
    elevation: 4,
  },
  drawer: {
    shadowColor: '#211C15',
    shadowOffset: { width: 8, height: 0 },
    shadowOpacity: 0.14,
    shadowRadius: 24,
    elevation: 12,
  },
} as const;

export function riskColor(level: string) {
  switch (level.toUpperCase()) {
    case 'DANGEROUS':
    case 'HIGH':
      return color.danger;
    case 'MODERATE':
    case 'MEDIUM':
      return color.warning;
    default:
      return color.success;
  }
}

// Soft gradient tokens. Kept subtle — two or three stops, low contrast between
// stops — so surfaces feel like a gentle wash rather than a loud effect.
export const gradient = {
  // Whole-screen backdrop: a faint vertical lift from the base background.
  screen: [color.bg, '#FAF8F4', color.bg] as const,
  // Card/surface lift, for panels that want a touch more depth than a flat fill.
  surface: [color.surface, color.surface] as const,
  // Primary accent surfaces (buttons, user chat bubble).
  accent: [color.accent, color.accentPressed] as const,
  // Soft tinted fills for badges, icon wells, avatars.
  accentSoft: ['rgba(124, 92, 252, 0.16)', 'rgba(124, 92, 252, 0.05)'] as const,
  successSoft: ['rgba(62, 178, 126, 0.18)', 'rgba(62, 178, 126, 0.05)'] as const,
  warningSoft: ['rgba(232, 163, 61, 0.18)', 'rgba(232, 163, 61, 0.05)'] as const,
  dangerSoft: ['rgba(232, 89, 75, 0.16)', 'rgba(232, 89, 75, 0.05)'] as const,
  // Ambient glow behind the hero orb on splash/pairing screens.
  orbGlow: ['rgba(124, 92, 252, 0.28)', 'rgba(124, 92, 252, 0.08)', 'transparent'] as const,
} as const;

// Two-stop soft tint gradient for a given hex/rgb color, e.g. dynamic risk colors.
export function softTint(hex: string) {
  return [`${hex}38`, `${hex}08`] as const;
}
