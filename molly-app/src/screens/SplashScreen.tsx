import React from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { ScreenGradient } from '@/components/ScreenGradient';
import { Hero } from '@/components/Hero';
import { useTypography } from '@/context/TypographyContext';
import { color, spacing } from '@/theme';

export function SplashScreen() {
  const { type } = useTypography();
  return (
    <View style={styles.container}>
      <ScreenGradient />
      <Hero height={320} />
      <Text style={[type.title, styles.title]}>Molly</Text>
      <Text style={[type.body, styles.subtitle]}>Your VPS, under your control.</Text>
      <ActivityIndicator color={color.accent} style={styles.spinner} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.sm },
  title: { color: color.textPrimary },
  subtitle: { color: color.textSecondary },
  spinner: { marginTop: spacing.xxl },
});
