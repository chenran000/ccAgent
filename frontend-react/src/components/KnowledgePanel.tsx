/** 知识库管理面板 */
import { useCallback, useEffect, useState } from 'react';
import { BookOpen, Loader2, Pencil, Plus, Search, Trash2 } from 'lucide-react';
import {
  addKnowledge,
  deleteKnowledge,
  getKnowledgeList,
  getKnowledgeStats,
  updateKnowledge,
} from '../lib/api';
import type { KnowledgeDoc } from '../lib/types';

interface KnowledgePanelProps {
  onStatsChange: () => void;
}

export default function KnowledgePanel({ onStatsChange }: KnowledgePanelProps) {
  const [docs, setDocs] = useState<KnowledgeDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [content, setContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const { knowledge } = await getKnowledgeList();
      setDocs(knowledge);
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openAdd = () => {
    setEditingId(null);
    setContent('');
    setError('');
    setDialogOpen(true);
  };

  const openEdit = (doc: KnowledgeDoc) => {
    setEditingId(doc.doc_id);
    setContent(doc.content);
    setError('');
    setDialogOpen(true);
  };

  const save = async () => {
    const text = content.trim();
    if (!text) {
      setError('内容不能为空');
      return;
    }
    setSaving(true);
    setError('');
    try {
      if (editingId) {
        await updateKnowledge(editingId, text);
      } else {
        await addKnowledge(text);
      }
      setDialogOpen(false);
      await load();
      onStatsChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const remove = async (doc: KnowledgeDoc) => {
    if (!window.confirm('确定删除这条知识文档吗?(将同时删除其全部分块)')) return;
    try {
      await deleteKnowledge(doc.doc_id);
      await load();
      onStatsChange();
    } catch { /* ignore */ }
  };

  const filtered = search.trim()
    ? docs.filter(d => d.content.toLowerCase().includes(search.trim().toLowerCase()))
    : docs;

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {/* 头部 */}
      <div className="px-6 py-4 border-b border-border bg-white flex items-center gap-3 flex-wrap">
        <div>
          <h1 className="text-base font-bold text-gray-900">知识库管理</h1>
          <p className="text-xs text-gray-400 mt-0.5">
            共 {docs.length} 篇文档,自动分块后用于 RAG 检索增强
          </p>
        </div>
        <span className="flex-1" />
        <div className="relative">
          <Search className="w-3.5 h-3.5 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="搜索知识内容"
            className="w-48 pl-8 pr-3 py-2 text-xs bg-gray-50 border border-gray-200 rounded-lg outline-none focus:border-blue-400 transition-colors"
          />
        </div>
        <button
          onClick={openAdd}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-700 transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          添加知识
        </button>
      </div>

      {/* 文档列表 */}
      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin px-6 py-4">
        <div className="max-w-4xl mx-auto space-y-3">
          {loading && (
            <div className="py-16 text-center text-sm text-gray-400 flex items-center justify-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              加载中...
            </div>
          )}
          {!loading && filtered.length === 0 && (
            <div className="py-16 text-center text-sm text-gray-400">
              {search ? '没有匹配的知识文档' : '知识库还是空的,点击右上角"添加知识"开始'}
            </div>
          )}
          {filtered.map(doc => (
            <div
              key={doc.doc_id}
              className="rounded-xl bg-white border border-gray-200 p-4 hover:border-blue-200 transition-colors group"
            >
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center shrink-0">
                  <BookOpen className="w-4 h-4" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed max-h-40 overflow-y-auto scrollbar-thin">
                    {doc.content}
                  </p>
                  <div className="mt-2 flex items-center gap-2 text-[11px] text-gray-400">
                    <span>{doc.chunk_count} 个分块</span>
                    {typeof doc.metadata?.source === 'string' && (
                      <span>· 来源: {doc.metadata.source as string}</span>
                    )}
                  </div>
                </div>
                <div className="hidden group-hover:flex items-center gap-1 shrink-0">
                  <button
                    onClick={() => openEdit(doc)}
                    className="p-1.5 rounded-md text-gray-400 hover:text-blue-600 hover:bg-blue-50"
                    title="编辑"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => remove(doc)}
                    className="p-1.5 rounded-md text-gray-400 hover:text-red-500 hover:bg-red-50"
                    title="删除"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 添加/编辑弹窗 */}
      {dialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4">
          <div className="w-full max-w-lg bg-white rounded-2xl p-5 shadow-xl animate-slide-up">
            <h3 className="text-sm font-bold text-gray-900 mb-3">
              {editingId ? '编辑知识文档' : '添加知识文档'}
            </h3>
            <textarea
              value={content}
              onChange={e => setContent(e.target.value)}
              rows={8}
              placeholder="粘贴测试规范、接口文档、业务知识等内容,保存后自动分块入向量库"
              className="w-full px-3 py-2.5 text-sm bg-gray-50 border border-gray-200 rounded-lg outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 transition-all resize-none"
            />
            {error && <div className="mt-2 text-xs text-red-500">{error}</div>}
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setDialogOpen(false)}
                className="px-3.5 py-2 text-xs rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 transition-colors"
              >
                取消
              </button>
              <button
                onClick={save}
                disabled={saving}
                className="flex items-center gap-1.5 px-3.5 py-2 text-xs rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {saving && <Loader2 className="w-3 h-3 animate-spin" />}
                保存
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
