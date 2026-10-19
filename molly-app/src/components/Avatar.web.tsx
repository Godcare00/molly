import React from 'react';
import { BotAvatar } from 'bot-avatars';

/**
 * Web build: Molly is a living bot avatar from Libraries.dev's `bot-avatars`
 * (plush clover that turns, hops and works). Metro picks this over Avatar.tsx
 * on web. bot-avatars' React Native port isn't published and needs Skia 2 /
 * Reanimated 4, so native keeps the initial-letter avatar.
 */
export function Avatar({ label, size = 36, working = false }: { label: string; size?: number; working?: boolean; paused?: boolean }) {
  return <BotAvatar type="clover" state={working ? 'working' : 'default'} size={size} aria-label={label} />;
}
