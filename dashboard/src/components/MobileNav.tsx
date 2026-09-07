import { useNavigate, useLocation } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCalendar, faCheckSquare, faLightbulb, faUsers, faCog } from '@fortawesome/free-solid-svg-icons';
import { Button } from '@/components/ui/button';

interface MobileNavProps {
  /** Toggle calendar drawer on Calendar page. If provided, this button navigates instead of toggling. */
  onCalendarToggle?: () => void;
}

const NAV_ITEMS = [
  { to: '/', icon: faCalendar, label: 'Calendar' },
  { to: '/todos', icon: faCheckSquare, label: 'TODOs' },
  { to: '/decisions', icon: faLightbulb, label: 'Decisions' },
  { to: '/speakers', icon: faUsers, label: 'Speakers' },
  { to: '/settings', icon: faCog, label: 'Settings' },
] as const;

export function MobileNav({ onCalendarToggle }: MobileNavProps) {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <nav className="mobile-nav-bar">
      {NAV_ITEMS.map(({ to, icon, label }) => {
        const isActive = location.pathname === to;
        const isCalendar = to === '/';
        const isOnCalendar = location.pathname === '/';

        if (isCalendar) {
          return (
            <Button
              key={to}
              variant="ghost"
              size="sm"
              className="mobile-nav-btn"
              onClick={isOnCalendar ? onCalendarToggle : () => navigate('/')}
            >
              <FontAwesomeIcon icon={icon} />
              <span>{label}</span>
            </Button>
          );
        }

        return (
          <Button
            key={to}
            variant="ghost"
            size="sm"
            className={`mobile-nav-btn ${isActive ? 'active' : ''}`}
            onClick={() => navigate(to)}
          >
            <FontAwesomeIcon icon={icon} />
            <span>{label}</span>
          </Button>
        );
      })}
    </nav>
  );
}
