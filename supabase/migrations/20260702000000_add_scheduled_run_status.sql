-- Gate: add 'scheduled' run status — approved via email or in-app "Approve & Schedule",
-- content stored, publishing deferred to the Thursday 5PM scheduler job.
ALTER TYPE run_status ADD VALUE 'scheduled' AFTER 'awaiting_review';
