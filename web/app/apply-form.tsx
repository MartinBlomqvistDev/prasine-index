'use client'

import { useForm, ValidationError } from '@formspree/react'

export default function ApplyForm() {
  const [state, handleSubmit] = useForm('xjgqgwqd')

  if (state.succeeded) {
    return (
      <p className="apply-thanks">
        Got it — I&apos;ll be in touch.
      </p>
    )
  }

  return (
    <form className="apply-form" onSubmit={handleSubmit}>
      <div className="form-row">
        <label className="form-label" htmlFor="name">Name</label>
        <input className="form-input" type="text" id="name" name="name" required />
        <ValidationError field="name" errors={state.errors} />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="email">Email</label>
        <input className="form-input" type="email" id="email" name="email" required />
        <ValidationError field="email" errors={state.errors} />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="claim-url">Company or claim URL</label>
        <input className="form-input" type="url" id="claim-url" name="claim_url" placeholder="https://www.company.com/sustainability/" />
        <ValidationError field="claim_url" errors={state.errors} />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="context">What should I assess?</label>
        <textarea className="form-textarea" id="context" name="context" rows={4} />
        <ValidationError field="context" errors={state.errors} />
      </div>
      <button className="form-submit" type="submit" disabled={state.submitting}>
        {state.submitting ? 'Sending…' : 'Send'}
      </button>
    </form>
  )
}
