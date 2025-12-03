/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'zylch': {
          'primary': '#1a1a1a',
          'muted': '#888888',
          'link': '#666666',
          'accent': '#4a9eff',
          'bg': '#ffffff',
        }
      },
      fontFamily: {
        'sans': ['Inter', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
      },
      borderRadius: {
        'zylch': '24px',
        'zylch-sm': '12px',
      },
      boxShadow: {
        'zylch': '0 2px 8px rgba(0,0,0,0.08)',
        'zylch-lg': '0 8px 32px rgba(0,0,0,0.12)',
      }
    },
  },
  plugins: [],
}
