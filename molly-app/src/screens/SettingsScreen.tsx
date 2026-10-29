import React from 'react';
import { View, Text, Pressable, ScrollView, StyleSheet, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { Feather } from '@expo/vector-icons';
import { useAuth } from '@/context/AuthContext';
import { useTypography } from '@/context/TypographyContext';
import { Avatar } from '@/components/Avatar';
import { ScreenGradient } from '@/components/ScreenGradient';
import { color, radius, shadow, spacing } from '@/theme';

interface SettingsRow {
  label: string;
  onPress: () => void;
  danger?: boolean;
}

export function SettingsScreen() {
  const { type } = useTypography();
  const navigation = useNavigation<any>();
  const { user, logout } = useAuth();

  const confirmLogout = () => {
    Alert.alert('Sign out', 'You can pair this device again anytime.', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Sign out', style: 'destructive', onPress: logout },
    ]);
  };

  const rows: SettingsRow[] = [
    { label: 'Projects', onPress: () => navigation.navigate('Projects') },
    { label: 'Activity', onPress: () => navigation.navigate('Activity') },
    { label: 'Connected devices', onPress: () => navigation.navigate('Devices') },
    { label: 'LLM providers', onPress: () => navigation.navigate('ProviderSettings') },
    { label: 'Text & Display', onPress: () => navigation.navigate('TextDisplay') },
    { label: 'Notifications', onPress: () => {} },
    { label: 'About Molly', onPress: () => {} },
  ];

  return (
    <SafeAreaView style={styles.container}>
      <ScreenGradient />
      <View style={styles.header}>
        <Pressable onPress={() => navigation.goBack()} hitSlop={8} accessibilityLabel="Back">
          <Feather name="chevron-left" size={24} color={color.textPrimary} />
        </Pressable>
        <Text style={[type.title, styles.title]}>Settings</Text>
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.profileCard}>
          <Avatar label={user?.display_name ?? user?.email ?? 'M'} size={48} />
          <View style={{ flex: 1 }}>
            <Text style={[type.bodyMedium, styles.profileName]} numberOfLines={1}>
              {user?.display_name ?? user?.username ?? 'Operator'}
            </Text>
            {user?.email ? (
              <Text style={[type.caption, styles.profileEmail]} numberOfLines={1}>
                {user.email}
              </Text>
            ) : null}
          </View>
        </View>

        <View style={styles.group}>
          {rows.map((row, i) => (
            <Pressable key={row.label} onPress={row.onPress} style={styles.row}>
              <Text style={[type.body, styles.rowLabel]}>{row.label}</Text>
              <Text style={styles.chevron}>›</Text>
            </Pressable>
          ))}
        </View>

        <Pressable style={styles.signOutRow} onPress={confirmLogout}>
          <Text style={[type.bodyMedium, styles.signOutText]}>Sign Out</Text>
        </Pressable>
      </ScrollView>
    </SafeAreaView>
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
  title: { color: color.textPrimary },
  scroll: { paddingHorizontal: spacing.lg, paddingBottom: spacing.xxl, gap: spacing.lg },
  profileCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    borderRadius: radius.lg,
    padding: spacing.lg,
    backgroundColor: color.surface,
    ...shadow.card,
  },
  profileName: { color: color.textPrimary },
  profileEmail: { color: color.textTertiary, marginTop: 2 },
  group: {
    borderRadius: radius.lg,
    backgroundColor: color.surface,
    ...shadow.card,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  rowLabel: { color: color.textPrimary },
  chevron: { color: color.textTertiary, fontSize: 18 },
  signOutRow: {
    borderRadius: radius.pill,
    paddingVertical: spacing.md,
    alignItems: 'center',
    backgroundColor: color.surface,
    ...shadow.soft,
  },
  signOutText: { color: color.danger },
});
