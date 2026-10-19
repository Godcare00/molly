import React from 'react';
import { View, Text, Pressable, StyleSheet } from 'react-native';
import { Feather } from '@expo/vector-icons';
import { color, radius, spacing } from '@/theme';
import { useTypography } from '@/context/TypographyContext';

function formatSize(bytes?: number): string {
  if (!bytes && bytes !== 0) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function FilePreview({
  fileName,
  size,
  kind = 'file',
  onRemove,
  onPress,
}: {
  fileName: string;
  size?: number;
  /** Picks the icon. Use 'image' for a Molly-sent image attachment. */
  kind?: 'file' | 'image';
  /** Composer use: lets the user drop this attachment before sending. */
  onRemove?: () => void;
  /** Message use: opens/downloads an attachment already on a sent message. */
  onPress?: () => void;
}) {
  const { type } = useTypography();

  const content = (
    <>
      <Feather name={kind === 'image' ? 'image' : 'file-text'} size={16} color={color.textSecondary} />
      <View style={styles.textCol}>
        <Text style={[type.caption, styles.name]} numberOfLines={1}>
          {fileName}
        </Text>
        {size !== undefined ? (
          <Text style={[type.caption, styles.size]} numberOfLines={1}>
            {formatSize(size)}
          </Text>
        ) : null}
      </View>
      {onRemove ? (
        <Pressable onPress={onRemove} style={styles.removeBtn} hitSlop={8}>
          <Feather name="x" size={12} color={color.textSecondary} />
        </Pressable>
      ) : null}
    </>
  );

  if (onPress) {
    return (
      <Pressable onPress={onPress} style={styles.wrap}>
        {content}
      </Pressable>
    );
  }

  return <View style={styles.wrap}>{content}</View>;
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    backgroundColor: color.surfaceHigh,
    borderRadius: radius.md,
    paddingHorizontal: spacing.sm,
    paddingVertical: 6,
    maxWidth: 180,
  },
  textCol: { flexShrink: 1 },
  name: { color: color.textPrimary },
  size: { color: color.textTertiary },
  removeBtn: {
    width: 18,
    height: 18,
    borderRadius: 9,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
