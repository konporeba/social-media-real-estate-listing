import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import PostEditor from '../PostEditor';
import type { RunDetail } from '../../types';

const makeDraft = (platform: string, content: string) => ({
  id: `draft-${platform}`,
  run_id: 'run-1',
  platform,
  generated_content: content,
  edited_content: null,
  final_content: content,
  image_url: null,
  prompt_version: 'v1',
  validation_errors: null,
  approved_at: null,
});

const mockRun: RunDetail = {
  id: 'run-1',
  status: 'awaiting_review',
  triggered_by: 'manual',
  property_url: 'https://dprealestate.es/test-OMS',
  error_message: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  completed_at: null,
  events: [],
  draft_posts: [
    makeDraft('facebook', 'A'.repeat(350)),
    makeDraft('instagram', 'B'.repeat(250)),
    makeDraft('linkedin', 'C'.repeat(450)),
  ],
};

vi.mock('../../hooks/useRuns', () => ({
  useApproveRun: () => ({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false }),
  useRejectRun:  () => ({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false }),
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('PostEditor', () => {
  it('renders three platform tabs', () => {
    render(<PostEditor run={mockRun} />, { wrapper });
    expect(screen.getByText('Facebook')).toBeInTheDocument();
    expect(screen.getByText('Instagram')).toBeInTheDocument();
    expect(screen.getByText('LinkedIn')).toBeInTheDocument();
  });

  it('defaults to Facebook tab and shows its character count', () => {
    render(<PostEditor run={mockRun} />, { wrapper });
    expect(screen.getByText(/350\s*\/\s*300–1200/)).toBeInTheDocument();
  });

  it('switches to Instagram tab and shows correct character count', () => {
    render(<PostEditor run={mockRun} />, { wrapper });
    fireEvent.click(screen.getByText('Instagram'));
    expect(screen.getByText(/250\s*\/\s*200–2200/)).toBeInTheDocument();
  });

  it('switches to LinkedIn tab and shows correct character count', () => {
    render(<PostEditor run={mockRun} />, { wrapper });
    fireEvent.click(screen.getByText('LinkedIn'));
    expect(screen.getByText(/450\s*\/\s*400–3000/)).toBeInTheDocument();
  });

  it('updates character count when user types', () => {
    render(<PostEditor run={mockRun} />, { wrapper });
    const textarea = screen.getByRole('textbox');
    fireEvent.change(textarea, { target: { value: 'X'.repeat(400) } });
    expect(screen.getByText(/400\s*\/\s*300–1200/)).toBeInTheDocument();
  });

  it('shows reject confirmation dialog on Reject click', async () => {
    render(<PostEditor run={mockRun} />, { wrapper });
    fireEvent.click(screen.getByText('Reject'));
    await waitFor(() =>
      expect(screen.getByText(/Reject this run\?/)).toBeInTheDocument(),
    );
    expect(screen.getByText('Confirm reject')).toBeInTheDocument();
  });

  it('closes reject dialog on Cancel', async () => {
    render(<PostEditor run={mockRun} />, { wrapper });
    fireEvent.click(screen.getByText('Reject'));
    await waitFor(() => screen.getByText('Confirm reject'));
    fireEvent.click(screen.getByText('Cancel'));
    await waitFor(() =>
      expect(screen.queryByText('Confirm reject')).not.toBeInTheDocument(),
    );
  });

  it('shows validation warnings when present', () => {
    const runWithWarnings: RunDetail = {
      ...mockRun,
      draft_posts: [
        {
          ...makeDraft('facebook', 'A'.repeat(350)),
          validation_errors: { length: 'Post too short' },
        },
        makeDraft('instagram', 'B'.repeat(250)),
        makeDraft('linkedin', 'C'.repeat(450)),
      ],
    };
    render(<PostEditor run={runWithWarnings} />, { wrapper });
    expect(screen.getByText('Post too short')).toBeInTheDocument();
  });

  it('disables approve button when no platforms are selected', () => {
    render(<PostEditor run={mockRun} />, { wrapper });
    const fbCheckbox = screen.getAllByRole('checkbox')[0];
    const igCheckbox = screen.getAllByRole('checkbox')[1];
    const liCheckbox = screen.getAllByRole('checkbox')[2];
    fireEvent.click(fbCheckbox);
    fireEvent.click(igCheckbox);
    fireEvent.click(liCheckbox);
    const approveBtn = screen.getByText(/Approve/);
    expect(approveBtn).toBeDisabled();
  });
});
