/** 测试执行卡片:实时步骤流、错误收集、代码问题人工确认修复 */
import { useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  FileCode,
  FileText,
  Loader2,
  Wrench,
  X,
} from 'lucide-react';
import { confirmFix, stopTest } from '../lib/api';
import type { FixResult, TestRunState } from '../lib/types';

interface TestRunCardProps {
  run: TestRunState;
  onUpdate: (mutate: (run: TestRunState) => TestRunState) => void;
}

const STATUS_BADGE: Record<TestRunState['status'], { text: string; cls: string }> = {
  running: { text: '执行中', cls: 'bg-blue-50 text-blue-600' },
  awaiting_confirm: { text: '待确认修复', cls: 'bg-amber-50 text-amber-600' },
  completed: { text: '已完成', cls: 'bg-emerald-50 text-emerald-600' },
  cancelled: { text: '已停止', cls: 'bg-gray-100 text-gray-500' },
  failed: { text: '失败', cls: 'bg-red-50 text-red-600' },
};

export default function TestRunCard({ run, onUpdate }: TestRunCardProps) {
  const [showSteps, setShowSteps] = useState(true);
  const [busyIndex, setBusyIndex] = useState<number | null>(null);
  const badge = STATUS_BADGE[run.status];

  const handleStop = async () => {
    if (!run.taskId) return;
    try {
      await stopTest(run.taskId);
      onUpdate(r => ({ ...r, message: '正在停止...' }));
    } catch { /* 忽略 */ }
  };

  const handleConfirm = async (issueIndex: number, confirmed: boolean) => {
    if (!run.taskId) return;
    setBusyIndex(issueIndex);
    try {
      const { fix_result } = await confirmFix(run.taskId, issueIndex, confirmed);
      onUpdate(r => {
        const results: FixResult[] = [
          ...r.results.filter(x => x.issue_index !== issueIndex),
          fix_result,
        ];
        const nextCursor = Math.max(r.confirmCursor, issueIndex + 1);
        const allDone = nextCursor >= r.issues.length;
        return {
          ...r,
          results,
          confirmCursor: nextCursor,
          status: allDone ? 'completed' : 'awaiting_confirm',
          message: allDone ? '修复确认处理完成' : r.message,
        };
      });
    } catch (e) {
      onUpdate(r => ({ ...r, message: `确认失败: ${e instanceof Error ? e.message : '未知错误'}` }));
    } finally {
      setBusyIndex(null);
    }
  };

  const errorCount = run.steps.filter(
    s => s.console_errors.length || s.network_errors.length || !s.success,
  ).length;

  return (
    <div className="rounded-xl border border-gray-200 bg-gray-50/60 overflow-hidden text-sm">
      {/* 头部 */}
      <div className="px-3.5 py-2.5 bg-white border-b border-gray-100 flex items-center gap-2 flex-wrap">
        <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${badge.cls}`}>
          {badge.text}
        </span>
        {run.url && (
          <span className="text-xs text-gray-500 truncate max-w-[220px]" title={run.url}>
            {run.url}
          </span>
        )}
        <span className="text-xs text-gray-400">
          {run.steps.length} 步 · {run.issues.length} 个代码问题
          {errorCount > 0 && ` · ${errorCount} 步异常`}
        </span>
        <span className="flex-1" />
        {run.status === 'running' && (
          <button
            onClick={handleStop}
            className="px-2 py-1 text-[11px] rounded-md bg-red-50 text-red-600 hover:bg-red-100 transition-colors"
          >
            停止测试
          </button>
        )}
      </div>

      {/* 步骤流 */}
      {run.steps.length > 0 && (
        <div className="border-b border-gray-100">
          <button
            onClick={() => setShowSteps(v => !v)}
            className="w-full px-3.5 py-2 flex items-center gap-1.5 text-xs text-gray-500 hover:bg-gray-50 transition-colors"
          >
            {showSteps ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
            执行步骤
          </button>
          {showSteps && (
            <div className="px-3.5 pb-2.5 space-y-1.5 max-h-64 overflow-y-auto scrollbar-thin">
              {run.steps.map(s => (
                <div key={s.step} className="flex items-start gap-2 text-xs">
                  {run.status === 'running' && s.step === run.steps.length ? (
                    <Loader2 className="w-3.5 h-3.5 mt-0.5 text-blue-500 animate-spin shrink-0" />
                  ) : s.success ? (
                    <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 text-emerald-500 shrink-0" />
                  ) : (
                    <X className="w-3.5 h-3.5 mt-0.5 text-red-500 shrink-0" />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="text-gray-700">
                      <span className="font-medium">{s.action}</span>
                      {s.target && <span className="text-gray-400"> · {s.target}</span>}
                    </div>
                    <div className="text-gray-500">{s.result}</div>
                    {(s.console_errors.length > 0 || s.network_errors.length > 0) && (
                      <div className="mt-1 space-y-0.5">
                        {[...s.console_errors, ...s.network_errors].slice(0, 3).map((err, i) => (
                          <div key={i} className="text-red-500/90 truncate" title={err}>
                            <AlertTriangle className="w-3 h-3 inline mr-1 -mt-0.5" />
                            {err.length > 120 ? `${err.slice(0, 120)}...` : err}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 代码问题与修复确认 */}
      {run.issues.length > 0 && (
        <div className="px-3.5 py-2.5 space-y-2.5">
          {run.issues.map((issue, index) => {
            const result = run.results.find(r => r.issue_index === index);
            const actionable =
              run.status === 'awaiting_confirm' && index === run.confirmCursor && !result;
            return (
              <div key={index} className="rounded-lg bg-white border border-gray-200 p-3">
                <div className="flex items-center gap-1.5 text-xs font-medium text-gray-700">
                  <Circle className="w-3 h-3 text-amber-500 fill-amber-400" />
                  <span className="truncate" title={issue.file_path}>
                    {issue.file_path}
                    {issue.line_number ? `:${issue.line_number}` : ''}
                  </span>
                </div>
                <div className="mt-1 text-xs text-gray-600">{issue.issue_description}</div>
                {result && (
                  <div className={`mt-2 text-xs ${result.confirmed && result.success ? 'text-emerald-600' : 'text-gray-400'}`}>
                    {result.confirmed
                      ? result.success
                        ? `已应用修复: ${result.fix_description || '完成'}`
                        : `修复失败: ${result.message}`
                      : '已跳过'}
                  </div>
                )}
                {actionable && (
                  <div className="mt-2 flex items-center gap-2">
                    <button
                      onClick={() => handleConfirm(index, true)}
                      disabled={busyIndex !== null}
                      className="px-2.5 py-1 text-[11px] rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors flex items-center gap-1"
                    >
                      {busyIndex === index && <Loader2 className="w-3 h-3 animate-spin" />}
                      <Wrench className="w-3 h-3" />
                      确认修复
                    </button>
                    <button
                      onClick={() => handleConfirm(index, false)}
                      disabled={busyIndex !== null}
                      className="px-2.5 py-1 text-[11px] rounded-md bg-gray-100 text-gray-600 hover:bg-gray-200 disabled:opacity-50 transition-colors"
                    >
                      跳过
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 结果消息 */}
      {run.message && run.status !== 'running' && (
        <div className="px-3.5 py-2 border-t border-gray-100 text-xs text-gray-500">{run.message}</div>
      )}

      {/* 回放脚本 */}
      {run.scriptPath && (
        <div className="px-3.5 py-2 border-t border-gray-100 text-xs text-gray-500 flex items-center gap-1.5">
          <FileCode className="w-3.5 h-3.5 shrink-0 text-blue-500" />
          <span className="truncate" title={run.scriptPath}>
            回放脚本已保存: {run.scriptPath}（可在被测项目目录直接运行，回归不再消耗 AI 调用）
          </span>
        </div>
      )}

      {/* 测试报告 */}
      {run.reportPath && (
        <div className="px-3.5 py-2 border-t border-gray-100 text-xs text-gray-500 flex items-center gap-1.5">
          <FileText className="w-3.5 h-3.5 shrink-0 text-emerald-500" />
          <span className="truncate" title={run.reportPath}>
            测试报告已生成: {run.reportPath}
          </span>
        </div>
      )}
    </div>
  );
}
