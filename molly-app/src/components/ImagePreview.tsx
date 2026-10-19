import React from 'react';
import { View, Image, Pressable, StyleSheet } from 'react-native';
import { Feather } from '@expo/vector-icons';
import { color, radius, spacing } from '@/theme';

export function ImagePreview({
  uri,
  onRemove,
  size = 72,
}: {
  uri: string;
  onRemove?: () => void;
  size?: number;
}) {
  return (
    <View style={[styles.wrap, { width: size, height: size }]}>
      <Image source={{ uri }} style={StyleSheet.absoluteFill} resizeMode="cover" />
      {onRemove ? (
        <Pressable onPress={onRemove} style={styles.removeBtn} hitSlop={8}>
          <Feather name="x" size={12} color={color.white} />
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    borderRadius: radius.md,
    overflow: 'hidden',
    backgroundColor: color.surfaceHigh,
  },
  removeBtn: {
    position: 'absolute',
    top: 4,
    right: 4,
    backgroundColor: color.overlay,
    width: 20,
    height: 20,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
