import 'react-native-get-random-values';
import 'react-native-gesture-handler';

import React, { useCallback, useEffect } from 'react';
import { View, StyleSheet } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import * as SplashScreenModule from 'expo-splash-screen';
import {
  useFonts as useInterFonts,
  Inter_400Regular,
  Inter_500Medium,
  Inter_600SemiBold,
  Inter_700Bold,
} from '@expo-google-fonts/inter';
import {
  useFonts as useMonoFonts,
  JetBrainsMono_400Regular,
  JetBrainsMono_500Medium,
  JetBrainsMono_600SemiBold,
  JetBrainsMono_700Bold,
} from '@expo-google-fonts/jetbrains-mono';

import { AuthProvider } from '@/context/AuthContext';
import { ToastProvider } from '@/components/ToastProvider';
import { TypographyProvider } from '@/context/TypographyContext';
import { RootNavigator } from '@/navigation/RootNavigator';
import { color } from '@/theme';

SplashScreenModule.preventAutoHideAsync().catch(() => {});

export default function App() {
  const [interLoaded] = useInterFonts({ Inter_400Regular, Inter_500Medium, Inter_600SemiBold, Inter_700Bold });
  const [monoLoaded] = useMonoFonts({
    JetBrainsMono_400Regular,
    JetBrainsMono_500Medium,
    JetBrainsMono_600SemiBold,
    JetBrainsMono_700Bold,
  });
  const fontsReady = interLoaded && monoLoaded;

  const onLayout = useCallback(async () => {
    if (fontsReady) await SplashScreenModule.hideAsync();
  }, [fontsReady]);

  useEffect(() => {
    onLayout();
  }, [onLayout]);

  if (!fontsReady) return null;

  return (
    <SafeAreaProvider>
      <View style={styles.root}>
        <StatusBar style="dark" />
        <TypographyProvider>
          <AuthProvider>
            <ToastProvider>
              <RootNavigator />
            </ToastProvider>
          </AuthProvider>
        </TypographyProvider>
      </View>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: color.bg },
});
