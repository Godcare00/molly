import { useCallback, useEffect, useRef, useState } from 'react';
import { AudioContext, AudioManager, AudioRecorder } from 'react-native-audio-api';
import type { AudioBufferQueueSourceNode } from 'react-native-audio-api';
import { useWebSocket, type WsEvent } from '@/context/WebSocketContext';
import { float32ToPcm16Base64, pcm16Base64ToFloat32 } from '@/utils/audioCodec';

/**
 * Hands-free voice mode for one conversation. Wraps mic capture + playback
 * (react-native-audio-api) around the WebSocketContext's live_* protocol,
 * which talks to app/agent/live_executor.py on the backend.
 *
 * Scope note (v1): this only runs while the chat screen is open and the app
 * is foregrounded — there's no background mode or wake word. Starting a
 * session is still a deliberate tap; "hands-free" describes the
 * conversation itself (no typing, spoken approvals) rather than
 * always-on listening. Backgrounding the app or leaving the screen ends
 * the session the same way closing the mic would.
 *
 * Fixed audio rates below are dictated by the Gemini Live API, not a
 * preference - see app/llm/gemini_live.py.
 */

export type LiveVoiceStatus =
  | 'idle'
  | 'connecting'
  | 'listening'
  | 'speaking'
  | 'awaiting_confirmation'
  | 'error';

export interface LiveTranscriptLine {
  role: 'user' | 'assistant';
  text: string;
}

const INPUT_SAMPLE_RATE = 16000;
const OUTPUT_SAMPLE_RATE = 24000;
// 100ms per chunk: small enough to feel responsive, large enough not to spam the socket.
const INPUT_CHUNK_SAMPLES = 1600;

/** Loudness 0–1 of a PCM chunk (speech RMS is small, so it's scaled up and clamped). */
function loudness(samples: Float32Array): number {
  if (!samples.length) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  return Math.min(1, Math.sqrt(sum / samples.length) * 5);
}

export function useLiveVoice() {
  const { addListener, startLive, stopLive, sendAudioChunk, sendAudioStreamEnd } = useWebSocket();
  const [status, setStatus] = useState<LiveVoiceStatus>('idle');
  const [transcript, setTranscript] = useState<LiveTranscriptLine[]>([]);
  const [error, setError] = useState<string | null>(null);

  const recorderRef = useRef<AudioRecorder | null>(null);
  const playbackContextRef = useRef<AudioContext | null>(null);
  const queueSourceRef = useRef<AudioBufferQueueSourceNode | null>(null);
  const activeRef = useRef(false);
  // Latest mic / assistant-voice loudness, for the VoiceBeam glow.
  const micLevelRef = useRef({ value: 0, at: 0 });
  const outLevelRef = useRef({ value: 0, at: 0 });
  /** 0–1 loudness of whoever is talking right now (read it every frame; it's a ref, not state). */
  const getLevel = useCallback(() => {
    const now = Date.now();
    if (now - outLevelRef.current.at < 250) return outLevelRef.current.value;
    return now - micLevelRef.current.at < 250 ? micLevelRef.current.value : 0;
  }, []);

  const flushPlayback = useCallback(() => {
    // Barge-in / session end: drop whatever's queued rather than let it
    // keep talking over the person.
    if (queueSourceRef.current) {
      try {
        queueSourceRef.current.stop();
      } catch {
        // Already stopped/ended - fine to ignore.
      }
      queueSourceRef.current = null;
    }
  }, []);

  const enqueuePlayback = useCallback((base64Pcm16: string) => {
    const ctx = playbackContextRef.current;
    if (!ctx) return;
    const float32 = pcm16Base64ToFloat32(base64Pcm16);
    if (float32.length === 0) return;
    outLevelRef.current = { value: loudness(float32), at: Date.now() };

    const buffer = ctx.createBuffer(1, float32.length, OUTPUT_SAMPLE_RATE);
    buffer.copyToChannel(float32 as Float32Array<ArrayBuffer>, 0);

    if (!queueSourceRef.current) {
      const source = ctx.createBufferQueueSource();
      source.connect(ctx.destination);
      source.start(ctx.currentTime);
      queueSourceRef.current = source;
    }
    queueSourceRef.current.enqueueBuffer(buffer);
    setStatus((prev) => (prev === 'awaiting_confirmation' ? prev : 'speaking'));
  }, []);

  const stopRecorder = useCallback(() => {
    if (recorderRef.current) {
      try {
        recorderRef.current.clearOnAudioReady();
        recorderRef.current.stop().catch(() => {});
      } catch {
        // Ignore - already stopped.
      }
      recorderRef.current = null;
    }
  }, []);

  const start = useCallback(async () => {
    setError(null);
    setTranscript([]);
    setStatus('connecting');
    activeRef.current = true;

    const permission = await AudioManager.requestRecordingPermissions();
    if (permission !== 'Granted') {
      setStatus('error');
      setError('Microphone access is needed for hands-free mode. Enable it in Settings.');
      activeRef.current = false;
      return;
    }

    AudioManager.setAudioSessionOptions({
      iosCategory: 'playAndRecord',
      iosMode: 'voiceChat',
      iosOptions: ['defaultToSpeaker', 'allowBluetoothHFP'],
    });

    playbackContextRef.current = new AudioContext({ sampleRate: OUTPUT_SAMPLE_RATE });

    const recorder = new AudioRecorder();
    recorder.onAudioReady(
      { sampleRate: INPUT_SAMPLE_RATE, bufferLength: INPUT_CHUNK_SAMPLES, channelCount: 1 },
      ({ buffer }) => {
      if (!activeRef.current) return;
      micLevelRef.current = { value: loudness(buffer.getChannelData(0)), at: Date.now() };
      sendAudioChunk(float32ToPcm16Base64(buffer.getChannelData(0)));
      },
    );
    recorderRef.current = recorder;

    // Actual mic capture only begins once the backend confirms the Gemini
    // session is up (the `live_started` handler below) - starting eagerly
    // would just stream audio into a socket nobody's listening on yet.
    startLive();
  }, [startLive, sendAudioChunk]);

  const stop = useCallback(() => {
    if (!activeRef.current && status === 'idle') return;
    activeRef.current = false;
    sendAudioStreamEnd();
    stopLive();
    stopRecorder();
    flushPlayback();
    playbackContextRef.current?.close();
    playbackContextRef.current = null;
    setStatus('idle');
  }, [sendAudioStreamEnd, stopLive, stopRecorder, flushPlayback, status]);

  useEffect(() => {
    const handle = (event: WsEvent) => {
      switch (event.type) {
        case 'live_started':
          recorderRef.current?.start().catch(() => {});
          setStatus('listening');
          break;

        case 'audio_output':
          enqueuePlayback(event.data);
          break;

        case 'live_transcript':
          if (event.final) {
            setTranscript((prev) => [...prev, { role: event.role, text: event.text }]);
          } else if (event.role === 'user') {
            // A fresh partial from the person talking is a reasonable
            // signal we're not mid-narration anymore, even before the
            // backend's next event confirms it.
            setStatus((prev) => (prev === 'speaking' ? 'listening' : prev));
          }
          break;

        case 'live_interrupted':
          flushPlayback();
          setStatus('listening');
          break;

        case 'approval_required':
          setStatus('awaiting_confirmation');
          break;

        case 'approval_rejected':
        case 'approval_timeout':
        case 'approval_corrected':
          setStatus('listening');
          break;

        case 'live_error':
          setError(event.error);
          break;

        case 'live_stopped':
          activeRef.current = false;
          stopRecorder();
          flushPlayback();
          playbackContextRef.current?.close();
          playbackContextRef.current = null;
          setStatus('idle');
          break;

        default:
          break;
      }
    };
    return addListener(handle);
  }, [addListener, enqueuePlayback, flushPlayback, stopRecorder]);

  // Make sure a screen unmount (navigating away mid-session) can't leave the
  // mic running or the socket in live mode.
  useEffect(() => {
    return () => {
      if (activeRef.current) stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { status, transcript, error, start, stop, getLevel };
}
