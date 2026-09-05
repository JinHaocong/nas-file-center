export interface OperationJournalEntry {
  id: number;
  operation: string;
  sequence: number;
  plan_id: number | null;
  plan_item_id: number | null;
  task_id: number | null;
  user_id: number | null;
  before: Record<string, any>;
  after: Record<string, any>;
  metadata_before: Record<string, any>;
  metadata_after: Record<string, any>;
  created_at: string;
}

export interface OperationJournalListResponse {
  items: OperationJournalEntry[];
  total: number;
  page: number;
  page_size: number;
}

export interface UndoPlanResponse {
  id: number;
  name: string;
  kind: string;
  status: string;
  total_items: number;
}
