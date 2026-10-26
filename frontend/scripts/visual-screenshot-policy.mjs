/**
 * Stage #71: preserve comparable long-page evidence for both effective themes.
 * 390px phone and 1440px desktop are the designated FULL_PAGE review widths.
 * Other widths retain their viewport captures in the existing 800-case matrix.
 * Never select screenshot depth by theme.mode: system themes must get parity.
 */
export const FULL_PAGE_REVIEW_WIDTHS = Object.freeze([390, 1440]);

export function requiresFullPageReview(width) {
  return FULL_PAGE_REVIEW_WIDTHS.includes(width);
}

/**
 * The desktop workspace has an independently scrollable .nfc-page-content
 * inside a fixed 100dvh shell, invisible to Chromium fullPage screenshots.
 * Review its bottom at our full-page desktop evidence width, never treating
 * a screenshot as human approval.
 */
export const WORKSPACE_SCROLL_REVIEW_WIDTH = 1440;

export function requiresWorkspaceScrollReview(width, route) {
  return width === WORKSPACE_SCROLL_REVIEW_WIDTH && route !== '/login';
}
