import { Link } from 'react-router-dom'
import { Wordmark } from './ui.jsx'

export default function AuthLayout({ title, intro, aside, width = 'max-w-md', children }) {
  return (
    <div className="min-h-dvh">
      <header className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-5 sm:px-6">
        <Link to="/login" aria-label="Bari Khujun home">
          <Wordmark className="h-14" />
        </Link>
        {aside && <p className="text-sm text-ink-soft">{aside}</p>}
      </header>
      <main className={`mx-auto ${width} px-4 pb-16 pt-6 sm:pt-12`}>
        <h1 className="font-display text-4xl font-extrabold uppercase leading-none tracking-wide sm:text-5xl">
          {title}
        </h1>
        {intro && <p className="mt-3 text-ink-soft">{intro}</p>}
        <div className="mt-8 rounded-xl border border-rule bg-sheet p-5 shadow-sm sm:p-7">{children}</div>
      </main>
    </div>
  )
}
