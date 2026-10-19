import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Feather } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import { color, softTint, spacing } from '@/theme';
import { useTypography } from '@/context/TypographyContext';
import type { ActivityItem } from '@/types/api';

const ICONS: Record<ActivityItem['status'], { name: React.ComponentProps<typeof Feather>['name']; tint: string }> = {
  complete: { name: 'check', tint: color.success },
  error: { name: 'x', tint: color.danger },
  running: { name: 'loader', tint: color.accent },
  pending: { name: 'more-horizontal', tint: color.warning },
};

function formatTime(iso: string) {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function ActivityRow({ item }: { item: ActivityItem }) {
  const { type } = useTypography();
  const icon = ICONS[item.status];
  return (
    <View style={styles.row}>
      <Text style={[type.caption, styles.time]}>{formatTime(item.timestamp)}</Text>
      <View style={styles.iconWrap}>
        <LinearGradient
          colors={softTint(icon.tint)}
          style={StyleSheet.absoluteFill}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
        />
        <Feather name={icon.name} size={12} color={icon.tint} />
      </View>
      <View style={styles.textCol}>
        <Text style={[type.bodyMedium, styles.title]}>{item.title}</Text>
        {item.subtitle ? (
          <Text style={[type.caption, styles.subtitle]} numberOfLines={1}>
            {item.subtitle}
          </Text>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.md, paddingVertical: spacing.sm },
  time: { color: color.textTertiary, width: 44 },
  iconWrap: {
    width: 22,
    height: 22,
    borderRadius: 11,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 1,
    overflow: 'hidden',
  },
  textCol: { flex: 1 },
  title: { color: color.textPrimary },
  subtitle: { color: color.textTertiary, marginTop: 2 },
});
