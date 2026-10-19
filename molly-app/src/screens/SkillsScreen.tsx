import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, FlatList, Pressable, StyleSheet, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Feather } from '@expo/vector-icons';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { skillsApi } from '@/api/skills';
import { useTypography } from '@/context/TypographyContext';
import { LoadingState } from '@/components/LoadingState';
import { ErrorState } from '@/components/ErrorState';
import { EmptyState } from '@/components/EmptyState';
import { ScreenGradient } from '@/components/ScreenGradient';
import { color, radius, shadow, spacing } from '@/theme';
import type { SkillInfo } from '@/types/api';

export function SkillsScreen() {
  const { type } = useTypography();
  const navigation = useNavigation<any>();
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await skillsApi.list();
      setSkills(res.skills);
    } catch (err: any) {
      setError(err?.message ?? 'Could not load skills.');
    } finally {
      setLoading(false);
    }
  }, []);

  // Refetch every time this screen comes back into focus (e.g. returning
  // from the editor after a save/delete), not just on first mount.
  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const confirmDelete = (skill: SkillInfo) => {
    Alert.alert('Delete skill', `"${skill.name}" and any supporting files in its folder will be removed.`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          try {
            await skillsApi.remove(skill.name);
            load();
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
        <Text style={[type.h1, styles.headerTitle]}>Skills</Text>
        <Pressable onPress={() => navigation.navigate('SkillEditor')} hitSlop={8}>
          <Feather name="plus" size={22} color={color.textPrimary} />
        </Pressable>
      </View>

      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : skills.length === 0 ? (
        <EmptyState
          title="No skills yet"
          message="Skills are reusable instructions Molly loads on demand for tasks you do often - deploying a particular stack, following a house style, a recurring maintenance procedure."
          action={
            <Pressable style={styles.addButton} onPress={() => navigation.navigate('SkillEditor')}>
              <Text style={[type.bodyMedium, styles.addButtonText]}>Add a skill</Text>
            </Pressable>
          }
        />
      ) : (
        <FlatList
          data={skills}
          keyExtractor={(s) => s.name}
          contentContainerStyle={styles.listContent}
          renderItem={({ item }) => (
            <Pressable
              style={({ pressed }) => [styles.card, pressed && styles.cardPressed]}
              onPress={() => navigation.navigate('SkillEditor', { name: item.name })}
            >
              <View style={{ flex: 1 }}>
                <Text style={[type.bodyMedium, styles.skillName]}>{item.name}</Text>
                <Text style={[type.caption, styles.skillDescription]} numberOfLines={2}>
                  {item.description || 'No description'}
                </Text>
              </View>
              <Pressable onPress={() => confirmDelete(item)} hitSlop={8} style={styles.deleteButton}>
                <Feather name="trash-2" size={16} color={color.textTertiary} />
              </Pressable>
            </Pressable>
          )}
        />
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
  headerTitle: { color: color.textPrimary },
  listContent: { paddingHorizontal: spacing.lg, paddingBottom: spacing.xxl },
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: color.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    marginBottom: spacing.md,
    ...shadow.card,
  },
  cardPressed: { opacity: 0.85 },
  skillName: { color: color.textPrimary },
  skillDescription: { color: color.textTertiary, marginTop: 2 },
  deleteButton: { padding: spacing.xs },
  addButton: {
    marginTop: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: radius.pill,
    backgroundColor: color.textPrimary,
  },
  addButtonText: { color: color.bg },
});
