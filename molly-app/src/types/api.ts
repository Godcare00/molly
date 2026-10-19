// Types mirrored from https://molly.devs.surf/openapi.json
// Keep these in sync with the backend spec — this is the single source of truth
// for request/response shapes across the app.

export type Platform = 'ios' | 'android' | 'desktop' | 'web';
export type UserRole = 'operator' | 'viewer' | 'admin';

// ---------- Auth / devices ----------

export interface DeviceRegisterRequest {
  public_key: string; // Ed25519 public key, PEM (SPKI)
  device_name: string;
  platform: Platform;
  platform_version?: string | null;
  app_version?: string | null;
}

export interface DeviceRegisterResponse {
  device_id: string;
  challenge: string;
  challenge_expires_at: string;
  pairing_code: string; // shown in-app; entered at the server's /connect page to approve this device
  pairing_code_expires_at: string;
}

export interface DeviceVerifyRequest {
  device_id: string;
  signature: string; // base64url signature of the challenge
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  refresh_expires_in: number;
}

export type RefreshResponse = TokenPair;

export interface DeviceResponse {
  id: string;
  name: string;
  platform: Platform;
  platform_version?: string | null;
  app_version?: string | null;
  key_id: string;
  is_trusted: boolean;
  is_revoked: boolean;
  last_used_at?: string | null;
  last_ip?: string | null;
  created_at: string;
}

export interface DeviceListResponse {
  devices: DeviceResponse[];
}

export interface UserResponse {
  id: string;
  email?: string | null;
  username?: string | null;
  display_name?: string | null;
  avatar_url?: string | null;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  last_login_at?: string | null;
}

// ---------- Conversations / messages ----------

export interface Conversation {
  id: string;
  title: string;
  project_id?: string | null;
  created_at: string;
  updated_at: string;
  last_message_preview?: string | null;
  // Only populated by GET /conversations/{id} (the list endpoint doesn't
  // include it). allow_all is the "no approval prompts in this
  // conversation" setting - see PATCH /conversations/{id}/settings.
  metadata?: { allow_all?: boolean; [key: string]: unknown };
}

export interface ConversationCreate {
  title?: string;
  project_id?: string;
}

export interface ToolCall {
  id: string;
  name: string;
  label?: string;
  status: 'running' | 'complete' | 'error';
  duration_seconds?: number;
  detail?: unknown;
}

export type MessageRole = 'user' | 'assistant' | 'system' | 'tool';

export interface Message {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  content_type: 'text' | 'markdown' | 'image';
  tool_calls?: ToolCall[] | null;
  tool_call_id?: string | null;
  metadata?: (Record<string, unknown> & { attachments?: MessageAttachment[] }) | null;
  created_at: string;
}

export interface MessageCreate {
  role: string;
  content: string;
  content_type?: string;
  tool_calls?: Record<string, unknown>[] | null;
  tool_call_id?: string | null;
  metadata?: Record<string, unknown> | null;
}

// ---------- Approvals ----------

export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'corrected';
export type RiskLevel = 'SAFE' | 'MODERATE' | 'DANGEROUS';

export interface Approval {
  id: string;
  conversation_id: string;
  task_id?: string | null;
  command: string;
  summary?: string | null;
  risk_level: RiskLevel;
  risk_note?: string | null;
  status: ApprovalStatus;
  created_at: string;
  resolved_at?: string | null;
  // The tool this approval is for (e.g. "write_file", "edit_file",
  // "execute_command") - used to label "approve all remaining <tool>
  // actions this task" and to scope that trust on the backend.
  tool?: string;
}

export interface CorrectRequest {
  instruction: string;
}

// ---------- Images ----------

export interface ImageResponse {
  image_id: string;
  path: string;
  mime_type: string;
  width: number;
  height: number;
  size_bytes: number;
  origin?: 'upload' | 'generated';
}

// ---------- Files ----------

export interface FileResponse {
  file_id: string;
  path: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  origin?: 'upload' | 'generated';
}

// ---------- Attachments (files/images Molly sends back on a message) ----------
// Populated server-side via the share_file tool — see
// AgentExecutor._register_shared_attachment in app/agent/executor.py. Lands
// in Message.metadata.attachments, not as a top-level Message field, because
// that's the shape the backend actually serializes (metadata is a free-form
// JSON column — see app/storage/conversations.py).

export interface MessageAttachment {
  type: 'file' | 'image';
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  /** Relative API path, e.g. /conversations/{id}/files/{file_id}/content — pass to filesApi/imagesApi.contentUrl(). */
  url: string;
}

// ---------- Projects ----------

export interface Project {
  id: string;
  name: string;
  path: string;
  description: string;
  stack: string[];
  repository: string;
  branch: string;
  environment: string;
  services: string[];
  commands: Record<string, string>;
  notes: string[];
  created_at?: string;
  updated_at?: string;
}

export interface ProjectCreate {
  id: string;
  name: string;
  path: string;
  description?: string;
  stack?: string[];
  repository?: string;
  branch?: string;
  environment?: string;
  services?: string[];
  commands?: Record<string, string>;
  notes?: string[];
}

export interface ProjectUpdate {
  name?: string;
  path?: string;
  description?: string;
  stack?: string[];
  repository?: string;
  branch?: string;
  environment?: string;
  services?: string[];
  commands?: Record<string, string>;
  notes?: string[];
}

// ---------- Settings ----------

export interface ProviderSettings {
  provider: string;
  base_url: string;
  api_key: string;
  model: string;
  temperature?: number;
  max_tokens?: number;
}

// ---------- Provider chain (multiple providers with automatic failover) ----------

export interface ProviderChainEntry {
  name?: string;
  provider: string;
  base_url: string;
  api_key: string;
  model: string;
  temperature: number;
  max_tokens: number;
}

export interface RetrySettings {
  max_retries: number;
  retry_base_delay_seconds: number;
  retry_max_delay_seconds: number;
}

export interface ProviderChainSettings {
  providers: ProviderChainEntry[];
  retry: RetrySettings;
}

// ---------- Activity (derived client-side from approvals + task events) ----------

export interface ActivityItem {
  id: string;
  title: string;
  subtitle?: string;
  status: 'complete' | 'error' | 'running' | 'pending';
  timestamp: string;
}

export interface ApiErrorBody {
  detail?:
    | { loc: (string | number)[]; msg: string; type: string }[]
    | string
    | { error_code: string; message: string };
}
