import prettierConfig from 'eslint-config-prettier'
import nextCoreWebVitals from 'eslint-config-next/core-web-vitals'
import nextTypeScript from 'eslint-config-next/typescript'
import neostandard from 'neostandard'

/** @type {import("eslint").Linter.Config[]} */
const eslintConfig = [
  {
    ignores: [
      'next-env.d.ts',
      '.next/**',
      'node_modules/**',
      'out/**',
      'build/**',
      'dist/**',
      'coverage/**'
    ]
  },
  // Standard JS style rules, deferring formatting to Prettier.
  // TypeScript linting is left to next/typescript below - neostandard's
  // own `ts: true` registers a second @typescript-eslint plugin instance
  // that conflicts with the one next/typescript registers.
  ...neostandard({ noStyle: true }),
  ...nextCoreWebVitals,
  ...nextTypeScript,
  {
    rules: {
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }
      ],
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/consistent-type-imports': [
        'error',
        { prefer: 'type-imports' }
      ],
      'no-console': ['error', { allow: ['warn', 'error'] }]
    }
  },
  // Prettier must be last to disable conflicting formatting rules
  prettierConfig
]

export default eslintConfig
