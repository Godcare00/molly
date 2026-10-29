import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View,
  Text,
  FlatList,
  Pressable,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { Feather } from '@expo/vector-icons';
import { useConversations } from '@/context/ConversationsContext';
import { useTypography } from '@/context/TypographyContext';
import { useConversation } from '@/hooks/useConversation';
import { useApprovals } from '@/hooks/useApprovals';
import { useLiveVoice } from '@/hooks/useLiveVoice';
import { imagesApi } from '@/api/images';
import { filesApi } from '@/api/files';
import { conversationsApi } from '@/api/conversations';
import { MessageBubble } from '@/components/MessageBubble';
import { ApprovalCard } from '@/components/ApprovalCard';
import { TypingIndicator } from '@/components/TypingIndicator';
import { orbStateForTool } from '@/components/ThinkingOrb';
import { ChatInput, type PendingImage, type PendingFile } from '@/components/ChatInput';
import { LiveVoiceBar } from '@/components/LiveVoiceBar';
import { EmptyState } from '@/components/EmptyState';
import { LoadingState } from '@/components/LoadingState';
import { ErrorState } from '@/components/ErrorState';
import { GooFan, type FanItem } from '@/components/GooFan';
import { ScrollDroplet } from '@/components/ScrollDroplet';
import { useToast } from '@/components/ToastProvider';
import { StatusDot } from '@/components/StatusDot';
import { ScreenGradient } from '@/components/ScreenGradient';
import { ConversationDrawer } from '@/components/ConversationDrawer';
import { color, spacing } from '@/theme';
import type { Message } from '@/types/api';

export function ChatScreen() {
  const { type } = useTypography();
  const navigation = useNavigation<any>();
  const { activeId, conversations, loading: conversationsLoading, createConversation, setActiveId } = useConversations();
  const { messages, loading, error, sending, agentRunning, sendMessage, reload } = useConversation(activeId);
  const { pending, respond } = useApprovals(activeId ?? undefined);
  const liveVoice = useLiveVoice();
  const [respondingId, setRespondingId] = useState<string | null>(null);
  const [creatingChat, setCreatingChat] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [allowAll, setAllowAll] = useState(false);
  const listRef = useRef<FlatList<Message>>(null);
  const toast = useToast();
  const [away, setAway] = useState(false);
  const [unread, setUnread] = useState(0);
  const nearBottomRef = useRef(true);
  const seenCountRef = useRef(0);

  const runningTool = [...messages].reverse().flatMap((m) => m.tool_calls ?? []).find((t) => t.status === 'running');
  const activeConversation = conversations.find((c) => c.id === activeId);

  // The conversations list (GET /conversations) doesn't carry metadata, so
  // allow_all's current value has to come from the single-conversation
  // fetch whenever the active conversation changes.
  useEffect(() => {
    let cancelled = false;
    if (!activeId) {
      setAllowAll(false);
      return;
    }
    conversationsApi
      .get(activeId)
      .then((conv) => {
        if (!cancelled) setAllowAll(Boolean(conv.metadata?.allow_all));
      })
      .catch(() => {
        // Non-critical - the toggle just starts showing "off" until the
        // person retries or switches conversations again.
      });
    return () => {
      cancelled = true;
    };
  }, [activeId]);

  const toggleAllowAll = useCallback(async () => {
    if (!activeId) return;
    const next = !allowAll;
    setAllowAll(next);
    try {
      await conversationsApi.updateSettings(activeId, { allow_all: next });
    } catch {
      setAllowAll(!next); // revert on failure
      toast.show("Couldn't change the approval setting", 'error');
      return;
    }
    toast.show(next ? 'Approvals off for this chat' : 'Approvals required again', 'success');
  }, [activeId, allowAll, toast]);

  // Switching conversations tears down and reopens the socket under the
  // hood (see WebSocketContext) - a live session belongs to whichever
  // conversation it was started on, so don't let it linger pointed at a
  // socket that's now serving a different one.
  const prevActiveIdRef = useRef(activeId);
  useEffect(() => {
    if (prevActiveIdRef.current !== activeId && liveVoice.status !== 'idle') {
      liveVoice.stop();
    }
    prevActiveIdRef.current = activeId;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);


  const startNewChat = useCallback(async () => {
    if (creatingChat) return;
    setCreatingChat(true);
    try {
      await createConversation();
    } finally {
      setCreatingChat(false);
    }
  }, [createConversation, creatingChat]);

  const handleSend = useCallback(
    async (text: string, images: PendingImage[], files: PendingFile[]) => {
      let conversationId = activeId;
      if (!conversationId) {
        const created = await createConversation();
        conversationId = created.id;
      }
      // Images and files must be uploaded first — the WS `message` event only
      // takes the resulting ids, not the file data itself.
      const attachments: ({ type: 'image'; image_id: string } | { type: 'file'; file_id: string })[] = [];
      for (const img of images) {
        try {
          const uploaded = await imagesApi.upload(conversationId, img.uri, img.fileName, img.mimeType);
          attachments.push({ type: 'image', image_id: uploaded.image_id });
        } catch {
          toast.show(`Couldn't upload ${img.fileName ?? 'image'}`, 'error');
        }
      }
      for (const file of files) {
        try {
          const uploaded = await filesApi.upload(conversationId, file.uri, file.fileName, file.mimeType);
          attachments.push({ type: 'file', file_id: uploaded.file_id });
        } catch {
          toast.show(`Couldn't upload ${file.fileName ?? 'file'}`, 'error');
        }
      }
      if (text || attachments.length) sendMessage(text, attachments);
    },
    [activeId, createConversation, sendMessage, toast],
  );

  useEffect(() => {
    const n = messages.length;
    if (n > seenCountRef.current && !nearBottomRef.current) setUnread((u) => u + (n - seenCountRef.current));
    seenCountRef.current = n;
  }, [messages.length]);

  useEffect(() => {
    if (liveVoice.error) toast.show(liveVoice.error, 'error');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveVoice.error]);

  const jumpToLatest = useCallback(() => {
    listRef.current?.scrollToEnd({ animated: true });
    setUnread(0);
  }, []);

  const fanItems: FanItem[] = [
    { key: 'lock', icon: allowAll ? 'unlock' : 'lock', label: allowAll ? 'Approvals off - tap to require approval again' : 'Require approval for risky actions', active: allowAll, disabled: !activeId, onPress: toggleAllowAll },
    { key: 'mic', icon: liveVoice.status === 'idle' ? 'mic' : 'mic-off', label: 'Live voice', active: liveVoice.status !== 'idle', disabled: !activeId, onPress: () => (liveVoice.status === 'idle' ? liveVoice.start() : liveVoice.stop()) },
    { key: 'new', icon: 'plus', label: 'New chat', disabled: creatingChat, onPress: startNewChat },
    { key: 'settings', icon: 'settings', label: 'Settings', onPress: () => navigation.navigate('Settings') },
  ];

  const handleApprovalAction = useCallback(
    (approvalId: string, action: 'approve' | 'approve_all' | 'reject' | 'correct', instruction?: string) => {
      // respond() sends over the socket and resolves synchronously from the
      // UI's perspective (it optimistically clears the pending entry) -
      // respondingId just gives the tapped button a brief loading state.
      setRespondingId(approvalId);
      respond(approvalId, action, instruction);
      setRespondingId(null);
    },
    [respond],
  );

  return (
    <SafeAreaView style={styles.container}>
      <ScreenGradient />
      <View style={styles.header}>
        <Pressable onPress={() => setDrawerOpen(true)} hitSlop={8}>
          <Feather name="menu" size={22} color={color.textPrimary} />
        </Pressable>
        <GooFan items={fanItems} />
      </View>

      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}
      >
        {conversationsLoading || (loading && messages.length === 0) ? (
          <LoadingState />
        ) : error && messages.length === 0 ? (
          <ErrorState message={error} onRetry={reload} />
        ) : messages.length === 0 ? (
          <EmptyState
            title="Ask Molly anything"
            message={
              activeConversation?.title
                ? `You're chatting in "${activeConversation.title}".`
                : 'Check server health, investigate an issue, or ship a deploy. Molly can do it safely, with your approval on anything risky.'
            }
          />
        ) : (
          <View style={styles.flex}>
          <FlatList
            ref={listRef}
            data={messages}
            keyExtractor={(m) => m.id}
            renderItem={({ item }) => <MessageBubble message={item} />}
            contentContainerStyle={styles.listContent}
            ListFooterComponent={agentRunning || sending ? <TypingIndicator state={orbStateForTool(runningTool?.name)} /> : null}
            scrollEventThrottle={64}
            onScroll={(e) => {
              const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
              const dist = contentSize.height - layoutMeasurement.height - contentOffset.y;
              nearBottomRef.current = dist < 120;
              const isAway = dist > 300;
              setAway((a) => (a === isAway ? a : isAway));
              if (dist < 120) setUnread((u) => (u ? 0 : u));
            }}
            onContentSizeChange={() => {
              if (nearBottomRef.current) listRef.current?.scrollToEnd({ animated: true });
            }}
          />
          <ScrollDroplet visible={away} unread={unread} onPress={jumpToLatest} />
          </View>
        )}

        {pending.map((approval) => (
          <ApprovalCard
            key={approval.id}
            approval={approval}
            busy={respondingId === approval.id}
            onApprove={() => handleApprovalAction(approval.id, 'approve')}
            onApproveAll={() => handleApprovalAction(approval.id, 'approve_all')}
            onReject={() => handleApprovalAction(approval.id, 'reject')}
            onCorrect={(instruction) => handleApprovalAction(approval.id, 'correct', instruction)}
          />
        ))}

        {liveVoice.status === 'idle' ? (
          <ChatInput onSend={handleSend} disabled={sending} busy={agentRunning || sending} />
        ) : (
          <LiveVoiceBar
            status={liveVoice.status}
            transcript={liveVoice.transcript}
            error={liveVoice.error}
            onStop={liveVoice.stop}
            getLevel={liveVoice.getLevel}
          />
        )}
      </KeyboardAvoidingView>

      <ConversationDrawer
        visible={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onSelect={setActiveId}
        onNew={startNewChat}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  flex: { flex: 1 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  headerCenter: { alignItems: 'center' },
  headerTitle: { color: color.textPrimary },
  headerRight: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  onlineRow: { flexDirection: 'row', alignItems: 'center', gap: 5, marginTop: 2 },
  onlineText: { color: color.textSecondary },
  listContent: { paddingVertical: spacing.lg },
});
