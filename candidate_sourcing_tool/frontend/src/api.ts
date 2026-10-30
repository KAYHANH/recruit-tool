import type {
  BackupItem,
  Candidate,
  DashboardMetrics,
  GitHubSearchResult,
  Job,
  JobRequirements,
  RankedResult,
  SearchHistoryItem,
  SearchQueryItem,
  SystemSettings,
  PipelineData,
  FullCandidateProfile,
  XRaySearchPlan,
  CVImportJob,
  CVImportJobFile,
  ReferralCandidate,
  ReferralOpportunity,
  CandidateOpportunityMatch,
  OutreachDraft,
  CVOutreachOverview,
  GmailAuthStatus,
} from './types';

const BASE_URL = '';

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errorDetail = `Request failed with status ${res.status}`;
    try {
      const data = await res.json();
      if (data && data.detail) {
        errorDetail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
      }
    } catch {
      // ignore json parse error
    }
    throw new Error(errorDetail);
  }
  return res.json();
}

export const api = {
  // Health & Overview
  async getHealth() {
    const res = await fetch(`${BASE_URL}/api/health`);
    return handleResponse<{ status: string; service: string; version: string; zero_budget_spend: string }>(res);
  },

  async getOverview(): Promise<DashboardMetrics> {
    const res = await fetch(`${BASE_URL}/api/overview`);
    return handleResponse<DashboardMetrics>(res);
  },

  // Jobs
  async getJobs(): Promise<Job[]> {
    const res = await fetch(`${BASE_URL}/api/jobs`);
    return handleResponse<Job[]>(res);
  },

  async getJob(id: number): Promise<Job> {
    const res = await fetch(`${BASE_URL}/api/jobs/${id}`);
    return handleResponse<Job>(res);
  },

  async createJob(payload: { title: string; jd_text: string; location?: string; extracted_data?: string }): Promise<Job> {
    const res = await fetch(`${BASE_URL}/api/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return handleResponse<Job>(res);
  },

  async updateJob(id: number, payload: Partial<{ title: string; jd_text: string; location: string; extracted_data: string }>): Promise<Job> {
    const res = await fetch(`${BASE_URL}/api/jobs/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return handleResponse<Job>(res);
  },

  async deleteJob(id: number): Promise<{ message: string }> {
    const res = await fetch(`${BASE_URL}/api/jobs/${id}`, {
      method: 'DELETE',
    });
    return handleResponse<{ message: string }>(res);
  },

  async getJobRecommendedSources(jobId: number) {
    const res = await fetch(`${BASE_URL}/api/jobs/${jobId}/recommended-sources`);
    return handleResponse<{
      job_id: number;
      job_title: string;
      role_family: string;
      recommended_sources: string[];
      policy: any;
    }>(res);
  },

  // Parsing & Analysis
  async parseDocument(file: File): Promise<{ filename: string; text: string; character_count: number }> {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${BASE_URL}/api/parse-document`, {
      method: 'POST',
      body: formData,
    });
    return handleResponse<{ filename: string; text: string; character_count: number }>(res);
  },

  async analyzeJd(payload: { jd_text: string; engine?: 'local' | 'groq'; groq_model?: string; session_key?: string }): Promise<{
    engine: string;
    model: string;
    message: string;
    requirements: JobRequirements;
    title_extraction: {
      title: string;
      alternative_titles: string[];
      confidence_score: number;
      confidence_level: string;
    };
  }> {
    const res = await fetch(`${BASE_URL}/api/analyze-jd`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return handleResponse(res);
  },

  // Search & Queries
  async getJobQueries(jobId: number): Promise<{
    job_id: number;
    job_title: string;
    target_location: string;
    queries: SearchQueryItem[];
    history_count: number;
  }> {
    const res = await fetch(`${BASE_URL}/api/jobs/${jobId}/queries`);
    return handleResponse(res);
  },

  async logSearch(jobId: number, payload: { query_text: string; strategy?: string; provider?: string }): Promise<{ message: string; history_id: number }> {
    const res = await fetch(`${BASE_URL}/api/jobs/${jobId}/log-search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return handleResponse(res);
  },

  async getSearchHistory(jobId: number): Promise<SearchHistoryItem[]> {
    const res = await fetch(`${BASE_URL}/api/jobs/${jobId}/search-history`);
    return handleResponse<SearchHistoryItem[]>(res);
  },

  async searchGitHub(payload: { keywords: string; location?: string; limit?: number }): Promise<GitHubSearchResult> {
    const res = await fetch(`${BASE_URL}/api/search/github`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return handleResponse<GitHubSearchResult>(res);
  },

  // Candidates
  async getCandidates(params?: { job_id?: number; status?: string; search?: string }): Promise<Candidate[]> {
    const url = new URL(`${window.location.origin}/api/candidates`);
    if (params?.job_id) url.searchParams.set('job_id', params.job_id.toString());
    if (params?.status) url.searchParams.set('status', params.status);
    if (params?.search) url.searchParams.set('search', params.search);
    const res = await fetch(url.toString());
    return handleResponse<Candidate[]>(res);
  },

  async getCandidate(id: number): Promise<Candidate> {
    const res = await fetch(`${BASE_URL}/api/candidates/${id}`);
    return handleResponse<Candidate>(res);
  },

  async createCandidate(payload: Partial<Candidate> & { name: string; evidence_text: string; job_id?: number }): Promise<Candidate> {
    const res = await fetch(`${BASE_URL}/api/candidates`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return handleResponse<Candidate>(res);
  },

  async updateCandidate(id: number, payload: Partial<Candidate>): Promise<Candidate> {
    const res = await fetch(`${BASE_URL}/api/candidates/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return handleResponse<Candidate>(res);
  },

  async deleteCandidate(id: number): Promise<{ message: string }> {
    const res = await fetch(`${BASE_URL}/api/candidates/${id}`, {
      method: 'DELETE',
    });
    return handleResponse<{ message: string }>(res);
  },

  // Ranking
  async rankCandidates(jobId: number, payload?: {
    target_location?: string;
    include_all_candidates?: boolean;
    status_filter?: string;
  }): Promise<{
    job_id: number;
    job_title: string;
    target_location: string;
    total_evaluated: number;
    results: RankedResult[];
  }> {
    const res = await fetch(`${BASE_URL}/api/jobs/${jobId}/rank`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    return handleResponse(res);
  },

  // Shortlist
  async getShortlist(jobId?: number): Promise<Candidate[]> {
    const url = new URL(`${window.location.origin}/api/shortlist`);
    if (jobId) url.searchParams.set('job_id', jobId.toString());
    const res = await fetch(url.toString());
    return handleResponse<Candidate[]>(res);
  },

  async removeFromShortlist(candidateId: number): Promise<{ message: string }> {
    const res = await fetch(`${BASE_URL}/api/candidates/${candidateId}/remove-shortlist`, {
      method: 'POST',
    });
    return handleResponse<{ message: string }>(res);
  },

  getExportShortlistUrl(jobId?: number): string {
    return jobId ? `/api/export/shortlist?job_id=${jobId}` : '/api/export/shortlist';
  },

  // Settings & Backups
  async getSettings(): Promise<SystemSettings> {
    const res = await fetch(`${BASE_URL}/api/settings`);
    return handleResponse<SystemSettings>(res);
  },

  async testGroq(payload?: { session_key?: string; model?: string }): Promise<{
    success: boolean;
    model: string;
    latency_ms: number;
    message: string;
    raw_preview?: string;
  }> {
    const res = await fetch(`${BASE_URL}/api/settings/test-groq`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    return handleResponse(res);
  },

  async testGitHub(): Promise<SystemSettings['github_search']> {
    const res = await fetch(`${BASE_URL}/api/settings/test-github`, {
      method: 'POST',
    });
    return handleResponse(res);
  },

  async getBackups(): Promise<BackupItem[]> {
    const res = await fetch(`${BASE_URL}/api/backups`);
    return handleResponse<BackupItem[]>(res);
  },

  async createBackup(): Promise<{ success: boolean; filename: string; size_kb: number; message: string }> {
    const res = await fetch(`${BASE_URL}/api/backups/create`, {
      method: 'POST',
    });
    return handleResponse(res);
  },

  async restoreBackup(file: File): Promise<{ success: boolean; message: string; safety_snapshot?: string }> {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${BASE_URL}/api/backups/restore`, {
      method: 'POST',
      body: formData,
    });
    return handleResponse(res);
  },

  // Automated Sourcing Engine & Run Management
  async startSearchRun(payload: { job_id: number; enabled_sources?: string[]; limit_per_source?: number; strategy_keys?: string[] }): Promise<{
    run_id: string;
    job_id: number;
    status: string;
    current_stage: string;
    progress_percent: number;
    enabled_sources: string[];
    started_at: string;
    message: string;
  }> {
    const res = await fetch(`${BASE_URL}/api/search-runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return handleResponse(res);
  },

  async getSearchRunStatus(runId: string): Promise<any> {
    const res = await fetch(`${BASE_URL}/api/search-runs/${runId}`);
    return handleResponse(res);
  },

  async getSearchRunResults(runId: string): Promise<{
    run_id: string;
    job_id: number;
    status: string;
    candidates: any[];
    total_results: number;
  }> {
    const res = await fetch(`${BASE_URL}/api/search-runs/${runId}/results`);
    return handleResponse(res);
  },

  async cancelSearchRun(runId: string): Promise<{ message: string }> {
    const res = await fetch(`${BASE_URL}/api/search-runs/${runId}/cancel`, {
      method: 'POST',
    });
    return handleResponse(res);
  },

  async getSearchRuns(jobId?: number): Promise<any[]> {
    const url = jobId ? `${BASE_URL}/api/search-runs?job_id=${jobId}` : `${BASE_URL}/api/search-runs`;
    const res = await fetch(url);
    return handleResponse<any[]>(res);
  },

  // Recruiter Feedback
  async submitFeedback(candidateId: number, rating: string, feedbackText: string = '', jobId?: number): Promise<any> {
    const res = await fetch(`${BASE_URL}/api/candidates/${candidateId}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rating, feedback_text: feedbackText, job_id: jobId }),
    });
    return handleResponse(res);
  },

  async getFeedback(candidateId: number): Promise<any[]> {
    const res = await fetch(`${BASE_URL}/api/candidates/${candidateId}/feedback`);
    return handleResponse<any[]>(res);
  },

  // Rich Overview Stats
  async getOverviewStats(): Promise<any> {
    const res = await fetch(`${BASE_URL}/api/overview-stats`);
    return handleResponse(res);
  },

  // Central Cost Guard & Strict ₹0 Verification
  async getCostGuard(): Promise<any> {
    const res = await fetch(`${BASE_URL}/api/cost-guard`);
    return handleResponse(res);
  },

  // Target-Company & Talent-Pool Mapping (Recruiting-Skills-for-AI-Agents)
  async getTalentPool(roleTitle: string, skills: string = ''): Promise<any> {
    const url = new URL(`${BASE_URL}/api/talent-pool/${encodeURIComponent(roleTitle)}`);
    if (skills) url.searchParams.set('skills', skills);
    const res = await fetch(url.toString());
    return handleResponse(res);
  },

  // Candidate Pipeline & Full Profiles
  async getJobPipeline(jobId: number): Promise<PipelineData> {
    const res = await fetch(`${BASE_URL}/api/jobs/${jobId}/pipeline`);
    return handleResponse<PipelineData>(res);
  },

  async updateCandidateStage(
    jobId: number,
    candidateId: number,
    stage: string,
    note: string = '',
    actor: string = 'Recruiter',
  ): Promise<{ success: boolean; job_id: number; candidate_id: number; stage: string }> {
    const res = await fetch(`${BASE_URL}/api/jobs/${jobId}/candidates/${candidateId}/stage`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stage, note, actor }),
    });
    return handleResponse(res);
  },

  async getCandidateFullProfile(candidateId: number, jobId?: number): Promise<FullCandidateProfile> {
    const url = jobId
      ? `${BASE_URL}/api/candidates/${candidateId}/full-profile?job_id=${jobId}`
      : `${BASE_URL}/api/candidates/${candidateId}/full-profile`;
    const res = await fetch(url);
    return handleResponse<FullCandidateProfile>(res);
  },

  async addCandidateNote(
    candidateId: number,
    note: string,
    author: string = 'Recruiter',
    jobId?: number,
  ): Promise<{ success: boolean; candidate_id: number }> {
    const res = await fetch(`${BASE_URL}/api/candidates/${candidateId}/notes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note, author, job_id: jobId }),
    });
    return handleResponse(res);
  },

  async addCandidateActivity(
    candidateId: number,
    activity: { activity_type: string; title: string; details?: string; actor?: string; job_id?: number },
  ): Promise<{ success: boolean; activity_id?: number }> {
    const res = await fetch(`${BASE_URL}/api/candidates/${candidateId}/activities`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(activity),
    });
    return handleResponse(res);
  },

  async getXRayPlan(jobId: number): Promise<XRaySearchPlan> {
    const res = await fetch(`${BASE_URL}/api/jobs/${jobId}/xray-plan`);
    return handleResponse<XRaySearchPlan>(res);
  },

  async launchXRayBatch(jobId: number, payload?: { max_queries?: number; strategy_keys?: string[] }): Promise<{
    job_id: number;
    job_title: string;
    batch_size: number;
    launched_strategies: Array<{ key: string; name: string; google_url: string; bing_url: string }>;
    direct_urls: string[];
    message: string;
  }> {
    const res = await fetch(`${BASE_URL}/api/jobs/${jobId}/xray-plan/launch-batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    return handleResponse(res);
  },

  async executeXRayPlan(jobId: number, payload?: { strategy_keys?: string[]; max_strategies?: number; limit_per_strategy?: number; enabled_sources?: string[] }): Promise<{
    run_id: string;
    job_id: number;
    status: string;
    current_stage: string;
    progress_percent: number;
    strategies_queued: string[];
    message: string;
  }> {
    const res = await fetch(`${BASE_URL}/api/jobs/${jobId}/xray-plan/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    return handleResponse(res);
  },

  // Groq AI Reasoning & Orchestration Layer
  async getAiSearchPlan(jobId: number): Promise<{ job_id: number; job_title: string; plan: any }> {
    const res = await fetch(`${BASE_URL}/api/jobs/${jobId}/ai-search-plan`, {
      method: 'POST',
    });
    return handleResponse(res);
  },

  async explainCandidateMatch(candidateId: number, jobId: number): Promise<{ candidate_id: number; job_id: number; explanation: any }> {
    const res = await fetch(`${BASE_URL}/api/candidates/${candidateId}/explain-match`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: jobId }),
    });
    return handleResponse(res);
  },

  async checkDuplicateCandidates(candidateA: any, candidateB: any): Promise<{
    is_likely_same_person: boolean;
    confidence: number;
    shared_signals: string[];
    conflicting_signals: string[];
    rationale: string;
  }> {
    const res = await fetch(`${BASE_URL}/api/candidates/dedup-check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ candidate_a: candidateA, candidate_b: candidateB }),
    });
    return handleResponse(res);
  },

  async calibrateJobFeedback(jobId: number, feedbackItems?: any[]): Promise<{ job_id: number; calibration: any }> {
    const res = await fetch(`${BASE_URL}/api/jobs/${jobId}/calibrate-feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(feedbackItems ? { feedback_items: feedbackItems } : {}),
    });
    return handleResponse(res);
  },

  async getJobStrategyVersions(jobId: number): Promise<any[]> {
    const res = await fetch(`${BASE_URL}/api/jobs/${jobId}/strategy-versions`);
    return handleResponse<any[]>(res);
  },

  async getProfileIntelligence(candidateId: number, jobId?: number): Promise<{
    candidate_id: number;
    job_id?: number;
    intelligence: {
      supported_skills: Array<{ skill: string; evidence: string; confidence: string }>;
      projects: Array<{ name: string; description: string; technologies: string[] }>;
      tenure_signals: string[];
      public_contact_or_links: string[];
      vanity_signals: string[];
      uncertainty_flags: string[];
    };
  }> {
    const res = await fetch(`${BASE_URL}/api/candidates/${candidateId}/profile-intelligence`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(jobId ? { job_id: jobId } : {}),
    });
    return handleResponse(res);
  },

  // CV Import & Referral Outreach
  async startFolderImport(folderPath: string, batchSize: number = 15, runAsync: boolean = false): Promise<{
    success: boolean;
    job_id: string;
    status: string;
    total_files: number;
    message: string;
  }> {
    const res = await fetch(`${BASE_URL}/api/cv-import/folder`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_path: folderPath, batch_size: batchSize, run_async: runAsync }),
    });
    return handleResponse(res);
  },

  async startZipImport(file: File, batchSize: number = 15, runAsync: boolean = false): Promise<{
    success: boolean;
    job_id: string;
    status: string;
    total_files: number;
    message: string;
  }> {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${BASE_URL}/api/cv-import/zip?batch_size=${batchSize}&run_async=${runAsync}`, {
      method: 'POST',
      body: formData,
    });
    return handleResponse(res);
  },

  async getImportJobs(limit: number = 50): Promise<CVImportJob[]> {
    const res = await fetch(`${BASE_URL}/api/cv-import/jobs?limit=${limit}`);
    return handleResponse<CVImportJob[]>(res);
  },

  async getImportJob(jobId: string): Promise<CVImportJob> {
    const res = await fetch(`${BASE_URL}/api/cv-import/jobs/${jobId}`);
    return handleResponse<CVImportJob>(res);
  },

  async getImportJobFiles(jobId: string, limit: number = 200, offset: number = 0): Promise<CVImportJobFile[]> {
    const res = await fetch(`${BASE_URL}/api/cv-import/jobs/${jobId}/files?limit=${limit}&offset=${offset}`);
    return handleResponse<CVImportJobFile[]>(res);
  },

  async cancelImportJob(jobId: string): Promise<{ success: boolean; job_id: string; message: string }> {
    const res = await fetch(`${BASE_URL}/api/cv-import/jobs/${jobId}/cancel`, {
      method: 'POST',
    });
    return handleResponse(res);
  },

  async retryImportJob(jobId: string, batchSize: number = 15): Promise<{ success: boolean; job_id: string; message: string }> {
    const res = await fetch(`${BASE_URL}/api/cv-import/jobs/${jobId}/retry?batch_size=${batchSize}`, {
      method: 'POST',
    });
    return handleResponse(res);
  },

  async getReferralCandidates(search: string = '', optOutOnly: boolean = false, limit: number = 100): Promise<ReferralCandidate[]> {
    const url = new URL(`${window.location.origin}/api/referrals/candidates`);
    if (search) url.searchParams.set('search', search);
    if (optOutOnly) url.searchParams.set('opt_out_only', 'true');
    url.searchParams.set('limit', limit.toString());
    const res = await fetch(url.toString());
    return handleResponse<ReferralCandidate[]>(res);
  },

  async setCandidateOptOut(candidateId: number, optOut: boolean, reason: string = ''): Promise<{
    success: boolean;
    candidate_id: number;
    opt_out_status: number;
    suppression_reason: string;
    message: string;
  }> {
    const res = await fetch(`${BASE_URL}/api/referrals/candidates/${candidateId}/opt-out`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ opt_out: optOut, reason }),
    });
    return handleResponse(res);
  },

  async setCandidatePermissionBasis(candidateId: number, permissionBasis: string): Promise<{
    success: boolean;
    candidate_id: number;
    permission_basis: string;
  }> {
    const res = await fetch(`${BASE_URL}/api/referrals/candidates/${candidateId}/permission`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ permission_basis: permissionBasis }),
    });
    return handleResponse(res);
  },

  async getCVOutreachOverview(): Promise<CVOutreachOverview> {
    const res = await fetch(`${BASE_URL}/api/referrals/overview`);
    return handleResponse<CVOutreachOverview>(res);
  },

  async getReferralOpportunities(isActive: boolean = true): Promise<ReferralOpportunity[]> {
    const res = await fetch(`${BASE_URL}/api/referrals/opportunities?is_active=${isActive}`);
    return handleResponse<ReferralOpportunity[]>(res);
  },

  async createReferralOpportunity(data: Partial<ReferralOpportunity>): Promise<any> {
    const res = await fetch(`${BASE_URL}/api/referrals/opportunities`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return handleResponse(res);
  },

  async addReferralLink(opportunityId: number, url: string, ownerLabel: string = 'Recruiter Link', eligibilityNotes: string = ''): Promise<any> {
    const res = await fetch(`${BASE_URL}/api/referrals/opportunities/${opportunityId}/links`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, owner_label: ownerLabel, eligibility_notes: eligibilityNotes }),
    });
    return handleResponse(res);
  },

  async evaluateMatches(minScore: number = 40): Promise<{ success: boolean; matches_evaluated: number; message: string }> {
    const res = await fetch(`${BASE_URL}/api/referrals/matches/evaluate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ min_score: minScore }),
    });
    return handleResponse(res);
  },

  async getMatches(opportunityId?: number, minScore?: number): Promise<CandidateOpportunityMatch[]> {
    const url = new URL(`${window.location.origin}/api/referrals/matches`);
    if (opportunityId) url.searchParams.set('opportunity_id', opportunityId.toString());
    if (minScore !== undefined) url.searchParams.set('min_score', minScore.toString());
    const res = await fetch(url.toString());
    return handleResponse<CandidateOpportunityMatch[]>(res);
  },

  async updateMatchDecision(matchId: number, decision: string, notes: string = ''): Promise<any> {
    const res = await fetch(`${BASE_URL}/api/referrals/matches/${matchId}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, notes }),
    });
    return handleResponse(res);
  },

  async getGmailAuthStatus(): Promise<GmailAuthStatus> {
    const res = await fetch(`${BASE_URL}/api/gmail/auth-status`);
    return handleResponse<GmailAuthStatus>(res);
  },

  async previewDraft(candidateId: number, opportunityId: number, referralLinkId?: number): Promise<any> {
    const res = await fetch(`${BASE_URL}/api/referrals/drafts/preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        candidate_id: candidateId,
        opportunity_id: opportunityId,
        referral_link_id: referralLinkId,
      }),
    });
    return handleResponse(res);
  },

  async createDraft(data: {
    candidate_id: number;
    opportunity_id: number;
    referral_link_id?: number;
    subject?: string;
    body_text?: string;
    save_to_gmail?: boolean;
    mock_mode?: boolean;
  }): Promise<any> {
    const res = await fetch(`${BASE_URL}/api/referrals/drafts/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        save_to_gmail: true,
        mock_mode: true,
        ...data,
      }),
    });
    return handleResponse(res);
  },

  async getDrafts(status?: string): Promise<OutreachDraft[]> {
    const url = new URL(`${window.location.origin}/api/referrals/drafts`);
    if (status) url.searchParams.set('status', status);
    const res = await fetch(url.toString());
    return handleResponse<OutreachDraft[]>(res);
  },

  async updateDraftStatus(draftId: number, status: string): Promise<any> {
    const res = await fetch(`${BASE_URL}/api/referrals/drafts/${draftId}/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    });
    return handleResponse(res);
  },
};


