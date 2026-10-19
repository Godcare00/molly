import React, { useEffect, useState } from 'react';
import { View, Text, Pressable, StyleSheet, ScrollView } from 'react-native';
import { ThinkingOrb, type OrbState } from './ThinkingOrb';
import { VoiceBeam } from './VoiceBeam';
import { Liquid } from './Liquid';
import Animated, { useAnimatedStyle, useSharedValue, withDelay, withTiming } from 'react-native-reanimated';
import { Feather } from '@expo/vector-icons';
import { color, radius, shadow, spacing } from '@/theme';
import { useTypography } from '@/context/TypographyContext';
import type { LiveVoiceStatus, LiveTranscriptLine } from '@/hooks/useLiveVoice';

const BAR_H = 56;

const STATUS_LABEL: Record<LiveVoiceStatus, string> = {
  idle: '',
  connecting: 'Connecting…',
  listening: 'Listening…',
  speaking: 'Molly is speaking…',
  awaiting_confirmation: 'Say "confirm" to proceed, or "cancel" to stop',
  error: 'Something went wrong',
};

const STATUS_ORB: Partial<Record<LiveVoiceStatus, OrbState>> = {
  connecting: 'connecting',
  listening: 'listening',
  speaking: 'composing',
};

const STATUS_DOT_COLOR: Record<LiveVoiceStatus, string> = {
  idle: color.textTertiary,
  connecting: color.textTertiary,
  listening: color.accent,
  speaking: color.accent,
  awaiting_confirmation: color.warning,
  error: color.danger,
};

/** Replaces ChatInput while a hands-free session is active (see ChatScreen). */
export function LiveVoiceBar({
  status,
  transcript,
  error,
  onStop,
  getLevel,
}: {
  status: LiveVoiceStatus;
  transcript: LiveTranscriptLine[];
  error: string | null;
  onStop: () => void;
  /** Mic / assistant loudness 0–1, sampled every frame to drive the glow. */
  getLevel?: () => number;
}) {
  const { type } = useTypography();
  const recentLines = transcript.slice(-4);
  const [w, setW] = useState(0);
  const fade = useSharedValue(0);
  useEffect(() => {
    fade.value = withDelay(180, withTiming(1, { duration: 220 }));
  }, [fade]);
  const fadeStyle = useAnimatedStyle(() => ({ opacity: fade.value }));

  return (
    <View style={styles.container}>
      {recentLines.length > 0 && (
        <ScrollView style={styles.transcriptBox} contentContainerStyle={styles.transcriptContent}>
          {recentLines.map((line, i) => (
            <Text
              key={i}
              style={[type.body, line.role === 'assistant' ? styles.assistantLine : styles.userLine]}
              numberOfLines={3}
            >
              {line.role === 'assistant' ? 'Molly: ' : 'You: '}
              {line.text}
            </Text>
          ))}
        </ScrollView>
      )}

      <View onLayout={(e) => setW(Math.round(e.nativeEvent.layout.width))} style={{ height: BAR_H }}>
        {w > 0 ? (
          <VoiceBeam
            level={getLevel ?? 0}
            borderRadius={radius.xl}
            active={status === 'listening' || status === 'speaking' || status === 'awaiting_confirmation'}
            colorVariant={status === 'speaking' ? 'candy' : 'colorful'}
            style={styles.beamShadow}
          >
            <Liquid blur={6} contrast={18} fill={color.bgElevated} filterPadding={24} style={{ width: w, height: BAR_H }}>
              <Liquid.Item
                animateSize
                transition="bouncy"
                width={w}
                height={BAR_H}
                radius={radius.xl}
                from={{ width: 44, height: 44, radius: 22 }}
                style={{ width: w, height: BAR_H }}
              >
                <Animated.View style={[styles.bar, fadeStyle]}>
                  <View style={styles.statusRow}>
                    {STATUS_ORB[status] && !error ? (
                      <ThinkingOrb state={STATUS_ORB[status]!} size={20} dark={false} />
                    ) : (
                      <View style={[styles.dot, { backgroundColor: STATUS_DOT_COLOR[status] }]} />
                    )}
                    <Text style={[type.body, styles.statusText]} numberOfLines={2}>
                      {error ?? STATUS_LABEL[status]}
                    </Text>
                  </View>
                  <Pressable onPress={onStop} style={styles.stopButton} hitSlop={8}>
                    <Feather name="mic-off" size={18} color={color.white} />
                  </Pressable>
                </Animated.View>
              </Liquid.Item>
            </Liquid>
          </VoiceBeam>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.md,
    gap: spacing.sm,
  },
  transcriptBox: { maxHeight: 140 },
  transcriptContent: { gap: spacing.xs, paddingVertical: spacing.xs },
  assistantLine: { color: color.textPrimary },
  userLine: { color: color.textSecondary },
  beamShadow: { borderRadius: radius.xl, ...shadow.soft },
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    flex: 1,
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
  },
  statusRow: { flexDirection: 'row', alignItems: 'center', flex: 1, gap: spacing.sm },
  dot: { width: 8, height: 8, borderRadius: 4 },
  statusText: { color: color.textPrimary, flexShrink: 1 },
  stopButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: color.danger,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
