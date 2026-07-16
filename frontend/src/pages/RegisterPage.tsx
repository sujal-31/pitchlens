import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

export default function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [errors, setErrors] = useState<{ email?: string; password?: string; confirmPassword?: string; general?: string }>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const errs: typeof errors = {};
    if (!email) errs.email = 'Email is required';
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) errs.email = 'Invalid email';
    if (!password) errs.password = 'Password is required';
    else if (password.length < 8) errs.password = 'At least 8 characters';
    if (!confirmPassword) errs.confirmPassword = 'Please confirm password';
    else if (password !== confirmPassword) errs.confirmPassword = 'Passwords do not match';
    if (Object.keys(errs).length) { setErrors(errs); return; }

    setErrors({});
    setIsSubmitting(true);
    const result = await register(email, password);
    setIsSubmitting(false);
    if (result.success) navigate('/upload');
    else setErrors({ general: result.error });
  }

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4 py-12">
      <div className="w-full max-w-[380px] animate-in">
        <div className="mb-8 text-center">
          <h1 className="text-xl font-semibold tracking-tight">Create your account</h1>
          <p className="mt-1.5 text-sm text-zinc-500 dark:text-zinc-400">Start analyzing pitch decks</p>
        </div>

        <div className="surface-elevated p-6">
          {errors.general && (
            <div className="mb-4 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 px-3 py-2.5" role="alert">
              <p className="text-[13px] text-red-700 dark:text-red-300">{errors.general}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            <div>
              <label htmlFor="email" className="mb-1.5 block text-[13px] font-medium text-zinc-700 dark:text-zinc-300">Email</label>
              <input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                className="input-field" placeholder="name@company.com" autoComplete="email"
                aria-invalid={!!errors.email} />
              {errors.email && <p className="mt-1.5 text-[12px] text-red-600 dark:text-red-400">{errors.email}</p>}
            </div>
            <div>
              <label htmlFor="password" className="mb-1.5 block text-[13px] font-medium text-zinc-700 dark:text-zinc-300">Password</label>
              <input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                className="input-field" placeholder="••••••••" autoComplete="new-password"
                aria-invalid={!!errors.password} />
              {errors.password && <p className="mt-1.5 text-[12px] text-red-600 dark:text-red-400">{errors.password}</p>}
            </div>
            <div>
              <label htmlFor="confirm-password" className="mb-1.5 block text-[13px] font-medium text-zinc-700 dark:text-zinc-300">Confirm password</label>
              <input id="confirm-password" type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)}
                className="input-field" placeholder="••••••••" autoComplete="new-password"
                aria-invalid={!!errors.confirmPassword} />
              {errors.confirmPassword && <p className="mt-1.5 text-[12px] text-red-600 dark:text-red-400">{errors.confirmPassword}</p>}
            </div>
            <button type="submit" disabled={isSubmitting} className="btn-primary w-full min-h-[40px]">
              {isSubmitting ? <><span className="spinner" /> Creating…</> : 'Create account'}
            </button>
          </form>
        </div>

        <p className="mt-5 text-center text-[13px] text-zinc-500 dark:text-zinc-400">
          Already have an account?{' '}
          <Link to="/login" className="font-medium text-zinc-900 dark:text-zinc-100 hover:underline">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
