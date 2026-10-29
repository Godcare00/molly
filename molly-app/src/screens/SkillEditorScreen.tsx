import React, { useEffect, useState } from 'react';
import { View, Text, TextInput, Pressable, StyleSheet, ScrollView, Alert, KeyboardAvoidingView, Platform } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Feather } from '@expo/vector-icons';
import { useNavigation, useRoute } from '@react-navigation/native';
import { skillsApi } from '@/api/skills';
import { useTypography } from '@/context/TypographyContext';
import { Button } from '@/components/Button';
import { LoadingState } from '@/components/LoadingState';
import { ScreenGradient } from '@/components/ScreenGradient';
import { color, radius, shadow, spacing } from '@/theme';

const NAME_RE = /^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$/;

/** Loosely mirrors what typing produces into a valid skill name as you
 * go, rather than only validating after the fact - lowercases, replaces
 * spaces/underscores with hyphens, and strips anything else disallowed.
 * Still validated for real against NAME_RE before saving, since this is
 * a convenience, not a guarantee (e.g. it won't fix a leading hyphen). */
function sanitizeNameInput(raw: string): string {
  return raw
    .toLowerCase()
    .replace(/[\s_]+/g, '-')
    .replace(/[^a-z0-9-]/g, '');
}

export function SkillEditorScreen() {
  const { type } = useTypography();
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const existingName: string | undefined = route.params?.name;
  const isNew = !existingName;

  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState(existingName ?? '');
  const [description, setDescription] = useState('');
  const [body, setBody] = useState('');
  const [files, setFiles] = useState<string[]>([]);
  const [nameError, setNameError] = useState<string | null>(null);

  useEffect(() => {
    if (isNew) return;
    skillsApi
      .get(existingName!)
      .then((skill) => {
        setDescription(skill.description);
        setBody(skill.body);
        setFiles(skill.files);
      })
      .catch((err: any) => {
        Alert.alert('Could not load skill', err?.message ?? 'Something went wrong.', [
          { text: 'OK', onPress: () => navigation.goBack() },
        ]);
      })
      .finally(() => setLoading(false));
  }, [existingName, isNew, navigation]);

  const save = async () => {
    const finalName = isNew ? name.trim() : existingName!;
    if (isNew && !NAME_RE.test(finalName)) {
      setNameError('Lowercase letters, digits, and hyphens only - not starting or ending with a hyphen.');
      return;
    }
    if (!description.trim()) {
      Alert.alert('Description required', "It's how Molly decides when to load this skill.");
      return;
    }
    setSaving(true);
    try {
      await skillsApi.put(finalName, { description: description.trim(), body });
      navigation.goBack();
    } catch (err: any) {
      Alert.alert('Could not save skill', err?.message ?? 'Something went wrong.');
    } finally {
      setSaving(false);
    }
  };

  const confirmDelete = () => {
    Alert.alert('Delete skill', `"${existingName}" and any supporting files in its folder will be removed.`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          try {
            await skillsApi.remove(existingName!);
            navigation.goBack();
          } catch (err: any) {
            Alert.alert('Could not delete skill', err?.message ?? 'Something went wrong.');
          }
        },
      },
    ]);
  };

  return (
    <SafeAreaView style={styles.container}>
      <ScreenGradient />
      <View style={styles.header}>
        <Pressable onPress={() => navigation.goBack()} hitSlop={8}>
          <Feather name="chevron-left" size={24} color={color.textPrimary} />
        </Pressable>
        <Text style={[type.h1, styles.headerTitle]}>{isNew ? 'New skill' : existingName}</Text>
        {!isNew ? (
          <Pressable onPress={confirmDelete} hitSlop={8}>
            <Feather name="trash-2" size={20} color={color.danger} />
          </Pressable>
        ) : (
          <View style={{ width: 22 }} />
        )}
      </View>

      {loading ? (
        <LoadingState />
      ) : (
        <KeyboardAvoidingView
          style={{ flex: 1 }}
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
          keyboardVerticalOffset={Platform.OS === 'ios' ? 16 : 0}
        >
          <ScrollView contentContainerStyle={styles.form} keyboardShouldPersistTaps="handled">
            {isNew ? (
              <View style={styles.field}>
                <Text style={[type.captionMedium, styles.fieldLabel]}>Name</Text>
                <TextInput
                  value={name}
                  onChangeText={(v) => {
                    setNameError(null);
                    setName(sanitizeNameInput(v));
                  }}
                  placeholder="e.g. deploy-rails-app"
                  placeholderTextColor={color.textTertiary}
                  autoCapitalize="none"
                  autoCorrect={false}
                  style={styles.input}
                />
                {nameError ? <Text style={[type.caption, styles.errorText]}>{nameError}</Text> : null}
                <Text style={[type.caption, styles.hint]}>Becomes a folder name on the server - can't be changed later.</Text>
              </View>
            ) : null}

            <View style={styles.field}>
              <Text style={[type.captionMedium, styles.fieldLabel]}>Description</Text>
              <TextInput
                value={description}
                onChangeText={setDescription}
                placeholder={'When should Molly use this? e.g. "Use when deploying or updating the Rails app on this server."'}
                placeholderTextColor={color.textTertiary}
                style={[styles.input, styles.multilineShort]}
                multiline
              />
              <Text style={[type.caption, styles.hint]}>
                Shown to Molly for every task, so it can judge relevance - keep it short and specific.
              </Text>
            </View>

            <View style={styles.field}>
              <Text style={[type.captionMedium, styles.fieldLabel]}>Instructions</Text>
              <TextInput
                value={body}
                onChangeText={setBody}
                placeholder={'Step-by-step instructions, in markdown. Only loaded once Molly decides this skill is relevant.'}
                placeholderTextColor={color.textTertiary}
                style={[styles.input, styles.multilineLong]}
                multiline
                textAlignVertical="top"
              />
            </View>

            {files.length > 0 ? (
              <View style={styles.filesBox}>
                <Text style={[type.captionMedium, styles.fieldLabel]}>Other files in this skill's folder</Text>
                {files.map((f) => (
                  <Text key={f} style={[type.caption, styles.fileRow]}>
                    {f}
                  </Text>
                ))}
                <Text style={[type.caption, styles.hint]}>
                  Manage these directly on the server - the app only edits SKILL.md itself.
                </Text>
              </View>
            ) : null}

            <Button label="Save skill" onPress={save} loading={saving} style={{ marginTop: spacing.md }} />
          </ScrollView>
        </KeyboardAvoidingView>
      )}
    </SafeAreaView>
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
  headerTitle: { color: color.textPrimary, flex: 1, textAlign: 'center' },
  form: { paddingHorizontal: spacing.lg, paddingBottom: spacing.xxl, gap: spacing.lg },
  field: { gap: spacing.xs },
  fieldLabel: { color: color.textSecondary },
  input: {
    backgroundColor: color.surface,
    borderRadius: radius.lg,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    color: color.textPrimary,
    ...shadow.soft,
  },
  multilineShort: { minHeight: 64 },
  multilineLong: { minHeight: 220 },
  hint: { color: color.textTertiary },
  errorText: { color: color.danger },
  filesBox: {
    backgroundColor: color.surfaceHigh,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: spacing.xs,
  },
  fileRow: { color: color.textSecondary, fontFamily: 'monospace' },
});
