import React from 'react';
import { View, Text, StyleSheet, ActivityIndicator, Pressable } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Feather } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import { useAuth } from '@/context/AuthContext';
import { useTypography } from '@/context/TypographyContext';
import { Button } from '@/components/Button';
import { Hero } from '@/components/Hero';
import { ScreenGradient } from '@/components/ScreenGradient';
import { color, gradient, radius, shadow, spacing } from '@/theme';

const FEATURES: { icon: React.ComponentProps<typeof Feather>['name']; label: string }[] = [
  { icon: 'message-circle', label: 'Chat with your server' },
  { icon: 'tool', label: 'Deploy, debug, and manage' },
  { icon: 'lock', label: 'Powerful, safe, and intelligent' },
];

export function PairingScreen() {
  const { type } = useTypography();
  const { status, pair, pairingError, pairingCode, cancelPairing } = useAuth();
  const pairing = status === 'pairing';

  if (pairing && pairingCode) {
    return (
      <SafeAreaView style={styles.container}>
        <ScreenGradient />
        <View style={styles.codeScreen}>
          <Text style={[type.body, styles.subtitle]}>Enter this code on your server</Text>
          <View style={styles.codeBox}>
            <Text style={styles.code}>{formatCode(pairingCode)}</Text>
          </View>
          <Text style={[type.caption, styles.hint]}>
            Run{' '}
            <Text style={styles.mono}>molly connect</Text>
            {' '}on your server, open the link it prints, and enter this code there to approve this device.
          </Text>
          <View style={styles.waitingRow}>
            <ActivityIndicator color={color.accent} />
            <Text style={[type.caption, styles.hint, styles.waitingLabel]}>Waiting for approval…</Text>
          </View>
        </View>
        <View style={styles.footer}>
          <Button label="Cancel" onPress={cancelPairing} variant="secondary" />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScreenGradient />
      <Hero height={300} />

      <View style={styles.content}>
        <Text style={[type.title, styles.title]}>Molly</Text>
        <Text style={[type.body, styles.subtitle]}>Your VPS, under your control.</Text>

        <View style={styles.features}>
          {FEATURES.map((f) => (
            <View key={f.label} style={styles.featureRow}>
              <View style={styles.featureIconWrap}>
                <LinearGradient
                  colors={gradient.accentSoft}
                  style={StyleSheet.absoluteFill}
                  start={{ x: 0, y: 0 }}
                  end={{ x: 1, y: 1 }}
                />
                <Feather name={f.icon} size={16} color={color.accent} />
              </View>
              <Text style={[type.body, styles.featureLabel]}>{f.label}</Text>
            </View>
          ))}
        </View>
      </View>

      <View style={styles.footer}>
        {pairingError ? <Text style={[type.caption, styles.error]}>{pairingError}</Text> : null}
        <Button label="Get Started" onPress={pair} loading={pairing} variant="white" />
        <Pressable onPress={pair} hitSlop={8} style={styles.signInRow}>
          <Text style={[type.caption, styles.hint]}>
            Already have an account? <Text style={styles.signInLink}>Sign In</Text>
          </Text>
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

/** "ABCD123" -> "ABC-D123", purely for on-screen readability. */
function formatCode(code: string): string {
  return code.length > 3 ? `${code.slice(0, 3)}-${code.slice(3)}` : code;
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  content: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: spacing.xxl, gap: spacing.lg },
  title: { color: color.textPrimary, textAlign: 'center' },
  subtitle: { color: color.textSecondary, marginBottom: spacing.md, textAlign: 'center' },
  features: { gap: spacing.md, alignSelf: 'stretch' },
  featureRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  featureIconWrap: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  featureLabel: { color: color.textPrimary },
  footer: { padding: spacing.xxl, paddingTop: 0, gap: spacing.md },
  signInRow: { alignItems: 'center', paddingTop: spacing.xs },
  signInLink: { color: color.textPrimary, fontWeight: '600' },
  error: { color: color.danger, textAlign: 'center' },
  hint: { color: color.textTertiary, textAlign: 'center' },
  codeScreen: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: spacing.xxl, gap: spacing.lg },
  codeBox: {
    backgroundColor: color.bgElevated,
    borderRadius: radius.lg,
    paddingVertical: spacing.lg,
    paddingHorizontal: spacing.xxl,
    ...shadow.card,
  },
  code: { fontSize: 34, fontWeight: '700', letterSpacing: 4, color: color.textPrimary },
  mono: { fontFamily: 'Menlo, Courier', color: color.textPrimary },
  waitingRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginTop: spacing.md },
  waitingLabel: { textAlign: 'left' },
});
