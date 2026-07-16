export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  cited_sections?: string[];
  created_at: string;
}
