import React, { useEffect, useRef } from 'react';
import { View, Text, Pressable, StyleSheet, Modal, Animated, ActivityIndicator, ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Feather } from '@expo/vector-icons';
import { useTypography } from '@/context/TypographyContext';
import { color, radius, shadow, spacing } from '@/theme';
import type { AvailableModel, ReasoningEffort } from '@/types/api';

const REASONING_OPTIONS: { value: ReasoningEffort; label: string }[] = [
  { value: 'off', label: 'Off' },
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
];

/** Picker for the chat input's model/reasoning pill. `models` comes from
 * GET /settings/available-models (the configured provider chain), fetched
 * once by the caller (ChatScreen) rather than here, since the caller also
 * needs it to render the pill's label. "Automatic" (null) means the
 * primary chain with its normal fallbacks, same as not pinning a model at
 * all. Reasoning effort is independent of which model is picked; the
 * backend only actually applies it if the chosen model supports it (see
 * app/agent/executor.py). */
export function ModelReasoningSheet({
  visible,
  onClose,
  models,
  modelsLoading,
  selectedModel,
  selectedProvider,
  reasoningEffort,
  onSelectModel,
  onSelectReasoning,
}: {
  visible: boolean;
  onClose: () => void;
  models: AvailableModel[];
  modelsLoading: boolean;
  selectedModel: string | null;
  selectedProvider?: string | null;
  reasoningEffort: ReasoningEffort;
  onSelectModel: (model: string | null, provider: string | null) => void;
  onSelectReasoning: (effort: ReasoningEffort) => void;
}) {
  const { type } = useTypography();
  const translateY = useRef(new Animated.Value(40)).current;
  const backdropOpacity = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.timing(translateY, { toValue: visible ? 0 : 40, duration: 220, useNativeDriver: true }),
      Animated.timing(backdropOpacity, { toValue: visible ? 1 : 0, duration: 200, useNativeDriver: true }),
    ]).start();
  }, [visible, translateY, backdropOpacity]);

  return (
    <Modal visible={visible} transparent animationType="none" onRequestClose={onClose} statusBarTranslucent>
      <View style={styles.fill}>
        <Animated.View style={[styles.backdrop, { opacity: backdropOpacity }]}>
          <Pressable style={styles.fill} onPress={onClose} />
        </Animated.View>

        <Animated.View style={[styles.sheet, { transform: [{ translateY }] }]}>
          <SafeAreaView edges={['bottom']}>
            <View style={styles.handle} />
            <Text style={[type.h1, styles.title]}>Model & reasoning</Text>

            <ScrollView keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>
              <Text style={[type.captionMedium, styles.sectionLabel]}>Model</Text>
              {modelsLoading ? (
                <ActivityIndicator color={color.textTertiary} style={{ marginVertical: spacing.md }} />
              ) : (
                <>
                  <ModelRow
                    label="Automatic"
                    subtitle="Primary provider, with automatic fallback"
                    selected={!selectedModel}
                    onPress={() => onSelectModel(null, null)}
                  />
                  {models.map((m) => (
                    <ModelRow
                      key={`${m.provider}:${m.model}`}
                      label={m.name}
                      subtitle={m.model}
                      selected={selectedModel === m.model && (!selectedProvider || selectedProvider === m.provider)}
                      onPress={() => onSelectModel(m.model, m.provider)}
                    />
                  ))}
                </>
              )}

              <Text style={[type.captionMedium, styles.sectionLabel]}>Reasoning</Text>
              <View style={styles.reasoningRow}>
                {REASONING_OPTIONS.map((opt) => {
                  const active = reasoningEffort === opt.value;
                  return (
                    <Pressable
                      key={opt.value}
                      onPress={() => onSelectReasoning(opt.value)}
                      style={[styles.reasoningChip, active && styles.reasoningChipActive]}
                    >
                      <Text style={[type.captionMedium, active ? styles.reasoningChipTextActive : styles.reasoningChipText]}>
                        {opt.label}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
              <Text style={[type.caption, styles.hint]}>
                Only applies if the picked model supports reasoning.
              </Text>
            </ScrollView>

            <Pressable style={styles.doneButton} onPress={onClose}>
              <Text style={[type.bodyMedium, styles.doneButtonText]}>Done</Text>
            </Pressable>
          </SafeAreaView>
        </Animated.View>
      </View>
    </Modal>
  );
}

function ModelRow({
  label,
  subtitle,
  selected,
  onPress,
}: {
  label: string;
  subtitle: string;
  selected: boolean;
  onPress: () => void;
}) {
  const { type } = useTypography();
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.modelRow, pressed && styles.modelRowPressed]}>
      <View style={styles.modelRowText}>
        <Text style={[type.bodyMedium, styles.modelRowLabel]}>{label}</Text>
        <Text style={[type.caption, styles.modelRowSubtitle]}>{subtitle}</Text>
      </View>
      {selected ? <Feather name="check" size={18} color={color.accent} /> : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  backdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: color.overlay,
  },
  sheet: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: color.bg,
    borderTopLeftRadius: radius.xl,
    borderTopRightRadius: radius.xl,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.lg,
    maxHeight: '80%',
    ...shadow.drawer,
  },
  handle: {
    alignSelf: 'center',
    width: 36,
    height: 4,
    borderRadius: radius.pill,
    backgroundColor: color.borderStrong,
    marginTop: spacing.sm,
    marginBottom: spacing.md,
  },
  title: { color: color.textPrimary, marginBottom: spacing.sm },
  sectionLabel: { color: color.textTertiary, marginTop: spacing.md, marginBottom: spacing.xs, textTransform: 'uppercase', letterSpacing: 0.5 },
  modelRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: color.bgElevated,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.xs,
    ...shadow.soft,
  },
  modelRowPressed: { opacity: 0.85 },
  modelRowText: { flex: 1, marginRight: spacing.sm },
  modelRowLabel: { color: color.textPrimary },
  modelRowSubtitle: { color: color.textTertiary, marginTop: 2 },
  reasoningRow: { flexDirection: 'row', gap: spacing.xs },
  reasoningChip: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: spacing.sm,
    borderRadius: radius.pill,
    backgroundColor: color.bgElevated,
  },
  reasoningChipActive: { backgroundColor: color.accent },
  reasoningChipText: { color: color.textSecondary },
  reasoningChipTextActive: { color: '#FFFFFF' },
  hint: { color: color.textTertiary, marginTop: spacing.sm },
  doneButton: {
    alignItems: 'center',
    marginTop: spacing.lg,
    paddingVertical: spacing.md,
    borderRadius: radius.lg,
    backgroundColor: color.textPrimary,
  },
  doneButtonText: { color: color.bg },
});
