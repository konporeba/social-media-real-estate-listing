import { useState, useEffect, useRef } from 'react';
import type { RunDetail, PlatformType, DraftPost } from '../types';
import { useAppStore } from '../store';
import { useApproveRun, useRejectRun } from '../hooks/useRuns';

const PLATFORMS: PlatformType[] = ['facebook', 'instagram', 'linkedin'];

const PLATFORM_LABELS: Record<PlatformType, string> = {
  facebook:  'Facebook',
  instagram: 'Instagram',
  linkedin:  'LinkedIn',
};

const CHAR_LIMITS: Record<PlatformType, [number, number]> = {
  facebook:  [300,  1200],
  instagram: [200,  2200],
  linkedin:  [400,  3000],
};

const PLATFORM_STYLE: Record<PlatformType, { bg: string; text: string; border: string; ring: string }> = {
  facebook:  { bg: 'bg-[#1877f2]/10', text: 'text-[#6ba5f0]', border: 'border-[#1877f2]/25', ring: 'ring-[#1877f2]/30' },
  instagram: { bg: 'bg-pink-600/10',  text: 'text-pink-400',  border: 'border-pink-600/25',  ring: 'ring-pink-600/30'  },
  linkedin:  { bg: 'bg-[#0a66c2]/10', text: 'text-[#70b5f9]', border: 'border-[#0a66c2]/25', ring: 'ring-[#0a66c2]/30' },
};

function charClass(count: number, [min, max]: [number, number]) {
  if (count < min || count > max) return 'text-red-400';
  if (count > max * 0.9) return 'text-yellow-400';
  return 'text-green-400/60';
}

function getDraft(run: RunDetail, platform: PlatformType): DraftPost | undefined {
  return run.draft_posts.find((d) => d.platform === platform);
}

// ─── Platform icons ───────────────────────────────────────────────────────────

function LinkedInIcon({ className = 'w-4 h-4' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
    </svg>
  );
}

function InstagramIcon({ className = 'w-4 h-4' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162S8.597 18.163 12 18.163s6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zM12 16c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z" />
    </svg>
  );
}

function FacebookIcon({ className = 'w-4 h-4' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z" />
    </svg>
  );
}

const PLATFORM_ICONS: Record<PlatformType, React.ReactNode> = {
  facebook:  <FacebookIcon />,
  instagram: <InstagramIcon />,
  linkedin:  <LinkedInIcon />,
};

// ─── Social media preview cards ───────────────────────────────────────────────

function LinkedInPreview({ content, imageUrl }: { content: string; imageUrl?: string | null }) {
  const [expanded, setExpanded] = useState(false);
  const truncated      = content.slice(0, 280);
  const shouldTruncate = content.length > 280;

  return (
    <div className="bg-[#1b1f23] overflow-hidden">
      <div className="px-3 pt-3 pb-2 flex items-start gap-2.5">
        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center text-white text-xs font-bold shrink-0">SA</div>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-gray-100 leading-tight">Social Agent</p>
          <p className="text-[11px] text-gray-400 leading-tight">Real Estate Specialist</p>
          <p className="text-[10px] text-gray-600 mt-0.5">2h · 🌐</p>
        </div>
        <span className="text-gray-500 text-base leading-none">···</span>
      </div>
      <div className="px-3 pb-2">
        <p className="text-xs text-gray-200 leading-relaxed whitespace-pre-wrap">
          {expanded ? content : truncated}{shouldTruncate && !expanded && '…'}
        </p>
        {shouldTruncate && (
          <button onClick={() => setExpanded(!expanded)} className="text-[11px] text-[#70b5f9] hover:underline mt-0.5">
            {expanded ? 'show less' : '…see more'}
          </button>
        )}
      </div>
      {imageUrl && <img src={imageUrl} alt="Property" className="w-full object-cover max-h-48" />}
      <div className="px-3 py-2 border-t border-gray-700/40">
        <div className="flex justify-between text-[10px] text-gray-600 mb-1.5">
          <span>👍 ❤️ 42</span><span>8 comments</span>
        </div>
        <div className="flex border-t border-gray-700/40 pt-1.5 -mx-0.5">
          {['👍 Like','💬 Comment','🔁 Repost','📨 Send'].map(a => (
            <button key={a} className="flex-1 text-[10px] text-gray-600 py-1 hover:bg-gray-700/30 rounded">{a}</button>
          ))}
        </div>
      </div>
    </div>
  );
}

function InstagramPreview({ content, imageUrl }: { content: string; imageUrl?: string | null }) {
  const [expanded, setExpanded] = useState(false);
  const truncated      = content.slice(0, 120);
  const shouldTruncate = content.length > 120;

  return (
    <div className="bg-black overflow-hidden">
      <div className="px-3 py-2.5 flex items-center gap-2">
        <div className="w-7 h-7 rounded-full p-0.5 bg-gradient-to-tr from-yellow-400 via-pink-600 to-purple-700 shrink-0">
          <div className="w-full h-full rounded-full bg-black flex items-center justify-center">
            <span className="text-white text-[9px] font-bold">SA</span>
          </div>
        </div>
        <span className="text-xs font-semibold text-gray-100 flex-1">socialagent_re</span>
        <span className="text-gray-300 text-base">···</span>
      </div>
      {imageUrl ? (
        <img src={imageUrl} alt="Property" className="w-full aspect-square object-cover" />
      ) : (
        <div className="w-full aspect-square bg-gray-900 flex items-center justify-center">
          <span className="text-gray-700 text-[11px]">No image</span>
        </div>
      )}
      <div className="px-3 pt-2 pb-3">
        <div className="flex justify-between mb-1.5 text-gray-100 text-base">
          <div className="flex gap-3">
            <button className="hover:text-red-400">♥</button>
            <button className="hover:text-gray-300">○</button>
            <button className="hover:text-gray-300">▷</button>
          </div>
          <button className="hover:text-gray-300">⊹</button>
        </div>
        <p className="text-[11px] font-semibold text-gray-100 mb-0.5">142 likes</p>
        <p className="text-[11px] text-gray-200 leading-relaxed">
          <span className="font-semibold">socialagent_re </span>
          <span className="whitespace-pre-wrap">{expanded ? content : truncated}</span>
          {shouldTruncate && (
            <button onClick={() => setExpanded(!expanded)} className="text-gray-400 ml-1">{expanded ? 'less' : 'more'}</button>
          )}
        </p>
        <p className="text-[10px] text-gray-600 mt-1">2 HOURS AGO</p>
      </div>
    </div>
  );
}

function FacebookPreview({ content, imageUrl }: { content: string; imageUrl?: string | null }) {
  const [expanded, setExpanded] = useState(false);
  const truncated      = content.slice(0, 200);
  const shouldTruncate = content.length > 200;

  return (
    <div className="bg-[#18191a] overflow-hidden">
      <div className="px-3 pt-3 pb-2 flex items-start gap-2.5">
        <div className="w-9 h-9 rounded-full bg-gradient-to-br from-blue-600 to-blue-800 flex items-center justify-center text-white text-xs font-bold shrink-0">SA</div>
        <div className="flex-1">
          <span className="text-xs font-semibold text-gray-100">Social Agent RE</span>
          <span className="text-[11px] text-[#4599f0] ml-1.5 cursor-pointer hover:underline">· Follow</span>
          <p className="text-[10px] text-gray-500">2h · 🌐</p>
        </div>
        <span className="text-gray-400 text-base">···</span>
      </div>
      <div className="px-3 pb-2">
        <p className="text-xs text-gray-200 leading-relaxed whitespace-pre-wrap">
          {expanded ? content : truncated}{shouldTruncate && !expanded && '…'}
        </p>
        {shouldTruncate && (
          <button onClick={() => setExpanded(!expanded)} className="text-[11px] text-[#4599f0] hover:underline mt-0.5">
            {expanded ? 'See less' : 'See more'}
          </button>
        )}
      </div>
      {imageUrl && <img src={imageUrl} alt="Property" className="w-full object-cover max-h-52" />}
      <div className="px-3 py-2">
        <div className="flex justify-between text-[10px] text-gray-500 pb-1.5 border-b border-gray-700/40">
          <span>👍 ❤️ 247</span><span>34 comments · 12 shares</span>
        </div>
        <div className="flex pt-1 -mx-1">
          {['👍 Like','💬 Comment','↗ Share'].map(a => (
            <button key={a} className="flex-1 text-[10px] text-gray-500 py-1 hover:bg-gray-700/30 rounded">{a}</button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Shared platform tab bar ──────────────────────────────────────────────────

function PlatformTabs({
  active,
  onSelect,
  dotColor,
}: {
  active: PlatformType;
  onSelect: (p: PlatformType) => void;
  dotColor?: (p: PlatformType) => string;
}) {
  return (
    <div className="flex border-b border-gray-200 dark:border-gray-800/60 shrink-0 px-2">
      {PLATFORMS.map((p) => {
        const style = PLATFORM_STYLE[p];
        const isActive = p === active;
        return (
          <button
            key={p}
            onClick={() => onSelect(p)}
            className={`flex items-center gap-2 px-4 py-3 text-sm border-b-2 -mb-px transition-colors ${
              isActive
                ? `border-current ${style.text}`
                : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            {PLATFORM_ICONS[p]}
            <span className="font-medium">{PLATFORM_LABELS[p]}</span>
            {dotColor && (
              <span className={`w-1.5 h-1.5 rounded-full ${dotColor(p)}`} />
            )}
          </button>
        );
      })}
    </div>
  );
}

// ─── Main PostEditor (awaiting_review) ────────────────────────────────────────

export default function PostEditor({ run }: { run: RunDetail }) {
  const [activeTab, setActiveTab]           = useState<PlatformType>('facebook');
  const [showRejectConfirm, setShowRejectConfirm] = useState(false);
  const [mobilePanel, setMobilePanel]       = useState<'preview' | 'edit'>('edit');

  const editBuffers          = useAppStore((s) => s.editBuffers[run.id]);
  const setEditBuffer        = useAppStore((s) => s.setEditBuffer);
  const addToast             = useAppStore((s) => s.addToast);
  const platformSelections   = useAppStore((s) => s.platformSelections[run.id]);
  const setPlatformSelection = useAppStore((s) => s.setPlatformSelection);

  const approveMutation = useApproveRun();
  const rejectMutation  = useRejectRun();

  useEffect(() => {
    for (const platform of PLATFORMS) {
      const draft = getDraft(run, platform);
      if (draft && !(editBuffers ?? {})[platform]) {
        setEditBuffer(run.id, platform, draft.final_content);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.id, run.draft_posts.length]);

  const buffers            = editBuffers ?? {};
  const isPlatformSelected = (p: PlatformType) => (platformSelections ?? {})[p] !== false;
  const selectedPlatforms  = PLATFORMS.filter(isPlatformSelected);

  const draft        = getDraft(run, activeTab);
  const content      = buffers[activeTab] ?? draft?.final_content ?? '';
  const limits       = CHAR_LIMITS[activeTab];
  const style        = PLATFORM_STYLE[activeTab];
  const textareaRef  = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  }, [content, activeTab]);

  const handleApprove = async () => {
    const posts = {
      facebook:  isPlatformSelected('facebook')  ? (buffers['facebook']  ?? getDraft(run, 'facebook')?.final_content  ?? '') : '',
      instagram: isPlatformSelected('instagram') ? (buffers['instagram'] ?? getDraft(run, 'instagram')?.final_content ?? '') : '',
      linkedin:  isPlatformSelected('linkedin')  ? (buffers['linkedin']  ?? getDraft(run, 'linkedin')?.final_content  ?? '') : '',
    };
    try {
      await approveMutation.mutateAsync({ id: run.id, posts });
      addToast(`Approved ${selectedPlatforms.length} platform(s) — publishing started.`, 'success');
    } catch (e) {
      addToast(`Approve failed: ${(e as Error).message}`, 'error');
    }
  };

  const handleReject = async () => {
    try {
      await rejectMutation.mutateAsync(run.id);
      addToast('Run rejected.', 'info');
      setShowRejectConfirm(false);
    } catch (e) {
      addToast(`Reject failed: ${(e as Error).message}`, 'error');
    }
  };

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800/80 shadow-sm dark:shadow-xl overflow-hidden animate-fade-in" data-testid="post-editor">

      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-800/80 flex items-center justify-between gap-3 shrink-0">
        <div>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Review Posts</h3>
          <p className="text-xs text-gray-500 mt-0.5">Preview and edit each platform before publishing</p>
        </div>
        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-yellow-500/10 border border-yellow-500/20 shrink-0">
          <div className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />
          <span className="text-xs text-yellow-400 font-medium">Awaiting approval</span>
        </div>
      </div>

      {/* Tab bar — dot shows include/skip state */}
      <PlatformTabs
        active={activeTab}
        onSelect={setActiveTab}
        dotColor={(p) => isPlatformSelected(p) ? 'bg-blue-400' : 'bg-gray-700'}
      />

      {/* Mobile panel toggle — hidden on desktop */}
      <div className="flex md:hidden shrink-0 border-b border-gray-200 dark:border-gray-800/60">
        <button
          onClick={() => setMobilePanel('edit')}
          className={`flex-1 py-2.5 text-xs font-medium transition-colors ${
            mobilePanel === 'edit'
              ? 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-500/10 border-b-2 border-blue-500'
              : 'text-gray-500 dark:text-gray-400'
          }`}
        >
          Edit
        </button>
        <button
          onClick={() => setMobilePanel('preview')}
          className={`flex-1 py-2.5 text-xs font-medium transition-colors ${
            mobilePanel === 'preview'
              ? 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-500/10 border-b-2 border-blue-500'
              : 'text-gray-500 dark:text-gray-400'
          }`}
        >
          Preview
        </button>
      </div>

      {/* Split view */}
      <div className="flex flex-1 min-h-0 overflow-hidden">

        {/* Left — post preview */}
        <div className={`${mobilePanel === 'preview' ? 'block' : 'hidden'} md:flex md:flex-col w-full md:w-1/2 md:min-h-0 border-r border-gray-200 dark:border-gray-800/60 overflow-y-auto p-4 md:p-5`}>
          <div className={`max-w-[480px] mx-auto rounded-xl border ${style.border} overflow-hidden bg-white dark:bg-gray-950/60 shadow-lg shrink-0`}>
            <div className="px-4 py-3 flex items-center gap-2 border-b border-yellow-500/10">
              <div className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />
              <span className="text-[11px] text-yellow-400/80 font-medium uppercase tracking-wider">Preview — awaiting approval</span>
            </div>
            {activeTab === 'linkedin'  && <LinkedInPreview  content={content} imageUrl={draft?.image_url} />}
            {activeTab === 'instagram' && <InstagramPreview content={content} imageUrl={draft?.image_url} />}
            {activeTab === 'facebook'  && <FacebookPreview  content={content} imageUrl={draft?.image_url} />}
          </div>
        </div>

        {/* Right — edit panel */}
        <div className={`${mobilePanel === 'edit' ? 'block' : 'hidden'} md:flex md:flex-col w-full md:w-1/2 md:min-h-0 overflow-y-auto p-4 md:p-5`}>
          <div className="max-w-[480px] mx-auto flex flex-col gap-4">

          {/* Include / skip toggle */}
          <div className="flex items-center justify-between">
            <span className={`text-sm font-semibold ${style.text}`}>{PLATFORM_LABELS[activeTab]}</span>
            <button
              role="checkbox"
              aria-checked={isPlatformSelected(activeTab)}
              onClick={() => setPlatformSelection(run.id, activeTab, !isPlatformSelected(activeTab))}
              className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition-all ${
                isPlatformSelected(activeTab)
                  ? 'border-blue-600/50 bg-blue-600/10 text-blue-500 dark:text-blue-400'
                  : 'border-gray-300 dark:border-gray-700/50 bg-gray-100 dark:bg-gray-800/40 text-gray-500'
              }`}
            >
              {isPlatformSelected(activeTab) ? (
                <>
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                  </svg>
                  Included
                </>
              ) : 'Skipped'}
            </button>
          </div>

          {/* Validation warnings */}
          {draft?.validation_errors && (
            <div className="text-[11px] bg-yellow-50 dark:bg-yellow-950/50 border border-yellow-200 dark:border-yellow-800/40 rounded-xl p-3 text-yellow-700 dark:text-yellow-300 space-y-1">
              <div className="font-medium text-yellow-600 dark:text-yellow-400 mb-1">Validation warnings</div>
              {Object.entries(draft.validation_errors).map(([k, v]) => (
                <div key={k} className="flex gap-1.5">
                  <span className="text-yellow-500 dark:text-yellow-600 shrink-0">·</span>
                  <span>{String(v)}</span>
                </div>
              ))}
            </div>
          )}

          {/* Edit textarea */}
          <div className="flex flex-col">
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-xs font-medium text-gray-600 dark:text-gray-400">Content</label>
              <span className={`text-[11px] ${charClass(content.length, limits)}`}>
                {content.length} / {limits[0]}–{limits[1]}
              </span>
            </div>
            <textarea
              ref={textareaRef}
              key={activeTab}
              value={content}
              onChange={(e) => setEditBuffer(run.id, activeTab, e.target.value)}
              disabled={!isPlatformSelected(activeTab)}
              className="w-full min-h-48 bg-gray-100 dark:bg-gray-800/70 rounded-xl p-3 text-xs text-gray-900 dark:text-gray-100 resize-none focus:outline-none focus:ring-1 focus:ring-blue-600/50 leading-relaxed border border-gray-200 dark:border-gray-700/50 hover:border-gray-300 dark:hover:border-gray-600/60 transition-colors disabled:opacity-40 disabled:cursor-not-allowed overflow-hidden"
              aria-label={`${PLATFORM_LABELS[activeTab]} post content`}
            />
            {!isPlatformSelected(activeTab) && (
              <p className="text-[10px] text-gray-300 dark:text-gray-700 mt-1 text-center">Skipped — will not publish</p>
            )}
          </div>
          </div>
        </div>
      </div>

      {/* Action bar */}
      <div className="flex items-center justify-between px-4 md:px-5 pb-4 md:pb-5 pt-3 gap-2 md:gap-3 border-t border-gray-200 dark:border-gray-800/60 shrink-0">
        <button
          onClick={() => setShowRejectConfirm(true)}
          className="px-3 md:px-4 py-2 rounded-xl text-sm text-red-500 dark:text-red-400 border border-red-200 dark:border-red-800/50 hover:bg-red-50 dark:hover:bg-red-950/40 hover:border-red-300 dark:hover:border-red-700/60 transition-all"
        >
          Reject
        </button>

        <div className="flex items-center gap-2 md:gap-3">
          {selectedPlatforms.length === 0 ? (
            <span className="hidden sm:inline text-xs text-gray-400 dark:text-gray-600">Select at least one platform</span>
          ) : (
            <span className="hidden sm:inline text-xs text-gray-500">
              Publishing to {selectedPlatforms.length} platform{selectedPlatforms.length > 1 ? 's' : ''}
            </span>
          )}
          <button
            onClick={handleApprove}
            disabled={approveMutation.isPending || selectedPlatforms.length === 0}
            className="flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-medium bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-lg shadow-blue-600/20 hover:shadow-blue-600/30"
          >
            {approveMutation.isPending ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Approving…
              </>
            ) : (
              `Approve & Publish${selectedPlatforms.length > 0 && selectedPlatforms.length < 3 ? ` (${selectedPlatforms.length})` : ''}`
            )}
          </button>
        </div>
      </div>

      {/* Reject confirmation modal */}
      {showRejectConfirm && (
        <div className="fixed inset-0 z-40 overflow-y-auto animate-fade-in">
          <div className="flex min-h-full items-end sm:items-center justify-center sm:p-4 bg-black/70 backdrop-blur-sm">
            <div className="bg-white dark:bg-gray-900 rounded-t-2xl sm:rounded-2xl border border-gray-200 dark:border-gray-700/60 p-6 w-full sm:w-80 shadow-2xl animate-slide-up">
              <div className="w-10 h-10 rounded-full bg-red-500/10 border border-red-500/20 flex items-center justify-center mb-4">
                <svg className="w-5 h-5 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                </svg>
              </div>
              <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-1">Reject this run?</h3>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-5">Nothing will be posted. This action cannot be undone.</p>
              <div className="flex gap-3 justify-end">
                <button
                  onClick={() => setShowRejectConfirm(false)}
                  className="px-4 py-2 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors rounded-xl hover:bg-gray-100 dark:hover:bg-gray-800"
                >
                  Cancel
                </button>
                <button
                  onClick={handleReject}
                  disabled={rejectMutation.isPending}
                  className="px-4 py-2 text-sm bg-red-700 hover:bg-red-600 rounded-xl disabled:opacity-50 transition-colors"
                >
                  {rejectMutation.isPending ? 'Rejecting…' : 'Confirm reject'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Read-only review (shown when "Review" stage filter active on a completed run) ──

export function DraftReview({ run, onClear }: { run: RunDetail; onClear: () => void }) {
  const [activeTab, setActiveTab]   = useState<PlatformType>('facebook');
  const [mobilePanel, setMobilePanel] = useState<'preview' | 'content'>('content');

  const draft   = getDraft(run, activeTab);
  const content = draft?.final_content ?? '';
  const style   = PLATFORM_STYLE[activeTab];

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800/80 shadow-sm dark:shadow-xl overflow-hidden">

      {/* Header */}
      <div className="px-4 md:px-5 py-3 md:py-4 border-b border-gray-200 dark:border-gray-800/80 flex items-center justify-between gap-3 shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-yellow-400" />
          <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">Generated Posts</span>
          <span className="text-[10px] bg-yellow-500/10 text-yellow-400 border border-yellow-500/20 px-2 py-0.5 rounded-full font-medium">
            Read-only
          </span>
        </div>
        <button
          onClick={onClear}
          className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition-colors underline shrink-0"
        >
          Show activity log
        </button>
      </div>

      {/* Tab bar */}
      <PlatformTabs active={activeTab} onSelect={setActiveTab} />

      {/* Mobile panel toggle */}
      <div className="flex md:hidden shrink-0 border-b border-gray-200 dark:border-gray-800/60">
        <button
          onClick={() => setMobilePanel('content')}
          className={`flex-1 py-2.5 text-xs font-medium transition-colors ${
            mobilePanel === 'content'
              ? 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-500/10 border-b-2 border-blue-500'
              : 'text-gray-500 dark:text-gray-400'
          }`}
        >
          Content
        </button>
        <button
          onClick={() => setMobilePanel('preview')}
          className={`flex-1 py-2.5 text-xs font-medium transition-colors ${
            mobilePanel === 'preview'
              ? 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-500/10 border-b-2 border-blue-500'
              : 'text-gray-500 dark:text-gray-400'
          }`}
        >
          Preview
        </button>
      </div>

      {/* Split view */}
      <div className="flex flex-1 min-h-0 overflow-hidden">

        {/* Left — post preview */}
        <div className={`${mobilePanel === 'preview' ? 'block' : 'hidden'} md:flex md:flex-col w-full md:w-1/2 md:min-h-0 border-r border-gray-200 dark:border-gray-800/60 overflow-y-auto p-4 md:p-5`}>
          {draft ? (
            <div className={`max-w-[480px] mx-auto rounded-xl border ${style.border} overflow-hidden bg-white dark:bg-gray-950/60 shadow-lg shrink-0`}>
              {activeTab === 'linkedin'  && <LinkedInPreview  content={content} imageUrl={draft.image_url} />}
              {activeTab === 'instagram' && <InstagramPreview content={content} imageUrl={draft.image_url} />}
              {activeTab === 'facebook'  && <FacebookPreview  content={content} imageUrl={draft.image_url} />}
            </div>
          ) : (
            <p className="text-xs text-gray-400 dark:text-gray-600">No draft generated for this platform.</p>
          )}
        </div>

        {/* Right — read-only content */}
        <div className={`${mobilePanel === 'content' ? 'block' : 'hidden'} md:flex md:flex-col w-full md:w-1/2 md:min-h-0 overflow-y-auto p-4 md:p-5`}>
          <div className="max-w-[480px] mx-auto w-full">
          {draft ? (
            <div className="flex flex-col gap-3">
              <span className={`text-sm font-semibold ${style.text}`}>{PLATFORM_LABELS[activeTab]}</span>
              <div className="bg-gray-50 dark:bg-gray-800/40 rounded-xl border border-gray-200 dark:border-gray-700/40 p-4">
                <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">Final content</p>
                <p className="text-xs text-gray-700 dark:text-gray-300 leading-relaxed whitespace-pre-wrap">{content}</p>
              </div>
            </div>
          ) : (
            <p className="text-xs text-gray-400 dark:text-gray-600">No content available.</p>
          )}
          </div>
        </div>
      </div>
    </div>
  );
}
