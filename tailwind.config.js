/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./apps/**/templates/**/*.html",
    "./apps/**/*.py",
    "./core/**/*.py",
    "./static/js/**/*.js",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans Arabic"', 'Cairo', 'Inter', 'system-ui', 'sans-serif'],
        display: ['"IBM Plex Sans Arabic"', 'Cairo', 'Inter', 'sans-serif'],
        royal: ['"IBM Plex Sans Arabic"', 'Cairo', 'Inter', 'sans-serif'],
        body: ['"IBM Plex Sans Arabic"', 'Cairo', 'Inter', 'sans-serif'],
      },
      colors: {
        paper: '#F8FAFC',
        'paper-soft': '#F1F5F9',
        card: '#FFFFFF',
        ink: '#0F172A',
        'ink-soft': '#475569',
        soft: '#64748B',
        line: '#E2E8F0',
        blue: {
          50: '#F5F3FF',   /* Luminous Muted Violet Surface */
          100: '#EDE9FE',  /* Active item background */
          200: '#DDD6FE',  /* Subtle boundary */
          300: '#C4B5FD',  /* Crisp active item border */
          400: '#A78BFA',  /* Muted accent */
          500: '#818CF8',  /* Accent */
          600: '#6366F1',  /* Primary CTA buttons & badges (Slate Violet) */
          700: '#4F46E5',  /* Hover buttons & prominent active links */
          800: '#3730A3',  /* Deep accent */
          900: '#312E81',  /* Deep violet */
          950: '#1E1B4B',  /* Ultra-deep violet text (AAA contrast) */
        },
        brand: {
          50: '#F5F3FF',
          100: '#EDE9FE',
          200: '#DDD6FE',
          300: '#C4B5FD',
          400: '#A78BFA',
          500: '#818CF8',
          600: '#6366F1',
          700: '#4F46E5',
          800: '#3730A3',
          900: '#312E81',
          950: '#1E1B4B',
        },
        good: {
          50: '#F0FDF4',
          100: '#DCFCE7',
          200: '#BBF7D0',
          600: '#16A34A',
          700: '#15803D',
        },
        warn: {
          50: '#FFFBEB',
          100: '#FEF3C7',
          200: '#FDE68A',
          600: '#D97706',
          700: '#B45309',
        },
        bad: {
          50: '#FEF2F2',
          100: '#FEE2E2',
          200: '#FECACA',
          600: '#DC2626',
          700: '#B91C1C',
        },
        info: {
          50: '#F0F9FF',
          100: '#E0F2FE',
          600: '#0284C7',
          700: '#0369A1',
        },
        gold: {
          400: '#E6C898',
          500: '#6366F1',
          600: '#4F46E5',
        }
      }
    }
  },
  plugins: [],
}
