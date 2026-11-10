import type { Account, BookSummary, Client, LoginResponse, Model, AnalyticsSeries } from '@/lib/api/types'
import { mockAccounts, mockClients, mockModels, mockSummary, mockTaxImpact, mockTrackingError } from '@/lib/mock/data'

const useMocks = process.env.NEXT_PUBLIC_USE_MOCKS !== 'false'
const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? '/api/v1'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = typeof window !== 'undefined' ? sessionStorage.getItem('transition_token') : null
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init?.headers } })
  if (!response.ok) throw new Error('Request failed')
  return response.json()
}

export const api = {
  async login(email: string, password: string): Promise<LoginResponse> {
    if (useMocks) {
      if (email !== 'demo@advisor.test' || password !== 'demo1234') throw new Error('Invalid email or password')
      return { access_token: 'mock-advisor-token', user: { id: 'usr-001', name: 'Alex Morgan', email } }
    }
    return request<LoginResponse>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
  },
  getBookSummary: () => useMocks ? Promise.resolve(mockSummary) : request<BookSummary>('/book/summary'),
  getClients: () => useMocks ? Promise.resolve(mockClients) : request<Client[]>('/clients'),
  getAccounts: (clientId: string) => useMocks ? Promise.resolve(mockAccounts.filter((account) => account.client_id === clientId)) : request<Account[]>(`/clients/${clientId}/accounts`),
  getModels: () => useMocks ? Promise.resolve(mockModels) : request<Model[]>('/models'),
  getTrackingError: () => useMocks ? Promise.resolve(mockTrackingError) : request<AnalyticsSeries>('/book/analytics/tracking-error?window=63'),
  getTaxImpact: () => useMocks ? Promise.resolve(mockTaxImpact) : request<AnalyticsSeries>('/book/analytics/tax-impact?granularity=month'),
}
