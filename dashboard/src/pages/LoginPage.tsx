import { Mic } from 'lucide-react';
import { useAuth } from '../auth/AuthContext';
import { Button } from '@/components/ui/button';

function AudioWave() {
  // Speech waveform: never goes to silence — continuous noise floor with peaks
  const heights = [
    // 0 silence at very start
    0, 0, 0, 0, 0, 0, 0,
    // 1 rise into first peak
    3, 8, 18, 32, 50, 68, 82,
    // 2 first peak (jagged top)
    95, 88, 100, 90, 78, 95, 82, 70, 92, 75, 60,
    // 3 decay but STAY above noise floor — rising into second peak
    40, 30, 42, 35, 52, 48, 65, 58, 75, 68, 85,
    // 4 second peak (higher, sustained)
    100, 92, 98, 100, 95, 88, 100, 97, 90, 85, 95, 80, 70,
    // 5 drop to noise floor, then buildup to third
    45, 38, 50, 55, 65, 75, 88, 78,
    // 6 third peak (sharp attack)
    100, 85, 95, 70, 55, 88, 65, 45,
    // 7 decay toward end
    30, 20, 12, 8, 5, 2, 0, 0, 0, 0, 0,
  ];
  const positions = heights.map((_, i) => 8 + i * 8);

  return (
    <svg
      viewBox={`0 0 ${positions[positions.length - 1] + 8} 100`}
      className="h-full w-full text-primary/40"
      aria-hidden="true"
      preserveAspectRatio="none"
    >
      {/* Center line over active region */}
      <line x1={positions[7]} y1="50" x2={positions[positions.length - 5]} y2="50" stroke="currentColor" strokeWidth="1" strokeDasharray="4 4" />
      <g>
        {positions.map((x, i) => {
          const envelope = heights[i] / 100;
          if (envelope < 0.03) return null;
          const noise = 0.88 + Math.random() * 0.24;
          const h = envelope * 44 * noise;
          return <rect key={`u${x}`} x={x} y={50 - h} width="6" height={h} rx="3" fill="currentColor" />;
        })}
      </g>
      <g>
        {positions.map((x, i) => {
          const envelope = heights[i] / 100;
          if (envelope < 0.03) return null;
          const noise = 0.88 + Math.random() * 0.24;
          const h = envelope * 44 * noise;
          return <rect key={`d${x}`} x={x} y={50} width="6" height={h} rx="3" fill="currentColor" />;
        })}
      </g>
    </svg>
  );
}

export default function LoginPage() {
  const { login } = useAuth();

  return (
    <div className="flex flex-col lg:grid lg:grid-cols-2 min-h-svh">
      {/* Left: text with logo */}
      <div className="order-2 lg:order-none flex items-center justify-center bg-background p-8 lg:min-h-svh">
        <div className="flex w-full max-w-sm flex-col gap-8">
          {/* Logo */}
          <div className="flex items-center gap-2 font-medium">
            <div className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <Mic className="size-4" aria-hidden="true" />
            </div>
            <span className="text-lg">LifeLog</span>
          </div>

          {/* CTA block */}
          <div className="space-y-6">
            <div className="space-y-3">
              <h1 className="text-4xl font-semibold tracking-tight">
                Your voice, remembered.
              </h1>
              <p className="text-base text-muted-foreground">
                Sign in to access your voice journal, recordings, and insights.
              </p>
            </div>

            <Button
              id="sign-in-button"
              size="lg"
              variant="default"
              className="w-full"
              style={{
                backgroundColor: 'hsl(221.2, 83.2%, 53.3%)',
                color: 'hsl(0, 0%, 98%)',
                border: 'none',
              }}
              onClick={login}
            >
              Sign in with OIDC
            </Button>

            <p className="text-xs text-foreground">
              Your voice journal is private. All recordings are encrypted and
              accessible only to you.
            </p>
          </div>
        </div>
      </div>

      {/* Right: waveform */}
      <div className="order-1 lg:order-none flex items-center justify-center bg-muted p-8 lg:min-h-svh">
        <div className="flex h-40 w-full max-w-sm items-center">
          <AudioWave />
        </div>
      </div>
    </div>
  );
}
