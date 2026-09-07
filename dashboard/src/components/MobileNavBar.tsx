import { useNavigate } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCalendar, faCheckSquare, faLightbulb, faUsers, faCog } from '@fortawesome/free-solid-svg-icons';
import { Button } from '@/components/ui/button';
import { useIsMobile } from '@/hooks/use-mobile';

interface MobileNavBarProps {
  calendarOpen?: boolean;
  onCalendarToggle?: () => void;
}

export default function MobileNavBar({ calendarOpen, onCalendarToggle }: MobileNavBarProps) {
  const navigate = useNavigate();
  const isMobile = useIsMobile();

  if (!isMobile) return null;

  return (
    <nav className="mobile-nav-bar">
      <Button
        variant="ghost"
        size="sm"
        className="mobile-nav-btn"
        onClick={onCalendarToggle ? onCalendarToggle : () => navigate('/')}
      >
        <FontAwesomeIcon icon={faCalendar} />
        <span>{calendarOpen !== undefined ? (calendarOpen ? 'Close' : 'Calendar') : 'Calendar'}</span>
      </Button>
      <Button variant="ghost" size="sm" className="mobile-nav-btn" onClick={() => navigate('/todos')}>
        <FontAwesomeIcon icon={faCheckSquare} />
        <span>TODOs</span>
      </Button>
      <Button variant="ghost" size="sm" className="mobile-nav-btn" onClick={() => navigate('/decisions')}>
        <FontAwesomeIcon icon={faLightbulb} />
        <span>Decisions</span>
      </Button>
      <Button variant="ghost" size="sm" className="mobile-nav-btn" onClick={() => navigate('/speakers')}>
        <FontAwesomeIcon icon={faUsers} />
        <span>Speakers</span>
      </Button>
      <Button variant="ghost" size="sm" className="mobile-nav-btn" onClick={() => navigate('/settings')}>
        <FontAwesomeIcon icon={faCog} />
        <span>Settings</span>
      </Button>
    </nav>
  );
}
