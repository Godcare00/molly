import React, { useMemo } from 'react';
import { View, Text, Pressable, SectionList, StyleSheet, RefreshControl } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Feather } from '@expo/vector-icons';
import { useNavigation } from '@react-navigation/native';
import { useApprovals } from '@/hooks/useApprovals';
import { useTypography } from '@/context/TypographyContext';
import { ActivityRow } from '@/components/ActivityRow';
import { EmptyState } from '@/components/EmptyState';
import { LoadingState } from '@/components/LoadingState';
import { ErrorState } from '@/components/ErrorState';
import { ScreenGradient } from '@/components/ScreenGradient';
import { color, spacing } from '@/theme';
import type { ActivityItem, Approval } from '@/types/api';

function toActivityItem(approval: Approval): ActivityItem {
  const status: ActivityItem['status'] =
    approval.status === 'approved'
      ? 'complete'
      : approval.status === 'rejected'
      ? 'error'
      : approval.status === 'pending'
      ? 'pending'
      : 'complete';
  return {
    id: approval.id,
    title: approval.summary ?? approval.command,
    subtitle: approval.status === 'pending' ? 'Awaiting approval' : statusLabel(approval.status),
    status,
    timestamp: approval.resolved_at ?? approval.created_at,
  };
}

function statusLabel(status: Approval['status']) {
  switch (status) {
    case 'approved':
      return 'Approved';
    case 'rejected':
      return 'Approval rejected';
    case 'corrected':
      return 'Correction sent';
    default:
      return status;
  }
}

function dayLabel(iso: string) {
  const d = new Date(iso);
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === now.toDateString()) return 'Today';
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return d.toLocaleDateString([], { month: 'long', day: 'numeric' });
}

export function ActivityScreen() {
  const { type } = useTypography();
  const navigation = useNavigation<any>();
  const { approvals, loading, error, reload } = useApprovals();

  const sections = useMemo(() => {
    const items = approvals
      .slice()
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
      .map(toActivityItem);
    const groups = new Map<string, ActivityItem[]>();
    items.forEach((item) => {
      const key = dayLabel(item.timestamp);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(item);
    });
    return Array.from(groups.entries()).map(([title, data]) => ({ title, data }));
  }, [approvals]);

  return (
    <SafeAreaView style={styles.container}>
      <ScreenGradient />
      <View style={styles.header}>
        <Pressable onPress={() => navigation.goBack()} hitSlop={8}>
          <Feather name="chevron-left" size={24} color={color.textPrimary} />
        </Pressable>
        <Text style={[type.h1, styles.title]}>Activity</Text>
        <View style={{ width: 24 }} />
      </View>

      {loading ? (
        <LoadingState />
      ) : error && approvals.length === 0 ? (
        <ErrorState message={error} onRetry={reload} />
      ) : sections.length === 0 ? (
        <EmptyState title="No activity yet" message="Tool runs and approvals will show up here as Molly works." />
      ) : (
        <SectionList
          sections={sections}
          keyExtractor={(item) => item.id}
          contentContainerStyle={styles.listContent}
          refreshControl={<RefreshControl refreshing={false} onRefresh={reload} tintColor={color.accent} />}
          renderSectionHeader={({ section: { title } }) => (
            <Text style={[type.captionMedium, styles.sectionHeader]}>{title}</Text>
          )}
          renderItem={({ item }) => <ActivityRow item={item} />}
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
  title: { color: color.textPrimary },
  listContent: { paddingHorizontal: spacing.lg, paddingBottom: spacing.xxl },
  sectionHeader: { color: color.textTertiary, marginTop: spacing.md, marginBottom: spacing.xs },
});
