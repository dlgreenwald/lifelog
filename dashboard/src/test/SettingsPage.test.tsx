import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import SettingsPage from '../pages/SettingsPage';
import * as AuthContext from '../auth/AuthContext';
import * as ReactRouter from 'react-router-dom';
import { api } from '../api/client';

vi.mock('../api/client', () => ({
  api: {
    getSettings: vi.fn(),
    saveSettings: vi.fn(),
  },
}));

vi.mock('@/hooks/use-mobile', () => ({
  useIsMobile: () => false,
}));

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof ReactRouter>();
  return {
    ...actual,
    useNavigate: vi.fn(),
    useLocation: vi.fn(),
  };
});

vi.spyOn(AuthContext, 'useAuth').mockReturnValue({
  user: { profile: {} } as AuthContext.User,
  loading: false,
  login: vi.fn(),
  logout: vi.fn(),
  getAccessToken: vi.fn(),
  userManager: {} as AuthContext.UserManager,
});

// SettingsForm and MobileNavBar are complex — mock them to avoid jsdom issues
vi.mock('@/components/SettingsForm', () => ({
  default: vi.fn(() => <div>SettingsForm</div>),
}));
vi.mock('@/components/MobileNavBar', () => ({
  default: vi.fn(() => <div>MobileNavBar</div>),
}));

const mockApi = vi.mocked(api);

beforeEach(() => {
  mockApi.getSettings.mockResolvedValue({ language: 'en', llm_context: 'ctx' });
  mockApi.saveSettings.mockResolvedValue(undefined);
});

describe('SettingsPage', () => {
  it('renders the settings heading', () => {
    render(<SettingsPage />);
    expect(screen.getByText('Settings')).toBeInTheDocument();
  });

  it('renders SettingsForm', async () => {
    render(<SettingsPage />);
    await waitFor(() => {
      expect(mockApi.getSettings).toHaveBeenCalled();
    });
    expect(screen.getByText('SettingsForm')).toBeInTheDocument();
  });
});
