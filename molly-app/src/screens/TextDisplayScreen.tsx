import React from 'react';
import { View, Text, Pressable, ScrollView, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { Feather } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import { LiquidSegmented } from '@/components/LiquidSegmented';
import { ScreenGradient } from '@/components/ScreenGradient';
import { useTypography } from '@/context/TypographyContext';
import {
  color,
  gradient,
  radius,
  spacing,
  FONT_CHOICES,
  TYPE_SIZE_CHOICES,
  TYPE_WEIGHT_CHOICES,
} from '@/theme';

export function TextDisplayScreen() {
  const navigation = useNavigation<any>();
  const { type, fontChoice, sizeChoice, weightChoice, setFontChoice, setSizeChoice, setWeightChoice, resetToDefaults } =
    useTypography();

  return (
    <SafeAreaView style={styles.container}>
      <ScreenGradient />
      <View style={styles.header}>
        <Pressable onPress={() => navigation.goBack()} hitSlop={12} style={styles.backBtn}>
          <Feather name="chevron-left" size={22} color={color.textPrimary} />
        </Pressable>
        <Text style={[type.title, styles.title]}>Text & Display</Text>
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.previewCard}>
          <LinearGradient
            colors={gradient.surface}
            style={StyleSheet.absoluteFill}
            start={{ x: 0, y: 0 }}
            end={{ x: 0, y: 1 }}
          />
          <Text style={[type.h1, styles.previewHeading]}>Molly</Text>
          <Text style={[type.body, styles.previewBody]}>
            This is what your messages and menus will look like with these settings.
          </Text>
          <Text style={[type.caption, styles.previewCaption]}>Last updated just now</Text>
        </View>

        <Section title="Font">
          {FONT_CHOICES.map((opt) => (
            <OptionRow
              key={opt.id}
              label={opt.label}
              sublabel={opt.sample}
              selected={fontChoice === opt.id}
              onPress={() => setFontChoice(opt.id)}
            />
          ))}
        </Section>

        <Section title="Text size">
          <LiquidSegmented options={TYPE_SIZE_CHOICES.map((o) => ({ id: o.id, label: o.label }))} value={sizeChoice} onChange={setSizeChoice} />
        </Section>

        <Section title="Weight">
          <LiquidSegmented options={TYPE_WEIGHT_CHOICES.map((o) => ({ id: o.id, label: o.label }))} value={weightChoice} onChange={setWeightChoice} />
        </Section>

        <Pressable style={styles.resetRow} onPress={resetToDefaults}>
          <Text style={[type.bodyMedium, styles.resetText]}>Reset to defaults</Text>
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const { type } = useTypography();
  return (
    <View style={styles.section}>
      <Text style={[type.captionMedium, styles.sectionTitle]}>{title.toUpperCase()}</Text>
      <View style={styles.group}>
        <LinearGradient
          colors={gradient.surface}
          style={StyleSheet.absoluteFill}
          start={{ x: 0, y: 0 }}
          end={{ x: 0, y: 1 }}
        />
        {children}
      </View>
    </View>
  );
}

function OptionRow({
  label,
  sublabel,
  selected,
  onPress,
}: {
  label: string;
  sublabel?: string;
  selected: boolean;
  onPress: () => void;
}) {
  const { type } = useTypography();
  return (
    <Pressable onPress={onPress} style={styles.row}>
      <View style={{ flex: 1 }}>
        <Text style={[type.body, styles.rowLabel]}>{label}</Text>
        {sublabel ? (
          <Text style={[type.caption, styles.rowSublabel]} numberOfLines={1}>
            {sublabel}
          </Text>
        ) : null}
      </View>
      {selected ? <Feather name="check" size={18} color={color.accent} /> : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.lg,
  },
  backBtn: { padding: 2 },
  title: { color: color.textPrimary },
  scroll: { paddingHorizontal: spacing.lg, paddingBottom: spacing.xxl, gap: spacing.lg },
  previewCard: {
    borderRadius: radius.lg,
    padding: spacing.lg,
    overflow: 'hidden',
    gap: spacing.xs,
  },
  previewHeading: { color: color.textPrimary },
  previewBody: { color: color.textSecondary },
  previewCaption: { color: color.textTertiary, marginTop: spacing.xs },
  section: { gap: spacing.sm },
  sectionTitle: { color: color.textTertiary, marginLeft: spacing.xs },
  group: { borderRadius: radius.lg, overflow: 'hidden', gap: 1 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    gap: spacing.md,
  },
  rowLabel: { color: color.textPrimary },
  rowSublabel: { color: color.textTertiary, marginTop: 2 },
  resetRow: {
    alignItems: 'center',
    paddingVertical: spacing.md,
  },
  resetText: { color: color.accent },
});
