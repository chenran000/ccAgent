/** 工作区组件:顶栏(当前项目路径 + 打开/关闭) + 右侧面板(项目文件/检查报告双 Tab,ZCode 式) */
import { useCallback, useEffect, useRef, useState } from 'react';
import { FolderOpen, FolderClosed, File as FileIcon, ListChecks, Loader2, ShieldCheck, Settings2, TrendingUp, Wrench, X } from 'lucide-react';
import {
  addRule,
  closeWorkspace,
  deleteRule,
  getReport,
  getRules,
  getWorkspace,
  getWorkspaceFile,
  getWorkspaceTree,
  getFileBackups,
  listReports,
  openWorkspace,
  restoreBackup,
  selectFolder,
  streamInspect,
} from '../lib/api';
import type { BackupInfo, FileNode, RuleInfo } from '../lib/types';
import type { ReportSummary } from '../lib/api';

export function useWorkspace() {
  const [workspacePath, setWorkspacePath] = useState<string | null>(null);
  const [tree, setTree] = useState<FileNode[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const refresh = useCallback(async () => {
    try {
      const { path } = await getWorkspace();
      setWorkspacePath(path);
      if (path) {
        const { tree: t } = await getWorkspaceTree();
        setTree(t);
      } else {
        setTree([]);
      }
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const open = useCallback(async () => {
    try {
      const folder = await selectFolder();
      if (!folder) return;
      await openWorkspace(folder);
      await refresh();
    } catch (e) {
      window.alert(e instanceof Error ? e.message : '打开工作区失败');
    }
  }, [refresh]);

  const close = useCallback(async () => {
    try {
      await closeWorkspace();
      setWorkspacePath(null);
      setTree([]);
    } catch { /* ignore */ }
  }, []);

  const toggle = useCallback((path: string) => {
    setExpanded(prev => ({ ...prev, [path]: !prev[path] }));
  }, []);

  return { workspacePath, tree, expanded, toggle, open, close, refresh };
}

function TreeItem({ node, depth, expanded, toggle, onFileClick }: {
  node: FileNode;
  depth: number;
  expanded: Record<string, boolean>;
  toggle: (path: string) => void;
  onFileClick: (path: string) => void;
}) {
  const isDir = node.type === 'directory';
  const isOpen = !!expanded[node.path];
  return (
    <>
      <button
        onClick={() => (isDir ? toggle(node.path) : onFileClick(node.path))}
        className="w-full flex items-center gap-1.5 px-2 py-[3px] rounded text-left text-[13px] text-gray-700 hover:bg-gray-100 transition-colors"
        style={{ paddingLeft: 8 + depth * 14 }}
        title={node.path}
      >
        {isDir
          ? <FolderClosed className={`w-3.5 h-3.5 shrink-0 ${isOpen ? 'text-blue-500' : 'text-gray-400'}`} />
          : <FileIcon className="w-3.5 h-3.5 shrink-0 text-gray-400" />}
        <span className="truncate">{node.name}</span>
      </button>
      {isDir && isOpen && node.children?.map(child => (
        <TreeItem key={child.path} node={child} depth={depth + 1} expanded={expanded} toggle={toggle} onFileClick={onFileClick} />
      ))}
    </>
  );
}

/** 顶部工作区栏 */
export function WorkspaceHeader({ workspacePath, onOpen, onClose }: {
  workspacePath: string | null;
  onOpen: () => void;
  onClose: () => void;
}) {
  return (
    <div className="h-10 shrink-0 border-b border-border bg-white flex items-center gap-2 px-3">
      <button
        onClick={workspacePath ? onClose : onOpen}
        className={`flex items-center gap-1.5 h-7 px-2.5 rounded-md text-xs transition-colors ${
          workspacePath
            ? 'bg-blue-50 text-blue-700 hover:bg-blue-100'
            : 'bg-blue-600 text-white hover:bg-blue-700'
        }`}
      >
        <FolderOpen className="w-3.5 h-3.5" />
        {workspacePath ? '关闭项目' : '打开项目文件夹'}
      </button>
      {workspacePath ? (
        <div className="flex items-center gap-1.5 min-w-0 text-xs text-gray-500">
          <FolderClosed className="w-3.5 h-3.5 text-gray-400 shrink-0" />
          <span className="truncate font-mono" title={workspacePath}>{workspacePath}</span>
          <button
            onClick={onClose}
            className="p-0.5 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600 shrink-0"
            title="关闭项目"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
      ) : (
        <span className="text-xs text-gray-400">未打开项目 — 选择本地文件夹后可进行代码检查与项目问答</span>
      )}
    </div>
  );
}

/** 右侧文件树面板 */
export function WorkspaceFilesPane({ workspacePath, tree, expanded, toggle, onOpen, onFixIssues }: {
  workspacePath: string | null;
  tree: FileNode[];
  expanded: Record<string, boolean>;
  toggle: (path: string) => void;
  onOpen: () => void;
  onFixIssues: (issues: ReportIssue[]) => void;
}) {
  const [tab, setTab] = useState<'files' | 'inspect'>('files');
  const [viewFile, setViewFile] = useState<string | null>(null);

  const tabs = (
    <div className="h-9 shrink-0 flex items-center gap-1 px-2 border-b border-border">
      {(['files', 'inspect'] as const).map(t => (
        <button
          key={t}
          onClick={() => setTab(t)}
          className={`flex items-center gap-1 px-2 py-1 rounded-md text-xs transition-colors ${
            tab === t ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-400 hover:text-gray-600'
          }`}
        >
          {t === 'files' ? <FolderClosed className="w-3.5 h-3.5" /> : <ListChecks className="w-3.5 h-3.5" />}
          {t === 'files' ? '项目文件' : '检查报告'}
        </button>
      ))}
    </div>
  );

  if (!workspacePath) {
    return (
      <div className="w-64 shrink-0 border-l border-border bg-white flex flex-col">
        {tabs}
        <div className="flex-1 flex flex-col items-center justify-center gap-3 px-4">
          <FolderOpen className="w-8 h-8 text-gray-300" />
          <p className="text-xs text-gray-400 text-center">未打开项目</p>
          <button
            onClick={onOpen}
            className="text-xs text-blue-600 hover:text-blue-700 font-medium"
          >
            打开项目文件夹
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="w-64 shrink-0 border-l border-border bg-white flex flex-col">
      {tabs}
      {tab === 'files' ? (
        <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin py-1">
          {tree.length === 0
            ? <div className="px-3 py-4 text-xs text-gray-400">空目录</div>
            : tree.map(node => (
              <TreeItem key={node.path} node={node} depth={0} expanded={expanded} toggle={toggle} onFileClick={setViewFile} />
            ))}
        </div>
      ) : (
        <WorkspaceInspectPane workspacePath={workspacePath} onOpen={onOpen} onFixIssues={onFixIssues} />
      )}
      {viewFile && (
        <FileViewerModal
          workspacePath={workspacePath}
          file={viewFile}
          onClose={() => setViewFile(null)}
        />
      )}
    </div>
  );
}


// ========== 文件查看弹窗(点击文件树文件;若有 .bak 历史备份可一键恢复) ==========
function FileViewerModal({ workspacePath, file, onClose }: {
  workspacePath: string;
  file: string;
  onClose: () => void;
}) {
  const [lines, setLines] = useState<string[] | null>(null);
  const [error, setError] = useState('');
  const [backups, setBackups] = useState<BackupInfo[]>([]);
  const [restoring, setRestoring] = useState('');
  const [notice, setNotice] = useState('');

  const abs = `${workspacePath.replace(/[\\/]+$/, '')}/${file}`;

  const load = useCallback(() => {
    getWorkspaceFile(abs)
      .then(({ content }) => setLines((content ?? '').split('\n')))
      .catch(e => setError(e instanceof Error ? e.message : '读取失败'));
    getFileBackups(abs)
      .then(({ backups: b }) => setBackups(b))
      .catch(() => setBackups([]));
  }, [abs]);

  useEffect(() => { load(); }, [load]);

  const doRestore = useCallback(async (suffix: string) => {
    setRestoring(suffix); setNotice('');
    try {
      const { message } = await restoreBackup(file, suffix);
      setNotice(message);
      setLines(null);
      load();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '恢复失败');
    } finally {
      setRestoring('');
    }
  }, [file, load]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6" onClick={onClose}>
      <div
        className="w-full max-w-3xl max-h-[80vh] flex flex-col rounded-xl bg-white shadow-2xl overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-gray-50">
          <FileIcon className="w-4 h-4 text-gray-400 shrink-0" />
          <span className="font-mono text-xs text-gray-700 truncate">{file}</span>
          <button onClick={onClose} className="ml-auto p-1 rounded hover:bg-gray-200 text-gray-400 hover:text-gray-600">
            <X className="w-4 h-4" />
          </button>
        </div>
        {backups.length > 0 && (
          <div className="px-4 py-2 border-b border-amber-100 bg-amber-50 flex items-center gap-2 flex-wrap">
            <span className="text-[11px] text-amber-700 font-medium">历史备份(智能体修改前自动留存,新→旧):</span>
            {backups.map(b => (
              <button
                key={b.suffix}
                onClick={() => doRestore(b.suffix)}
                disabled={!!restoring}
                className="px-2 py-0.5 rounded border border-amber-200 bg-white text-[11px] text-amber-700 hover:bg-amber-100 transition-colors disabled:opacity-50"
                title={`${b.mtime} · ${b.size} 字节`}
              >
                {restoring === b.suffix ? '恢复中...' : `恢复到 ${b.mtime.replace('T', ' ')}`}
              </button>
            ))}
          </div>
        )}
        {notice && <div className="px-4 py-1.5 text-[11px] text-green-700 bg-green-50">{notice}</div>}
        <div className="flex-1 min-h-0 overflow-auto scrollbar-thin bg-gray-900">
          {error && <div className="p-4 text-xs text-red-400">{error}</div>}
          {!lines && !error && <div className="p-4 text-xs text-gray-400">加载中...</div>}
          {lines && (
            <div className="py-2 font-mono text-[12px] leading-5">
              {lines.slice(0, 600).map((l, i) => (
                <div key={i} className="flex hover:bg-white/5">
                  <span className="w-12 shrink-0 pr-2 text-right text-gray-500 select-none">{i + 1}</span>
                  <span className="whitespace-pre-wrap break-all pr-4 text-gray-200">{l || ' '}</span>
                </div>
              ))}
              {lines.length > 600 && (
                <div className="px-4 py-1 text-[11px] text-gray-500">仅显示前 600 行,完整内容共 {lines.length} 行</div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}


// ========== 检查报告 Tab ==========
export interface ReportIssue {
  severity: string;
  source: string;
  file: string;
  line: number;
  message: string;
  evidence: string;
  suggestion: string;
  rule_id: string;
}

interface ReportData {
  workspace?: string;
  created_at?: string;
  scope?: string;
  score?: number;
  total?: number;
  by_severity?: Record<string, number>;
  ai_files?: number;
  cache_hits?: number;
  rule_count?: number;
  ai_count?: number;
  issues?: ReportIssue[];
}

const SEVERITY_STYLE: Record<string, string> = {
  critical: 'bg-red-100 text-red-700',
  high: 'bg-orange-100 text-orange-700',
  medium: 'bg-amber-100 text-amber-700',
  low: 'bg-gray-100 text-gray-600',
};

// ========== 代码定位弹窗(报告问题 → 文件内容高亮目标行) ==========
function CodeLocateModal({ file, line, workspacePath, onClose }: {
  file: string;
  line: number;
  workspacePath: string;
  onClose: () => void;
}) {
  const [lines, setLines] = useState<string[] | null>(null);
  const [error, setError] = useState('');
  const targetRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    const abs = `${workspacePath.replace(/[\\/]+$/, '')}/${file}`;
    getWorkspaceFile(abs)
      .then(({ content }) => { if (!cancelled) setLines((content ?? '').split('\n')); })
      .catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : '读取失败'); });
    return () => { cancelled = true; };
  }, [file, workspacePath]);

  useEffect(() => {
    if (lines) targetRef.current?.scrollIntoView({ block: 'center' });
  }, [lines]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl max-h-[80vh] flex flex-col rounded-xl bg-white shadow-2xl overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-gray-50">
          <FileIcon className="w-4 h-4 text-gray-400 shrink-0" />
          <span className="font-mono text-xs text-gray-700 truncate">{file}<span className="text-gray-400">:{line}</span></span>
          <button onClick={onClose} className="ml-auto p-1 rounded hover:bg-gray-200 text-gray-400 hover:text-gray-600">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-auto scrollbar-thin bg-gray-900">
          {error && <div className="p-4 text-xs text-red-400">{error}</div>}
          {!lines && !error && <div className="p-4 text-xs text-gray-400">加载中...</div>}
          {lines && (
            <div className="py-2 font-mono text-[12px] leading-5">
              {lines.map((l, i) => {
                const no = i + 1;
                const isTarget = no === line;
                return (
                  <div
                    key={i}
                    ref={isTarget ? targetRef : undefined}
                    className={`flex ${isTarget ? 'bg-amber-500/25 border-y border-amber-400/40' : 'hover:bg-white/5'}`}
                  >
                    <span className="w-12 shrink-0 pr-2 text-right text-gray-500 select-none">{no}</span>
                    <span className={`whitespace-pre-wrap break-all pr-4 ${isTarget ? 'text-amber-200' : 'text-gray-200'}`}>{l || ' '}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ========== 健康分趋势(历史报告 SVG 折线) ==========
function ScoreTrend({ history }: { history: ReportSummary[] }) {
  const pts = [...history].reverse().map(h => h.score ?? 0);
  if (pts.length < 2) return null;
  const w = 216, h = 44, pad = 4;
  const xy = pts.map((s, i) => [
    pad + (i * (w - 2 * pad)) / (pts.length - 1),
    h - pad - (s / 100) * (h - 2 * pad),
  ]);
  const color = pts[pts.length - 1] >= 80 ? '#16a34a' : pts[pts.length - 1] >= 50 ? '#d97706' : '#dc2626';
  return (
    <div className="rounded-lg border border-gray-100 bg-white px-2.5 py-2">
      <div className="flex items-center gap-1.5 text-[11px] text-gray-400 mb-1">
        <TrendingUp className="w-3 h-3" />
        健康分趋势(最近 {pts.length} 次检查)
      </div>
      <svg width="100%" viewBox={`0 0 ${w} ${h}`} className="block">
        <polyline
          points={xy.map(p => p.map(n => n.toFixed(1)).join(',')).join(' ')}
          fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"
        />
        {xy.map((p, i) => (
          <circle key={i} cx={p[0]} cy={p[1]} r="2.5" fill={color} />
        ))}
      </svg>
    </div>
  );
}

// ========== 检查规则管理弹窗(内置规则只读 + 自定义规则增删) ==========
function RulesModal({ onClose }: { onClose: () => void }) {
  const [builtin, setBuiltin] = useState<RuleInfo[]>([]);
  const [custom, setCustom] = useState<RuleInfo[]>([]);
  const [showBuiltin, setShowBuiltin] = useState(false);
  const [pattern, setPattern] = useState('');
  const [severity, setSeverity] = useState('medium');
  const [message, setMessage] = useState('');
  const [codeOnly, setCodeOnly] = useState(true);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const { builtin: b, custom: c } = await getRules();
      setBuiltin(b);
      setCustom(c);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载规则失败');
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleAdd = async () => {
    setError('');
    if (!pattern.trim()) { setError('正则表达式不能为空'); return; }
    setSaving(true);
    try {
      await addRule({ pattern: pattern.trim(), severity, message: message.trim(), code_only: codeOnly });
      setPattern(''); setMessage('');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : '添加失败');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    setError('');
    try {
      await deleteRule(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除失败');
    }
  };

  const RuleRow = ({ r, deletable }: { r: RuleInfo; deletable: boolean }) => (
    <div className="rounded-lg border border-gray-100 bg-white px-2.5 py-1.5 text-[11px]">
      <div className="flex items-center gap-1.5">
        <span className={`px-1.5 py-0.5 rounded ${SEVERITY_STYLE[r.severity] || SEVERITY_STYLE.low}`}>{r.severity}</span>
        <span className="font-mono text-gray-500">{r.id}</span>
        {r.code_only && <span className="text-[10px] text-gray-400">仅源码</span>}
        {deletable && (
          <button
            onClick={() => handleDelete(r.id)}
            className="ml-auto text-red-500 hover:text-red-600 shrink-0"
          >
            删除
          </button>
        )}
      </div>
      <div className="mt-0.5 text-gray-700">{r.message}</div>
      <div className="mt-0.5 font-mono text-gray-400 break-all">{r.pattern}</div>
    </div>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6" onClick={onClose}>
      <div
        className="w-full max-w-lg max-h-[80vh] flex flex-col rounded-xl bg-gray-50 shadow-2xl overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-white">
          <Settings2 className="w-4 h-4 text-gray-500" />
          <span className="text-sm font-medium text-gray-700">检查规则管理</span>
          <span className="text-[11px] text-gray-400">内置 {builtin.length} 条 · 自定义 {custom.length} 条</span>
          <button onClick={onClose} className="ml-auto p-1 rounded hover:bg-gray-200 text-gray-400 hover:text-gray-600">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin p-3 space-y-3">
          <div className="rounded-lg border border-blue-100 bg-blue-50/60 p-2.5 space-y-2">
            <div className="text-xs font-medium text-blue-800">新增自定义规则(下次检查生效)</div>
            <input
              value={pattern}
              onChange={e => setPattern(e.target.value)}
              placeholder={'正则表达式,如 (?i)secret\\s*[=:]'}
              className="w-full rounded border border-gray-200 px-2 py-1.5 text-xs font-mono focus:outline-none focus:border-blue-400"
            />
            <div className="flex items-center gap-2">
              <select
                value={severity}
                onChange={e => setSeverity(e.target.value)}
                className="rounded border border-gray-200 px-1.5 py-1 text-xs"
              >
                {(['critical', 'high', 'medium', 'low'] as const).map(s => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              <label className="flex items-center gap-1 text-[11px] text-gray-600 select-none">
                <input type="checkbox" checked={codeOnly} onChange={e => setCodeOnly(e.target.checked)} className="accent-blue-600" />
                仅源码文件
              </label>
              <button
                onClick={handleAdd}
                disabled={saving}
                className="ml-auto px-3 py-1 rounded bg-blue-600 text-white text-xs hover:bg-blue-700 transition-colors disabled:opacity-50"
              >
                {saving ? '添加中...' : '添加'}
              </button>
            </div>
            <input
              value={message}
              onChange={e => setMessage(e.target.value)}
              placeholder="问题说明(可选),如:疑似硬编码数据库口令"
              className="w-full rounded border border-gray-200 px-2 py-1.5 text-xs focus:outline-none focus:border-blue-400"
            />
          </div>
          {error && <div className="text-xs text-red-500">{error}</div>}
          {custom.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-xs font-medium text-gray-500">自定义规则</div>
              {custom.map(r => <RuleRow key={r.id} r={r} deletable />)}
            </div>
          )}
          <div className="space-y-1.5">
            <button
              onClick={() => setShowBuiltin(v => !v)}
              className="text-xs font-medium text-gray-500 hover:text-gray-700"
            >
              内置规则({builtin.length}){showBuiltin ? ' ▾' : ' ▸'}
            </button>
            {showBuiltin && builtin.map(r => <RuleRow key={r.id} r={r} deletable={false} />)}
          </div>
        </div>
      </div>
    </div>
  );
}

function ReportView({ report, onFixIssues, fixing, workspacePath }: {
  report: ReportData;
  onFixIssues: (issues: ReportIssue[]) => void;
  fixing: boolean;
  workspacePath: string;
}) {
  const [locate, setLocate] = useState<{ file: string; line: number } | null>(null);
  const sev = report.by_severity || {};
  const issues = report.issues || [];
  const highIssues = issues.filter(i => i.severity === 'critical' || i.severity === 'high');
  return (
    <div className="space-y-3 p-3">
      <div className="flex items-center gap-3">
        <div className={`text-2xl font-bold ${  (report.score ?? 0) >= 80 ? 'text-green-600' : (report.score ?? 0) >= 50 ? 'text-amber-600' : 'text-red-600'}`}>
          {report.score ?? '-'}
        </div>
        <div className="text-xs text-gray-500">
          <div>健康分{report.scope === 'changed' ? '(增量)' : ''}</div>
          <div>共 {report.total ?? 0} 个问题</div>
        </div>
      </div>
      <div className="flex gap-1.5 text-xs flex-wrap">
        {(['critical', 'high', 'medium', 'low'] as const).map(s => (
          <span key={s} className={`px-2 py-0.5 rounded-full ${SEVERITY_STYLE[s]}`}>{s} {sev[s] || 0}</span>
        ))}
      </div>
      <div className="text-[11px] text-gray-400">
        规则引擎 {report.rule_count ?? 0} 项 · AI 审查 {report.ai_files ?? 0} 个文件/{report.ai_count ?? 0} 项
        {(report.cache_hits ?? 0) > 0 && ` · 缓存命中 ${report.cache_hits}`}
      </div>
      {highIssues.length > 0 && !fixing && (
        <button
          onClick={() => onFixIssues(highIssues)}
          className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-amber-500 text-white text-xs font-medium hover:bg-amber-600 transition-colors"
        >
          <Wrench className="w-3.5 h-3.5" />
          让智能体修复全部高危问题({highIssues.length})
        </button>
      )}
      {fixing && (
        <div className="rounded-lg bg-blue-50 text-blue-700 text-xs px-3 py-2 text-center">
          已发送到对话,智能体修复中 — 修改文件时会请求你确认 diff
        </div>
      )}
      <div className="space-y-2">
        {issues.slice(0, 60).map((issue, i) => (
          <div
            key={i}
            onClick={() => setLocate({ file: issue.file, line: issue.line })}
            className="rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs cursor-pointer hover:border-blue-300 transition-colors"
            title="点击查看问题所在代码"
          >
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className={`px-1.5 py-0.5 rounded ${SEVERITY_STYLE[issue.severity] || SEVERITY_STYLE.low}`}>{issue.severity}</span>
              <span className="font-mono text-[11px] text-gray-500 truncate">{issue.file}:{issue.line}</span>
              <span className="text-[10px] text-gray-300 font-mono">{issue.rule_id}</span>
              {!fixing && (
                <button
                  onClick={() => onFixIssues([issue])}
                  className="ml-auto flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] text-blue-600 hover:bg-blue-50 transition-colors shrink-0"
                  title="让智能体修复此问题"
                >
                  <Wrench className="w-3 h-3" />
                  修复
                </button>
              )}
            </div>
            <div className="mt-1 text-gray-700">{issue.message}</div>
            {issue.evidence && <div className="mt-0.5 font-mono text-[11px] text-gray-400 break-all line-clamp-2">{issue.evidence}</div>}
            {issue.suggestion && <div className="mt-0.5 text-blue-700">建议: {issue.suggestion}</div>}
          </div>
        ))}
        {issues.length > 60 && (
          <div className="text-xs text-gray-400 text-center">仅显示前 60 条,完整报告见导出文件</div>
        )}
      </div>
      {locate && (
        <CodeLocateModal
          file={locate.file}
          line={locate.line}
          workspacePath={workspacePath}
          onClose={() => setLocate(null)}
        />
      )}
    </div>
  );
}

export function WorkspaceInspectPane({ workspacePath, onOpen, onFixIssues }: {
  workspacePath: string | null;
  onOpen: () => void;
  onFixIssues: (issues: ReportIssue[]) => void;
}) {
  const [running, setRunning] = useState(false);
  const [onlyChanged, setOnlyChanged] = useState(false);
  const [steps, setSteps] = useState<{ action: string; target: string; result: string; success: boolean }[]>([]);
  const [report, setReport] = useState<ReportData | null>(null);
  const [history, setHistory] = useState<ReportSummary[]>([]);
  const [error, setError] = useState('');
  const [fixing, setFixing] = useState(false);
  const [showRules, setShowRules] = useState(false);

  const loadHistory = useCallback(async () => {
    if (!workspacePath) return setHistory([]);
    try {
      const { reports } = await listReports();
      setHistory(reports);
    } catch { /* ignore */ }
  }, [workspacePath]);

  useEffect(() => { setReport(null); setSteps([]); setError(''); loadHistory(); }, [workspacePath, loadHistory]);

  const run = useCallback(async () => {
    setRunning(true); setSteps([]); setReport(null); setError('');
    try {
      await streamInspect(ev => {
        if (ev.type === 'step') {
          setSteps(prev => [...prev, {
            action: String(ev.action ?? ''),
            target: String(ev.target ?? ''),
            result: String(ev.result ?? ''),
            success: ev.success !== false,
          }]);
        } else if (ev.type === 'report') {
          setReport(ev.data as ReportData);
          loadHistory();
        } else if (ev.type === 'error') {
          setError(String(ev.message ?? '检查失败'));
        }
      }, undefined, onlyChanged ? 'changed' : 'all');
    } catch (e) {
      setError(e instanceof Error ? e.message : '检查失败');
    } finally {
      setRunning(false);
    }
  }, [loadHistory, onlyChanged]);

  const handleFixIssues = useCallback((issues: ReportIssue[]) => {
    if (issues.length === 0) return;
    setFixing(true);
    onFixIssues(issues);
  }, [onFixIssues]);

  const openSaved = useCallback(async (name: string) => {
    try {
      const data = await getReport(name);
      setReport(data as ReportData);
    } catch { /* ignore */ }
  }, []);

  if (!workspacePath) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center px-4">
        <ShieldCheck className="w-8 h-8 text-gray-300" />
        <p className="text-xs text-gray-400">打开项目后可运行规范检查</p>
      </div>
    );
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="p-3 space-y-2">
        <div className="flex items-center gap-2">
          <button
            onClick={run}
            disabled={running}
            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-700 transition-colors disabled:opacity-50"
          >
            {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ShieldCheck className="w-3.5 h-3.5" />}
            {running ? '检查中...' : '运行规范检查'}
          </button>
          <button
            onClick={() => setShowRules(true)}
            disabled={running}
            className="flex items-center gap-1 px-2 py-2 rounded-lg border border-gray-200 text-gray-500 text-xs hover:bg-gray-50 hover:text-gray-700 transition-colors disabled:opacity-50"
            title="管理检查规则(内置只读,自定义可增删)"
          >
            <Settings2 className="w-3.5 h-3.5" />
            规则
          </button>
        </div>
        <label className="flex items-center gap-1.5 text-[11px] text-gray-500 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={onlyChanged}
            onChange={e => setOnlyChanged(e.target.checked)}
            className="accent-blue-600"
          />
          仅检查 git 变更文件(增量,更快;未变更文件命中 AI 审查缓存)
        </label>
        {error && <div className="text-xs text-red-500">{error}</div>}
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin">
        {running && steps.length > 0 && (
          <div className="px-3 pb-3 space-y-1">
            {steps.slice(-8).map((s, i) => (
              <div key={i} className="rounded border border-gray-100 bg-gray-50 px-2 py-1 text-[11px]">
                <span className={`inline-block w-1.5 h-1.5 rounded-full mr-1.5 ${s.success ? 'bg-green-500' : 'bg-red-500'}`} />
                <span className="font-mono text-blue-700">{s.action}</span>
                <span className="text-gray-400 font-mono ml-1 truncate">{s.target}</span>
                <div className="text-gray-500 truncate">{s.result}</div>
              </div>
            ))}
          </div>
        )}
        {report && <ReportView report={report} onFixIssues={handleFixIssues} fixing={fixing} workspacePath={workspacePath} />}
        {!report && history.length > 0 && (
          <div className="px-3 pb-4">
            <div className="text-xs font-medium text-gray-400 mb-1.5">历史报告</div>
            <ScoreTrend history={history} />
            <div className="space-y-1">
              {history.map(h => (
                <button
                  key={h.name}
                  onClick={() => openSaved(h.name)}
                  className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg border border-gray-100 bg-white text-xs hover:border-blue-300 transition-colors"
                >
                  <span className="text-gray-600">{h.created_at?.replace('T', ' ')}</span>
                  <span className={`font-semibold ${(h.score ?? 0) >= 80 ? 'text-green-600' : (h.score ?? 0) >= 50 ? 'text-amber-600' : 'text-red-600'}`}>{h.score ?? '-'}分</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      {showRules && <RulesModal onClose={() => setShowRules(false)} />}
    </div>
  );
}
