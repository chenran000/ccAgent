/** 共享类型定义 */

// ========== 会话 ==========
export interface SessionInfo {
  session_id: string;
  name: string;
  created_at: string;
  updated_at: string;
}

// 后端对话记录(历史恢复用)
export interface ConversationRecord {
  id: number;
  session_id: string;
  module: string;
  input_text: string;
  output_data: string;
  created_at: string;
}

// ========== 模型配置 ==========
export interface ModelConfigInfo {
  id: number;
  platform: string;
  platform_name: string;
  api_key_masked?: string;
  api_base_url: string;
  model_name: string;
  is_active: boolean;
  created_at: string;
}

export interface SupportedPlatform {
  key: string;
  name: string;
  icon: string;
  default_base_url: string;
}

export interface ActiveModel {
  use_default: boolean;
  model_config_id?: number;
  model_name?: string;
  platform?: string;
}

// ========== 知识库 ==========
export interface KnowledgeDoc {
  doc_id: string;
  content: string;
  metadata: Record<string, unknown>;
  chunk_count: number;
}

export interface KnowledgeStats {
  total_docs: number;
  index_ready: boolean;
}

// ========== 文件 ==========
export interface FileInfo {
  id: number;
  original_filename: string;
  file_type: string;
  file_size: number;
}

// ========== 聊天消息(前端渲染模型) ==========
export interface AgentStep {
  step: number;
  action: string;
  target: string;
  result: string;
  success: boolean;
}

export interface WriteConfirm {
  changeId: string;
  path: string;
  diff: string;
  kind?: 'write' | 'command'; // write=展示 diff;command=展示待执行命令
  resolved?: boolean; // 用户已裁决(避免重复提交)
}

export interface VerifyIssue {
  severity: string;
  file: string;
  line: number;
  rule_id: string;
  message: string;
}

export interface VerifyInfo {
  files: string[];
  clean: boolean;
  remaining: VerifyIssue[];
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  module: string; // agent / chat / code / case / knowledge
  text: string;
  data?: Record<string, unknown>;
  references?: string[];
  agentSteps?: AgentStep[];
  confirm?: WriteConfirm;
  verify?: VerifyInfo;
  pending?: boolean;
  error?: string;
  createdAt: string;
}

export interface ChatStreamEvent {
  type: string;
  [key: string]: unknown;
}

// ========== 工作区 ==========
export interface FileNode {
  name: string;
  path: string;
  type: 'file' | 'directory';
  size?: number;
  children?: FileNode[];
}
