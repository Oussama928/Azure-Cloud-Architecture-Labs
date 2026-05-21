module.exports = [
  {
    ignores: ['dist', 'node_modules', 'build'],
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      parser: require('@typescript-eslint/parser'),
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
      },
      globals: {
        browser: true,
        es2020: true,
        React: 'writable',
      },
    },
    settings: {
      react: { version: '18.2' },
    },
    plugins: {
      '@typescript-eslint': require('@typescript-eslint/eslint-plugin'),
      'react-hooks': require('eslint-plugin-react-hooks'),
    },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
      'no-unused-vars': 'off',
    },
  },
];
