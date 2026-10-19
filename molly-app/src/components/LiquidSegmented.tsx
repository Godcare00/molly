import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Liquid } from './Liquid';
import { color, radius } from '@/theme';
import { useTypography } from '@/context/TypographyContext';

const H = 44;

/** Segmented control whose selected pill slides with a liquid trailing tail. */
export function LiquidSegmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { id: T; label: string }[];
  value: T;
  onChange: (id: T) => void;
}) {
  const { type } = useTypography();
  const [w, setW] = useState(0);
  const segW = w / options.length;
  const idx = Math.max(0, options.findIndex((o) => o.id === value));

  return (
    <View style={styles.track} onLayout={(e) => setW(e.nativeEvent.layout.width - 8)}>
      {w > 0 ? (
        <>
          <Liquid blur={5} contrast={16} fill={color.accent} filterPadding={16} style={[StyleSheet.absoluteFill, styles.pad]}>
            <Liquid.Item effect="move" x={idx * segW} transition="snappy" width={segW} height={H - 8} radius={radius.md} style={styles.pill} />
          </Liquid>
          <View style={[styles.row, styles.pad]} pointerEvents="box-none">
            {options.map((o) => (
              <Pressable key={o.id} accessibilityRole="button" accessibilityState={{ selected: o.id === value }} onPress={() => onChange(o.id)} style={styles.seg}>
                <Text style={[type.bodyMedium, { color: o.id === value ? color.white : color.textPrimary }]}>{o.label}</Text>
              </Pressable>
            ))}
          </View>
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  track: { height: H, borderRadius: radius.md + 4, backgroundColor: color.bgElevated, margin: 8 },
  pad: { left: 4, top: 4, right: 4, bottom: 4, position: 'absolute' },
  row: { flexDirection: 'row' },
  pill: { position: 'absolute', left: 0, top: 0 },
  seg: { flex: 1, height: H - 8, alignItems: 'center', justifyContent: 'center' },
});
