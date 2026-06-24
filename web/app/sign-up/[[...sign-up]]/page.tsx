import { SignUp } from '@clerk/nextjs'

export default function SignUpPage() {
  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--surface)',
    }}>
      <SignUp
        appearance={{
          elements: {
            rootBox: { margin: '0 auto' },
            card: { borderRadius: 0, boxShadow: 'none', border: '1px solid var(--border)' },
          },
        }}
      />
    </div>
  )
}
