import React from 'react';
import { ThinkingOrb as WebOrb } from 'thinking-orbs';
import type { ThinkingOrbProps } from './ThinkingOrb';

export { orbStateForTool } from './ThinkingOrb';
export type { ThinkingOrbProps, OrbState, OrbSize, OrbTheme } from './ThinkingOrb';

/** Web build: the stock canvas component from Libraries.dev (Metro picks this over ThinkingOrb.tsx). */
export function ThinkingOrb({ dark, theme, accessibilityLabel, style, size = 64, ...rest }: ThinkingOrbProps) {
  return (
    <WebOrb
      {...(rest as any)}
      size={size as any}
      theme={dark === undefined ? theme : dark ? 'dark' : 'light'}
      aria-label={accessibilityLabel}
      style={style as any}
    />
  );
}
