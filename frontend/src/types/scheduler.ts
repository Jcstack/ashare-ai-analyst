/** Scheduler types for PRD v3.2 FR-SS002/SS004. */

export interface SchedulerStatus {
  current_profile: string
  override: string | null
  is_trading_day: boolean
  current_session: string
  is_holiday_period: boolean
  next_trading_day: string
}

export interface TaskConfig {
  name: string
  enabled: boolean
  description: string
}

export interface SchedulePlan {
  name: string
  label: string
  default_enabled: boolean
  tasks: TaskConfig[]
}

export interface SchedulePlansResult {
  plans: SchedulePlan[]
}

export interface CalendarDay {
  date: string
  is_trading_day: boolean
  is_weekend: boolean
  is_holiday: boolean
  day_of_week: number
}

export interface CalendarResult {
  days: CalendarDay[]
  today: string
  next_trading_day: string
}

export interface NotificationChannel {
  type: string
  enabled: boolean
  events: string[]
  webhook_url?: string
  bot_token?: string
  chat_id?: string
  secret?: string
  url?: string
  method?: string
  headers?: Record<string, string>
}

export interface SentinelConfig {
  data_sources: {
    global_markets?: { enabled: boolean; provider: string }
    news_platforms?: { enabled: boolean; platforms: string[]; refresh_interval: number }
    rss_feeds?: { enabled: boolean; feeds: { url: string; name: string; category: string }[]; max_age_days: number }
  }
  notifications: {
    channels: NotificationChannel[]
    event_types: string[]
  }
}
