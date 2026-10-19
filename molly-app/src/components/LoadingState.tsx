import React from 'react';
import { View, StyleSheet } from 'react-native';
import { SkeletonCard } from './Skeleton';
import { spacing } from '@/theme';

/** Shimmering placeholder cards instead of a lone spinner. */
export function LoadingState() {
  return (
    <View style={styles.container}>
      <SkeletonCard />
      <SkeletonCard />
      <SkeletonCard />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, paddingHorizontal: spacing.lg, paddingTop: spacing.lg },
});
