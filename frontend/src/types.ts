export type RunStatus =
  | 'pending'
  | 'discovering'
  | 'generating'
  | 'validating'
  | 'regenerating'
  | 'awaiting_review'
  | 'scheduled'
  | 'publishing'
  | 'completed'
  | 'partial'
  | 'rejected'
  | 'failed';

export type PlatformType = 'facebook' | 'instagram' | 'linkedin';
export type TriggerSource = 'schedule' | 'manual';

export interface Run {
  id: string;
  status: RunStatus;
  triggered_by: TriggerSource;
  property_url: string | null;
  property_title: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface RunEvent {
  id: string;
  run_id: string;
  agent: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface DraftPost {
  id: string;
  run_id: string;
  platform: PlatformType;
  generated_content: string;
  edited_content: string | null;
  final_content: string;
  image_url: string | null;
  prompt_version: string | null;
  validation_errors: Record<string, unknown> | null;
  approved_at: string | null;
}

export interface RunDetail extends Run {
  events: RunEvent[];
  draft_posts: DraftPost[];
}

export interface SSEEvent {
  run_id: string;
  agent: string;
  event_type: string;
  payload: Record<string, unknown>;
  timestamp: string;
}
