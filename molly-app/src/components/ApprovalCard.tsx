import React, { useState } from 'react';
import { View, Text, StyleSheet, TextInput } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import Animated, { FadeInDown } from 'react-native-reanimated';
import { BorderBeam, type BorderBeamColorVariant } from './BorderBeam';
import { Button } from './Button';
import { ApproveGoo } from './ApproveGoo';
import { color, gradient, radius, riskColor, shadow, softTint, spacing } from '@/theme';
import { useTypography } from '@/context/TypographyContext';
import type { Approval } from '@/types/api';

export function ApprovalCard({
  approval,
  onApprove,
  onApproveAll,
  onReject,
  onCorrect,
  busy,
}: {
  approval: Approval;
  onApprove: () => void;
  onApproveAll?: () => void;
  onReject: () => void;
  onCorrect: (instruction: string) => void;
  busy?: boolean;
}) {
  const { type } = useTypography();
  const [correcting, setCorrecting] = useState(false);
  const [instruction, setInstruction] = useState('');
  const tint = riskColor(approval.risk_level);
  const resolved = approval.status !== 'pending';
  const risk = approval.risk_level.toUpperCase();
  const beamColor: BorderBeamColorVariant =
    risk === 'DANGEROUS' || risk === 'HIGH' ? 'sunset' : risk === 'MODERATE' || risk === 'MEDIUM' ? 'colorful' : 'ocean';

  return (
    <Animated.View entering={FadeInDown.springify().damping(16)} style={styles.beamShadow}>
    <BorderBeam size="md" colorVariant={beamColor} theme="light" strength={0.75} borderRadius={radius.lg} active={!resolved}>
    <View style={styles.card}>
      <LinearGradient
        colors={gradient.surface}
        style={StyleSheet.absoluteFill}
        start={{ x: 0, y: 0 }}
        end={{ x: 0, y: 1 }}
      />
      <View style={styles.header}>
        <Text style={[type.h2, styles.title]}>
          {resolved ? 'Approval' : 'Approval required'}
        </Text>
        <View style={styles.badge}>
          <LinearGradient
            colors={softTint(tint)}
            style={StyleSheet.absoluteFill}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 0 }}
          />
          <Text style={[type.micro, { color: tint }]}>{approval.risk_level}</Text>
        </View>
      </View>

      <View style={styles.commandBox}>
        <Text style={[type.mono, styles.commandText]} numberOfLines={4}>
          {approval.command}
        </Text>
      </View>

      {approval.risk_note ? (
        <Text style={[type.caption, styles.riskNote]}>{approval.risk_note}</Text>
      ) : null}

      {resolved ? (
        <Text style={[type.captionMedium, styles.resolvedLabel, { color: statusColor(approval.status) }]}>
          {statusLabel(approval.status)}
        </Text>
      ) : correcting ? (
        <View style={styles.correctBox}>
          <TextInput
            value={instruction}
            onChangeText={setInstruction}
            placeholder="Tell Molly what to do instead…"
            placeholderTextColor={color.textTertiary}
            style={[styles.input, { fontFamily: type.body.fontFamily }]}
            cursorColor={color.accent}
            selectionColor={color.accent}
            multiline
          />
          <View style={styles.actionsRow}>
            <Button label="Cancel" variant="ghost" onPress={() => setCorrecting(false)} />
            <Button
              label="Send"
              variant="primary"
              disabled={!instruction.trim()}
              loading={busy}
              onPress={() => onCorrect(instruction.trim())}
              style={{ flex: 1 }}
            />
          </View>
        </View>
      ) : (
        <View style={styles.correctBox}>
          <View style={styles.actionsRow}>
            <Button label="Reject" variant="danger" onPress={onReject} loading={busy} style={{ flex: 1 }} />
            <Button label="Correct" variant="secondary" onPress={() => setCorrecting(true)} style={{ flex: 1 }} />
            {onApproveAll ? (
              <ApproveGoo
                onApprove={onApprove}
                onApproveAll={onApproveAll}
                busy={busy}
                allLabel={approval.tool ? `Approve all "${approval.tool}" actions for this task` : 'Approve all remaining actions for this task'}
              />
            ) : (
              <Button label="Approve" variant="primary" onPress={onApprove} loading={busy} style={{ flex: 1 }} />
            )}
          </View>
        </View>
      )}
    </View>
    </BorderBeam>
    </Animated.View>
  );
}

function statusLabel(status: Approval['status']) {
  switch (status) {
    case 'approved':
      return 'Approved';
    case 'rejected':
      return 'Rejected';
    case 'corrected':
      return 'Correction sent';
    default:
      return status;
  }
}

function statusColor(status: Approval['status']) {
  switch (status) {
    case 'approved':
      return color.success;
    case 'rejected':
      return color.danger;
    default:
      return color.textSecondary;
  }
}

const styles = StyleSheet.create({
  beamShadow: {
    marginHorizontal: spacing.lg,
    marginBottom: spacing.lg,
    borderRadius: radius.lg,
    ...shadow.card,
  },
  card: {
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.md,
    backgroundColor: color.surface,
  },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  title: { color: color.textPrimary },
  badge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    borderRadius: radius.pill,
    overflow: 'hidden',
  },
  commandBox: {
    backgroundColor: color.bgElevated,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  commandText: { color: color.textPrimary },
  riskNote: { color: color.textSecondary },
  actionsRow: { flexDirection: 'row', gap: spacing.sm },
  correctBox: { gap: spacing.sm },
  input: {
    backgroundColor: color.bgElevated,
    borderRadius: radius.md,
    padding: spacing.md,
    color: color.textPrimary,
    minHeight: 64,
    textAlignVertical: 'top',
  },
  resolvedLabel: {},
  approveAllLink: { color: color.accent, textAlign: 'center' },
});
