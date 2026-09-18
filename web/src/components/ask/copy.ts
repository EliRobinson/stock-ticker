// Every user-facing string in the Ask panel, in one place for review.
// Chrome copy: the fact, then the consequence, then the action (AGENTS.md).

export const askCopy = {
  title: 'Ask',
  subtitle: 'Direct database access',
  working: 'working…',
  close: 'Close Ask',
  intro: 'Questions run against the local database. Answers show their SQL.',
  suggestions: [
    'Which companies fell most when COVID struck (Feb 19 – Mar 23, 2020)?',
    'Top 10 Companies by Market Cap, 2020–2021',
    'Which of my Notes sit within 5 days of an 8-K?',
    'Show AAPL and MSFT adjusted close, indexed to Jan 2020'
  ],
  inputLabel: 'Ask a question',
  placeholder: 'Ask about the database…',
  placeholderDisabled: 'Input disabled',
  hint: 'Enter sends · Shift+Enter newline',
  disclosure:
    'Your questions, and the data used to answer them, including your Notes, are sent to Anthropic.',
  send: 'Send',
  stop: 'Stop',
  showSql: 'Show SQL',
  hideSql: 'Hide SQL',
  pin: 'Pin result',
  pinLater: 'Pinning lands later',
  toolLog: 'Query steps',
  rows: (n: number, capped: boolean) =>
    `${capped ? 'over ' : ''}${n.toLocaleString('en-US')} ${n === 1 ? 'row' : 'rows'}`,
  quietStep: {
    show_table: 'Built the table',
    show_chart: 'Built the chart'
  } as Record<string, string>,
  stepRunning: 'running',
  stepDone: 'done',
  stepFailed: 'failed',
  retry: 'Retry',
  errors: {
    'backend-down':
      'The answer could not be generated. The AI service is unreachable. Try the question again.',
    'query-failed':
      'The answer could not be generated. The query failed against the database. Try rephrasing the question.'
  },
  missingKeyTitle: 'AI answers are unavailable',
  missingKeyBody:
    'No AI API key is configured. Set the key and restart the app.',
  spendTitle: 'AI answers are paused',
  spendBody: (limit: string) =>
    `AI spend limit reached (${limit}). Raise AI_SPEND_LIMIT_USD to continue.`,
  otherScreensWork:
    'Market, Company and Notes keep working. Only this panel is out.',
  tableFallback: 'Result'
} as const
