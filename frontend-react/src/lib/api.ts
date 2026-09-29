/** API 请求与 SSE 流式封装 */
import { API_BASE } from '../config';
import type {
  ActiveModel,
  ChatStreamEvent,
  ConversationRecord,
  FileInfo,
  FixResult,
  KnowledgeDoc,
  KnowledgeStats,
  ModelConfigInfo,
  SessionInfo,
  SupportedPlatform,
} from './types';

export { API_BASE };

async function request(url: string, options: RequestInit = {}): Promise<Response> {
  const token = localStorage.getItem('auth_token');
  const headers: Record<string, string> = { ...(options.headers as Record<string, string>) };
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${url}`, { ...options, headers });
  if (res.status === 401) {
    localStorage.removeItem('auth_token');
    window.location.reload();
    throw new Error('登录已过期');
  }
  return res;
}

export async function apiJson<T = unknown>(url: string, options: RequestInit = {}): Promise<T> {
  const res = await request(url, options);
  if (!res.ok) {
    let detail = `请求失败 (HTTP ${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail && typeof body.detail === 'string') detail = body.detail;
    } catch { /* 忽略非 JSON 错误体 */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

/** POST SSE 流式请求:解析 "data: {...}" 行,逐事件回调 */
export async function streamSSE(
  url: string,
  body: unknown,
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await request(url, {
    method: 'POST',
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    let detail = `请求失败 (HTTP ${res.status})`;
    try {
      const j = await res.json();
      if (j?.detail && typeof j.detail === 'string') detail = j.detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith('data:')) continue;
      const payload = trimmed.slice(5).trim();
      if (!payload || payload === '[DONE]') continue;
      try {
        onEvent(JSON.parse(payload));
      } catch { /* 忽略无法解析的事件 */ }
    }
  }
}

// ========== 会话 ==========
export const listSessions = () =>
  apiJson<{ sessions: SessionInfo[]; total: number }>('/sessions');

export const createSession = (name: string) =>
  apiJson<SessionInfo>('/sessions', { method: 'POST', body: JSON.stringify({ name }) });

export const renameSession = (sessionId: string, name: string) =>
  apiJson<SessionInfo>(`/sessions/${sessionId}`, { method: 'PUT', body: JSON.stringify({ name }) });

export const deleteSession = (sessionId: string) =>
  apiJson<{ message: string }>(`/sessions/${sessionId}`, { method: 'DELETE' });

// ========== 对话历史 ==========
export const listConversations = (sessionId: string) =>
  apiJson<{ conversations: ConversationRecord[]; total: number }>(
    `/conversations?session_id=${encodeURIComponent(sessionId)}&limit=200`,
  );

// ========== 知识库 ==========
export const getKnowledgeList = () =>
  apiJson<{ knowledge: KnowledgeDoc[]; total: number }>('/knowledge/list');

export const getKnowledgeStats = () =>
  apiJson<KnowledgeStats>('/knowledge/stats');

export const addKnowledge = (content: string) =>
  apiJson<{ doc_id: string }>('/knowledge/add', {
    method: 'POST',
    body: JSON.stringify({ content, metadata: { source: 'panel' } }),
  });

export const updateKnowledge = (docId: string, content: string) =>
  apiJson<{ doc_id: string }>(`/knowledge/${docId}`, {
    method: 'PUT',
    body: JSON.stringify({ content, metadata: { updated: 'true' } }),
  });

export const deleteKnowledge = (docId: string) =>
  apiJson<{ message: string }>(`/knowledge/${docId}`, { method: 'DELETE' });

// ========== 模型管理 ==========
export const getPlatforms = () =>
  apiJson<SupportedPlatform[]>('/settings/platforms');

export const getModels = () =>
  apiJson<{ builtin: ModelConfigInfo[]; custom: ModelConfigInfo[] }>('/settings/models');

export const addModel = (p: { api_key: string; api_base_url: string; model_name: string }) =>
  apiJson<{ message: string; id: number }>('/settings/models', { method: 'POST', body: JSON.stringify(p) });

export const updateModel = (
  id: number,
  p: Partial<{ api_key: string; api_base_url: string; model_name: string; is_active: boolean }>,
) => apiJson<{ message: string }>(`/settings/models/${id}`, { method: 'PUT', body: JSON.stringify(p) });

export const deleteModel = (id: number) =>
  apiJson<{ message: string }>(`/settings/models/${id}`, { method: 'DELETE' });

export const getActiveModel = () => apiJson<ActiveModel>('/settings/active');

export const setActiveModel = (id: number) =>
  apiJson<{ message: string }>(`/settings/active/${id}`, { method: 'POST' });

export const clearActiveModel = () =>
  apiJson<{ message: string }>('/settings/active', { method: 'DELETE' });

export const testAIConnection = (p: { api_key: string; api_base_url: string; chat_model: string }) =>
  apiJson<{ success: boolean; message: string }>('/settings/ai/test', { method: 'POST', body: JSON.stringify(p) });

// ========== 文件 ==========
export async function uploadFile(file: File): Promise<FileInfo> {
  const fd = new FormData();
  fd.append('file', file);
  return apiJson<FileInfo>('/files/upload', { method: 'POST', body: fd });
}

// ========== 测试 Agent ==========
export const confirmFix = (taskId: string, issueIndex: number, confirmed: boolean) =>
  apiJson<{ fix_result: FixResult }>('/test/code/fix', {
    method: 'POST',
    body: JSON.stringify({ task_id: taskId, issue_index: issueIndex, confirmed }),
  });

export const stopTest = (taskId: string) =>
  apiJson<{ success: boolean; message: string }>(`/test/stop/${taskId}`, { method: 'POST' });
