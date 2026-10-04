/** 聊天面板:消息流渲染 + SSE 发送 */
import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import {
  BookOpen,
  Bug,
  ChevronDown,
  ChevronRight,
  FileEdit,
  ListChecks,
  Send,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Square,
  Terminal,
} from 'lucide-react';
import {
  confirmAgentChange,
  listConversations,
  streamSSE,
} from '../lib/api';
import {
  type AgentStep,
  type ChatMessage,
  type ChatStreamEvent,
  type ConversationRecord,
  type VerifyIssue,
  type VerifyInfo,
  type WriteConfirm,
} from '../lib/types';

interface ChatPanelProps {
  currentSessionId: string;
  onSessionsChanged: () => void;
  onKnowledgeAdded: () => void;
  workspacePath?: string | null;
  /** 外部(检查报告)注入的待发送提示,nonce 变化触发自动发送 */
  pendingPrompt?: { text: string; nonce: number } | null;
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

const SAMPLES_AGENT = [
  { icon: Bug, text: '分析这个项目的整体结构和技术栈' },
  { icon: ListChecks, text: '检查项目里有没有硬编码的密码或密钥' },
  { icon: Sparkles, text: '找出代码中潜在的性能问题并给出修复建议' },
  { icon: BookOpen, text: '帮我给核心模块补充单元测试' },
];
const SAMPLES = [
  { icon: Bug, text: '分析这个 bug：点击提交按钮后页面无响应' },
  { icon: ListChecks, text: '为登录功能设计一份测试用例' },
  { icon: BookOpen, text: '什么是边界值分析和等价类划分？' },
  { icon: Sparkles, text: '帮我写一个 Python 快速排序实现' },
];

// ---------- Markdown 渲染 ----------
function MarkdownText({ text }: { text: string }) {
  return (
    <div className="text-sm text-gray-800 leading-relaxed break-words">
      <ReactMarkdown
        components={{
          p: ({ children }) => <p className="my-1.5 first:mt-0 last:mb-0">{children}</p>,
          h1: ({ children }) => <h1 className="text-base font-semibold mt-3 mb-1.5">{children}</h1>,
          h2: ({ children }) => <h2 className="text-[15px] font-semibold mt-3 mb-1.5">{children}</h2>,
          h3: ({ children }) => <h3 className="text-sm font-semibold mt-2.5 mb-1">{children}</h3>,
          h4: ({ children }) => <h4 className="text-sm font-semibold mt-2 mb-1">{children}</h4>,
          ul: ({ children }) => <ul className="list-disc pl-5 my-1.5 space-y-0.5">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-5 my-1.5 space-y-0.5">{children}</ol>,
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noreferrer" className="text-blue-600 underline underline-offset-2">{children}</a>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-gray-300 pl-3 my-1.5 text-gray-600">{children}</blockquote>
          ),
          hr: () => <hr className="my-2 border-gray-200" />,
          code: props => {
            const { className, children } = props as { className?: string; children?: React.ReactNode };
            const isBlock = /language-/.test(className ?? '');
            if (isBlock) return <code className={`${className ?? ''} block font-mono`}>{children}</code>;
            return <code className="px-1 py-0.5 rounded bg-gray-100 text-[12.5px] font-mono text-blue-700">{children}</code>;
          },
          pre: ({ children }) => (
            <pre className="my-2 rounded-lg bg-gray-900 text-gray-100 p-3 overflow-x-auto text-xs font-mono leading-relaxed">
              {children}
            </pre>
          ),
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto">
              <table className="text-xs border-collapse">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-gray-200 bg-gray-50 px-2 py-1 text-left font-medium">{children}</th>
          ),
          td: ({ children }) => <td className="border border-gray-200 px-2 py-1 align-top">{children}</td>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

// ---------- 智能体工具步骤(默认折叠) ----------
function AgentStepsBlock({ steps, pending }: { steps: AgentStep[]; pending?: boolean }) {
  // 流式进行中默认展开看实时进度;结束后自动收起为一行摘要
  const [expanded, setExpanded] = useState(!!pending);
  const [openIdx, setOpenIdx] = useState<number | null>(null);

  useEffect(() => {
    if (!pending) {
      setExpanded(false);
      setOpenIdx(null);
    }
  }, [pending]);

  if (steps.length === 0) return null;

  const okCount = steps.filter(s => s.success).length;
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50/60 text-xs overflow-hidden">
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center gap-1.5 px-3 py-2 hover:bg-gray-100 transition-colors"
      >
        <Terminal className="w-3.5 h-3.5 text-gray-400 shrink-0" />
        <span className="text-gray-600 font-medium">
          {pending ? '正在执行工具' : '执行了工具调用'}
        </span>
        <span className="text-gray-400">
          {steps.length} 步{okCount < steps.length ? ` · ${steps.length - okCount} 步失败` : ''}
        </span>
        <span className="ml-auto text-gray-400">
          {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        </span>
      </button>
      {expanded && (
        <div className="border-t border-gray-200 divide-y divide-gray-100 bg-white">
          {steps.map((s, i) => (
            <div key={i}>
              <button
                onClick={() => setOpenIdx(openIdx === i ? null : i)}
                className="w-full flex items-center gap-1.5 px-3 py-1.5 hover:bg-gray-50 transition-colors text-left"
              >
                <span className={`inline-block w-1.5 h-1.5 rounded-full shrink-0 ${s.success ? 'bg-green-500' : 'bg-red-500'}`} />
                <span className="font-mono font-medium text-blue-700 shrink-0">{s.action}</span>
                <span className="text-gray-400 truncate font-mono flex-1">{s.target}</span>
                {s.result && (
                  <span className="text-gray-300 shrink-0">
                    {openIdx === i ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                  </span>
                )}
              </button>
              {openIdx === i && s.result && (
                <div className="px-3 pb-2 pl-7 text-gray-500 font-mono whitespace-pre-wrap break-all max-h-48 overflow-y-auto scrollbar-thin">
                  {s.result}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------- 写文件/执行命令确认卡(diff 或命令审批) ----------
function ConfirmCard({ confirm, onResolve }: {
  confirm: WriteConfirm;
  onResolve: (changeId: string, approved: boolean) => void;
}) {
  const decided = !!confirm.resolved;
  const isCommand = confirm.kind === 'command';
  const lines = confirm.diff.split('\n');
  return (
    <div className={`rounded-lg border px-3 py-2.5 text-xs space-y-2 ${
      decided ? 'border-gray-200 bg-gray-50 opacity-70' : 'border-amber-300 bg-amber-50/60'
    }`}>
      <div className="flex items-center gap-1.5">
        {isCommand
          ? <Terminal className="w-3.5 h-3.5 text-amber-600 shrink-0" />
          : <FileEdit className="w-3.5 h-3.5 text-amber-600 shrink-0" />}
        <span className="font-medium text-gray-700">
          {decided
            ? '已处理请求'
            : isCommand ? '智能体请求执行命令,请确认' : '智能体请求修改文件,请确认'}
        </span>
        {!isCommand && <span className="font-mono text-gray-500 truncate">{confirm.path}</span>}
      </div>
      {isCommand ? (
        <pre className="rounded bg-gray-900 p-2 font-mono text-[11px] leading-relaxed text-gray-100 whitespace-pre-wrap break-all">
          {confirm.path}
        </pre>
      ) : (
        <pre className="max-h-56 overflow-y-auto scrollbar-thin rounded bg-gray-900 p-2 font-mono text-[11px] leading-relaxed text-gray-100 whitespace-pre-wrap break-all">
          {lines.map((l, i) => {
            const cls = l.startsWith('+') && !l.startsWith('+++') ? 'text-green-400'
              : l.startsWith('-') && !l.startsWith('---') ? 'text-red-400'
              : l.startsWith('@@') ? 'text-blue-300' : '';
            return <span key={i} className={cls}>{l + '\n'}</span>;
          })}
        </pre>
      )}
      {!decided && (
        <div className="flex gap-2">
          <button
            onClick={() => onResolve(confirm.changeId, true)}
            className={`px-3 py-1.5 rounded-lg text-white font-medium transition-colors ${
              isCommand ? 'bg-blue-600 hover:bg-blue-700' : 'bg-green-600 hover:bg-green-700'
            }`}
          >
            {isCommand ? '允许执行' : '批准修改'}
          </button>
          <button
            onClick={() => onResolve(confirm.changeId, false)}
            className="px-3 py-1.5 rounded-lg bg-gray-200 text-gray-700 font-medium hover:bg-gray-300 transition-colors"
          >
            拒绝
          </button>
        </div>
      )}
    </div>
  );
}

// ---------- 修复复查结果卡 ----------
function VerifyCard({ verify }: { verify: VerifyInfo }) {
  return (
    <div className={`rounded-lg border px-3 py-2 text-xs space-y-1 ${
      verify.clean ? 'border-green-200 bg-green-50/60' : 'border-amber-200 bg-amber-50/60'
    }`}>
      <div className="flex items-center gap-1.5 font-medium">
        {verify.clean
          ? <><ShieldCheck className="w-3.5 h-3.5 text-green-600" /><span className="text-green-700">修复复查通过 — 未再发现规则问题</span></>
          : <><ShieldAlert className="w-3.5 h-3.5 text-amber-600" /><span className="text-amber-700">修复复查仍有问题</span></>}
      </div>
      <div className="text-gray-500 font-mono text-[11px]">复查文件: {verify.files.join(', ')}</div>
      {!verify.clean && verify.remaining.map((i, idx) => (
        <div key={idx} className="text-gray-600">
          <span className="font-mono text-[11px] text-gray-500">{i.file}:{i.line}</span>
          <span className="mx-1.5 text-[10px] font-mono text-gray-400">{i.rule_id}</span>
          {i.message}
        </div>
      ))}
    </div>
  );
}

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
export default function ChatPanel({ workspacePath, ...props }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [useRag, setUseRag] = useState(false);
  const [inputError, setInputError] = useState('');
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

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

  // 外部注入的提示(检查报告一键修复):到达即自动发送
  const lastNonceRef = useRef(0);
  useEffect(() => {
    if (!props.pendingPrompt || props.pendingPrompt.nonce === lastNonceRef.current) return;
    lastNonceRef.current = props.pendingPrompt.nonce;
    if (!sending) send(props.pendingPrompt.text);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.pendingPrompt?.nonce]);

  const patchMessage = (id: string, mutate: (m: ChatMessage) => ChatMessage) => {
    setMessages(prev => prev.map(m => (m.id === id ? mutate(m) : m)));
  };

  const applyEvent = (id: string, ev: ChatStreamEvent) => {
    patchMessage(id, m => {
      switch (ev.type) {
        case 'meta':
          return { ...m, module: asString(ev.intent, 'chat') };
        case 'chunk':
          return { ...m, text: m.text + asString(ev.content) };
        case 'result':
          return {
            ...m,
            module: asString(ev.module, m.module),
            data: asRecord(ev.data),
            pending: false,
          };
        case 'step': {
          // 智能体的工具步骤内联渲染
          const step: AgentStep = {
            step: Number(ev.step) || (m.agentSteps?.length ?? 0) + 1,
            action: asString(ev.action),
            target: asString(ev.target),
            result: asString(ev.result),
            success: ev.success !== false,
          };
          return { ...m, agentSteps: [...(m.agentSteps ?? []), step] };
        }
        case 'confirm_request':
          return {
            ...m,
            confirm: {
              changeId: asString(ev.change_id),
              path: asString(ev.path),
              diff: asString(ev.diff),
              kind: ev.kind === 'command' ? 'command' as const : 'write' as const,
            },
          };
        case 'verify':
          return { ...m, verify: {
            files: asArray<string>(ev.files),
            clean: ev.clean === true,
            remaining: asArray<VerifyIssue>(ev.remaining),
          } };
        case 'error':
          return { ...m, pending: false, error: asString(ev.message, '请求失败') };
        case 'done': {
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

  const send = async (contentOverride?: string) => {
    const content = (contentOverride ?? input).trim();
    if (sending || !props.currentSessionId || !content) return;

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
    setInputError('');
    setSending(true);

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamSSE(
        '/chat/stream',
        { content, session_id: props.currentSessionId, use_rag: useRag },
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

  const handleKnowledgeResult = () => {
    props.onKnowledgeAdded();
  };

  const renderAssistant = (m: ChatMessage) => {
    if (m.error) {
      return <div className="text-sm text-red-500">{m.error}</div>;
    }
    if (m.module === 'agent') {
      return (
        <div className="space-y-2 w-full">
          {m.confirm && (
            <ConfirmCard
              confirm={m.confirm}
              onResolve={(changeId, approved) => {
                patchMessage(m.id, msg =>
                  msg.confirm?.changeId === changeId
                    ? { ...msg, confirm: { ...msg.confirm, resolved: true } }
                    : msg,
                );
                confirmAgentChange(changeId, approved).catch(() => {
                  patchMessage(m.id, msg => (msg.confirm ? { ...msg, confirm: { ...msg.confirm, resolved: false } } : msg));
                });
              }}
            />
          )}
          <AgentStepsBlock steps={m.agentSteps ?? []} pending={m.pending && !m.text} />
          {m.verify && <VerifyCard verify={m.verify} />}
          {(m.text || m.pending) && (
            <div>
              {m.text ? (
                <MarkdownText text={m.text} />
              ) : (
                <div className="text-sm text-gray-800 leading-relaxed">
                  {m.pending ? '思考中...' : ''}
                  {m.pending && (
                    <span className="inline-block w-1.5 h-4 bg-blue-500 animate-pulse ml-0.5 align-middle rounded-sm" />
                  )}
                </div>
              )}
              {m.pending && m.text && (
                <span className="inline-block w-1.5 h-4 bg-blue-500 animate-pulse ml-0.5 align-middle rounded-sm" />
              )}
            </div>
          )}
        </div>
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
      <div>
        {m.text ? (
          <MarkdownText text={m.text} />
        ) : (
          <div className="text-sm text-gray-800 leading-relaxed">
            {m.pending ? '思考中...' : ''}
            {m.pending && (
              <span className="inline-block w-1.5 h-4 bg-blue-500 animate-pulse ml-0.5 align-middle rounded-sm" />
            )}
          </div>
        )}
        {m.pending && m.text && (
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
              <h2 className="text-lg font-bold text-gray-900">{workspacePath ? '开始与项目对话' : '开始你的任务'}</h2>
              <p className="text-sm text-gray-400 mt-1 mb-6">
                {workspacePath
                  ? '智能体已就绪:代码分析 / Bug 定位 / 规范检查 / 用例生成 / 自动修复,工具执行过程实时可见'
                  : '直接描述需求,自动识别意图:Web 自动化测试 / 用例生成 / Bug 分析 / 知识管理'}
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-xl mx-auto">
                {(workspacePath ? SAMPLES_AGENT : SAMPLES).map(({ icon: Icon, text }) => (
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
          <div className="flex items-end gap-2">
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
              placeholder="描述你的需求,Enter 发送,Shift+Enter 换行"
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
                onClick={() => send()}
                disabled={!input.trim()}
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
