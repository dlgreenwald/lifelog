import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import * as ReactRouter from 'react-router-dom';

vi.mock('@/hooks/use-mobile', () => ({
  useIsMobile: vi.fn(),
}));

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof ReactRouter>();
  return {
    ...actual,
    useNavigate: vi.fn(() => navigateSpy),
    useLocation: vi.fn(() => ({
      pathname: '/',
      search: '',
      hash: '',
      state: null,
      key: 'default',
    })),
  };
});

const navigateSpy = vi.fn();
const { useIsMobile } = await import('@/hooks/use-mobile');

beforeEach(() => {
  navigateSpy.mockClear();
  vi.mocked(useIsMobile).mockReturnValue(true);
});

import MobileNavBar from '../components/MobileNavBar';

describe('MobileNavBar', () => {
  it('renders all nav buttons when mobile', () => {
    render(<MobileNavBar />);
    expect(screen.getAllByRole('button')).toHaveLength(6);
  });

  it('returns null when not mobile', () => {
    vi.mocked(useIsMobile).mockReturnValue(false);
    const { container } = render(<MobileNavBar />);
    expect(container).toBeEmptyDOMElement();
  });

  it('navigates to /todos when TODOs button clicked', async () => {
    const user = userEvent.setup();
    render(<MobileNavBar />);
    await user.click(screen.getByRole('button', { name: /TODOs/i }));
    expect(navigateSpy).toHaveBeenCalledWith('/todos');
  });

  it('navigates to /search when Search button clicked', async () => {
    const user = userEvent.setup();
    render(<MobileNavBar />);
    await user.click(screen.getByRole('button', { name: /Search/i }));
    expect(navigateSpy).toHaveBeenCalledWith('/search');
  });

  it('calls onCalendarToggle when calendar button clicked', async () => {
    const user = userEvent.setup();
    const onCalendarToggle = vi.fn();
    render(<MobileNavBar onCalendarToggle={onCalendarToggle} />);
    await user.click(screen.getByRole('button', { name: /Calendar/i }));
    expect(onCalendarToggle).toHaveBeenCalledTimes(1);
    expect(navigateSpy).not.toHaveBeenCalled();
  });

  it('shows Close text when calendarOpen is true', () => {
    render(<MobileNavBar calendarOpen={true} />);
    expect(screen.getByText('Close')).toBeInTheDocument();
  });

  it('shows Calendar text when calendarOpen is false', () => {
    render(<MobileNavBar calendarOpen={false} />);
    expect(screen.getByText('Calendar')).toBeInTheDocument();
  });
});
