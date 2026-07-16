/**
 * Determines the color range for a given score.
 * - 1-3: 'low' (red)
 * - 4-6: 'mid' (amber)
 * - 7-10: 'high' (green)
 *
 * Returns 'low' for scores outside the valid 1-10 range (error state).
 */
export function getScoreColor(score: number): 'low' | 'mid' | 'high' {
  if (score >= 7 && score <= 10) return 'high';
  if (score >= 4 && score <= 6) return 'mid';
  return 'low';
}

/**
 * Returns the Tailwind background class for the score color.
 */
export function getScoreColorClass(score: number): string {
  const color = getScoreColor(score);
  switch (color) {
    case 'high':
      return 'bg-green-500';
    case 'mid':
      return 'bg-amber-500';
    case 'low':
      return 'bg-red-500';
  }
}

/**
 * Returns the Tailwind text class for the score color.
 */
export function getScoreTextColorClass(score: number): string {
  const color = getScoreColor(score);
  switch (color) {
    case 'high':
      return 'text-green-600 dark:text-green-400';
    case 'mid':
      return 'text-amber-600 dark:text-amber-400';
    case 'low':
      return 'text-red-600 dark:text-red-400';
  }
}

/**
 * Returns whether a score is valid (within 1-10 range).
 */
export function isValidScore(score: number): boolean {
  return Number.isInteger(score) && score >= 1 && score <= 10;
}
