import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
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
  /<\/?script/i,
  /javascript:/i,
  /on\w+\s*=/i,
  /data:/i,
  /vbscript:/i,
];

function validateClientSide(text: string): string | null {
  if (INJECTION_PATTERNS.some((p) => p.test(text))) {
    return 'Input contains potentially harmful characters. HTML and script tags are not allowed.';
  }
  return null;
}

export interface SettingsFormProps {
  settings: UserSettings;
  saving: boolean;
  message: { type: 'success' | 'error'; text: string } | null;
  onChange: (next: UserSettings) => void;
  onSave: () => void;
  onLogout: () => void;
}

export default function SettingsForm({
  settings,
  saving,
  message,
  onChange,
  onSave,
  onLogout,
}: SettingsFormProps) {
  const clientError = validateClientSide(settings.llm_context);
  const sortedLanguages = Object.entries(LANGUAGES).sort(([, a], [, b]) =>
    a.localeCompare(b),
  );

  return (
    <Card className="mx-auto max-w-xl">
      <CardHeader>
        <CardTitle>Settings</CardTitle>
        <CardDescription>Manage your account and transcription preferences.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Appearance */}
        <div className="space-y-2">
          <h3 className="text-sm font-medium">Appearance</h3>
          <p className="text-xs text-muted-foreground">Toggle between light, dark, and system color theme.</p>
        </div>

        {/* Transcription Language */}
        <div className="space-y-2">
          <label htmlFor="language-select" className="block">
            <h3 className="text-sm font-medium">Transcription Language</h3>
            <p className="text-xs text-muted-foreground">
              Default language for WhisperX transcription. &quot;Auto-detect&quot; will automatically
              identify the language.
            </p>
          </label>
          <select
            id="language-select"
            value={settings.language}
            onChange={(e) => onChange({ ...settings, language: e.target.value })}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            {sortedLanguages.map(([code, name]) => (
              <option key={code} value={code}>{name}</option>
            ))}
          </select>
        </div>

        {/* LLM Context */}
        <div className="space-y-2">
          <label htmlFor="llm-context" className="block">
            <h3 className="text-sm font-medium">LLM Context</h3>
            <p className="text-xs text-muted-foreground">
              Background information about yourself to improve summarization quality. This context
              is prepended to every transcript before summarization.
            </p>
          </label>
          <textarea
            id="llm-context"
            value={settings.llm_context}
            onChange={(e) => onChange({ ...settings, llm_context: e.target.value })}
            placeholder="e.g. I work as a software engineer at a startup. My wife is named Sarah..."
            maxLength={2000}
            rows={5}
            className={`flex min-h-[100px] w-full rounded-md border bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${
              clientError ? 'border-destructive' : 'border-input'
            }`}
          />
          <div className="flex items-center justify-between">
            {clientError ? (
              <p className="text-xs text-destructive">{clientError}</p>
            ) : (
              <span />
            )}
            <span className="text-xs text-muted-foreground">
              {settings.llm_context.length} / 2000
            </span>
          </div>
        </div>

        {/* Feedback */}
        {message && (
          <p className={`text-sm ${message.type === 'success' ? 'text-green-600' : 'text-destructive'}`}>
            {message.text}
          </p>
        )}

        {/* Actions */}
        <div className="flex items-center gap-3 pt-2">
          <Button onClick={onSave} disabled={saving || !!clientError} variant="default">
            {saving ? 'Saving...' : 'Save Settings'}
          </Button>
          <Button onClick={onLogout} variant="outline">
            Sign out
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
