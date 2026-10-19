import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Animated, { FadeInDown } from 'react-native-reanimated';
import { Avatar } from './Avatar';
import { Liquid } from './Liquid';
import { ThinkingOrb, type OrbState } from './ThinkingOrb';
import { color, radius, spacing } from '@/theme';
import { useTypography } from '@/context/TypographyContext';

const LABEL: Partial<Record<OrbState, string>> = {
  working: 'Working…',
  searching: 'Searching…',
  composing: 'Writing…',
  solving: 'Solving…',
  connecting: 'Connecting…',
};

/** "Molly is working" bubble at the end of the thread, with an orb that reflects what she's doing. */
export function TypingIndicator({ state = 'working' }: { state?: OrbState }) {
  const { type } = useTypography();
  return (
    <Animated.View entering={FadeInDown.duration(220)} style={styles.row}>
      <Liquid blur={5} contrast={16} fill={color.surface} shadow="0 2px 8px rgba(33,28,21,.10)" filterPadding={24} style={styles.liquid}>
        <Liquid.Item width={28} height={28} radius={14} style={styles.avatar}>
          <Avatar label="Molly" size={28} working />
        </Liquid.Item>
        <Liquid.Item from={{ x: -30, scale: 0.6 }} transition="bouncy" delay={120} radius={radius.lg} style={styles.bubble}>
          <ThinkingOrb state={state} size={20} dark={false} />
          <Text style={[type.caption, styles.label]}>{LABEL[state] ?? 'Thinking…'}</Text>
        </Liquid.Item>
      </Liquid>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'flex-end', gap: 0, paddingHorizontal: spacing.lg, marginBottom: spacing.lg },
  liquid: { flexDirection: 'row', alignItems: 'flex-end', gap: 3 },
  avatar: { width: 28, height: 28 },
  bubble: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    height: 40,
    paddingHorizontal: spacing.lg,
  },
  label: { color: color.textSecondary },
});
