import { useEffect, useState } from 'react';
import { useAuth } from '../auth/AuthContext';
import { api } from '../api/client';
import { ModeToggle } from '@/components/mode-toggle';
import type { UserSettings } from '../types';
import SettingsForm from '@/components/SettingsForm';

export default function SettingsPage() {
  const { logout } = useAuth();
  const [settings, setSettings] = useState<UserSettings>({
    language: 'auto',
    llm_context: '',
  });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  useEffect(() => {
    api.getSettings().then((data) => {
      setSettings(data.settings);
    });
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.saveSettings(settings);
      setMessage({ type: 'success', text: 'Settings saved successfully.' });
    } catch {
      setMessage({ type: 'error', text: 'Failed to save settings. Please try again.' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <ModeToggle />
      </div>
      <SettingsForm
        settings={settings}
        saving={saving}
        message={message}
        onChange={setSettings}
        onSave={handleSave}
        onLogout={logout}
      />
    </div>
  );
}
