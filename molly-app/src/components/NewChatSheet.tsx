import React, { useEffect, useRef } from 'react';
import { View, Text, Pressable, StyleSheet, Modal, Animated } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Feather } from '@expo/vector-icons';
import { useTypography } from '@/context/TypographyContext';
import { color, radius, shadow, spacing } from '@/theme';
import type { ConversationMode } from '@/types/api';

const OPTIONS: {
  mode: ConversationMode;
  icon: React.ComponentProps<typeof Feather>['name'];
  title: string;
  subtitle: string;
  iconBg: string;
  iconColor: string;
}[] = [
  {
    mode: 'general',
    icon: 'message-circle',
    title: 'New chat',
    subtitle: 'Manage, debug, and deploy on your own server.',
    iconBg: color.accentSoft,
    iconColor: color.accent,
  },
  {
    mode: 'bug_bounty',
    icon: 'shield',
    title: 'Bug bounty chat',
    subtitle: 'Authorized security testing - same approvals, a scope-first workflow.',
    iconBg: color.warningSoft,
    iconColor: color.warning,
  },
];

/** A short bottom sheet for picking a new conversation's mode. Kept to
 * exactly the two modes the backend supports (see backend/README.md's
 * "Agent Modes") rather than a generic settings screen - if a third mode
 * shows up, add a row here. */
export function NewChatSheet({
  visible,
  onClose,
  onChoose,
}: {
  visible: boolean;
  onClose: () => void;
  onChoose: (mode: ConversationMode) => void;
}) {
  const { type } = useTypography();
  const translateY = useRef(new Animated.Value(40)).current;
  const backdropOpacity = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.timing(translateY, {
        toValue: visible ? 0 : 40,
        duration: 220,
        useNativeDriver: true,
      }),
      Animated.timing(backdropOpacity, {
        toValue: visible ? 1 : 0,
        duration: 200,
        useNativeDriver: true,
      }),
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
            <Text style={[type.h1, styles.title]}>Start a chat</Text>

            {OPTIONS.map((opt) => (
              <Pressable
                key={opt.mode}
                onPress={() => {
                  onChoose(opt.mode);
                  onClose();
                }}
                style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
              >
                <View style={[styles.iconWrap, { backgroundColor: opt.iconBg }]}>
                  <Feather name={opt.icon} size={18} color={opt.iconColor} />
                </View>
                <View style={styles.rowText}>
                  <Text style={[type.bodyMedium, styles.rowTitle]}>{opt.title}</Text>
                  <Text style={[type.caption, styles.rowSubtitle]}>{opt.subtitle}</Text>
                </View>
                <Feather name="chevron-right" size={18} color={color.textTertiary} />
              </Pressable>
            ))}
          </SafeAreaView>
        </Animated.View>
      </View>
    </Modal>
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
  title: { color: color.textPrimary, marginBottom: spacing.md },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    backgroundColor: color.bgElevated,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.sm,
    ...shadow.soft,
  },
  rowPressed: { opacity: 0.85 },
  iconWrap: {
    width: 36,
    height: 36,
    borderRadius: radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
  },
  rowText: { flex: 1 },
  rowTitle: { color: color.textPrimary },
  rowSubtitle: { color: color.textTertiary, marginTop: 2 },
});
