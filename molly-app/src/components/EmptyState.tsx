import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { color, spacing } from '@/theme';
import { useTypography } from '@/context/TypographyContext';

export function EmptyState({
  title,
  message,
  action,
}: {
  title: string;
  message?: string;
  action?: React.ReactNode;
}) {
  const { type } = useTypography();
  return (
    <View style={styles.container}>
      <Text style={[type.h1, styles.title]}>{title}</Text>
      {message ? <Text style={[type.body, styles.message]}>{message}</Text> : null}
      {action}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.xxl,
    gap: spacing.sm,
  },
  title: { color: color.textPrimary, textAlign: 'center' },
  message: { color: color.textSecondary, textAlign: 'center' },
});
