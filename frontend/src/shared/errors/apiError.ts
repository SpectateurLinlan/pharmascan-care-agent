/** Pure backend contract; no transport, browser or UI dependencies. */
export interface ApiErrorBody {
  code: string;
  message: string;
  rule_id: string | null;
}

export class ApiError extends Error {
  readonly code: string;
  readonly ruleId: string | null;
  readonly status: number;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = 'ApiError';
    this.status = status;
    this.code = body.code;
    this.ruleId = body.rule_id;
  }
}
