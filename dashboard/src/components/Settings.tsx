import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { ModeToggle } from '@/components/mode-toggle';
import type { UserSettings } from '../types';

const LANGUAGES: Record<string, string> = {
  auto: 'Auto-detect',
  en: 'English',
  zh: 'Chinese',
  de: 'German',
  es: 'Spanish',
  ru: 'Russian',
  ko: 'Korean',
  fr: 'French',
  ja: 'Japanese',
  pt: 'Portuguese',
  tr: 'Turkish',
  pl: 'Polish',
  ca: 'Catalan',
  nl: 'Dutch',
  sv: 'Swedish',
  bg: 'Bulgarian',
  cs: 'Czech',
  da: 'Danish',
  fi: 'Finnish',
  el: 'Greek',
  hr: 'Croatian',
  sk: 'Slovak',
  mw: 'Maori',
  no: 'Norwegian',
  uk: 'Ukrainian',
  sl: 'Slovenian',
  lv: 'Latvian',
  tt: 'Tatar',
  hy: 'Armenian',
  et: 'Estonian',
  mk: 'Macedonian',
  bs: 'Bosnian',
  kk: 'Kazakh',
  sq: 'Albanian',
  sw: 'Swahili',
  tk: 'Turkmen',
  tg: 'Tajik',
  az: 'Azerbaijani',
  id: 'Indonesian',
  ms: 'Malay',
  tl: 'Tagalog',
  ro: 'Romanian',
  vi: 'Vietnamese',
  ml: 'Malayalam',
  th: 'Thai',
  mr: 'Marathi',
  ta: 'Tamil',
  ur: 'Urdu',
  bn: 'Bengali',
  pa: 'Punjabi',
  gu: 'Gujarati',
  kn: 'Kannada',
  te: 'Telugu',
  si: 'Sinhala',
  my: 'Burmese',
  am: 'Amharic',
  sd: 'Sindhi',
  ne: 'Nepali',
  as: 'Assamese',
  bo: 'Tibetan',
  mn: 'Mongolian',
  cy: 'Welsh',
  gl: 'Galician',
  is: 'Icelandic',
  mt: 'Maltese',
  ba: 'Bashkir',
  uz: 'Uzbek',
  su: 'Sundanese',
  ha: 'Hausa',
  yo: 'Yoruba',
  'zh-CN': 'Chinese (Simplified)',
  'zh-TW': 'Chinese (Traditional)',
  'pt-BR': 'Portuguese (Brazil)',
  'es-MX': 'Spanish (Mexico)',
};

const INJECTION_PATTERNS: RegExp[] = [
  /ignore\s+(all\s+)?(previous|your)/i,
  /disregard\s+(all\s+)?(previous|your)/i,
  /forget\s+everything/i,
  /you\s+are\s+now\s+/i,
  /new\s+instructions?/i,
  /system\s+prompt/i,
  /#{2,}|[-=]{3,}|\*{3,}/,
  /\bdo\s+not\b/i,
  /\bnever\b/i,
  /\balways\s+follow\b/i,
  /\boverride\b/i,
  /\bnew\s+rule\b/i,
  /<(system|instruction|prompt)[^>]*>.*?<\/\1>/i,
];

function validateClientSide(text: string): string | null {
  if (text.length > 2000) {
    return 'LLM context exceeds maximum length of 2000 characters';
  }
  for (const pattern of INJECTION_PATTERNS) {
    if (pattern.test(text)) {
      return 'LLM context contains disallowed content. Please remove any prompt injection patterns.';
    }
  }
  return null;
}

export default function Settings() {
  const [settings, setSettings] = useState<UserSettings>({ language: 'auto', llm_context: '' });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [clientError, setClientError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getSettings().then((data) => {
      setSettings({ language: data.language ?? 'auto', llm_context: data.llm_context ?? '' });
      setLoading(false);
    }).catch(() => {
      setLoading(false);
    });
  }, []);

  async function handleSave() {
    const error = validateClientSide(settings.llm_context);
    if (error) {
      setClientError(error);
      return;
    }
    setClientError(null);
    setSaving(true);
    setMessage(null);
    try {
      await api.saveSettings(settings);
      setMessage({ type: 'success', text: 'Settings saved successfully.' });
    } catch (err) {
      setMessage({ type: 'error', text: err instanceof Error ? err.message : 'Failed to save settings.' });
    } finally {
      setSaving(false);
    }
  }

  function handleContextChange(value: string) {
    setSettings((s) => ({ ...s, llm_context: value }));
    setClientError(validateClientSide(value));
  }

  const sortedLanguages = Object.entries(LANGUAGES).sort(([, a], [, b]) => a.localeCompare(b));

  if (loading) {
    return <div className="settings-loading">Loading settings...</div>;
  }

  return (
    <div className="settings-page">
      <h2>Settings</h2>

      <div className="settings-section">
        <h3>Appearance</h3>
        <p>Toggle between light, dark, and system color theme.</p>
        <ModeToggle />
      </div>
      <div className="settings-section">
        <label htmlFor="language-select">
          <h3>Transcription Language</h3>
          <p>Default language for WhisperX transcription. &quot;Auto-detect&quot; will automatically identify the language.</p>
          <select
            id="language-select"
            value={settings.language}
            onChange={(e) => setSettings((s) => ({ ...s, language: e.target.value }))}
          >
            {sortedLanguages.map(([code, name]) => (
              <option key={code} value={code}>{name}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="settings-section">
        <h3>LLM Context</h3>
        <p>
          Provide background information about yourself to improve summarization quality.
          Include nicknames you use, your job or profession, locations you frequently discuss, etc.
          This context is prepended to every transcript before summarization.
        </p>
        <textarea
          value={settings.llm_context}
          onChange={(e) => handleContextChange(e.target.value)}
          placeholder="e.g. I work as a software engineer at a startup. My wife is named Sarah. We live in Seattle. I often discuss side projects related to Python and React..."
          maxLength={2000}
          rows={6}
          className={clientError ? 'error' : ''}
        />
        <div className="char-count">
          {settings.llm_context.length} / 2000 characters
        </div>
        {clientError && (
          <div className="error-message">{clientError}</div>
        )}
      </div>

      {message && (
        <div className={`message ${message.type}`}>
          {message.text}
        </div>
      )}

      <button onClick={handleSave} disabled={saving || !!clientError} className="save-button">
        {saving ? 'Saving...' : 'Save Settings'}
      </button>
    </div>
  );
}
