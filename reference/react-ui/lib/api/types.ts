export type Status = 'on_target' | 'drifting' | 'needs_review' | 'onboarding'
export type AccountType = 'individual' | 'joint' | 'trust' | 'ira' | 'roth_ira'
export type EventType = 'transition' | 'rebalance' | 'tax_loss_harvest' | 'cash_flow' | 'model_change'

export interface User { id: string; name: string; email: string }
export interface LoginResponse { access_token: string; user: User }
export interface BookSummary {
  clients: number; accounts: number; aum: number; taxes_saved_ytd: number
  taxes_saved_since_inception: number; drifting_accounts: number; average_te: number
}
export interface Client {
  id: string; name: string; email: string; client_type: 'individual' | 'joint' | 'trust'
  account_count: number; market_value: number; target_models: string[]; tracking_error: number
  taxes_saved_ytd: number; last_rebalance: string | null; status: Status; onboarding_date: string
  tax_profile: { federal_st_rate: number; federal_lt_rate: number; state: string; state_rate: number }
}
export interface Account { id: string; client_id: string; account_type: AccountType; custodian: string; nickname?: string; market_value: number; unrealized_gain: number; target_model_id?: string; tracking_error: number }
export interface AnalyticsPoint { date: string; value: number; lower?: number; upper?: number; data_source?: 'mock_random' | 'live' }
export interface AnalyticsSeries { data_source: 'mock_random' | 'live'; points: AnalyticsPoint[] }
export interface ManagementEvent { id: string; type: EventType; date: string; account_id: string; trigger: string; trades: number; turnover: number; realized_st_gain: number; realized_lt_gain: number; losses_harvested: number; taxes_saved: number; te_before: number; te_after: number; note: string }
export interface Model { id: string; name: string; objective: 'income' | 'total_return'; construction: string; fee: number; holdings: number }
export interface ChatTurn { state: string; assistant_message: string; quick_replies: { id: string; label: string }[]; ui_payload: { type: string; data: Record<string, unknown> }; allowed_actions: string[]; progress: { step: number; total: number; label: string } }
export interface Transition { id: string; client_id: string; account_id: string; state: string; turns: ChatTurn[] }
