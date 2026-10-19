import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { StyleProp, View, ViewStyle } from 'react-native';
import Animated, {
  useAnimatedStyle,
  useDerivedValue,
  useSharedValue,
  withDelay,
  withSpring,
  withTiming,
  Easing,
} from 'react-native-reanimated';
import type { SharedValue } from 'react-native-reanimated';
import { Blur, Canvas, ColorMatrix, Group, Paint, RoundedRect, Shadow, rect, rrect } from '@shopify/react-native-skia';

/**
 * Native (iOS / Android) Liquid — the "gooey" effect from Libraries.dev's
 * `liquid-gooey`.
 *
 * `liquid-gooey` is built on SVG filters over the DOM, so it can't run in
 * React Native, and the library has no native port. This follows its design:
 * a silhouette layer carries the goo and the shadow (blur + alpha contrast, so
 * touching shapes bridge and merge), while your real views ride crisp on top,
 * moved by the same springs (the library's snappy / smooth / bouncy presets).
 * `Liquid.web.tsx` uses the real package on web.
 *
 * Items should be direct children of <Liquid>.
 */

export type LiquidTransition = 'snappy' | 'smooth' | 'bouncy' | { stiffness: number; damping: number; mass?: number } | { duration: number };

export interface LiquidProps {
  /** Blur (px) of the silhouette layer; larger = stickier bridges. */
  blur?: number;
  /** Alpha contrast of the goo threshold. */
  contrast?: number;
  /** Fill colour of the liquid. */
  fill?: string;
  /** CSS box-shadow-style shadow rebuilt on the merged silhouette, e.g. "0 2px 6px rgba(0,0,0,.08)". */
  shadow?: string;
  /** Extra canvas room (px) around the container so droplets can travel outside it. */
  filterPadding?: number;
  style?: StyleProp<ViewStyle>;
  children?: React.ReactNode;
}

export interface LiquidItemProps {
  x?: number;
  y?: number;
  scale?: number;
  transition?: LiquidTransition;
  /** ms before this item starts moving (stagger). */
  delay?: number;
  /** Silhouette size; defaults to the measured size of the item. */
  width?: number;
  height?: number;
  /** Corner radius of the silhouette; defaults to a pill/circle. */
  radius?: number;
  /** 'morph' (default): merge + spring. 'move': the liquid trails the item as a stretching tail. */
  effect?: 'morph' | 'move';
  /** Where the item starts on mount; it springs from here to its target (a droplet pushed out of something). */
  from?: { x?: number; y?: number; scale?: number; width?: number; height?: number; radius?: number };
  /** Animate width/height/radius to the `width`/`height`/`radius` props (the shape-change morph). */
  animateSize?: boolean;
  style?: StyleProp<ViewStyle>;
  children?: React.ReactNode;
}

const PRESETS = {
  snappy: { stiffness: 480, damping: 34, mass: 1 },
  smooth: { stiffness: 190, damping: 26, mass: 1 },
  bouncy: { stiffness: 320, damping: 17, mass: 1 },
} as const;

interface Rec {
  id: number;
  left: SharedValue<number>;
  top: SharedValue<number>;
  w: SharedValue<number>;
  h: SharedValue<number>;
  tx: SharedValue<number>;
  ty: SharedValue<number>;
  sc: SharedValue<number>;
  r: SharedValue<number>; // -1 = pill
}

const Ctx = createContext<{ register: (r: Rec) => void; unregister: (id: number) => void } | null>(null);

function parseShadow(css?: string) {
  if (!css) return null;
  const m = /(-?[\d.]+)(?:px)?\s+(-?[\d.]+)(?:px)?\s+([\d.]+)(?:px)?\s+(.+)$/.exec(css.trim());
  if (!m) return null;
  return { dx: parseFloat(m[1]), dy: parseFloat(m[2]), blur: parseFloat(m[3]) / 2, color: m[4] };
}

function Silhouette({ rec, fill, pad }: { rec: Rec; fill: string; pad: number }) {
  const rr = useDerivedValue(() => {
    const w = rec.w.value * rec.sc.value;
    const h = rec.h.value * rec.sc.value;
    const cx = pad + rec.left.value + rec.tx.value + rec.w.value / 2;
    const cy = pad + rec.top.value + rec.ty.value + rec.h.value / 2;
    const r = rec.r.value < 0 ? Math.min(w, h) / 2 : rec.r.value * rec.sc.value;
    return rrect(rect(cx - w / 2, cy - h / 2, w, h), r, r);
  });
  return <RoundedRect rect={rr} color={fill} />;
}

export function Liquid({ blur = 6, contrast = 18, fill = '#ffffff', shadow, filterPadding = 96, style, children }: LiquidProps) {
  const [recs, setRecs] = useState<Rec[]>([]);
  const register = useCallback((r: Rec) => setRecs((p) => (p.some((x) => x.id === r.id) ? p : [...p, r])), []);
  const unregister = useCallback((id: number) => setRecs((p) => p.filter((x) => x.id !== id)), []);
  const ctx = useMemo(() => ({ register, unregister }), [register, unregister]);
  const sh = useMemo(() => parseShadow(shadow), [shadow]);
  const pad = filterPadding;

  // Blur, then crush alpha: soft edges snap hard, and neighbours bridge.
  const goo = (
    <Paint>
      <Blur blur={blur} />
      <ColorMatrix matrix={[1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, contrast, -contrast / 2]} />
    </Paint>
  );
  const shadowPaint = sh ? (
    <Paint>
      <Shadow dx={sh.dx} dy={sh.dy} blur={sh.blur} color={sh.color} />
    </Paint>
  ) : undefined;

  return (
    <Ctx.Provider value={ctx}>
      <View style={style}>
        <Canvas
          pointerEvents="none"
          style={{ position: 'absolute', left: -pad, top: -pad, right: -pad, bottom: -pad }}
        >
          <Group layer={shadowPaint}>
            <Group layer={goo}>
              {recs.map((r) => (
                <Silhouette key={r.id} rec={r} fill={fill} pad={pad} />
              ))}
            </Group>
          </Group>
        </Canvas>
        {children}
      </View>
    </Ctx.Provider>
  );
}

let nextId = 1;

function useMotion(transition: LiquidTransition, delay: number) {
  return (target: number, extraDelay = 0, override?: LiquidTransition) => {
    const t = override ?? transition;
    const anim =
      typeof t === 'string'
        ? withSpring(target, PRESETS[t])
        : 'duration' in t
          ? withTiming(target, { duration: t.duration, easing: Easing.out(Easing.cubic) })
          : withSpring(target, { mass: 1, ...t });
    const d = delay + extraDelay;
    return d ? withDelay(d, anim) : anim;
  };
}

function LiquidItem({
  x = 0, y = 0, scale = 1, transition = 'bouncy', delay = 0, width, height, radius,
  effect = 'morph', from, animateSize = false, style, children,
}: LiquidItemProps) {
  const ctx = useContext(Ctx);
  const id = useRef(nextId++).current;
  const tailId = useRef(nextId++).current;
  const left = useSharedValue(0);
  const top = useSharedValue(0);
  const w = useSharedValue(from?.width ?? width ?? 0);
  const h = useSharedValue(from?.height ?? height ?? 0);
  const tx = useSharedValue(from?.x ?? x);
  const ty = useSharedValue(from?.y ?? y);
  const sc = useSharedValue(from?.scale ?? scale);
  const r = useSharedValue(from?.radius ?? radius ?? -1);
  // Tail (effect="move"): its own position, trailing the main one.
  const ttx = useSharedValue(from?.x ?? x);
  const tty = useSharedValue(from?.y ?? y);
  const tsc = useSharedValue((from?.scale ?? scale) * 0.82);

  const rec = useMemo<Rec>(() => ({ id, left, top, w, h, tx, ty, sc, r }), [id, left, top, w, h, tx, ty, sc, r]);
  const tail = useMemo<Rec>(() => ({ id: tailId, left, top, w, h, tx: ttx, ty: tty, sc: tsc, r }), [tailId, left, top, w, h, ttx, tty, tsc, r]);
  const wantsTail = effect === 'move';

  useEffect(() => {
    ctx?.register(rec);
    return () => ctx?.unregister(id);
  }, [ctx, rec, id]);
  useEffect(() => {
    if (!wantsTail) return;
    ctx?.register(tail);
    return () => ctx?.unregister(tailId);
  }, [ctx, tail, tailId, wantsTail]);

  const motion = useMotion(transition, delay);
  useEffect(() => {
    tx.value = motion(x);
    ty.value = motion(y);
    sc.value = motion(scale);
    if (wantsTail) {
      // The tail lags behind with a softer spring, so the liquid stretches while moving and gathers when it stops.
      ttx.value = motion(x, 70, 'smooth');
      tty.value = motion(y, 70, 'smooth');
      tsc.value = motion(scale * 0.82, 70, 'smooth');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [x, y, scale, delay, wantsTail]);

  useEffect(() => {
    if (animateSize) {
      if (width !== undefined) w.value = motion(width);
      if (height !== undefined) h.value = motion(height);
      r.value = radius === undefined ? -1 : motion(radius);
    } else {
      if (width !== undefined) w.value = width;
      if (height !== undefined) h.value = height;
      r.value = radius ?? -1;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [width, height, radius, animateSize]);

  const moveStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: tx.value }, { translateY: ty.value }, { scale: sc.value }],
  }));
  const sizeStyle = useAnimatedStyle(() =>
    animateSize ? { width: w.value, height: h.value, borderRadius: r.value < 0 ? Math.min(w.value, h.value) / 2 : r.value } : {},
  );

  return (
    <Animated.View
      style={[style, animateSize ? sizeStyle : null, moveStyle]}
      onLayout={(e) => {
        const l = e.nativeEvent.layout;
        left.value = l.x;
        top.value = l.y;
        if (!animateSize) {
          if (width === undefined) w.value = l.width;
          if (height === undefined) h.value = l.height;
        }
      }}
    >
      {children}
    </Animated.View>
  );
}

Liquid.Item = LiquidItem;
