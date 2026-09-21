import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type * as ReactRouterDom from 'react-router-dom';

// vi.mock is hoisted — runs before MobileNav imports react-router-dom
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof ReactRouterDom>();
  return {
    ...actual,
    useNavigate: vi.fn(() => navigateSpy),
    useLocation: vi.fn(() => locationSpy()),
  };
});

const navigateSpy = vi.fn();
const locationSpy = vi.fn(() => ({
  pathname: '/',
  search: '',
  hash: '',
  state: null,
  key: 'default',
}));

// Import after vi.mock runs so MobileNav gets the mocked module
import { MobileNav } from '../components/MobileNav';

beforeEach(() => {
  navigateSpy.mockClear();
  locationSpy.mockReturnValue({
    pathname: '/',
    search: '',
    hash: '',
    state: null,
    key: 'default',
  });
});

describe('MobileNav', () => {
  it('renders all five nav buttons', () => {
    render(<MobileNav />);
    expect(screen.getAllByRole('button')).toHaveLength(5);
  });

  it('calls navigate with /todos when Todos button clicked', async () => {
    const user = userEvent.setup();
    render(<MobileNav />);
    await user.click(screen.getByRole('button', { name: /TODOs/i }));
    expect(navigateSpy).toHaveBeenCalledWith('/todos');
  });

  it('calls navigate with /decisions when Decisions button clicked', async () => {
    const user = userEvent.setup();
    render(<MobileNav />);
    await user.click(screen.getByRole('button', { name: /Decisions/i }));
    expect(navigateSpy).toHaveBeenCalledWith('/decisions');
  });

  it('calls navigate with /speakers when Speakers button clicked', async () => {
    const user = userEvent.setup();
    render(<MobileNav />);
    await user.click(screen.getByRole('button', { name: /Speakers/i }));
    expect(navigateSpy).toHaveBeenCalledWith('/speakers');
  });

  it('calls navigate with /settings when Settings button clicked', async () => {
    const user = userEvent.setup();
    render(<MobileNav />);
    await user.click(screen.getByRole('button', { name: /Settings/i }));
    expect(navigateSpy).toHaveBeenCalledWith('/settings');
  });

  it('calls onCalendarToggle when Calendar clicked on calendar page', async () => {
    const user = userEvent.setup();
    const onCalendarToggle = vi.fn();
    render(<MobileNav onCalendarToggle={onCalendarToggle} />);
    await user.click(screen.getByRole('button', { name: /Calendar/i }));
    expect(onCalendarToggle).toHaveBeenCalledTimes(1);
    expect(navigateSpy).not.toHaveBeenCalled();
  });

  it('calls navigate with / when Calendar clicked on non-calendar page', async () => {
    const user = userEvent.setup();
    // Simulate being on a non-calendar page
    locationSpy.mockReturnValueOnce({
      pathname: '/todos',
      search: '',
      hash: '',
      state: null,
      key: 'default',
    });
    render(<MobileNav />);
    await user.click(screen.getByRole('button', { name: /Calendar/i }));
    expect(navigateSpy).toHaveBeenCalledWith('/');
  });
});
