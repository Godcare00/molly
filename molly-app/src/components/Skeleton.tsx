import React, { useEffect, useState } from 'react';
import { View, StyleSheet, StyleProp, ViewStyle, DimensionValue } from 'react-native';
import Animated, { Easing, useAnimatedStyle, useSharedValue, withRepeat, withTiming } from 'react-native-reanimated';
import { LinearGradient } from 'expo-linear-gradient';
import { color, radius, shadow, spacing } from '@/theme';

/** A rounded placeholder block with a soft shimmer sweeping across it. */
export function Skeleton({
  width = '100%',
  height = 14,
  borderRadius = radius.sm,
  style,
}: {
  width?: DimensionValue;
  height?: number;
  borderRadius?: number;
  style?: StyleProp<ViewStyle>;
}) {
  const [w, setW] = useState(0);
  const t = useSharedValue(0);

  useEffect(() => {
    t.value = withRepeat(withTiming(1, { duration: 1300, easing: Easing.inOut(Easing.quad) }), -1);
  }, [t]);

  const sweep = useAnimatedStyle(() => ({ transform: [{ translateX: -w + t.value * w * 2 }] }));

  return (
    <View
      onLayout={(e) => setW(e.nativeEvent.layout.width)}
      style={[{ width, height, borderRadius, backgroundColor: color.surfaceHigh, overflow: 'hidden' }, style]}
    >
      {w > 0 ? (
        <Animated.View style={[StyleSheet.absoluteFill, sweep]}>
          <LinearGradient
            colors={['transparent', 'rgba(255,255,255,0.75)', 'transparent']}
            start={{ x: 0, y: 0.5 }}
            end={{ x: 1, y: 0.5 }}
            style={StyleSheet.absoluteFill}
          />
        </Animated.View>
      ) : null}
    </View>
  );
}

/** Card-shaped skeleton matching ProjectCard / list rows. */
export function SkeletonCard() {
  return (
    <View style={styles.card}>
      <Skeleton width={44} height={44} borderRadius={radius.md} />
      <View style={{ flex: 1, gap: 8 }}>
        <Skeleton width="55%" height={14} />
        <Skeleton width="85%" height={11} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.md,
    borderRadius: radius.lg,
    backgroundColor: color.surface,
    marginBottom: spacing.md,
    ...shadow.soft,
  },
});
