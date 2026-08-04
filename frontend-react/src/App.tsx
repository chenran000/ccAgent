import { useAuth } from './context/AuthContext';
import LoginPage from './pages/LoginPage';
import IDELayout from './components/IDELayout';

export default function App() {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="text-gray-500 text-sm">加载中...</div>
    </div>
    );
  }

  return user ? <IDELayout /> : <LoginPage />;
}
