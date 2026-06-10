import { createContext, useContext, useState, useCallback, useEffect, ReactNode } from 'react';
import { API_BASE } from '../config';

interface User {
  id: number;
  username: string;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => void;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(localStorage.getItem('auth_token'));
  const [isLoading, setIsLoading] = useState(true);

  const apiFetch = useCallback(async (url: string, options: RequestInit = {}) => {
    const headers: Record<string, string> = { 'Content-Type': 'application/json', ...options.headers as Record<string, string> };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(`${API_BASE}${url}`, { ...options, headers });
    if (res.status === 401) {
      logout();
      throw new Error('登录已过期');
    }
    return res;
  }, [token]);

  useEffect(() => {
    if (token) {
      apiFetch('/auth/me')
        .then(res => {
          if (!res.ok) throw new Error();
          return res.json();
        })
        .then(data => setUser(data))
        .catch(() => { setToken(null); localStorage.removeItem('auth_token'); })
        .finally(() => setIsLoading(false));
    } else {
      setIsLoading(false);
    }
  }, []);

  const login = async (username: string, password: string) => {
    const res = await apiFetch('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) });
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
    const data = await res.json();
    setToken(data.token);
    setUser({ id: 0, username: data.username });
    localStorage.setItem('auth_token', data.token);
  };

  const register = async (username: string, password: string) => {
    const res = await apiFetch('/auth/register', { method: 'POST', body: JSON.stringify({ username, password }) });
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
    const data = await res.json();
    setToken(data.token);
    setUser({ id: 0, username: data.username });
    localStorage.setItem('auth_token', data.token);
  };

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    localStorage.removeItem('auth_token');
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, login, register, logout, isLoading }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

export async function apiFetch(url: string, options: RequestInit = {}) {
  const token = localStorage.getItem('auth_token');
  const headers: Record<string, string> = { 'Content-Type': 'application/json', ...options.headers as Record<string, string> };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${url}`, { ...options, headers });
  if (res.status === 401) {
    localStorage.removeItem('auth_token');
    window.location.reload();
    throw new Error('登录已过期');
  }
  return res;
}
