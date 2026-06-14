import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { Bug } from 'lucide-react';

export default function LoginPage() {
  const { login, register } = useAuth();
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      if (isRegister) {
        if (password.length < 6) { setError('密码至少6位'); return; }
        await register(username, password);
      } else {
        await login(username, password);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-950 via-blue-950 to-slate-950 px-4">
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-blue-500/10 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-emerald-500/5 rounded-full blur-3xl" />
      </div>

      <div className="relative w-full max-w-md">
        <div className="bg-slate-900/90 backdrop-blur-xl border border-white/10 rounded-2xl p-8 shadow-2xl">
          <div className="text-center mb-8">
            <div className="inline-flex items-center justify-center w-14 h-14 bg-gradient-to-br from-blue-500 to-blue-700 rounded-xl mb-4">
              <Bug className="w-7 h-7 text-white" />
            </div>
            <h1 className="text-xl font-bold text-white">TestAssistant AI</h1>
            <p className="text-sm text-slate-400 mt-1">高级测试助手</p>
          </div>

          {error && (
            <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm text-center">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm text-slate-300 mb-1.5">用户名</label>
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                className="w-full px-4 py-2.5 bg-slate-950/80 border border-white/10 rounded-lg text-white text-sm outline-none focus:border-blue-500 transition-colors"
                placeholder="请输入用户名"
                required
              />
            </div>
            <div>
              <label className="block text-sm text-slate-300 mb-1.5">密码</label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="w-full px-4 py-2.5 bg-slate-950/80 border border-white/10 rounded-lg text-white text-sm outline-none focus:border-blue-500 transition-colors"
                placeholder={isRegister ? '至少6位' : '请输入密码'}
                required
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 bg-gradient-to-r from-blue-500 to-blue-700 text-white font-semibold rounded-lg hover:shadow-lg hover:shadow-blue-500/25 transition-all disabled:opacity-50"
            >
              {loading ? '处理中...' : (isRegister ? '注 册' : '登 录')}
            </button>
            <button
              type="button"
              onClick={() => { setIsRegister(!isRegister); setError(''); }}
              className="w-full py-3 bg-white/5 border border-white/10 text-slate-300 font-medium rounded-lg hover:bg-white/10 hover:text-white transition-all text-sm"
            >
              {isRegister ? '已有账号？去登录' : '还没有账号？去注册'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
