import React from 'react';
import { View, Text, StyleSheet, ViewStyle } from 'react-native';
import { ThinkingOrb } from './ThinkingOrb';
import { PressableScale } from './PressableScale';
import { LinearGradient } from 'expo-linear-gradient';
import { color, gradient, radius, shadow, spacing } from '@/theme';
import { useTypography } from '@/context/TypographyContext';

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost' | 'white';

const FILL_GRADIENT: Partial<Record<Variant, readonly [string, string]>> = {
  primary: gradient.accent,
  secondary: [color.white, color.white],
  danger: gradient.dangerSoft,
  white: [color.white, color.white],
};

// Every variant renders as a soft pill — the difference is fill and shadow,
// never a stroke. Ghost is the only variant with no shadow, since it reads as
// plain text rather than a raised surface.
const SHADOW_STYLE: Partial<Record<Variant, object>> = {
  primary: shadow.accentPill,
  secondary: shadow.pill,
  white: shadow.pill,
  danger: shadow.soft,
};

export function Button({
  label,
  onPress,
  variant = 'primary',
  loading = false,
  disabled = false,
  style,
}: {
  label: string;
  onPress: () => void;
  variant?: Variant;
  loading?: boolean;
  disabled?: boolean;
  style?: ViewStyle;
}) {
  const { type } = useTypography();
  const isDisabled = disabled || loading;
  const fill = FILL_GRADIENT[variant];
  return (
    <PressableScale
      onPress={onPress}
      disabled={isDisabled}
      haptic={variant === 'primary' || variant === 'danger'}
      style={[styles.shadowWrap, !isDisabled && SHADOW_STYLE[variant], isDisabled && styles.disabled, style]}
    >
      <View style={styles.base}>
        {fill ? (
          <LinearGradient
            colors={fill}
            style={StyleSheet.absoluteFill}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 1 }}
          />
        ) : null}
        {loading ? (
          <ThinkingOrb state="working" size={20} dark={variant === 'primary'} />
        ) : (
          <Text style={[type.bodyMedium, textVariantStyles[variant]]}>{label}</Text>
        )}
      </View>
    </PressableScale>
  );
}

const styles = StyleSheet.create({
  shadowWrap: {
    borderRadius: radius.pill,
  },
  base: {
    height: 52,
    borderRadius: radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.xl,
    overflow: 'hidden',
  },
  disabled: { opacity: 0.45 },
});

const textVariantStyles: Record<Variant, { color: string }> = {
  primary: { color: color.white },
  secondary: { color: color.textPrimary },
  danger: { color: color.danger },
  ghost: { color: color.accent },
  white: { color: color.textPrimary },
};
