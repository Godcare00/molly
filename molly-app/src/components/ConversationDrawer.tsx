import React, { useEffect, useRef } from 'react';
import { View, Text, FlatList, Pressable, StyleSheet, Modal, Animated, Dimensions } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Feather } from '@expo/vector-icons';
import { useConversations } from '@/context/ConversationsContext';
import { useTypography } from '@/context/TypographyContext';
import { LoadingState } from '@/components/LoadingState';
import { color, radius, shadow, spacing } from '@/theme';
import type { Conversation } from '@/types/api';

const DRAWER_WIDTH = Math.min(320, Dimensions.get('window').width * 0.84);

function formatDate(iso: string) {
  const d = new Date(iso);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

// A soft, elegant slide-in panel for recent conversations — sits over the
// chat instead of taking a whole screen, the way a "history" drawer does in
// the ChatGPT app.
export function ConversationDrawer({
  visible,
  onClose,
  onSelect,
  onNew,
}: {
  visible: boolean;
  onClose: () => void;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  const { type } = useTypography();
  const { conversations, loading, activeId } = useConversations();
  const translateX = useRef(new Animated.Value(-DRAWER_WIDTH)).current;
  const backdropOpacity = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.timing(translateX, {
        toValue: visible ? 0 : -DRAWER_WIDTH,
        duration: 260,
        useNativeDriver: true,
      }),
      Animated.timing(backdropOpacity, {
        toValue: visible ? 1 : 0,
        duration: 220,
        useNativeDriver: true,
      }),
    ]).start();
  }, [visible, translateX, backdropOpacity]);

  return (
    <Modal visible={visible} transparent animationType="none" onRequestClose={onClose} statusBarTranslucent>
      <View style={styles.fill}>
        <Animated.View style={[styles.backdrop, { opacity: backdropOpacity }]}>
          <Pressable style={styles.fill} onPress={onClose} />
        </Animated.View>

        <Animated.View style={[styles.panel, { width: DRAWER_WIDTH, transform: [{ translateX }] }]}>
          <SafeAreaView style={styles.fill}>
            <View style={styles.header}>
              <Text style={[type.h1, styles.title]}>Chats</Text>
              <Pressable
                onPress={() => {
                  onNew();
                  onClose();
                }}
                hitSlop={8}
                style={styles.newButton}
              >
                <Feather name="edit" size={16} color={color.accent} />
              </Pressable>
            </View>

            {loading ? (
              <LoadingState />
            ) : conversations.length === 0 ? (
              <View style={styles.empty}>
                <Text style={[type.body, styles.emptyText]}>No conversations yet</Text>
              </View>
            ) : (
              <FlatList
                data={conversations}
                keyExtractor={(c) => c.id}
                contentContainerStyle={styles.listContent}
                renderItem={({ item }: { item: Conversation }) => (
                  <Pressable
                    onPress={() => {
                      onSelect(item.id);
                      onClose();
                    }}
                    style={[styles.row, item.id === activeId && styles.rowActive]}
                  >
                    <View style={styles.rowText}>
                      <Text style={[type.bodyMedium, styles.rowTitle]} numberOfLines={1}>
                        {item.title || 'Untitled conversation'}
                      </Text>
                      {item.last_message_preview ? (
                        <Text style={[type.caption, styles.rowPreview]} numberOfLines={1}>
                          {item.last_message_preview}
                        </Text>
                      ) : null}
                    </View>
                    <Text style={[type.caption, styles.rowTime]}>{formatDate(item.updated_at)}</Text>
                  </Pressable>
                )}
              />
            )}
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
  panel: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    left: 0,
    backgroundColor: color.bg,
    ...shadow.drawer,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  title: { color: color.textPrimary },
  newButton: {
    width: 34,
    height: 34,
    borderRadius: radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: color.white,
    ...shadow.soft,
  },
  listContent: { paddingHorizontal: spacing.md, paddingBottom: spacing.xxl },
  row: {
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.xs,
  },
  rowActive: { backgroundColor: color.accentSoft },
  rowText: { marginRight: spacing.sm },
  rowTitle: { color: color.textPrimary },
  rowPreview: { color: color.textTertiary, marginTop: 2 },
  rowTime: { color: color.textTertiary, marginTop: 4 },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  emptyText: { color: color.textTertiary },
});
