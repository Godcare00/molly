import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, FlatList, Pressable, StyleSheet, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Feather } from '@expo/vector-icons';
import { useNavigation } from '@react-navigation/native';
import { authApi } from '@/api/auth';
import { useTypography } from '@/context/TypographyContext';
import { StatusDot } from '@/components/StatusDot';
import { LoadingState } from '@/components/LoadingState';
import { ErrorState } from '@/components/ErrorState';
import { ScreenGradient } from '@/components/ScreenGradient';
import { LinearGradient } from 'expo-linear-gradient';
import { color, gradient, radius, spacing } from '@/theme';
import type { DeviceResponse } from '@/types/api';

function formatDate(iso?: string | null) {
  if (!iso) return 'Never';
  return new Date(iso).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
}

export function DevicesScreen() {
  const { type } = useTypography();
  const navigation = useNavigation<any>();
  const [devices, setDevices] = useState<DeviceResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await authApi.listDevices();
      setDevices(res.devices);
    } catch (err: any) {
      setError(err?.message ?? 'Could not load devices.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const revoke = (device: DeviceResponse) => {
    Alert.alert('Revoke device', `"${device.name}" will be signed out immediately.`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Revoke',
        style: 'destructive',
        onPress: async () => {
          await authApi.revokeDevice(device.id);
          load();
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
        <Text style={[type.h1, styles.headerTitle]}>Connected devices</Text>
        <View style={{ width: 24 }} />
      </View>

      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : (
        <FlatList
          data={devices}
          keyExtractor={(d) => d.id}
          contentContainerStyle={styles.listContent}
          renderItem={({ item }) => (
            <View style={styles.card}>
              <LinearGradient
                colors={gradient.surface}
                style={StyleSheet.absoluteFill}
                start={{ x: 0, y: 0 }}
                end={{ x: 0, y: 1 }}
              />
              <View style={{ flex: 1 }}>
                <View style={styles.nameRow}>
                  <Text style={[type.bodyMedium, styles.deviceName]}>{item.name}</Text>
                  {item.is_trusted && (
                    <View style={styles.trustedBadge}>
                      <LinearGradient
                        colors={gradient.successSoft}
                        style={StyleSheet.absoluteFill}
                        start={{ x: 0, y: 0 }}
                        end={{ x: 1, y: 0 }}
                      />
                      <Text style={[type.micro, styles.trustedText]}>TRUSTED</Text>
                    </View>
                  )}
                </View>
                <View style={styles.metaRow}>
                  <StatusDot status={item.is_revoked ? 'offline' : 'online'} size={6} />
                  <Text style={[type.caption, styles.metaText]}>
                    {item.platform} · Last used {formatDate(item.last_used_at)}
                  </Text>
                </View>
              </View>
              {!item.is_revoked && (
                <Pressable onPress={() => revoke(item)} hitSlop={8}>
                  <Text style={[styles.revokeText, { fontFamily: type.captionMedium.fontFamily }]}>
                    Revoke
                  </Text>
                </Pressable>
              )}
            </View>
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
    borderRadius: radius.lg,
    padding: spacing.lg,
    marginBottom: spacing.md,
    overflow: 'hidden',
  },
  nameRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  deviceName: { color: color.textPrimary },
  trustedBadge: {
    borderRadius: radius.pill,
    paddingHorizontal: 8,
    paddingVertical: 2,
    overflow: 'hidden',
  },
  trustedText: { color: color.success },
  metaRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 4 },
  metaText: { color: color.textTertiary },
  revokeText: { color: color.danger, fontSize: 13 },
});
