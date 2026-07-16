import { getScoreColorClass, getScoreTextColorClass, isValidScore } from '../lib/scoreUtils';

interface ScoreGaugeProps {
  score: number;
  label?: string;
}

/**
 * Renders a score gauge with a filled bar proportional to the score (1-10).
 * Color coded: 1-3 red, 4-6 amber, 7-10 green.
 * Shows an error state for scores outside the valid 1-10 range.
 */
export default function ScoreGauge({ score, label }: ScoreGaugeProps) {
  if (!isValidScore(score)) {
    return (
      <div className="space-y-1">
        {label && (
          <div className="flex justify-between items-center">
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">{label}</span>
            <span className="text-sm font-bold text-red-600 dark:text-red-400">Invalid</span>
          </div>
        )}
        <div className="w-full h-3 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
          <div
            className="h-full bg-red-500 rounded-full animate-pulse"
            style={{ width: '100%' }}
            role="progressbar"
            aria-valuenow={score}
            aria-valuemin={1}
            aria-valuemax={10}
            aria-invalid="true"
            aria-label={label ? `${label}: invalid score ${score}` : `Invalid score ${score}`}
          />
        </div>
        <p className="text-xs text-red-600 dark:text-red-400">
          Score {score} is outside the valid range (1-10)
        </p>
      </div>
    );
  }

  const percentage = (score / 10) * 100;
  const colorClass = getScoreColorClass(score);
  const textColorClass = getScoreTextColorClass(score);

  return (
    <div className="space-y-1">
      {label && (
        <div className="flex justify-between items-center">
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">{label}</span>
          <span className={`text-sm font-bold ${textColorClass}`}>{score}/10</span>
        </div>
      )}
      <div className="w-full h-3 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
        <div
          className={`h-full ${colorClass} rounded-full transition-all duration-500`}
          style={{ width: `${percentage}%` }}
          role="progressbar"
          aria-valuenow={score}
          aria-valuemin={1}
          aria-valuemax={10}
          aria-label={label ? `${label}: ${score} out of 10` : `${score} out of 10`}
        />
      </div>
    </div>
  );
}
