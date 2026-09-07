import { Mic } from 'lucide-react';
import { useAuth } from '../auth/AuthContext';
import { Button } from '@/components/ui/button';

function AudioWave() {
  return (
    <svg
      viewBox="0 0 400 120"
      className="w-full max-w-xs text-primary/30"
      aria-hidden="true"
      preserveAspectRatio="none"
    >
      {/* Center line */}
      <line x1="0" y1="60" x2="400" y2="60" stroke="currentColor" strokeWidth="1" />
      {/* Top wave bars */}
      {[8, 16, 24, 32, 40, 48, 56, 64, 72, 80, 88, 96, 104, 112, 120, 128, 136, 144, 152, 160, 168, 176, 184, 192, 200, 208, 216, 224, 232, 240, 248, 256, 264, 272, 280, 288, 296, 304, 312, 320, 328, 336, 344, 352, 360, 368, 376, 384, 392, 400].map((x, i) => {
        const heights = [20, 35, 50, 65, 80, 65, 50, 75, 90, 75, 55, 70, 85, 70, 50, 40, 60, 80, 95, 80, 60, 45, 65, 85, 100, 85, 65, 50, 35, 55, 75, 90, 75, 55, 40, 60, 80, 95, 80, 60, 45, 30, 50, 70, 85, 70, 50, 35, 20];
        const h = heights[i % heights.length];
        return <rect key={x} x={x} y={60 - h} width="6" height={h} rx="3" fill="currentColor" />;
      })}
    </svg>
  );
}

export default function LoginPage() {
  const { login } = useAuth();

  return (
    <div className="grid min-h-svh w-full lg:grid-cols-2">
      {/* Left column: branding + sign-in */}
      <div className="flex flex-col bg-background p-8 md:p-12">
        {/* Logo */}
        <div className="flex items-center gap-2 font-medium">
          <div className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Mic className="size-4" aria-hidden="true" />
          </div>
          <span className="text-lg">LifeLog</span>
        </div>

        {/* Sign-in content — flows directly, no card wrapper */}
        <div className="flex flex-1 flex-col justify-center">
          <div className="max-w-sm space-y-6">
            <div className="space-y-3">
              <h1 className="text-4xl font-semibold tracking-tight">
                Your voice, remembered.
              </h1>
              <p className="text-base text-muted-foreground">
                Sign in to access your voice journal, recordings, and insights.
              </p>
            </div>

            <Button
              size="lg"
              variant="outline"
              className="w-full"
              onClick={login}
            >
              Sign in with OIDC
            </Button>

            <p className="text-xs text-muted-foreground">
              Your voice journal is private. All recordings are encrypted and
              accessible only to you.
            </p>
          </div>
        </div>
      </div>

      {/* Right column: audio wave hero */}
      <div className="relative hidden flex-col items-center justify-center bg-muted lg:flex">
        <div className="flex w-full flex-col items-center gap-6 p-12">
          <div className="flex size-16 items-center justify-center rounded-full bg-primary/10">
            <Mic className="size-8 text-primary" aria-hidden="true" />
          </div>
          <div className="w-full">
            <AudioWave />
          </div>
          <p className="text-sm text-muted-foreground text-center max-w-xs">
            Speak freely. LifeLog captures, transcribes, and organizes your conversations automatically.
          </p>
        </div>
      </div>
    </div>
  );
}
