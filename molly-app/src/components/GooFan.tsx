import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import Animated, { useAnimatedStyle, useSharedValue, withDelay, withTiming } from 'react-native-reanimated';
import { Feather } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { Platform } from 'react-native';
import { Liquid } from './Liquid';
import { color } from '@/theme';

type IconName = React.ComponentProps<typeof Feather>['name'];

export interface FanItem {
  key: string;
  icon: IconName;
  label: string;
  /** Tints the icon with the accent colour (e.g. a toggle that is on). */
  active?: boolean;
  disabled?: boolean;
  onPress: () => void;
}

const BTN = 40;
const STEP = 44;

function FanIcon({ item, open, index, onDone }: { item: FanItem; open: boolean; index: number; onDone: () => void }) {
  const o = useSharedValue(0);
  useEffect(() => {
    o.value = open ? withDelay(80 + index * 45, withTiming(1, { duration: 160 })) : withTiming(0, { duration: 90 });
  }, [open, index, o]);
  const style = useAnimatedStyle(() => ({ opacity: o.value }));
  return (
    <Animated.View style={style} pointerEvents={open ? 'auto' : 'none'}>
      <Pressable
        accessibilityLabel={item.label}
        disabled={item.disabled}
        hitSlop={2}
        style={styles.btn}
        onPress={() => {
          if (Platform.OS !== 'web') Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
          onDone();
          item.onPress();
        }}
      >
        <Feather name={item.icon} size={19} color={item.disabled ? color.textTertiary : item.active ? color.accent : color.textPrimary} />
      </Pressable>
    </Animated.View>
  );
}

/**
 * A row of header actions that lives inside one button: tap it and the actions
 * split out to the left as gooey droplets, tap again and they pour back in.
 */
export function GooFan({ items }: { items: FanItem[] }) {
  const [open, setOpen] = useState(false);
  const n = items.length;
  const width = BTN + n * STEP;

  return (
    <View style={{ width, height: BTN }} pointerEvents="box-none">
      <Liquid blur={5} contrast={16} fill="#ffffff" shadow="0 2px 8px rgba(33,28,21,.10)" filterPadding={24} style={{ width, height: BTN }}>
        {items.map((item, i) => (
          <Liquid.Item
            key={item.key}
            x={open ? -(i + 1) * STEP : 0}
            transition="bouncy"
            delay={i * 35}
            width={BTN}
            height={BTN}
            style={styles.slot}
          >
            <FanIcon item={item} open={open} index={i} onDone={() => setOpen(false)} />
          </Liquid.Item>
        ))}
        <Liquid.Item width={BTN} height={BTN} scale={open ? 1.06 : 1} style={styles.slot}>
          <Pressable accessibilityLabel={open ? 'Close actions' : 'Open actions'} style={styles.btn} onPress={() => setOpen((o) => !o)}>
            <Feather name={open ? 'x' : 'more-horizontal'} size={20} color={open ? color.accent : color.textPrimary} />
          </Pressable>
        </Liquid.Item>
      </Liquid>
    </View>
  );
}

const styles = StyleSheet.create({
  slot: { position: 'absolute', right: 0, top: 0, width: BTN, height: BTN },
  btn: { width: BTN, height: BTN, borderRadius: BTN / 2, alignItems: 'center', justifyContent: 'center' },
});
