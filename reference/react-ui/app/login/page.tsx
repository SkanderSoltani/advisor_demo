'use client'

import { FormEvent, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { AlertCircle, ArrowRight, Check, Eye, EyeOff, LockKeyhole, Mail, ShieldCheck } from 'lucide-react'
import { api } from '@/lib/api/client'

export default function LoginPage() {
  const router = useRouter()
  const [email, setEmail] = useState('demo@advisor.test')
  const [password, setPassword] = useState('demo1234')
  const [remember, setRemember] = useState(true)
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => { if (sessionStorage.getItem('transition_token')) router.replace('/') }, [router])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    if (!email.trim() || !password) { setError('Enter your email and password to continue.'); return }
    setLoading(true)
    try {
      const result = await api.login(email.trim(), password)
      sessionStorage.setItem('transition_token', result.access_token)
      sessionStorage.setItem('transition_user', JSON.stringify(result.user))
      if (!remember) sessionStorage.setItem('transition_session_only', 'true')
      router.replace('/')
    } catch { setError('We couldn’t sign you in. Check your credentials and try again.') } finally { setLoading(false) }
  }

  return <main className="grid min-h-screen bg-surface-50 lg:grid-cols-[minmax(420px,0.9fr)_1.1fr]">
    <section className="flex items-center justify-center px-6 py-12 sm:px-12 lg:px-16"><div className="w-full max-w-[410px]"><div className="mb-12 flex items-center gap-3"><div className="flex h-9 items-center rounded-lg bg-white px-2"><img src="https://cdn.jsdelivr.net/gh/glincker/thesvg@main/public/icons/charles-schwab/default.svg" alt="Charles Schwab" className="h-5 w-auto" /></div><span className="font-semibold tracking-tight text-brand-navy">Transition Studio</span></div><div className="mb-8"><p className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-brand-primary-dark">Advisor workspace</p><h1 className="text-3xl font-semibold tracking-tight text-brand-navy">Welcome back</h1><p className="mt-3 text-sm leading-6 text-ink-600">Sign in to review client portfolios and guide their next transition.</p></div><form onSubmit={handleSubmit} noValidate className="flex flex-col gap-5"><label className="flex flex-col gap-2 text-sm font-medium text-brand-navy">Email address<div className="relative"><Mail className="pointer-events-none absolute left-3 top-3 text-ink-600" size={17} /><input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} className="h-11 w-full rounded-lg border border-ink-300 bg-white pl-10 pr-3 text-sm outline-none transition focus:border-brand-primary focus:ring-3 focus:ring-brand-primary/15" placeholder="you@firm.com" aria-label="Email address" /></div></label><label className="flex flex-col gap-2 text-sm font-medium text-brand-navy">Password<div className="relative"><LockKeyhole className="pointer-events-none absolute left-3 top-3 text-ink-600" size={17} /><input type={showPassword ? 'text' : 'password'} autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} className="h-11 w-full rounded-lg border border-ink-300 bg-white pl-10 pr-11 text-sm outline-none transition focus:border-brand-primary focus:ring-3 focus:ring-brand-primary/15" placeholder="Enter your password" aria-label="Password" /><button type="button" onClick={() => setShowPassword((visible) => !visible)} className="absolute right-3 top-2.5 text-ink-600 hover:text-brand-navy" aria-label={showPassword ? 'Hide password' : 'Show password'}>{showPassword ? <EyeOff size={18} /> : <Eye size={18} />}</button></div></label><div className="flex items-center justify-between"><label className="flex items-center gap-2 text-sm text-ink-600"><input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} className="size-4 accent-brand-primary" />Remember me</label><button type="button" className="text-sm font-medium text-brand-primary-dark hover:underline">Forgot password?</button></div>{error && <div role="alert" className="flex items-start gap-2 rounded-lg border border-negative/20 bg-negative/5 px-3 py-3 text-sm text-negative"><AlertCircle className="mt-0.5 shrink-0" size={16} /><span>{error}</span></div>}<button type="submit" disabled={loading} className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-brand-primary px-4 text-sm font-semibold text-brand-navy transition hover:bg-brand-primary-dark hover:text-white disabled:cursor-wait disabled:opacity-70">{loading ? <><span className="size-4 animate-spin rounded-full border-2 border-brand-navy/30 border-t-brand-navy" />Signing in…</> : <>Sign in <ArrowRight size={17} /></>}</button></form><div className="mt-8 rounded-lg border border-brand-primary/15 bg-brand-primary/5 p-4"><p className="text-xs font-semibold text-brand-navy">Demo access</p><p className="mt-1 text-xs leading-5 text-ink-600">Use <span className="font-medium text-brand-navy">demo@advisor.test</span> with password <span className="font-medium text-brand-navy">demo1234</span></p></div><p className="mt-8 text-center text-xs text-ink-600">Internal prototype · Synthetic data · Not for client use.</p></div></section>
    <section className="relative hidden overflow-hidden bg-brand-navy lg:flex lg:items-center lg:px-20 xl:px-28"><div className="absolute inset-0 opacity-20" style={{ backgroundImage: 'radial-gradient(circle at 80% 20%, rgba(0,160,223,.8), transparent 30%), radial-gradient(circle at 20% 80%, rgba(0,133,124,.45), transparent 26%)' }} /><svg className="absolute inset-0 h-full w-full opacity-30" viewBox="0 0 800 900" preserveAspectRatio="none" aria-hidden="true"><path d="M-20 660 C 110 600, 150 700, 260 570 S 420 360, 510 430 S 650 250, 840 300" fill="none" stroke="#7FCFEF" strokeWidth="2" /><path d="M-20 730 C 120 690, 180 760, 310 650 S 440 500, 540 540 S 680 400, 840 450" fill="none" stroke="#fff" strokeDasharray="4 9" strokeWidth="1" /><path d="M-20 660 C 110 600, 150 700, 260 570 S 420 360, 510 430 S 650 250, 840 300 L 840 900 L -20 900 Z" fill="#00A0DF" opacity=".08" /></svg><div className="relative max-w-xl"><div className="mb-8 flex size-14 items-center justify-center rounded-2xl border border-white/15 bg-white/10"><ShieldCheck className="text-brand-primary" size={28} /></div><p className="mb-6 text-sm font-medium uppercase tracking-[0.18em] text-brand-primary">Precision for every transition</p><h2 className="max-w-lg text-5xl font-semibold leading-[1.08] tracking-[-0.04em] text-white">Transition client portfolios with precision.</h2><p className="mt-6 max-w-md text-xl leading-8 text-white/65">Minimize tracking error, control taxes, and make every recommendation easier to explain.</p><div className="mt-12 flex items-center gap-6 text-sm text-white/65"><span className="flex items-center gap-2"><Check className="text-brand-primary" size={16} />Tax-aware</span><span className="flex items-center gap-2"><Check className="text-brand-primary" size={16} />Advisor-led</span><span className="flex items-center gap-2"><Check className="text-brand-primary" size={16} />Transparent</span></div></div></section>
  </main>
}
