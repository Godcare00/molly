import React, { useState } from 'react';
import { View, TextInput, Pressable, Text, StyleSheet, ScrollView, Alert } from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import * as DocumentPicker from 'expo-document-picker';
import { Feather } from '@expo/vector-icons';
import { BorderBeam } from './BorderBeam';
import { AttachMenu } from './AttachMenu';
import { Liquid } from './Liquid';
import { ImagePreview } from './ImagePreview';
import { FilePreview } from './FilePreview';
import { color, radius, shadow, spacing } from '@/theme';
import { useTypography } from '@/context/TypographyContext';

export interface PendingImage {
  uri: string;
  fileName: string;
  mimeType: string;
}

export interface PendingFile {
  uri: string;
  fileName: string;
  mimeType: string;
  size?: number;
}

export function ChatInput({
  onSend,
  disabled,
  busy,
}: {
  onSend: (text: string, images: PendingImage[], files: PendingFile[]) => void;
  disabled?: boolean;
  /** Molly is working — keeps the beam travelling even when the input isn't focused. */
  busy?: boolean;
}) {
  const { type } = useTypography();
  const [text, setText] = useState('');
  const [focused, setFocused] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [images, setImages] = useState<PendingImage[]>([]);
  const [files, setFiles] = useState<PendingFile[]>([]);

  const addFromLibrary = async () => {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      Alert.alert('Photo access needed', 'Enable photo access in Settings to attach images.');
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({ quality: 0.8, allowsMultipleSelection: true });
    if (!result.canceled) {
      setImages((prev) => [
        ...prev,
        ...result.assets.map((a) => ({
          uri: a.uri,
          fileName: a.fileName ?? `image-${Date.now()}.jpg`,
          mimeType: a.mimeType ?? 'image/jpeg',
        })),
      ]);
    }
  };

  const addFromCamera = async () => {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) {
      Alert.alert('Camera access needed', 'Enable camera access in Settings to take a photo.');
      return;
    }
    const result = await ImagePicker.launchCameraAsync({ quality: 0.8 });
    if (!result.canceled) {
      const a = result.assets[0];
      setImages((prev) => [
        ...prev,
        { uri: a.uri, fileName: a.fileName ?? `photo-${Date.now()}.jpg`, mimeType: a.mimeType ?? 'image/jpeg' },
      ]);
    }
  };

  const addFile = async () => {
    const result = await DocumentPicker.getDocumentAsync({
      type: '*/*',
      multiple: true,
      copyToCacheDirectory: true,
    });
    if (result.canceled) return;
    setFiles((prev) => [
      ...prev,
      ...result.assets.map((a) => ({
        uri: a.uri,
        fileName: a.name ?? `file-${Date.now()}`,
        mimeType: a.mimeType ?? 'application/octet-stream',
        size: a.size ?? undefined,
      })),
    ]);
  };

  const submit = () => {
    if (!text.trim() && images.length === 0 && files.length === 0) return;
    setMenuOpen(false);
    onSend(text.trim(), images, files);
    setText('');
    setImages([]);
    setFiles([]);
  };

  const hasAttachments = images.length > 0 || files.length > 0;

  return (
    <View style={styles.container}>
      {hasAttachments && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.imageRow}>
          <Liquid blur={5} contrast={16} fill="#ffffff" shadow="0 2px 8px rgba(33,28,21,.10)" filterPadding={24} style={{ flexDirection: 'row', gap: 4, paddingVertical: 4 }}>
            {images.map((img, i) => (
              <Liquid.Item key={img.uri + i} from={{ x: -40, scale: 0.4 }} transition="bouncy" delay={i * 60} radius={radius.md}>
                <ImagePreview uri={img.uri} onRemove={() => setImages((prev) => prev.filter((_, idx) => idx !== i))} />
              </Liquid.Item>
            ))}
            {files.map((file, i) => (
              <Liquid.Item key={file.uri + i} from={{ x: -40, scale: 0.4 }} transition="bouncy" delay={(images.length + i) * 60} radius={radius.md}>
                <FilePreview
                  fileName={file.fileName}
                  size={file.size}
                  onRemove={() => setFiles((prev) => prev.filter((_, idx) => idx !== i))}
                />
              </Liquid.Item>
            ))}
          </Liquid>
        </ScrollView>
      )}
      <AttachMenu
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        onCamera={addFromCamera}
        onPhoto={addFromLibrary}
        onFile={addFile}
      />
      <View style={styles.beamShadow}>
      <BorderBeam size="md" colorVariant="colorful" theme="light" strength={0.7} borderRadius={radius.xl} active={focused || !!busy}>
      <View style={styles.inputRow}>
        <Pressable onPress={() => setMenuOpen((o) => !o)} style={styles.iconButton} hitSlop={8} accessibilityLabel="Attach">
          <Feather name={menuOpen ? 'x' : 'plus'} size={20} color={menuOpen ? color.accent : color.textSecondary} />
        </Pressable>
        <TextInput
          value={text}
          onChangeText={setText}
          placeholder="Ask Molly anything"
          placeholderTextColor={color.textTertiary}
          style={[styles.input, { fontFamily: type.body.fontFamily, fontSize: type.body.fontSize }]}
          cursorColor={color.accent}
          selectionColor={color.accent}
          multiline
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
        />
        <Pressable
          onPress={submit}
          disabled={disabled || (!text.trim() && !hasAttachments)}
          style={[
            styles.sendButton,
            (disabled || (!text.trim() && !hasAttachments)) && styles.sendButtonDisabled,
          ]}
        >
          <Feather
            name="arrow-up"
            size={18}
            color={disabled || (!text.trim() && !hasAttachments) ? color.textTertiary : color.white}
          />
        </Pressable>
      </View>
      </BorderBeam>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.md,
    gap: spacing.sm,
  },
  imageRow: { paddingLeft: 2 },
  beamShadow: { borderRadius: radius.xl, ...shadow.soft },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    backgroundColor: color.bgElevated,
    borderRadius: radius.xl,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    gap: spacing.xs,
  },
  iconButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  input: {
    flex: 1,
    color: color.textPrimary,
    maxHeight: 120,
    paddingVertical: 8,
  },
  sendButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: color.accent,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendButtonDisabled: { backgroundColor: color.surfaceHigh },
});
