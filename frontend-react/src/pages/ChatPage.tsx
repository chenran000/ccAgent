import { useState, useEffect, useCallback, useRef } from 'react';
import { useAuth, apiFetch } from '../context/AuthContext';
import { API_BASE } from '../config';
import {
  LogOut, FileText, AlertTriangle, BookOpen, Send, Plus, Trash2,
  Loader2, Sparkles, Pencil, Save, X, MessageSquare, Zap, Settings,
  FileUp, Bug, CheckCircle, AlertCircle, ClipboardList, Globe, FolderOpen, Code, TestTube
} from 'lucide-react';

import TestWorkspace from './TestWorkspace';

type ModuleType = 'code' | 'case' | 'knowledge';

interface Message {
  id: number;
  input: string;
  output: any;
  time: string;
  intent?: string;
  module?: string;
  session_id?: string;
}

interface KnowledgeItem {
  doc_id: string;
  content: string;
  metadata: Record<string, any>;
}

interface Session {
  session_id: string;
  name: string;
  created_at: string;
  updated_at: string;
}

interface FileItem {
  id: number;
  original_filename: string;
  file_type: string;
  file_size: number;
  created_at: string;
  extracted_text_preview: string;
}

// Intent config for display
const INTENT_CONFIG: Record<string, { icon: React.ReactNode; label: string; color: string }> = {
  code: { icon: <Code className="w-3 h-3" />, label: '代码分析', color: 'bg-blue-500/20 text-blue-400 border-blue-500/30' },
  case: { icon: <TestTube className="w-3 h-3" />, label: '用例生成', color: 'bg-purple-500/20 text-purple-400 border-purple-500/30' },
  knowledge: { icon: <BookOpen className="w-3 h-3" />, label: '测试文档', color: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' },
  chat: { icon: <MessageSquare className="w-3 h-3" />, label: '对话', color: 'bg-amber-500/20 text-amber-400 border-amber-500/30' },
};

const EXAMPLES = [
  { icon: <Code className="w-3.5 h-3.5" />, label: '分析代码', text: '帮我分析这段代码的边界条件和潜在bug' },
  { icon: <TestTube className="w-3.5 h-3.5" />, label: '生成用例', text: '为登录功能生成测试用例，包含正常和异常场景' },
  { icon: <BookOpen className="w-3.5 h-3.5" />, label: '添加文档', text: '添加到测试文档库：Web自动化测试规范' },
  { icon: <MessageSquare className="w-3.5 h-3.5" />, label: '随便聊聊', text: '你好，请问你能帮我做什么测试工作？' },
];

export default function ChatPage() {
  const { user, logout } = useAuth();
  const [showWorkspace, setShowWorkspace] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputText, setInputText] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [useRag, setUseRag] = useState(false);
  const [docCount, setDocCount] = useState(0);
  const [totalCount, setTotalCount] = useState(0);
  const [showKnowledge, setShowKnowledge] = useState(false);

  // Session state
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState('');
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);

  // Knowledge management state
  const [knowledgeList, setKnowledgeList] = useState<KnowledgeItem[]>([]);
  const [editingDoc, setEditingDoc] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');
  const [deletingDocId, setDeletingDocId] = useState<string | null>(null);
  const [showClearChatConfirm, setShowClearChatConfirm] = useState(false);

  // AI Model Management state
  const [showSettings, setShowSettings] = useState(false);
  const [supportedPlatforms, setSupportedPlatforms] = useState<any[]>([]);
  const [builtinModels, setBuiltinModels] = useState<any[]>([]);
  const [customModels, setCustomModels] = useState<any[]>([]);
  const [activeModelId, setActiveModelId] = useState<number | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [editingModelId, setEditingModelId] = useState<number | null>(null);
  const [addPlatform, setAddPlatform] = useState('deepseek');
  const [addApiKey, setAddApiKey] = useState('');
  const [addBaseUrl, setAddBaseUrl] = useState('');
  const [addModelName, setAddModelName] = useState('');
  const [isSavingModel, setIsSavingModel] = useState(false);
  const [isTestingModel, setIsTestingModel] = useState(false);
  const [settingsStatus, setSettingsStatus] = useState<{type: 'success' | 'error' | null; message: string}>({type: null, message: ''});
  const [showAddApiKey, setShowAddApiKey] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<{builtin: boolean; custom: boolean}>({builtin: true, custom: true});

  // File upload state
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploadingFile, setIsUploadingFile] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // File management panel state
  const [showFilePanel, setShowFilePanel] = useState(false);
  const [fileList, setFileList] = useState<FileItem[]>([]);
  const [isUploadingFilePanel, setIsUploadingFilePanel] = useState(false);
  const [deletingFileId, setDeletingFileId] = useState<number | null>(null);
  const [selectedFileId, setSelectedFileId] = useState<number | null>(null);
  const [filePanelUploadFile, setFilePanelUploadFile] = useState<File | null>(null);
  const pendingFileRef = useRef<File | null>(null);
  const [confirmUploadFile, setConfirmUploadFile] = useState<{name: string; size: number; type: string} | null>(null);
  const filePanelInputRef = useRef<HTMLInputElement>(null);

  // Web Test Agent state
  const [showTestPanel, setShowTestPanel] = useState(false);
  const [testTargetUrl, setTestTargetUrl] = useState('');
  const [testProjectPath, setTestProjectPath] = useState('');
  const [testGoals, setTestGoals] = useState('');
  const [isTestRunning, setIsTestRunning] = useState(false);
  const [testTaskId, setTestTaskId] = useState<string | null>(null);
  const [testStatus, setTestStatus] = useState<string>('');
  const [testMessage, setTestMessage] = useState('');
  const [testSteps, setTestSteps] = useState<any[]>([]);
  const [testCodeIssues, setTestCodeIssues] = useState<any[]>([]);
  const [testErrorsFound, setTestErrorsFound] = useState(0);
  const [testScreenshotsSaved, setTestScreenshotsSaved] = useState(0);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const currentSessionIdRef = useRef<string | null>(null);

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      if (messagesEndRef.current) {
        messagesEndRef.current.scrollIntoView({ behavior: 'instant' });
      }
    });
  }, []);

  // Keep ref in sync
  useEffect(() => {
    currentSessionIdRef.current = currentSessionId;
  }, [currentSessionId]);

  useEffect(() => { scrollToBottom(); }, [messages, scrollToBottom]);

  // Load sessions on mount & restore last session
  useEffect(() => {
    const lastSessionId = localStorage.getItem('lastSessionId');
    loadSessions(lastSessionId);
    updateKnowledgeStats();
  }, []);

  // Load conversations when session changes & persist
  useEffect(() => {
    if (currentSessionId !== undefined) {
      loadMessages(currentSessionId);
      if (currentSessionId) {
        localStorage.setItem('lastSessionId', currentSessionId);
      }
    }
  }, [currentSessionId]);

  useEffect(() => {
    if (showKnowledge) {
      loadKnowledgeList();
    }
  }, [showKnowledge]);

  useEffect(() => {
    if (showFilePanel) {
      loadFileList();
    }
  }, [showFilePanel]);

  // Load AI settings
  useEffect(() => {
    if (showSettings) {
      loadPlatforms();
      loadModels();
      loadActiveModel();
    }
  }, [showSettings]);

  const loadPlatforms = async () => {
    try {
      const res = await apiFetch('/settings/platforms');
      if (!res.ok) return;
      const data = await res.json();
      if (Array.isArray(data)) {
        setSupportedPlatforms(data);
      }
    } catch {}
  };

  const loadModels = async () => {
    try {
      const res = await apiFetch('/settings/models');
      const data = await res.json();
      setBuiltinModels(Array.isArray(data?.builtin) ? data.builtin : []);
      setCustomModels(Array.isArray(data?.custom) ? data.custom : []);
    } catch {}
  };

  const loadActiveModel = async () => {
    try {
      const res = await apiFetch('/settings/active');
      const data = await res.json();
      setActiveModelId(data.model_config_id || null);
    } catch {}
  };

  const resetAddModal = () => {
    setAddPlatform('deepseek');
    setAddApiKey('');
    setAddBaseUrl('');
    setAddModelName('');
    setShowAddApiKey(false);
    setSettingsStatus({type: null, message: ''});
  };

  const handlePlatformChange = (platformKey: string) => {
    setAddPlatform(platformKey);
    const platform = supportedPlatforms.find((p: any) => p.key === platformKey);
    if (platform) {
      setAddBaseUrl(platform.default_base_url);
      if (platformKey === 'custom') {
        setAddModelName('');
      } else {
        // Auto-fill first model name for known platforms
        setAddModelName('');
      }
    }
  };

  const addModel = async () => {
    setIsSavingModel(true);
    setSettingsStatus({type: null, message: ''});
    try {
      if (!addApiKey.trim() || !addModelName.trim()) {
        setSettingsStatus({type: 'error', message: '请填写 API Key 和模型名称'});
        return;
      }
      const res = await apiFetch('/settings/models', {
        method: 'POST',
        body: JSON.stringify({
          platform: addPlatform,
          api_key: addApiKey,
          api_base_url: addBaseUrl || supportedPlatforms.find((p: any) => p.key === addPlatform)?.default_base_url || '',
          model_name: addModelName,
        }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
      setSettingsStatus({type: 'success', message: '模型添加成功'});
      loadModels();
      loadActiveModel();
      setTimeout(() => { setShowAddModal(false); setSettingsStatus({type: null, message: ''}); }, 800);
    } catch (e: any) {
      setSettingsStatus({type: 'error', message: e.message});
    } finally {
      setIsSavingModel(false);
    }
  };

  const testModelConnection = async (apiKey: string, baseUrl: string, modelName: string) => {
    setIsTestingModel(true);
    setSettingsStatus({type: null, message: ''});
    try {
      if (!apiKey || !modelName) {
        setSettingsStatus({type: 'error', message: '请先填写 API Key 和模型名称'});
        return;
      }
      const res = await apiFetch('/settings/ai/test', {
        method: 'POST',
        body: JSON.stringify({
          api_key: apiKey,
          api_base_url: baseUrl,
          chat_model: modelName,
        }),
      });
      const data = await res.json();
      if (data.success) {
        setSettingsStatus({type: 'success', message: data.message || '连接成功'});
      } else {
        setSettingsStatus({type: 'error', message: data.message || '连接失败'});
      }
    } catch (e: any) {
      setSettingsStatus({type: 'error', message: e.message});
    } finally {
      setIsTestingModel(false);
    }
  };

  const setActiveModel = async (configId: number) => {
    try {
      const res = await apiFetch(`/settings/active/${configId}`, { method: 'POST' });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
      setActiveModelId(configId);
      loadModels();
    } catch (e: any) {
      setSettingsStatus({type: 'error', message: e.message});
    }
  };

  const resetToDefault = async () => {
    try {
      const res = await apiFetch('/settings/active', { method: 'DELETE' });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
      setActiveModelId(null);
      loadModels();
      setSettingsStatus({type: 'success', message: '已取消选择模型'});
    } catch (e: any) {
      setSettingsStatus({type: 'error', message: e.message});
    }
  };

  const deleteModel = async (configId: number) => {
    try {
      const res = await apiFetch(`/settings/models/${configId}`, { method: 'DELETE' });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
      if (activeModelId === configId) {
        setActiveModelId(null);
      }
      loadModels();
      loadActiveModel();
    } catch (e: any) {
      setSettingsStatus({type: 'error', message: e.message});
    }
  };

  const loadSessions = async (restoreSessionId?: string | null) => {
    try {
      const res = await apiFetch('/sessions');
      if (!res.ok) throw new Error();
      const data = await res.json();
      setSessions(data.sessions || []);
      // 恢复上次会话或使用当前会话
      const activeSessionId = currentSessionIdRef.current;
      if (restoreSessionId && data.sessions?.some((s: any) => s.session_id === restoreSessionId)) {
        setCurrentSessionId(restoreSessionId);
      } else if (activeSessionId && data.sessions?.some((s: any) => s.session_id === activeSessionId)) {
        // 当前会话仍然有效，保持
      } else if (data.sessions?.length > 0 && !activeSessionId) {
        setCurrentSessionId(data.sessions[0].session_id);
      } else if (data.sessions?.length === 0) {
        setCurrentSessionId(null);
      }
    } catch {
      setSessions([]);
      setCurrentSessionId(null);
    }
  };

  const loadMessages = async (sessionId: string | null) => {
    try {
      const url = sessionId ? `/conversations?session_id=${sessionId}&limit=100` : '/conversations?limit=100';
      const res = await apiFetch(url);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setTotalCount(data.total || 0);
      // Already sorted ASC by created_at on backend
      setMessages(data.conversations.map((c: any) => {
        const parsed = JSON.parse(c.output_data);
        if (parsed.records || parsed.policyholder_name !== undefined) {
          return { id: c.id, input: c.input_text, output: { intent: 'extract', module: 'extract', data: parsed, message: '' }, time: c.created_at, intent: 'extract', module: 'extract', session_id: c.session_id };
        }
        if (parsed.category !== undefined) {
          return { id: c.id, input: c.input_text, output: { intent: 'complaint', module: 'complaint', data: parsed, message: '' }, time: c.created_at, intent: 'complaint', module: 'complaint', session_id: c.session_id };
        }
        if (parsed.doc_id !== undefined) {
          return { id: c.id, input: c.input_text, output: { intent: 'knowledge', module: 'knowledge', data: parsed, message: '' }, time: c.created_at, intent: 'knowledge', module: 'knowledge', session_id: c.session_id };
        }
        if (parsed.answer !== undefined) {
          return { id: c.id, input: c.input_text, output: { intent: 'chat', module: 'chat', data: parsed, message: '' }, time: c.created_at, intent: 'chat', module: 'chat', session_id: c.session_id };
        }
        if (parsed.intent) {
          return { id: c.id, input: c.input_text, output: parsed, time: c.created_at, intent: parsed.intent, module: parsed.module, session_id: c.session_id };
        }
        return { id: c.id, input: c.input_text, output: { intent: 'chat', module: 'chat', data: { answer: parsed.message || '', has_knowledge: false, references: [] }, message: '' }, time: c.created_at, intent: 'chat', module: 'chat', session_id: c.session_id };
      }));
    } catch { setMessages([]); }
  };

  const updateKnowledgeStats = async () => {
    try {
      const res = await apiFetch('/knowledge/stats');
      const data = await res.json();
      setDocCount(data.total_docs || 0);
    } catch {}
  };

  const loadKnowledgeList = async () => {
    try {
      const res = await apiFetch('/knowledge/list');
      if (!res.ok) throw new Error();
      const data = await res.json();
      setKnowledgeList(data.knowledge || []);
    } catch { setKnowledgeList([]); }
  };

  const createNewSession = async () => {
    try {
      const res = await apiFetch('/sessions', {
        method: 'POST',
        body: JSON.stringify({ name: '新会话' }),
      });
      if (!res.ok) throw new Error();
      const data = await res.json();
      setSessions(prev => [data, ...prev]);
      setCurrentSessionId(data.session_id);
      setMessages([]);
      setTotalCount(0);
    } catch (e: any) {
      alert('创建会话失败: ' + e.message);
    }
  };

  const deleteSession = async (sessionId: string) => {
    try {
      const res = await apiFetch(`/sessions/${sessionId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error();
      setSessions(prev => prev.filter(s => s.session_id !== sessionId));
      if (currentSessionId === sessionId) {
        // Switch to next session or null
        const remaining = sessions.filter(s => s.session_id !== sessionId);
        setCurrentSessionId(remaining.length > 0 ? remaining[0].session_id : null);
      }
    } catch (e: any) {
      alert('删除会话失败: ' + e.message);
    } finally {
      setDeletingSessionId(null);
    }
  };

  const saveSessionName = async (sessionId: string, name: string) => {
    try {
      const res = await apiFetch(`/sessions/${sessionId}`, {
        method: 'PUT',
        body: JSON.stringify({ name }),
      });
      if (!res.ok) throw new Error('保存失败');
      const data = await res.json();
      setSessions(prev => prev.map(s => s.session_id === sessionId ? { ...s, name: data.name } : s));
    } catch (e: any) {
      alert('重命名失败: ' + e.message);
    } finally {
      setEditingSessionId(null);
      setEditingName('');
    }
  };

  const handleDeleteKnowledge = async (docId: string) => {
    setDeletingDocId(docId);
  };

  const [showAddKnowledge, setShowAddKnowledge] = useState(false);
  const [newKnowledgeContent, setNewKnowledgeContent] = useState('');
  const [isAddingKnowledge, setIsAddingKnowledge] = useState(false);

  const handleAddKnowledge = async () => {
    if (!newKnowledgeContent.trim() || isAddingKnowledge) return;
    setIsAddingKnowledge(true);
    try {
      const res = await apiFetch('/knowledge/add', {
        method: 'POST',
        body: JSON.stringify({ content: newKnowledgeContent.trim(), metadata: {} }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
      setNewKnowledgeContent('');
      setShowAddKnowledge(false);
      loadKnowledgeList();
      updateKnowledgeStats();
    } catch (e: any) {
      alert('添加失败: ' + e.message);
    } finally {
      setIsAddingKnowledge(false);
    }
  };

  const confirmDelete = async () => {
    if (!deletingDocId) return;
    const docId = deletingDocId;
    try {
      const res = await apiFetch(`/knowledge/${docId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error();
      setKnowledgeList(prev => prev.filter(k => k.doc_id !== docId));
      if (editingDoc === docId) { setEditingDoc(null); setEditContent(''); }
      updateKnowledgeStats();
    } catch (e: any) {
      alert('删除失败: ' + e.message);
    } finally {
      setDeletingDocId(null);
    }
  };

  const cancelDelete = () => setDeletingDocId(null);

  const startEdit = (doc: KnowledgeItem) => {
    setEditingDoc(doc.doc_id);
    setEditContent(doc.content);
  };

  const cancelEdit = () => {
    setEditingDoc(null);
    setEditContent('');
  };

  const saveEdit = async (docId: string) => {
    if (!editContent.trim()) return;
    try {
      const res = await apiFetch(`/knowledge/${docId}`, {
        method: 'PUT',
        body: JSON.stringify({ content: editContent.trim(), metadata: {} }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
      setEditingDoc(null);
      setEditContent('');
      loadKnowledgeList();
      updateKnowledgeStats();
    } catch (e: any) {
      alert('编辑失败: ' + e.message);
    }
  };

  // File management functions
  const loadFileList = async () => {
    try {
      const res = await apiFetch('/files');
      if (!res.ok) throw new Error();
      const data = await res.json();
      setFileList(data.files || []);
    } catch { setFileList([]); }
  };

  const handleFilePanelSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.pdf') && !file.name.toLowerCase().endsWith('.txt')) {
      alert('仅支持 PDF 和 TXT 文件');
      return;
    }
    // Store file in ref (File objects can't be in state)
    pendingFileRef.current = file;
    setConfirmUploadFile({
      name: file.name,
      size: file.size,
      type: file.type,
    });
  };

  const handleFilePanelUpload = async (file: File) => {
    if (!file || isUploadingFilePanel) return;
    setIsUploadingFilePanel(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const token = localStorage.getItem('auth_token');
      const res = await fetch(`${API_BASE}/files/upload`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData,
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
      loadFileList();
    } catch (e: any) {
      alert('文件上传失败: ' + e.message);
    } finally {
      setIsUploadingFilePanel(false);
      setFilePanelUploadFile(null);
      if (filePanelInputRef.current) filePanelInputRef.current.value = '';
    }
  };

  const deleteFile = async (fileId: number) => {
    try {
      const res = await apiFetch(`/files/${fileId}`, { method: 'DELETE' });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
      setFileList(prev => prev.filter(f => f.id !== fileId));
      if (selectedFileId === fileId) setSelectedFileId(null);
    } catch (e: any) {
      alert('文件删除失败: ' + e.message);
    } finally {
      setDeletingFileId(null);
    }
  };

  const sendChatWithFile = async (fileId: number) => {
    const text = inputText.trim() || '请读取这个文件的内容并总结';
    setInputText('');
    setIsProcessing(true);

    const tempId = Date.now();
    setMessages(prev => [...prev, {
      id: tempId,
      input: `[引用文件] ${text}`,
      output: null as any,
      time: new Date().toISOString(),
      intent: '',
      module: '',
      session_id: currentSessionId || '',
    }]);

    try {
      const res = await apiFetch('/chat', {
        method: 'POST',
        body: JSON.stringify({ content: text, use_rag: useRag, session_id: currentSessionId, file_id: fileId }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
      const data = await res.json();

      if (data.module === 'knowledge') {
        loadKnowledgeList();
      }

      loadSessions();
      loadFileList();

      setMessages(prev => {
        const updated = [...prev];
        const idx = updated.findIndex(m => m.id === tempId);
        if (idx !== -1) {
          updated[idx] = {
            id: tempId,
            input: `[引用文件] ${text}`,
            output: { intent: data.intent, module: data.module, data: data.data, message: data.message },
            time: updated[idx].time,
            intent: data.intent,
            module: data.module,
            session_id: data.session_id || currentSessionId || '',
          };
        }
        return updated;
      });
      setTotalCount(prev => prev + 1);
      updateKnowledgeStats();
    } catch (e: any) {
      setMessages(prev => {
        const updated = [...prev];
        const idx = updated.findIndex(m => m.id === tempId);
        if (idx !== -1) {
          updated[idx] = {
            id: tempId,
            input: `[引用文件] ${text}`,
            output: { error: e.message },
            time: updated[idx].time,
            intent: '',
            module: '',
            session_id: currentSessionId || '',
          };
        }
        return updated;
      });
    } finally {
      setIsProcessing(false);
    }
  };

  const handleSend = async () => {
    if (!inputText.trim() || isProcessing) return;
    const text = inputText.trim();
    setInputText('');
    setIsProcessing(true);

    const tempId = Date.now();
    setMessages(prev => [...prev, {
      id: tempId,
      input: text,
      output: null as any,
      time: new Date().toISOString(),
      intent: '',
      module: '',
      session_id: currentSessionId || '',
    }]);

    try {
      const res = await apiFetch('/chat', {
        method: 'POST',
        body: JSON.stringify({ content: text, use_rag: useRag, session_id: currentSessionId }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
      const data = await res.json();

      if (data.module === 'knowledge') {
        loadKnowledgeList();
      }

      // Refresh sessions to get updated names
      loadSessions();

      setMessages(prev => {
        const updated = [...prev];
        const idx = updated.findIndex(m => m.id === tempId);
        if (idx !== -1) {
          updated[idx] = {
            id: tempId,
            input: text,
            output: { intent: data.intent, module: data.module, data: data.data, message: data.message },
            time: updated[idx].time,
            intent: data.intent,
            module: data.module,
            session_id: data.session_id || currentSessionId || '',
          };
        }
        return updated;
      });
      setTotalCount(prev => prev + 1);
      updateKnowledgeStats();
    } catch (e: any) {
      setMessages(prev => {
        const updated = [...prev];
        const idx = updated.findIndex(m => m.id === tempId);
        if (idx !== -1) {
          updated[idx] = {
            id: tempId,
            input: text,
            output: { error: e.message },
            time: updated[idx].time,
            intent: '',
            module: '',
            session_id: currentSessionId || '',
          };
        }
        return updated;
      });
    } finally {
      setIsProcessing(false);
    }
  };

  const handleFileUpload = async (file: File) => {
    if (!file || isUploadingFile || !currentSessionId) return;
    setIsUploadingFile(true);

    const tempId = Date.now();
    setMessages(prev => [...prev, {
      id: tempId,
      input: `[上传文件: ${file.name}]`,
      output: null as any,
      time: new Date().toISOString(),
      intent: 'extract',
      module: 'extract',
      session_id: currentSessionId,
    }]);

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('use_rag', String(useRag));
      if (currentSessionId) formData.append('session_id', currentSessionId);

      const token = localStorage.getItem('auth_token');
      const res = await fetch(`${API_BASE}/extractPolicyInfo/file`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
        body: formData,
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
      const data = await res.json();

      loadSessions();

      setMessages(prev => {
        const updated = [...prev];
        const idx = updated.findIndex(m => m.id === tempId);
        if (idx !== -1) {
          updated[idx] = {
            id: tempId,
            input: `[上传文件: ${file.name}]`,
            output: { intent: 'extract', module: 'extract', data, message: '文件提取成功' },
            time: updated[idx].time,
            intent: 'extract',
            module: 'extract',
            session_id: data.session_id || currentSessionId || '',
          };
        }
        return updated;
      });
      setTotalCount(prev => prev + 1);
      updateKnowledgeStats();
    } catch (e: any) {
      setMessages(prev => {
        const updated = [...prev];
        const idx = updated.findIndex(m => m.id === tempId);
        if (idx !== -1) {
          updated[idx] = {
            id: tempId,
            input: `[上传文件: ${file.name}]`,
            output: { error: e.message },
            time: updated[idx].time,
            intent: 'extract',
            module: 'extract',
            session_id: currentSessionId,
          };
        }
        return updated;
      });
    } finally {
      setIsUploadingFile(false);
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      alert('仅支持 PDF 文件');
      return;
    }
    setSelectedFile(file);
    handleFileUpload(file);
  };

  const clearAllChat = async () => {
    if (messages.length === 0) return;
    setShowClearChatConfirm(false);
    try {
      const dbIds = messages.map(m => m.id).filter(id => id < 1000000000000);
      if (dbIds.length > 0) {
        await Promise.allSettled(
          dbIds.map(id => apiFetch(`/conversations/${id}`, { method: 'DELETE' }))
        );
      }
      setMessages([]);
      setTotalCount(0);
    } catch (e: any) {
      setMessages([]);
      setTotalCount(0);
    }
  };

  const handleTestRun = async () => {
    if (!testTargetUrl.trim() || !testProjectPath.trim() || !testGoals.trim() || isTestRunning) return;
    setIsTestRunning(true);
    setTestSteps([]);
    setTestCodeIssues([]);
    setTestStatus('running');
    setTestMessage('Web测试Agent正在执行...');

    try {
      const goals = testGoals.split('\n').map(g => g.trim()).filter(Boolean);
      const res = await apiFetch('/test/run', {
        method: 'POST',
        body: JSON.stringify({
          target_url: testTargetUrl.trim(),
          project_path: testProjectPath.trim(),
          test_goals: goals,
          max_steps: 30,
        }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
      const data = await res.json();

      setTestTaskId(data.task_id);
      setTestSteps(data.steps || []);
      setTestCodeIssues(data.code_issues || []);
      setTestStatus(data.status);
      setTestMessage(data.message || '');
      setTestErrorsFound(data.errors_found || 0);
      setTestScreenshotsSaved(data.screenshots_saved || 0);
    } catch (e: any) {
      setTestStatus('failed');
      setTestMessage('测试失败: ' + e.message);
    } finally {
      setIsTestRunning(false);
    }
  };

  const handleCodeFix = async (issueIndex: number, confirmed: boolean) => {
    if (!testTaskId) return;
    try {
      const res = await apiFetch('/test/code/fix', {
        method: 'POST',
        body: JSON.stringify({
          task_id: testTaskId,
          issue_index: issueIndex,
          confirmed,
        }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
      const data = await res.json();

      if (confirmed) {
        setTestMessage(`代码已自动修复: ${data.fix_result?.message || ''}`);
      } else {
        setTestMessage(`修复建议: ${data.fix_result?.fix_description || data.fix_result?.message || ''}`);
      }

      // Update the issue with fix result
      setTestCodeIssues(prev => prev.map((issue, idx) =>
        idx === issueIndex ? { ...issue, fix_result: data.fix_result } : issue
      ));
    } catch (e: any) {
      alert('修复失败: ' + e.message);
    }
  };

  // ==================== Knowledge Page ====================
  if (showKnowledge) {
    return (
      <div className="h-screen flex bg-gradient-to-br from-slate-950 via-blue-950/30 to-slate-950">
        <aside className="w-64 bg-slate-900/80 backdrop-blur-xl border-r border-white/5 flex flex-col">
          <div className="p-5 border-b border-white/5">
            <div className="flex items-center gap-3">
              <button onClick={() => setShowKnowledge(false)} className="w-9 h-9 bg-gradient-to-br from-blue-500 to-blue-700 rounded-lg flex items-center justify-center hover:opacity-80 transition-opacity">
                <Bug className="w-5 h-5 text-white" />
              </button>
              <div>
                <h1 className="text-sm font-bold text-white">TestAssistant AI</h1>
                <p className="text-[10px] text-slate-500">高级测试助手</p>
              </div>
            </div>
          </div>
          <div className="mx-4 mt-4 p-3 bg-white/[0.03] rounded-lg border border-white/5 flex items-center gap-2">
            <div className="w-7 h-7 rounded-md bg-gradient-to-br from-emerald-500 to-emerald-700 flex items-center justify-center text-xs text-white font-bold">
              {user?.username?.[0]?.toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-xs text-white font-medium truncate">{user?.username}</div>
              <div className="text-[10px] text-slate-500">已登录</div>
            </div>
            <button onClick={logout} className="p-1 text-slate-500 hover:text-red-400 transition-colors">
              <LogOut className="w-3.5 h-3.5" />
            </button>
          </div>
          <nav className="flex-1 p-4">
            <button
              onClick={() => setShowKnowledge(false)}
              className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-sm text-slate-400 hover:bg-white/5 hover:text-white transition-all"
            >
              <MessageSquare className="w-4 h-4" />
              <span>对话</span>
            </button>
            <button
              className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-sm bg-gradient-to-r from-emerald-500 to-emerald-700 text-white shadow-lg shadow-emerald-500/20"
            >
              <BookOpen className="w-4 h-4" />
              <span>测试文档库</span>
            </button>
          </nav>
          <div className="p-4 border-t border-white/5 space-y-3">
            <button onClick={clearAllChat} className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-red-500/10 border border-red-500/20 rounded-lg text-xs text-red-400 hover:bg-red-500/20 transition-all">
              <Trash2 className="w-3.5 h-3.5" />
              清空对话
            </button>
            <div className="p-3 bg-white/[0.03] rounded-lg border border-white/5">
              <div className="text-[10px] text-slate-500 mb-1">测试文档数</div>
              <div className="text-lg font-bold text-emerald-400">{docCount}</div>
            </div>
          </div>
        </aside>

        <main className="flex-1 flex flex-col min-w-0">
          <header className="px-6 py-4 border-b border-white/5 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-white">测试文档管理</h2>
              <p className="text-xs text-slate-500 mt-0.5">共 {knowledgeList.length} 条测试文档</p>
            </div>
            <button
              onClick={() => { setShowAddKnowledge(true); setNewKnowledgeContent(''); }}
              className="px-4 py-2 bg-gradient-to-r from-emerald-500 to-emerald-700 text-white text-sm rounded-lg hover:opacity-90 transition-opacity flex items-center gap-2"
            >
              <Plus className="w-4 h-4" />
              添加测试文档
            </button>
          </header>
          <div className="flex-1 overflow-y-auto scrollbar-thin px-6 py-4 space-y-3">
            {showAddKnowledge && (
              <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
                <div className="bg-slate-800 border border-white/10 rounded-xl p-6 max-w-lg w-full mx-4">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-white font-semibold flex items-center gap-2">
                      <BookOpen className="w-4 h-4 text-emerald-400" />
                      添加测试文档
                    </h3>
                    <button onClick={() => { setShowAddKnowledge(false); setNewKnowledgeContent(''); }} className="p-1 text-slate-400 hover:text-white transition-colors">
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                  <textarea
                    value={newKnowledgeContent}
                    onChange={e => setNewKnowledgeContent(e.target.value)}
                    placeholder="请输入测试文档内容..."
                    rows={8}
                    className="w-full bg-slate-900/50 border border-white/10 rounded-lg px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-emerald-500/50 resize-none mb-4"
                    autoFocus
                  />
                  <div className="flex gap-3 justify-end">
                    <button
                      onClick={() => { setShowAddKnowledge(false); setNewKnowledgeContent(''); }}
                      className="px-4 py-2 bg-slate-700 text-white text-sm rounded-lg hover:bg-slate-600 transition-colors"
                      disabled={isAddingKnowledge}
                    >
                      取消
                    </button>
                    <button
                      onClick={handleAddKnowledge}
                      disabled={!newKnowledgeContent.trim() || isAddingKnowledge}
                      className="px-4 py-2 bg-gradient-to-r from-emerald-500 to-emerald-700 text-white text-sm rounded-lg hover:opacity-90 transition-opacity disabled:opacity-30 disabled:cursor-not-allowed flex items-center gap-2"
                    >
                      {isAddingKnowledge ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                      添加
                    </button>
                  </div>
                </div>
              </div>
            )}

            {knowledgeList.length === 0 ? (
              <div className="flex-1 flex flex-col items-center justify-center text-center py-20">
                <div className="w-16 h-16 bg-gradient-to-br from-emerald-500/20 to-blue-500/20 rounded-2xl flex items-center justify-center mb-4">
                  <BookOpen className="w-7 h-7 text-emerald-400" />
                </div>
                <h3 className="text-base font-semibold text-white mb-2">测试文档库为空</h3>
                <p className="text-xs text-slate-500 max-w-xs">点击右上角"添加测试文档"按钮，即可添加测试文档</p>
              </div>
            ) : (
              <>
                {deletingDocId && (
                  <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
                    <div className="bg-slate-800 border border-white/10 rounded-xl p-6 max-w-sm w-full mx-4">
                      <h3 className="text-white font-semibold mb-2">确认删除</h3>
                      <p className="text-sm text-slate-400 mb-6">删除后无法恢复，确定要删除这条测试文档吗？</p>
                      <div className="flex gap-3 justify-end">
                        <button onClick={cancelDelete} className="px-4 py-2 bg-slate-700 text-white text-sm rounded-lg hover:bg-slate-600 transition-colors">取消</button>
                        <button onClick={confirmDelete} className="px-4 py-2 bg-red-500 text-white text-sm rounded-lg hover:bg-red-600 transition-colors">确认删除</button>
                      </div>
                    </div>
                  </div>
                )}

                {knowledgeList.map((doc, idx) => (
                  <div key={doc.doc_id} className="bg-slate-800/60 border border-white/5 rounded-xl overflow-hidden">
                    <div className="flex items-start justify-between px-4 py-3 border-b border-white/5">
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-slate-500 font-mono">#{idx + 1}</span>
                        <span className="text-[10px] text-slate-600 font-mono">{doc.doc_id}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        {editingDoc === doc.doc_id ? (
                          <>
                            <button onClick={() => saveEdit(doc.doc_id)} className="p-1.5 text-emerald-400 hover:bg-emerald-500/20 rounded transition-colors" title="保存"><Save className="w-3.5 h-3.5" /></button>
                            <button onClick={cancelEdit} className="p-1.5 text-slate-400 hover:bg-white/10 rounded transition-colors" title="取消"><X className="w-3.5 h-3.5" /></button>
                          </>
                        ) : (
                          <>
                            <button onClick={() => startEdit(doc)} className="p-1.5 text-blue-400 hover:bg-blue-500/20 rounded transition-colors" title="编辑"><Pencil className="w-3.5 h-3.5" /></button>
                            <button onClick={() => handleDeleteKnowledge(doc.doc_id)} className="p-1.5 text-red-400 hover:bg-red-500/20 rounded transition-colors" title="删除"><Trash2 className="w-3.5 h-3.5" /></button>
                          </>
                        )}
                      </div>
                    </div>
                    <div className="px-4 py-3">
                      {editingDoc === doc.doc_id ? (
                        <textarea value={editContent} onChange={e => setEditContent(e.target.value)} className="w-full bg-slate-900/50 border border-white/10 rounded-lg px-3 py-2 text-sm text-white outline-none focus:border-blue-500/50 resize-none min-h-[80px]" autoFocus />
                      ) : (
                        <p className="text-sm text-slate-300 whitespace-pre-wrap">{doc.content}</p>
                      )}
                    </div>
                  </div>
                ))}
              </>
            )}
          </div>
        </main>
      </div>
    );
  }

  // ==================== Workspace View ====================
  if (showWorkspace) {
    return <TestWorkspace onBack={() => setShowWorkspace(false)} />;
  }

  // ==================== Chat Page ====================
  return (
    <div className="h-screen flex bg-gradient-to-br from-slate-950 via-blue-950/30 to-slate-950">
      {/* Sidebar */}
      <aside className="w-64 bg-slate-900/80 backdrop-blur-xl border-r border-white/5 flex flex-col">
        <div className="p-5 border-b border-white/5">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 bg-gradient-to-br from-blue-500 to-blue-700 rounded-lg flex items-center justify-center">
              <Bug className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-sm font-bold text-white">TestAssistant AI</h1>
              <p className="text-[10px] text-slate-500">高级测试助手</p>
            </div>
          </div>
        </div>

        <div className="mx-4 mt-4 p-3 bg-white/[0.03] rounded-lg border border-white/5 flex items-center gap-2">
          <div className="w-7 h-7 rounded-md bg-gradient-to-br from-emerald-500 to-emerald-700 flex items-center justify-center text-xs text-white font-bold">
            {user?.username?.[0]?.toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-xs text-white font-medium truncate">{user?.username}</div>
            <div className="text-[10px] text-slate-500">已登录</div>
          </div>
          <button onClick={logout} className="p-1 text-slate-500 hover:text-red-400 transition-colors">
            <LogOut className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Session list */}
        <div className="flex-1 overflow-y-auto scrollbar-thin p-4">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-2 px-2">会话列表</div>
          <button
            onClick={createNewSession}
            className="w-full flex items-center gap-2 px-3 py-2 mb-2 rounded-lg text-sm text-blue-400 border border-blue-500/20 bg-blue-500/10 hover:bg-blue-500/20 transition-all"
          >
            <Plus className="w-4 h-4" />
            <span>新建会话</span>
          </button>
          <div className="space-y-1">
            {sessions.map(s => (
              <div
                key={s.session_id}
                onClick={() => {
                  if (editingSessionId !== s.session_id) {
                    setCurrentSessionId(s.session_id);
                  }
                }}
                className={`group flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm cursor-pointer transition-all ${
                  currentSessionId === s.session_id
                    ? 'bg-white/10 text-white'
                    : 'text-slate-400 hover:bg-white/5 hover:text-white'
                }`}
              >
                <MessageSquare className="w-3.5 h-3.5 flex-shrink-0" />
                {editingSessionId === s.session_id ? (
                  <div className="flex-1 flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="text"
                      autoFocus
                      maxLength={20}
                      value={editingName}
                      onChange={(e) => setEditingName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && editingName.trim()) {
                          saveSessionName(s.session_id, editingName.trim());
                        } else if (e.key === 'Escape') {
                          setEditingSessionId(null);
                          setEditingName('');
                        }
                      }}
                      onBlur={() => {
                        if (editingName.trim()) {
                          saveSessionName(s.session_id, editingName.trim());
                        } else {
                          setEditingSessionId(null);
                          setEditingName('');
                        }
                      }}
                      className="flex-1 bg-slate-700 border border-white/10 rounded px-1.5 py-0.5 text-xs text-white outline-none"
                    />
                  </div>
                ) : (
                  <>
                    <span className="flex-1 truncate">{s.name}</span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setEditingSessionId(s.session_id);
                        setEditingName(s.name);
                      }}
                      className="p-1 text-slate-500 hover:text-blue-400 transition-all flex-shrink-0"
                      title="重命名"
                    >
                      <Pencil className="w-3 h-3" />
                    </button>
                  </>
                )}
                <button
                  onClick={(e) => { e.stopPropagation(); setDeletingSessionId(s.session_id); }}
                  className="opacity-0 group-hover:opacity-100 p-1 text-slate-500 hover:text-red-400 transition-all"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="p-4 border-t border-white/5 space-y-2">
          <button
            onClick={() => setShowWorkspace(true)}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-sm text-emerald-400 hover:bg-emerald-500/10 hover:text-emerald-300 transition-all border border-emerald-500/20"
          >
            <Bug className="w-4 h-4" />
            <span>测试工作台</span>
          </button>
          <button
            onClick={() => setShowFilePanel(true)}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-sm text-slate-400 hover:bg-white/5 hover:text-white transition-all"
          >
            <FileUp className="w-4 h-4" />
            <span>文件管理</span>
            <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded-full bg-white/5 text-slate-500">{fileList.length}</span>
          </button>
          <button
            onClick={() => setShowKnowledge(true)}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-sm text-slate-400 hover:bg-white/5 hover:text-white transition-all"
          >
            <BookOpen className="w-4 h-4" />
            <span>测试文档管理</span>
            <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded-full bg-white/5 text-slate-500">{docCount}</span>
          </button>
          <button onClick={() => setShowClearChatConfirm(true)} className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-red-500/10 border border-red-500/20 rounded-lg text-xs text-red-400 hover:bg-red-500/20 transition-all">
            <Trash2 className="w-3.5 h-3.5" />
            清空当前会话
          </button>
        </div>
      </aside>

      {/* Delete session confirmation modal */}
      {deletingSessionId && (
        <div className="fixed inset-0 z-[9999] bg-black/50 backdrop-blur-sm flex items-center justify-center">
          <div className="bg-slate-800 border border-white/10 rounded-xl p-6 max-w-sm w-full mx-4 shadow-2xl">
            <h3 className="text-white font-semibold mb-2">确认删除会话</h3>
            <p className="text-sm text-slate-400 mb-6">删除后该会话的所有对话记录将无法恢复</p>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setDeletingSessionId(null)} className="px-4 py-2 bg-slate-700 text-white text-sm rounded-lg hover:bg-slate-600 transition-colors">取消</button>
              <button onClick={() => deleteSession(deletingSessionId)} className="px-4 py-2 bg-red-500 text-white text-sm rounded-lg hover:bg-red-600 transition-colors">确认删除</button>
            </div>
          </div>
        </div>
      )}

      {/* Clear chat confirmation modal */}
      {showClearChatConfirm && (
        <div className="fixed inset-0 z-[9999] bg-black/50 backdrop-blur-sm flex items-center justify-center">
          <div className="bg-slate-800 border border-white/10 rounded-xl p-6 max-w-sm w-full mx-4 shadow-2xl">
            <h3 className="text-white font-semibold mb-2">清空对话记录</h3>
            <p className="text-sm text-slate-400 mb-6">确定要清空当前会话的所有对话记录吗？此操作无法恢复。</p>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setShowClearChatConfirm(false)} className="px-4 py-2 bg-slate-700 text-white text-sm rounded-lg hover:bg-slate-600 transition-colors">取消</button>
              <button onClick={clearAllChat} className="px-4 py-2 bg-red-500 text-white text-sm rounded-lg hover:bg-red-600 transition-colors">确认清空</button>
            </div>
          </div>
        </div>
      )}

      {/* Main area */}
      <main className="flex-1 flex flex-col min-w-0">
        <header className="px-6 py-4 border-b border-white/5 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-white flex items-center gap-2">
              <Zap className="w-4 h-4 text-amber-400" />
              {currentSessionId ? sessions.find(s => s.session_id === currentSessionId)?.name || '统一对话' : '统一对话'}
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">智能识别意图，自动路由到对应功能</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-slate-500">{totalCount} 条对话</span>
          </div>
        </header>

        {/* Content area */}
        <div className="flex-1 overflow-y-auto scrollbar-thin px-6 py-4 space-y-4">
          {messages.length === 0 ? (
            <div className="flex-1 flex flex-col items-center justify-center text-center py-20">
              <div className="w-16 h-16 bg-gradient-to-br from-blue-500/20 to-emerald-500/20 rounded-2xl flex items-center justify-center mb-4">
                <Sparkles className="w-7 h-7 text-blue-400" />
              </div>
              <h3 className="text-base font-semibold text-white mb-2">
                {currentSessionId ? '开始对话' : '选择或新建会话'}
              </h3>
              <p className="text-xs text-slate-500 max-w-xs mb-6">
                {currentSessionId
                  ? '输入任意内容，系统自动识别您的意图并处理'
                  : '请先选择或新建一个会话来开始对话'
                }
              </p>
              {currentSessionId && (
                <div className="grid grid-cols-2 gap-2 w-full max-w-sm">
                  {EXAMPLES.map((ex, i) => (
                    <button
                      key={i}
                      onClick={() => setInputText(ex.text)}
                      className="p-3 bg-slate-800/50 border border-white/5 rounded-lg text-xs text-slate-300 hover:border-blue-500/30 hover:bg-blue-500/10 transition-all text-left"
                    >
                      <div className="flex items-center gap-1.5 font-medium text-white mb-1">
                        {ex.icon}
                        {ex.label}
                      </div>
                      <div className="text-[10px] text-slate-500 truncate">{ex.text}</div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            messages.map((msg, i) => {
              const date = new Date(msg.time).toLocaleDateString('zh-CN');
              const prevDate = i > 0 ? new Date(messages[i - 1].time).toLocaleDateString('zh-CN') : '';
              const intentCfg = msg.intent ? INTENT_CONFIG[msg.intent] || INTENT_CONFIG.chat : null;

              return (
                <div key={msg.id} className="space-y-4">
                  {date !== prevDate && (
                    <div className="flex items-center gap-4">
                      <div className="flex-1 h-px bg-white/10" />
                      <span className="text-[10px] text-slate-600">{date}</span>
                      <div className="flex-1 h-px bg-white/10" />
                    </div>
                  )}
                  {/* User message */}
                  <div className="flex justify-end animate-slide-up">
                    <div className="max-w-[70%] px-4 py-3 bg-gradient-to-r from-blue-500 to-blue-700 rounded-2xl rounded-tr-sm text-sm text-white whitespace-pre-wrap break-words">
                      {msg.input}
                    </div>
                  </div>
                  {/* Bot response */}
                  <div className="flex gap-3 animate-slide-up">
                    <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center flex-shrink-0 mt-0.5">
                      <Bug className="w-4 h-4 text-white" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="space-y-2">
                        {/* Intent tag */}
                        {intentCfg && (
                          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] border ${intentCfg.color}`}>
                            {intentCfg.icon}
                            {intentCfg.label}
                          </span>
                        )}
                        {/* Response card */}
                        <div className="bg-slate-800/60 border border-white/5 rounded-2xl rounded-tl-sm px-4 py-3">
                          {!msg.output ? (
                            <div className="flex items-center gap-2 text-slate-400">
                              <Loader2 className="w-4 h-4 animate-spin" />
                              <span className="text-sm">AI 思考中...</span>
                            </div>
                          ) : msg.output.error ? (
                            <div className="text-red-400 text-sm">❌ {msg.output.error}</div>
                          ) : msg.output.intent === 'chat' ? (
                            <div className="space-y-3">
                              {msg.output.data?.answer != null ? (
                                <>
                                  <div className="text-sm text-slate-300 whitespace-pre-wrap leading-relaxed">{msg.output.data.answer}</div>
                                  {msg.output.data.has_knowledge && msg.output.data.references && msg.output.data.references.length > 0 && (
                                    <div className="pt-3 border-t border-white/5">
                                      <div className="text-[10px] text-emerald-400 font-semibold mb-1 flex items-center gap-1">
                                        <BookOpen className="w-3 h-3" /> 参考测试文档
                                      </div>
                                      {msg.output.data.references.map((ref: string, idx: number) => (
                                        <span key={idx} className="inline-block mr-2 mt-1 px-1.5 py-0.5 bg-emerald-500/10 border border-emerald-500/20 rounded text-[10px] text-emerald-400">
                                          {ref}
                                        </span>
                                      ))}
                                    </div>
                                  )}
                                  {!msg.output.data.has_knowledge && (
                                    <div className="pt-3 border-t border-white/5">
                                      <span className="text-[10px] text-amber-400">提示：测试文档库为空，当前基于AI通用知识回答</span>
                                    </div>
                                  )}
                                </>
                              ) : (
                                <div className="text-sm text-slate-300">{msg.output.message || '暂无回答'}</div>
                              )}
                            </div>
                          ) : msg.output.module === 'code' ? (
                            <div className="space-y-2">
                              <div className="flex items-center gap-2 text-xs font-semibold text-slate-300">
                                <Code className="w-3.5 h-3.5" /> 代码分析结果
                              </div>
                              <div className="text-sm text-slate-300 whitespace-pre-wrap">{msg.output.data?.analysis || msg.output.message || '暂无分析结果'}</div>
                            </div>
                          ) : msg.output.module === 'case' ? (
                            <div className="space-y-2">
                              <div className="flex items-center gap-2 text-xs font-semibold text-slate-300">
                                <TestTube className="w-3.5 h-3.5" /> 测试用例
                              </div>
                              <div className="text-sm text-slate-300 whitespace-pre-wrap">{msg.output.data?.cases || msg.output.message || '暂无用例生成结果'}</div>
                            </div>
                          ) : msg.output.module === 'complaint' ? (
                            <div className="space-y-2">
                              <div className="flex items-center gap-2 text-xs font-semibold text-slate-300">
                                <AlertCircle className="w-3.5 h-3.5" /> Bug分析结果
                              </div>
                              <div className="space-y-1.5">
                                <div className="flex items-center justify-between">
                                  <span className="text-xs text-slate-400">Bug类型</span>
                                  <div className="flex items-center gap-2">
                                    <span className="text-sm text-white font-medium">{msg.output.data?.bug_type}</span>
                                    <ConfidenceBadge value={msg.output.data?.category_confidence || 0} />
                                  </div>
                                </div>
                                <div className="flex items-center justify-between">
                                  <span className="text-xs text-slate-400">严重程度</span>
                                  <div className="flex items-center gap-2">
                                    <span className="text-sm text-white font-medium">{msg.output.data?.severity || '待评估'}</span>
                                    <ConfidenceBadge value={msg.output.data?.reason_primary_confidence || 0} />
                                  </div>
                                </div>
                                <div className="flex items-center justify-between">
                                  <span className="text-xs text-slate-400">影响范围</span>
                                  <div className="flex items-center gap-2">
                                    <span className="text-sm text-white font-medium">{msg.output.data?.scope || '待评估'}</span>
                                    <ConfidenceBadge value={msg.output.data?.reason_secondary_confidence || 0} />
                                  </div>
                                </div>
                              </div>
                            </div>
                          ) : msg.output.module === 'knowledge' ? (
                            <div className="flex items-center gap-2">
                              <span className="text-xs text-emerald-400 font-semibold">✅ 测试文档添加成功</span>
                              <span className="text-[10px] text-slate-500 font-mono">{msg.output.data?.doc_id}</span>
                            </div>
                          ) : (
                            <pre className="text-[10px] text-slate-400 whitespace-pre-wrap">{JSON.stringify(msg.output, null, 2)}</pre>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })
          )}
          {/* Typing indicator */}
          {isProcessing && (
            <div className="flex gap-3 animate-slide-up">
              <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center flex-shrink-0">
                <Loader2 className="w-4 h-4 text-white animate-spin" />
              </div>
              <div className="space-y-2">
                <div className="bg-slate-800/60 border border-white/5 rounded-2xl rounded-tl-sm px-4 py-3 flex items-center gap-1.5">
                  <div className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <div className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <div className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
                <span className="text-[10px] text-slate-500">正在分析意图...</span>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input area */}
        <div className="px-6 py-4 border-t border-white/5 bg-slate-900/50">
          <div className="flex gap-3 items-end">
            <textarea
              ref={textareaRef}
              value={inputText}
              onChange={e => setInputText(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
              placeholder={currentSessionId ? "输入任意内容，AI自动识别意图..." : "请先选择或新建会话"}
              rows={1}
              className="flex-1 bg-slate-800/60 border border-white/10 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-500 outline-none focus:border-blue-500/50 resize-none transition-colors min-h-[48px] max-h-[120px] scrollbar-thin"
              disabled={isProcessing || !currentSessionId}
            />
            <button
              onClick={handleSend}
              disabled={isProcessing || !inputText.trim() || !currentSessionId}
              className="w-11 h-11 bg-gradient-to-r from-blue-500 to-blue-700 rounded-xl flex items-center justify-center text-white disabled:opacity-30 disabled:cursor-not-allowed hover:shadow-lg hover:shadow-blue-500/20 transition-all flex-shrink-0"
            >
              {isProcessing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </button>
          </div>
          <div className="mt-2 flex items-center gap-3">
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <div
                className={`w-8 h-5 rounded-full transition-colors relative ${useRag ? 'bg-blue-500' : 'bg-slate-700'}`}
                onClick={() => setUseRag(!useRag)}
              >
                <div className={`w-3.5 h-3.5 bg-white rounded-full absolute top-0.5 transition-all ${useRag ? 'left-4' : 'left-0.5'}`} />
              </div>
              <span className="text-[11px] text-slate-400">RAG 增强</span>
            </label>
            <button
              onClick={() => { setShowSettings(true); resetAddModal(); }}
              className="flex items-center gap-1.5 px-2 py-1 text-[11px] text-slate-400 hover:text-blue-400 transition-colors"
            >
              <Settings className="w-3.5 h-3.5" />
              <span>模型管理</span>
            </button>
          </div>
        </div>
      </main>

      {/* Model Management Modal */}
      {showSettings && (
        <div className="fixed inset-0 z-[9999] bg-black/50 backdrop-blur-sm flex items-center justify-center">
          <div className="bg-slate-800 border border-white/10 rounded-xl p-6 max-w-lg w-full mx-4 shadow-2xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-white font-semibold flex items-center gap-2">
                <Settings className="w-4 h-4 text-blue-400" />
                AI 模型管理
              </h3>
              <button onClick={() => { setShowSettings(false); setSettingsStatus({type: null, message: ''}); }} className="p-1 text-slate-400 hover:text-white transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Status message */}
            {settingsStatus.type && (
              <div className={`mb-4 px-3 py-2 rounded-lg text-xs ${settingsStatus.type === 'success' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20'}`}>
                {settingsStatus.message}
              </div>
            )}

            {/* Model list */}
            <div className="space-y-4 mb-6">
              {/* Builtin models group */}
              <div>
                <button
                  onClick={() => setExpandedGroups(prev => ({...prev, builtin: !prev.builtin}))}
                  className="w-full flex items-center justify-between px-2 py-1.5 text-xs text-slate-400 hover:text-white transition-colors"
                >
                  <span className="font-semibold">内置模型</span>
                  <span className="text-[10px]">{expandedGroups.builtin ? '收起' : '展开'}</span>
                </button>
                {expandedGroups.builtin && (
                  <div className="space-y-2 mt-2">
                    {builtinModels.length === 0 ? (
                      <div className="text-xs text-slate-500 px-2 py-4 text-center">尚未配置内置模型</div>
                    ) : (
                      builtinModels.map(m => (
                        <ModelItem
                          key={m.id}
                          model={m}
                          isActive={activeModelId === m.id}
                          onActivate={() => setActiveModel(m.id)}
                          onEdit={() => { setEditingModelId(m.id); setShowEditModal(true); }}
                          onDelete={() => deleteModel(m.id)}
                          onTest={() => testModelConnection('', m.api_base_url, m.model_name)}
                        />
                      ))
                    )}
                  </div>
                )}
              </div>

              {/* Custom models group */}
              <div>
                <button
                  onClick={() => setExpandedGroups(prev => ({...prev, custom: !prev.custom}))}
                  className="w-full flex items-center justify-between px-2 py-1.5 text-xs text-slate-400 hover:text-white transition-colors"
                >
                  <span className="font-semibold">自定义模型</span>
                  <span className="text-[10px]">{expandedGroups.custom ? '收起' : '展开'}</span>
                </button>
                {expandedGroups.custom && (
                  <div className="space-y-2 mt-2">
                    {customModels.length === 0 ? (
                      <div className="text-xs text-slate-500 px-2 py-4 text-center">尚未配置自定义模型</div>
                    ) : (
                      customModels.map(m => (
                        <ModelItem
                          key={m.id}
                          model={m}
                          isActive={activeModelId === m.id}
                          onActivate={() => setActiveModel(m.id)}
                          onEdit={() => { setEditingModelId(m.id); setShowEditModal(true); }}
                          onDelete={() => deleteModel(m.id)}
                          onTest={() => testModelConnection('', m.api_base_url, m.model_name)}
                        />
                      ))
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* Action buttons */}
            <div className="flex gap-2 justify-end border-t border-white/5 pt-4">
              {!activeModelId ? (
                <span className="text-xs text-slate-500 self-center">请选择一个模型开始使用</span>
              ) : (
                <button onClick={resetToDefault} className="px-3 py-2 bg-slate-700 text-white text-xs rounded-lg hover:bg-slate-600 transition-colors">
                  取消选择
                </button>
              )}
              <button
                onClick={() => { setShowAddModal(true); resetAddModal(); }}
                className="px-4 py-2 bg-gradient-to-r from-blue-500 to-blue-700 text-white text-xs rounded-lg hover:opacity-90 transition-opacity flex items-center gap-1.5"
              >
                <Plus className="w-3.5 h-3.5" />
                添加模型
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Model Modal */}
      {showAddModal && (
        <div className="fixed inset-0 z-[99999] bg-black/60 backdrop-blur-sm flex items-center justify-center">
          <div className="bg-slate-800 border border-white/10 rounded-xl p-6 max-w-md w-full mx-4 shadow-2xl">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-white font-semibold">添加模型</h3>
              <button onClick={() => { setShowAddModal(false); resetAddModal(); }} className="p-1 text-slate-400 hover:text-white transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Platform selection */}
            <div className="mb-4">
              <label className="text-xs text-slate-400 mb-2 block">选择平台</label>
              <div className="flex flex-wrap gap-2">
                {supportedPlatforms.map((p: any) => (
                  <button
                    key={p.key}
                    onClick={() => handlePlatformChange(p.key)}
                    className={`px-3 py-1.5 rounded-lg text-xs transition-all ${
                      addPlatform === p.key
                        ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                        : 'bg-white/5 text-slate-400 border border-white/10 hover:border-white/20'
                    }`}
                  >
                    {p.name}
                  </button>
                ))}
              </div>
            </div>

            {/* API Key */}
            <div className="mb-4">
              <label className="text-xs text-slate-400 mb-2 block">API Key</label>
              <div className="relative">
                <input
                  type={showAddApiKey ? 'text' : 'password'}
                  value={addApiKey}
                  onChange={e => setAddApiKey(e.target.value)}
                  placeholder="输入你的 API Key"
                  className="w-full bg-slate-900/50 border border-white/10 rounded-lg pl-4 pr-16 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:border-blue-500/50"
                />
                <button
                  onClick={() => setShowAddApiKey(!showAddApiKey)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-slate-500 hover:text-blue-400 transition-colors"
                >
                  {showAddApiKey ? '隐藏' : '显示'}
                </button>
              </div>
            </div>

            {/* API Base URL */}
            <div className="mb-4">
              <label className="text-xs text-slate-400 mb-2 block">API 地址</label>
              <input
                type="text"
                value={addBaseUrl}
                onChange={e => setAddBaseUrl(e.target.value)}
                placeholder="https://api.example.com/v1"
                className="w-full bg-slate-900/50 border border-white/10 rounded-lg px-4 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:border-blue-500/50"
              />
            </div>

            {/* Model Name */}
            <div className="mb-6">
              <label className="text-xs text-slate-400 mb-2 block">模型名称</label>
              <input
                type="text"
                value={addModelName}
                onChange={e => setAddModelName(e.target.value)}
                placeholder={addPlatform === 'custom' ? '输入模型名称' : '如 deepseek-chat'}
                className="w-full bg-slate-900/50 border border-white/10 rounded-lg px-4 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:border-blue-500/50"
              />
            </div>

            {/* Status */}
            {settingsStatus.type && (
              <div className={`mb-4 px-3 py-2 rounded-lg text-xs ${settingsStatus.type === 'success' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20'}`}>
                {settingsStatus.message}
              </div>
            )}

            {/* Action buttons */}
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => testModelConnection(addApiKey, addBaseUrl || supportedPlatforms.find((p: any) => p.key === addPlatform)?.default_base_url || '', addModelName)}
                disabled={isTestingModel}
                className="px-3 py-2 bg-amber-500/20 text-amber-400 text-xs rounded-lg hover:bg-amber-500/30 transition-colors disabled:opacity-50 flex items-center gap-1.5"
              >
                {isTestingModel ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
                测试连接
              </button>
              <button
                onClick={addModel}
                disabled={isSavingModel}
                className="px-4 py-2 bg-gradient-to-r from-blue-500 to-blue-700 text-white text-xs rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50 flex items-center gap-1.5"
              >
                {isSavingModel ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                保存
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Model Modal */}
      {showEditModal && (
        <EditModelModal
          modelId={editingModelId}
          onClose={() => { setShowEditModal(false); setEditingModelId(null); }}
          onSave={() => { setShowEditModal(false); setEditingModelId(null); loadModels(); }}
          onTest={testModelConnection}
          onDelete={deleteModel}
        />
      )}

      {/* File Management Panel (Right Side) */}
      {showFilePanel && (
        <div className="fixed inset-0 z-[9999] bg-black/30 backdrop-blur-sm flex justify-end">
          <div className="w-80 bg-slate-900/95 backdrop-blur-xl border-l border-white/10 flex flex-col h-full animate-slide-left">
            {/* Panel Header */}
            <div className="px-5 py-4 border-b border-white/5 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                  <FileUp className="w-4 h-4 text-blue-400" />
                  文件管理
                </h3>
                <p className="text-[10px] text-slate-500 mt-0.5">共 {fileList.length} 个文件</p>
              </div>
              <button onClick={() => setShowFilePanel(false)} className="p-1 text-slate-400 hover:text-white transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Upload Area */}
            <div className="px-4 py-3 border-b border-white/5">
              <input
                ref={filePanelInputRef}
                type="file"
                accept=".pdf,.txt"
                onChange={handleFilePanelSelect}
                className="hidden"
              />
              <button
                onClick={() => filePanelInputRef.current?.click()}
                disabled={isUploadingFilePanel}
                className="w-full flex items-center justify-center gap-2 px-3 py-2.5 bg-gradient-to-r from-blue-500 to-blue-700 text-white text-sm rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
              >
                {isUploadingFilePanel ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileUp className="w-4 h-4" />}
                {isUploadingFilePanel ? '上传中...' : '上传文件'}
              </button>
              <p className="text-[10px] text-slate-500 mt-2 text-center">支持 PDF、TXT 格式</p>
            </div>

            {/* File List */}
            <div className="flex-1 overflow-y-auto scrollbar-thin px-4 py-3 space-y-2">
              {fileList.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <div className="w-12 h-12 bg-white/[0.03] rounded-xl flex items-center justify-center mb-3">
                    <FileUp className="w-5 h-5 text-slate-600" />
                  </div>
                  <p className="text-xs text-slate-500">暂无文件</p>
                  <p className="text-[10px] text-slate-600 mt-1">点击上方按钮上传文件</p>
                </div>
              ) : (
                fileList.map(file => (
                  <div
                    key={file.id}
                    className={`bg-white/[0.03] border rounded-lg overflow-hidden transition-all ${
                      selectedFileId === file.id ? 'border-blue-500/30 bg-blue-500/5' : 'border-white/5 hover:border-white/10'
                    }`}
                  >
                    {/* File Info */}
                    <div className="px-3 py-2.5">
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <div className="text-xs text-white font-medium truncate">{file.original_filename}</div>
                          <div className="flex items-center gap-2 mt-1">
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 uppercase">{file.file_type}</span>
                            <span className="text-[10px] text-slate-500">{(file.file_size / 1024).toFixed(1)} KB</span>
                          </div>
                          {file.extracted_text_preview && (
                            <p className="text-[10px] text-slate-500 mt-1.5 line-clamp-2">{file.extracted_text_preview}</p>
                          )}
                        </div>
                        <button
                          onClick={(e) => { e.stopPropagation(); setDeletingFileId(file.id); }}
                          className="p-1 text-slate-500 hover:text-red-400 transition-colors flex-shrink-0"
                          title="删除"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    </div>
                    {/* Action Button */}
                    <div className="px-3 py-2 border-t border-white/5">
                      <button
                        onClick={() => {
                          setSelectedFileId(file.id);
                          sendChatWithFile(file.id);
                          setShowFilePanel(false);
                        }}
                        disabled={isProcessing}
                        className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 bg-blue-500/10 border border-blue-500/20 rounded text-[10px] text-blue-400 hover:bg-blue-500/20 transition-colors disabled:opacity-50"
                      >
                        <Sparkles className="w-3 h-3" />
                        让 AI 读取此文件
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* File Delete Confirmation */}
      {deletingFileId !== null && (
        <div className="fixed inset-0 z-[99999] bg-black/50 backdrop-blur-sm flex items-center justify-center">
          <div className="bg-slate-800 border border-white/10 rounded-xl p-6 max-w-sm w-full mx-4 shadow-2xl">
            <h3 className="text-white font-semibold mb-2">确认删除文件</h3>
            <p className="text-sm text-slate-400 mb-6">删除后无法恢复，确定要删除这个文件吗？</p>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setDeletingFileId(null)} className="px-4 py-2 bg-slate-700 text-white text-sm rounded-lg hover:bg-slate-600 transition-colors">取消</button>
              <button onClick={() => deleteFile(deletingFileId)} className="px-4 py-2 bg-red-500 text-white text-sm rounded-lg hover:bg-red-600 transition-colors">确认删除</button>
            </div>
          </div>
        </div>
      )}

      {/* File Upload Confirmation */}
      {confirmUploadFile !== null && (
        <div className="fixed inset-0 z-[99999] bg-black/50 backdrop-blur-sm flex items-center justify-center">
          <div className="bg-slate-800 border border-white/10 rounded-xl p-6 max-w-sm w-full mx-4 shadow-2xl">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-lg bg-blue-500/20 flex items-center justify-center">
                <FileUp className="w-5 h-5 text-blue-400" />
              </div>
              <div>
                <h3 className="text-white font-semibold">确认上传文件</h3>
                <p className="text-[10px] text-slate-500 mt-0.5">文件将被解析并存储</p>
              </div>
            </div>
            <div className="bg-slate-900/50 rounded-lg px-4 py-3 mb-6">
              <div className="text-xs text-white font-medium">{confirmUploadFile.name}</div>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 uppercase">{confirmUploadFile.name.split('.').pop()}</span>
                <span className="text-[10px] text-slate-500">{(confirmUploadFile.size / 1024).toFixed(1)} KB</span>
              </div>
            </div>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => { setConfirmUploadFile(null); if (filePanelInputRef.current) filePanelInputRef.current.value = ''; }}
                className="px-4 py-2 bg-slate-700 text-white text-sm rounded-lg hover:bg-slate-600 transition-colors"
              >
                取消
              </button>
              <button
                onClick={() => {
                  if (pendingFileRef.current) {
                    handleFilePanelUpload(pendingFileRef.current);
                  }
                  setConfirmUploadFile(null);
                  pendingFileRef.current = null;
                }}
                className="px-4 py-2 bg-gradient-to-r from-blue-500 to-blue-700 text-white text-sm rounded-lg hover:opacity-90 transition-opacity flex items-center gap-2"
              >
                <FileUp className="w-3.5 h-3.5" />
                确认上传
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Web Test Agent Panel (Right Side) */}
      {showTestPanel && (
        <div className="fixed inset-0 z-[9999] bg-black/30 backdrop-blur-sm flex justify-end">
          <div className="w-[480px] bg-slate-900/95 backdrop-blur-xl border-l border-white/10 flex flex-col h-full animate-slide-left">
            {/* Panel Header */}
            <div className="px-5 py-4 border-b border-white/5 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                  <Bug className="w-4 h-4 text-emerald-400" />
                  Web 测试 Agent
                </h3>
                <p className="text-[10px] text-slate-500 mt-0.5">AI自动测试网页 + 定位修复代码Bug</p>
              </div>
              <button onClick={() => setShowTestPanel(false)} className="p-1 text-slate-400 hover:text-white transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Config Area */}
            <div className="px-4 py-3 border-b border-white/5 space-y-3">
              {/* Target URL */}
              <div>
                <label className="text-[10px] text-slate-500 mb-1 block flex items-center gap-1">
                  <Globe className="w-3 h-3" /> 目标测试网址
                </label>
                <input
                  type="text"
                  value={testTargetUrl}
                  onChange={e => setTestTargetUrl(e.target.value)}
                  placeholder="https://example.com"
                  className="w-full bg-slate-800/60 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 outline-none focus:border-emerald-500/50"
                  disabled={isTestRunning}
                />
              </div>

              {/* Project Path */}
              <div>
                <label className="text-[10px] text-slate-500 mb-1 block flex items-center gap-1">
                  <FolderOpen className="w-3 h-3" /> 项目代码路径
                </label>
                <input
                  type="text"
                  value={testProjectPath}
                  onChange={e => setTestProjectPath(e.target.value)}
                  placeholder="C:\Users\yourname\project"
                  className="w-full bg-slate-800/60 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 outline-none focus:border-emerald-500/50"
                  disabled={isTestRunning}
                />
              </div>

              {/* Test Goals */}
              <div>
                <label className="text-[10px] text-slate-500 mb-1 block flex items-center gap-1">
                  <ClipboardList className="w-3 h-3" /> 测试目标 (每行一个)
                </label>
                <textarea
                  value={testGoals}
                  onChange={e => setTestGoals(e.target.value)}
                  placeholder={"测试登录功能\n测试搜索框\n测试表单提交"}
                  rows={3}
                  className="w-full bg-slate-800/60 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 outline-none focus:border-emerald-500/50 resize-none"
                  disabled={isTestRunning}
                />
              </div>

              {/* Run Button */}
              <button
                onClick={handleTestRun}
                disabled={isTestRunning || !testTargetUrl.trim() || !testProjectPath.trim() || !testGoals.trim()}
                className="w-full flex items-center justify-center gap-2 px-3 py-2.5 bg-gradient-to-r from-emerald-500 to-emerald-700 text-white text-sm rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
              >
                {isTestRunning ? <Loader2 className="w-4 h-4 animate-spin" /> : <Bug className="w-4 h-4" />}
                {isTestRunning ? '测试执行中...' : '开始测试'}
              </button>
            </div>

            {/* Results Area */}
            <div className="flex-1 overflow-y-auto scrollbar-thin px-4 py-3 space-y-3">
              {/* Empty State */}
              {testStatus === '' && testSteps.length === 0 && (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <div className="w-12 h-12 bg-emerald-500/10 rounded-xl flex items-center justify-center mb-3">
                    <Bug className="w-5 h-5 text-emerald-400" />
                  </div>
                  <p className="text-xs text-slate-500">暂无测试任务</p>
                  <p className="text-[10px] text-slate-600 mt-1">配置测试参数后开始自动化测试</p>
                </div>
              )}

              {/* Running Status */}
              {testStatus === 'running' && (
                <div className="flex items-center gap-2 p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-lg">
                  <Loader2 className="w-4 h-4 text-emerald-400 animate-spin" />
                  <span className="text-xs text-emerald-400">Web测试Agent正在执行...</span>
                </div>
              )}

              {/* Completed/Failed Status */}
              {(testStatus === 'completed' || testStatus === 'failed') && (
                <div className={`flex items-center gap-2 p-3 rounded-lg ${
                  testStatus === 'completed'
                    ? 'bg-emerald-500/10 border border-emerald-500/20'
                    : 'bg-red-500/10 border border-red-500/20'
                }`}>
                  {testStatus === 'completed'
                    ? <CheckCircle className="w-4 h-4 text-emerald-400" />
                    : <AlertCircle className="w-4 h-4 text-red-400" />
                  }
                  <span className="text-xs text-white">{testMessage}</span>
                </div>
              )}

              {/* Stats */}
              {testSteps.length > 0 && (
                <div className="grid grid-cols-3 gap-2">
                  <div className="bg-white/[0.03] border border-white/5 rounded-lg p-2 text-center">
                    <div className="text-lg font-bold text-white">{testSteps.length}</div>
                    <div className="text-[10px] text-slate-500">执行步骤</div>
                  </div>
                  <div className="bg-white/[0.03] border border-white/5 rounded-lg p-2 text-center">
                    <div className={`text-lg font-bold ${testErrorsFound > 0 ? 'text-red-400' : 'text-emerald-400'}`}>{testErrorsFound}</div>
                    <div className="text-[10px] text-slate-500">发现错误</div>
                  </div>
                  <div className="bg-white/[0.03] border border-white/5 rounded-lg p-2 text-center">
                    <div className="text-lg font-bold text-blue-400">{testScreenshotsSaved}</div>
                    <div className="text-[10px] text-slate-500">截图保存</div>
                  </div>
                </div>
              )}

              {/* Steps List */}
              {testSteps.map((step, idx) => (
                <div key={idx} className="bg-white/[0.03] border border-white/5 rounded-lg overflow-hidden">
                  {/* Step Header */}
                  <div className="flex items-center gap-2 px-3 py-2 border-b border-white/5">
                    <span className="text-[10px] text-slate-500 font-mono">#{step.step}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                      step.action === 'click' ? 'bg-blue-500/20 text-blue-400' :
                      step.action === 'fill' ? 'bg-emerald-500/20 text-emerald-400' :
                      step.action === 'navigate' ? 'bg-purple-500/20 text-purple-400' :
                      step.action === 'wait' ? 'bg-amber-500/20 text-amber-400' :
                      step.action === 'done' ? 'bg-cyan-500/20 text-cyan-400' :
                      'bg-slate-500/20 text-slate-400'
                    }`}>
                      {step.action}
                    </span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                      step.success ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
                    }`}>
                      {step.success ? '✅' : '❌'}
                    </span>
                    <span className="text-xs text-slate-300 flex-1 truncate">{step.target}</span>
                  </div>

                  {/* Screenshot */}
                  {step.screenshot && (
                    <div className="px-3 py-2">
                      <img
                        src={step.screenshot}
                        alt={`步骤 ${step.step} 截图`}
                        className="w-full rounded border border-white/5"
                        style={{ maxHeight: '150px', objectFit: 'contain' }}
                      />
                    </div>
                  )}

                  {/* Console/Network Errors */}
                  {(step.console_errors?.length > 0 || step.network_errors?.length > 0) && (
                    <div className="px-3 py-2 border-t border-white/5 space-y-1 max-h-40 overflow-y-auto scrollbar-thin">
                      {step.console_errors?.slice(0, 10).map((err: string, i: number) => (
                        <div key={i} className="text-[10px] text-red-400 font-mono whitespace-pre-wrap break-all">Console: {err}</div>
                      ))}
                      {step.network_errors?.slice(0, 10).map((err: string, i: number) => (
                        <div key={i} className="text-[10px] text-orange-400 font-mono whitespace-pre-wrap break-all">Network: {err}</div>
                      ))}
                    </div>
                  )}

                  {/* Result */}
                  {step.result && (
                    <div className="px-3 py-2 border-t border-white/5">
                      <span className="text-[10px] text-slate-400">{step.result}</span>
                    </div>
                  )}
                </div>
              ))}

              {/* Code Issues */}
              {testCodeIssues.length > 0 && (
                <div className="pt-2">
                  <div className="flex items-center gap-2 mb-2">
                    <Bug className="w-3.5 h-3.5 text-red-400" />
                    <span className="text-xs text-white font-semibold">代码问题定位 ({testCodeIssues.length})</span>
                  </div>
                  {testCodeIssues.map((issue, idx) => (
                    <div key={idx} className="bg-red-500/5 border border-red-500/20 rounded-lg p-3 mb-2">
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <div className="text-xs text-red-400 font-mono truncate">
                            {issue.file_path}:{issue.line_number}
                          </div>
                          <div className="text-xs text-white mt-1">{issue.issue_description}</div>
                          <div className="text-[10px] text-slate-500 mt-1 font-mono whitespace-pre-wrap max-h-20 overflow-y-auto">
                            {issue.suggested_fix}
                          </div>
                        </div>
                      </div>
                      {/* Fix Actions */}
                      {!issue.fix_result && (
                        <div className="flex gap-2 mt-3 pt-2 border-t border-white/5">
                          <button
                            onClick={() => handleCodeFix(idx, true)}
                            className="flex-1 px-2 py-1.5 bg-emerald-500/20 text-emerald-400 text-[10px] rounded hover:bg-emerald-500/30 transition-colors flex items-center justify-center gap-1"
                          >
                            <CheckCircle className="w-3 h-3" /> 同意修改
                          </button>
                          <button
                            onClick={() => handleCodeFix(idx, false)}
                            className="flex-1 px-2 py-1.5 bg-amber-500/20 text-amber-400 text-[10px] rounded hover:bg-amber-500/30 transition-colors flex items-center justify-center gap-1"
                          >
                            <ClipboardList className="w-3 h-3" /> 仅看建议
                          </button>
                        </div>
                      )}
                      {/* Fix Result */}
                      {issue.fix_result && (
                        <div className={`mt-3 pt-2 border-t border-white/5 ${
                          issue.fix_result.success ? 'text-emerald-400' : 'text-red-400'
                        }`}>
                          <div className="text-[10px] font-medium">{issue.fix_result.message}</div>
                          {issue.fix_result.fixed_code && (
                            <pre className="text-[10px] text-slate-300 bg-slate-900/50 rounded p-2 mt-1 overflow-x-auto max-h-40">
                              {issue.fix_result.fixed_code}
                            </pre>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** Model item component for the model list */
function ModelItem({ model, isActive, onActivate, onEdit, onDelete, onTest }: {
  model: any;
  isActive: boolean;
  onActivate: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onTest: () => void;
}) {
  return (
    <div className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border transition-all ${
      isActive
        ? 'bg-blue-500/10 border-blue-500/30'
        : 'bg-white/[0.02] border-white/5 hover:border-white/10'
    }`}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm text-white font-medium">{model.platform_name}</span>
          {isActive && <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-500/20 text-blue-400">当前使用</span>}
        </div>
        <div className="text-[10px] text-slate-500 mt-0.5 truncate">
          {model.model_name} · {model.api_key_masked}
        </div>
      </div>
      <div className="flex items-center gap-1">
        {!isActive && (
          <button onClick={onActivate} className="p-1.5 text-slate-500 hover:text-blue-400 transition-colors" title="使用此模型">
            <Zap className="w-3.5 h-3.5" />
          </button>
        )}
        <button onClick={onTest} className="p-1.5 text-slate-500 hover:text-amber-400 transition-colors" title="测试连接">
          <Sparkles className="w-3.5 h-3.5" />
        </button>
        <button onClick={onEdit} className="p-1.5 text-slate-500 hover:text-blue-400 transition-colors" title="编辑">
          <Pencil className="w-3.5 h-3.5" />
        </button>
        <button onClick={onDelete} className="p-1.5 text-slate-500 hover:text-red-400 transition-colors" title="删除">
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}

/** Edit model modal component */
function EditModelModal({ modelId, onClose, onSave, onTest, onDelete }: {
  modelId: number | null;
  onClose: () => void;
  onSave: () => void;
  onTest: (apiKey: string, baseUrl: string, modelName: string) => void;
  onDelete: (configId: number) => void;
}) {
  const [model, setModel] = useState<any>(null);
  const [editApiKey, setEditApiKey] = useState('');
  const [editBaseUrl, setEditBaseUrl] = useState('');
  const [editModelName, setEditModelName] = useState('');
  const [showApiKey, setShowApiKey] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [status, setStatus] = useState<{type: 'success' | 'error' | null; message: string}>({type: null, message: ''});

  useEffect(() => {
    if (modelId) {
      apiFetch(`/settings/models/${modelId}`)
        .then(res => res.json())
        .then(data => {
          setModel(data);
          setEditApiKey(data.api_key || '');
          setEditBaseUrl(data.api_base_url || '');
          setEditModelName(data.model_name || '');
        })
        .catch(() => {});
    }
  }, [modelId]);

  const handleSave = async () => {
    if (!modelId || !editModelName.trim()) return;
    setIsSaving(true);
    setStatus({type: null, message: ''});
    try {
      const res = await apiFetch(`/settings/models/${modelId}`, {
        method: 'PUT',
        body: JSON.stringify({
          api_key: editApiKey,
          api_base_url: editBaseUrl,
          model_name: editModelName,
        }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
      setStatus({type: 'success', message: '保存成功'});
      setTimeout(onSave, 800);
    } catch (e: any) {
      setStatus({type: 'error', message: e.message});
    } finally {
      setIsSaving(false);
    }
  };

  const handleTest = async () => {
    setIsTesting(true);
    setStatus({type: null, message: ''});
    try {
      const res = await apiFetch('/settings/ai/test', {
        method: 'POST',
        body: JSON.stringify({
          api_key: editApiKey,
          api_base_url: editBaseUrl,
          chat_model: editModelName,
        }),
      });
      const data = await res.json();
      if (data.success) {
        setStatus({type: 'success', message: data.message || '连接成功'});
      } else {
        setStatus({type: 'error', message: data.message || '连接失败'});
      }
    } catch (e: any) {
      setStatus({type: 'error', message: e.message});
    } finally {
      setIsTesting(false);
    }
  };

  if (!model) return null;

  return (
    <div className="fixed inset-0 z-[99999] bg-black/60 backdrop-blur-sm flex items-center justify-center">
      <div className="bg-slate-800 border border-white/10 rounded-xl p-6 max-w-md w-full mx-4 shadow-2xl">
        <div className="flex items-center justify-between mb-6">
          <h3 className="text-white font-semibold">编辑模型</h3>
          <button onClick={onClose} className="p-1 text-slate-400 hover:text-white transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="mb-4">
          <label className="text-xs text-slate-400 mb-2 block">平台</label>
          <div className="px-4 py-2.5 bg-slate-900/50 rounded-lg text-sm text-white">{model.platform_name}</div>
        </div>

        <div className="mb-4">
          <label className="text-xs text-slate-400 mb-2 block">API Key</label>
          <div className="relative">
            <input
              type={showApiKey ? 'text' : 'password'}
              value={editApiKey}
              onChange={e => setEditApiKey(e.target.value)}
              placeholder="输入新的 API Key（留空保持不变）"
              className="w-full bg-slate-900/50 border border-white/10 rounded-lg pl-4 pr-16 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:border-blue-500/50"
            />
            <button
              onClick={() => setShowApiKey(!showApiKey)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-slate-500 hover:text-blue-400 transition-colors"
            >
              {showApiKey ? '隐藏' : '显示'}
            </button>
          </div>
        </div>

        <div className="mb-4">
          <label className="text-xs text-slate-400 mb-2 block">API 地址</label>
          <input
            type="text"
            value={editBaseUrl}
            onChange={e => setEditBaseUrl(e.target.value)}
            className="w-full bg-slate-900/50 border border-white/10 rounded-lg px-4 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:border-blue-500/50"
          />
        </div>

        <div className="mb-6">
          <label className="text-xs text-slate-400 mb-2 block">模型名称</label>
          <input
            type="text"
            value={editModelName}
            onChange={e => setEditModelName(e.target.value)}
            className="w-full bg-slate-900/50 border border-white/10 rounded-lg px-4 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:border-blue-500/50"
          />
        </div>

        {status.type && (
          <div className={`mb-4 px-3 py-2 rounded-lg text-xs ${status.type === 'success' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20'}`}>
            {status.message}
          </div>
        )}

        <div className="flex gap-2 justify-end">
          <button onClick={() => modelId !== null && onDelete(modelId)} className="px-3 py-2 bg-red-500/10 text-red-400 text-xs rounded-lg hover:bg-red-500/20 transition-colors flex items-center gap-1.5">
            <Trash2 className="w-3.5 h-3.5" />
            删除
          </button>
          <button
            onClick={handleTest}
            disabled={isTesting}
            className="px-3 py-2 bg-amber-500/20 text-amber-400 text-xs rounded-lg hover:bg-amber-500/30 transition-colors disabled:opacity-50 flex items-center gap-1.5"
          >
            {isTesting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
            测试
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving}
            className="px-4 py-2 bg-gradient-to-r from-blue-500 to-blue-700 text-white text-xs rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50 flex items-center gap-1.5"
          >
            {isSaving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            保存
          </button>
        </div>
      </div>
    </div>
  );
}

function ConfidenceBadge({ value }: { value: number }) {
  const cls = value >= 0.8
    ? 'bg-emerald-500/20 text-emerald-400'
    : value >= 0.6
    ? 'bg-amber-500/20 text-amber-400'
    : 'bg-red-500/20 text-red-400';
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${cls}`}>
      {(value * 100).toFixed(0)}%
    </span>
  );
}
