import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import LoginPage from '../pages/LoginPage';
import * as AuthContext from '../auth/AuthContext';

const loginSpy = vi.fn();
vi.spyOn(AuthContext, 'useAuth').mockReturnValue({
  user: null,
  loading: false,
  login: loginSpy,
  logout: vi.fn(),
  getAccessToken: vi.fn(),
  userManager: {} as AuthContext.UserManager,
});

describe('LoginPage', () => {
  it('renders the login button', () => {
    render(<LoginPage />);
    expect(screen.getByRole('button', { name: /sign in with oidc/i })).toBeInTheDocument();
  });

  it('calls login when the button is clicked', async () => {
    const user = userEvent.setup();
    render(<LoginPage />);
    await user.click(screen.getByRole('button', { name: /sign in with oidc/i }));
    expect(loginSpy).toHaveBeenCalledTimes(1);
  });
});
