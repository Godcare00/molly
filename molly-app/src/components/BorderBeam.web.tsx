import React from 'react';
import { BorderBeam as WebBorderBeam } from 'border-beam';
import type { BorderBeamProps } from './BorderBeam';

export type { BorderBeamProps, BorderBeamSize, BorderBeamColorVariant, BorderBeamTheme } from './BorderBeam';

/**
 * Web build: the real `border-beam` package from Libraries.dev. Metro picks this
 * file over BorderBeam.tsx when bundling for web (react-native-web).
 */
export function BorderBeam({ style, children, ...rest }: BorderBeamProps) {
  return (
    <WebBorderBeam {...(rest as any)} style={style as any}>
      {children as React.ReactElement}
    </WebBorderBeam>
  );
}
