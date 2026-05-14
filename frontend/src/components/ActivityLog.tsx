import { useRef, useEffect } from 'react';
import type { RunEvent } from '../types';

// ─── Agent badge config ───────────────────────────────────────────────────────

const AGENT_CONFIG: Record<string, { badge: string; dot: string; label: string }> = {
  orchestrator: { badge: 'bg-purple-500/15 text-purple-700 dark:text-purple-300 border-purple-500/25', dot: 'bg-purple-400', label: 'Orchestrator' },
  discovery:    { badge: 'bg-cyan-500/15 text-cyan-700 dark:text-cyan-300 border-cyan-500/25',         dot: 'bg-cyan-400',   label: 'Discovery'    },
  content:      { badge: 'bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/25',         dot: 'bg-blue-400',   label: 'Content'      },
  validation:   { badge: 'bg-yellow-500/15 text-yellow-700 dark:text-yellow-300 border-yellow-500/25', dot: 'bg-yellow-400', label: 'Validation'   },
  publishing:   { badge: 'bg-green-500/15 text-green-700 dark:text-green-300 border-green-500/25',     dot: 'bg-green-400',  label: 'Publishing'   },
};

// ─── Stage filter mapping ─────────────────────────────────────────────────────

const STAGE_AGENTS: Record<string, string[]> = {
  discover: ['discovery'],
  generate: ['content', 'validation'],
  review:   [],
  publish:  ['publishing'],
  done:     [],
};

const STAGE_EVENT_TYPES: Record<string, string[]> = {
  discover: ['run_started', 'property_selected', 'property_discovered', 'property_not_found'],
  generate: ['content_generating', 'content_generated', 'content_validating', 'content_validated', 'content_invalid', 'content_regenerating', 'draft_saved'],
  review:   ['awaiting_human_review', 'review_email_sent', 'run_rejected'],
  publish:  ['publishing_started', 'platform_posted', 'platform_failed', 'platform_not_configured', 'platform_skipped', 'posted_link_saved', 'publishing_done'],
  done:     ['run_completed', 'run_failed', 'run_partial'],
};

function matchesStage(event: RunEvent, stage: string): boolean {
  const agents = STAGE_AGENTS[stage] ?? [];
  const types  = STAGE_EVENT_TYPES[stage] ?? [];
  return agents.includes(event.agent) || types.includes(event.event_type);
}

// ─── Event info: label + description (detail may be a fn receiving the payload) ─

type DetailFn = (payload: Record<string, unknown>) => string;
type EventConfig = { label: string; detail: string | DetailFn };

function cap(s: string) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }
function platformLabel(p: Record<string, unknown>) { return cap(String(p.platform ?? 'Platform')); }
function platformList(arr: unknown) {
  const items = Array.isArray(arr) ? (arr as string[]) : [];
  return items.map(cap).join(', ') || '—';
}

const EVENT_INFO: Record<string, EventConfig> = {
  run_started: {
    label:  'Pipeline started',
    detail: 'All agents are initialized and the orchestrator is coordinating the pipeline. Property discovery will begin immediately.',
  },
  property_selected: {
    label:  'Property selected',
    detail: 'A specific property URL was provided for this run. Content generation agents will use the listing details as source material.',
  },
  property_discovered: {
    label:  'Property discovered',
    detail: 'The discovery agent found an eligible property through automated scanning. Property details have been extracted and handed off for content creation.',
  },
  property_not_found: {
    label:  'No property found',
    detail: 'The discovery scan completed but returned no new eligible listings. The pipeline will stop — no posts will be generated for this run.',
  },
  content_generating: {
    label:  'Generating content',
    detail: 'The content agent is crafting post copy tailored for each platform. It accounts for audience tone, formatting conventions, and character constraints on each channel.',
  },
  content_generated: {
    label:  'Content generated',
    detail: "Unique drafts have been written for Facebook, Instagram, and LinkedIn. Each version is adapted to the platform's character limits and engagement patterns.",
  },
  content_validating: {
    label:  'Validating content',
    detail: 'The validation agent is checking all three drafts against quality rules. Checks include character counts, prohibited phrases, and readability scores.',
  },
  content_validated: {
    label:  'Content passed validation',
    detail: 'All quality checks passed — character counts are within limits, tone is appropriate, and no policy violations were detected. Drafts are ready for human review.',
  },
  content_invalid: {
    label:  'Validation failed',
    detail: 'One or more drafts did not meet the quality standards set by the validation rules. The content agent will regenerate the failing posts using improved prompts.',
  },
  content_regenerating: {
    label:  'Regenerating content',
    detail: 'The content agent is rewriting posts that failed validation, using feedback from the previous attempt to produce better results. This may happen multiple times.',
  },
  draft_saved: {
    label:  'Draft saved',
    detail: 'All post drafts have been written to the database and are preserved. They are now ready to be displayed for human review and approval.',
  },
  awaiting_human_review: {
    label:  'Awaiting human review',
    detail: "The pipeline is paused and waiting for your decision. Preview each platform's post, edit content if needed, then approve or reject to continue.",
  },
  review_email_sent: {
    label:  'Review email dispatched',
    detail: 'A notification email with the post drafts and an approval link has been sent to the reviewer. The pipeline will remain paused until a decision is made.',
  },
  run_rejected: {
    label:  'Posts rejected',
    detail: 'The reviewer chose not to publish this batch. The run is now closed and no posts will be sent to any platform.',
  },
  publishing_started: {
    label:  'Publishing started',
    detail: 'The publishing agent is now sending posts to each selected social media platform. Platforms are handled independently, so a failure on one does not affect the others.',
  },
  platform_posted: {
    label:  'Post published',
    detail: (p) => {
      const label = platformLabel(p);
      return String(p.mode) === 'shadow'
        ? `${label} post was recorded in shadow mode — no real API call was made.`
        : `The post is now live on ${label}.`;
    },
  },
  platform_failed: {
    label:  'Post failed to publish',
    detail: (p) => {
      const label = platformLabel(p);
      const error = String(p.error ?? '').trim();
      return error
        ? `${label} rejected the post: ${error}`
        : `${label} rejected the post — this may be due to API rate limits, authentication issues, or content policy violations.`;
    },
  },
  platform_not_configured: {
    label:  'Platform not configured',
    detail: (p) => `${platformLabel(p)} has no API credentials configured and was skipped. Add credentials to .env to enable this platform.`,
  },
  platform_skipped: {
    label:  'Platform already posted',
    detail: (p) => `${platformLabel(p)} was skipped — a successful post already exists from a previous attempt on this run.`,
  },
  posted_link_saved: {
    label:  'Posted link recorded',
    detail: (p) => {
      const platforms = platformList(p.platforms);
      return `The property URL has been saved to the posted-links list for: ${platforms}. It will not be picked up by the discovery agent again.`;
    },
  },
  publishing_done: {
    label:  'Publishing session complete',
    detail: (p) => {
      const succeeded = platformList(p.succeeded);
      const failed    = platformList(p.failed);
      const skipped   = platformList(p.skipped);
      const none      = platformList(p.not_configured);
      const parts: string[] = [];
      if ((p.succeeded as string[] | undefined)?.length)       parts.push(`Published: ${succeeded}`);
      if ((p.failed    as string[] | undefined)?.length)       parts.push(`Failed: ${failed}`);
      if ((p.skipped   as string[] | undefined)?.length)       parts.push(`Already posted: ${skipped}`);
      if ((p.not_configured as string[] | undefined)?.length)  parts.push(`Not configured: ${none}`);
      return parts.length ? parts.join(' · ') : 'Publishing session finished.';
    },
  },
  run_completed: {
    label:  'Pipeline complete',
    detail: 'All selected posts have been published successfully. The run is now closed.',
  },
  run_partial: {
    label:  'Run partially completed',
    detail: (p) => {
      const failed = platformList(p.failed);
      return (p.failed as string[] | undefined)?.length
        ? `Posts were not published to: ${failed}. Use Retry publish to re-attempt the failed platforms.`
        : 'Some platforms were not published. Use Retry publish to re-attempt.';
    },
  },
  run_failed: {
    label:  'Pipeline failed',
    detail: 'An unrecoverable error occurred and the pipeline was stopped. Review the error message in the pipeline header for details.',
  },
  error: {
    label:  'Error occurred',
    detail: 'An unexpected error was logged by an agent. Depending on severity, the pipeline may continue or stop automatically.',
  },
};

function getEventInfo(eventType: string): EventConfig {
  if (EVENT_INFO[eventType]) return EVENT_INFO[eventType];
  const label = eventType.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  return { label, detail: `The ${eventType.replace(/_/g, ' ')} event was emitted by the agent.` };
}

// ─── Event row ────────────────────────────────────────────────────────────────

function EventRow({ event, isLast }: { event: RunEvent; isLast: boolean }) {
  const cfg  = AGENT_CONFIG[event.agent] ?? {
    badge: 'bg-gray-500/15 text-gray-300 border-gray-500/25',
    dot:   'bg-gray-400',
    label: event.agent,
  };
  const info   = getEventInfo(event.event_type);
  const detail = typeof info.detail === 'function' ? info.detail(event.payload) : info.detail;

  return (
    <div className="flex gap-3 animate-fade-in">
      <div className="flex flex-col items-center shrink-0 pt-1.5">
        <div className={`w-2 h-2 rounded-full shrink-0 ring-2 ring-white dark:ring-gray-900 ${cfg.dot}`} />
        {!isLast && <div className="w-px flex-1 bg-gray-200 dark:bg-gray-800/80 mt-1.5" />}
      </div>

      <div className={`flex-1 min-w-0 ${isLast ? 'pb-0' : 'pb-5'}`}>
        {/* Badge + timestamp always on the same row — both are short, never wrap */}
        <div className="flex items-center justify-between gap-2 mb-0.5">
          <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full border shrink-0 ${cfg.badge}`}>
            {cfg.label} Agent
          </span>
          <span className="text-[10px] text-gray-400 dark:text-gray-500 font-mono tabular-nums shrink-0">
            {new Date(event.created_at).toLocaleTimeString('pl-PL', { hour12: false })}
          </span>
        </div>
        {/* Event label gets its own full-width row — never competes for space */}
        <span className="text-sm text-gray-800 dark:text-gray-200 font-medium leading-tight">{info.label}</span>
        <p className="text-xs text-gray-500 mt-1 leading-relaxed">{detail}</p>
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

interface ActivityLogProps {
  events: RunEvent[];
  stageFilter: string | null;
  onClearFilter: () => void;
}

export default function ActivityLog({ events, stageFilter, onClearFilter }: ActivityLogProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!stageFilter) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [events.length, stageFilter]);

  const visible = stageFilter
    ? events.filter((e) => matchesStage(e, stageFilter))
    : events;

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800/80 shadow-sm dark:shadow-xl">
      <div className="px-4 md:px-5 py-3 md:py-4 border-b border-gray-200 dark:border-gray-800/80 flex items-center justify-between gap-3 shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
          <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">Activity Log</span>
          {stageFilter && (
            <span className="text-[10px] bg-blue-600/20 text-blue-400 border border-blue-600/30 px-2 py-0.5 rounded-full capitalize font-medium">
              {stageFilter}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {stageFilter && (
            <button
              onClick={onClearFilter}
              className="text-[10px] text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition-colors underline"
            >
              Clear filter
            </button>
          )}
          <span className="text-[10px] text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded-full font-mono">
            {visible.length}{stageFilter && events.length !== visible.length ? `/${events.length}` : ''} events
          </span>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-4 md:px-5 py-4">
        {visible.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 gap-2.5 text-gray-400 dark:text-gray-600">
            <div className="w-8 h-8 rounded-full border border-gray-200 dark:border-gray-800 flex items-center justify-center">
              <div className="w-2 h-2 rounded-full bg-gray-300 dark:bg-gray-700 animate-pulse" />
            </div>
            <span className="text-xs">
              {stageFilter ? `No events recorded for the ${stageFilter} stage.` : 'Waiting for pipeline events…'}
            </span>
            {stageFilter && (
              <button onClick={onClearFilter} className="text-xs text-blue-500 dark:text-blue-400/70 hover:text-blue-600 dark:hover:text-blue-300 underline transition-colors">
                Show all events
              </button>
            )}
          </div>
        ) : (
          <div className="pt-1">
            {visible.map((e, i) => (
              <EventRow key={e.id} event={e} isLast={i === visible.length - 1} />
            ))}
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
