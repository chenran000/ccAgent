/** 主布局:侧边栏 + 对话/知识库/模型 三视图(聊天视图常驻以保留状态) */
import { useCallback, useEffect, useState } from 'react';
import ChatPanel from './ChatPanel';
import KnowledgePanel from './KnowledgePanel';
import ModelPanel from './ModelPanel';
import Sidebar, { type MainView } from './Sidebar';
import { WorkspaceFilesPane, WorkspaceHeader, useWorkspace, type ReportIssue } from './WorkspacePane';
import { createSession, deleteSession, getKnowledgeStats, listSessions, renameSession } from '../lib/api';
import type { SessionInfo } from '../lib/types';

export default function IDELayout() {
  const [view, setView] = useState<MainView>('chat');
  const workspace = useWorkspace();
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string>(
    () => localStorage.getItem('lastSessionId') || '',
  );
  const [knowledgeCount, setKnowledgeCount] = useState(0);
  // 检查报告 → 对话的修复请求(nonce 变化触发 ChatPanel 自动发送)
  const [pendingPrompt, setPendingPrompt] = useState<{ text: string; nonce: number } | null>(null);

  const handleFixIssues = useCallback((issues: ReportIssue[]) => {
    if (issues.length === 0) return;
    const list = issues
      .map(i =>
        `- ${i.file}:${i.line} [${i.severity}/${i.rule_id}] ${i.message}`
        + (i.evidence ? `\n  证据: ${i.evidence}` : '')
        + (i.suggestion ? `\n  建议: ${i.suggestion}` : ''),
      )
      .join('\n');
    const text =
      `规范检查发现以下 ${issues.length} 个代码问题,请逐个修复:\n${list}\n\n`
      + `要求:先读目标文件定位问题,再用 write_file 修复(修改前我会确认 diff),`
      + `完成后用 search_code 自查问题已消除,最后简要总结改了什么。`;
    setPendingPrompt({ text, nonce: Date.now() });
    setView('chat');
  }, []);

  const loadKnowledgeStats = useCallback(async () => {
    try {
      const stats = await getKnowledgeStats();
      setKnowledgeCount(stats.total_docs);
    } catch { /* ignore */ }
  }, []);

  // 初始化:加载会话;无会话自动创建;恢复上次会话
  useEffect(() => {
    (async () => {
      try {
        const { sessions: list } = await listSessions();
        if (list.length === 0) {
          const created = await createSession('新会话');
          setSessions([created]);
          setCurrentSessionId(created.session_id);
          return;
        }
        setSessions(list);
        const saved = localStorage.getItem('lastSessionId');
        if (saved && list.some(s => s.session_id === saved)) {
          setCurrentSessionId(saved);
        } else {
          setCurrentSessionId(list[0].session_id);
        }
      } catch { /* ignore */ }
    })();
    loadKnowledgeStats();
  }, [loadKnowledgeStats]);

  // 持久化当前会话
  useEffect(() => {
    if (currentSessionId) {
      localStorage.setItem('lastSessionId', currentSessionId);
    }
  }, [currentSessionId]);

  const refreshSessions = useCallback(async () => {
    try {
      const { sessions: list } = await listSessions();
      setSessions(list);
    } catch { /* ignore */ }
  }, []);

  const handleNewSession = async () => {
    try {
      const created = await createSession('新会话');
      setSessions(prev => [created, ...prev]);
      setCurrentSessionId(created.session_id);
      setView('chat');
    } catch { /* ignore */ }
  };

  const handleRenameSession = async (sessionId: string, name: string) => {
    try {
      await renameSession(sessionId, name);
      setSessions(prev =>
        prev.map(s => (s.session_id === sessionId ? { ...s, name } : s)),
      );
    } catch { /* ignore */ }
  };

  const handleDeleteSession = async (sessionId: string) => {
    if (!window.confirm('删除该会话及其全部对话记录?')) return;
    try {
      await deleteSession(sessionId);
      const remaining = sessions.filter(s => s.session_id !== sessionId);
      setSessions(remaining);
      if (currentSessionId === sessionId) {
        setCurrentSessionId(remaining[0]?.session_id || '');
        if (remaining.length === 0) {
          const created = await createSession('新会话');
          setSessions([created]);
          setCurrentSessionId(created.session_id);
        }
      }
    } catch { /* ignore */ }
  };

  return (
    <div className="h-screen flex overflow-hidden bg-background">
      <Sidebar
        view={view}
        onViewChange={setView}
        sessions={sessions}
        currentSessionId={currentSessionId}
        onSelectSession={id => {
          setCurrentSessionId(id);
          setView('chat');
        }}
        onNewSession={handleNewSession}
        onRenameSession={handleRenameSession}
        onDeleteSession={handleDeleteSession}
        knowledgeCount={knowledgeCount}
      />

      <main className="flex-1 min-w-0 h-full flex flex-col bg-gray-50">
        {/* 工作区顶栏(ZCode 式:项目路径 + 打开/关闭) */}
        <WorkspaceHeader
          workspacePath={workspace.workspacePath}
          onOpen={workspace.open}
          onClose={workspace.close}
        />
        {/* 聊天视图常驻挂载(切视图不丢对话状态);右侧项目文件面板仅聊天视图显示 */}
        <div className={view === 'chat' ? 'flex-1 min-h-0 flex flex-row' : 'hidden'}>
          <div className="flex-1 min-w-0 flex flex-col">
            {currentSessionId ? (
              <ChatPanel
                currentSessionId={currentSessionId}
                onSessionsChanged={refreshSessions}
                onKnowledgeAdded={loadKnowledgeStats}
                workspacePath={workspace.workspacePath}
                pendingPrompt={pendingPrompt}
              />
            ) : (
              <div className="flex-1 flex items-center justify-center text-sm text-gray-400">
                正在准备会话...
              </div>
            )}
          </div>
          <WorkspaceFilesPane
            workspacePath={workspace.workspacePath}
            tree={workspace.tree}
            expanded={workspace.expanded}
            toggle={workspace.toggle}
            onOpen={workspace.open}
            onFixIssues={handleFixIssues}
          />
        </div>
        {view === 'knowledge' && <KnowledgePanel onStatsChange={loadKnowledgeStats} />}
        {view === 'models' && <ModelPanel />}
      </main>
    </div>
  );
}
