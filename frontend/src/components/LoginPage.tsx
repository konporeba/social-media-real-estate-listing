import { useRef, useState, useEffect, KeyboardEvent, ClipboardEvent } from 'react';
import { api } from '../lib/api';
import { useAppStore } from '../store';

const PIN_LENGTH = 6;

function ShieldIcon() {
  return (
    <svg className="w-7 h-7 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
    </svg>
  );
}

function BoltIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
    </svg>
  );
}

export default function LoginPage() {
  const [digits, setDigits] = useState<string[]>(Array(PIN_LENGTH).fill(''));
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [shake, setShake] = useState(false);
  const inputs = useRef<(HTMLInputElement | null)[]>([]);
  const setAuth = useAppStore((s) => s.setAuth);

  useEffect(() => {
    inputs.current[0]?.focus();
  }, []);

  const submit = async (pin: string) => {
    if (loading) return;
    setLoading(true);
    setError('');
    try {
      const { token, role } = await api.login(pin);
      setAuth(token, role);
    } catch {
      setShake(true);
      setError('Incorrect access code. Please try again.');
      setDigits(Array(PIN_LENGTH).fill(''));
      setTimeout(() => {
        setShake(false);
        inputs.current[0]?.focus();
      }, 420);
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (index: number, value: string) => {
    const digit = value.replace(/\D/g, '').slice(-1);
    const newDigits = [...digits];
    newDigits[index] = digit;
    setDigits(newDigits);
    if (error) setError('');

    if (digit && index < PIN_LENGTH - 1) {
      inputs.current[index + 1]?.focus();
    }
    if (newDigits.every((d) => d !== '')) {
      submit(newDigits.join(''));
    }
  };

  const handleKeyDown = (index: number, e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace') {
      if (digits[index]) {
        const newDigits = [...digits];
        newDigits[index] = '';
        setDigits(newDigits);
      } else if (index > 0) {
        inputs.current[index - 1]?.focus();
        const newDigits = [...digits];
        newDigits[index - 1] = '';
        setDigits(newDigits);
      }
    } else if (e.key === 'ArrowLeft' && index > 0) {
      inputs.current[index - 1]?.focus();
    } else if (e.key === 'ArrowRight' && index < PIN_LENGTH - 1) {
      inputs.current[index + 1]?.focus();
    }
  };

  const handlePaste = (e: ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault();
    const text = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, PIN_LENGTH);
    if (!text) return;
    const newDigits = Array(PIN_LENGTH).fill('');
    for (let i = 0; i < text.length; i++) newDigits[i] = text[i];
    setDigits(newDigits);
    const lastFilledIndex = Math.min(text.length, PIN_LENGTH - 1);
    inputs.current[lastFilledIndex]?.focus();
    if (text.length === PIN_LENGTH) submit(text);
  };

  const filledCount = digits.filter((d) => d !== '').length;

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50 dark:bg-gray-950 px-4 relative overflow-hidden">

      {/* Ambient glow */}
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[700px] h-[500px] bg-blue-500/6 dark:bg-blue-500/10 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 right-1/4 w-[300px] h-[300px] bg-indigo-500/4 dark:bg-indigo-500/8 rounded-full blur-3xl" />
      </div>

      <div className="relative w-full max-w-sm animate-slide-up">

        {/* Brand mark above the card */}
        <div className="flex items-center justify-center gap-2 mb-6">
          <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center shadow-lg shadow-blue-900/30">
            <BoltIcon />
          </div>
          <span className="text-sm font-semibold text-gray-500 dark:text-gray-400 tracking-wide">DP Real Estate</span>
        </div>

        {/* Card */}
        <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700/60 shadow-2xl shadow-black/5 dark:shadow-black/50 overflow-hidden">

          {/* Card header */}
          <div className="bg-gradient-to-br from-blue-600 to-blue-800 px-8 pt-8 pb-10 text-center relative">
            <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(255,255,255,0.08),transparent)]" />
            <div className="relative">
              <div className="w-14 h-14 rounded-2xl bg-white/15 border border-white/20 flex items-center justify-center mx-auto mb-4 shadow-xl">
                <ShieldIcon />
              </div>
              <h1 className="text-xl font-bold text-white tracking-tight">Secure Access</h1>
              <p className="text-blue-200 text-xs mt-1.5 leading-relaxed">
                Real Estate Agent · Automated Publishing
              </p>
            </div>
          </div>

          {/* Card body */}
          <div className="px-8 py-7">

            <p className="text-center text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Enter your access code
            </p>
            <p className="text-center text-xs text-gray-400 dark:text-gray-500 mb-7">
              Type your 6-digit PIN to access the workspace
            </p>

            {/* PIN digit boxes */}
            <div className={`flex gap-2.5 justify-center mb-6 ${shake ? 'animate-shake' : ''}`}>
              {Array.from({ length: PIN_LENGTH }).map((_, i) => (
                <input
                  key={i}
                  ref={(el) => { inputs.current[i] = el; }}
                  type="password"
                  inputMode="numeric"
                  pattern="\d*"
                  maxLength={1}
                  value={digits[i]}
                  onChange={(e) => handleChange(i, e.target.value)}
                  onKeyDown={(e) => handleKeyDown(i, e)}
                  onPaste={handlePaste}
                  disabled={loading}
                  aria-label={`PIN digit ${i + 1}`}
                  className={[
                    'w-10 text-center text-lg font-bold rounded-xl border-2',
                    'transition-all duration-150 select-none',
                    'bg-gray-50 dark:bg-gray-800',
                    'text-gray-900 dark:text-gray-100',
                    'focus:outline-none focus:scale-105',
                    'disabled:opacity-40 disabled:cursor-not-allowed',
                    error
                      ? 'border-red-400 dark:border-red-500/80 bg-red-50/50 dark:bg-red-900/10'
                      : digits[i]
                      ? 'border-blue-500 dark:border-blue-400 shadow-sm shadow-blue-500/20'
                      : 'border-gray-200 dark:border-gray-700 focus:border-blue-500 dark:focus:border-blue-400',
                  ].join(' ')}
                  style={{ height: '52px' }}
                />
              ))}
            </div>

            {/* Progress dots */}
            <div className="flex justify-center gap-1.5 mb-5">
              {Array.from({ length: PIN_LENGTH }).map((_, i) => (
                <div
                  key={i}
                  className={`w-1.5 h-1.5 rounded-full transition-all duration-200 ${
                    i < filledCount
                      ? 'bg-blue-500 scale-110'
                      : 'bg-gray-200 dark:bg-gray-700'
                  }`}
                />
              ))}
            </div>

            {/* Error message */}
            <div className="h-5 flex items-center justify-center mb-4">
              {error && (
                <p className="text-xs text-red-500 dark:text-red-400 text-center animate-fade-in">
                  {error}
                </p>
              )}
              {loading && !error && (
                <div className="flex items-center gap-2 text-xs text-gray-400 dark:text-gray-500 animate-fade-in">
                  <div className="w-3.5 h-3.5 border-2 border-blue-500/30 border-t-blue-500 rounded-full animate-spin" />
                  Verifying…
                </div>
              )}
            </div>

            {/* Security note */}
            <div className="flex items-center justify-center gap-1.5 text-[11px] text-gray-400 dark:text-gray-600">
              <svg className="w-3 h-3 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
              </svg>
              Access is encrypted and rate-limited
            </div>
          </div>
        </div>

        {/* Footer */}
        <p className="text-center text-[11px] text-gray-400 dark:text-gray-600 mt-5">
          © {new Date().getFullYear()} DP Real Estate &middot; All rights reserved
        </p>
      </div>
    </div>
  );
}
