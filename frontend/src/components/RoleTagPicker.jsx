import { ROLES, SELF_REGISTER_ROLES } from '../constants/roles.js'
import KeyTag from './KeyTag.jsx'

// Unselected tags hang slightly crooked; the chosen one drops, swings and settles straight.
const REST_TILT = ['-rotate-2', 'rotate-1', '-rotate-1', 'rotate-2']

export default function RoleTagPicker({ value, onChange }) {
  return (
    <fieldset>
      <legend className="mb-3 text-sm font-medium">I'm joining as</legend>
      <div className="relative">
        <div aria-hidden="true" className="absolute inset-x-0 top-0 h-0.5 rounded-full bg-leaf" />
        <div className="grid grid-cols-4 items-start gap-2 sm:gap-3">
          {SELF_REGISTER_ROLES.map((role, index) => {
            const active = role === value
            return (
              <label key={role} className="group flex cursor-pointer flex-col items-center">
                <input
                  type="radio"
                  name="role"
                  value={role}
                  checked={active}
                  onChange={() => onChange(role)}
                  className="peer sr-only"
                />
                <span
                  aria-hidden="true"
                  className={`block w-px bg-leaf transition-[height] duration-300 ${active ? 'h-6' : 'h-3'}`}
                />
                <KeyTag
                  role={role}
                  active={active}
                  className={`w-full transition-[rotate,background-color,color] duration-200 peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-leaf ${
                    active ? 'animate-tag-swing rotate-0 shadow-md' : `${REST_TILT[index]} group-hover:rotate-0`
                  }`}
                />
              </label>
            )
          })}
        </div>
      </div>
      <p className="mt-3 min-h-10 text-sm text-ink-soft" aria-live="polite">
        {value ? ROLES[value].blurb : 'Pick the one that fits. Each account holds one role.'}
      </p>
    </fieldset>
  )
}
