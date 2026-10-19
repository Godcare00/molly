import React from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { ChatScreen } from '@/screens/ChatScreen';
import { ProjectsScreen } from '@/screens/ProjectsScreen';
import { ProjectDetailScreen } from '@/screens/ProjectDetailScreen';
import { ActivityScreen } from '@/screens/ActivityScreen';
import { SettingsScreen } from '@/screens/SettingsScreen';
import { TextDisplayScreen } from '@/screens/TextDisplayScreen';
import { DevicesScreen } from '@/screens/DevicesScreen';
import { ProviderSettingsScreen } from '@/screens/ProviderSettingsScreen';

const ChatStack = createNativeStackNavigator();
const ProjectsStack = createNativeStackNavigator();
const SettingsStack = createNativeStackNavigator();

function ProjectsStackNavigator() {
  return (
    <ProjectsStack.Navigator screenOptions={{ headerShown: false }}>
      <ProjectsStack.Screen name="ProjectsHome" component={ProjectsScreen} />
      <ProjectsStack.Screen name="ProjectDetail" component={ProjectDetailScreen} />
    </ProjectsStack.Navigator>
  );
}

// Projects and Activity used to be their own tabs. There's only one real
// "place" in the app now (Chat) — those two live under Settings instead,
// as rows that push into this stack, same as Devices/LLM provider.
function SettingsStackNavigator() {
  return (
    <SettingsStack.Navigator screenOptions={{ headerShown: false }}>
      <SettingsStack.Screen name="SettingsHome" component={SettingsScreen} />
      <SettingsStack.Screen name="TextDisplay" component={TextDisplayScreen} />
      <SettingsStack.Screen name="Devices" component={DevicesScreen} />
      <SettingsStack.Screen name="ProviderSettings" component={ProviderSettingsScreen} />
      <SettingsStack.Screen name="Projects" component={ProjectsStackNavigator} />
      <SettingsStack.Screen name="Activity" component={ActivityScreen} />
    </SettingsStack.Navigator>
  );
}

// The app now opens straight into Chat — no bottom tab bar. Recent
// conversations live in a slide-in drawer over the chat itself (see
// ConversationDrawer), not a pushed screen. Everything else (Projects,
// Activity, Settings and its sub-screens) is reachable from the menu button
// on the Chat header.
export function MainTabs() {
  return (
    <ChatStack.Navigator screenOptions={{ headerShown: false }}>
      <ChatStack.Screen name="ChatHome" component={ChatScreen} />
      <ChatStack.Screen name="Settings" component={SettingsStackNavigator} />
    </ChatStack.Navigator>
  );
}
