import { useState, useEffect, useCallback, useRef } from 'react';
import { useAuth, apiFetch } from '../context/AuthContext';
import { API_BASE } from '../config';
import {
  Bug, Send, Loader2, FolderOpen, Globe, Settings,
  MessageSquare, CheckCircle, AlertCircle, FileText,
  Folder, ChevronRight, ChevronDown, X, Play, Square,
  Zap, AlertTriangle
} from 'lucide-react';

interface ProjectFile {
  name: string;
  path: string;
  type: 'file' | 'directory';
  children?: ProjectFile[];
}

interface TestStep {
  step: number;
  action: string;
  target: string;
  result: string;
  success: boolean;
  screenshot?: string;
  console_errors?: string[];
  network_errors?: string[];
}

interface CodeIssue {
  file_path: string;
  line_number: number;
  issue_description: string;
  error_log: string;
  suggested_fix: string;
  code_snippet?: string;
}

interface ChatMessage {
  id: number;
  role: 'user' | 'assistant' | 'system';
  content: string;
  time: string;
  type?: 'chat' | 'error_report' | 'code_issue' | 'status';
  relatedIssue?: number;
}

export default function TestWorkspace({ onBack }: { onBack: () => void }) {
  const { user, logout } = useAuth();
  
  // 目标配置
  const [targetUrl, setTargetUrl] = useState('');
  const [projectPath, setProjectPath] = useState('');
  const [testGoals, setTestGoals] = useState('');
  const [isTestRunning, setIsTestRunning] = useState(false);
  const [testTaskId, setTestTaskId] = useState<string | null>(null);
  
  // 测试状态
  const [testStatus, setTestStatus] = useState<string>('');
  const [testMessage, setTestMessage] = useState('');
  const [testSteps, setTestSteps] = useState<TestStep[]>([]);
  const [testCodeIssues, setTestCodeIssues] = useState<CodeIssue[]>([]);
  const [currentScreenshot, setCurrentScreenshot] = useState<string>('');
  const [stats, setStats] = useState({ steps: 0, errors: 0, screenshots: 0 });
  
  // 项目文件树
  const [projectFiles, setProjectFiles] = useState<ProjectFile[]>([]);
  const [selectedFile, setSelectedFile] = useState<string>('');
  const [fileContent, setFileContent] = useState<string>('');
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());
  
  // AI 对话
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  
  const scrollToBottom = useCallback(() => {
    setTimeout(() => {
      chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, 100);
  }, []);
  
  useEffect(() => {
    scrollToBottom();
  }, [chatMessages, scrollToBottom]);
  
  // 加载项目文件
  const loadProjectFiles = async () => {
    if (!projectPath.trim()) return;
    try {
      const res = await apiFetch(`/test/project/files?path=${encodeURIComponent(projectPath.trim())}`);
      if (!res.ok) throw new Error('加载文件失败');
      const data = await res.json();
      setProjectFiles(data.files || []);
    } catch (e) {
      // 如果API不存在，用简单的树结构
      addChatMessage('system', `⚠️ 无法加载项目文件树，请确认项目路径: ${projectPath}`);
    }
  };
  
  // 获取文件内容
  const openFile = async (filePath: string) => {
    setSelectedFile(filePath);
    try {
      const res = await apiFetch(`/test/project/file?path=${encodeURIComponent(filePath)}`);
      if (!res.ok) throw new Error('读取文件失败');
      const data = await res.json();
      setFileContent(data.content || '');
    } catch {
      setFileContent('// 无法读取文件内容');
    }
  };
  
  // 切换目录展开状态
  const toggleDir = (path: string) => {
    const next = new Set(expandedDirs);
    if (next.has(path)) {
      next.delete(path);
    } else {
      next.add(path);
    }
    setExpandedDirs(next);
  };
  
  // 添加聊天消息
  const addChatMessage = (role: 'user' | 'assistant' | 'system', content: string, type?: ChatMessage['type']) => {
    setChatMessages(prev => [...prev, {
      id: Date.now() + Math.random(),
      role,
      content,
      time: new Date().toISOString(),
      type: type || (role === 'assistant' ? 'error_report' : 'chat'),
    }]);
  };
  
  // 开始测试
  const startTest = async () => {
    if (!targetUrl.trim() || !projectPath.trim() || !testGoals.trim() || isTestRunning) return;
    
    setIsTestRunning(true);
    setTestSteps([]);
    setTestCodeIssues([]);
    setTestMessage('');
    setStats({ steps: 0, errors: 0, screenshots: 0 });
    setChatMessages([{
      id: Date.now(),
      role: 'system',
      content: `🚀 开始测试\n\n目标: ${targetUrl}\n项目: ${projectPath}\n测试目标: ${testGoals}`,
      time: new Date().toISOString(),
      type: 'status',
    }]);
    
    try {
      const goals = testGoals.split('\n').map(g => g.trim()).filter(Boolean);
      
      // 先加载项目文件
      await loadProjectFiles();
      
      addChatMessage('assistant', '正在启动浏览器...', 'status');
      
      const res = await apiFetch('/test/run', {
        method: 'POST',
        body: JSON.stringify({
          target_url: targetUrl.trim(),
          project_path: projectPath.trim(),
          test_goals: goals,
          max_steps: 30,
        }),
      });
      
      if (!res.ok) {
        const e = await res.json();
        throw new Error(e.detail);
      }
      
      const data = await res.json();
      
      setTestTaskId(data.task_id);
      setTestSteps(data.steps || []);
      setTestCodeIssues(data.code_issues || []);
      setTestStatus(data.status);
      setTestMessage(data.message || '');
      setStats({
        steps: (data.steps || []).length,
        errors: data.errors_found || 0,
        screenshots: data.screenshots_saved || 0,
      });
      
      // 如果有截图，显示最后一张
      const lastStep = (data.steps || []).findLast((s: TestStep) => s.screenshot);
      if (lastStep?.screenshot) {
        setCurrentScreenshot(lastStep.screenshot);
      }
      
      // 报告问题
      if (data.code_issues?.length > 0) {
        addChatMessage('assistant', ` 测试发现了 ${data.code_issues.length} 个问题，请查看右侧代码面板。`, 'error_report');
        data.code_issues.forEach((issue: CodeIssue, idx: number) => {
          addChatMessage('assistant', `问题 #${idx + 1}\n\n文件: ${issue.file_path}:${issue.line_number}\n\n${issue.issue_description}\n\n修复建议:\n${issue.suggested_fix}`, 'code_issue');
        });
      } else {
        addChatMessage('assistant', `✅ 测试完成！未发现明显问题。`, 'status');
      }
      
    } catch (e: any) {
      setTestStatus('failed');
      setTestMessage('测试失败: ' + e.message);
      addChatMessage('assistant', `❌ 测试执行失败: ${e.message}`, 'error_report');
    } finally {
      setIsTestRunning(false);
    }
  };
  
  // 停止测试
  const stopTest = () => {
    setIsTestRunning(false);
    setTestStatus('stopped');
    setTestMessage('测试已停止');
    addChatMessage('assistant', '⏹️ 测试已手动停止', 'status');
  };
  
  // 发送对话
  const handleSendChat = async () => {
    if (!chatInput.trim() || isSending) return;
    const text = chatInput.trim();
    setChatInput('');
    setIsSending(true);
    
    addChatMessage('user', text);
    
    try {
      const res = await apiFetch('/chat', {
        method: 'POST',
        body: JSON.stringify({
          content: text,
          use_rag: false,
          session_id: testTaskId,
        }),
      });
      
      if (!res.ok) throw new Error('发送失败');
      const data = await res.json();
      
      const answer = data.data?.answer || data.message || '暂无回复';
      addChatMessage('assistant', answer);
    } catch (e: any) {
      addChatMessage('assistant', ` 回复失败: ${e.message}`, 'error_report');
    } finally {
      setIsSending(false);
    }
  };
  
  // 渲染文件树
  const renderFileTree = (files: ProjectFile[], depth = 0) => {
    return files.map(file => {
      const isExpanded = expandedDirs.has(file.path);
      const indent = depth * 16 + 8;
      
      if (file.type === 'directory') {
        return (
          <div key={file.path}>
            <button
              onClick={() => toggleDir(file.path)}
              className="flex items-center gap-1.5 px-2 py-1 w-full text-left text-xs text-slate-300 hover:bg-white/5 transition-colors"
              style={{ paddingLeft: `${indent}px` }}
            >
              {isExpanded ? <ChevronDown className="w-3 h-3 text-slate-500" /> : <ChevronRight className="w-3 h-3 text-slate-500" />}
              <Folder className="w-3.5 h-3.5 text-amber-400" />
              <span className="truncate">{file.name}</span>
            </button>
            {isExpanded && file.children && (
              <div>{renderFileTree(file.children, depth + 1)}</div>
            )}
          </div>
        );
      }
      
      const isSelected = selectedFile === file.path;
      return (
        <button
          key={file.path}
          onClick={() => openFile(file.path)}
          className={`flex items-center gap-1.5 px-2 py-1 w-full text-left text-xs truncate transition-colors ${
            isSelected ? 'bg-blue-500/20 text-blue-400' : 'text-slate-400 hover:bg-white/5 hover:text-white'
          }`}
          style={{ paddingLeft: `${indent + 16}px` }}
        >
          <FileText className="w-3 h-3 flex-shrink-0" />
          <span className="truncate">{file.name}</span>
        </button>
      );
    });
  };
  
  return (
    <div className="h-screen flex bg-slate-950">
      {/* ==================== 左侧：AI 对话面板 ==================== */}
      <div className="w-[380px] bg-slate-900/80 border-r border-white/5 flex flex-col">
        {/* Header */}
        <div className="px-4 py-3 border-b border-white/5">
          <div className="flex items-center gap-2">
            <button
              onClick={onBack}
              className="p-1.5 text-slate-500 hover:text-white hover:bg-white/5 rounded-lg transition-colors mr-1"
            >
              <X className="w-4 h-4" />
            </button>
            <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-blue-700 rounded-lg flex items-center justify-center">
              <Bug className="w-4 h-4 text-white" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-white">测试工作台</h2>
              <p className="text-[10px] text-slate-500">AI 自动化测试 + 代码定位修复</p>
            </div>
          </div>
        </div>
        
        {/* Model Config */}
        <div className="px-3 py-2 border-b border-white/5">
          <div className="flex items-center gap-1.5 text-[10px] text-slate-500 mb-1">
            <Settings className="w-3 h-3" />
            <span>AI 模型配置</span>
          </div>
          <button
            onClick={() => {/* TODO: 打开模型配置 */}}
            className="w-full flex items-center justify-between px-2 py-1.5 bg-white/[0.03] border border-white/5 rounded text-xs text-slate-400 hover:border-white/10 transition-colors"
          >
            <span>当前模型: 请在设置中配置</span>
            <ChevronRight className="w-3 h-3" />
          </button>
        </div>
        
        {/* Chat Messages */}
        <div className="flex-1 overflow-y-auto scrollbar-thin px-3 py-3 space-y-3">
          {chatMessages.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="w-12 h-12 bg-blue-500/10 rounded-xl flex items-center justify-center mb-3">
                <MessageSquare className="w-5 h-5 text-blue-400" />
              </div>
              <p className="text-xs text-slate-500">暂无对话</p>
              <p className="text-[10px] text-slate-600 mt-1">配置测试参数后开始测试</p>
            </div>
          ) : (
            chatMessages.map((msg) => (
              <div key={msg.id} className={`px-3 py-2 rounded-lg text-xs ${
                msg.role === 'user' ? 'bg-blue-500/10 border border-blue-500/20 text-white' :
                msg.type === 'error_report' ? 'bg-red-500/5 border border-red-500/20 text-red-300' :
                msg.type === 'code_issue' ? 'bg-amber-500/5 border border-amber-500/20 text-amber-300' :
                msg.type === 'status' ? 'bg-emerald-500/5 border border-emerald-500/20 text-emerald-300' :
                'bg-white/[0.03] border border-white/5 text-slate-300'
              }`}>
                {msg.role === 'assistant' && (
                  <div className="flex items-center gap-1 mb-1">
                    <Bug className="w-3 h-3 text-blue-400" />
                    <span className="text-[10px] text-slate-500">Agent</span>
                  </div>
                )}
                <div className="whitespace-pre-wrap break-words">{msg.content}</div>
              </div>
            ))
          )}
          <div ref={chatEndRef} />
        </div>
        
        {/* Chat Input */}
        <div className="px-3 py-3 border-t border-white/5">
          <div className="flex gap-2 items-end">
            <textarea
              value={chatInput}
              onChange={e => setChatInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendChat(); } }}
              placeholder="和 Agent 对话..."
              rows={1}
              className="flex-1 bg-slate-800/60 border border-white/10 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 outline-none focus:border-blue-500/50 resize-none min-h-[36px]"
              disabled={isSending}
            />
            <button
              onClick={handleSendChat}
              disabled={isSending || !chatInput.trim()}
              className="w-9 h-9 bg-blue-500 rounded-lg flex items-center justify-center text-white disabled:opacity-30 hover:bg-blue-600 transition-colors"
            >
              {isSending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </button>
          </div>
        </div>
      </div>
      
      {/* ==================== 中间：浏览器测试面板 ==================== */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Config Bar */}
        <div className="px-4 py-3 border-b border-white/5 bg-slate-900/50">
          <div className="flex gap-3 items-end mb-3">
            <div className="flex-1">
              <label className="flex items-center gap-1.5 text-[10px] text-slate-500 mb-1">
                <Globe className="w-3 h-3" /> 目标测试网址
              </label>
              <input
                type="text"
                value={targetUrl}
                onChange={e => setTargetUrl(e.target.value)}
                placeholder="http://localhost:5000"
                className="w-full bg-slate-800/60 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-white placeholder-slate-500 outline-none focus:border-emerald-500/50"
                disabled={isTestRunning}
              />
            </div>
            <div className="flex-1">
              <label className="flex items-center gap-1.5 text-[10px] text-slate-500 mb-1">
                <FolderOpen className="w-3 h-3" /> 项目代码路径
              </label>
              <input
                type="text"
                value={projectPath}
                onChange={e => setProjectPath(e.target.value)}
                placeholder="E:\zzProject\ai-gateway"
                className="w-full bg-slate-800/60 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-white placeholder-slate-500 outline-none focus:border-emerald-500/50"
                disabled={isTestRunning}
              />
            </div>
          </div>
          <div className="flex gap-3 items-center">
            <div className="flex-1">
              <label className="flex items-center gap-1.5 text-[10px] text-slate-500 mb-1">
                <Bug className="w-3 h-3" /> 测试目标 (每行一个)
              </label>
              <textarea
                value={testGoals}
                onChange={e => setTestGoals(e.target.value)}
                placeholder={"测试登录功能\n测试注册功能"}
                rows={1}
                className="w-full bg-slate-800/60 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-white placeholder-slate-500 outline-none focus:border-emerald-500/50 resize-none"
                disabled={isTestRunning}
              />
            </div>
            <div className="flex gap-2 flex-shrink-0">
              <button
                onClick={startTest}
                disabled={isTestRunning || !targetUrl.trim() || !projectPath.trim() || !testGoals.trim()}
                className="px-4 py-2 bg-gradient-to-r from-emerald-500 to-emerald-700 text-white text-xs rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50 flex items-center gap-1.5"
              >
                {isTestRunning ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                {isTestRunning ? '测试中...' : '开始测试'}
              </button>
              {isTestRunning && (
                <button
                  onClick={stopTest}
                  className="px-4 py-2 bg-red-500/20 text-red-400 text-xs rounded-lg hover:bg-red-500/30 transition-colors flex items-center gap-1.5"
                >
                  <Square className="w-3 h-3" />
                  停止
                </button>
              )}
            </div>
          </div>
          
          {/* Stats */}
          {testSteps.length > 0 && (
            <div className="flex gap-3 mt-3 pt-3 border-t border-white/5">
              <div className="flex items-center gap-1.5 text-[10px] text-slate-400">
                <span className="w-5 h-5 bg-white/[0.05] rounded flex items-center justify-center font-bold text-white">{stats.steps}</span>
                执行步骤
              </div>
              <div className="flex items-center gap-1.5 text-[10px] text-slate-400">
                <span className={`w-5 h-5 rounded flex items-center justify-center font-bold ${stats.errors > 0 ? 'bg-red-500/20 text-red-400' : 'bg-emerald-500/20 text-emerald-400'}`}>{stats.errors}</span>
                发现错误
              </div>
              <div className="flex items-center gap-1.5 text-[10px] text-slate-400">
                <span className="w-5 h-5 bg-blue-500/20 text-blue-400 rounded flex items-center justify-center font-bold">{stats.screenshots}</span>
                截图保存
              </div>
              {testMessage && (
                <span className="text-[10px] text-slate-500 ml-auto">{testMessage}</span>
              )}
            </div>
          )}
        </div>
        
        {/* Browser View Area */}
        <div className="flex-1 overflow-y-auto scrollbar-thin px-4 py-4 space-y-4">
          {/* Current Screenshot */}
          {currentScreenshot ? (
            <div className="bg-slate-800/50 border border-white/5 rounded-xl overflow-hidden">
              <div className="px-4 py-2 border-b border-white/5 flex items-center gap-2">
                <Globe className="w-4 h-4 text-emerald-400" />
                <span className="text-xs text-white font-medium">当前页面截图</span>
              </div>
              <div className="p-3">
                <img
                  src={currentScreenshot}
                  alt="页面截图"
                  className="w-full rounded border border-white/5"
                  style={{ maxHeight: '400px', objectFit: 'contain' }}
                />
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <div className="w-16 h-16 bg-emerald-500/10 rounded-2xl flex items-center justify-center mb-4">
                <Globe className="w-7 h-7 text-emerald-400" />
              </div>
              <h3 className="text-sm font-semibold text-white mb-2">等待测试</h3>
              <p className="text-xs text-slate-500 max-w-xs">
                配置好目标地址和项目路径后，点击"开始测试"<br/>Agent 将自动执行测试并截图
              </p>
            </div>
          )}
          
          {/* Steps Timeline */}
          {testSteps.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <Bug className="w-3.5 h-3.5 text-emerald-400" />
                <span className="text-xs text-white font-semibold">执行步骤</span>
              </div>
              {testSteps.map((step, idx) => (
                <div key={idx} className={`bg-white/[0.03] border rounded-lg overflow-hidden ${
                  step.success ? 'border-emerald-500/10' : 'border-red-500/20'
                }`}>
                  <div className="flex items-center gap-2 px-3 py-2">
                    <span className="text-[10px] text-slate-500 font-mono">#{step.step}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                      step.action === 'click' ? 'bg-blue-500/20 text-blue-400' :
                      step.action === 'fill' || step.action === 'type' ? 'bg-emerald-500/20 text-emerald-400' :
                      step.action === 'navigate' ? 'bg-purple-500/20 text-purple-400' :
                      step.action === 'done' ? 'bg-cyan-500/20 text-cyan-400' :
                      'bg-slate-500/20 text-slate-400'
                    }`}>
                      {step.action}
                    </span>
                    {step.success
                      ? <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                      : <AlertCircle className="w-3.5 h-3.5 text-red-400" />
                    }
                    <span className="text-xs text-slate-300 flex-1 truncate">{step.target || step.result}</span>
                  </div>
                  {(step.console_errors?.length > 0 || step.network_errors?.length > 0) && (
                    <div className="px-3 py-2 border-t border-white/5 space-y-1">
                      {step.console_errors?.slice(0, 5).map((err, i) => (
                        <div key={i} className="text-[10px] text-red-400 font-mono whitespace-pre-wrap break-all">Console: {err}</div>
                      ))}
                      {step.network_errors?.slice(0, 5).map((err, i) => (
                        <div key={i} className="text-[10px] text-orange-400 font-mono whitespace-pre-wrap break-all">Network: {err}</div>
                      ))}
                    </div>
                  )}
                  {step.screenshot && (
                    <div className="px-3 py-2 border-t border-white/5">
                      <button
                        onClick={() => setCurrentScreenshot(step.screenshot!)}
                        className="text-[10px] text-blue-400 hover:text-blue-300 transition-colors"
                      >
                        📷 点击查看此步骤截图
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      
      {/* ==================== 右侧：项目代码面板 ==================== */}
      <div className="w-[360px] bg-slate-900/80 border-l border-white/5 flex flex-col">
        {/* Header */}
        <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FolderOpen className="w-4 h-4 text-amber-400" />
            <span className="text-sm font-semibold text-white">项目代码</span>
          </div>
          <button
            onClick={loadProjectFiles}
            disabled={!projectPath.trim()}
            className="p-1.5 text-slate-500 hover:text-white transition-colors"
            title="刷新文件树"
          >
            <Settings className="w-4 h-4" />
          </button>
        </div>
        
        {/* File Tree */}
        <div className="flex-1 overflow-y-auto scrollbar-thin">
          {projectFiles.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center px-4">
              <div className="w-12 h-12 bg-amber-500/10 rounded-xl flex items-center justify-center mb-3">
                <FolderOpen className="w-5 h-5 text-amber-400" />
              </div>
              <p className="text-xs text-slate-500">暂无文件</p>
              <p className="text-[10px] text-slate-600 mt-1">配置项目路径后自动加载</p>
            </div>
          ) : (
            <div className="py-1">
              {renderFileTree(projectFiles)}
            </div>
          )}
        </div>
        
        {/* Code Issues */}
        {testCodeIssues.length > 0 && (
          <div className="border-t border-white/5">
            <div className="px-4 py-2 border-b border-white/5 flex items-center gap-2">
              <AlertTriangle className="w-3.5 h-3.5 text-red-400" />
              <span className="text-xs text-white font-semibold">
                代码问题 ({testCodeIssues.length})
              </span>
            </div>
            <div className="max-h-48 overflow-y-auto scrollbar-thin px-3 py-2 space-y-2">
              {testCodeIssues.map((issue, idx) => (
                <div key={idx} className="bg-red-500/5 border border-red-500/20 rounded-lg p-2">
                  <button
                    onClick={() => openFile(issue.file_path)}
                    className="text-[10px] text-red-400 font-mono hover:text-red-300 transition-colors"
                  >
                    {issue.file_path}:{issue.line_number}
                  </button>
                  <div className="text-xs text-white mt-1">{issue.issue_description}</div>
                  <div className="text-[10px] text-emerald-400 mt-1">{issue.suggested_fix}</div>
                </div>
              ))}
            </div>
          </div>
        )}
        
        {/* Code Viewer */}
        {selectedFile && (
          <div className="border-t border-white/5 flex flex-col" style={{ maxHeight: '40%' }}>
            <div className="px-3 py-2 border-b border-white/5 flex items-center justify-between bg-slate-800/50">
              <div className="flex items-center gap-1.5 min-w-0">
                <FileText className="w-3 h-3 text-blue-400 flex-shrink-0" />
                <span className="text-xs text-white font-mono truncate">{selectedFile.split('\\').pop() || selectedFile.split('/').pop()}</span>
              </div>
              <button
                onClick={() => { setSelectedFile(''); setFileContent(''); }}
                className="p-0.5 text-slate-500 hover:text-white transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
            <pre className="flex-1 overflow-auto scrollbar-thin p-3 text-[10px] text-slate-300 font-mono leading-relaxed bg-slate-950/50">
              {fileContent || '加载中...'}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
