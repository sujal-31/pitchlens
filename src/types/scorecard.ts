export interface CategoryScore {
  category: string;
  score: number; // 1-10
  reasoning: string;
  suggestions: string[];
}

export interface Scorecard {
  id: string;
  analysis_id: string;
  deck_id: string;
  overall_score: number;
  category_scores: CategoryScore[];
  verdict_summary: string;
  category_ranking: string[];
  failed_categories: string[];
  created_at: string; // ISO timestamp
}

export interface EvaluationListItem {
  id: string;
  deck_name: string;
  overall_score: number;
  created_at: string;
}

export interface PaginatedEvaluations {
  items: EvaluationListItem[];
  total: number;
  page: number;
  page_size: number;
}
