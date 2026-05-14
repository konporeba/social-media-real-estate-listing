import { useEffect, useState } from 'react';

export function useTheme() {
  const [isDark, setIsDark] = useState(() => {
    const stored = localStorage.getItem('theme');
    if (stored) return stored === 'dark';
    return true; // default dark
  });

  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark);
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
  }, [isDark]);

  // Apply on first render synchronously
  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { isDark, toggle: () => setIsDark((d) => !d) };
}
