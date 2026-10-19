import React from 'react';
import { MetalFx as WebMetalFx } from 'metal-fx';

/** Web build: the real metal-fx ring around a single host element. */
export function MetalFx({ children, variant = 'circle', paused, theme }: { children: React.ReactNode; variant?: 'button' | 'circle'; paused?: boolean; theme?: 'light' | 'dark'; preset?: string; strength?: number; innerShadow?: boolean }) {
  return (
    <WebMetalFx variant={variant} preset="chromatic" theme={theme} paused={paused}>
      <div style={{ display: 'inline-flex', borderRadius: variant === 'circle' ? '50%' : 999 }}>{children}</div>
    </WebMetalFx>
  );
}
