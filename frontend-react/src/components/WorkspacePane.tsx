/** 工作区组件:顶栏(当前项目路径 + 打开/关闭) + 右侧文件树(ZCode 式工作区交互) */
import { useCallback, useEffect, useState } from 'react';
import { FolderOpen, FolderClosed, File as FileIcon, X } from 'lucide-react';
import {
  closeWorkspace,
  getWorkspace,
  getWorkspaceTree,
  openWorkspace,
  selectFolder,
} from '../lib/api';
import type { FileNode } from '../lib/types';

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
export function WorkspaceFilesPane({ workspacePath, tree, expanded, toggle, onOpen }: {
  workspacePath: string | null;
  tree: FileNode[];
  expanded: Record<string, boolean>;
  toggle: (path: string) => void;
  onOpen: () => void;
}) {
  if (!workspacePath) {
    return (
      <div className="w-64 shrink-0 border-l border-border bg-white flex flex-col items-center justify-center gap-3 px-4">
        <FolderOpen className="w-8 h-8 text-gray-300" />
        <p className="text-xs text-gray-400 text-center">未打开项目</p>
        <button
          onClick={onOpen}
          className="text-xs text-blue-600 hover:text-blue-700 font-medium"
        >
          打开项目文件夹
        </button>
      </div>
    );
  }
  return (
    <div className="w-64 shrink-0 border-l border-border bg-white flex flex-col">
      <div className="h-9 shrink-0 flex items-center px-3 border-b border-border">
        <span className="text-xs font-medium text-gray-400">项目文件</span>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin py-1">
        {tree.length === 0
          ? <div className="px-3 py-4 text-xs text-gray-400">空目录</div>
          : tree.map(node => (
            <TreeItem key={node.path} node={node} depth={0} expanded={expanded} toggle={toggle} />
          ))}
      </div>
    </div>
  );
}
