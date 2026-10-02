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

// ========== Web 测试 Agent ==========
export interface TestStep {
  step: number;
  action: string;
  target: string;
  result: string;
  success: boolean;
  selector?: string;
  screenshot_path?: string;
  console_errors: string[];
  network_errors: string[];
}

export interface CodeIssue {
  file_path: string;
  line_number: number;
  issue_description: string;
  error_log: string;
  suggested_fix: string;
  code_snippet?: string | null;
}

export interface FixResult {
  issue_index: number;
  confirmed: boolean;
  success: boolean;
  message: string;
  fixed_code?: string;
  fix_description?: string;
}

export type TestRunStatus = 'running' | 'awaiting_confirm' | 'completed' | 'cancelled' | 'failed';

export interface TestRunState {
  taskId?: string;
  url?: string;
  steps: TestStep[];
  issues: CodeIssue[];
  status: TestRunStatus;
  message: string;
  confirmCursor: number;
  results: FixResult[];
  scriptPath?: string;
  reportPath?: string;
}

// ========== 聊天消息(前端渲染模型) ==========
export interface AgentStep {
  step: number;
  action: string;
  target: string;
  result: string;
  success: boolean;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  module: string; // agent / chat / code / case / knowledge / web_test
  text: string;
  data?: Record<string, unknown>;
  references?: string[];
  testRun?: TestRunState;
  agentSteps?: AgentStep[];
  pending?: boolean;
  error?: string;
  createdAt: string;
}

export interface ChatStreamEvent {
  type: string;
  [key: string]: unknown;
}

export function emptyTestRun(): TestRunState {
  return {
    steps: [],
    issues: [],
    status: 'running',
    message: '',
    confirmCursor: 0,
    results: [],
  };
}

// ========== 工作区 ==========
export interface FileNode {
  name: string;
  path: string;
  type: 'file' | 'directory';
  size?: number;
  children?: FileNode[];
}
