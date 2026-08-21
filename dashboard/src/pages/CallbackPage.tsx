import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';

export default function CallbackPage() {
  const navigate = useNavigate();
  const { userManager } = useAuth();

  useEffect(() => {
    userManager.signinCallback().then(() => {
      navigate('/', { replace: true });
    }).catch(() => {
      navigate('/login', { replace: true });
    });
  }, [navigate, userManager]);

  return <div className="loading">Signing in...</div>;
}
