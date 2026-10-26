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

/**
 * In the 800 baseline matrix, only 390px and 1440px are whole-document
 * frames. Opened source-editor and selected-detail states are separate
 * screenshots: all THREE supported phone widths need the lower form/table,
 * not only 390px. Retain prior 1440px capture policy.
 * Other viewport screenshots are deliberately unchanged.
 */
export const EXPANDED_INTERACTION_FULL_PAGE_WIDTHS = Object.freeze([360, 390, 430, 1440]);

export function requiresExpandedInteractionFullPageReview(width) {
  return EXPANDED_INTERACTION_FULL_PAGE_WIDTHS.includes(width);
}
