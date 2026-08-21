import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { UserManager, User } from 'oidc-client-ts';
import { getOidcConfig } from './config';

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: () => Promise<void>;
  logout: () => Promise<void>;
  getAccessToken: () => Promise<string | null>;
  userManager: UserManager;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [userManager] = useState(() => new UserManager(getOidcConfig()));
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    userManager.getUser().then((u) => {
      setUser(u);
      setLoading(false);
    });

    // Listen for user changes (signinCallback stores user, fires userLoaded)
    const onUserLoaded = (u: User) => setUser(u);
    const onUserUnloaded = () => setUser(null);
    userManager.events.addUserLoaded(onUserLoaded);
    userManager.events.addUserUnloaded(onUserUnloaded);
    return () => {
      userManager.events.removeUserLoaded(onUserLoaded);
      userManager.events.removeUserUnloaded(onUserUnloaded);
    };
  }, [userManager]);

  const login = useCallback(async () => {
    await userManager.signinRedirect();
  }, [userManager]);

  const logout = useCallback(async () => {
    await userManager.signoutRedirect();
  }, [userManager]);

  const getAccessToken = useCallback(async (): Promise<string | null> => {
    const u = await userManager.getUser();
    if (!u) return null;
    if (!u.expired) return u.access_token;

    // Token expired — try refresh token grant
    if (u.refresh_token) {
      try {
        const refreshed = await userManager.signinSilent();
        if (refreshed?.access_token) {
          setUser(refreshed);
          return refreshed.access_token;
        }
      } catch { /* fall through */ }
    }

    setUser(null);
    return null;
  }, [userManager]);

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, getAccessToken, userManager }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
