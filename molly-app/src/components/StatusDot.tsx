import React from 'react';
import { View } from 'react-native';
import { color } from '@/theme';

type Status = 'online' | 'offline' | 'running' | 'stopped' | 'warning';

const STATUS_COLOR: Record<Status, string> = {
  online: color.success,
  running: color.success,
  offline: color.textTertiary,
  stopped: color.textTertiary,
  warning: color.warning,
};

export function StatusDot({ status, size = 8 }: { status: Status; size?: number }) {
  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius: size / 2,
        backgroundColor: STATUS_COLOR[status],
      }}
    />
  );
}
