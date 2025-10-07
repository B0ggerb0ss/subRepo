const { skeleton } = require('@skeletonlabs/tw-plugin');
const { leafGuardTheme } = require('./src/lib/themes/leafGuard.cjs');

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: ['src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {
      fontFamily: {
        display: ['"Space Grotesk"', 'system-ui', 'sans-serif'],
        body: ['"Inter"', 'system-ui', 'sans-serif']
      }
    }
  },
  plugins: [
    skeleton({
      themes: {
        preset: ['skeleton', 'modern', 'crimson'],
        custom: [leafGuardTheme]
      }
    })
  ]
};
