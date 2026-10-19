import React from 'react';
import { View, StyleSheet, DimensionValue } from 'react-native';
import { Image } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
import { color } from '@/theme';

/**
 * Full-bleed hero banner for the pairing/splash screens. A slowly turning,
 * gently breathing animated illustration on the same warm ivory as
 * `color.bg`, so instead of floating it in a small box (which would show a
 * hard rectangle edge), we let it fill the top of the screen and fade into
 * `color.bg` at the edges — same trick a lot of app store hero shots use so
 * the image reads as part of the screen, not a sticker on top of it.
 * `expo-image` is used instead of the RN core `Image` since it plays
 * animated GIFs natively on both iOS and Android.
 */
export function Hero({ height = 340 }: { height?: DimensionValue }) {
  return (
    <View style={[styles.wrap, { height }]}>
      <Image
        source={require('../../assets/hero.gif')}
        style={styles.image}
        contentFit="cover"
        autoplay
      />
      {/* Soft top fade so the status bar area doesn't show a hard image edge either. */}
      <LinearGradient
        colors={[color.bg, 'transparent']}
        style={styles.topFade}
        start={{ x: 0.5, y: 0 }}
        end={{ x: 0.5, y: 1 }}
      />
      <LinearGradient
        colors={['transparent', color.bg]}
        style={styles.bottomFade}
        start={{ x: 0.5, y: 0 }}
        end={{ x: 0.5, y: 1 }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { width: '100%', overflow: 'hidden' },
  image: { width: '100%', height: '100%' },
  topFade: { position: 'absolute', top: 0, left: 0, right: 0, height: '18%' },
  bottomFade: { position: 'absolute', bottom: 0, left: 0, right: 0, height: '55%' },
});
