import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Animated, { FadeInDown } from 'react-native-reanimated';
import { PressableScale } from './PressableScale';
import { LinearGradient } from 'expo-linear-gradient';
import { StatusDot } from './StatusDot';
import { color, gradient, radius, shadow, spacing } from '@/theme';
import { useTypography } from '@/context/TypographyContext';
import type { Project } from '@/types/api';

export function ProjectCard({ project, onPress, index = 0 }: { project: Project; onPress: () => void; index?: number }) {
  const { type } = useTypography();
  const isProd = project.environment?.toLowerCase() === 'production';
  return (
    <Animated.View entering={FadeInDown.delay(Math.min(index, 8) * 50).duration(320).springify().damping(16)}>
    <PressableScale onPress={onPress} scaleTo={0.98} style={styles.card}>
      <View style={styles.iconWrap}>
        <LinearGradient
          colors={gradient.accentSoft}
          style={StyleSheet.absoluteFill}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
        />
        <Text style={[styles.iconText, { fontFamily: type.h2.fontFamily }]}>
          {project.name.charAt(0).toUpperCase()}
        </Text>
      </View>
      <View style={styles.info}>
        <Text style={[type.bodyMedium, styles.name]}>{project.name}</Text>
        <Text style={[type.caption, styles.path]} numberOfLines={1}>
          {project.path}
        </Text>
        <View style={styles.statusRow}>
          <StatusDot status={isProd ? 'online' : 'warning'} size={6} />
          <Text style={[type.caption, styles.envText]}>{project.environment}</Text>
        </View>
      </View>
      <Text style={styles.chevron}>›</Text>
    </PressableScale>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: spacing.md,
    marginBottom: spacing.md,
    backgroundColor: color.surface,
    ...shadow.card,
  },
  iconWrap: {
    width: 44,
    height: 44,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  iconText: { color: color.accent, fontSize: 17 },
  info: { flex: 1, gap: 2 },
  name: { color: color.textPrimary },
  path: { color: color.textTertiary },
  statusRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 2 },
  envText: { color: color.textSecondary },
  chevron: { color: color.textTertiary, fontSize: 22 },
});
