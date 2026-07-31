import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        paper: '#F5F2EA',
        ink: '#17211B',
        pine: {
          50: '#EEF7F2',
          100: '#DCEEE4',
          500: '#2C7A57',
          600: '#216246',
          700: '#174934',
          900: '#102B20'
        },
        amber: {
          50: '#FFF8E7',
          100: '#FDEFC5',
          500: '#C77A12',
          600: '#A65F08'
        }
      },
      boxShadow: {
        card: '0 1px 2px rgba(23,33,27,.05), 0 12px 40px rgba(23,33,27,.05)',
        drawer: '-16px 0 48px rgba(23,33,27,.16)'
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'PingFang SC', 'Microsoft YaHei', 'sans-serif'],
        display: ['STSong', 'Songti SC', 'Noto Serif CJK SC', 'serif']
      },
      animation: {
        'progress-stripe': 'progress-stripe 1.2s linear infinite',
        'fade-in': 'fade-in .2s ease-out'
      },
      keyframes: {
        'progress-stripe': { to: { backgroundPosition: '24px 0' } },
        'fade-in': { from: { opacity: '0', transform: 'translateY(4px)' }, to: { opacity: '1', transform: 'translateY(0)' } }
      }
    }
  },
  plugins: []
} satisfies Config;
