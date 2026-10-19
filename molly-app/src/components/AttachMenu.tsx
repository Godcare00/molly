import React, { useEffect, useState } from 'react';
import { View, Pressable, StyleSheet } from 'react-native';
import { Feather } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { Platform } from 'react-native';
import { Liquid } from './Liquid';
import { color, spacing } from '@/theme';

const BTN = 46;
const H = 124;

const ACTIONS = [
  { key: 'camera', icon: 'camera' as const, label: 'Take photo', x: 0, y: -66 },
  { key: 'photo', icon: 'image' as const, label: 'Choose photo', x: 52, y: -50 },
  { key: 'file', icon: 'paperclip' as const, label: 'Choose file', x: 96, y: -12 },
];

/**
 * The attach menu: tapping + splits droplets out of the input bar that fan up
 * and bridge back like goo (Libraries.dev `liquid-gooey`). Rendered in flow
 * above the input row so every droplet is a normal, tappable button.
 */
export function AttachMenu({
  open,
  onClose,
  onCamera,
  onPhoto,
  onFile,
}: {
  open: boolean;
  onClose: () => void;
  onCamera: () => void;
  onPhoto: () => void;
  onFile: () => void;
}) {
  // Stay mounted while the droplets travel back into the bar.
  const [mounted, setMounted] = useState(open);
  const [spread, setSpread] = useState(false);
  useEffect(() => {
    if (open) {
      setMounted(true);
      const t = setTimeout(() => setSpread(true), 30);
      return () => clearTimeout(t);
    }
    setSpread(false);
    const t = setTimeout(() => setMounted(false), 520);
    return () => clearTimeout(t);
  }, [open]);

  if (!mounted) return null;
  const handlers = { camera: onCamera, photo: onPhoto, file: onFile };

  return (
    <View style={styles.wrap} pointerEvents="box-none">
      <Liquid blur={6} contrast={18} fill="#ffffff" shadow="0 2px 8px rgba(33,28,21,.10)" style={styles.liquid}>
        {/* Silhouette that bridges the droplets back to the + button in the bar. */}
        <Liquid.Item x={0} y={0} width={BTN} height={BTN} style={styles.slot} />
        {ACTIONS.map((a, i) => (
          <Liquid.Item
            key={a.key}
            x={spread ? a.x : 0}
            y={spread ? a.y : 0}
            transition="bouncy"
            delay={i * 40}
            width={BTN}
            height={BTN}
            style={styles.slot}
          >
            <Pressable
              accessibilityLabel={a.label}
              hitSlop={4}
              style={styles.btn}
              onPress={() => {
                if (Platform.OS !== 'web') Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
                onClose();
                handlers[a.key as keyof typeof handlers]();
              }}
            >
              <Feather name={a.icon} size={20} color={color.accent} />
            </Pressable>
          </Liquid.Item>
        ))}
      </Liquid>
    </View>
  );
}

const styles = StyleSheet.create({
  // Left edge lines the first droplet up over the + button (16 gutter + 8 inset + 18 half - 23 half).
  wrap: { height: H, marginLeft: spacing.lg + spacing.sm + 18 - BTN / 2, marginBottom: -spacing.sm - 6 },
  liquid: { flex: 1 },
  slot: { position: 'absolute', left: 0, top: H - BTN, width: BTN, height: BTN },
  btn: { width: BTN, height: BTN, borderRadius: BTN / 2, alignItems: 'center', justifyContent: 'center' },
});
