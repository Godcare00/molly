import React from 'react';
import { View, Text, StyleSheet, Linking } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import Animated, { FadeInDown } from 'react-native-reanimated';
import { Avatar } from './Avatar';
import { MarkdownText } from './Markdown';
import { ToolCallGroup } from './ToolCallCard';
import { FilePreview } from './FilePreview';
import { filesApi } from '@/api/files';
import { imagesApi } from '@/api/images';
import { color, gradient, radius, shadow, spacing } from '@/theme';
import { useTypography } from '@/context/TypographyContext';
import type { Message } from '@/types/api';

export function MessageBubble({ message }: { message: Message }) {
  const { type } = useTypography();
  const isUser = message.role === 'user';
  const attachments = message.metadata?.attachments ?? [];

  if (isUser) {
    return (
      <Animated.View entering={FadeInDown.duration(260)} style={[styles.row, styles.rowRight]}>
        <LinearGradient
          colors={gradient.accent}
          style={[styles.bubble, styles.userBubble]}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
        >
          <Text style={[type.body, styles.userText]}>{message.content}</Text>
        </LinearGradient>
      </Animated.View>
    );
  }

  return (
    <Animated.View entering={FadeInDown.duration(260)} style={[styles.row, styles.rowLeft]}>
      <Avatar label="Molly" size={28} paused />
      <View style={styles.assistantColumn}>
        <LinearGradient
          colors={gradient.surface}
          style={[styles.bubble, styles.assistantBubble]}
          start={{ x: 0, y: 0 }}
          end={{ x: 0, y: 1 }}
        >
          <MarkdownText content={message.content} />
        </LinearGradient>
        {attachments.length ? (
          <View style={styles.attachmentRow}>
            {attachments.map((a) => (
              <FilePreview
                key={a.id}
                fileName={a.filename}
                size={a.size_bytes}
                kind={a.type}
                onPress={() =>
                  Linking.openURL(
                    a.type === 'image'
                      ? imagesApi.contentUrl(message.conversation_id, a.id)
                      : filesApi.contentUrl(message.conversation_id, a.id),
                  )
                }
              />
            ))}
          </View>
        ) : null}
        {message.tool_calls?.length ? <ToolCallGroup toolCalls={message.tool_calls} /> : null}
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    marginBottom: spacing.lg,
    paddingHorizontal: spacing.lg,
    gap: spacing.sm,
  },
  rowLeft: { justifyContent: 'flex-start' },
  rowRight: { justifyContent: 'flex-end' },
  assistantColumn: { flex: 1, maxWidth: '88%' },
  attachmentRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
    marginTop: spacing.xs,
  },
  bubble: {
    borderRadius: radius.lg,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  userBubble: {
    borderBottomRightRadius: radius.sm,
    maxWidth: '82%',
    ...shadow.accentPill,
  },
  assistantBubble: {
    borderBottomLeftRadius: radius.sm,
    ...shadow.soft,
  },
  userText: { color: color.white },
});
