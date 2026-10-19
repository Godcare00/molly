import React from 'react';
import { Pressable, StyleSheet, Text, ViewStyle } from 'react-native';
import { Liquid } from './Liquid';
import { Button } from './Button';
import { color } from '@/theme';
import { useTypography } from '@/context/TypographyContext';

/**
 * "Approve" with an "Approve all" droplet: on mount the droplet is pushed out of
 * the button and stays bridged to it by a thin liquid neck.
 */
export function ApproveGoo({
  onApprove,
  onApproveAll,
  busy,
  allLabel,
  style,
}: {
  onApprove: () => void;
  onApproveAll: () => void;
  busy?: boolean;
  allLabel: string;
  style?: ViewStyle;
}) {
  const { type } = useTypography();
  return (
    <Liquid blur={6} contrast={18} fill={color.accent} filterPadding={16} style={[styles.row, style]}>
      <Liquid.Item transition="bouncy" radius={26} style={styles.grow}>
        <Button label="Approve" variant="primary" onPress={onApprove} loading={busy} />
      </Liquid.Item>
      <Liquid.Item from={{ x: -54, scale: 0.4 }} transition="bouncy" delay={140} width={52} height={52} style={styles.drop}>
        <Pressable
          accessibilityLabel={allLabel}
          accessibilityHint="Approves every matching action for the rest of this task"
          disabled={busy}
          onPress={onApproveAll}
          style={styles.dropBtn}
        >
          <Text style={[type.captionMedium, styles.dropText]}>All</Text>
        </Pressable>
      </Liquid.Item>
    </Liquid>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 5, flex: 1.6 },
  grow: { flex: 1 },
  drop: { width: 52, height: 52 },
  dropBtn: { width: 52, height: 52, borderRadius: 26, alignItems: 'center', justifyContent: 'center' },
  dropText: { color: color.white },
});
