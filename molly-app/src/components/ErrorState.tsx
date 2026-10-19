import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Button } from './Button';
import { color, spacing } from '@/theme';
import { useTypography } from '@/context/TypographyContext';

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const { type } = useTypography();
  return (
    <View style={styles.container}>
      <Text style={[type.h2, styles.title]}>Something went wrong</Text>
      <Text style={[type.body, styles.message]}>{message}</Text>
      {onRetry ? <Button label="Try again" onPress={onRetry} variant="secondary" /> : null}
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
  title: { color: color.textPrimary },
  message: { color: color.textSecondary, textAlign: 'center', marginBottom: spacing.sm },
});
