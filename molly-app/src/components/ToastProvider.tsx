import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Feather } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { Platform } from 'react-native';
import { Liquid } from './Liquid';
import { color, radius, spacing } from '@/theme';
import { useTypography } from '@/context/TypographyContext';

type Tone = 'info' | 'success' | 'error';
interface ToastState {
  id: number;
  text: string;
  tone: Tone;
  shown: boolean;
}
interface ToastApi {
  show: (text: string, tone?: Tone) => void;
}

const Ctx = createContext<ToastApi>({ show: () => {} });
export const useToast = () => useContext(Ctx);

const ICON: Record<Tone, { name: React.ComponentProps<typeof Feather>['name']; tint: string }> = {
  info: { name: 'info', tint: color.accent },
  success: { name: 'check-circle', tint: color.success },
  error: { name: 'alert-circle', tint: color.danger },
};

/** Toasts that drip down from the top edge as gooey liquid. */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const { type } = useTypography();
  const insets = useSafeAreaInsets();
  const [toast, setToast] = useState<ToastState | null>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const idRef = useRef(0);

  const clearTimers = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  };
  useEffect(() => clearTimers, []);

  const show = useCallback((text: string, tone: Tone = 'info') => {
    clearTimers();
    const id = ++idRef.current;
    setToast({ id, text, tone, shown: false });
    // Next tick: mount hidden above the edge, then let it drip down.
    timers.current.push(setTimeout(() => setToast((t) => (t && t.id === id ? { ...t, shown: true } : t)), 20));
    timers.current.push(setTimeout(() => setToast((t) => (t && t.id === id ? { ...t, shown: false } : t)), 3200));
    timers.current.push(setTimeout(() => setToast((t) => (t && t.id === id ? null : t)), 3800));
    if (Platform.OS !== 'web') {
      Haptics.notificationAsync(tone === 'error' ? Haptics.NotificationFeedbackType.Error : Haptics.NotificationFeedbackType.Success).catch(() => {});
    }
  }, []);

  const api = useMemo(() => ({ show }), [show]);

  return (
    <Ctx.Provider value={api}>
      {children}
      {toast ? (
        <View style={[styles.host, { paddingTop: insets.top + 6 }]} pointerEvents="box-none">
          <Liquid blur={6} contrast={18} fill="#ffffff" shadow="0 4px 14px rgba(33,28,21,.14)" filterPadding={40} style={styles.liquid}>
            {/* The edge the drop hangs from. */}
            <Liquid.Item
              scale={toast.shown ? 1 : 0.6}
              transition="smooth"
              height={22}
              radius={11}
              style={styles.anchor}
            />
            <Liquid.Item y={toast.shown ? 0 : -70} transition="bouncy" radius={radius.lg} style={styles.toastSlot}>
              <View style={styles.toast} accessibilityLiveRegion="polite" accessibilityRole="alert">
                <Feather name={ICON[toast.tone].name} size={18} color={ICON[toast.tone].tint} />
                <Text style={[type.bodyMedium, styles.text]} numberOfLines={2}>
                  {toast.text}
                </Text>
              </View>
            </Liquid.Item>
          </Liquid>
        </View>
      ) : null}
    </Ctx.Provider>
  );
}

const styles = StyleSheet.create({
  host: { position: 'absolute', top: 0, left: 0, right: 0, alignItems: 'center' },
  liquid: { width: '100%', height: 60, alignItems: 'center' },
  anchor: { position: 'absolute', top: -14, left: 70, right: 70, height: 22 },
  toastSlot: { alignSelf: 'center', maxWidth: '90%' },
  toast: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  text: { color: color.textPrimary, flexShrink: 1 },
});
