import React, { useEffect, useState } from 'react';
import { View, Text, ScrollView, StyleSheet, Pressable } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Feather } from '@expo/vector-icons';
import { useNavigation, useRoute } from '@react-navigation/native';
import { projectsApi } from '@/api/projects';
import { useTypography } from '@/context/TypographyContext';
import { useConversations } from '@/context/ConversationsContext';
import { LoadingState } from '@/components/LoadingState';
import { ErrorState } from '@/components/ErrorState';
import { StatusDot } from '@/components/StatusDot';
import { Button } from '@/components/Button';
import { ScreenGradient } from '@/components/ScreenGradient';
import { LinearGradient } from 'expo-linear-gradient';
import { color, gradient, radius, shadow, spacing } from '@/theme';
import type { Project } from '@/types/api';

export function ProjectDetailScreen() {
  const { type } = useTypography();
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const { projectId } = route.params as { projectId: string };
  const { createConversation } = useConversations();

  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [startingChat, setStartingChat] = useState(false);

  useEffect(() => {
    projectsApi
      .get(projectId)
      .then(setProject)
      .catch((err) => setError(err?.message ?? 'Could not load this project.'))
      .finally(() => setLoading(false));
  }, [projectId]);

  const askAboutProject = async () => {
    if (!project) return;
    setStartingChat(true);
    try {
      await createConversation(`${project.name}`, project.id);
      navigation.navigate('Chat', { screen: 'ChatHome' });
    } finally {
      setStartingChat(false);
    }
  };

  if (loading) return <LoadingState />;
  if (error || !project) return <ErrorState message={error ?? 'Project not found.'} />;

  return (
    <SafeAreaView style={styles.container}>
      <ScreenGradient />
      <View style={styles.header}>
        <Pressable onPress={() => navigation.goBack()} hitSlop={8}>
          <Feather name="chevron-left" size={24} color={color.textPrimary} />
        </Pressable>
        <Text style={[type.h1, styles.headerTitle]} numberOfLines={1}>
          {project.name}
        </Text>
        <View style={{ width: 24 }} />
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.summaryCard}>
          <View style={styles.iconWrap}>
            <LinearGradient
              colors={gradient.accentSoft}
              style={StyleSheet.absoluteFill}
              start={{ x: 0, y: 0 }}
              end={{ x: 1, y: 1 }}
            />
            <Text style={[styles.iconText, { fontFamily: type.h1.fontFamily }]}>
              {project.name.charAt(0).toUpperCase()}
            </Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={[type.bodyMedium, styles.summaryTitle]}>{project.name}</Text>
            <View style={styles.envRow}>
              <StatusDot status={project.environment === 'production' ? 'online' : 'warning'} size={6} />
              <Text style={[type.caption, styles.summaryEnv]}>{project.environment}</Text>
              <Text style={[type.caption, styles.summaryPath]} numberOfLines={1}>
                {project.path}
              </Text>
            </View>
          </View>
        </View>

        {project.repository ? (
          <Section title="Git">
            <Row label="Repository" value={project.repository} />
            <Row label="Branch" value={project.branch} />
          </Section>
        ) : null}

        {project.stack.length > 0 && (
          <Section title="Stack">
            <View style={styles.chipRow}>
              {project.stack.map((s) => (
                <View key={s} style={styles.chip}>
                  <LinearGradient
                    colors={gradient.surface}
                    style={StyleSheet.absoluteFill}
                    start={{ x: 0, y: 0 }}
                    end={{ x: 1, y: 0 }}
                  />
                  <Text style={[type.caption, styles.chipText]}>{s}</Text>
                </View>
              ))}
            </View>
          </Section>
        )}

        {project.services.length > 0 && (
          <Section title="Services">
            {project.services.map((s) => (
              <View key={s} style={styles.serviceRow}>
                <Text style={[type.body, styles.serviceLabel]}>{s}</Text>
                <View style={styles.runningBadge}>
                  <StatusDot status="running" size={6} />
                  <Text style={[type.caption, styles.runningText]}>Running</Text>
                </View>
              </View>
            ))}
          </Section>
        )}

        {project.notes.length > 0 && (
          <Section title="Notes">
            {project.notes.map((n, i) => (
              <Text key={i} style={[type.body, styles.note]}>
                • {n}
              </Text>
            ))}
          </Section>
        )}

        {project.description ? (
          <Section title="About">
            <Text style={[type.body, styles.description]}>{project.description}</Text>
          </Section>
        ) : null}
      </ScrollView>

      <View style={styles.footer}>
        <Button label="Ask Molly about this project" onPress={askAboutProject} loading={startingChat} />
      </View>
    </SafeAreaView>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const { type } = useTypography();
  return (
    <View style={styles.section}>
      <Text style={[type.captionMedium, styles.sectionTitle]}>{title.toUpperCase()}</Text>
      <View style={styles.sectionCard}>
        {children}
      </View>
    </View>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  const { type } = useTypography();
  return (
    <View style={styles.infoRow}>
      <Text style={[type.caption, styles.infoLabel]}>{label}</Text>
      <Text style={[type.body, styles.infoValue]}>{value}</Text>
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
  headerTitle: { color: color.textPrimary, flex: 1, textAlign: 'center' },
  scroll: { paddingHorizontal: spacing.lg, paddingBottom: spacing.xxl, gap: spacing.lg },
  summaryCard: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.md,
    backgroundColor: color.surface,
    ...shadow.card,
  },
  iconWrap: {
    width: 48,
    height: 48,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  iconText: { color: color.accent, fontSize: 18 },
  summaryTitle: { color: color.textPrimary },
  envRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 4 },
  summaryEnv: { color: color.textSecondary },
  summaryPath: { color: color.textTertiary, marginLeft: 6, flexShrink: 1 },
  section: { gap: spacing.sm },
  sectionTitle: { color: color.textTertiary, letterSpacing: 0.4 },
  sectionCard: {
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.md,
    backgroundColor: color.surface,
    ...shadow.card,
  },
  infoRow: { flexDirection: 'row', justifyContent: 'space-between' },
  infoLabel: { color: color.textTertiary },
  infoValue: { color: color.textPrimary },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  chip: {
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    overflow: 'hidden',
  },
  chipText: { color: color.textSecondary },
  serviceRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  serviceLabel: { color: color.textPrimary },
  runningBadge: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  runningText: { color: color.success },
  note: { color: color.textSecondary },
  description: { color: color.textSecondary },
  footer: { padding: spacing.lg },
});
