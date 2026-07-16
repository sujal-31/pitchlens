export type PipelineStage =
  | "extracting"
  | "scoring_market"
  | "scoring_team"
  | "scoring_business_model"
  | "scoring_competition"
  | "aggregating"
  | "complete"
  | "failed";

export interface WSEvent {
  event_type: "stage_change" | "heartbeat" | "partial_result" | "complete" | "error";
  stage?: PipelineStage;
  data?: Record<string, unknown>;
  timestamp: string;
}
