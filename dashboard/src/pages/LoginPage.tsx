import { Mic } from 'lucide-react';
import { useAuth } from '../auth/AuthContext';
import { Button } from '../components/ui/button';

export default function LoginPage() {
  const { login } = useAuth();

  return (
    <div className="grid min-h-svh w-full lg:grid-cols-2">
      {/* Left column: branding + OAuth button */}
      <div className="flex flex-col gap-6 p-8 md:p-10">
        <div className="flex items-center gap-2 font-medium">
          <div className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Mic className="size-4" aria-hidden="true" />
          </div>
          <span className="text-lg">LifeLog</span>
        </div>

        <div className="flex flex-1 items-center justify-center">
          <div className="w-full max-w-sm space-y-8">
            <div className="space-y-2">
              <h1 className="text-3xl font-semibold tracking-tight">
                Your voice, remembered.
              </h1>
              <p className="text-sm text-muted-foreground">
                Sign in to access your voice journal, recordings, and insights.
              </p>
            </div>

            <Button
              size="lg"
              className="w-full"
              onClick={login}
            >
              Sign in with OIDC
            </Button>

            <p className="text-xs text-muted-foreground text-center">
              Your voice journal is private. All recordings are encrypted and
              accessible only to you.
            </p>
          </div>
        </div>
      </div>

      {/* Right column: hero panel — reserved for future marketing image */}
      <div className="relative hidden bg-muted lg:block">
        {/* Empty — a marketing hero image goes here */}
        <div className="absolute inset-0 flex items-center justify-center">
          <p className="text-sm text-muted-foreground italic">
            Hero image coming soon
          </p>
        </div>
      </div>
    </div>
  );
}
