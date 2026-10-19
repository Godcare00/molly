import React, { useEffect, useState } from 'react';
import { View, Text, TextInput, ScrollView, StyleSheet, Pressable, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Feather } from '@expo/vector-icons';
import { useNavigation } from '@react-navigation/native';
import { settingsApi } from '@/api/settings';
import { useTypography } from '@/context/TypographyContext';
import { Button } from '@/components/Button';
import { LoadingState } from '@/components/LoadingState';
import { ScreenGradient } from '@/components/ScreenGradient';
import { color, radius, shadow, spacing } from '@/theme';
import type { ProviderChainEntry, RetrySettings } from '@/types/api';

const EMPTY_ENTRY: ProviderChainEntry = {
  name: '',
  provider: '',
  base_url: '',
  api_key: '',
  model: '',
  temperature: 0.1,
  max_tokens: 4096,
};

const DEFAULT_RETRY: RetrySettings = {
  max_retries: 2,
  retry_base_delay_seconds: 1.0,
  retry_max_delay_seconds: 20.0,
};

export function ProviderSettingsScreen() {
  const { type } = useTypography();
  const navigation = useNavigation<any>();
  const [providers, setProviders] = useState<ProviderChainEntry[]>([]);
  const [retry, setRetry] = useState<RetrySettings>(DEFAULT_RETRY);
  const [expanded, setExpanded] = useState<number | null>(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testingIndex, setTestingIndex] = useState<number | null>(null);

  useEffect(() => {
    settingsApi
      .getProviderChain()
      .then((data) => {
        setProviders(data.providers.length ? data.providers : [EMPTY_ENTRY]);
        setRetry(data.retry);
      })
      .catch(() => setProviders([EMPTY_ENTRY]))
      .finally(() => setLoading(false));
  }, []);

  const updateEntry = (index: number, patch: Partial<ProviderChainEntry>) =>
    setProviders((prev) => prev.map((p, i) => (i === index ? { ...p, ...patch } : p)));

  const addProvider = () => {
    setProviders((prev) => [...prev, { ...EMPTY_ENTRY }]);
    setExpanded(providers.length);
  };

  const removeProvider = (index: number) => {
    if (providers.length <= 1) return;
    setProviders((prev) => prev.filter((_, i) => i !== index));
    setExpanded(null);
  };

  const moveProvider = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= providers.length) return;
    setProviders((prev) => {
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
    setExpanded(target);
  };

  const testProvider = async (index: number) => {
    const entry = providers[index];
    setTestingIndex(index);
    try {
      const res = await settingsApi.testProvider({
        provider: entry.provider,
        base_url: entry.base_url,
        api_key: entry.api_key,
        model: entry.model,
        temperature: entry.temperature,
        max_tokens: entry.max_tokens,
      });
      Alert.alert(res.ok ? 'Connection OK' : 'Connection failed', res.message ?? '');
    } catch (err: any) {
      Alert.alert('Connection failed', err?.message ?? 'Something went wrong.');
    } finally {
      setTestingIndex(null);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      const result = await settingsApi.updateProviderChain({ providers, retry });
      setProviders(result.providers);
      setRetry(result.retry);
      Alert.alert('Saved', result.message ?? 'Provider chain updated.');
    } catch (err: any) {
      Alert.alert('Could not save', err?.message ?? 'Something went wrong.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <LoadingState />;

  return (
    <SafeAreaView style={styles.container}>
      <ScreenGradient />
      <View style={styles.header}>
        <Pressable onPress={() => navigation.goBack()} hitSlop={8}>
          <Feather name="chevron-left" size={24} color={color.textPrimary} />
        </Pressable>
        <Text style={[type.h1, styles.headerTitle]}>LLM providers</Text>
        <View style={{ width: 24 }} />
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={[type.caption, styles.hint]}>
          The first provider is tried for every request. If it fails after its retries, Molly
          automatically moves to the next one in the list.
        </Text>

        {providers.map((entry, index) => (
          <ProviderCard
            key={index}
            entry={entry}
            index={index}
            isFirst={index === 0}
            isLast={index === providers.length - 1}
            canRemove={providers.length > 1}
            expanded={expanded === index}
            testing={testingIndex === index}
            onToggle={() => setExpanded(expanded === index ? null : index)}
            onChange={(patch) => updateEntry(index, patch)}
            onMoveUp={() => moveProvider(index, -1)}
            onMoveDown={() => moveProvider(index, 1)}
            onRemove={() => removeProvider(index)}
            onTest={() => testProvider(index)}
          />
        ))}

        <Pressable style={styles.addRow} onPress={addProvider}>
          <Feather name="plus" size={18} color={color.accent} />
          <Text style={[type.bodyMedium, styles.addLabel]}>Add fallback provider</Text>
        </Pressable>

        <View style={styles.retrySection}>
          <Text style={[type.h2, styles.sectionTitle]}>Retry behavior</Text>
          <Text style={[type.caption, styles.hint]}>
            Applied to each provider before Molly moves on to the next one.
          </Text>
          <View style={styles.retryRow}>
            <RetryField
              label="Max retries"
              value={String(retry.max_retries)}
              onChangeText={(v) => setRetry((prev) => ({ ...prev, max_retries: Math.max(0, Number(v) || 0) }))}
            />
            <RetryField
              label="Base delay (s)"
              value={String(retry.retry_base_delay_seconds)}
              onChangeText={(v) =>
                setRetry((prev) => ({ ...prev, retry_base_delay_seconds: Math.max(0, Number(v) || 0) }))
              }
            />
            <RetryField
              label="Max delay (s)"
              value={String(retry.retry_max_delay_seconds)}
              onChangeText={(v) =>
                setRetry((prev) => ({ ...prev, retry_max_delay_seconds: Math.max(0, Number(v) || 0) }))
              }
            />
          </View>
        </View>

        <Button label="Save" onPress={save} loading={saving} style={{ marginTop: spacing.lg }} />
      </ScrollView>
    </SafeAreaView>
  );
}

function ProviderCard({
  entry,
  index,
  isFirst,
  isLast,
  canRemove,
  expanded,
  testing,
  onToggle,
  onChange,
  onMoveUp,
  onMoveDown,
  onRemove,
  onTest,
}: {
  entry: ProviderChainEntry;
  index: number;
  isFirst: boolean;
  isLast: boolean;
  canRemove: boolean;
  expanded: boolean;
  testing: boolean;
  onToggle: () => void;
  onChange: (patch: Partial<ProviderChainEntry>) => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onRemove: () => void;
  onTest: () => void;
}) {
  const title = entry.name?.trim() || entry.model?.trim() || entry.provider?.trim() || `Provider ${index + 1}`;
  const { type } = useTypography();

  return (
    <View style={styles.card}>
      <Pressable style={styles.cardHeader} onPress={onToggle}>
        <View style={styles.orderBadge}>
          <Text style={[type.captionMedium, styles.orderBadgeText]}>{index + 1}</Text>
        </View>
        <View style={styles.cardHeaderInfo}>
          <Text style={[type.bodyMedium, styles.cardTitle]} numberOfLines={1}>
            {title}
          </Text>
          <Text style={[type.caption, styles.cardSubtitle]} numberOfLines={1}>
            {isFirst ? 'Primary' : 'Fallback'} · {entry.model || 'no model set'}
          </Text>
        </View>
        <Feather name={expanded ? 'chevron-up' : 'chevron-down'} size={20} color={color.textTertiary} />
      </Pressable>

      {expanded && (
        <View style={styles.cardBody}>
          <Field label="Name (optional)" value={entry.name ?? ''} onChangeText={(v) => onChange({ name: v })} placeholder="e.g. OpenAI (main)" />
          <Field label="Provider" value={entry.provider} onChangeText={(v) => onChange({ provider: v })} placeholder="anthropic" autoCapitalize="none" />
          <Field label="Base URL" value={entry.base_url} onChangeText={(v) => onChange({ base_url: v })} placeholder="https://api.anthropic.com" autoCapitalize="none" />
          <Field label="API key" value={entry.api_key} onChangeText={(v) => onChange({ api_key: v })} placeholder="sk-…" secureTextEntry />
          <Field label="Model" value={entry.model} onChangeText={(v) => onChange({ model: v })} placeholder="claude-sonnet-4-6" autoCapitalize="none" />
          <Field
            label="Max tokens"
            value={String(entry.max_tokens ?? '')}
            onChangeText={(v) => onChange({ max_tokens: Number(v) || 0 })}
            keyboardType="number-pad"
          />

          <View style={styles.cardActions}>
            <Pressable style={styles.iconButton} onPress={onMoveUp} disabled={isFirst} hitSlop={8}>
              <Feather name="arrow-up" size={18} color={isFirst ? color.textTertiary : color.textSecondary} />
            </Pressable>
            <Pressable style={styles.iconButton} onPress={onMoveDown} disabled={isLast} hitSlop={8}>
              <Feather name="arrow-down" size={18} color={isLast ? color.textTertiary : color.textSecondary} />
            </Pressable>
            <View style={{ flex: 1 }} />
            <Pressable style={styles.iconButton} onPress={onRemove} disabled={!canRemove} hitSlop={8}>
              <Feather name="trash-2" size={18} color={canRemove ? color.danger : color.textTertiary} />
            </Pressable>
          </View>

          <Button label="Test connection" variant="secondary" onPress={onTest} loading={testing} />
        </View>
      )}
    </View>
  );
}

function Field({
  label,
  ...inputProps
}: { label: string } & React.ComponentProps<typeof TextInput>) {
  const { type } = useTypography();
  return (
    <View style={styles.field}>
      <Text style={[type.captionMedium, styles.fieldLabel]}>{label}</Text>
      <TextInput
        placeholderTextColor={color.textTertiary}
        style={[styles.input, { fontFamily: type.body.fontFamily, fontSize: type.body.fontSize }]}
        cursorColor={color.accent}
        selectionColor={color.accent}
        {...inputProps}
      />
    </View>
  );
}

function RetryField({
  label,
  value,
  onChangeText,
}: {
  label: string;
  value: string;
  onChangeText: (v: string) => void;
}) {
  const { type } = useTypography();
  return (
    <View style={styles.retryField}>
      <Text style={[type.captionMedium, styles.fieldLabel]}>{label}</Text>
      <TextInput
        style={[styles.input, { fontFamily: type.body.fontFamily, fontSize: type.body.fontSize }]}
        value={value}
        onChangeText={onChangeText}
        keyboardType="decimal-pad"
        cursorColor={color.accent}
        selectionColor={color.accent}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  headerTitle: { color: color.textPrimary },
  scroll: { paddingHorizontal: spacing.lg, paddingBottom: spacing.xxl, gap: spacing.md },
  hint: { color: color.textTertiary },

  card: {
    backgroundColor: color.surface,
    borderRadius: radius.lg,
    ...shadow.card,
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    padding: spacing.md,
  },
  orderBadge: {
    width: 24,
    height: 24,
    borderRadius: radius.pill,
    backgroundColor: color.accentSoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  orderBadgeText: { color: color.accent },
  cardHeaderInfo: { flex: 1, gap: 2 },
  cardTitle: { color: color.textPrimary },
  cardSubtitle: { color: color.textTertiary },
  cardBody: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.md,
    gap: spacing.md,
    paddingTop: spacing.sm,
  },
  cardActions: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  iconButton: {
    width: 36,
    height: 36,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: color.surfaceHigh,
  },

  addRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    paddingVertical: spacing.md,
    borderRadius: radius.pill,
    backgroundColor: color.surfaceHigh,
  },
  addLabel: { color: color.accent },

  retrySection: { gap: spacing.xs, marginTop: spacing.sm },
  sectionTitle: { color: color.textPrimary },
  retryRow: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.xs },
  retryField: { flex: 1, gap: spacing.xs },

  field: { gap: spacing.xs },
  fieldLabel: { color: color.textTertiary },
  input: {
    backgroundColor: color.surfaceHigh,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    color: color.textPrimary,
  },
});
