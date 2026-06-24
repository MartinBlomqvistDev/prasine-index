import { SignIn } from '@clerk/nextjs'

export default function SignInPage() {
  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--surface)',
    }}>
      <div style={{ textAlign: 'center', marginBottom: 32 }}>
        <SignIn
          appearance={{
            elements: {
              rootBox: { margin: '0 auto' },
              card: { borderRadius: 0, boxShadow: 'none', border: '1px solid var(--border)' },
            },
          }}
        />
      </div>
    </div>
  )
}
