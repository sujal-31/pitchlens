import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';
import { tokenStorage, apiClient } from '../lib/api';

interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
}

interface AuthContextType extends AuthState {
  login: (email: string, password: string) => Promise<{ success: boolean; error?: string }>;
  register: (email: string, password: string) => Promise<{ success: boolean; error?: string }>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authState, setAuthState] = useState<AuthState>({
    isAuthenticated: false,
    isLoading: true,
  });

  // Check for existing token on mount
  useEffect(() => {
    const token = tokenStorage.getAccessToken();
    setAuthState({
      isAuthenticated: !!token,
      isLoading: false,
    });
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    try {
      const response = await apiClient('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        return { success: false, error: data.detail || 'Invalid email or password' };
      }

      const data = await response.json();
      tokenStorage.setTokens(data.access_token, data.refresh_token);
      setAuthState({ isAuthenticated: true, isLoading: false });
      return { success: true };
    } catch {
      return { success: false, error: 'Network error. Please try again.' };
    }
  }, []);

  const register = useCallback(async (email: string, password: string) => {
    try {
      const response = await apiClient('/api/auth/register', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        return { success: false, error: data.detail || 'Registration failed' };
      }

      const data = await response.json();
      tokenStorage.setTokens(data.access_token, data.refresh_token);
      setAuthState({ isAuthenticated: true, isLoading: false });
      return { success: true };
    } catch {
      return { success: false, error: 'Network error. Please try again.' };
    }
  }, []);

  const logout = useCallback(() => {
    tokenStorage.clearTokens();
    setAuthState({ isAuthenticated: false, isLoading: false });
  }, []);

  return (
    <AuthContext value={{ ...authState, login, register, logout }}>
      {children}
    </AuthContext>
  );
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
