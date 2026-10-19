import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { BotAvatar } from '@/vendor/bot-avatars-native';
import { color, gradient } from '@/theme';
import { useTypography } from '@/context/TypographyContext';

/**
 * Molly is the official animated bot avatar from Libraries.dev (a plush clover
 * that idles, and works while she's thinking). Any other name falls back to
 * an initial. `paused` freezes it on a still pose — used for avatars in the
 * message history so only the live one animates.
 */
export function Avatar({
  label,
  size = 36,
  working = false,
  paused = false,
}: {
  label: string;
  size?: number;
  working?: boolean;
  paused?: boolean;
}) {
  const { type } = useTypography();
  if (label === 'Molly') {
    return (
      <BotAvatar
        type="clover"
        state={working ? 'working' : 'default'}
        size={size}
        paused={paused}
        theme="light"
        accessibilityLabel="Molly"
      />
    );
  }
  const initial = label.trim().charAt(0).toUpperCase() || '?';
  return (
    <View style={[styles.circle, { width: size, height: size, borderRadius: size / 2 }]}>
      <LinearGradient
        colors={gradient.accentSoft}
        style={StyleSheet.absoluteFill}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
      />
      <Text style={[type.captionMedium, styles.text]}>{initial}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  circle: {
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  text: { color: color.accent },
});
