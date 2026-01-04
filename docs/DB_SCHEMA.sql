-- WARNING: This schema is for context only and is not meant to be run.
-- Table order and constraints may not be valid for execution.

CREATE TABLE public.agent_prompts (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  owner_id text NOT NULL,
  agent_type text NOT NULL,
  agent_prompt text NOT NULL,
  metadata jsonb DEFAULT '{}'::jsonb,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT agent_prompts_pkey PRIMARY KEY (id)
);
CREATE TABLE public.background_jobs (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  owner_id text NOT NULL,
  job_type text NOT NULL,
  channel text,
  status text NOT NULL DEFAULT 'pending'::text,
  progress_pct integer DEFAULT 0,
  items_processed integer DEFAULT 0,
  total_items integer,
  status_message text,
  created_at timestamp with time zone DEFAULT now(),
  started_at timestamp with time zone,
  completed_at timestamp with time zone,
  last_error text,
  retry_count integer DEFAULT 0,
  result jsonb DEFAULT '{}'::jsonb,
  CONSTRAINT background_jobs_pkey PRIMARY KEY (id)
);
CREATE TABLE public.blob_sentences (
  id uuid NOT NULL DEFAULT uuid_generate_v4(),
  blob_id uuid NOT NULL,
  owner_id text NOT NULL,
  sentence_text text NOT NULL,
  embedding USER-DEFINED NOT NULL,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT blob_sentences_pkey PRIMARY KEY (id),
  CONSTRAINT blob_sentences_blob_id_fkey FOREIGN KEY (blob_id) REFERENCES public.blobs(id)
);
CREATE TABLE public.blobs (
  id uuid NOT NULL DEFAULT uuid_generate_v4(),
  owner_id text NOT NULL,
  namespace text NOT NULL,
  content text NOT NULL,
  embedding USER-DEFINED,
  events jsonb DEFAULT '[]'::jsonb,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  tsv tsvector DEFAULT to_tsvector('simple'::regconfig, extract_identifiers(content)),
  CONSTRAINT blobs_pkey PRIMARY KEY (id)
);
CREATE TABLE public.calendar_events (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  owner_id text NOT NULL,
  google_event_id text NOT NULL,
  summary text,
  description text,
  start_time timestamp with time zone,
  end_time timestamp with time zone,
  location text,
  attendees jsonb,
  organizer_email text,
  is_external boolean DEFAULT false,
  meet_link text,
  calendar_id text DEFAULT 'primary'::text,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  memory_processed_at timestamp with time zone,
  task_processed_at timestamp with time zone,
  CONSTRAINT calendar_events_pkey PRIMARY KEY (id)
);
CREATE TABLE public.drafts (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  owner_id text NOT NULL,
  to_addresses ARRAY NOT NULL DEFAULT '{}'::text[],
  cc_addresses ARRAY DEFAULT '{}'::text[],
  bcc_addresses ARRAY DEFAULT '{}'::text[],
  subject text,
  body text,
  body_format text DEFAULT 'html'::text CHECK (body_format = ANY (ARRAY['html'::text, 'plain'::text])),
  in_reply_to text,
  references ARRAY,
  thread_id text,
  original_message_id text,
  status text DEFAULT 'draft'::text CHECK (status = ANY (ARRAY['draft'::text, 'sending'::text, 'sent'::text, 'failed'::text])),
  provider text CHECK (provider = ANY (ARRAY['google'::text, 'microsoft'::text])),
  sent_at timestamp with time zone,
  sent_message_id text,
  error_message text,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT drafts_pkey PRIMARY KEY (id)
);
CREATE TABLE public.email_read_events (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  tracking_id text,
  sendgrid_message_id text,
  owner_id text NOT NULL,
  message_id text NOT NULL,
  recipient_email text NOT NULL,
  tracking_source text NOT NULL CHECK (tracking_source = ANY (ARRAY['sendgrid_webhook'::text, 'custom_pixel'::text])),
  read_count integer DEFAULT 0,
  first_read_at timestamp with time zone,
  last_read_at timestamp with time zone,
  user_agents ARRAY,
  ip_addresses ARRAY,
  sendgrid_event_data jsonb,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT email_read_events_pkey PRIMARY KEY (id)
);
CREATE TABLE public.emails (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  owner_id text NOT NULL,
  gmail_id text NOT NULL,
  thread_id text NOT NULL,
  from_email text,
  from_name text,
  to_email text,
  cc_email text,
  subject text,
  date timestamp with time zone NOT NULL,
  date_timestamp bigint,
  snippet text,
  body_plain text,
  body_html text,
  labels text,
  message_id_header text,
  in_reply_to text,
  references text,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  fts_document tsvector DEFAULT ((setweight(to_tsvector('english'::regconfig, COALESCE(subject, ''::text)), 'A'::"char") || setweight(to_tsvector('english'::regconfig, COALESCE(body_plain, ''::text)), 'B'::"char")) || setweight(to_tsvector('english'::regconfig, COALESCE(from_email, ''::text)), 'C'::"char")),
  read_events jsonb DEFAULT '[]'::jsonb,
  memory_processed_at timestamp with time zone,
  embedding USER-DEFINED,
  tsv tsvector DEFAULT to_tsvector('simple'::regconfig, ((COALESCE(subject, ''::text) || ' '::text) || COALESCE(body_plain, ''::text))),
  task_processed_at timestamp with time zone,
  CONSTRAINT emails_pkey PRIMARY KEY (id)
);
CREATE TABLE public.integration_providers (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  provider_key text NOT NULL UNIQUE,
  display_name text NOT NULL,
  category text NOT NULL,
  icon_url text,
  description text,
  requires_oauth boolean DEFAULT true,
  oauth_url text,
  config_fields jsonb,
  is_available boolean DEFAULT true,
  documentation_url text,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT integration_providers_pkey PRIMARY KEY (id)
);
CREATE TABLE public.oauth_states (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  state text NOT NULL UNIQUE,
  owner_id text NOT NULL,
  email text,
  cli_callback text,
  expires_at timestamp with time zone NOT NULL,
  created_at timestamp with time zone DEFAULT now(),
  provider text DEFAULT 'google'::text,
  metadata jsonb,
  CONSTRAINT oauth_states_pkey PRIMARY KEY (id)
);
CREATE TABLE public.oauth_tokens (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  owner_id text NOT NULL,
  provider text NOT NULL,
  email text NOT NULL,
  scopes text,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  connection_status text DEFAULT 'connected'::text,
  last_sync timestamp with time zone,
  error_message text,
  display_name text,
  credentials jsonb,
  CONSTRAINT oauth_tokens_pkey PRIMARY KEY (id)
);
CREATE TABLE public.patterns (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  owner_id text NOT NULL,
  namespace text NOT NULL,
  skill text NOT NULL,
  intent text NOT NULL,
  context jsonb,
  action jsonb,
  outcome text,
  contact_id text,
  confidence real DEFAULT 0.5,
  times_applied integer DEFAULT 0,
  times_successful integer DEFAULT 0,
  state text DEFAULT 'active'::text,
  embedding USER-DEFINED,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  last_accessed timestamp with time zone,
  CONSTRAINT patterns_pkey PRIMARY KEY (id)
);
CREATE TABLE public.pipedrive_deals (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  owner_id text NOT NULL,
  deal_id text NOT NULL,
  title text,
  person_name text,
  org_name text,
  value numeric,
  currency text DEFAULT 'USD'::text,
  status text,
  stage_name text,
  pipeline_name text,
  expected_close_date date,
  deal_data jsonb,
  memory_processed_at timestamp with time zone,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT pipedrive_deals_pkey PRIMARY KEY (id)
);
CREATE TABLE public.scheduled_jobs (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  owner_id text NOT NULL,
  job_type text NOT NULL,
  message text NOT NULL,
  callback_type text NOT NULL DEFAULT 'notification'::text,
  metadata jsonb DEFAULT '{}'::jsonb,
  run_at timestamp with time zone,
  cron_expression text,
  interval_seconds integer,
  condition_key text,
  timeout_seconds integer,
  status text NOT NULL DEFAULT 'pending'::text,
  last_run_at timestamp with time zone,
  next_run_at timestamp with time zone,
  run_count integer DEFAULT 0,
  last_error text,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT scheduled_jobs_pkey PRIMARY KEY (id)
);
CREATE TABLE public.sendgrid_message_mapping (
  sendgrid_message_id text NOT NULL,
  message_id text NOT NULL,
  owner_id text NOT NULL,
  recipient_email text NOT NULL,
  campaign_id text,
  created_at timestamp with time zone DEFAULT now(),
  expires_at timestamp with time zone DEFAULT (now() + '90 days'::interval),
  CONSTRAINT sendgrid_message_mapping_pkey PRIMARY KEY (sendgrid_message_id)
);
CREATE TABLE public.sharing_auth (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  sender_id text NOT NULL,
  sender_email text NOT NULL,
  recipient_email text NOT NULL,
  status text DEFAULT 'pending'::text CHECK (status = ANY (ARRAY['pending'::text, 'authorized'::text, 'revoked'::text])),
  created_at timestamp with time zone DEFAULT now(),
  authorized_at timestamp with time zone,
  CONSTRAINT sharing_auth_pkey PRIMARY KEY (id)
);
CREATE TABLE public.sync_state (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  owner_id text NOT NULL UNIQUE,
  history_id text,
  last_sync timestamp with time zone,
  full_sync_completed timestamp with time zone,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT sync_state_pkey PRIMARY KEY (id)
);
CREATE TABLE public.task_items (
  id uuid NOT NULL DEFAULT uuid_generate_v4(),
  owner_id text NOT NULL,
  event_type text NOT NULL,
  event_id text NOT NULL,
  contact_email text,
  contact_name text,
  action_required boolean NOT NULL DEFAULT false,
  urgency text,
  reason text,
  suggested_action text,
  created_at timestamp with time zone DEFAULT now(),
  analyzed_at timestamp with time zone,
  completed_at timestamp with time zone,
  sources jsonb DEFAULT '{}'::jsonb,
  CONSTRAINT task_items_pkey PRIMARY KEY (id)
);
CREATE TABLE public.thread_analysis (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  owner_id text NOT NULL,
  thread_id text NOT NULL,
  contact_email text,
  contact_name text,
  last_email_date timestamp with time zone,
  last_email_direction text,
  analysis jsonb,
  needs_action boolean DEFAULT false,
  task_description text,
  priority integer,
  manually_closed boolean DEFAULT false,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT thread_analysis_pkey PRIMARY KEY (id)
);
CREATE TABLE public.trigger_events (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  owner_id text NOT NULL,
  event_type text NOT NULL CHECK (event_type = ANY (ARRAY['email_received'::text, 'sms_received'::text, 'call_received'::text])),
  event_data jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text DEFAULT 'pending'::text CHECK (status = ANY (ARRAY['pending'::text, 'processing'::text, 'completed'::text, 'failed'::text])),
  trigger_id uuid,
  result jsonb,
  created_at timestamp with time zone DEFAULT now(),
  processed_at timestamp with time zone,
  attempts integer DEFAULT 0,
  last_error text,
  CONSTRAINT trigger_events_pkey PRIMARY KEY (id),
  CONSTRAINT trigger_events_trigger_id_fkey FOREIGN KEY (trigger_id) REFERENCES public.triggers(id)
);
CREATE TABLE public.triggers (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  owner_id text NOT NULL,
  trigger_type text NOT NULL CHECK (trigger_type = ANY (ARRAY['session_start'::text, 'email_received'::text, 'sms_received'::text, 'call_received'::text])),
  instruction text NOT NULL,
  active boolean DEFAULT true,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT triggers_pkey PRIMARY KEY (id)
);
CREATE TABLE public.user_notifications (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  owner_id text NOT NULL,
  message text NOT NULL,
  notification_type text DEFAULT 'warning'::text,
  read boolean DEFAULT false,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT user_notifications_pkey PRIMARY KEY (id)
);