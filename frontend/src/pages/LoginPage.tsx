import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

function validateEmail(email: string): string | null {
  if (!email) return 'Email is required';
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return 'Please enter a valid email address';
  return null;
}

function validatePassword(password: string): string | null {
  if (!password) return 'Password is required';
  if (password.length < 8) return 'Password must be at least 8 characters';
  return null;
}

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState<{ email?: string; password?: string; general?: string }>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const emailError = validateEmail(email);
    const passwordError = validatePassword(password);
    if (emailError || passwordError) {
      setErrors({ email: emailError ?? undefined, password: passwordError ?? undefined });
      return;
    }
    setErrors({});
    setIsSubmitting(true);
    const result = await login(email, password);
    setIsSubmitting(false);
    if (result.success) navigate('/upload');
    else setErrors({ general: result.error });
  }

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4 py-12">
      <div className="w-full max-w-[380px] animate-in">
        <div className="mb-8 text-center">
          <h1 className="text-xl font-semibold tracking-tight">Sign in to PitchLens</h1>
          <p className="mt-1.5 text-sm text-zinc-500 dark:text-zinc-400">
            Analyze pitch decks with AI-powered insights
          </p>
        </div>

        <div className="surface-elevated p-6">
          {errors.general && (
            <div className="mb-4 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 px-3 py-2.5" role="alert">
              <p className="text-[13px] text-red-700 dark:text-red-300">{errors.general}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            <div>
              <label htmlFor="email" className="mb-1.5 block text-[13px] font-medium text-zinc-700 dark:text-zinc-300">
                Email address
              </label>
              <input
                id="email" type="email" value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input-field" placeholder="name@company.com"
                autoComplete="email" aria-invalid={!!errors.email}
                aria-describedby={errors.email ? 'email-error' : undefined}
              />
              {errors.email && <p id="email-error" className="mt-1.5 text-[12px] text-red-600 dark:text-red-400">{errors.email}</p>}
            </div>

            <div>
              <label htmlFor="password" className="mb-1.5 block text-[13px] font-medium text-zinc-700 dark:text-zinc-300">
                Password
              </label>
              <input
                id="password" type="password" value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input-field" placeholder="••••••••"
                autoComplete="current-password" aria-invalid={!!errors.password}
                aria-describedby={errors.password ? 'password-error' : undefined}
              />
              {errors.password && <p id="password-error" className="mt-1.5 text-[12px] text-red-600 dark:text-red-400">{errors.password}</p>}
            </div>

            <button type="submit" disabled={isSubmitting} className="btn-primary w-full min-h-[40px]">
              {isSubmitting ? <><span className="spinner" /> Signing in…</> : 'Continue'}
            </button>
          </form>
        </div>

        <p className="mt-5 text-center text-[13px] text-zinc-500 dark:text-zinc-400">
          Don't have an account?{' '}
          <Link to="/register" className="font-medium text-zinc-900 dark:text-zinc-100 hover:underline">Sign up</Link>
        </p>
      </div>
    </div>
  );
}
