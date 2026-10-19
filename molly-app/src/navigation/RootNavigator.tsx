import React from 'react';
import { NavigationContainer, DarkTheme } from '@react-navigation/native';
import { useAuth } from '@/context/AuthContext';
import { WebSocketProvider } from '@/context/WebSocketContext';
import { ConversationsProvider } from '@/context/ConversationsContext';
import { SplashScreen } from '@/screens/SplashScreen';
import { PairingScreen } from '@/screens/PairingScreen';
import { MainTabs } from '@/navigation/MainTabs';
import { color } from '@/theme';

const navTheme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    background: color.bg,
    card: color.bgElevated,
    text: color.textPrimary,
    border: color.border,
    primary: color.accent,
  },
};

export function RootNavigator() {
  const { status } = useAuth();

  if (status === 'loading') {
    return <SplashScreen />;
  }

  if (status !== 'authenticated') {
    return <PairingScreen />;
  }

  return (
    <WebSocketProvider enabled>
      <ConversationsProvider>
        <NavigationContainer theme={navTheme}>
          <MainTabs />
        </NavigationContainer>
      </ConversationsProvider>
    </WebSocketProvider>
  );
}
