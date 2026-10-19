import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { ThinkingOrb, orbStateForTool } from './ThinkingOrb';
import { Feather } from '@expo/vector-icons';
import { color, radius, shadow, spacing } from '@/theme';
import { useTypography } from '@/context/TypographyContext';
import type { ToolCall } from '@/types/api';

function StatusIcon({ status, toolName }: { status: ToolCall['status']; toolName?: string }) {
  if (status === 'running') return <ThinkingOrb state={orbStateForTool(toolName)} size={20} dark={false} />;
  const name = status === 'complete' ? 'check' : 'x';
  const tint = status === 'complete' ? color.success : color.danger;
  return <Feather name={name} size={14} color={tint} />;
}

export function ToolCallGroup({ toolCalls }: { toolCalls: ToolCall[] }) {
  const { type } = useTypography();
  if (!toolCalls.length) return null;
  return (
    <View style={styles.container}>
      <Text style={[type.micro, styles.header]}>TOOLS USED</Text>
      {toolCalls.map((tool) => (
        <View key={tool.id} style={styles.row}>
          <StatusIcon status={tool.status} toolName={tool.name} />
          <Text style={[type.caption, styles.label]} numberOfLines={1}>
            {tool.label ?? tool.name}
          </Text>
          {tool.duration_seconds !== undefined && (
            <Text style={[type.caption, styles.duration]}>{tool.duration_seconds}s</Text>
          )}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    borderRadius: radius.md,
    padding: spacing.md,
    marginTop: spacing.sm,
    gap: spacing.sm,
    backgroundColor: color.surface,
    ...shadow.soft,
  },
  header: { color: color.textTertiary, letterSpacing: 0.4 },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  label: { color: color.textSecondary, flex: 1 },
  duration: { color: color.textTertiary },
});
