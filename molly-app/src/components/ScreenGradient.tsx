import React from 'react';
import { StyleSheet } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { gradient } from '@/theme';

// A faint vertical wash placed behind screen content, so surfaces read as a
// soft gradient backdrop instead of one flat block of color. Render this as
// the first child of a relatively-positioned, flex:1 container.
export function ScreenGradient() {
  return (
    <LinearGradient
      colors={gradient.screen}
      style={StyleSheet.absoluteFill}
      start={{ x: 0.5, y: 0 }}
      end={{ x: 0.5, y: 1 }}
    />
  );
}
