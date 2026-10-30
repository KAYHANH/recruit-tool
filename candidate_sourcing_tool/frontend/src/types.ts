export interface Job {
  id: number;
  title: string;
  jd_text: string;
  location: string;
  extracted_data: string;
  created_at: string;
  candidate_count?: number;
}

export interface Candidate {
  id: number;
  name: string;
  profile_url?: string;
  github_url?: string;
  gitlab_url?: string;
  stackoverflow_url?: string;
  huggingface_url?: string;
  portfolio_url?: string;
  headline?: string;
  company?: string;
  location?: string;
  experience?: string;
  source?: string;
  evidence_text: string;
  notes?: string;
  status: string;
  email?: string;
  phone?: string;
  contact_provenance?: string;
  contact_status?: string;
  evidence_ladder_tier?: string;
  created_at?: string;
  job_ids?: number[];
  match_score?: number;
}


export interface JobRequirements {
  job_title: string;
  alternative_titles: string[];
  core_skills: string[];
  required_skills?: string[];
  preferred_skills: string[];
  tools_and_technologies: string[];
  tools_and_tech?: string[];
  domain_keywords: string[];
  inferred_keywords?: string[];
  certifications: string[];
  education: string[];
  education_or_certifications?: string[];
  experience_years?: number | null;
  experience_level?: string;
  location?: string;
  work_arrangement?: string;
  uncertain_items?: string[];
}

export interface SearchQueryItem {
  id: string;
  label: string;
  strategy: string;
  query_text: string;
  description: string;
  google_url: string;
  bing_url: string;
  is_repeated: boolean;
  last_executed_at?: string | null;
}

export interface SearchHistoryItem {
  id: number;
  job_id: number;
  query_text: string;
  strategy: string;
  provider: string;
  executed_at: string;
  status: string;
}

export interface CriterionScore {
  criterion: string;
  score: number;
  max_score: number;
  status: 'FULL' | 'PARTIAL' | 'NOT_MET' | 'NEUTRAL';
  matched_items: string[];
  missing_items: string[];
  explanation: string;
}

export interface CandidateEvaluation {
  total_score: number;
  percentage: number;
  recommendation: 'STRONG_MATCH' | 'GOOD_MATCH' | 'POTENTIAL_MATCH' | 'LOW_MATCH' | 'NO_MATCH';
  summary: string;
  criteria_scores: Record<string, CriterionScore>;
  matched_evidence: string[];
  is_fallback: boolean;
}

export interface RankedResult {
  candidate: Candidate;
  evaluation: CandidateEvaluation;
}

export interface DashboardMetrics {
  total_jobs: number;
  total_candidates: number;
  needing_review: number;
  shortlisted: number;
  recent_jobs: Job[];
  recent_candidates: Candidate[];
  recent_searches: SearchHistoryItem[];
}

export interface GitHubCandidate {
  name: string;
  github_url: string;
  bio?: string;
  company?: string;
  location?: string;
  blog?: string;
  public_repos?: number;
  followers?: number;
  email?: string;
  evidence_text: string;
  contact_provenance?: string;
  contact_status?: string;
}

export interface GitHubSearchResult {
  total_found: number;
  rate_limited: boolean;
  message: string;
  candidates: GitHubCandidate[];
}

export interface SystemSettings {
  zero_budget_policy: {
    spend_permitted: string;
    paid_apis_enabled: boolean;
    status: string;
  };
  local_extractor: {
    status: string;
    offline_cpu: boolean;
    telemetry: string;
  };
  groq_extractor: {
    active_model: string;
    api_key_configured: boolean;
    free_tier_only: boolean;
  };
  github_search: {
    status: string;
    rate_limited: boolean;
    remaining: number;
    limit: number;
    reset_time: string;
    message: string;
  };
  database: {
    file: string;
    size_kb: number;
  };
}

export interface BackupItem {
  filename: string;
  size_kb: number;
  created_at: string;
}

export interface SearchRun {
  run_id: string;
  job_id: number;
  status: string;
  current_stage: string;
  progress_percent: number;
  enabled_sources: string[];
  total_raw_found: number;
  total_unique_found: number;
  total_duplicates: number;
  total_saved: number;
  source_stats: Record<string, any>;
  strategy_tasks?: Record<string, {
    strategy_key: string;
    strategy_name: string;
    status: string;
    results_count: number;
    error_message?: string;
    started_at?: string;
    completed_at?: string;
  }>;
  reconciled_counters?: {
    raw_source_results: number;
    valid_profile_leads: number;
    total_duplicates: number;
    total_unique_found: number;
    newly_inserted_count: number;
    updated_count: number;
    associated_job_count: number;
    sourced_stage_count: number;
    rejected_count: number;
  };
  error_message?: string;
  started_at: string;
  completed_at?: string;
  duration_seconds?: number;
}

export interface RecruiterFeedback {
  id: number;
  candidate_id: number;
  job_id?: number;
  rating: string;
  feedback_text?: string;
  created_at: string;
}

export interface OverviewStats {
  total_jobs: number;
  total_candidates: number;
  needing_review: number;
  shortlisted: number;
  archived: number;
  contacts_found: number;
  source_breakdown: Record<string, number>;
  recent_jobs: Job[];
  recent_candidates: Candidate[];
  recent_runs: SearchRun[];
  zero_budget_enforced: boolean;
  spend_amount: string;
}

export interface VerifiedConnector {
  name: string;
  cost: string;
  rate_limit: string;
  status: string;
  authenticated: boolean;
}

export interface PipelineCandidate {
  id: number;
  name: string;
  profile_url?: string;
  headline?: string;
  company?: string;
  location?: string;
  years_of_experience: number;
  experience_badge: string;
  experience?: string;
  source?: string;
  email?: string;
  phone?: string;
  github_url?: string;
  portfolio_url?: string;
  linkedin_url?: string;
  contact_status?: string;
  contact_provenance?: string;
  evidence_ladder_tier?: string;
  added_by?: string;
  created_at?: string;
  candidate_notes?: string;
  raw_stage?: string;
  stage: string;
  match_score?: number;
  match_details?: string;
  job_notes?: string;
  updated_at?: string;
}

export interface PipelineStage {
  id: string;
  name: string;
  color: string;
  count: number;
  candidates: PipelineCandidate[];
}

export interface PipelineData {
  job_id: number;
  job_title: string;
  total_candidates: number;
  stages: PipelineStage[];
}

export interface WorkExperience {
  id: number;
  candidate_id: number;
  company: string;
  title: string;
  start_date: string;
  end_date: string;
  duration: string;
  description: string;
  skills: string[];
  is_current: number;
  source: string;
}

export interface CandidateActivity {
  id: number;
  candidate_id: number;
  job_id?: number | null;
  activity_type: string;
  title: string;
  details: string;
  actor: string;
  created_at: string;
}

export interface AssociatedJobInfo {
  job_id: number;
  job_title: string;
  job_location?: string;
  stage: string;
  match_score: number;
  updated_at?: string;
  created_at?: string;
}

export interface EvidenceQuote {
  quote: string;
  source: string;
  url: string;
}

export interface ProfileAnalysis {
  job_id: number | null;
  job_title: string;
  match_score: number;
  tier: string;
  matched_required_skills: string[];
  matched_preferred_skills: string[];
  missing_skills: string[];
  coverage_percent: number;
  evidence_quotes: EvidenceQuote[];
  recommendation: string;
}

export interface CandidateResumeInfo {
  has_resume: boolean;
  resume_text: string;
  resume_filename: string;
  resume_source: string;
  resume_uploaded_at: string;
}

export interface CandidateContacts {
  email: string;
  phone: string;
  linkedin_url: string;
  github_url: string;
  portfolio_url: string;
  gitlab_url: string;
  stackoverflow_url: string;
  huggingface_url: string;
  contact_status: string;
  contact_provenance: string;
}

export interface FullCandidateProfile {
  id: number;
  name: string;
  headline?: string;
  company?: string;
  location?: string;
  years_of_experience: number;
  total_experience_str: string;
  source: string;
  profile_url?: string;
  added_by: string;
  created_at: string;
  stage: string;
  notes?: string;
  evidence_ladder_tier: string;
  highlights: string[];
  work_experiences: WorkExperience[];
  skills: string[];
  contacts: CandidateContacts;
  analysis: ProfileAnalysis;
  resume: CandidateResumeInfo;
  activities: CandidateActivity[];
  associated_jobs: AssociatedJobInfo[];
}

export interface XRayStrategy {
  key: string;
  name: string;
  target_platform: string;
  category: string;
  query_text: string;
  google_url: string;
  bing_url: string;
  description: string;
  search_operator_breakdown?: string[];
  operator_breakdown?: string[];
}

export interface XRaySearchPlan {
  job_id: number | null;
  job_title: string;
  location: string;
  strategies: XRayStrategy[];
  total_strategies: number;
  batch_urls: string[];
}

export interface CandidateFile {
  id: number;
  candidate_id: number;
  file_path: string;
  file_name: string;
  file_hash: string;
  file_size: number;
  file_type: string;
  parsing_status: string;
  parsing_error?: string;
  created_at: string;
  is_primary: number;
}

export interface CVImportJob {
  id: number;
  job_id: string;
  source_type: string;
  source_path: string;
  status: string;
  total_files: number;
  processed_files: number;
  successful_files: number;
  failed_files: number;
  duplicate_files: number;
  new_candidates: number;
  updated_candidates: number;
  error_message?: string;
  created_at: string;
  completed_at?: string;
}

export interface CVImportJobFile {
  id: number;
  job_id: string;
  file_path: string;
  file_name: string;
  file_size: number;
  file_type: string;
  status: string;
  error_message?: string;
  candidate_id?: number | null;
  processed_at?: string;
}

export interface ReferralCandidate extends Candidate {
  normalized_email?: string;
  skills?: string[] | string;
  skills_list?: string[];
  languages?: string[];
  contact_permission_basis?: 'PENDING_REVIEW' | 'UNVERIFIED' | 'APPROVED_OUTREACH' | 'DIRECT_CONSENT' | 'OPTED_OUT' | string;
  permission_reviewed_by?: string;
  permission_reviewed_at?: string;
  permission_notes?: string;
  email_verification_status?: 'EXTRACTED' | 'PENDING_VERIFICATION' | 'VERIFIED' | 'INVALID' | string;
  opt_out_status?: number;
  suppression_reason?: string;
  last_contacted_at?: string;
  files?: CandidateFile[];
  file_count?: number;
}

export interface ReferralOpportunity {
  id: number;
  platform: string;
  title: string;
  description: string;
  url: string;
  official_url?: string;
  referral_url?: string;
  requirements: string[];
  location_restrictions: string;
  language_requirements: string[];
  experience_years_min: number;
  verification_status: string;
  last_verified_at?: string;
  verification_source?: string;
  verification_notes?: string;
  verified_by?: string;
  verified_at?: string;
  expiry_date?: string;
  links?: Array<{ id: number; url: string; owner_label: string; eligibility_notes?: string }>;
}

export interface CandidateOpportunityMatch {
  id: number;
  candidate_id: number;
  opportunity_id: number;
  candidate_name: string;
  candidate_email?: string;
  candidate_phone?: string;
  candidate_location?: string;
  candidate_opt_out?: number;
  candidate_permission_basis?: string;
  candidate_email_verification_status?: string;
  opportunity_platform: string;
  opportunity_title: string;
  score: number;
  score_breakdown: {
    skills_score: number;
    experience_score: number;
    language_score: number;
    location_score: number;
    other_score: number;
  };
  matched_requirements: string[];
  missing_requirements: string[];
  contradictions: string[];
  recommendation: string;
  outreach_eligibility?: 'ELIGIBLE' | 'PENDING_REVIEW' | 'BLOCKED' | string;
  opportunity_verification_status: string;
  reviewer_decision?: string;
  reviewer_notes?: string;
}

export interface OutreachDraft {
  id: number;
  idempotency_key: string;
  candidate_id: number;
  opportunity_id: number;
  candidate_name: string;
  opportunity_platform: string;
  opportunity_title: string;
  referral_url?: string;
  recipient_email: string;
  subject: string;
  body_text: string;
  gmail_draft_id?: string;
  status: string;
  created_at: string;
}

export interface CVOutreachOverview {
  total_imported_files: number;
  total_candidates: number;
  cv_candidates: number;
  active_opportunities: number;
  total_matches: number;
  high_confidence_matches: number;
  total_drafts: number;
  drafts_created_in_gmail: number;
  suppressed_candidates: number;
}

export interface GmailAuthStatus {
  authenticated: boolean;
  scope: string;
  token_file_present: boolean;
  credentials_file_present: boolean;
  message: string;
}




