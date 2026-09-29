/** 侧边栏:视图切换、会话管理、知识库统计、用户信息 */
import { useState } from 'react';
import {
  BookOpen,
  Bug,
  Check,
  MessageSquare,
  Pencil,
  Plus,
  Settings,
  Trash2,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import type { SessionInfo } from '../lib/types';

export type MainView = 'chat' | 'knowledge' | 'models';

interface SidebarProps {
  view: MainView;
  onViewChange: (view: MainView) => void;
  sessions: SessionInfo[];
  currentSessionId: string;
  onSelectSession: (sessionId: string) => void;
  onNewSession: () => void;
  onRenameSession: (sessionId: string, name: string) => Promise<void>;
  onDeleteSession: (sessionId: string) => Promise<void>;
  knowledgeCount: number;
}

const VIEW_ITEMS: { key: MainView; icon: typeof MessageSquare; label: string }[] = [
  { key: 'chat', icon: MessageSquare, label: '对话' },
  { key: 'knowledge', icon: BookOpen, label: '知识库' },
  { key: 'models', icon: Settings, label: '模型' },
];

export default function Sidebar(props: SidebarProps) {
  const { user, logout } = useAuth();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState('');

  const startRename = (s: SessionInfo) => {
    setEditingId(s.session_id);
    setEditingName(s.name);
  };

  const commitRename = async () => {
    if (editingId && editingName.trim()) {
      await props.onRenameSession(editingId, editingName.trim());
    }
    setEditingId(null);
  };

  return (
    <aside className="w-64 shrink-0 h-full bg-white border-r border-border flex flex-col">
      {/* Logo */}
      <div className="px-4 py-4 border-b border-border flex items-center gap-2.5">
        <div className="w-9 h-9 bg-gradient-to-br from-blue-500 to-blue-600 rounded-xl flex items-center justify-center shadow-md shadow-blue-500/20">
          <Bug className="w-5 h-5 text-white" />
        </div>
        <div className="min-w-0">
          <div className="text-sm font-bold text-gray-900 truncate">TestAssistant AI</div>
          <div className="text-[11px] text-gray-400">高级测试助手</div>
        </div>
      </div>

      {/* 视图切换 */}
      <div className="px-3 pt-3 grid grid-cols-3 gap-1.5">
        {VIEW_ITEMS.map(({ key, icon: Icon, label }) => (
          <button
            key={key}
            onClick={() => props.onViewChange(key)}
            className={`flex flex-col items-center gap-1 py-2 rounded-lg text-[11px] transition-colors ${
              props.view === key
                ? 'bg-blue-50 text-blue-600 font-medium'
                : 'text-gray-500 hover:bg-gray-50'
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {/* 会话区 */}
      {props.view === 'chat' && (
        <div className="flex-1 min-h-0 flex flex-col mt-3">
          <div className="px-4 flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-gray-400">会话列表</span>
            <button
              onClick={props.onNewSession}
              className="p-1 rounded-md text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors"
              title="新建会话"
            >
              <Plus className="w-4 h-4" />
            </button>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin px-2 space-y-0.5 pb-2">
            {props.sessions.map(s => (
              <div
                key={s.session_id}
                onClick={() => props.onSelectSession(s.session_id)}
                className={`group flex items-center gap-1.5 px-2.5 py-2 rounded-lg cursor-pointer text-sm transition-colors ${
                  s.session_id === props.currentSessionId
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-gray-600 hover:bg-gray-50'
                }`}
              >
                {editingId === s.session_id ? (
                  <>
                    <input
                      autoFocus
                      value={editingName}
                      onChange={e => setEditingName(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === 'Enter') commitRename();
                        if (e.key === 'Escape') setEditingId(null);
                      }}
                      onClick={e => e.stopPropagation()}
                      className="flex-1 min-w-0 px-1.5 py-0.5 text-sm bg-white border border-blue-300 rounded outline-none"
                    />
                    <button
                      onClick={e => { e.stopPropagation(); commitRename(); }}
                      className="p-0.5 text-blue-600 hover:bg-blue-100 rounded"
                    >
                      <Check className="w-3.5 h-3.5" />
                    </button>
                  </>
                ) : (
                  <>
                    <span className="flex-1 min-w-0 truncate">{s.name}</span>
                    <span className="hidden group-hover:flex items-center gap-0.5">
                      <button
                        onClick={e => { e.stopPropagation(); startRename(s); }}
                        className="p-1 rounded text-gray-400 hover:text-blue-600 hover:bg-blue-50"
                        title="重命名"
                      >
                        <Pencil className="w-3 h-3" />
                      </button>
                      <button
                        onClick={e => { e.stopPropagation(); props.onDeleteSession(s.session_id); }}
                        className="p-1 rounded text-gray-400 hover:text-red-500 hover:bg-red-50"
                        title="删除"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </span>
                  </>
                )}
              </div>
            ))}
            {props.sessions.length === 0 && (
              <div className="px-3 py-6 text-xs text-gray-400 text-center">暂无会话</div>
            )}
          </div>
        </div>
      )}

      {props.view !== 'chat' && <div className="flex-1" />}

      {/* 知识库统计 */}
      <div className="px-4 py-3 border-t border-border">
        <div className="flex items-center justify-between text-xs">
          <span className="text-gray-400">知识库文档</span>
          <span className="font-semibold text-gray-700">{props.knowledgeCount}</span>
        </div>
      </div>

      {/* 用户信息 */}
      <div className="px-4 py-3 border-t border-border flex items-center gap-2.5">
        <div className="w-8 h-8 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center text-sm font-semibold shrink-0">
          {(user?.username || '?').slice(0, 1).toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm text-gray-800 truncate">{user?.username}</div>
        </div>
        <button
          onClick={logout}
          className="text-xs text-gray-400 hover:text-red-500 transition-colors shrink-0"
        >
          退出
        </button>
      </div>
    </aside>
  );
}
