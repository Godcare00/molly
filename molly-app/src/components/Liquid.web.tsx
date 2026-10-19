import React, { useEffect, useState } from 'react';
import { Liquid as WebLiquid } from 'liquid-gooey';
import type { LiquidProps as NativeProps, LiquidItemProps as NativeItemProps } from './Liquid';

export type { LiquidProps, LiquidItemProps, LiquidTransition } from './Liquid';

/** Web build: the real `liquid-gooey` package (Metro picks this over Liquid.tsx). */
export function Liquid({ filterPadding, style, children, ...rest }: NativeProps) {
  return (
    <WebLiquid {...(rest as any)} filterPadding={filterPadding} style={style as any}>
      {children as React.ReactNode}
    </WebLiquid>
  );
}

// `width` / `height` / `radius` only matter to the native silhouette; the DOM measures itself.
function Item({ width: _w, height: _h, radius: _r, from, animateSize, effect, x = 0, y = 0, scale = 1, style, children, ...rest }: NativeItemProps) {
  // `from`: start at the origin on mount, then move to the target (the library animates the change).
  const [ready, setReady] = useState(!from);
  useEffect(() => {
    if (from) {
      const t = setTimeout(() => setReady(true), 16);
      return () => clearTimeout(t);
    }
  }, [from]);
  return (
    <WebLiquid.Item
      {...(rest as any)}
      effect={effect === 'move' ? 'move' : undefined}
      morph={animateSize ? { shape: true } : undefined}
      x={ready ? x : from?.x ?? x}
      y={ready ? y : from?.y ?? y}
      scale={ready ? scale : from?.scale ?? scale}
      style={style as any}
    >
      {children}
    </WebLiquid.Item>
  );
}
Liquid.Item = Item;
