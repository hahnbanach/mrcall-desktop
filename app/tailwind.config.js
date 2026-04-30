/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/renderer/index.html', './src/renderer/src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        'brand-blue':       '#0068FF',
        'brand-black':      '#0F110C',
        'brand-orange':     '#F7941F',
        'brand-light-grey': '#F1F3F7',
        'brand-mid-grey':   '#D7DCE2',
        'brand-grey-80':    '#3F413D',
        'brand-danger':     '#C52233',
      },
      fontFamily: {
        sans:  ['Montserrat', 'system-ui', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'sans-serif'],
        serif: ['"Noto Serif Display"', 'Georgia', 'serif'],
      },
      borderRadius: {
        'pill':    '33px',
        'pill-sm': '22px',
      },
      transitionDuration: {
        DEFAULT: '300ms',
      },
    },
  },
  plugins: [],
}
