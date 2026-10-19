import React from 'react';
import type { ViewStyle } from 'react-native';
import { ThinkingOrb as NativeOrb, type OrbState, type OrbSize, type OrbTheme } from '@/vendor/thinking-orbs-native';

/**
 * Native ThinkingOrb: the official React Native port from Libraries.dev
 * (vendored in src/vendor/thinking-orbs-native). On web, ThinkingOrb.web.tsx
 * uses the `thinking-orbs` package. This wrapper only adds a `dark` boolean
 * (light-ink vs dark-ink tuning) on top of the package's `theme`.
 */
export type { OrbState, OrbSize, OrbTheme };

export interface ThinkingOrbProps {
  state?: OrbState;
  /** 64 = chat-avatar scale, 20 = inline-text scale (separately tuned). */
  size?: OrbSize;
  speed?: number;
  /** true = light ink for dark backgrounds, false = dark ink for light ones. Overrides `theme`. */
  dark?: boolean;
  theme?: OrbTheme;
  paused?: boolean;
  accessibilityLabel?: string;
  style?: ViewStyle;
}

export function ThinkingOrb({ dark, theme = 'auto', ...rest }: ThinkingOrbProps) {
  return <NativeOrb {...rest} theme={dark === undefined ? theme : dark ? 'dark' : 'light'} />;
}

/** Picks an orb state that fits what a tool is doing, from its name. */
export function orbStateForTool(name?: string): OrbState {
  const n = (name ?? '').toLowerCase();
  if (/search|grep|find|query|lookup|web/.test(n)) return 'searching';
  if (/write|edit|compose|draft|create|patch/.test(n)) return 'composing';
  if (/test|debug|solve|calc|build|compile|lint/.test(n)) return 'solving';
  if (/fetch|connect|ssh|http|deploy|curl|net/.test(n)) return 'connecting';
  return 'working';
}
