import React, { useEffect, useMemo, useState } from 'react';
import { LayoutChangeEvent, StyleProp, View, ViewStyle } from 'react-native';
import Animated, { useAnimatedStyle, useDerivedValue, useFrameCallback, useSharedValue, withTiming } from 'react-native-reanimated';
import type { SharedValue } from 'react-native-reanimated';
import { Canvas, Circle, Group, LinearGradient, RadialGradient, Rect, vec } from '@shopify/react-native-skia';
import { radius as radiusTokens } from '@/theme';

/**
 * Native (iOS / Android) VoiceBeam — the "voice-glow" effect from Libraries.dev.
 *
 * `voice-glow` listens to a browser MediaStream, which doesn't exist in React
 * Native, and the library has no native port. This follows its published spec
 * instead: seven soft lobes fanning from the bottom-centre of an element
 * (same geometry and palettes), a centre lobe following the lows, its
 * neighbours the mids and the outer pairs the highs (synthesised from `level`),
 * colours that flow sideways while a voice is heard, a thin edge stroke, and a
 * quiet idle breath so it never looks dead. Feed it a `level` (0–1 number, or
 * a getter sampled every frame) from your own audio meter.
 * `VoiceBeam.web.tsx` uses the real package on web.
 */

export type VoiceBeamColorVariant = 'colorful' | 'mono' | 'ocean' | 'sunset' | 'forest' | 'candy' | 'ice' | 'gold';
export type VoiceBeamLevel = number | (() => number);

export interface VoiceBeamProps {
  /** 0–1 loudness: a number, or a getter read every frame (no re-render). */
  level?: VoiceBeamLevel;
  colorVariant?: VoiceBeamColorVariant;
  /** Input gain — raise for quiet sources. */
  sensitivity?: number;
  /** Noise gate: below this is silence. */
  threshold?: number;
  /** Seconds to rise. */
  attack?: number;
  /** Seconds to settle. */
  release?: number;
  /** How tall it grows at full level. */
  reach?: number;
  /** How far the lobes widen with the voice. */
  spread?: number;
  /** Sideways colour travel at full level (px/s at the 350px reference). */
  flow?: number;
  /** Resting breath, 0 = nothing at all while silent. */
  idle?: number;
  /** Fade the whole effect in/out. */
  active?: boolean;
  /** Corner radius of the wrapped element (the glow is clipped to it). */
  borderRadius?: number;
  style?: StyleProp<ViewStyle>;
  children: React.ReactNode;
}

// Lobe geometry in px for a ~350px-wide element (from voice-glow).
const LOBES = [
  { x: 0, w: 74, h: 46, band: 0 },
  { x: -36, w: 54, h: 40, band: 1 },
  { x: 36, w: 54, h: 40, band: 1 },
  { x: -72, w: 48, h: 32, band: 2 },
  { x: 72, w: 48, h: 32, band: 2 },
  { x: -108, w: 42, h: 26, band: 1 },
  { x: 108, w: 42, h: 26, band: 1 },
] as const;
const LOBE_SPAN = 36 * LOBES.length;

// voice-glow's light-theme palettes: centre lobe first, then pairs outward.
const PALETTES: Record<VoiceBeamColorVariant, [number, number, number][]> = {
  colorful: [[255, 201, 21], [126, 196, 255], [180, 40, 230], [235, 100, 160], [255, 176, 122], [154, 160, 255], [127, 217, 238]],
  mono: [[60, 60, 60], [90, 90, 90], [85, 85, 85], [110, 110, 110], [105, 105, 105], [125, 125, 125], [120, 120, 120]],
  ocean: [[40, 100, 240], [20, 160, 200], [90, 60, 230], [20, 130, 180], [130, 50, 220], [40, 80, 230], [20, 150, 150]],
  sunset: [[235, 80, 30], [230, 150, 10], [230, 30, 70], [225, 175, 30], [215, 40, 110], [235, 110, 20], [205, 30, 90]],
  forest: [[30, 170, 80], [20, 150, 130], [90, 180, 30], [20, 130, 100], [130, 180, 20], [30, 150, 80], [20, 120, 90]],
  candy: [[235, 40, 140], [230, 70, 190], [180, 40, 230], [235, 100, 160], [150, 70, 230], [230, 30, 110], [200, 60, 210]],
  ice: [[30, 160, 220], [20, 130, 210], [60, 180, 230], [40, 120, 220], [50, 160, 220], [20, 110, 220], [70, 170, 230]],
  gold: [[200, 140, 10], [190, 120, 0], [210, 160, 30], [180, 110, 0], [205, 170, 40], [175, 115, 5], [195, 150, 20]],
};

const rgba = (c: [number, number, number], a: number) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;

interface Drive {
  lvl: SharedValue<number>;
  phase: SharedValue<number>;
  clock: SharedValue<number>;
}

function Lobe({ i, color, W, H, k, drive, idle, reach, spread }: {
  i: number; color: [number, number, number]; W: number; H: number; k: number; drive: Drive; idle: number; reach: number; spread: number;
}) {
  const lobe = LOBES[i];
  const transform = useDerivedValue(() => {
    const L = drive.lvl.value;
    const t = drive.clock.value;
    // Bands are synthesised from the level so the lobes still dance.
    const wob = lobe.band === 0 ? 1 : lobe.band === 1 ? 0.75 + 0.25 * Math.sin(t * 3.1 + i * 1.7) : 0.55 + 0.45 * Math.sin(t * 5.3 + i * 2.3);
    const breath = idle * (0.55 + 0.45 * Math.sin(t * 1.6 + i * 0.9));
    const band = Math.max(L * wob, breath);
    const h = Math.min(H * 1.15, lobe.h * k * (0.25 + 1.9 * band * reach));
    // Slide along the ring, wrapping at ±span/2 so every colour takes a turn at the centre.
    const half = LOBE_SPAN / 2;
    const pos = ((((lobe.x + drive.phase.value + half) % LOBE_SPAN) + LOBE_SPAN) % LOBE_SPAN) - half;
    const x = W / 2 + pos * k * (1 + spread * 0.5 * L);
    const w = lobe.w * k * (1 + 0.25 * L);
    return [{ translateX: x }, { translateY: H }, { scaleX: w }, { scaleY: Math.max(0.5, h) }];
  });
  const opacity = useDerivedValue(() => {
    const half = LOBE_SPAN / 2;
    const pos = ((((lobe.x + drive.phase.value + half) % LOBE_SPAN) + LOBE_SPAN) % LOBE_SPAN) - half;
    const edge = Math.min(1, Math.max(0, (1 - Math.abs(pos) / half) / 0.2)); // fade through the wrap point
    const L = drive.lvl.value;
    return edge * (0.4 + 0.6 * Math.min(1, L * 1.4 + idle));
  });
  return (
    <Group transform={transform} opacity={opacity}>
      <Circle cx={0} cy={0} r={1}>
        <RadialGradient c={vec(0, 0)} r={1} colors={[rgba(color, 0.85), rgba(color, 0.35), rgba(color, 0)]} positions={[0, 0.45, 1]} />
      </Circle>
    </Group>
  );
}

export function VoiceBeam({
  level = 0,
  colorVariant = 'colorful',
  sensitivity = 1.6,
  threshold = 0.03,
  attack = 0.1,
  release = 0.5,
  reach = 1,
  spread = 0.6,
  flow = 80,
  idle = 0.16,
  active = true,
  borderRadius = radiusTokens.xl,
  style,
  children,
}: VoiceBeamProps) {
  const [box, setBox] = useState({ w: 0, h: 0 });
  const palette = PALETTES[colorVariant];
  const target = useSharedValue(0);
  const lvl = useSharedValue(0);
  const phase = useSharedValue(0);
  const clock = useSharedValue(0);
  const shown = useSharedValue(active ? 1 : 0);
  const drive = useMemo<Drive>(() => ({ lvl, phase, clock }), [lvl, phase, clock]);

  // JS side hands the raw level to the UI thread; smoothing happens there.
  useEffect(() => {
    if (typeof level === 'number') {
      target.value = level;
      return;
    }
    let raf = 0;
    const loop = () => {
      target.value = level();
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [level, target]);

  useEffect(() => {
    shown.value = withTiming(active ? 1 : 0, { duration: 300 });
  }, [active, shown]);

  const k = Math.min(1.5, Math.max(0.5, box.w / 350 || 1));
  useFrameCallback((f) => {
    const dt = Math.min(0.05, (f.timeSincePreviousFrame ?? 16) / 1000);
    clock.value += dt;
    let want = (target.value * sensitivity - threshold) / (1 - threshold);
    want = Math.min(1, Math.max(0, want));
    const tau = Math.max(0.001, want > lvl.value ? attack : release);
    lvl.value += (want - lvl.value) * (1 - Math.exp(-dt / tau));
    phase.value = (phase.value + flow * lvl.value * dt) % LOBE_SPAN;
  });

  const wrapStyle = useAnimatedStyle(() => ({ opacity: shown.value }));
  const strokeOpacity = useDerivedValue(() => 0.35 + 0.65 * Math.min(1, lvl.value * 1.5 + idle));

  const W = box.w;
  const H = Math.min(box.h, 72 * k);
  const onLayout = (e: LayoutChangeEvent) => {
    const { width, height } = e.nativeEvent.layout;
    setBox((p) => (p.w === width && p.h === height ? p : { w: width, h: height }));
  };

  return (
    <View style={style} onLayout={onLayout}>
      {children}
      {W > 0 && idle + 1 > 0 ? (
        <Animated.View
          pointerEvents="none"
          style={[
            {
              position: 'absolute',
              left: 0,
              right: 0,
              bottom: 0,
              height: H,
              overflow: 'hidden',
              borderBottomLeftRadius: borderRadius,
              borderBottomRightRadius: borderRadius,
            },
            wrapStyle,
          ]}
        >
          <Canvas style={{ width: W, height: H }}>
            {palette.map((c, i) => (
              <Lobe key={i} i={i} color={c} W={W} H={H} k={k} drive={drive} idle={idle} reach={reach} spread={spread} />
            ))}
            {/* The 1.5px edge stroke along the bottom. */}
            <Group opacity={strokeOpacity}>
              <Rect x={0} y={H - 1.5} width={W} height={1.5}>
                <LinearGradient
                  start={vec(0, 0)}
                  end={vec(W, 0)}
                  colors={[0, 3, 1, 4, 2, 5, 6].map((j) => rgba(palette[j] ?? palette[0], 0.95))}
                />
              </Rect>
            </Group>
          </Canvas>
        </Animated.View>
      ) : null}
    </View>
  );
}
