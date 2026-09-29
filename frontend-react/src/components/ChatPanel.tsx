/** 聊天面板:消息流渲染 + SSE 发送 + 测试运行卡片 + 文件引用 */
import { useEffect, useRef, useState } from 'react';
import {
  BookOpen,
  Bug,
  Eye,
  FileText,
  ListChecks,
  Loader2,
  Paperclip,
  Send,
  Sparkles,
  Square,
  X,
} from 'lucide-react';
import {
  listConversations,
  streamSSE,
  uploadFile,
} from '../lib/api';
import {
  emptyTestRun,
  type ChatMessage,
  type ChatStreamEvent,
  type CodeIssue,
  type ConversationRecord,
  type FileInfo,
  type TestRunState,
  type TestStep,
  type TestRunStatus,
} from '../lib/types';
import TestRunCard from './TestRunCard';

interface ChatPanelProps {
  currentSessionId: string;
  onSessionsChanged: () => void;
  onKnowledgeAdded: () => void;
}

// ---------- 小工具 ----------
const asString = (v: unknown, fallback = ''): string => (typeof v === 'string' ? v : fallback);
const asArray = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);
const asRecord = (v: unknown): Record<string, unknown> | undefined =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : undefined;
const genId = () =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `id-${Date.now()}-${Math.random().toString(36).slice(2)}`;
const pct = (v: unknown): string =>
  typeof v === 'number' && v > 0 ? ` ${Math.round(v * 100)}%` : '';

const SAMPLES = [
  { icon: Bug, text: '帮我测试 http://localhost:5000 的登录功能' },
  { icon: ListChecks, text: '为登录功能生成测试用例' },
  { icon: BookOpen, text: '记住：登录接口超时时间为 30 秒' },
  { icon: Sparkles, text: '分析这个 bug：点击提交按钮后页面无响应' },
];

// ---------- 历史记录映射 ----------
function mapRecordToMessages(rec: ConversationRecord): ChatMessage[] {
  const createdAt = rec.created_at;
  const messages: ChatMessage[] = [
    {
      id: `hist-u-${rec.id}`,
      role: 'user',
      module: rec.module || 'chat',
      text: rec.input_text,
      createdAt,
    },
  ];
  if (rec.module === 'web_test') return messages; // 测试过程不落库
  let parsed: Record<string, unknown> | undefined;
  try {
    parsed = JSON.parse(rec.output_data);
  } catch {
    parsed = undefined;
  }
  if (rec.module === 'chat') {
    messages.push({
      id: `hist-a-${rec.id}`,
      role: 'assistant',
      module: 'chat',
      text: asString(parsed?.answer),
      references: asArray<string>(parsed?.references),
      createdAt,
    });
  } else {
    messages.push({
      id: `hist-a-${rec.id}`,
      role: 'assistant',
      module: rec.module,
      text: '',
      data: parsed,
      createdAt,
    });
  }
  return messages;
}

// ---------- 分析结果卡片 ----------
function BugAnalysisCard({ data }: { data: Record<string, unknown> }) {
  const severity = asString(data.severity, '一般');
  const severityCls =
    severity === '致命' ? 'bg-red-100 text-red-700'
    : severity === '严重' ? 'bg-orange-100 text-orange-700'
    : severity === '一般' ? 'bg-amber-100 text-amber-700'
    : 'bg-gray-100 text-gray-600';
  return (
    <div className="rounded-xl border border-gray-200 bg-gray-50/60 p-3.5 space-y-2.5">
      <div className="flex flex-wrap gap-1.5 text-[11px]">
        <span className="px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 font-medium">
          {asString(data.bug_type, '未知类型')}
          {pct(data.bug_type_confidence)}
        </span>
        <span className={`px-2 py-0.5 rounded-full font-medium ${severityCls}`}>
          {severity}
          {pct(data.severity_confidence)}
        </span>
        <span className="px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">
          {asString(data.scope, '范围未知')}
        </span>
      </div>
      {asString(data.description) && (
        <p className="text-xs text-gray-700 leading-relaxed whitespace-pre-wrap">
          {asString(data.description)}
        </p>
      )}
      {asString(data.suggestion) && (
        <div className="text-xs leading-relaxed">
          <span className="font-medium text-gray-500">修复建议：</span>
          <span className="text-gray-700 whitespace-pre-wrap">{asString(data.suggestion)}</span>
        </div>
      )}
    </div>
  );
}

function TestCaseCard({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-gray-50/60 p-3.5">
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <ListChecks className="w-4 h-4 text-blue-500" />
        <span className="text-xs font-medium text-gray-700">
          测试用例{typeof data.total === 'number' ? ` · 共 ${data.total} 条` : ''}
        </span>
        {data.used_knowledge === true && (
          <span className="px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 text-[10px] font-medium">
            已结合知识库
          </span>
        )}
      </div>
      <pre className="text-xs text-gray-700 whitespace-pre-wrap break-words leading-relaxed max-h-96 overflow-y-auto scrollbar-thin">
        {asString(data.cases)}
      </pre>
    </div>
  );
}

function KnowledgeAddedCard({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-3.5">
      <div className="flex items-center gap-1.5 text-xs font-medium text-emerald-700">
        <BookOpen className="w-3.5 h-3.5" />
        已添加到知识库
        {typeof data.chunk_count === 'number' && ` · ${data.chunk_count} 个分块`}
      </div>
      <p className="mt-1.5 text-xs text-gray-600 whitespace-pre-wrap leading-relaxed">
        {asString(data.content)}
      </p>
    </div>
  );
}

// ---------- 主组件 ----------
export default function ChatPanel(props: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [useRag, setUseRag] = useState(false);
  const [useVision, setUseVision] = useState(false);
  const [attachedFile, setAttachedFile] = useState<FileInfo | null>(null);
  const [uploading, setUploading] = useState(false);
  const [inputError, setInputError] = useState('');
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 切换会话时加载历史
  useEffect(() => {
    if (!props.currentSessionId) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    listConversations(props.currentSessionId)
      .then(({ conversations }) => {
        if (!cancelled) setMessages(conversations.flatMap(mapRecordToMessages));
      })
      .catch(() => {
        if (!cancelled) setMessages([]);
      });
    return () => {
      cancelled = true;
    };
  }, [props.currentSessionId]);

  // 自动滚动到底部
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  const patchMessage = (id: string, mutate: (m: ChatMessage) => ChatMessage) => {
    setMessages(prev => prev.map(m => (m.id === id ? mutate(m) : m)));
  };

  const applyEvent = (id: string, ev: ChatStreamEvent) => {
    patchMessage(id, m => {
      switch (ev.type) {
        case 'meta': {
          const intent = asString(ev.intent, 'chat');
          return {
            ...m,
            module: intent,
            testRun: intent === 'web_test' ? emptyTestRun() : m.testRun,
          };
        }
        case 'chunk':
          return { ...m, text: m.text + asString(ev.content) };
        case 'result':
          return {
            ...m,
            module: asString(ev.module, m.module),
            data: asRecord(ev.data),
            pending: false,
          };
        case 'start': {
          const run = m.testRun ?? emptyTestRun();
          return {
            ...m,
            module: 'web_test',
            testRun: {
              ...run,
              taskId: asString(ev.task_id, run.taskId || ''),
              url: asString(ev.url) || run.url,
              status: 'running',
              message: asString(ev.message),
            },
          };
        }
        case 'step': {
          const run = m.testRun ?? emptyTestRun();
          const step: TestStep = {
            step: Number(ev.step) || run.steps.length + 1,
            action: asString(ev.action),
            target: asString(ev.target),
            result: asString(ev.result),
            success: ev.success !== false,
            console_errors: asArray<string>(ev.console_errors),
            network_errors: asArray<string>(ev.network_errors),
          };
          return { ...m, testRun: { ...run, steps: [...run.steps, step] } };
        }
        case 'code_issue': {
          const run = m.testRun ?? emptyTestRun();
          const issue = asRecord(ev.issue) as unknown as CodeIssue | undefined;
          if (!issue) return m;
          if (run.issues.some(i => i.file_path === issue.file_path && i.error_log === issue.error_log)) {
            return m;
          }
          return { ...m, testRun: { ...run, issues: [...run.issues, issue] } };
        }
        case 'waiting_confirm':
          return { ...m, testRun: { ...(m.testRun ?? emptyTestRun()), status: 'awaiting_confirm' } };
        case 'cancelled':
          return {
            ...m,
            pending: false,
            testRun: { ...(m.testRun ?? emptyTestRun()), status: 'cancelled', message: asString(ev.message, '测试已停止') },
          };
        case 'error':
          return { ...m, pending: false, error: asString(ev.message, '请求失败') };
        case 'done': {
          if (m.testRun) {
            const run = m.testRun;
            const issues = asArray<CodeIssue>(ev.code_issues);
            const status = asString(ev.status);
            const finalStatus: TestRunStatus =
              status === 'awaiting_fix' ? 'awaiting_confirm'
              : status === 'cancelled' ? 'cancelled'
              : status === 'failed' ? 'failed'
              : 'completed';
            return {
              ...m,
              pending: false,
              testRun: {
                ...run,
                issues: issues.length ? issues : run.issues,
                status: run.status === 'awaiting_confirm' && finalStatus === 'completed'
                  ? 'awaiting_confirm'
                  : finalStatus,
                message: asString(ev.message, run.message),
                scriptPath: asString(ev.script_path) || run.scriptPath,
                reportPath: asString(ev.report_path) || run.reportPath,
              },
            };
          }
          const data = asRecord(ev.data) as { references?: string[] } | undefined;
          return {
            ...m,
            pending: false,
            data: asRecord(ev.data),
            references: asArray<string>(data?.references),
          };
        }
        default:
          return m;
      }
    });
  };

  const send = async () => {
    const content = input.trim();
    if (sending || !props.currentSessionId || (!content && !attachedFile)) return;

    const userMsg: ChatMessage = {
      id: genId(),
      role: 'user',
      module: 'chat',
      text: content,
      createdAt: new Date().toISOString(),
    };
    const assistantId = genId();
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      module: 'chat',
      text: '',
      pending: true,
      createdAt: new Date().toISOString(),
    };
    setMessages(prev => [...prev, userMsg, assistantMsg]);
    setInput('');
    const fileId = attachedFile?.id;
    setAttachedFile(null);
    setInputError('');
    setSending(true);

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamSSE(
        '/chat/stream',
        { content, session_id: props.currentSessionId, use_rag: useRag, file_id: fileId, use_vision: useVision || undefined },
        ev => applyEvent(assistantId, ev),
        controller.signal,
      );
    } catch (e) {
      patchMessage(assistantId, m =>
        m.pending || !m.text
          ? { ...m, pending: false, error: e instanceof Error ? e.message : '请求失败' }
          : m,
      );
    } finally {
      setSending(false);
      abortRef.current = null;
      patchMessage(assistantId, m => (m.pending ? { ...m, pending: false } : m));
      props.onSessionsChanged();
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setInputError('');
    setUploading(true);
    try {
      setAttachedFile(await uploadFile(file));
    } catch (err) {
      setInputError(err instanceof Error ? err.message : '文件上传失败');
    } finally {
      setUploading(false);
    }
  };

  const handleKnowledgeResult = () => {
    props.onKnowledgeAdded();
  };

  const renderAssistant = (m: ChatMessage) => {
    if (m.error) {
      return <div className="text-sm text-red-500">{m.error}</div>;
    }
    if (m.module === 'web_test' && m.testRun) {
      return (
        <TestRunCard
          run={m.testRun}
          onUpdate={mutate =>
            patchMessage(m.id, msg =>
              msg.testRun ? { ...msg, testRun: mutate(msg.testRun) } : msg,
            )
          }
        />
      );
    }
    if (m.data) {
      if (m.module === 'code') return <BugAnalysisCard data={m.data} />;
      if (m.module === 'case') return <TestCaseCard data={m.data} />;
      if (m.module === 'knowledge') {
        handleKnowledgeResult();
        return <KnowledgeAddedCard data={m.data} />;
      }
    }
    return (
      <div className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap break-words">
        {m.text || (m.pending ? '思考中...' : '')}
        {m.pending && (
          <span className="inline-block w-1.5 h-4 bg-blue-500 animate-pulse ml-0.5 align-middle rounded-sm" />
        )}
      </div>
    );
  };

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {/* 消息列表 */}
      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto scrollbar-thin px-4 md:px-8 py-6">
        <div className="max-w-3xl mx-auto space-y-4">
          {messages.length === 0 && (
            <div className="pt-16 text-center animate-slide-up">
              <div className="inline-flex items-center justify-center w-14 h-14 bg-gradient-to-br from-blue-500 to-blue-600 rounded-2xl shadow-lg shadow-blue-500/20 mb-4">
                <Bug className="w-7 h-7 text-white" />
              </div>
              <h2 className="text-lg font-bold text-gray-900">开始你的测试任务</h2>
              <p className="text-sm text-gray-400 mt-1 mb-6">
                直接描述需求,自动识别意图:Web 自动化测试 / 用例生成 / Bug 分析 / 知识管理
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-xl mx-auto">
                {SAMPLES.map(({ icon: Icon, text }) => (
                  <button
                    key={text}
                    onClick={() => setInput(text)}
                    className="flex items-center gap-2 px-3.5 py-2.5 rounded-xl bg-white border border-gray-200 text-left text-xs text-gray-600 hover:border-blue-300 hover:text-blue-700 transition-colors"
                  >
                    <Icon className="w-3.5 h-3.5 text-blue-500 shrink-0" />
                    <span className="truncate">{text}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map(m =>
            m.role === 'user' ? (
              <div key={m.id} className="flex justify-end animate-slide-up">
                <div className="max-w-[80%] px-3.5 py-2.5 rounded-2xl rounded-br-md bg-blue-600 text-white text-sm leading-relaxed whitespace-pre-wrap break-words">
                  {m.text}
                  {m.id.startsWith('hist') && m.text.startsWith('[引用文件]') && (
                    <span className="block mt-1 text-[10px] text-blue-200">引用了文件内容</span>
                  )}
                </div>
              </div>
            ) : (
              <div key={m.id} className="flex justify-start animate-slide-up">
                <div className="max-w-[88%] w-fit min-w-0">
                  {renderAssistant(m)}
                  {m.references && m.references.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {m.references.map((ref, i) => (
                        <span
                          key={i}
                          className="px-1.5 py-0.5 rounded bg-gray-100 text-[10px] text-gray-500"
                        >
                          {ref}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ),
          )}
        </div>
      </div>

      {/* 输入区 */}
      <div className="border-t border-border bg-white px-4 md:px-8 py-3">
        <div className="max-w-3xl mx-auto">
          {inputError && (
            <div className="mb-2 text-xs text-red-500">{inputError}</div>
          )}
          {attachedFile && (
            <div className="mb-2 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-blue-50 text-xs text-blue-700">
              <FileText className="w-3.5 h-3.5" />
              <span className="truncate max-w-[200px]">{attachedFile.original_filename}</span>
              <button
                onClick={() => setAttachedFile(null)}
                className="text-blue-400 hover:text-blue-600"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          )}
          <div className="flex items-end gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.txt"
              className="hidden"
              onChange={handleFileChange}
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading || sending}
              className="p-2.5 rounded-xl text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors disabled:opacity-40"
              title="引用文件 (PDF/TXT)"
            >
              {uploading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Paperclip className="w-5 h-5" />}
            </button>
            <button
              onClick={() => setUseRag(v => !v)}
              className={`flex items-center gap-1 px-2.5 py-2 rounded-xl text-xs transition-colors ${
                useRag
                  ? 'bg-blue-50 text-blue-700 font-medium'
                  : 'text-gray-400 hover:text-blue-600 hover:bg-blue-50'
              }`}
              title="启用知识库检索增强"
            >
              <BookOpen className="w-4 h-4" />
              知识库
            </button>
            <button
              onClick={() => setUseVision(v => !v)}
              className={`flex items-center gap-1 px-2.5 py-2 rounded-xl text-xs transition-colors ${
                useVision
                  ? 'bg-blue-50 text-blue-700 font-medium'
                  : 'text-gray-400 hover:text-blue-600 hover:bg-blue-50'
              }`}
              title="开启后测试任务携带页面截图(可发现视觉类问题,成本更高);关闭时使用 DOM 文本感知"
            >
              <Eye className="w-4 h-4" />
              视觉
            </button>
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  send();
                }
              }}
              rows={1}
              placeholder="描述你的测试需求,Enter 发送,Shift+Enter 换行"
              className="flex-1 resize-none px-4 py-2.5 max-h-32 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-900 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 transition-all"
            />
            {sending ? (
              <button
                onClick={() => abortRef.current?.abort()}
                className="p-2.5 rounded-xl bg-gray-100 text-gray-600 hover:bg-gray-200 transition-colors"
                title="停止生成"
              >
                <Square className="w-5 h-5" />
              </button>
            ) : (
              <button
                onClick={send}
                disabled={!input.trim() && !attachedFile}
                className="p-2.5 rounded-xl bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40 transition-colors"
                title="发送"
              >
                <Send className="w-5 h-5" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
