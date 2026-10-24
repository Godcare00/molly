import React, { useState } from 'react';
import { View, Text, StyleSheet, TextInput } from 'react-native';
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
  const { status, pair, pairingError, cancelPairing } = useAuth();
  const [code, setCode] = useState('');

  const pairing = status === 'pairing';
  const clean = code.replace(/[^0-9a-z]/gi, '');
  const canSubmit = clean.length >= 6 && !pairing;

  const submit = () => {
    if (canSubmit) pair(clean);
  };

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScreenGradient />
      <Hero height={260} />

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
        <Text style={[type.caption, styles.hint]}>
          Run <Text style={styles.mono}>molly connect</Text> on your server, then enter the code it prints.
        </Text>

        <TextInput
          value={code}
          onChangeText={setCode}
          placeholder="PAIRING CODE"
          placeholderTextColor={color.textTertiary}
          autoCapitalize="characters"
          autoCorrect={false}
          autoComplete="off"
          maxLength={8}
          editable={!pairing}
          returnKeyType="go"
          onSubmitEditing={submit}
          style={[type.body, styles.input]}
        />

        {pairingError ? <Text style={[type.caption, styles.error]}>{pairingError}</Text> : null}

        <Button
          label="Connect"
          onPress={submit}
          loading={pairing}
          disabled={clean.length < 6}
          variant="white"
        />
        {pairing ? <Button label="Cancel" onPress={cancelPairing} variant="secondary" /> : null}
      </View>
    </SafeAreaView>
  );
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
  hint: { color: color.textTertiary, textAlign: 'center' },
  mono: { fontFamily: 'Menlo, Courier', color: color.textPrimary },
  error: { color: color.danger, textAlign: 'center' },
  input: {
    backgroundColor: color.bgElevated,
    borderRadius: radius.lg,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    textAlign: 'center',
    letterSpacing: 4,
    fontSize: 20,
    fontWeight: '600',
    color: color.textPrimary,
    ...shadow.card,
  },
});
