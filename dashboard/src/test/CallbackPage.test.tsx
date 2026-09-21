import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import * as ReactRouter from 'react-router-dom';
import * as AuthContext from '../auth/AuthContext';

// Use vi.mock to replace useNavigate at the module level, before any component imports
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof ReactRouter>();
  return {
    ...actual,
    useNavigate: vi.fn(() => navigateSpy),
    useLocation: vi.fn(() => ({
      pathname: '/callback',
      search: '',
      hash: '',
      state: null,
      key: 'default',
    })),
  };
});

const navigateSpy = vi.fn();

const mockUserManager = {
  signinCallback: vi.fn<[], Promise<void>>(),
};

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({
    user: null,
    loading: false,
    login: vi.fn(),
    logout: vi.fn(),
    getAccessToken: vi.fn(),
    userManager: mockUserManager,
  }),
}));

// Must import after vi.mock
import CallbackPage from '../pages/CallbackPage';

beforeEach(() => {
  navigateSpy.mockClear();
  mockUserManager.signinCallback.mockResolvedValue(undefined);
});

describe('CallbackPage', () => {
  it('renders loading text while processing', () => {
    render(<CallbackPage />);
    expect(screen.getByText(/signing in/i)).toBeInTheDocument();
  });

  it('navigates to home on successful callback', async () => {
    render(<CallbackPage />);
    await waitFor(() => {
      expect(navigateSpy).toHaveBeenCalledWith('/', { replace: true });
    });
  });

  it('navigates to login on callback error', async () => {
    mockUserManager.signinCallback.mockRejectedValue(new Error('oauth error'));
    render(<CallbackPage />);
    await waitFor(() => {
      expect(navigateSpy).toHaveBeenCalledWith('/login', { replace: true });
    });
  });
});
