import React from 'react';
import { VoiceBeam as WebVoiceBeam } from 'voice-glow';
import type { VoiceBeamProps } from './VoiceBeam';

export type { VoiceBeamProps, VoiceBeamColorVariant, VoiceBeamLevel } from './VoiceBeam';

/** Web build: the real `voice-glow` package (Metro picks this over VoiceBeam.tsx). */
export function VoiceBeam({ style, children, active = true, borderRadius: _r, ...rest }: VoiceBeamProps) {
  return (
    <WebVoiceBeam {...(rest as any)} style={style as any}>
      {children as React.ReactElement}
    </WebVoiceBeam>
  );
}
