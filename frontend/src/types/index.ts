// User & Auth Types
export interface User {
  id: string
  uid?: string
  email: string
  name: string
  displayName?: string | null
  picture?: string
  photoURL?: string | null
  emailVerified?: boolean
  provider?: 'google' | 'microsoft'
}

export interface AuthState {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  isLoading: boolean
  error: string | null
}

// Email Types
export interface EmailThread {
  id: string
  threadId: string
  subject: string
  snippet: string
  participants: string[]
  lastMessageDate: string
  messageCount: number
  isUnread?: boolean
  unread?: boolean  // alias for compatibility
  labels: string[]
  messages?: EmailMessage[]  // populated when fetching full thread
}

export interface EmailMessage {
  id: string
  threadId: string
  from: string
  to: string[]
  cc: string[]
  subject: string
  body: string
  bodyHtml: string
  date: string
  attachments: Attachment[]
}

export interface Attachment {
  id: string
  filename: string
  mimeType: string
  size: number
}

export interface Draft {
  id: string
  threadId: string | null
  to: string[]
  cc: string[]
  subject: string
  body: string
  createdAt: string
  updatedAt: string
}

// Task Types
export interface Task {
  id: string
  title?: string
  description?: string
  contactEmail?: string
  contactName?: string
  summary?: string
  status: 'pending' | 'in_progress' | 'completed' | 'open' | 'waiting' | 'closed'
  priority: 'high' | 'medium' | 'low'
  person?: string
  dueDate?: string
  completedAt?: string
  threads?: TaskThread[]
  lastUpdated?: string
  actionRequired?: string | null
}

export interface TaskThread {
  threadId: string
  subject: string
  lastMessageDate: string
  snippet: string
}

// Calendar Types
export interface CalendarEvent {
  id: string
  summary: string
  description: string | null
  start: string
  end: string
  location: string | null
  attendees: Attendee[]
  meetLink: string | null
  isAllDay: boolean
}

export interface Attendee {
  email: string
  displayName: string | null
  responseStatus: 'needsAction' | 'declined' | 'tentative' | 'accepted'
}

// Contact Types
export interface Contact {
  id: string
  email: string
  name: string
  company?: string | null
  phone?: string | null
  notes?: string | null
  source?: 'gmail' | 'starchat' | 'pipedrive' | 'manual'
  enrichmentData?: Record<string, any> | null
  lastInteraction?: string | null
  lastContact?: string | null
  relationshipGap?: number  // days since last contact
}

// Memory Types
export interface Memory {
  id: string
  type: 'personal' | 'global'
  rule: string
  context: string | null
  confidence: number
  usageCount: number
  lastUsed: string | null
  createdAt: string
}

export interface MemoryStats {
  totalMemories: number
  personalMemories: number
  globalMemories: number
  averageConfidence: number
}

// Trigger Types
export interface Trigger {
  id: string
  type: string
  condition: string
  action: string
  isActive: boolean
  lastTriggered: string | null
  createdAt: string
}

// Cache Types
export interface CacheStats {
  emails: CacheInfo
  calendar: CacheInfo
  gaps: CacheInfo
  tasks: CacheInfo
}

export interface CacheInfo {
  count: number
  sizeBytes: number
  lastUpdated: string | null
}

// Sharing Types
export interface ShareAuthorization {
  id: string
  recipientEmail: string
  permissions: SharePermission[]
  createdAt: string
  expiresAt: string | null
}

export type SharePermission = 'read_emails' | 'read_tasks' | 'read_calendar' | 'write_drafts'

// MrCall Types
export interface MrCallAssistant {
  id: string
  name: string
  phone: string
  status: 'active' | 'inactive'
  linkedZylchAssistant: string | null
}

// Sync Types
export interface SyncStatus {
  isRunning: boolean
  lastSync: string | null
  progress: SyncProgress | null
  error: string | null
}

export interface SyncProgress {
  phase: 'emails' | 'calendar' | 'gaps' | 'tasks'
  current: number
  total: number
  message: string
}

// Gap Analysis Types
export interface RelationshipGap {
  contactEmail: string
  contactName: string
  daysSinceContact: number
  lastInteraction: string
  recommendedAction: string
  priority: 'high' | 'medium' | 'low'
}

// Chat Types
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  toolCalls?: ToolCall[]
}

export interface ToolCall {
  name: string
  arguments: Record<string, any>
  result?: any
}

// API Response Types
export interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  message?: string
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
  hasMore: boolean
}

// Assistant Types
export interface Assistant {
  id: string
  name: string
  ownerId: string
  createdAt: string
  settings: AssistantSettings
}

export interface AssistantSettings {
  emailStyle: string | null
  model: 'haiku' | 'sonnet' | 'opus' | 'auto'
  timezone: string
  // UI preferences
  assistantTone?: 'casual' | 'professional' | 'formal'
  responseLength?: 'concise' | 'balanced' | 'detailed'
  proactiveSuggestions?: boolean
  storeHistory?: boolean
  shareAnalytics?: boolean
  emailNotifications?: boolean
  taskReminders?: boolean
  gapAlerts?: boolean
}
