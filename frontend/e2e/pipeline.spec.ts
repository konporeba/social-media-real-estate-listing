import { test, expect } from '@playwright/test';

const RUN_ID = 'test-run-uuid-0001';

const mockRun = {
  id: RUN_ID,
  status: 'awaiting_review',
  triggered_by: 'manual',
  property_url: 'https://dprealestate.es/test-OMS',
  error_message: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  completed_at: null,
};

const mockDraftPost = (platform: string, content: string) => ({
  id: `dp-${platform}`,
  run_id: RUN_ID,
  platform,
  generated_content: content,
  edited_content: null,
  final_content: content,
  image_url: null,
  prompt_version: 'v1',
  validation_errors: null,
  approved_at: null,
});

test('trigger manual run, view pipeline, edit and approve posts', async ({ page }) => {
  // Mock GET /runs
  await page.route('**/runs', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: [mockRun] });
    } else if (route.request().method() === 'POST') {
      await route.fulfill({ json: { run_id: RUN_ID } });
    } else {
      await route.continue();
    }
  });

  // Mock GET /runs/:id
  await page.route(`**/runs/${RUN_ID}`, async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        json: {
          ...mockRun,
          events: [
            {
              id: 'evt-1',
              run_id: RUN_ID,
              agent: 'orchestrator',
              event_type: 'run_started',
              payload: {},
              created_at: new Date().toISOString(),
            },
            {
              id: 'evt-2',
              run_id: RUN_ID,
              agent: 'discovery',
              event_type: 'property_selected',
              payload: {},
              created_at: new Date().toISOString(),
            },
          ],
          draft_posts: [
            mockDraftPost('facebook', 'Facebook post: Piękne mieszkanie na sprzedaż. '.repeat(9)),
            mockDraftPost('instagram', 'Instagram: Mieszkanie OMS. '.repeat(10)),
            mockDraftPost('linkedin', 'LinkedIn: Inwestycja w nieruchomości. '.repeat(12)),
          ],
        },
      });
    } else {
      await route.continue();
    }
  });

  // Mock SSE endpoint — return minimal heartbeat
  await page.route('**/events**', async (route) => {
    await route.fulfill({
      contentType: 'text/event-stream',
      body: ': heartbeat\n\n',
    });
  });

  // Mock approve endpoint
  await page.route(`**/runs/${RUN_ID}/approve`, async (route) => {
    await route.fulfill({ json: { status: 'accepted' } });
  });

  await page.goto('/');

  // Open New Run dialog
  await page.getByRole('button', { name: 'New Run' }).click();
  await expect(page.getByText('Trigger manual run')).toBeVisible();

  // Submit without URL
  await page.getByRole('button', { name: 'Start' }).click();

  // Run should appear selected in sidebar
  await expect(page.getByText('awaiting review').first()).toBeVisible({ timeout: 5000 });

  // PostEditor should be visible
  await expect(page.getByTestId('post-editor')).toBeVisible({ timeout: 5000 });

  // PipelineView shows Review stage as active
  await expect(page.getByText('Review')).toBeVisible();

  // Switch to LinkedIn tab
  await page.getByRole('button', { name: 'LinkedIn' }).click();
  await expect(page.getByRole('textbox')).toContainText('LinkedIn');

  // Switch back to Facebook and approve
  await page.getByRole('button', { name: 'Facebook' }).click();
  await page.getByRole('button', { name: 'Approve & Publish' }).click();

  // Success toast appears
  await expect(page.getByText(/Run approved/)).toBeVisible({ timeout: 3000 });
});

test('activity log shows events', async ({ page }) => {
  await page.route('**/runs', async (route) => {
    await route.fulfill({ json: [mockRun] });
  });

  await page.route(`**/runs/${RUN_ID}`, async (route) => {
    await route.fulfill({
      json: {
        ...mockRun,
        events: [
          {
            id: 'evt-1',
            run_id: RUN_ID,
            agent: 'orchestrator',
            event_type: 'run_started',
            payload: {},
            created_at: new Date().toISOString(),
          },
        ],
        draft_posts: [
          mockDraftPost('facebook', 'F'.repeat(350)),
          mockDraftPost('instagram', 'I'.repeat(250)),
          mockDraftPost('linkedin', 'L'.repeat(450)),
        ],
      },
    });
  });

  await page.route('**/events**', async (route) => {
    await route.fulfill({
      contentType: 'text/event-stream',
      body: ': heartbeat\n\n',
    });
  });

  await page.goto('/');

  // Click on the run in sidebar
  await page.getByText(RUN_ID.slice(0, 8)).click();

  // Activity Log should show the event
  await expect(page.getByText('run started')).toBeVisible({ timeout: 5000 });
});
