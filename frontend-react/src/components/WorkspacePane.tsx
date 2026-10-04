/** 工作区组件:顶栏(当前项目路径 + 打开/关闭) + 右侧面板(项目文件/检查报告双 Tab,ZCode 式) */
import { useCallback, useEffect, useState } from 'react';
import { FolderOpen, FolderClosed, File as FileIcon, ListChecks, Loader2, ShieldCheck, Wrench, X } from 'lucide-react';
import {
  closeWorkspace,
  getReport,
  getWorkspace,
  getWorkspaceTree,
  listReports,
  openWorkspace,
  selectFolder,
  streamInspect,
} from '../lib/api';
import type { FileNode } from '../lib/types';
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

function TreeItem({ node, depth, expanded, toggle }: {
  node: FileNode;
  depth: number;
  expanded: Record<string, boolean>;
  toggle: (path: string) => void;
}) {
  const isDir = node.type === 'directory';
  const isOpen = !!expanded[node.path];
  return (
    <>
      <button
        onClick={() => isDir && toggle(node.path)}
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
        <TreeItem key={child.path} node={child} depth={depth + 1} expanded={expanded} toggle={toggle} />
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
              <TreeItem key={node.path} node={node} depth={0} expanded={expanded} toggle={toggle} />
            ))}
        </div>
      ) : (
        <WorkspaceInspectPane workspacePath={workspacePath} onOpen={onOpen} onFixIssues={onFixIssues} />
      )}
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

function ReportView({ report, onFixIssues, fixing }: {
  report: ReportData;
  onFixIssues: (issues: ReportIssue[]) => void;
  fixing: boolean;
}) {
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
          <div key={i} className="rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs">
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
        <button
          onClick={run}
          disabled={running}
          className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-700 transition-colors disabled:opacity-50"
        >
          {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ShieldCheck className="w-3.5 h-3.5" />}
          {running ? '检查中...' : '运行规范检查'}
        </button>
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
        {report && <ReportView report={report} onFixIssues={handleFixIssues} fixing={fixing} />}
        {!report && history.length > 0 && (
          <div className="px-3 pb-4">
            <div className="text-xs font-medium text-gray-400 mb-1.5">历史报告</div>
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
    </div>
  );
}
