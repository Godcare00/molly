import React from 'react';
import Markdown from 'react-native-markdown-display';
import { color, radius, spacing } from '@/theme';
import { useTypography } from '@/context/TypographyContext';

export function MarkdownText({ content, tone = 'light' }: { content: string; tone?: 'light' | 'dark' }) {
  const { type } = useTypography();
  const textColor = tone === 'light' ? color.textPrimary : color.textPrimary;
  return (
    <Markdown
      style={{
        body: { color: textColor, fontFamily: type.body.fontFamily, fontSize: 15, lineHeight: 21 },
        heading1: { color: textColor, fontFamily: type.h1.fontFamily, fontSize: 19, marginTop: spacing.sm },
        heading2: { color: textColor, fontFamily: type.h1.fontFamily, fontSize: 17, marginTop: spacing.sm },
        strong: { fontFamily: type.bodyMedium.fontFamily },
        code_inline: {
          backgroundColor: color.surfaceHigh,
          color: color.accent,
          fontFamily: type.mono.fontFamily,
          fontSize: 13,
          paddingHorizontal: 4,
          borderRadius: 4,
        },
        code_block: {
          backgroundColor: color.bgElevated,
          color: color.textPrimary,
          fontFamily: type.mono.fontFamily,
          fontSize: 13,
          borderRadius: radius.md,
          padding: spacing.md,
        },
        fence: {
          backgroundColor: color.bgElevated,
          color: color.textPrimary,
          fontFamily: type.mono.fontFamily,
          fontSize: 13,
          borderRadius: radius.md,
          padding: spacing.md,
        },
        bullet_list_icon: { color: color.textSecondary },
        link: { color: color.accent },
      }}
    >
      {content}
    </Markdown>
  );
}
