import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Animated, { ZoomIn, ZoomOut } from 'react-native-reanimated';
import { Feather } from '@expo/vector-icons';
import { Liquid } from './Liquid';
import { color } from '@/theme';
import { useTypography } from '@/context/TypographyContext';

const BTN = 44;
const H = 92;

/**
 * "Jump to latest": when you've scrolled up, a droplet pulls away from the
 * input bar below and floats up; it sinks back into the bar when you return.
 * A badge counts messages that arrived while you were away.
 */
export function ScrollDroplet({ visible, unread, onPress }: { visible: boolean; unread: number; onPress: () => void }) {
  const { type } = useTypography();
  return (
    <View style={styles.wrap} pointerEvents="box-none">
      <Liquid blur={6} contrast={18} fill="#ffffff" shadow="0 3px 10px rgba(33,28,21,.12)" filterPadding={24} style={styles.liquid}>
        {/* The bar it separates from: a wide blob resting on the bottom edge. */}
        <Liquid.Item width={92} height={30} radius={15} scale={visible ? 1 : 0} transition="smooth" style={styles.anchor} />
        <Liquid.Item y={visible ? 0 : 56} transition="bouncy" width={BTN} height={BTN} style={styles.drop}>
          <Pressable accessibilityLabel="Jump to latest message" disabled={!visible} onPress={onPress} style={styles.btn}>
            <Feather name="arrow-down" size={20} color={color.accent} />
          </Pressable>
        </Liquid.Item>
      </Liquid>
      {visible && unread > 0 ? (
        <Animated.View entering={ZoomIn.springify().damping(12)} exiting={ZoomOut.duration(120)} style={styles.badge} pointerEvents="none">
          <Text style={[type.micro, styles.badgeText]}>{unread > 9 ? '9+' : unread}</Text>
        </Animated.View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { position: 'absolute', right: 14, bottom: 0, width: 62, height: H },
  liquid: { width: 62, height: H },
  anchor: { position: 'absolute', left: -15, top: H - 12, width: 92, height: 30 },
  drop: { position: 'absolute', left: 9, top: H - BTN - 14, width: BTN, height: BTN },
  btn: { width: BTN, height: BTN, borderRadius: BTN / 2, alignItems: 'center', justifyContent: 'center' },
  badge: {
    position: 'absolute',
    right: 2,
    top: H - BTN - 22,
    minWidth: 20,
    height: 20,
    borderRadius: 10,
    paddingHorizontal: 5,
    backgroundColor: color.accent,
    alignItems: 'center',
    justifyContent: 'center',
  },
  badgeText: { color: color.white },
});
