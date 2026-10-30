import React, { useEffect, useState, useRef } from 'react';
import {
  Sparkles,
  ExternalLink,
  Copy,
  Check,
  Plus,
  Loader2,
  AlertCircle,
  Briefcase,
  MapPin,
  Building,
  Mail,
  Globe,
  Star,
  CheckCircle2,
  ThumbsUp,
  ThumbsDown,
  HelpCircle,
  Eye,
  StopCircle,
  Database,
  ChevronDown,
  ChevronUp,
  ArrowRight,
  ShieldCheck,
  Compass,
  Clock,
} from 'lucide-react';
import { GithubIcon } from '../components/GithubIcon';
import { api } from '../api';
import type { Job, SearchQueryItem, SearchRun, XRaySearchPlan, XRayStrategy } from '../types';

interface FindCandidatesViewProps {
  jobs: Job[];
  activeJobId: number | null;
  onSelectJob: (id: number) => void;
  onCandidateAdded: () => void;
  onNavigate?: (view: string) => void;
}

export const FindCandidatesView: React.FC<FindCandidatesViewProps> = ({
  jobs,
  activeJobId,
  onSelectJob,
  onCandidateAdded,
  onNavigate,
}) => {
  const [activeTab, setActiveTab] = useState<'automated' | 'xray' | 'manual'>('automated');

  // Automated Sourcing State
  const [enabledSources, setEnabledSources] = useState<string[]>([
    'github',
    'gitlab',
    'stackoverflow',
    'huggingface',
    'local_db',
    'groq_browser',
  ]);
  const [limitPerSource, setLimitPerSource] = useState(5);
  const [currentRunId, setCurrentRunId] = useState<string | null>(null);
  const [runProgress, setRunProgress] = useState<SearchRun | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [discoveredCandidates, setDiscoveredCandidates] = useState<any[]>([]);
  const [searchError, setSearchError] = useState<string | null>(null);

  // Repository-Informed Talent Mapping & Cost Guard State
  const [talentPool, setTalentPool] = useState<any | null>(null);
  const [costGuardInfo, setCostGuardInfo] = useState<any | null>(null);
  const [recommendedSourcesInfo, setRecommendedSourcesInfo] = useState<{
    job_id: number;
    job_title: string;
    role_family: string;
    recommended_sources: string[];
    policy: {
      primary: string[];
      secondary: string[];
      excluded_or_low_priority: string[];
      rationale: string;
    };
  } | null>(null);

  // Selected candidate detail drawer/modal
  const [selectedCandidate, setSelectedCandidate] = useState<any | null>(null);
  const [feedbackRating, setFeedbackRating] = useState<string>('');
  const [feedbackNotes, setFeedbackNotes] = useState<string>('');
  const [savingFeedback, setSavingFeedback] = useState(false);
  const [feedbackSavedMsg, setFeedbackSavedMsg] = useState<string | null>(null);

  // Manual Candidate Intake Form State
  const [manualForm, setManualForm] = useState({
    name: '',
    profile_url: '',
    github_url: '',
    portfolio_url: '',
    headline: '',
    company: '',
    location: '',
    email: '',
    phone: '',
    evidence_text: '',
    notes: '',
  });
  const [savingManual, setSavingManual] = useState(false);
  const [manualFeedback, setManualFeedback] = useState<{ type: 'success' | 'error'; msg: string } | null>(null);

  // X-Ray Queries & Strategy Plan State (Strategies A through G)
  const [queries, setQueries] = useState<SearchQueryItem[]>([]);
  const [xrayPlan, setXRayPlan] = useState<XRaySearchPlan | null>(null);
  const [loadingQueries, setLoadingQueries] = useState(false);
  const [loadingXRay, setLoadingXRay] = useState(false);
  const [copiedQueryId, setCopiedQueryId] = useState<string | null>(null);
  const [launchingBatch, setLaunchingBatch] = useState(false);
  const [batchSuccessMsg, setBatchSuccessMsg] = useState<string | null>(null);
  const [showXRayDetails, setShowXRayDetails] = useState(true);
  const [loadingAiExplanation, setLoadingAiExplanation] = useState(false);
  const [calibratingStrategy, setCalibratingStrategy] = useState(false);
  const [calibrationResultMsg, setCalibrationResultMsg] = useState<string | null>(null);
  const [strategyVersions, setStrategyVersions] = useState<any[]>([]);

  const activeJob = jobs.find((j) => j.id === activeJobId) || jobs[0];
  const pollIntervalRef = useRef<any>(null);

  // Helper to render 4-tier evidence model badges
  const renderEvidenceTierBadge = (tier?: string) => {
    if (!tier) return null;
    if (tier.includes('Tier 1')) {
      return (
        <span
          className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-300"
          title="Tier 1: Strong Technical Evidence (Verified active repositories, artifacts, and core skill alignment)"
        >
          ⚡ {tier}
        </span>
      );
    }
    if (tier.includes('Tier 2')) {
      return (
        <span
          className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold bg-blue-50 text-blue-700 border border-blue-300"
          title="Tier 2: Moderate Technical Evidence (Verified platform profile with projects or skills alignment)"
        >
          🔹 {tier}
        </span>
      );
    }
    if (tier.includes('Tier 3')) {
      return (
        <span
          className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-amber-50 text-amber-700 border border-amber-300"
          title="Tier 3: Weak / Contextual Signal (Community activity or generic profile mentions)"
        >
          🔸 {tier}
        </span>
      );
    }
    return (
      <span
        className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-gray-100 text-gray-600 border border-gray-300"
        title="Tier 4: Insufficient Evidence (Minimal or unverified profile data)"
      >
        ⚪ {tier}
      </span>
    );
  };

  const renderContactBadge = (status?: string, email?: string, phone?: string) => {
    if (email || phone || status?.includes('Publicly published') || status?.includes('Available')) {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
          <Mail className="w-3 h-3 text-emerald-600" />
          {email || 'Contact Details Available'}
        </span>
      );
    }
    if (status?.includes('Profile Only') || status?.includes('Checked') || status?.includes('Profile')) {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-indigo-50 text-indigo-700 border border-indigo-200">
          <Globe className="w-3 h-3 text-indigo-600" />
          Profile Link Only
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] text-gray-400 bg-gray-50 border border-gray-200">
        <Mail className="w-3 h-3 text-gray-300" />
        No Public Email
      </span>
    );
  };

  // Load queries, X-Ray plan, talent mapping, and recommended sources when job changes
  useEffect(() => {
    if (activeJob) {
      loadJobQueries(activeJob.id);
      loadXRayPlan(activeJob.id);
      loadRecentRuns(activeJob.id);
      loadTalentPool(activeJob.title);
      loadStrategyVersions(activeJob.id);
      loadRecommendedSources(activeJob.id);
    }
  }, [activeJob?.id, activeJob?.title]);

  const loadRecommendedSources = async (jobId: number) => {
    try {
      const rec = await api.getJobRecommendedSources(jobId);
      setRecommendedSourcesInfo(rec);
      if (rec?.recommended_sources && rec.recommended_sources.length > 0) {
        setEnabledSources(rec.recommended_sources);
      }
    } catch (err) {
      console.error('Failed to load recommended sources:', err);
    }
  };

  const loadStrategyVersions = async (jobId: number) => {
    try {
      const vers = await api.getJobStrategyVersions(jobId);
      setStrategyVersions(vers || []);
    } catch {
      setStrategyVersions([]);
    }
  };

  const loadXRayPlan = async (jobId: number) => {
    try {
      setLoadingXRay(true);
      const plan = await api.getXRayPlan(jobId);
      setXRayPlan(plan);
    } catch (err) {
      console.error('Failed to load X-Ray plan:', err);
    } finally {
      setLoadingXRay(false);
    }
  };

  const handleLaunchBatch = async (maxQueries: number = 4) => {
    if (!activeJob) return;
    setLaunchingBatch(true);
    setBatchSuccessMsg(null);
    try {
      const res = await api.launchXRayBatch(activeJob.id, { max_queries: maxQueries });
      // Open direct URLs in new browser tabs
      res.direct_urls.forEach((url) => {
        window.open(url, '_blank', 'noopener,noreferrer');
      });
      setBatchSuccessMsg(`🚀 Launched ${res.batch_size} X-Ray search strategies in your browser. All queries recorded to job history.`);
      setTimeout(() => setBatchSuccessMsg(null), 8000);
    } catch (err: any) {
      console.error('Batch launch failed:', err);
    } finally {
      setLaunchingBatch(false);
    }
  };

  const handleExecuteStrategies = async (strategyKeys?: string[]) => {
    if (!activeJob) return;
    setIsSearching(true);
    setSearchError(null);
    setDiscoveredCandidates([]);
    setRunProgress(null);
    setBatchSuccessMsg(null);
    try {
      const res = await api.executeXRayPlan(activeJob.id, {
        strategy_keys: strategyKeys,
        max_strategies: strategyKeys ? strategyKeys.length : 7,
        limit_per_strategy: 3,
        enabled_sources: enabledSources.includes('groq_browser') ? enabledSources : [...enabledSources, 'groq_browser'],
      });
      setCurrentRunId(res.run_id);
      setBatchSuccessMsg(`⚡ Executing ${res.strategies_queued?.length || (strategyKeys ? strategyKeys.length : 7)} sourcing strategies automatically via Groq Browser Search engine.`);
      setTimeout(() => setBatchSuccessMsg(null), 8000);

      // Start Polling Run Status
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = setInterval(() => pollRunStatus(res.run_id), 1000);
    } catch (err: any) {
      console.error('Failed to execute strategies:', err);
      setSearchError(err.message || 'Failed to start automated strategy search.');
      setIsSearching(false);
    }
  };

  // Load cost guard on mount
  useEffect(() => {
    api.getCostGuard().then(setCostGuardInfo).catch(() => {});
  }, []);

  // Clean up poll interval on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  const loadTalentPool = async (roleTitle: string) => {
    try {
      const data = await api.getTalentPool(roleTitle);
      setTalentPool(data);
    } catch (err) {
      console.error('Failed to load talent pool:', err);
    }
  };

  const loadJobQueries = async (jobId: number) => {
    try {
      setLoadingQueries(true);
      const res = await api.getJobQueries(jobId);
      setQueries(res.queries);
    } catch (err) {
      console.error('Failed to load queries:', err);
    } finally {
      setLoadingQueries(false);
    }
  };

  const loadRecentRuns = async (jobId: number) => {
    try {
      const runs = await api.getSearchRuns(jobId);
      if (runs && runs.length > 0) {
        const latest = runs[0];
        setRunProgress(latest);
        if (latest.status === 'COMPLETED' || latest.status === 'PARTIAL') {
          const res = await api.getSearchRunResults(latest.run_id);
          setDiscoveredCandidates(res.candidates || []);
        }
      }
    } catch (err) {
      console.error('Failed to load recent runs:', err);
    }
  };

  // Automated Sourcing: Trigger Run
  const handleStartAutomatedSearch = async () => {
    if (!activeJob) return;
    setIsSearching(true);
    setSearchError(null);
    setDiscoveredCandidates([]);
    setRunProgress(null);

    try {
      const res = await api.startSearchRun({
        job_id: activeJob.id,
        enabled_sources: enabledSources,
        limit_per_source: limitPerSource,
      });

      setCurrentRunId(res.run_id);

      // Start Polling Run Status
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = setInterval(() => pollRunStatus(res.run_id), 1000);
    } catch (err: any) {
      setSearchError(err.message || 'Failed to initiate candidate sourcing run.');
      setIsSearching(false);
    }
  };

  const pollRunStatus = async (runId: string) => {
    try {
      const statusRes = await api.getSearchRunStatus(runId);
      setRunProgress(statusRes);

      if (['COMPLETED', 'PARTIAL', 'FAILED', 'CANCELLED'].includes(statusRes.status)) {
        clearInterval(pollIntervalRef.current);
        setIsSearching(false);

        // Fetch final discovered candidates
        const resultsRes = await api.getSearchRunResults(runId);
        setDiscoveredCandidates(resultsRes.candidates || []);
        onCandidateAdded();
      }
    } catch (err) {
      console.error('Polling error:', err);
    }
  };

  const handleCancelRun = async () => {
    if (!currentRunId) return;
    try {
      await api.cancelSearchRun(currentRunId);
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      setIsSearching(false);
      setRunProgress((prev) => (prev ? { ...prev, status: 'CANCELLED', current_stage: 'Cancelled by recruiter' } : null));
    } catch (err: any) {
      console.error('Failed to cancel run:', err);
    }
  };

  const toggleSource = (sourceKey: string) => {
    setEnabledSources((prev) =>
      prev.includes(sourceKey) ? prev.filter((s) => s !== sourceKey) : [...prev, sourceKey]
    );
  };

  // Recruiter Feedback Submission
  const handleSubmitFeedback = async (rating: string) => {
    if (!selectedCandidate) return;
    setSavingFeedback(true);
    setFeedbackSavedMsg(null);
    try {
      await api.submitFeedback(selectedCandidate.id, rating, feedbackNotes, activeJob?.id);
      setFeedbackRating(rating);
      setFeedbackSavedMsg(`Feedback recorded as "${rating}".`);
      onCandidateAdded();
    } catch (err: any) {
      console.error('Failed to save feedback:', err);
    } finally {
      setSavingFeedback(false);
    }
  };

  const handleQuickShortlist = async (cand: any) => {
    try {
      await api.updateCandidate(cand.id, { status: 'Shortlisted' });
      setDiscoveredCandidates((prev) =>
        prev.map((c) => (c.id === cand.id ? { ...c, status: 'Shortlisted' } : c))
      );
      if (selectedCandidate && selectedCandidate.id === cand.id) {
        setSelectedCandidate({ ...selectedCandidate, status: 'Shortlisted' });
      }
      onCandidateAdded();
    } catch (err: any) {
      console.error('Failed to shortlist:', err);
    }
  };

  const handleRequestAiExplanation = async () => {
    if (!selectedCandidate || !activeJob) return;
    setLoadingAiExplanation(true);
    try {
      const [explainResult, intelResult] = await Promise.allSettled([
        api.explainCandidateMatch(selectedCandidate.id, activeJob.id),
        api.getProfileIntelligence(selectedCandidate.id, activeJob.id),
      ]);
      let detailsObj: any = {};
      if (typeof selectedCandidate.match_details === 'string') {
        try {
          detailsObj = JSON.parse(selectedCandidate.match_details || '{}');
        } catch {
          detailsObj = {};
        }
      } else if (selectedCandidate.match_details) {
        detailsObj = { ...selectedCandidate.match_details };
      }
      if (explainResult.status === 'fulfilled' && explainResult.value?.explanation) {
        detailsObj.ai_explanation = explainResult.value.explanation;
      }
      if (intelResult.status === 'fulfilled' && intelResult.value?.intelligence) {
        detailsObj.profile_intelligence = intelResult.value.intelligence;
      }
      setSelectedCandidate({
        ...selectedCandidate,
        match_details: detailsObj,
      });
    } catch (err: any) {
      console.error('Failed to generate AI match explanation and intelligence:', err);
    } finally {
      setLoadingAiExplanation(false);
    }
  };

  const handleCalibrateStrategy = async () => {
    if (!activeJob) return;
    setCalibratingStrategy(true);
    setCalibrationResultMsg(null);
    try {
      const res = await api.calibrateJobFeedback(activeJob.id);
      if (res && res.calibration) {
        setCalibrationResultMsg(
          `Strategy calibrated: ${res.calibration.changes_summary}`
        );
        const vers = await api.getJobStrategyVersions(activeJob.id);
        setStrategyVersions(vers);
      }
    } catch (err: any) {
      setCalibrationResultMsg(`Calibration failed: ${err.message}`);
    } finally {
      setCalibratingStrategy(false);
    }
  };

  // Manual Candidate Submission
  const handleSaveManualCandidate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!manualForm.name.trim()) {
      setManualFeedback({ type: 'error', msg: 'Candidate name is required.' });
      return;
    }
    setSavingManual(true);
    setManualFeedback(null);
    try {
      await api.createCandidate({
        ...manualForm,
        source: 'Manual entry',
        job_id: activeJob?.id,
      });
      setManualFeedback({ type: 'success', msg: `Candidate "${manualForm.name}" added successfully.` });
      setManualForm({
        name: '',
        profile_url: '',
        github_url: '',
        portfolio_url: '',
        headline: '',
        company: '',
        location: '',
        email: '',
        phone: '',
        evidence_text: '',
        notes: '',
      });
      onCandidateAdded();
    } catch (err: any) {
      setManualFeedback({ type: 'error', msg: err.message || 'Failed to save candidate.' });
    } finally {
      setSavingManual(false);
    }
  };

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedQueryId(id);
    setTimeout(() => setCopiedQueryId(null), 2000);
  };

  // Parse requirements summary for badge display
  let coreSkills: string[] = [];
  if (activeJob?.extracted_data) {
    try {
      const parsed = JSON.parse(activeJob.extracted_data);
      coreSkills = parsed.required_skills || parsed.core_skills || [];
    } catch {
      coreSkills = [];
    }
  }

  return (
    <div className="space-y-6">
      {/* Header and Job Context Bar */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 bg-white p-5 rounded-xl border border-gray-200 shadow-sm">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-2xl font-bold text-gray-900">Find Candidates</h1>
            <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 border border-emerald-200 flex items-center gap-1.5 shadow-2xs">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
              Cost Guard: ₹0.00 Spend Enforced
            </span>
            {costGuardInfo && (
              <span className="text-[11px] text-gray-500 bg-gray-50 px-2 py-0.5 rounded border border-gray-200">
                {costGuardInfo.verified_free_connectors?.length || 5} Free Connectors Active
              </span>
            )}
          </div>
          <p className="text-gray-500 text-sm mt-1">
            Automated candidate discovery across verified zero-cost public platforms and your local talent database.
          </p>
        </div>

        {/* Job Selector Dropdown */}
        <div className="flex items-center gap-3">
          <label className="text-sm font-medium text-gray-700 whitespace-nowrap">Active Job:</label>
          <select
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm font-medium text-gray-900 bg-gray-50 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none min-w-[220px]"
            value={activeJob?.id || ''}
            onChange={(e) => onSelectJob(Number(e.target.value))}
          >
            {jobs.map((j) => (
              <option key={j.id} value={j.id}>
                {j.title} (#{j.id})
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Selected Job Context Card & Talent Pool Mapping */}
      {activeJob && (
        <div className="bg-gradient-to-r from-blue-50 via-indigo-50 to-white p-5 rounded-xl border border-blue-200 space-y-3">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <Briefcase className="w-4 h-4 text-blue-600" />
                <span className="font-semibold text-gray-900">{activeJob.title}</span>
                {activeJob.location && (
                  <span className="text-xs text-gray-500 flex items-center gap-1">
                    <MapPin className="w-3 h-3" /> {activeJob.location}
                  </span>
                )}
              </div>
              <div className="flex flex-wrap gap-1.5 mt-2">
                {coreSkills.slice(0, 6).map((skill, idx) => (
                  <span key={idx} className="bg-white/80 border border-blue-200 text-blue-800 text-xs px-2 py-0.5 rounded-md font-medium">
                    {skill}
                  </span>
                ))}
                {coreSkills.length > 6 && (
                  <span className="text-xs text-gray-500 self-center">+{coreSkills.length - 6} more skills</span>
                )}
              </div>
            </div>
            <div className="text-right flex items-center gap-3">
              <span className="text-xs text-gray-500">
                Total candidates saved: <strong className="text-gray-900">{activeJob.candidate_count || 0}</strong>
              </span>
            </div>
          </div>

          {/* Target-Company & Talent-Pool Mapping (Recruiting-Skills-for-AI-Agents & talent-intelligence-os) */}
          {talentPool && (
            <div className="pt-3 border-t border-blue-200/70 space-y-2">
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className="font-semibold text-indigo-950 flex items-center gap-1">
                  <Building className="w-3.5 h-3.5 text-indigo-600" />
                  Target Peer Companies:
                </span>
                {talentPool.target_companies?.slice(0, 7).map((comp: string, i: number) => (
                  <span
                    key={i}
                    className="px-2 py-0.5 rounded-md text-[11px] font-medium bg-indigo-50 text-indigo-800 border border-indigo-200/80"
                  >
                    {comp}
                  </span>
                ))}
              </div>

              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className="font-semibold text-slate-700 flex items-center gap-1">
                  <Briefcase className="w-3.5 h-3.5 text-slate-500" />
                  Adjacent Role Titles:
                </span>
                {talentPool.adjacent_titles?.slice(0, 4).map((title: string, i: number) => (
                  <span
                    key={i}
                    className="px-2 py-0.5 rounded-md text-[11px] font-medium bg-slate-100 text-slate-700 border border-slate-200"
                  >
                    {title}
                  </span>
                ))}
                <span className="text-[11px] text-indigo-600 font-semibold ml-auto">
                  Domain: {talentPool.domain_display || talentPool.domain}
                </span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Sourcing Navigation Tabs */}
      <div className="flex border-b border-gray-200">
        <button
          onClick={() => setActiveTab('automated')}
          className={`flex items-center gap-2 px-5 py-3 text-sm font-semibold border-b-2 transition-colors ${
            activeTab === 'automated'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
          }`}
        >
          <Sparkles className="w-4 h-4 text-amber-500" />
          Automated Discovery Engine
        </button>
        <button
          onClick={() => setActiveTab('manual')}
          className={`flex items-center gap-2 px-5 py-3 text-sm font-semibold border-b-2 transition-colors ${
            activeTab === 'manual'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
          }`}
        >
          <Plus className="w-4 h-4" />
          Manual Intake / CV Paste
        </button>
        <button
          onClick={() => setActiveTab('xray')}
          className={`flex items-center gap-2 px-5 py-3 text-sm font-semibold border-b-2 transition-colors ${
            activeTab === 'xray'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
          }`}
        >
          <Globe className="w-4 h-4" />
          Manual Search Links (Browser Fallback)
        </button>
      </div>

      {/* TAB 1: AUTOMATED DISCOVERY ENGINE */}
      {activeTab === 'automated' && (
        <div className="space-y-6">
          {/* Sourcing Configuration & Run Panel */}
          <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm space-y-5">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-gray-100 pb-4">
              <div>
                <h3 className="text-base font-bold text-gray-900">Eligible Zero-Budget Platform Connectors</h3>
                <p className="text-xs text-gray-500 mt-0.5">
                  The engine automatically queries enabled sources, normalizes records, removes cross-source duplicates, and scores candidates.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <label className="text-xs font-medium text-gray-600">Limit per source:</label>
                <select
                  value={limitPerSource}
                  onChange={(e) => setLimitPerSource(Number(e.target.value))}
                  disabled={isSearching}
                  className="border border-gray-300 rounded px-2 py-1 text-xs text-gray-800 bg-white"
                >
                  <option value={3}>3 candidates</option>
                  <option value={5}>5 candidates</option>
                  <option value={10}>10 candidates</option>
                </select>
              </div>
            </div>

            {/* JD-Aware Role Family Recommendation Banner */}
            {recommendedSourcesInfo && (
              <div className="p-3.5 bg-gradient-to-r from-blue-50/70 via-indigo-50/50 to-slate-50 border border-blue-200/80 rounded-lg text-xs space-y-1.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-gray-900 flex items-center gap-1.5">
                      <Sparkles className="w-3.5 h-3.5 text-indigo-600" />
                      Role Family Detected:
                    </span>
                    <span className="px-2 py-0.5 rounded-full font-bold bg-indigo-100 text-indigo-800 border border-indigo-200 capitalize">
                      {recommendedSourcesInfo.role_family.replace(/_/g, ' ')}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setEnabledSources(recommendedSourcesInfo.recommended_sources)}
                      className="px-2.5 py-1 text-[11px] font-semibold text-blue-700 bg-white border border-blue-300 rounded hover:bg-blue-50 transition-colors shadow-2xs"
                    >
                      Apply Recommended Sources ({recommendedSourcesInfo.recommended_sources.length})
                    </button>
                    <button
                      type="button"
                      onClick={() => setEnabledSources(['github', 'gitlab', 'stackoverflow', 'huggingface', 'local_db', 'groq_browser'])}
                      className="px-2 py-1 text-[11px] font-medium text-gray-600 bg-white border border-gray-200 rounded hover:bg-gray-50 transition-colors"
                    >
                      Select All
                    </button>
                  </div>
                </div>
                <p className="text-[11px] text-gray-600 leading-relaxed">
                  <strong>Source Policy:</strong> {recommendedSourcesInfo.policy?.rationale}
                </p>
              </div>
            )}

            {/* Source Toggles */}
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-3 lg:grid-cols-6 gap-3">
              {[
                { id: 'github', label: 'GitHub Public API', icon: GithubIcon, color: 'text-purple-600', badge: 'Devs & Repos' },
                { id: 'gitlab', label: 'GitLab Public API', icon: Globe, color: 'text-orange-600', badge: 'Projects & Creators' },
                { id: 'stackoverflow', label: 'Stack Overflow', icon: Globe, color: 'text-amber-600', badge: 'Tech Contributors' },
                { id: 'huggingface', label: 'Hugging Face', icon: Globe, color: 'text-yellow-600', badge: 'AI & ML Creators' },
                { id: 'local_db', label: 'Local Rediscovery', icon: Database, color: 'text-emerald-600', badge: 'Existing DB' },
                { id: 'groq_browser', label: 'Groq Browser Search', icon: Compass, color: 'text-cyan-600', badge: 'Web & X-Ray Search' },
              ].map((src) => {
                const isChecked = enabledSources.includes(src.id);
                const isRecommended = recommendedSourcesInfo?.recommended_sources?.includes(src.id);
                const isLowPriority = recommendedSourcesInfo?.policy?.excluded_or_low_priority?.includes(src.id);
                return (
                  <button
                    key={src.id}
                    type="button"
                    disabled={isSearching}
                    onClick={() => toggleSource(src.id)}
                    className={`flex flex-col p-3 rounded-lg border text-left transition-all ${
                      isChecked
                        ? 'border-blue-500 bg-blue-50/50 ring-1 ring-blue-500/20'
                        : 'border-gray-200 bg-gray-50 opacity-60 hover:opacity-100'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-xs text-gray-900">{src.label}</span>
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={() => {}}
                        className="rounded text-blue-600 focus:ring-blue-500 w-3.5 h-3.5"
                      />
                    </div>
                    <div className="flex items-center justify-between mt-1 gap-1">
                      <span className="text-[10px] text-gray-500">{src.badge}</span>
                      {isRecommended && (
                        <span className="text-[9px] font-bold text-emerald-700 bg-emerald-100/80 px-1 py-0.5 rounded border border-emerald-300">
                          ★ Recommended
                        </span>
                      )}
                      {isLowPriority && !isRecommended && (
                        <span className="text-[9px] font-medium text-amber-700 bg-amber-50 px-1 py-0.5 rounded border border-amber-200">
                          Low Rel
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Sourcing Action Buttons */}
            <div className="flex items-center gap-3 pt-2">
              <button
                type="button"
                disabled={isSearching || enabledSources.length === 0}
                onClick={handleStartAutomatedSearch}
                className="flex items-center gap-2 px-6 py-3 rounded-lg text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 transition-all shadow-sm"
              >
                {isSearching ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Finding Candidates Automatically...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-4 h-4 text-amber-300" />
                    ⚡ Run Automated Candidate Discovery
                  </>
                )}
              </button>

              {isSearching && (
                <button
                  type="button"
                  onClick={handleCancelRun}
                  className="flex items-center gap-2 px-4 py-3 rounded-lg text-sm font-semibold text-red-600 bg-red-50 hover:bg-red-100 transition-colors border border-red-200"
                >
                  <StopCircle className="w-4 h-4" />
                  Stop / Cancel
                </button>
              )}
            </div>

            {searchError && (
              <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{searchError}</span>
              </div>
            )}
          </div>

          {/* Google X-Ray & Boolean Sourcing Strategy Engine (Strategies A through G) */}
          <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm space-y-5">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-gray-100 pb-4">
              <div className="space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <h3 className="text-base font-bold text-gray-900 flex items-center gap-2">
                    <Compass className="w-5 h-5 text-indigo-600" />
                    Google X-Ray & Boolean Sourcing Engine
                  </h3>
                  <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-indigo-50 text-indigo-700 border border-indigo-200">
                    7 Role Strategies (A–G)
                  </span>
                  <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 flex items-center gap-1">
                    <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
                    Zero-Spend Direct Browser Launch
                  </span>
                </div>
                <p className="text-xs text-gray-500">
                  Target publicly indexed LinkedIn profiles, technical portfolios, public CVs/PDFs, and domain terminology directly in your browser without paid APIs or account logins.
                </p>
              </div>

              {/* Automated Execution & Manual Browser Fallback Buttons */}
              <div className="flex flex-wrap items-center gap-2 shrink-0">
                <button
                  type="button"
                  disabled={isSearching || !xrayPlan || xrayPlan.strategies.length === 0}
                  onClick={() => handleExecuteStrategies()}
                  className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-bold text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 transition-all shadow-sm"
                  title="Executes all 7 X-Ray sourcing strategies automatically via Groq Browser Search engine and imports real candidates"
                >
                  {isSearching ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      Executing Sourcing...
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-3.5 h-3.5 text-amber-300" />
                      ⚡ Execute 7 Strategies Auto
                    </>
                  )}
                </button>

                <button
                  type="button"
                  disabled={isSearching || !xrayPlan || xrayPlan.strategies.length === 0}
                  onClick={() => handleExecuteStrategies(xrayPlan?.strategies.slice(0, 4).map((s: XRayStrategy) => s.key))}
                  className="flex items-center gap-1 px-3 py-2 rounded-lg text-xs font-semibold text-indigo-700 bg-indigo-50 hover:bg-indigo-100 disabled:opacity-50 transition-colors border border-indigo-200"
                  title="Executes top 4 targeted strategies automatically via web search"
                >
                  ⚡ Execute Top 4
                </button>

                <button
                  type="button"
                  disabled={launchingBatch || !xrayPlan || xrayPlan.strategies.length === 0}
                  onClick={() => handleLaunchBatch(4)}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 disabled:opacity-50 transition-colors"
                  title="Opens direct Google search queries in new browser tabs (manual fallback)"
                >
                  {launchingBatch ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      Launching...
                    </>
                  ) : (
                    <>
                      <ExternalLink className="w-3.5 h-3.5" />
                      Browser Tabs (Manual)
                    </>
                  )}
                </button>

                <button
                  type="button"
                  onClick={() => setShowXRayDetails(!showXRayDetails)}
                  className="px-2.5 py-2 rounded-lg text-xs font-semibold text-gray-600 bg-gray-50 hover:bg-gray-100 transition-colors flex items-center gap-1 border border-gray-200"
                >
                  {showXRayDetails ? (
                    <>
                      Hide <ChevronUp className="w-3.5 h-3.5" />
                    </>
                  ) : (
                    <>
                      View All 7 <ChevronDown className="w-3.5 h-3.5" />
                    </>
                  )}
                </button>
              </div>
            </div>

            {batchSuccessMsg && (
              <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg text-emerald-800 text-xs flex items-center gap-2 font-medium">
                <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                <span>{batchSuccessMsg}</span>
              </div>
            )}

            {loadingXRay ? (
              <div className="text-center py-6">
                <Loader2 className="w-5 h-5 animate-spin text-indigo-600 mx-auto" />
                <p className="text-xs text-gray-500 mt-1.5">Generating 7-strategy search plan...</p>
              </div>
            ) : xrayPlan && showXRayDetails ? (
              <div className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {xrayPlan.strategies.map((strat: XRayStrategy) => (
                    <div
                      key={strat.key}
                      className="flex flex-col justify-between p-4 rounded-xl border border-gray-200 bg-slate-50/50 hover:bg-white hover:border-indigo-300 hover:shadow-sm transition-all space-y-3"
                    >
                      <div className="space-y-2">
                        <div className="flex items-start justify-between gap-2">
                          <span className="font-bold text-xs text-gray-900 leading-tight">
                            {strat.name}
                          </span>
                          <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-indigo-50 text-indigo-700 border border-indigo-200 shrink-0">
                            {strat.target_platform}
                          </span>
                        </div>
                        <p className="text-[11px] text-gray-500 line-clamp-2">{strat.description}</p>

                        {/* Operator breakdown tags */}
                        {((strat.operator_breakdown || strat.search_operator_breakdown) || []).length > 0 && (
                          <div className="flex flex-wrap gap-1">
                            {((strat.operator_breakdown || strat.search_operator_breakdown) || []).map((op: string, i: number) => (
                              <span
                                key={i}
                                className="text-[10px] font-mono px-1.5 py-0.5 bg-gray-100 text-gray-700 rounded border border-gray-200"
                              >
                                {op}
                              </span>
                            ))}
                          </div>
                        )}

                        {/* Boolean Query Box */}
                        <div className="bg-white p-2 rounded-lg border border-gray-200 font-mono text-[11px] text-gray-800 break-all select-all max-h-20 overflow-y-auto">
                          {strat.query_text}
                        </div>
                      </div>

                      {/* Strategy Actions */}
                      <div className="flex items-center justify-between pt-2 border-t border-gray-100">
                        <button
                          type="button"
                          onClick={() => copyToClipboard(strat.query_text, strat.key)}
                          className="flex items-center gap-1 text-[11px] font-medium text-gray-600 hover:text-indigo-600 transition-colors"
                        >
                          {copiedQueryId === strat.key ? (
                            <>
                              <Check className="w-3.5 h-3.5 text-emerald-600" />
                              <span className="text-emerald-600 font-bold">Copied!</span>
                            </>
                          ) : (
                            <>
                              <Copy className="w-3.5 h-3.5" />
                              Copy
                            </>
                          )}
                        </button>

                        <div className="flex items-center gap-1.5">
                          <button
                            type="button"
                            disabled={isSearching}
                            onClick={() => handleExecuteStrategies([strat.key])}
                            className="px-2 py-1 bg-indigo-600 hover:bg-indigo-700 text-white rounded text-[11px] font-semibold transition-colors flex items-center gap-1 shadow-2xs disabled:opacity-50"
                            title={`Execute ${strat.name} automatically via Groq Browser Search and import candidate results`}
                          >
                            <Sparkles className="w-3 h-3 text-amber-300" />
                            Run Auto
                          </button>
                          <a
                            href={strat.google_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="px-2 py-1 bg-white border border-gray-200 hover:border-indigo-400 rounded text-[11px] font-medium text-gray-600 hover:text-indigo-600 transition-colors shadow-2xs flex items-center gap-0.5"
                            title="Manual Google search in new browser tab"
                          >
                            Google ↗
                          </a>
                          <a
                            href={strat.bing_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="px-2 py-1 bg-white border border-gray-200 hover:border-indigo-400 rounded text-[11px] font-medium text-gray-600 hover:text-indigo-600 transition-colors shadow-2xs flex items-center gap-0.5"
                            title="Manual Bing search in new browser tab"
                          >
                            Bing ↗
                          </a>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="pt-2 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-gray-500">
                  <span className="flex items-center gap-1 text-emerald-700 font-medium">
                    <ShieldCheck className="w-4 h-4 text-emerald-600" />
                    Strict ₹0 Budget: Real candidate web discovery using openai/gpt-oss-120b browser_search or manual queries.
                  </span>
                  <button
                    type="button"
                    onClick={() => handleLaunchBatch(7)}
                    className="text-gray-500 hover:text-gray-700 hover:underline text-xs flex items-center gap-1"
                    title="Opens all 7 Google search queries in new browser tabs (manual fallback)"
                  >
                    <ExternalLink className="w-3 h-3" />
                    Open All 7 in Browser (Manual Fallback) →
                  </button>
                </div>
              </div>
            ) : null}
          </div>

          {/* Live Progress HUD */}
          {runProgress && (
            <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span
                    className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-bold ${
                      runProgress.status === 'COMPLETED'
                        ? 'bg-emerald-100 text-emerald-800'
                        : runProgress.status === 'CANCELLED'
                        ? 'bg-gray-100 text-gray-700'
                        : runProgress.status === 'FAILED'
                        ? 'bg-red-100 text-red-700'
                        : 'bg-blue-100 text-blue-800 animate-pulse'
                    }`}
                  >
                    {runProgress.status}
                  </span>
                  <span className="text-sm font-semibold text-gray-800">{runProgress.current_stage}</span>
                </div>
                <span className="text-xs font-semibold text-gray-500">{runProgress.progress_percent}%</span>
              </div>

              {/* Progress Bar */}
              <div className="w-full bg-gray-100 rounded-full h-2.5 overflow-hidden">
                <div
                  className="bg-blue-600 h-2.5 rounded-full transition-all duration-300"
                  style={{ width: `${runProgress.progress_percent}%` }}
                ></div>
              </div>

              {/* Source-by-Source Yield Badges */}
              {runProgress.source_stats && Object.keys(runProgress.source_stats).length > 0 && (
                <div className="flex flex-wrap gap-2 pt-1 border-t border-gray-100">
                  {Object.entries(runProgress.source_stats)
                    .filter(([k]) => !k.startsWith('_'))
                    .map(([k, v]: [string, any]) => (
                      <div
                        key={k}
                        className="flex items-center gap-1.5 px-2.5 py-1 bg-gray-50 border border-gray-200 rounded-md text-xs"
                      >
                        <span className="font-medium text-gray-700">{v.name}:</span>
                        <span className="font-bold text-gray-900">{v.found || 0} found</span>
                        {v.rate_limited && <span className="text-[10px] text-amber-600 font-bold">(Rate Limited)</span>}
                      </div>
                    ))}
                  <div className="ml-auto text-xs text-gray-500 self-center">
                    Unique: <strong className="text-gray-900">{runProgress.total_unique_found}</strong> | Duplicates
                    filtered: <strong className="text-gray-900">{runProgress.total_duplicates}</strong>
                  </div>
                </div>
              )}

              {/* Strategy-by-Strategy Sourcing Execution Pipeline (Strategies A-G) */}
              {((runProgress.strategy_tasks && Object.keys(runProgress.strategy_tasks).length > 0) ||
                (runProgress.source_stats?.groq_browser?.strategy_tasks) ||
                (runProgress.source_stats?._strategy_tasks)) && (() => {
                  const strats = runProgress.strategy_tasks || runProgress.source_stats?.groq_browser?.strategy_tasks || runProgress.source_stats?._strategy_tasks || {};
                  if (Object.keys(strats).length === 0) return null;
                  return (
                    <div className="pt-3 border-t border-gray-100 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-gray-800 flex items-center gap-1.5">
                          <Sparkles className="w-3.5 h-3.5 text-indigo-600" />
                          Sourcing Strategy Execution Pipeline (Strategies A–G)
                        </span>
                        <span className="text-[11px] text-gray-500 font-mono">
                          Automated Web Discovery
                        </span>
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2">
                        {Object.entries(strats).map(([k, s]: [string, any]) => {
                          const status = s.status || 'PENDING';
                          let badgeColor = 'bg-gray-100 text-gray-700 border-gray-200';
                          let icon = <Clock className="w-3 h-3 text-gray-500" />;
                          let label = 'Pending';

                          if (status === 'SEARCHING') {
                            badgeColor = 'bg-blue-50 text-blue-700 border-blue-300 animate-pulse';
                            icon = <Loader2 className="w-3 h-3 animate-spin text-blue-600" />;
                            label = 'Searching web...';
                          } else if (status === 'RESULTS_RETURNED') {
                            badgeColor = 'bg-emerald-50 text-emerald-800 border-emerald-300';
                            icon = <CheckCircle2 className="w-3 h-3 text-emerald-600" />;
                            label = `${s.results_count || 0} leads returned`;
                          } else if (status === 'NO_RESULTS') {
                            badgeColor = 'bg-amber-50 text-amber-700 border-amber-200';
                            icon = <AlertCircle className="w-3 h-3 text-amber-500" />;
                            label = 'No leads found';
                          } else if (status === 'RATE_LIMITED') {
                            badgeColor = 'bg-purple-50 text-purple-700 border-purple-200';
                            icon = <Clock className="w-3 h-3 text-purple-600" />;
                            label = 'Rate limited (Paused)';
                          } else if (status === 'FAILED') {
                            badgeColor = 'bg-red-50 text-red-700 border-red-200';
                            icon = <AlertCircle className="w-3 h-3 text-red-500" />;
                            label = 'Search failed';
                          } else if (status === 'SKIPPED') {
                            badgeColor = 'bg-slate-100 text-slate-600 border-slate-200';
                            icon = <ShieldCheck className="w-3 h-3 text-slate-400" />;
                            label = 'Skipped (Manual fallback)';
                          }

                          return (
                            <div
                              key={k}
                              className="p-2.5 rounded-lg border bg-white shadow-2xs flex flex-col justify-between space-y-1.5"
                            >
                              <div className="flex items-start justify-between gap-1">
                                <span className="text-[11px] font-bold text-gray-900 leading-tight">
                                  {s.name || k}
                                </span>
                                {s.target_platform && (
                                  <span className="text-[9px] font-mono px-1 py-0.2 bg-gray-50 text-gray-600 rounded border border-gray-200 shrink-0">
                                    {s.target_platform}
                                  </span>
                                )}
                              </div>
                              <div className="flex items-center justify-between text-[10px]">
                                <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border ${badgeColor} font-semibold`}>
                                  {icon}
                                  {label}
                                </span>
                                {s.duration_seconds > 0 && (
                                  <span className="text-gray-400 font-mono text-[9px]">{s.duration_seconds}s</span>
                                )}
                              </div>
                              {s.error_message && status !== 'RESULTS_RETURNED' && (
                                <p className="text-[10px] text-gray-500 line-clamp-1 italic" title={s.error_message}>
                                  {s.error_message}
                                </p>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })()}

              {/* Mathematical Candidate Reconciliation Ledger */}
              {((runProgress.reconciled_counters && Object.keys(runProgress.reconciled_counters).length > 0) ||
                (runProgress.source_stats?._reconciled_counters)) && (() => {
                  const rc = runProgress.reconciled_counters || runProgress.source_stats?._reconciled_counters;
                  return (
                    <div className="pt-3 border-t border-gray-100 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-gray-800 flex items-center gap-1.5">
                          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                          Candidate Reconciliation Ledger (Audited)
                        </span>
                        <span className="text-[11px] text-gray-500 font-mono">
                          SQLite DB Saved: <strong className="text-gray-900">{runProgress.total_saved}</strong>
                        </span>
                      </div>
                      <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-8 gap-2 text-center text-xs">
                        <div className="bg-slate-50 p-2 rounded border border-slate-200">
                          <div className="text-[10px] text-gray-500 uppercase font-semibold">Tasks Run</div>
                          <div className="font-bold text-gray-800 text-sm">{rc.search_tasks_attempted ?? '-'}</div>
                        </div>
                        <div className="bg-slate-50 p-2 rounded border border-slate-200">
                          <div className="text-[10px] text-gray-500 uppercase font-semibold">Raw Found</div>
                          <div className="font-bold text-gray-900 text-sm">{rc.raw_results_retrieved ?? rc.raw_source_results ?? runProgress.total_raw_found}</div>
                        </div>
                        <div className="bg-slate-50 p-2 rounded border border-slate-200">
                          <div className="text-[10px] text-gray-500 uppercase font-semibold">Valid Leads</div>
                          <div className="font-bold text-indigo-700 text-sm">{rc.valid_profile_leads ?? runProgress.total_raw_found}</div>
                        </div>
                        <div className="bg-slate-50 p-2 rounded border border-slate-200">
                          <div className="text-[10px] text-gray-500 uppercase font-semibold">Duplicates</div>
                          <div className="font-bold text-amber-600 text-sm">{rc.duplicates_filtered ?? rc.total_duplicates ?? runProgress.total_duplicates}</div>
                        </div>
                        <div className="bg-slate-50 p-2 rounded border border-slate-200">
                          <div className="text-[10px] text-gray-500 uppercase font-semibold">Unique Leads</div>
                          <div className="font-bold text-emerald-700 text-sm">{rc.unique_candidates ?? rc.total_unique_found ?? runProgress.total_unique_found}</div>
                        </div>
                        <div className="bg-slate-50 p-2 rounded border border-slate-200">
                          <div className="text-[10px] text-gray-500 uppercase font-semibold">New / Updated</div>
                          <div className="font-bold text-blue-700 text-sm">
                            {rc.candidates_newly_saved ?? rc.newly_inserted_count ?? 0} / {rc.candidates_updated ?? rc.updated_count ?? 0}
                          </div>
                        </div>
                        <div className="bg-slate-50 p-2 rounded border border-slate-200">
                          <div className="text-[10px] text-gray-500 uppercase font-semibold">Sourced Stage</div>
                          <div className="font-bold text-emerald-800 text-sm">{rc.sourced_stage_count ?? runProgress.total_saved}</div>
                        </div>
                        <div className="bg-slate-50 p-2 rounded border border-slate-200">
                          <div className="text-[10px] text-gray-500 uppercase font-semibold">Contacts Backed</div>
                          <div className="font-bold text-purple-700 text-sm">{rc.source_backed_contacts ?? '-'}</div>
                        </div>
                      </div>
                    </div>
                  );
                })()}
            </div>
          )}

          {/* Discovered Candidates Stream */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            <div className="p-4 border-b border-gray-200 flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-gray-50">
              <div className="flex items-center gap-2">
                <h3 className="font-bold text-gray-900 text-base">Discovered Candidates</h3>
                <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-blue-100 text-blue-800">
                  {discoveredCandidates.length}
                </span>
                <span className="text-xs text-gray-500 hidden sm:inline">
                  • {discoveredCandidates.filter(c => c.status === 'Sourced').length} Sourced, {discoveredCandidates.filter(c => c.status === 'Low Relevance').length} Low Relevance
                </span>
              </div>
              <div className="flex items-center gap-3">
                {onNavigate && (
                  <button
                    type="button"
                    onClick={() => onNavigate('pipeline')}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-blue-700 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 transition-colors shadow-2xs"
                  >
                    View in Pipeline <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                )}
                <span className="text-xs text-gray-500">Sorted by Match Score & Evidence Coverage</span>
              </div>
            </div>

            {discoveredCandidates.length === 0 ? (
              <div className="text-center py-12 px-4">
                <Sparkles className="w-10 h-10 text-gray-300 mx-auto mb-3" />
                <h4 className="font-medium text-gray-700">No candidate search executed yet for this session.</h4>
                <p className="text-xs text-gray-500 mt-1 max-w-md mx-auto">
                  Click the "Run Automated Candidate Discovery" button above to initiate zero-budget sourcing across GitHub, GitLab, Stack Overflow, Hugging Face, and Local Talent.
                </p>
              </div>
            ) : (
              <div className="divide-y divide-gray-100">
                {discoveredCandidates.map((cand) => {
                  const score = cand.match_score || 0;
                  const isShortlisted = cand.status === 'Shortlisted';

                  return (
                    <div
                      key={cand.id || cand.profile_url}
                      className="p-5 hover:bg-gray-50 transition-colors flex flex-col md:flex-row md:items-center justify-between gap-4"
                    >
                      {/* Left: Info & Badges */}
                      <div className="space-y-1.5 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <h4 className="font-bold text-gray-900 text-base">{cand.name}</h4>

                          {/* Match Score Badge */}
                          <span
                            className={`px-2 py-0.5 rounded-full text-xs font-bold border ${
                              score >= 80
                                ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                                : score >= 60
                                ? 'bg-blue-50 text-blue-700 border-blue-200'
                                : 'bg-amber-50 text-amber-700 border-amber-200'
                            }`}
                          >
                            {score}% Match
                          </span>

                          {/* Source Badge */}
                          <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-gray-100 text-gray-700 border border-gray-200">
                            {cand.source}
                          </span>

                          {/* 4-Tier Evidence Badge */}
                          {(cand.evidence_ladder_tier || cand.match_details?.evidence_tier) &&
                            renderEvidenceTierBadge(cand.evidence_ladder_tier || cand.match_details?.evidence_tier)}

                          {/* Contact Availability Badge */}
                          {renderContactBadge(
                            cand.contact_status || cand.match_details?.contact_availability,
                            cand.email,
                            cand.phone
                          )}

                          {/* Source Platform Reliability */}
                          {cand.match_details?.source_reliability && (
                            <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-slate-100 text-slate-600 border border-slate-200 hidden md:inline">
                              Source: {cand.match_details.source_reliability}
                            </span>
                          )}

                          {isShortlisted && (
                            <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-amber-100 text-amber-800 border border-amber-200 flex items-center gap-1">
                              <Star className="w-3 h-3 fill-amber-500 text-amber-500" /> Shortlisted
                            </span>
                          )}
                        </div>

                        {cand.headline && (
                          <p className="text-sm font-medium text-gray-700 line-clamp-1">{cand.headline}</p>
                        )}

                        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500">
                          {cand.company && (
                            <span className="flex items-center gap-1">
                              <Building className="w-3.5 h-3.5 text-gray-400" /> {cand.company}
                            </span>
                          )}
                          {cand.location && (
                            <span className="flex items-center gap-1">
                              <MapPin className="w-3.5 h-3.5 text-gray-400" /> {cand.location}
                            </span>
                          )}
                          <span className="flex items-center gap-1">
                            <Mail className="w-3.5 h-3.5 text-gray-400" />
                            {cand.email ? (
                              <span className="text-emerald-700 font-semibold">{cand.email}</span>
                            ) : (
                              <span className="text-gray-400 italic">No Public Email</span>
                            )}
                          </span>
                        </div>

                        {/* Matched Skills Tags */}
                        {cand.match_details?.matched_skills && cand.match_details.matched_skills.length > 0 && (
                          <div className="flex flex-wrap items-center gap-1.5 pt-1">
                            <span className="text-[10px] uppercase font-bold tracking-wider text-gray-400">
                              Matched Skills:
                            </span>
                            {cand.match_details.matched_skills.slice(0, 5).map((sk: string, i: number) => (
                              <span
                                key={i}
                                className="px-1.5 py-0.5 bg-emerald-50 text-emerald-800 border border-emerald-200 rounded text-[10px] font-semibold"
                              >
                                ✓ {sk}
                              </span>
                            ))}
                            {cand.match_details.matched_skills.length > 5 && (
                              <span className="text-[10px] text-gray-400">
                                +{cand.match_details.matched_skills.length - 5} more
                              </span>
                            )}
                          </div>
                        )}
                      </div>

                      {/* Right: Actions */}
                      <div className="flex items-center gap-2 shrink-0">
                        {cand.profile_url && cand.profile_url.startsWith('http') && (
                          <a
                            href={cand.profile_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="p-2 text-gray-600 hover:text-blue-600 border border-gray-200 rounded-lg hover:border-blue-300 transition-colors"
                            title="Open Public Profile"
                          >
                            <ExternalLink className="w-4 h-4" />
                          </a>
                        )}

                        <button
                          type="button"
                          onClick={() => {
                            setSelectedCandidate(cand);
                            setFeedbackRating('');
                            setFeedbackNotes('');
                            setFeedbackSavedMsg(null);
                          }}
                          className="flex items-center gap-1.5 px-3 py-2 text-xs font-semibold text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
                        >
                          <Eye className="w-3.5 h-3.5" />
                          Evidence & Score
                        </button>

                        {onNavigate && (
                          <button
                            type="button"
                            onClick={() => onNavigate('pipeline')}
                            className="flex items-center gap-1 px-2.5 py-2 text-xs font-semibold text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors border border-slate-200"
                            title="Open Kanban Candidate Pipeline"
                          >
                            Pipeline <ArrowRight className="w-3 h-3" />
                          </button>
                        )}

                        <button
                          type="button"
                          disabled={isShortlisted}
                          onClick={() => handleQuickShortlist(cand)}
                          className={`flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-lg transition-colors ${
                            isShortlisted
                              ? 'bg-emerald-50 text-emerald-700 border border-emerald-200 cursor-default'
                              : 'bg-blue-50 text-blue-700 border border-blue-200 hover:bg-blue-100'
                          }`}
                        >
                          {isShortlisted ? (
                            <>
                              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                              Shortlisted
                            </>
                          ) : (
                            <>
                              <Plus className="w-3.5 h-3.5" />
                              Shortlist
                            </>
                          )}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* TAB 2: MANUAL INTAKE / CV PASTE */}
      {activeTab === 'manual' && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm space-y-6">
          <div>
            <h3 className="text-lg font-bold text-gray-900">Manual Candidate Intake</h3>
            <p className="text-xs text-gray-500 mt-0.5">
              Paste profile excerpts, CV text, or manual candidate evidence. The engine will match and score them against the active job.
            </p>
          </div>

          <form onSubmit={handleSaveManualCandidate} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">Full Name *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Jane Doe"
                  value={manualForm.name}
                  onChange={(e) => setManualForm({ ...manualForm, name: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">Headline / Role Title</label>
                <input
                  type="text"
                  placeholder="e.g. Senior Machine Learning Engineer"
                  value={manualForm.headline}
                  onChange={(e) => setManualForm({ ...manualForm, headline: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">Public Profile URL</label>
                <input
                  type="text"
                  placeholder="https://..."
                  value={manualForm.profile_url}
                  onChange={(e) => setManualForm({ ...manualForm, profile_url: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">Location</label>
                <input
                  type="text"
                  placeholder="e.g. Bengaluru, India"
                  value={manualForm.location}
                  onChange={(e) => setManualForm({ ...manualForm, location: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">Email Address</label>
                <input
                  type="email"
                  placeholder="jane@example.com"
                  value={manualForm.email}
                  onChange={(e) => setManualForm({ ...manualForm, email: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">Portfolio / GitHub Link</label>
                <input
                  type="text"
                  placeholder="https://github.com/..."
                  value={manualForm.portfolio_url}
                  onChange={(e) => setManualForm({ ...manualForm, portfolio_url: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-700 mb-1">Profile / CV Evidence Text *</label>
              <textarea
                required
                rows={4}
                placeholder="Paste bio, project experience, technical stack, or interview notes here..."
                value={manualForm.evidence_text}
                onChange={(e) => setManualForm({ ...manualForm, evidence_text: e.target.value })}
                className="w-full border border-gray-300 rounded-lg p-3 text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
              ></textarea>
            </div>

            {manualFeedback && (
              <div
                className={`p-3 rounded-lg text-sm flex items-center gap-2 ${
                  manualFeedback.type === 'success'
                    ? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
                    : 'bg-red-50 text-red-800 border border-red-200'
                }`}
              >
                {manualFeedback.type === 'success' ? <CheckCircle2 className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
                <span>{manualFeedback.msg}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={savingManual}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 transition-colors disabled:opacity-50"
            >
              {savingManual ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
              Save Candidate to Database
            </button>
          </form>
        </div>
      )}

      {/* TAB 3: MANUAL SEARCH LINKS (BROWSER FALLBACK) */}
      {activeTab === 'xray' && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-gray-100 pb-4">
            <div>
              <h3 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                <Globe className="w-5 h-5 text-blue-600" />
                Manual Search Links & Browser X-Ray Strategies
              </h3>
              <p className="text-xs text-gray-500 mt-0.5">
                Role-specific Google and Bing X-Ray search strings. Launch individual strategies or 1-click batch directly in your browser.
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                disabled={launchingBatch || !xrayPlan || xrayPlan.strategies.length === 0}
                onClick={() => handleLaunchBatch(4)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 transition-all shadow-sm"
              >
                {launchingBatch ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    Launching...
                  </>
                ) : (
                  <>
                    <ExternalLink className="w-3.5 h-3.5" />
                    🚀 1-Click Launch Batch (Top 4)
                  </>
                )}
              </button>
              <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-gray-100 text-gray-700">
                Direct Browser Launch
              </span>
            </div>
          </div>

          {batchSuccessMsg && (
            <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg text-emerald-800 text-xs flex items-center gap-2 font-medium">
              <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
              <span>{batchSuccessMsg}</span>
            </div>
          )}

          {loadingQueries ? (
            <div className="text-center py-10">
              <Loader2 className="w-6 h-6 animate-spin text-blue-600 mx-auto" />
              <p className="text-xs text-gray-500 mt-2">Generating query strategies...</p>
            </div>
          ) : queries.length === 0 ? (
            <p className="text-sm text-gray-500 italic">No query strategies available for this job.</p>
          ) : (
            <div className="space-y-4">
              {queries.map((q) => (
                <div key={q.id} className="p-4 rounded-lg border border-gray-200 hover:border-blue-300 transition-all bg-gray-50/50 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-sm text-gray-900">{q.label}</span>
                    <span className="text-xs font-medium text-blue-700 bg-blue-50 px-2 py-0.5 rounded border border-blue-200">
                      {q.strategy}
                    </span>
                  </div>

                  <div className="bg-white p-2.5 rounded border border-gray-200 font-mono text-xs text-gray-800 break-all select-all">
                    {q.query_text}
                  </div>

                  <div className="flex items-center justify-between pt-1">
                    <button
                      type="button"
                      onClick={() => copyToClipboard(q.query_text, q.id)}
                      className="flex items-center gap-1.5 text-xs font-medium text-gray-600 hover:text-blue-600 transition-colors"
                    >
                      {copiedQueryId === q.id ? (
                        <>
                          <Check className="w-3.5 h-3.5 text-emerald-600" />
                          <span className="text-emerald-600 font-bold">Copied!</span>
                        </>
                      ) : (
                        <>
                          <Copy className="w-3.5 h-3.5" />
                          Copy Boolean String
                        </>
                      )}
                    </button>

                    <div className="flex items-center gap-2">
                      <a
                        href={q.google_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1 px-3 py-1 bg-white border border-gray-300 hover:border-blue-400 rounded text-xs font-medium text-gray-700 hover:text-blue-600 transition-colors shadow-2xs"
                      >
                        Google X-Ray <ExternalLink className="w-3 h-3" />
                      </a>
                      <a
                        href={q.bing_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1 px-3 py-1 bg-white border border-gray-300 hover:border-blue-400 rounded text-xs font-medium text-gray-700 hover:text-blue-600 transition-colors shadow-2xs"
                      >
                        Bing X-Ray <ExternalLink className="w-3 h-3" />
                      </a>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* CANDIDATE DETAILS & EVIDENCE MODAL / DRAWER */}
      {selectedCandidate && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto shadow-2xl border border-gray-200 p-6 space-y-6 animate-in fade-in zoom-in-95 duration-150">
            {/* Modal Header */}
            <div className="flex items-start justify-between border-b border-gray-100 pb-4">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-xl font-bold text-gray-900">{selectedCandidate.name}</h3>
                  <span
                    className={`px-2.5 py-0.5 rounded-full text-xs font-bold border ${
                      (selectedCandidate.match_score || 0) >= 80
                        ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                        : 'bg-blue-50 text-blue-700 border-blue-200'
                    }`}
                  >
                    {selectedCandidate.match_score || 0}% Match
                  </span>
                </div>
                {selectedCandidate.headline && (
                  <p className="text-sm text-gray-600 mt-1">{selectedCandidate.headline}</p>
                )}
              </div>
              <button
                type="button"
                onClick={() => setSelectedCandidate(null)}
                className="p-1 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
              >
                ✕
              </button>
            </div>

            {/* Profile Links & Provenance */}
            <div className="bg-gray-50 rounded-lg p-3.5 space-y-2 border border-gray-200 text-xs">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                <span className="font-semibold text-gray-700">Source:</span>
                <span className="font-bold text-gray-900">{selectedCandidate.source}</span>
                {selectedCandidate.profile_url && selectedCandidate.profile_url.startsWith('http') && (
                  <a
                    href={selectedCandidate.profile_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 hover:underline flex items-center gap-1 font-medium"
                  >
                    View Source Profile <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                <span className="font-semibold text-gray-700">Contact Status:</span>
                {renderContactBadge(
                  selectedCandidate.contact_status || selectedCandidate.match_details?.contact_availability,
                  selectedCandidate.email,
                  selectedCandidate.phone
                )}
              </div>
              {selectedCandidate.contact_provenance && (
                <div className="text-[11px] text-gray-500">
                  <span className="font-semibold text-gray-600">Provenance:</span> {selectedCandidate.contact_provenance}
                </div>
              )}
              {selectedCandidate.evidence_ladder_tier && (
                <div className="pt-2 border-t border-gray-200 space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-gray-700">GitHub Literacy Ladder:</span>
                    {renderEvidenceTierBadge(selectedCandidate.evidence_ladder_tier)}
                  </div>
                  <p className="text-[11px] text-gray-500 leading-relaxed">
                    {selectedCandidate.evidence_ladder_tier.includes('Tier 1')
                      ? 'Tier 1 Strong Technical Evidence: Substantive engineering work, active repositories, or merged commits. Emphasizes authentic code impact over vanity stars.'
                      : selectedCandidate.evidence_ladder_tier.includes('Tier 2')
                      ? 'Tier 2 Moderate Technical Evidence: Verified public profile and repositories present for technical evaluation.'
                      : selectedCandidate.evidence_ladder_tier.includes('Tier 3')
                      ? 'Tier 3 Weak Signal: Platform presence or contextual profile without deep repository history.'
                      : 'Tier 4: Insufficient verified technical evidence.'}
                  </p>
                </div>
              )}
            </div>

            {/* Evidence Matching Breakdown */}
            {(() => {
              const matchDetails =
                typeof selectedCandidate.match_details === 'string'
                  ? (() => {
                      try {
                        return JSON.parse(selectedCandidate.match_details);
                      } catch {
                        return null;
                      }
                    })()
                  : selectedCandidate.match_details;

              if (!matchDetails) return null;

              return (
                <div className="bg-white rounded-lg p-3.5 space-y-3 border border-gray-200 text-xs">
                  <div className="flex items-center justify-between">
                    <h4 className="font-bold uppercase tracking-wider text-gray-700">
                      Evidence Matching Breakdown
                    </h4>
                    {matchDetails.source_reliability && (
                      <span className="text-[11px] font-semibold text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-200">
                        Reliability: {matchDetails.source_reliability}
                      </span>
                    )}
                  </div>

                  {matchDetails.breakdown && (
                    <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-center">
                      <div className="p-2 bg-gray-50 rounded border border-gray-100">
                        <div className="text-[10px] text-gray-500 font-semibold">Core Skills</div>
                        <div className="text-sm font-bold text-gray-900">
                          {matchDetails.breakdown.core_skills ?? 0} pts
                        </div>
                      </div>
                      <div className="p-2 bg-gray-50 rounded border border-gray-100">
                        <div className="text-[10px] text-gray-500 font-semibold">Tools & Tech</div>
                        <div className="text-sm font-bold text-gray-900">
                          {matchDetails.breakdown.tools ?? 0} pts
                        </div>
                      </div>
                      <div className="p-2 bg-gray-50 rounded border border-gray-100">
                        <div className="text-[10px] text-gray-500 font-semibold">Role Alignment</div>
                        <div className="text-sm font-bold text-gray-900">
                          {matchDetails.breakdown.role_alignment ?? 0} pts
                        </div>
                      </div>
                      <div className="p-2 bg-gray-50 rounded border border-gray-100">
                        <div className="text-[10px] text-gray-500 font-semibold">Location</div>
                        <div className="text-sm font-bold text-gray-900">
                          {matchDetails.breakdown.location ?? 0} pts
                        </div>
                      </div>
                      <div className="p-2 bg-gray-50 rounded border border-gray-100">
                        <div className="text-[10px] text-gray-500 font-semibold">Portfolio</div>
                        <div className="text-sm font-bold text-gray-900">
                          {matchDetails.breakdown.portfolio ?? 0} pts
                        </div>
                      </div>
                    </div>
                  )}

                  {matchDetails.matched_skills && matchDetails.matched_skills.length > 0 && (
                    <div className="space-y-1">
                      <span className="font-semibold text-gray-700 text-[11px]">Matched Skills:</span>
                      <div className="flex flex-wrap gap-1">
                        {matchDetails.matched_skills.map((sk: string, i: number) => (
                          <span
                            key={i}
                            className="px-2 py-0.5 bg-emerald-50 text-emerald-800 border border-emerald-200 rounded text-[11px] font-semibold"
                          >
                            ✓ {sk}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {matchDetails.missing_skills && matchDetails.missing_skills.length > 0 && (
                    <div className="space-y-1">
                      <span className="font-semibold text-gray-500 text-[11px]">Unmatched Requirements:</span>
                      <div className="flex flex-wrap gap-1">
                        {matchDetails.missing_skills.map((sk: string, i: number) => (
                          <span
                            key={i}
                            className="px-2 py-0.5 bg-gray-100 text-gray-600 border border-gray-200 rounded text-[11px]"
                          >
                            — {sk}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* AI Qualitative Match Assessment */}
                  {matchDetails.ai_explanation && (
                    <div className="mt-3 p-3 bg-purple-50/70 border border-purple-200 rounded-lg space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-1.5 font-bold text-xs text-purple-900">
                          <Sparkles className="w-3.5 h-3.5 text-purple-600" />
                          <span>AI Match Explanation (Groq)</span>
                        </div>
                        {matchDetails.ai_explanation.evidence_verdict && (
                          <span
                            className={`text-[10px] font-bold px-2 py-0.5 rounded border ${
                              matchDetails.ai_explanation.evidence_verdict.includes('High')
                                ? 'bg-emerald-100 text-emerald-800 border-emerald-300'
                                : matchDetails.ai_explanation.evidence_verdict.includes('Moderate')
                                ? 'bg-blue-100 text-blue-800 border-blue-300'
                                : 'bg-amber-100 text-amber-800 border-amber-300'
                            }`}
                          >
                            {matchDetails.ai_explanation.evidence_verdict}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-700 leading-relaxed font-medium">
                        {matchDetails.ai_explanation.summary}
                      </p>
                      {matchDetails.ai_explanation.strong_signals && matchDetails.ai_explanation.strong_signals.length > 0 && (
                        <div>
                          <div className="text-[10px] font-bold uppercase tracking-wider text-purple-800 mb-1">
                            Verified Signals
                          </div>
                          <ul className="text-[11px] text-gray-700 space-y-0.5 list-disc list-inside">
                            {matchDetails.ai_explanation.strong_signals.map((sig: string, idx: number) => (
                              <li key={idx}>{sig}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {matchDetails.ai_explanation.missing_or_uncertain && matchDetails.ai_explanation.missing_or_uncertain.length > 0 && (
                        <div>
                          <div className="text-[10px] font-bold uppercase tracking-wider text-amber-800 mb-1">
                            Missing / Uncertain
                          </div>
                          <ul className="text-[11px] text-gray-600 space-y-0.5 list-disc list-inside">
                            {matchDetails.ai_explanation.missing_or_uncertain.map((miss: string, idx: number) => (
                              <li key={idx}>{miss}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}

                  {/* AI Profile Intelligence & Technical Corroboration */}
                  {matchDetails.profile_intelligence && (
                    <div className="mt-3 p-3 bg-indigo-50/70 border border-indigo-200 rounded-lg space-y-2.5">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-1.5 font-bold text-xs text-indigo-900">
                          <CheckCircle2 className="w-3.5 h-3.5 text-indigo-600" />
                          <span>AI Profile Intelligence (Technical Evidence vs Vanity Signals)</span>
                        </div>
                      </div>

                      {/* Supported Skills with Evidence */}
                      {matchDetails.profile_intelligence.supported_skills && matchDetails.profile_intelligence.supported_skills.length > 0 && (
                        <div>
                          <div className="text-[10px] font-bold uppercase tracking-wider text-indigo-800 mb-1">
                            Corroborated Technical Evidence
                          </div>
                          <div className="space-y-1">
                            {matchDetails.profile_intelligence.supported_skills.map((item: any, idx: number) => (
                              <div key={idx} className="text-[11px] bg-white p-1.5 rounded border border-indigo-100 flex items-start gap-1.5">
                                <span className="font-semibold text-indigo-900 shrink-0">{item.skill}:</span>
                                <span className="text-gray-700 italic font-mono text-[10px] truncate">{item.evidence}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Vanity Signal Guard */}
                      {matchDetails.profile_intelligence.vanity_signals && matchDetails.profile_intelligence.vanity_signals.length > 0 && (
                        <div className="p-2 bg-amber-50 rounded border border-amber-200 text-[11px] text-amber-900">
                          <div className="font-bold text-[10px] uppercase tracking-wider text-amber-800 flex items-center gap-1 mb-0.5">
                            <AlertCircle className="w-3 h-3 text-amber-600" />
                            <span>Vanity Signal Filtered</span>
                          </div>
                          <ul className="list-disc list-inside space-y-0.5 text-amber-800 text-[10px]">
                            {matchDetails.profile_intelligence.vanity_signals.map((vs: string, idx: number) => (
                              <li key={idx}>{vs}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Tenure / Public Links */}
                      {(matchDetails.profile_intelligence.tenure_signals?.length > 0 || matchDetails.profile_intelligence.public_contact_or_links?.length > 0) && (
                        <div className="flex flex-wrap gap-2 text-[10px] text-gray-600">
                          {matchDetails.profile_intelligence.tenure_signals?.map((ts: string, idx: number) => (
                            <span key={idx} className="bg-white px-2 py-0.5 rounded border border-gray-200 font-medium">
                              ⏱️ {ts}
                            </span>
                          ))}
                          {matchDetails.profile_intelligence.public_contact_or_links?.map((link: string, idx: number) => (
                            <span key={idx} className="bg-white px-2 py-0.5 rounded border border-gray-200 font-medium text-blue-700 truncate max-w-[200px]">
                              🔗 {link}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {!matchDetails.ai_explanation && !matchDetails.profile_intelligence && (
                    <div className="mt-2 pt-2 border-t border-gray-100 flex justify-end">
                      <button
                        type="button"
                        onClick={handleRequestAiExplanation}
                        disabled={loadingAiExplanation}
                        className="inline-flex items-center gap-1.5 px-3 py-1 bg-purple-50 hover:bg-purple-100 text-purple-700 text-xs font-semibold rounded border border-purple-200 transition-colors disabled:opacity-50"
                      >
                        <Sparkles className="w-3.5 h-3.5 text-purple-600" />
                        {loadingAiExplanation ? 'Analyzing Match & Evidence...' : '⚡ Request AI Match & Profile Intelligence'}
                      </button>
                    </div>
                  )}
                </div>
              );
            })()}

            {/* Evidence Text Box */}
            <div className="space-y-1.5">
              <h4 className="text-xs font-bold uppercase tracking-wider text-gray-500">Source Evidence</h4>
              <div className="p-3 bg-gray-50 rounded-lg border border-gray-200 text-xs font-mono text-gray-800 whitespace-pre-wrap max-h-48 overflow-y-auto">
                {selectedCandidate.evidence_text || 'No evidence supplied.'}
              </div>
            </div>

            {/* Recruiter Feedback Calibration */}
            <div className="space-y-3 border-t border-gray-100 pt-4">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-bold uppercase tracking-wider text-gray-700">
                  Recruiter Feedback & Calibration
                </h4>
                {feedbackRating && (
                  <span className="text-xs font-medium text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                    Logged: {feedbackRating}
                  </span>
                )}
              </div>
              <p className="text-xs text-gray-500">
                Rate this candidate to train future query adjustments and calibrate ranking for this role family.
              </p>

              <div className="flex flex-wrap gap-2">
                {[
                  { rating: 'Relevant', icon: ThumbsUp, color: 'text-emerald-700 bg-emerald-50 border-emerald-300' },
                  { rating: 'Partially Relevant', icon: HelpCircle, color: 'text-blue-700 bg-blue-50 border-blue-300' },
                  { rating: 'Irrelevant', icon: ThumbsDown, color: 'text-rose-700 bg-rose-50 border-rose-300' },
                  { rating: 'Duplicate', icon: AlertCircle, color: 'text-amber-700 bg-amber-50 border-amber-300' },
                  { rating: 'Contact Unavailable', icon: Mail, color: 'text-gray-700 bg-gray-100 border-gray-300' },
                ].map((btn) => (
                  <button
                    key={btn.rating}
                    type="button"
                    disabled={savingFeedback}
                    onClick={() => handleSubmitFeedback(btn.rating)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-semibold transition-all ${btn.color} hover:opacity-80`}
                  >
                    <btn.icon className="w-3.5 h-3.5" />
                    {btn.rating}
                  </button>
                ))}
              </div>

              <div>
                <input
                  type="text"
                  value={feedbackNotes}
                  onChange={(e) => setFeedbackNotes(e.target.value)}
                  placeholder="Optional recruiter calibration note (e.g. good Python, missing senior experience)..."
                  className="w-full text-xs px-3 py-1.5 border border-gray-200 rounded-lg focus:ring-1 focus:ring-blue-500 text-gray-800 placeholder-gray-400"
                />
              </div>

              {feedbackSavedMsg && (
                <div className="p-2 bg-emerald-50 border border-emerald-200 rounded text-emerald-800 text-xs flex items-center gap-1.5 font-medium">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                  {feedbackSavedMsg}
                </div>
              )}

              <div className="pt-2 flex items-center justify-between gap-2 border-t border-gray-100">
                <button
                  type="button"
                  disabled={calibratingStrategy || !activeJob}
                  onClick={handleCalibrateStrategy}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-indigo-700 bg-indigo-50 hover:bg-indigo-100 border border-indigo-200 transition-colors disabled:opacity-50"
                >
                  <Sparkles className="w-3.5 h-3.5 text-indigo-600" />
                  {calibratingStrategy ? 'Calibrating Strategy...' : '⚡ Calibrate Search Strategy from Feedback'}
                </button>
              </div>

              {calibrationResultMsg && (
                <div className="p-2 bg-indigo-50 border border-indigo-200 rounded text-indigo-800 text-xs flex items-center gap-1.5 font-medium">
                  <Sparkles className="w-3.5 h-3.5 text-indigo-600 flex-shrink-0" />
                  <span>{calibrationResultMsg}</span>
                </div>
              )}

              {strategyVersions && strategyVersions.length > 0 && (
                <div className="p-2.5 bg-gray-50 border border-gray-200 rounded-lg text-xs space-y-1.5">
                  <div className="font-semibold text-gray-700 flex items-center justify-between">
                    <span>Calibration History</span>
                    <span className="text-[10px] text-gray-500 font-normal">{strategyVersions.length} revision(s)</span>
                  </div>
                  <ul className="space-y-1 text-gray-600 text-[11px]">
                    {strategyVersions.slice(0, 3).map((sv: any, idx: number) => (
                      <li key={idx} className="flex justify-between items-start gap-2">
                        <span className="font-medium text-gray-800">v{sv.version_number ?? sv.version_num}: {sv.changes_summary}</span>
                        <span className="text-[10px] text-gray-400 whitespace-nowrap">
                          {sv.created_at ? new Date(sv.created_at).toLocaleDateString() : ''}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            {/* Modal Footer Actions */}
            <div className="flex items-center justify-between border-t border-gray-100 pt-4">
              <button
                type="button"
                onClick={() => setSelectedCandidate(null)}
                className="px-4 py-2 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors"
              >
                Close
              </button>

              <div className="flex items-center gap-2">
                {onNavigate && (
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedCandidate(null);
                      onNavigate('pipeline');
                    }}
                    className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 transition-colors"
                  >
                    View in Pipeline <ArrowRight className="w-4 h-4" />
                  </button>
                )}

                <button
                  type="button"
                  onClick={() => handleQuickShortlist(selectedCandidate)}
                  disabled={selectedCandidate.status === 'Shortlisted'}
                  className="flex items-center gap-1.5 px-5 py-2 rounded-lg text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 transition-colors shadow-sm"
                >
                  <Star className="w-4 h-4 fill-white text-white" />
                  {selectedCandidate.status === 'Shortlisted' ? 'Already Shortlisted' : 'Shortlist Candidate'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
