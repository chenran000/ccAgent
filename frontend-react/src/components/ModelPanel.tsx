/** 模型管理面板:多平台模型配置 CRUD + 活跃模型切换 + 连接测试 */
import { useCallback, useEffect, useState } from 'react';
import { Loader2, Pencil, Plus, Plug, Star, Trash2, X } from 'lucide-react';
import {
  addModel,
  clearActiveModel,
  deleteModel,
  getActiveModel,
  getModels,
  getPlatforms,
  setActiveModel,
  testAIConnection,
  updateModel,
} from '../lib/api';
import type { ActiveModel, ModelConfigInfo, SupportedPlatform } from '../lib/types';

interface FormState {
  editingId: number | null;
  platform: string;
  api_key: string;
  api_base_url: string;
  model_name: string;
}

const EMPTY_FORM: FormState = {
  editingId: null,
  platform: 'custom',
  api_key: '',
  api_base_url: '',
  model_name: '',
};

function ConfigCard(props: {
  config: ModelConfigInfo;
  isActive: boolean;
  busy: boolean;
  onSetActive: (id: number) => void;
  onEdit: (config: ModelConfigInfo) => void;
  onDelete: (id: number) => void;
}) {
  const { config, isActive, busy } = props;
  return (
    <div
      className={`rounded-xl bg-white border p-4 transition-colors ${
        isActive ? 'border-blue-300 ring-1 ring-blue-100' : 'border-gray-200 hover:border-blue-200'
      }`}
    >
      <div className="flex items-start gap-3">
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 text-sm ${isActive ? 'bg-blue-100 text-blue-600' : 'bg-gray-100 text-gray-500'}`}>
          {isActive ? <Star className="w-4 h-4 fill-blue-500" /> : <Plug className="w-4 h-4" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-gray-900">{config.platform_name}</span>
            <span className="text-xs text-gray-500">{config.model_name}</span>
            {isActive && (
              <span className="px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 text-[10px] font-medium">
                当前使用
              </span>
            )}
          </div>
          <div className="mt-1 text-[11px] text-gray-400 truncate" title={config.api_base_url}>
            {config.api_base_url}
          </div>
          <div className="text-[11px] text-gray-400">Key: {config.api_key_masked || '****'}</div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {!isActive && (
            <button
              onClick={() => props.onSetActive(config.id)}
              disabled={busy}
              className="px-2.5 py-1.5 text-[11px] rounded-md bg-blue-50 text-blue-600 hover:bg-blue-100 disabled:opacity-50 transition-colors"
            >
              设为当前
            </button>
          )}
          <button
            onClick={() => props.onEdit(config)}
            className="p-1.5 rounded-md text-gray-400 hover:text-blue-600 hover:bg-blue-50"
            title="编辑"
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => props.onDelete(config.id)}
            className="p-1.5 rounded-md text-gray-400 hover:text-red-500 hover:bg-red-50"
            title="删除"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}

export default function ModelPanel() {
  const [platforms, setPlatforms] = useState<SupportedPlatform[]>([]);
  const [builtin, setBuiltin] = useState<ModelConfigInfo[]>([]);
  const [custom, setCustom] = useState<ModelConfigInfo[]>([]);
  const [active, setActive] = useState<ActiveModel | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState<FormState | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState('');
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState('');

  const load = useCallback(async () => {
    try {
      const [platformList, modelList, activeModel] = await Promise.all([
        getPlatforms(),
        getModels(),
        getActiveModel(),
      ]);
      setPlatforms(platformList);
      setBuiltin(modelList.builtin);
      setCustom(modelList.custom);
      setActive(activeModel);
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openAdd = () => {
    setForm({ ...EMPTY_FORM });
    setFormError('');
    setTestResult('');
  };

  const openEdit = (config: ModelConfigInfo) => {
    setForm({
      editingId: config.id,
      platform: config.platform,
      api_key: '',
      api_base_url: config.api_base_url,
      model_name: config.model_name,
    });
    setFormError('');
    setTestResult('');
  };

  const handlePlatformChange = (key: string) => {
    const platform = platforms.find(p => p.key === key);
    setForm(f =>
      f ? { ...f, platform: key, api_base_url: platform?.default_base_url || f.api_base_url } : f,
    );
  };

  const save = async () => {
    if (!form) return;
    if (!form.model_name.trim() || !form.api_base_url.trim()) {
      setFormError('模型名称与 API 地址不能为空');
      return;
    }
    setSaving(true);
    setFormError('');
    try {
      if (form.editingId) {
        const payload: { api_base_url: string; model_name: string; api_key?: string } = {
          api_base_url: form.api_base_url.trim(),
          model_name: form.model_name.trim(),
        };
        if (form.api_key.trim()) payload.api_key = form.api_key.trim();
        await updateModel(form.editingId, payload);
      } else {
        await addModel({
          api_key: form.api_key.trim(),
          api_base_url: form.api_base_url.trim(),
          model_name: form.model_name.trim(),
        });
      }
      setForm(null);
      await load();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const runTest = async () => {
    if (!form) return;
    setTesting(true);
    setTestResult('');
    try {
      const { success, message } = await testAIConnection({
        api_key: form.api_key.trim(),
        api_base_url: form.api_base_url.trim(),
        chat_model: form.model_name.trim(),
      });
      setTestResult(message);
      if (!success) setTestResult(`连接失败: ${message}`);
    } catch (e) {
      setTestResult(`连接失败: ${e instanceof Error ? e.message : '未知错误'}`);
    } finally {
      setTesting(false);
    }
  };

  const handleSetActive = async (id: number) => {
    setBusy(true);
    try {
      await setActiveModel(id);
      await load();
    } catch { /* ignore */ } finally {
      setBusy(false);
    }
  };

  const handleClearActive = async () => {
    setBusy(true);
    try {
      await clearActiveModel();
      await load();
    } catch { /* ignore */ } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('确定删除这个模型配置吗?')) return;
    setBusy(true);
    try {
      await deleteModel(id);
      await load();
    } catch { /* ignore */ } finally {
      setBusy(false);
    }
  };

  const renderGroup = (title: string, list: ModelConfigInfo[]) => (
    <div className="mb-5">
      <h3 className="text-xs font-medium text-gray-400 mb-2">{title}</h3>
      <div className="space-y-2.5">
        {list.map(config => (
          <ConfigCard
            key={config.id}
            config={config}
            isActive={active?.use_default === false && active.model_config_id === config.id}
            busy={busy}
            onSetActive={handleSetActive}
            onEdit={openEdit}
            onDelete={handleDelete}
          />
        ))}
        {list.length === 0 && (
          <div className="text-xs text-gray-300 px-1 py-2">暂无配置</div>
        )}
      </div>
    </div>
  );

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {/* 头部 */}
      <div className="px-6 py-4 border-b border-border bg-white flex items-center gap-3 flex-wrap">
        <div>
          <h1 className="text-base font-bold text-gray-900">AI 模型管理</h1>
          <p className="text-xs text-gray-400 mt-0.5">
            当前使用:
            {active?.use_default === false
              ? ` ${active.model_name} (${active.platform})`
              : ' 默认模型(未配置时功能不可用)'}
          </p>
        </div>
        <span className="flex-1" />
        {active?.use_default === false && (
          <button
            onClick={handleClearActive}
            disabled={busy}
            className="px-3 py-2 rounded-lg bg-gray-100 text-gray-600 text-xs hover:bg-gray-200 disabled:opacity-50 transition-colors"
          >
            恢复默认
          </button>
        )}
        <button
          onClick={openAdd}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-700 transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          添加模型
        </button>
      </div>

      {/* 配置列表 */}
      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin px-6 py-4">
        <div className="max-w-4xl mx-auto">
          {loading && (
            <div className="py-16 text-center text-sm text-gray-400 flex items-center justify-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              加载中...
            </div>
          )}
          {!loading && (
            <>
              {renderGroup('内置平台', builtin)}
              {renderGroup('自定义模型', custom)}
            </>
          )}
        </div>
      </div>

      {/* 添加/编辑弹窗 */}
      {form && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4">
          <div className="w-full max-w-md bg-white rounded-2xl p-5 shadow-xl animate-slide-up">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-bold text-gray-900">
                {form.editingId ? '编辑模型配置' : '添加模型配置'}
              </h3>
              <button
                onClick={() => setForm(null)}
                className="p-1 text-gray-400 hover:text-gray-600"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">平台</label>
                <select
                  value={form.platform}
                  onChange={e => handlePlatformChange(e.target.value)}
                  className="w-full px-3 py-2 text-sm bg-gray-50 border border-gray-200 rounded-lg outline-none focus:border-blue-400 transition-colors"
                >
                  {platforms.map(p => (
                    <option key={p.key} value={p.key}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">
                  API Key{form.editingId ? '(留空则不修改)' : ''}
                </label>
                <input
                  type="password"
                  value={form.api_key}
                  onChange={e => setForm(f => (f ? { ...f, api_key: e.target.value } : f))}
                  placeholder={form.editingId ? '不修改请留空' : 'sk-...'}
                  className="w-full px-3 py-2 text-sm bg-gray-50 border border-gray-200 rounded-lg outline-none focus:border-blue-400 transition-colors"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">API Base URL</label>
                <input
                  value={form.api_base_url}
                  onChange={e => setForm(f => (f ? { ...f, api_base_url: e.target.value } : f))}
                  placeholder="https://api.deepseek.com/v1"
                  className="w-full px-3 py-2 text-sm bg-gray-50 border border-gray-200 rounded-lg outline-none focus:border-blue-400 transition-colors"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">模型名称</label>
                <input
                  value={form.model_name}
                  onChange={e => setForm(f => (f ? { ...f, model_name: e.target.value } : f))}
                  placeholder="deepseek-chat"
                  className="w-full px-3 py-2 text-sm bg-gray-50 border border-gray-200 rounded-lg outline-none focus:border-blue-400 transition-colors"
                />
              </div>

              {formError && <div className="text-xs text-red-500">{formError}</div>}
              {testResult && (
                <div className={`text-xs ${testResult.startsWith('连接失败') ? 'text-red-500' : 'text-emerald-600'}`}>
                  {testResult}
                </div>
              )}
            </div>

            <div className="mt-4 flex justify-between items-center">
              <button
                onClick={runTest}
                disabled={testing || !form.api_key.trim()}
                className="flex items-center gap-1.5 px-3 py-2 text-xs rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 disabled:opacity-50 transition-colors"
              >
                {testing && <Loader2 className="w-3 h-3 animate-spin" />}
                测试连接
              </button>
              <div className="flex gap-2">
                <button
                  onClick={() => setForm(null)}
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
        </div>
      )}
    </div>
  );
}
