import React, { useEffect, useState, useRef } from 'react';
import {
  LayoutDashboard,
  FolderUp,
  FileArchive,
  Users,
  Briefcase,
  CheckCircle2,
  Mail,
  History,
  RefreshCw,
  AlertTriangle,
  UserX,
  Search,
  Play,
  StopCircle,
  RotateCcw,
  Sparkles,
  ExternalLink,
  Edit3,
  Plus,
  Check,
  Pause,
  ShieldCheck,
  ShieldAlert,
  LogOut,
  ChevronLeft,
  ChevronRight,
  X,
  Info,
} from 'lucide-react';
import { api } from '../api';
import type {
  CVImportJob,
  CVImportJobFile,
  ReferralCandidate,
  ReferralOpportunity,
  CandidateOpportunityMatch,
  OutreachDraft,
  CVOutreachOverview,
  GmailAuthStatus,
} from '../types';

export type OutreachTab =
  | 'overview'
  | 'upload'
  | 'library'
  | 'opportunities'
  | 'matches'
  | 'drafts'
  | 'history';

export const CvOutreachView: React.FC = () => {
  const [activeTab, setActiveTab] = useState<OutreachTab>('overview');

  // Overview Data
  const [overview, setOverview] = useState<CVOutreachOverview | null>(null);

  // Upload & Import State
  const [folderPath, setFolderPath] = useState<string>('');
  const [batchSize, setBatchSize] = useState<number>(15);
  const [isImporting, setIsImporting] = useState<boolean>(false);
  const [importJobs, setImportJobs] = useState<CVImportJob[]>([]);
  const [selectedJob, setSelectedJob] = useState<CVImportJob | null>(null);
  const [jobFiles, setJobFiles] = useState<CVImportJobFile[]>([]);
  const [loadingFiles, setLoadingFiles] = useState<boolean>(false);
  const [importMessage, setImportMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  // Candidate Library State
  const [candidates, setCandidates] = useState<ReferralCandidate[]>([]);
  const [candidateSearch, setCandidateSearch] = useState<string>('');
  const [optOutOnly, setOptOutOnly] = useState<boolean>(false);
  const [loadingCandidates, setLoadingCandidates] = useState<boolean>(false);
  const [candidatePage, setCandidatePage] = useState<number>(1);
  const CANDIDATES_PER_PAGE = 50;

  // Permission Review Modal State
  const [permissionCandidate, setPermissionCandidate] = useState<ReferralCandidate | null>(null);
  const [permBasis, setPermBasis] = useState<string>('APPROVED_OUTREACH');
  const [permReviewer, setPermReviewer] = useState<string>('Recruiter');
  const [permNotes, setPermNotes] = useState<string>('');
  const [permEmailStatus, setPermEmailStatus] = useState<string>('VERIFIED');
  const [savingPermission, setSavingPermission] = useState<boolean>(false);

  // Opportunities State
  const [opportunities, setOpportunities] = useState<ReferralOpportunity[]>([]);
  const [showAddOppModal, setShowAddOppModal] = useState<boolean>(false);
  const [newOppPlatform, setNewOppPlatform] = useState<string>('Turing');
  const [newOppTitle, setNewOppTitle] = useState<string>('');
  const [newOppUrl, setNewOppUrl] = useState<string>('');
  const [newOppReferralUrl, setNewOppReferralUrl] = useState<string>('');
  const [newOppReqs, setNewOppReqs] = useState<string>('python, react, fastapi');

  // Verify Opportunity Modal State
  const [verifyingOpp, setVerifyingOpp] = useState<ReferralOpportunity | null>(null);
  const [oppStatus, setOppStatus] = useState<string>('VERIFIED');
  const [oppSource, setOppSource] = useState<string>('Official Partner Portal');
  const [oppNotes, setOppNotes] = useState<string>('');
  const [savingOppVerification, setSavingOppVerification] = useState<boolean>(false);

  // Matches State
  const [matches, setMatches] = useState<CandidateOpportunityMatch[]>([]);
  const [matchFilterOpp, setMatchFilterOpp] = useState<number | undefined>(undefined);
  const [matchMinScore, setMatchMinScore] = useState<number>(40);
  const [isEvaluatingMatches, setIsEvaluatingMatches] = useState<boolean>(false);

  // Blocked Draft Warning Modal
  const [blockedWarning, setBlockedWarning] = useState<{
    candidateName: string;
    opportunityTitle: string;
    reasons: string[];
    suggestedTab?: OutreachTab;
  } | null>(null);

  // Drafts State
  const [drafts, setDrafts] = useState<OutreachDraft[]>([]);
  const [gmailAuth, setGmailAuth] = useState<GmailAuthStatus | null>(null);
  const [editingDraft, setEditingDraft] = useState<OutreachDraft | null>(null);
  const [editSubject, setEditSubject] = useState<string>('');
  const [editBody, setEditBody] = useState<string>('');

  // File upload ref for ZIP
  const zipInputRef = useRef<HTMLInputElement>(null);

  // Loaders
  const loadOverview = async () => {
    try {
      const data = await api.getCVOutreachOverview();
      setOverview(data);
    } catch (err) {
      console.error('Error loading overview:', err);
    }
  };

  const loadJobs = async () => {
    try {
      const data = await api.getImportJobs();
      setImportJobs(data);
      if (selectedJob) {
        const found = data.find((j) => j.job_id === selectedJob.job_id);
        if (found) setSelectedJob(found);
      }
    } catch (err) {
      console.error('Error loading jobs:', err);
    }
  };

  const loadCandidates = async () => {
    setLoadingCandidates(true);
    try {
      const data = await api.getReferralCandidates(candidateSearch, optOutOnly);
      setCandidates(data);
      setCandidatePage(1);
    } catch (err) {
      console.error('Error loading candidates:', err);
    } finally {
      setLoadingCandidates(false);
    }
  };

  const loadOpportunities = async () => {
    try {
      const data = await api.getReferralOpportunities();
      setOpportunities(data);
    } catch (err) {
      console.error('Error loading opportunities:', err);
    }
  };

  const loadMatches = async () => {
    try {
      const data = await api.getMatches(matchFilterOpp, matchMinScore);
      setMatches(data);
    } catch (err) {
      console.error('Error loading matches:', err);
    }
  };

  const loadGmailAuth = async () => {
    try {
      const auth = await api.getGmailAuthStatus();
      setGmailAuth(auth);
    } catch (err) {
      console.error('Error loading Gmail auth:', err);
    }
  };

  const loadDrafts = async () => {
    try {
      const [d] = await Promise.all([api.getDrafts(), loadGmailAuth()]);
      setDrafts(d);
    } catch (err) {
      console.error('Error loading drafts:', err);
    }
  };

  // Tab switch effect (deduplicated loadOverview)
  useEffect(() => {
    loadOverview();
    if (activeTab === 'overview') {
      loadJobs();
      loadOpportunities();
    } else if (activeTab === 'upload' || activeTab === 'history') {
      loadJobs();
    } else if (activeTab === 'library') {
      loadCandidates();
    } else if (activeTab === 'opportunities') {
      loadOpportunities();
    } else if (activeTab === 'matches') {
      loadOpportunities();
      loadMatches();
    } else if (activeTab === 'drafts') {
      loadDrafts();
    }
  }, [activeTab]);

  // Polling for active background jobs
  useEffect(() => {
    const hasRunning = importJobs.some((j) => j.status === 'PROCESSING' || j.status === 'QUEUED');
    if (!hasRunning) return;

    const interval = setInterval(() => {
      loadJobs();
      loadOverview();
      if (selectedJob && (selectedJob.status === 'PROCESSING' || selectedJob.status === 'QUEUED')) {
        loadJobFiles(selectedJob.job_id);
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [importJobs, selectedJob]);

  // Listen for OAuth success popup messages
  useEffect(() => {
    const handleMsg = (e: MessageEvent) => {
      if (e.data?.type === 'GMAIL_OAUTH_SUCCESS') {
        loadGmailAuth();
      }
    };
    window.addEventListener('message', handleMsg);
    return () => window.removeEventListener('message', handleMsg);
  }, []);

  // Folder Import Handler
  const handleStartFolderImport = async () => {
    if (!folderPath.trim()) {
      setImportMessage({ text: 'Please enter a valid Windows folder path.', type: 'error' });
      return;
    }

    setIsImporting(true);
    setImportMessage(null);
    try {
      const res = await api.startFolderImport(folderPath.trim(), batchSize, true);
      setImportMessage({ text: res.message, type: 'success' });
      await loadJobs();
      await loadOverview();
      const updatedJob = await api.getImportJob(res.job_id);
      setSelectedJob(updatedJob);
      loadJobFiles(res.job_id);
      setActiveTab('history');
    } catch (err: any) {
      setImportMessage({ text: err.message || 'Folder import failed.', type: 'error' });
    } finally {
      setIsImporting(false);
    }
  };

  // ZIP Import Handler
  const handleZipUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsImporting(true);
    setImportMessage(null);
    try {
      const res = await api.startZipImport(file, batchSize, true);
      setImportMessage({ text: res.message, type: 'success' });
      await loadJobs();
      await loadOverview();
      const updatedJob = await api.getImportJob(res.job_id);
      setSelectedJob(updatedJob);
      loadJobFiles(res.job_id);
      setActiveTab('history');
    } catch (err: any) {
      setImportMessage({ text: err.message || 'ZIP import failed.', type: 'error' });
    } finally {
      setIsImporting(false);
      if (zipInputRef.current) zipInputRef.current.value = '';
    }
  };

  const loadJobFiles = async (jobId: string) => {
    setLoadingFiles(true);
    try {
      const files = await api.getImportJobFiles(jobId);
      setJobFiles(files);
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingFiles(false);
    }
  };

  const handleSelectJob = (job: CVImportJob) => {
    setSelectedJob(job);
    loadJobFiles(job.job_id);
  };

  const handleCancelJob = async (jobId: string) => {
    try {
      await api.cancelImportJob(jobId);
      await loadJobs();
      await loadOverview();
      if (selectedJob?.job_id === jobId) {
        setSelectedJob(await api.getImportJob(jobId));
      }
    } catch (err: any) {
      alert(`Cancel error: ${err.message}`);
    }
  };

  const handlePauseJob = async (jobId: string) => {
    try {
      await api.pauseImportJob(jobId);
      await loadJobs();
      if (selectedJob?.job_id === jobId) {
        setSelectedJob(await api.getImportJob(jobId));
      }
    } catch (err: any) {
      alert(`Pause error: ${err.message}`);
    }
  };

  const handleResumeJob = async (jobId: string) => {
    try {
      await api.resumeImportJob(jobId, batchSize);
      await loadJobs();
      if (selectedJob?.job_id === jobId) {
        setSelectedJob(await api.getImportJob(jobId));
      }
    } catch (err: any) {
      alert(`Resume error: ${err.message}`);
    }
  };

  const handleRetryJob = async (jobId: string) => {
    try {
      await api.retryImportJob(jobId, batchSize);
      await loadJobs();
      loadJobFiles(jobId);
    } catch (err: any) {
      alert(`Retry error: ${err.message}`);
    }
  };

  // Run Matching
  const handleRunMatching = async () => {
    setIsEvaluatingMatches(true);
    try {
      const res = await api.evaluateMatches(matchMinScore);
      alert(res.message);
      await loadMatches();
      await loadOverview();
    } catch (err: any) {
      alert(`Matching failed: ${err.message}`);
    } finally {
      setIsEvaluatingMatches(false);
    }
  };

  // Create Draft from Match with Strict Outreach Gating Check
  const handleGenerateDraftFromMatch = async (match: CandidateOpportunityMatch) => {
    const isEligible = match.outreach_eligibility === 'ELIGIBLE';

    if (!isEligible) {
      const reasons: string[] = [];
      if (match.candidate_opt_out === 1) {
        reasons.push('Candidate has opted out of recruitment outreach.');
      }
      if (match.score < 40) {
        reasons.push(`Candidate fit score is ${match.score}/100, which is below the minimum threshold of 40.`);
      }
      if (!match.candidate_email) {
        reasons.push('Candidate has no email address extracted or verified.');
      }
      const permUpper = (match.candidate_permission_basis || 'PENDING_REVIEW').toUpperCase();
      if (permUpper !== 'APPROVED_OUTREACH' && permUpper !== 'DIRECT_CONSENT') {
        reasons.push(
          `Candidate contact permission is "${match.candidate_permission_basis || 'PENDING_REVIEW'}". Outreach requires approved permission (APPROVED_OUTREACH or DIRECT_CONSENT).`
        );
      }
      const emailStatusUpper = (match.candidate_email_verification_status || 'PENDING_VERIFICATION').toUpperCase();
      if (emailStatusUpper !== 'VERIFIED') {
        reasons.push(
          `Email verification status is "${match.candidate_email_verification_status || 'PENDING_VERIFICATION'}". Email must be verified before drafting.`
        );
      }
      const oppStatusUpper = (match.opportunity_verification_status || 'UNVERIFIED').toUpperCase();
      if (oppStatusUpper !== 'VERIFIED') {
        reasons.push(
          `Opportunity is "${match.opportunity_verification_status || 'UNVERIFIED'}". Partner opportunities must be verified before outreach.`
        );
      }

      setBlockedWarning({
        candidateName: match.candidate_name,
        opportunityTitle: `${match.opportunity_platform}: ${match.opportunity_title}`,
        reasons: reasons.length > 0 ? reasons : ['One or more required compliance gates are not satisfied.'],
        suggestedTab: oppStatusUpper !== 'VERIFIED' ? 'opportunities' : 'library',
      });
      return;
    }

    try {
      const res = await api.createDraft({
        candidate_id: match.candidate_id,
        opportunity_id: match.opportunity_id,
        save_to_gmail: true,
        mock_mode: false,
      });
      alert(res.message || 'Draft prepared successfully in Gmail!');
      await loadDrafts();
      await loadOverview();
      setActiveTab('drafts');
    } catch (err: any) {
      alert(`Draft creation error: ${err.message}`);
    }
  };

  // Open Permission Modal
  const openPermissionModal = (cand: ReferralCandidate) => {
    setPermissionCandidate(cand);
    setPermBasis(
      cand.contact_permission_basis && cand.contact_permission_basis !== 'PENDING_REVIEW'
        ? cand.contact_permission_basis
        : 'APPROVED_OUTREACH'
    );
    setPermReviewer(cand.permission_reviewed_by || 'Recruiter');
    setPermNotes(cand.permission_notes || '');
    setPermEmailStatus(cand.email_verification_status || 'VERIFIED');
  };

  // Save Permission Modal
  const handleSavePermission = async () => {
    if (!permissionCandidate) return;
    setSavingPermission(true);
    try {
      await api.setCandidatePermissionBasis(
        permissionCandidate.id,
        permBasis,
        permReviewer.trim() || 'Recruiter',
        permNotes.trim()
      );
      if (permEmailStatus) {
        await api.setCandidateEmailVerification(
          permissionCandidate.id,
          permEmailStatus,
          permNotes.trim()
        );
      }
      setPermissionCandidate(null);
      await loadCandidates();
      await loadOverview();
    } catch (err: any) {
      alert(`Failed to save permission: ${err.message}`);
    } finally {
      setSavingPermission(false);
    }
  };

  // Open Opportunity Verification Modal
  const openOppVerifyModal = (opp: ReferralOpportunity) => {
    setVerifyingOpp(opp);
    setOppStatus(opp.verification_status || 'VERIFIED');
    setOppSource(opp.verification_source || 'Official Partner Portal / Agreement');
    setOppNotes(opp.verification_notes || '');
  };

  // Save Opportunity Verification Modal
  const handleSaveOppVerification = async () => {
    if (!verifyingOpp) return;
    setSavingOppVerification(true);
    try {
      await api.verifyOpportunity(
        verifyingOpp.id,
        oppStatus,
        oppSource.trim() || 'Manual verification audit',
        oppNotes.trim()
      );
      setVerifyingOpp(null);
      await loadOpportunities();
      await loadOverview();
    } catch (err: any) {
      alert(`Failed to verify opportunity: ${err.message}`);
    } finally {
      setSavingOppVerification(false);
    }
  };

  // Create New Opportunity
  const handleCreateOpportunity = async () => {
    if (!newOppTitle.trim()) return;
    try {
      const reqList = newOppReqs
        .split(',')
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean);
      await api.createReferralOpportunity({
        platform: newOppPlatform,
        title: newOppTitle.trim(),
        official_url: newOppUrl.trim(),
        referral_url: newOppReferralUrl.trim() || undefined,
        requirements: reqList,
        verification_status: 'UNVERIFIED',
      });
      setShowAddOppModal(false);
      setNewOppTitle('');
      setNewOppUrl('');
      setNewOppReferralUrl('');
      await loadOpportunities();
      await loadOverview();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleConnectGmail = async () => {
    try {
      const res = await api.getGmailAuthUrl();
      if (res.auth_url) {
        window.open(res.auth_url, '_blank', 'width=600,height=700');
      }
    } catch (err: any) {
      alert(`Could not start Gmail OAuth: ${err.message}`);
    }
  };

  const handleDisconnectGmail = async () => {
    if (!confirm('Are you sure you want to disconnect Gmail? Stored credentials will be removed.')) return;
    try {
      await api.disconnectGmail();
      await loadGmailAuth();
    } catch (err: any) {
      alert(err.message);
    }
  };

  // Toggle Opt Out
  const handleToggleOptOut = async (candidate: ReferralCandidate) => {
    const isCurrentlyOptedOut = candidate.opt_out_status === 1;
    let reason = '';
    if (!isCurrentlyOptedOut) {
      const input = prompt('Enter suppression reason (e.g. "Candidate requested removal via email"):');
      if (input === null) return;
      reason = input.trim() || 'Candidate requested opt-out';
    }

    try {
      await api.setCandidateOptOut(candidate.id, !isCurrentlyOptedOut, reason);
      loadCandidates();
      loadOverview();
    } catch (err) {
      console.error(err);
    }
  };

  // Open Edit Draft Modal
  const openEditDraft = (draft: OutreachDraft) => {
    setEditingDraft(draft);
    setEditSubject(draft.subject);
    setEditBody(draft.body_text);
  };

  // Save Edited Draft
  const handleSaveEditedDraft = async () => {
    if (!editingDraft) return;
    try {
      await api.createDraft({
        candidate_id: editingDraft.candidate_id,
        opportunity_id: editingDraft.opportunity_id,
        subject: editSubject,
        body_text: editBody,
        save_to_gmail: true,
        mock_mode: false,
      });
      setEditingDraft(null);
      await loadDrafts();
    } catch (err: any) {
      alert(`Save error: ${err.message}`);
    }
  };

  // Pagination for Candidates
  const totalCandidatePages = Math.max(1, Math.ceil(candidates.length / CANDIDATES_PER_PAGE));
  const displayedCandidates = candidates.slice(
    (candidatePage - 1) * CANDIDATES_PER_PAGE,
    candidatePage * CANDIDATES_PER_PAGE
  );

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <Mail className="text-indigo-400" size={26} />
            CV Outreach System
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Windows CV folder import, deduplication, Turing/Mercor/micro1 opportunity matching, and official Gmail draft creation.
          </p>
        </div>

        {/* Status Pill */}
        <div className="flex items-center gap-2 bg-slate-800/80 px-3 py-1.5 rounded-lg border border-slate-700 text-xs text-slate-300">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          <span>Draft-Only Mode (Never Auto-Sends)</span>
        </div>
      </div>

      {/* 7-Tab Navigation Bar */}
      <div className="flex flex-wrap items-center gap-1.5 bg-slate-900/90 p-1.5 rounded-xl border border-slate-800">
        {[
          { id: 'overview', label: 'Overview', icon: <LayoutDashboard size={15} /> },
          { id: 'upload', label: 'Upload CVs', icon: <FolderUp size={15} /> },
          { id: 'library', label: 'CV Library', icon: <Users size={15} /> },
          { id: 'opportunities', label: 'Referral Opportunities', icon: <Briefcase size={15} /> },
          { id: 'matches', label: 'Match Review', icon: <Sparkles size={15} /> },
          { id: 'drafts', label: 'Gmail Drafts', icon: <Mail size={15} /> },
          { id: 'history', label: 'Import History', icon: <History size={15} /> },
        ].map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as OutreachTab)}
              className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold transition-all ${
                isActive
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* TAB 1: OVERVIEW */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          {/* Key Stat Cards */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3.5">
            <div className="bg-slate-850 border border-slate-750 p-4 rounded-xl text-center">
              <div className="text-xs text-slate-400">Total CV Files</div>
              <div className="text-2xl font-bold text-white mt-1">
                {overview?.total_imported_files ?? 0}
              </div>
            </div>
            <div className="bg-slate-850 border border-slate-750 p-4 rounded-xl text-center">
              <div className="text-xs text-slate-400">Total Candidates</div>
              <div className="text-2xl font-bold text-white mt-1">
                {overview?.total_candidates ?? 0}
              </div>
            </div>
            <div className="bg-slate-850 border border-slate-750 p-4 rounded-xl text-center">
              <div className="text-xs text-slate-400">Active Roles</div>
              <div className="text-2xl font-bold text-indigo-400 mt-1">
                {overview?.active_opportunities ?? 0}
              </div>
            </div>
            <div className="bg-slate-850 border border-slate-750 p-4 rounded-xl text-center">
              <div className="text-xs text-slate-400">Total Matches</div>
              <div className="text-2xl font-bold text-emerald-400 mt-1">
                {overview?.total_matches ?? 0}
              </div>
            </div>
            <div className="bg-slate-850 border border-slate-750 p-4 rounded-xl text-center">
              <div className="text-xs text-slate-400">Gmail Drafts</div>
              <div className="text-2xl font-bold text-cyan-400 mt-1">
                {overview?.total_drafts ?? 0}
              </div>
            </div>
            <div className="bg-slate-850 border border-slate-750 p-4 rounded-xl text-center">
              <div className="text-xs text-slate-400">Suppressed</div>
              <div className="text-2xl font-bold text-rose-400 mt-1">
                {overview?.suppressed_candidates ?? 0}
              </div>
            </div>
          </div>

          {/* Quick Action Banner */}
          <div className="bg-gradient-to-r from-indigo-950/60 to-slate-900 border border-indigo-800/40 rounded-xl p-6 flex flex-col md:flex-row items-center justify-between gap-4">
            <div className="space-y-1">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Sparkles size={18} className="text-indigo-400" />
                Deterministic Scoring & Compliance Gating
              </h3>
              <p className="text-xs text-slate-300">
                Transparent 100-pt fit scoring (40% skills, 25% exp, 15% lang, 10% loc, 10% other) decoupled from strict outreach compliance gates.
              </p>
            </div>

            <div className="flex items-center gap-2.5">
              <button
                onClick={() => setActiveTab('upload')}
                className="bg-slate-800 hover:bg-slate-700 text-slate-200 px-4 py-2 rounded-lg text-xs font-semibold flex items-center gap-1.5 border border-slate-700 transition-all"
              >
                <FolderUp size={14} />
                Upload CVs
              </button>
              <button
                onClick={handleRunMatching}
                disabled={isEvaluatingMatches}
                className="bg-indigo-600 hover:bg-indigo-500 text-white px-5 py-2 rounded-lg text-xs font-semibold flex items-center gap-1.5 shadow-sm transition-all"
              >
                {isEvaluatingMatches ? <RefreshCw className="animate-spin" size={14} /> : <Play size={14} />}
                Run Match Engine
              </button>
            </div>
          </div>

          {/* Partner Programs Hub */}
          <div className="bg-slate-850 border border-slate-800 rounded-xl p-5 space-y-3">
            <h3 className="text-sm font-bold text-white uppercase tracking-wider">
              Referral Opportunities Hub ({opportunities.length})
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {opportunities.map((opp) => (
                <div key={opp.id} className="bg-slate-900/70 border border-slate-800 p-4 rounded-lg space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-indigo-400 uppercase tracking-wider">
                      {opp.platform}
                    </span>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                        opp.verification_status === 'VERIFIED'
                          ? 'bg-emerald-500/20 text-emerald-300'
                          : opp.verification_status === 'UNDER_REVIEW'
                          ? 'bg-blue-500/20 text-blue-300'
                          : opp.verification_status === 'EXPIRED_INACTIVE'
                          ? 'bg-rose-500/20 text-rose-300'
                          : 'bg-amber-500/20 text-amber-300'
                      }`}
                    >
                      {opp.verification_status}
                    </span>
                  </div>
                  <h4 className="text-sm font-semibold text-white">{opp.title}</h4>
                  <p className="text-xs text-slate-400 line-clamp-2">{opp.description}</p>
                  <div className="text-[11px] text-slate-400 pt-1">
                    {opp.experience_years_min}+ yrs exp · {opp.location_restrictions}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: UPLOAD CVS */}
      {activeTab === 'upload' && (
        <div className="space-y-6">
          <div className="bg-slate-850 border border-slate-700/80 rounded-xl p-6 space-y-5">
            <h2 className="text-base font-semibold text-white flex items-center gap-2">
              <FolderUp size={18} className="text-indigo-400" />
              Windows CV Folder / Archive Ingestion (500–1,000 CVs)
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="md:col-span-2 space-y-1.5">
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-300">
                  Windows Folder Path
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={folderPath}
                    onChange={(e) => setFolderPath(e.target.value)}
                    placeholder="e.g. D:\recuirtement tool\sample_cvs or C:\Users\...\Desktop\CVs"
                    className="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                  />
                  <select
                    value={batchSize}
                    onChange={(e) => setBatchSize(Number(e.target.value))}
                    className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2.5 text-sm text-slate-300 focus:outline-none"
                    title="Batch Chunk Size"
                  >
                    <option value={10}>10 / chunk</option>
                    <option value={15}>15 / chunk</option>
                    <option value={25}>25 / chunk</option>
                    <option value={50}>50 / chunk</option>
                  </select>
                  <button
                    onClick={handleStartFolderImport}
                    disabled={isImporting || !folderPath.trim()}
                    className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white px-5 py-2.5 rounded-lg text-sm font-semibold flex items-center gap-2 shadow-sm transition-all"
                  >
                    {isImporting ? <RefreshCw className="animate-spin" size={16} /> : <Play size={16} />}
                    Scan & Import
                  </button>
                </div>
                <p className="text-xs text-slate-400">
                  Recursively extracts text from PDF, DOCX, RTF, and TXT files using local offline parsers. No PII is sent to external cloud APIs.
                </p>
              </div>

              {/* ZIP Upload Alternative */}
              <div className="space-y-1.5">
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-300">
                  Or Upload ZIP Archive
                </label>
                <input
                  type="file"
                  ref={zipInputRef}
                  accept=".zip"
                  onChange={handleZipUpload}
                  className="hidden"
                />
                <button
                  onClick={() => zipInputRef.current?.click()}
                  disabled={isImporting}
                  className="w-full bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 px-4 py-2.5 rounded-lg text-sm font-semibold flex items-center justify-center gap-2 transition-all"
                >
                  <FileArchive size={16} className="text-indigo-400" />
                  Select .ZIP Archive
                </button>
                <p className="text-xs text-slate-400">
                  Safely unpacks resumes with Zip-Slip protection, symlink rejection, and SHA-256 deduplication.
                </p>
              </div>
            </div>

            {importMessage && (
              <div
                className={`p-3.5 rounded-lg text-sm flex items-center gap-2.5 ${
                  importMessage.type === 'success'
                    ? 'bg-emerald-500/10 border border-emerald-500/30 text-emerald-300'
                    : 'bg-rose-500/10 border border-rose-500/30 text-rose-300'
                }`}
              >
                {importMessage.type === 'success' ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
                <span>{importMessage.text}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* TAB 3: CV LIBRARY */}
      {activeTab === 'library' && (
        <div className="space-y-6">
          <div className="bg-slate-850 border border-slate-700/80 rounded-xl p-4 flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="relative flex-1 w-full">
              <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={candidateSearch}
                onChange={(e) => setCandidateSearch(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && loadCandidates()}
                placeholder="Search candidates by name, email, or skill..."
                className="w-full bg-slate-900 border border-slate-700 rounded-lg pl-10 pr-4 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div className="flex items-center gap-3 w-full sm:w-auto justify-end">
              <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={optOutOnly}
                  onChange={(e) => {
                    setOptOutOnly(e.target.checked);
                    loadCandidates();
                  }}
                  className="rounded border-slate-700 text-indigo-600 focus:ring-0 bg-slate-900"
                />
                Suppressed Only
              </label>

              <button
                onClick={loadCandidates}
                className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-lg text-sm font-semibold flex items-center gap-2 transition-all shadow-sm"
              >
                <Search size={14} />
                Filter
              </button>
            </div>
          </div>

          <div className="bg-slate-850 border border-slate-700/80 rounded-xl overflow-hidden shadow-sm">
            <div className="bg-slate-900/80 px-6 py-3 border-b border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                  Indexed Candidates ({candidates.length})
                </h3>
                <span className="text-xs text-slate-400">
                  Showing {candidates.length === 0 ? 0 : (candidatePage - 1) * CANDIDATES_PER_PAGE + 1}–
                  {Math.min(candidatePage * CANDIDATES_PER_PAGE, candidates.length)} of {candidates.length}
                </span>
              </div>
              {loadingCandidates && <RefreshCw size={14} className="animate-spin text-slate-400" />}
            </div>

            <div className="divide-y divide-slate-800 max-h-[650px] overflow-y-auto">
              {displayedCandidates.length === 0 ? (
                <div className="p-12 text-center text-slate-400 text-sm">
                  No candidates found matching query.
                </div>
              ) : (
                displayedCandidates.map((cand) => {
                  const isOptedOut = cand.opt_out_status === 1;
                  const permBasisUpper = (cand.contact_permission_basis || 'PENDING_REVIEW').toUpperCase();
                  const emailStatusUpper = (cand.email_verification_status || 'PENDING_VERIFICATION').toUpperCase();
                  const isAmbiguous = cand.status === 'AMBIGUOUS_REVIEW';

                  return (
                    <div
                      key={cand.id}
                      className="p-5 hover:bg-slate-800/30 transition-colors flex flex-col md:flex-row md:items-center justify-between gap-4"
                    >
                      <div className="space-y-1.5 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-base font-bold text-white">{cand.name}</span>

                          {/* Ambiguity Warning */}
                          {isAmbiguous && (
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-amber-950/80 border border-amber-600/60 text-amber-300 flex items-center gap-1">
                              <AlertTriangle size={11} />
                              Ambiguous Match Review
                            </span>
                          )}

                          {/* Opt-Out Badge */}
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                              isOptedOut
                                ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                                : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                            }`}
                          >
                            {isOptedOut ? 'Suppressed (Opted Out)' : 'Active'}
                          </span>

                          {/* Contact Permission Badge */}
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase border ${
                              permBasisUpper === 'APPROVED_OUTREACH' || permBasisUpper === 'DIRECT_CONSENT'
                                ? 'bg-emerald-950/60 text-emerald-300 border-emerald-700/50'
                                : permBasisUpper === 'PENDING_REVIEW'
                                ? 'bg-amber-950/60 text-amber-300 border-amber-700/50'
                                : permBasisUpper === 'OPTED_OUT'
                                ? 'bg-rose-950/60 text-rose-300 border-rose-700/50'
                                : 'bg-slate-800 text-slate-300 border-slate-700'
                            }`}
                          >
                            Basis: {cand.contact_permission_basis || 'PENDING_REVIEW'}
                          </span>

                          {/* Email Verification Status Badge */}
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase border ${
                              emailStatusUpper === 'VERIFIED'
                                ? 'bg-teal-950/60 text-teal-300 border-teal-700/50'
                                : emailStatusUpper === 'INVALID'
                                ? 'bg-rose-950/60 text-rose-300 border-rose-700/50'
                                : 'bg-slate-850 text-slate-400 border-slate-700'
                            }`}
                          >
                            Email: {emailStatusUpper}
                          </span>
                        </div>

                        <div className="text-xs text-slate-300 flex flex-wrap items-center gap-x-4 gap-y-1">
                          {cand.email ? (
                            <span className="text-indigo-300 font-mono">{cand.email}</span>
                          ) : (
                            <span className="text-rose-400/80 italic">No email extracted</span>
                          )}
                          {cand.phone && <span>{cand.phone}</span>}
                          {cand.location && <span>{cand.location}</span>}
                          {cand.headline && <span className="text-slate-400 italic">{cand.headline}</span>}
                        </div>

                        {/* Audit Details */}
                        {(cand.permission_reviewed_by || cand.permission_notes) && (
                          <div className="text-[11px] text-slate-400 flex items-center gap-1.5 pt-0.5">
                            <Info size={12} className="text-indigo-400 shrink-0" />
                            <span>
                              Audited by <strong className="text-slate-300">{cand.permission_reviewed_by || 'Reviewer'}</strong>
                              {cand.permission_reviewed_at && ` on ${new Date(cand.permission_reviewed_at).toLocaleDateString()}`}
                              {cand.permission_notes && `: "${cand.permission_notes}"`}
                            </span>
                          </div>
                        )}

                        <div className="flex flex-wrap items-center gap-1.5 pt-1">
                          {Array.isArray(cand.skills) &&
                            cand.skills.slice(0, 6).map((skill: string, i: number) => (
                              <span key={i} className="px-2 py-0.5 rounded bg-slate-800 text-[11px] text-slate-300">
                                {skill}
                              </span>
                            ))}
                          {cand.file_count && cand.file_count > 0 && (
                            <span className="text-[11px] text-indigo-400 bg-indigo-950/40 px-2 py-0.5 rounded border border-indigo-800/40">
                              {cand.file_count} CV file{cand.file_count > 1 ? 's' : ''}
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="flex items-center gap-2 shrink-0">
                        <button
                          onClick={() => openPermissionModal(cand)}
                          className="px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 border border-indigo-700 bg-indigo-950/40 hover:bg-indigo-900/60 text-indigo-300 transition-all"
                          title="Review and update contact permission and email verification"
                        >
                          <ShieldCheck size={14} />
                          Review Permission
                        </button>
                        <button
                          onClick={() => handleToggleOptOut(cand)}
                          className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 border transition-all ${
                            isOptedOut
                              ? 'bg-emerald-950/40 hover:bg-emerald-900/60 border-emerald-800 text-emerald-300'
                              : 'bg-rose-950/40 hover:bg-rose-900/60 border-rose-800 text-rose-300'
                          }`}
                        >
                          <UserX size={14} />
                          {isOptedOut ? 'Revoke Opt-Out' : 'Record Opt-Out'}
                        </button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            {/* Pagination Controls */}
            {totalCandidatePages > 1 && (
              <div className="bg-slate-900/80 px-6 py-3 border-t border-slate-800 flex items-center justify-between">
                <span className="text-xs text-slate-400">
                  Page {candidatePage} of {totalCandidatePages}
                </span>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setCandidatePage((p) => Math.max(1, p - 1))}
                    disabled={candidatePage === 1}
                    className="p-1.5 rounded border border-slate-700 bg-slate-800 text-slate-300 disabled:opacity-40 hover:bg-slate-700 transition-all"
                  >
                    <ChevronLeft size={16} />
                  </button>
                  <button
                    onClick={() => setCandidatePage((p) => Math.min(totalCandidatePages, p + 1))}
                    disabled={candidatePage === totalCandidatePages}
                    className="p-1.5 rounded border border-slate-700 bg-slate-800 text-slate-300 disabled:opacity-40 hover:bg-slate-700 transition-all"
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Permission Review Modal */}
          {permissionCandidate && (
            <div className="fixed inset-0 bg-black/75 flex items-center justify-center p-4 z-50">
              <div className="bg-slate-850 border border-slate-700 rounded-xl p-6 max-w-lg w-full space-y-4">
                <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                  <h3 className="text-base font-bold text-white flex items-center gap-2">
                    <ShieldCheck size={18} className="text-indigo-400" />
                    Review Contact Permission: {permissionCandidate.name}
                  </h3>
                  <button
                    onClick={() => setPermissionCandidate(null)}
                    className="text-slate-400 hover:text-white"
                  >
                    <X size={18} />
                  </button>
                </div>

                <div className="space-y-3.5 text-xs">
                  <div>
                    <label className="text-slate-400 font-semibold uppercase tracking-wider block mb-1">
                      Contact Permission Basis
                    </label>
                    <select
                      value={permBasis}
                      onChange={(e) => setPermBasis(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500"
                    >
                      <option value="APPROVED_OUTREACH">APPROVED_OUTREACH — Recruiter reviewed & approved</option>
                      <option value="DIRECT_CONSENT">DIRECT_CONSENT — Direct candidate consent confirmed</option>
                      <option value="PENDING_REVIEW">PENDING_REVIEW — Not yet verified (Blocks outreach drafts)</option>
                      <option value="UNVERIFIED">UNVERIFIED — Ambiguous or unverified source</option>
                      <option value="OPTED_OUT">OPTED_OUT — Candidate requested suppression</option>
                    </select>
                  </div>

                  <div>
                    <label className="text-slate-400 font-semibold uppercase tracking-wider block mb-1">
                      Email Verification Status
                    </label>
                    <select
                      value={permEmailStatus}
                      onChange={(e) => setPermEmailStatus(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500"
                    >
                      <option value="VERIFIED">VERIFIED — Valid and active email</option>
                      <option value="PENDING_VERIFICATION">PENDING_VERIFICATION — Extracted but unverified</option>
                      <option value="INVALID">INVALID — Bounced, invalid format or missing</option>
                    </select>
                  </div>

                  <div>
                    <label className="text-slate-400 font-semibold uppercase tracking-wider block mb-1">
                      Reviewer Name / ID
                    </label>
                    <input
                      type="text"
                      value={permReviewer}
                      onChange={(e) => setPermReviewer(e.target.value)}
                      placeholder="e.g. Recruiter Lead or Staff Recruiter"
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500"
                    />
                  </div>

                  <div>
                    <label className="text-slate-400 font-semibold uppercase tracking-wider block mb-1">
                      Audit Notes & Evidence
                    </label>
                    <textarea
                      rows={3}
                      value={permNotes}
                      onChange={(e) => setPermNotes(e.target.value)}
                      placeholder="e.g. Verified candidate resume submitted directly via recruitment intake / portfolio consent."
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500"
                    />
                  </div>
                </div>

                <div className="flex justify-end gap-2 pt-2 border-t border-slate-800">
                  <button
                    onClick={() => setPermissionCandidate(null)}
                    className="px-4 py-2 rounded-lg text-xs text-slate-400 hover:text-white"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleSavePermission}
                    disabled={savingPermission}
                    className="bg-indigo-600 hover:bg-indigo-500 text-white px-5 py-2 rounded-lg text-xs font-semibold flex items-center gap-1.5 shadow-sm transition-all"
                  >
                    {savingPermission ? <RefreshCw className="animate-spin" size={14} /> : <Check size={14} />}
                    Save Permission Audit
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 4: REFERRAL OPPORTUNITIES */}
      {activeTab === 'opportunities' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-white">Managed Partner Opportunities</h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Every opportunity must be audited and verified before outreach drafts can be created.
              </p>
            </div>
            <button
              onClick={() => setShowAddOppModal(true)}
              className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-lg text-xs font-semibold flex items-center gap-1.5 shadow-sm transition-all"
            >
              <Plus size={14} />
              Add Opportunity
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {opportunities.map((opp) => (
              <div key={opp.id} className="bg-slate-850 border border-slate-750 p-5 rounded-xl space-y-3 flex flex-col justify-between">
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-indigo-400 uppercase tracking-wider">{opp.platform}</span>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                        opp.verification_status === 'VERIFIED'
                          ? 'bg-emerald-500/20 text-emerald-300'
                          : opp.verification_status === 'UNDER_REVIEW'
                          ? 'bg-blue-500/20 text-blue-300'
                          : opp.verification_status === 'EXPIRED_INACTIVE'
                          ? 'bg-rose-500/20 text-rose-300'
                          : 'bg-amber-500/20 text-amber-300'
                      }`}
                    >
                      {opp.verification_status}
                    </span>
                  </div>
                  <h3 className="text-base font-bold text-white">{opp.title}</h3>
                  <p className="text-xs text-slate-400">{opp.description}</p>
                </div>

                <div className="space-y-2 border-t border-slate-800 pt-3">
                  <div className="text-xs text-slate-300">
                    <span className="text-slate-500">Requirements:</span> {opp.requirements.join(', ')}
                  </div>
                  <div className="text-xs text-slate-300">
                    <span className="text-slate-500">Min Exp:</span> {opp.experience_years_min}+ years · {opp.location_restrictions}
                  </div>

                  {/* Official URL */}
                  {opp.official_url && (
                    <div className="text-xs text-slate-300 truncate">
                      <span className="text-slate-500">Official Portal:</span>{' '}
                      <a href={opp.official_url} target="_blank" rel="noreferrer" className="underline hover:text-indigo-300">
                        {opp.official_url}
                      </a>
                    </div>
                  )}

                  {/* Referral URL */}
                  {(opp.referral_url || (opp.links && opp.links.length > 0)) && (
                    <div className="text-xs text-indigo-300 truncate">
                      <span className="text-slate-500">Referral Link:</span>{' '}
                      <a
                        href={opp.referral_url || (opp.links ? opp.links[0]?.url : '#')}
                        target="_blank"
                        rel="noreferrer"
                        className="underline hover:text-indigo-200"
                      >
                        {opp.referral_url || (opp.links ? opp.links[0]?.url : '')}
                      </a>
                    </div>
                  )}

                  {/* Verification Audit Info */}
                  {opp.verified_by && (
                    <div className="text-[11px] text-slate-400 pt-1">
                      Verified by <strong className="text-slate-300">{opp.verified_by}</strong>
                      {opp.verified_at && ` (${new Date(opp.verified_at).toLocaleDateString()})`}
                      {opp.verification_notes && `: "${opp.verification_notes}"`}
                    </div>
                  )}

                  <button
                    onClick={() => openOppVerifyModal(opp)}
                    className="mt-2 w-full py-1.5 px-3 rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5 border border-indigo-700 bg-indigo-950/40 hover:bg-indigo-900/60 text-indigo-300 transition-all"
                  >
                    <ShieldCheck size={14} />
                    Audit & Verify Opportunity
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* Add Opportunity Modal */}
          {showAddOppModal && (
            <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50">
              <div className="bg-slate-850 border border-slate-700 rounded-xl p-6 max-w-md w-full space-y-4">
                <h3 className="text-base font-bold text-white">Add Partner Opportunity</h3>
                <div className="space-y-3">
                  <div>
                    <label className="text-xs text-slate-400">Platform</label>
                    <input
                      type="text"
                      value={newOppPlatform}
                      onChange={(e) => setNewOppPlatform(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded p-2 text-sm text-white"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-slate-400">Role Title</label>
                    <input
                      type="text"
                      value={newOppTitle}
                      onChange={(e) => setNewOppTitle(e.target.value)}
                      placeholder="e.g. Senior Machine Learning Engineer"
                      className="w-full bg-slate-900 border border-slate-700 rounded p-2 text-sm text-white"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-slate-400">Official Portal URL</label>
                    <input
                      type="text"
                      value={newOppUrl}
                      onChange={(e) => setNewOppUrl(e.target.value)}
                      placeholder="https://..."
                      className="w-full bg-slate-900 border border-slate-700 rounded p-2 text-sm text-white"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-slate-400">Referral Link URL (Optional)</label>
                    <input
                      type="text"
                      value={newOppReferralUrl}
                      onChange={(e) => setNewOppReferralUrl(e.target.value)}
                      placeholder="https://.../?ref=..."
                      className="w-full bg-slate-900 border border-slate-700 rounded p-2 text-sm text-white"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-slate-400">Required Skills (comma separated)</label>
                    <input
                      type="text"
                      value={newOppReqs}
                      onChange={(e) => setNewOppReqs(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded p-2 text-sm text-white"
                    />
                  </div>
                </div>

                <div className="flex justify-end gap-2 pt-2">
                  <button
                    onClick={() => setShowAddOppModal(false)}
                    className="px-4 py-2 rounded text-xs text-slate-400 hover:text-white"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleCreateOpportunity}
                    className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded text-xs font-semibold"
                  >
                    Create Opportunity
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Verify Opportunity Modal */}
          {verifyingOpp && (
            <div className="fixed inset-0 bg-black/75 flex items-center justify-center p-4 z-50">
              <div className="bg-slate-850 border border-slate-700 rounded-xl p-6 max-w-lg w-full space-y-4">
                <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                  <h3 className="text-base font-bold text-white flex items-center gap-2">
                    <ShieldCheck size={18} className="text-indigo-400" />
                    Audit Opportunity: {verifyingOpp.platform} - {verifyingOpp.title}
                  </h3>
                  <button onClick={() => setVerifyingOpp(null)} className="text-slate-400 hover:text-white">
                    <X size={18} />
                  </button>
                </div>

                <div className="space-y-3.5 text-xs">
                  <div>
                    <label className="text-slate-400 font-semibold uppercase tracking-wider block mb-1">
                      Verification Status
                    </label>
                    <select
                      value={oppStatus}
                      onChange={(e) => setOppStatus(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500"
                    >
                      <option value="VERIFIED">VERIFIED — Program active & referral link confirmed</option>
                      <option value="UNDER_REVIEW">UNDER_REVIEW — In review / pending documentation</option>
                      <option value="UNVERIFIED">UNVERIFIED — Unconfirmed program (Blocks outreach drafts)</option>
                      <option value="EXPIRED_INACTIVE">EXPIRED_INACTIVE — Role closed or program expired</option>
                    </select>
                  </div>

                  <div>
                    <label className="text-slate-400 font-semibold uppercase tracking-wider block mb-1">
                      Verification Source
                    </label>
                    <input
                      type="text"
                      value={oppSource}
                      onChange={(e) => setOppSource(e.target.value)}
                      placeholder="e.g. Official partner documentation / platform affiliate portal"
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500"
                    />
                  </div>

                  <div>
                    <label className="text-slate-400 font-semibold uppercase tracking-wider block mb-1">
                      Verification Notes & Audit Trail
                    </label>
                    <textarea
                      rows={3}
                      value={oppNotes}
                      onChange={(e) => setOppNotes(e.target.value)}
                      placeholder="e.g. Audited live job listing on official career site; referral mechanism validated."
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500"
                    />
                  </div>
                </div>

                <div className="flex justify-end gap-2 pt-2 border-t border-slate-800">
                  <button
                    onClick={() => setVerifyingOpp(null)}
                    className="px-4 py-2 rounded-lg text-xs text-slate-400 hover:text-white"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleSaveOppVerification}
                    disabled={savingOppVerification}
                    className="bg-indigo-600 hover:bg-indigo-500 text-white px-5 py-2 rounded-lg text-xs font-semibold flex items-center gap-1.5 shadow-sm transition-all"
                  >
                    {savingOppVerification ? <RefreshCw className="animate-spin" size={14} /> : <Check size={14} />}
                    Save Verification
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 5: MATCH REVIEW */}
      {activeTab === 'matches' && (
        <div className="space-y-6">
          <div className="bg-slate-850 border border-slate-700/80 rounded-xl p-4 flex flex-col md:flex-row items-center justify-between gap-4">
            <div className="flex flex-wrap items-center gap-3 w-full md:w-auto">
              <select
                value={matchFilterOpp || ''}
                onChange={(e) => {
                  const val = e.target.value ? Number(e.target.value) : undefined;
                  setMatchFilterOpp(val);
                }}
                className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none"
              >
                <option value="">All Partner Opportunities</option>
                {opportunities.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.platform} - {o.title}
                  </option>
                ))}
              </select>

              <select
                value={matchMinScore}
                onChange={(e) => setMatchMinScore(Number(e.target.value))}
                className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none"
              >
                <option value={40}>Min Score: 40+ (All Matches)</option>
                <option value={60}>Min Score: 60+ (Moderate)</option>
                <option value={75}>Min Score: 75+ (High Confidence)</option>
              </select>

              <button
                onClick={loadMatches}
                className="bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 px-3 py-2 rounded-lg text-xs font-medium"
              >
                Apply Filters
              </button>
            </div>

            <button
              onClick={handleRunMatching}
              disabled={isEvaluatingMatches}
              className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-lg text-xs font-semibold flex items-center gap-1.5 shadow-sm transition-all"
            >
              {isEvaluatingMatches ? <RefreshCw className="animate-spin" size={14} /> : <Play size={14} />}
              Re-Evaluate Matches
            </button>
          </div>

          <div className="space-y-4">
            {matches.length === 0 ? (
              <div className="bg-slate-850 border border-slate-800 rounded-xl p-12 text-center text-slate-400 text-sm">
                No candidate matches found matching the criteria. Click "Re-Evaluate Matches" to compute match scores.
              </div>
            ) : (
              matches.map((m) => {
                const isEligible = m.outreach_eligibility === 'ELIGIBLE';
                const isBlocked = m.outreach_eligibility === 'BLOCKED';

                return (
                  <div key={m.id} className="bg-slate-850 border border-slate-750 p-5 rounded-xl space-y-4">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-base font-bold text-white">{m.candidate_name}</span>
                          <span className="text-xs text-slate-400">→</span>
                          <span className="text-sm font-semibold text-indigo-400">
                            {m.opportunity_platform}: {m.opportunity_title}
                          </span>
                        </div>
                        <div className="text-xs text-slate-400 mt-0.5">
                          {m.candidate_email || 'No email'} · {m.candidate_location || 'Unknown location'}
                        </div>
                      </div>

                      <div className="flex items-center gap-3">
                        {/* Fit Score & Outreach Status */}
                        <div className="text-right">
                          <div className="text-xl font-extrabold text-white">{m.score}/100</div>
                          <div
                            className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded border inline-block mt-0.5 ${
                              isEligible
                                ? 'bg-emerald-950/60 text-emerald-300 border-emerald-700/50'
                                : isBlocked
                                ? 'bg-rose-950/60 text-rose-300 border-rose-700/50'
                                : 'bg-amber-950/60 text-amber-300 border-amber-700/50'
                            }`}
                          >
                            {m.outreach_eligibility || m.recommendation}
                          </div>
                        </div>

                        <button
                          onClick={() => handleGenerateDraftFromMatch(m)}
                          className="bg-indigo-600 hover:bg-indigo-500 text-white px-3.5 py-2 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all shadow-sm"
                        >
                          <Mail size={13} />
                          Prepare Draft
                        </button>
                      </div>
                    </div>

                    {/* Score Breakdown Pills */}
                    <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-center text-xs">
                      <div className="bg-slate-900 p-2 rounded border border-slate-800">
                        <span className="text-slate-400 block text-[11px]">Skills</span>
                        <span className="font-bold text-slate-200">{m.score_breakdown.skills_score}/40</span>
                      </div>
                      <div className="bg-slate-900 p-2 rounded border border-slate-800">
                        <span className="text-slate-400 block text-[11px]">Experience</span>
                        <span className="font-bold text-slate-200">{m.score_breakdown.experience_score}/25</span>
                      </div>
                      <div className="bg-slate-900 p-2 rounded border border-slate-800">
                        <span className="text-slate-400 block text-[11px]">Language</span>
                        <span className="font-bold text-slate-200">{m.score_breakdown.language_score}/15</span>
                      </div>
                      <div className="bg-slate-900 p-2 rounded border border-slate-800">
                        <span className="text-slate-400 block text-[11px]">Location</span>
                        <span className="font-bold text-slate-200">{m.score_breakdown.location_score}/10</span>
                      </div>
                      <div className="bg-slate-900 p-2 rounded border border-slate-800">
                        <span className="text-slate-400 block text-[11px]">Other</span>
                        <span className="font-bold text-slate-200">{m.score_breakdown.other_score}/10</span>
                      </div>
                    </div>

                    {/* Skills tags & Gating notes */}
                    <div className="space-y-1.5 text-xs">
                      {m.matched_requirements.length > 0 && (
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="text-slate-400">Matched Skills:</span>
                          {m.matched_requirements.map((s, i) => (
                            <span key={i} className="bg-emerald-950/40 border border-emerald-800/40 text-emerald-300 px-2 py-0.5 rounded text-[11px]">
                              {s}
                            </span>
                          ))}
                        </div>
                      )}
                      {m.missing_requirements.length > 0 && (
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="text-slate-400">Missing Requirements:</span>
                          {m.missing_requirements.map((s, i) => (
                            <span key={i} className="bg-amber-950/40 border border-amber-800/40 text-amber-300 px-2 py-0.5 rounded text-[11px]">
                              {s}
                            </span>
                          ))}
                        </div>
                      )}
                      {m.contradictions.length > 0 && (
                        <div className="text-rose-400">
                          Notice: {m.contradictions.join('; ')}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* Blocked Draft Warning Modal */}
          {blockedWarning && (
            <div className="fixed inset-0 bg-black/75 flex items-center justify-center p-4 z-50">
              <div className="bg-slate-850 border border-amber-500/40 rounded-xl p-6 max-w-lg w-full space-y-4">
                <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                  <h3 className="text-base font-bold text-amber-300 flex items-center gap-2">
                    <ShieldAlert size={20} className="text-amber-400" />
                    Draft Blocked by Compliance Gating
                  </h3>
                  <button onClick={() => setBlockedWarning(null)} className="text-slate-400 hover:text-white">
                    <X size={18} />
                  </button>
                </div>

                <div className="space-y-3 text-xs">
                  <p className="text-slate-300">
                    A Gmail draft cannot be generated for <strong className="text-white">{blockedWarning.candidateName}</strong> for{' '}
                    <strong className="text-indigo-300">{blockedWarning.opportunityTitle}</strong> until all prerequisites are satisfied:
                  </p>

                  <ul className="list-disc list-inside space-y-1.5 text-rose-300 bg-slate-900/80 p-3 rounded-lg border border-slate-800">
                    {blockedWarning.reasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>

                  <p className="text-slate-400">
                    To maintain strict candidate privacy, contact permissions must be explicitly approved in the CV Library and referral opportunities must be verified in the Opportunities tab.
                  </p>
                </div>

                <div className="flex justify-end gap-2 pt-2 border-t border-slate-800">
                  <button
                    onClick={() => setBlockedWarning(null)}
                    className="px-4 py-2 rounded-lg text-xs text-slate-400 hover:text-white"
                  >
                    Dismiss
                  </button>
                  {blockedWarning.suggestedTab && (
                    <button
                      onClick={() => {
                        const tab = blockedWarning.suggestedTab!;
                        setBlockedWarning(null);
                        setActiveTab(tab);
                      }}
                      className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-lg text-xs font-semibold"
                    >
                      Go to {blockedWarning.suggestedTab === 'opportunities' ? 'Opportunities' : 'CV Library'}
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 6: GMAIL DRAFTS */}
      {activeTab === 'drafts' && (
        <div className="space-y-6">
          {/* Gmail Auth Status Banner */}
          <div className="bg-slate-850 border border-slate-700/80 rounded-xl p-5 flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className={`w-2.5 h-2.5 rounded-full ${gmailAuth?.authenticated ? 'bg-emerald-400' : 'bg-amber-400'}`} />
                <h3 className="text-sm font-bold text-white">
                  {gmailAuth?.authenticated ? 'Gmail OAuth Connected (Compose-Only Scope)' : 'Gmail OAuth Offline / Ready for Setup'}
                </h3>
              </div>
              <p className="text-xs text-slate-400">{gmailAuth?.message}</p>
            </div>

            <div className="flex items-center gap-2">
              {gmailAuth?.authenticated ? (
                <button
                  onClick={handleDisconnectGmail}
                  className="bg-rose-950/40 hover:bg-rose-900/60 border border-rose-800 text-rose-300 px-3.5 py-2 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all"
                >
                  <LogOut size={14} />
                  Disconnect Gmail
                </button>
              ) : (
                <button
                  onClick={handleConnectGmail}
                  className="bg-indigo-600 hover:bg-indigo-500 text-white px-3.5 py-2 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all shadow-sm"
                >
                  <Mail size={14} />
                  Connect Gmail (OAuth)
                </button>
              )}
              <a
                href="https://mail.google.com/mail/u/0/#drafts"
                target="_blank"
                rel="noreferrer"
                className="bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 px-3.5 py-2 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all"
              >
                <ExternalLink size={14} />
                Open Gmail Drafts
              </a>
            </div>
          </div>

          {/* Drafts List */}
          <div className="space-y-4">
            {drafts.length === 0 ? (
              <div className="bg-slate-850 border border-slate-800 rounded-xl p-12 text-center text-slate-400 text-sm">
                No outreach drafts created yet. Go to "Match Review" and click "Prepare Draft" on any qualified candidate.
              </div>
            ) : (
              drafts.map((d) => (
                <div key={d.id} className="bg-slate-850 border border-slate-750 p-5 rounded-xl space-y-3">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-bold text-white">{d.candidate_name}</span>
                        <span className="text-xs text-indigo-400 font-mono">({d.recipient_email})</span>
                      </div>
                      <div className="text-xs text-slate-400 mt-0.5">
                        Role: {d.opportunity_platform} - {d.opportunity_title}
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                          d.status === 'CREATED_IN_GMAIL'
                            ? 'bg-emerald-500/20 text-emerald-300'
                            : d.status === 'SIMULATED_DRAFT'
                            ? 'bg-sky-500/20 text-sky-300'
                            : d.status === 'CREATING'
                            ? 'bg-indigo-500/20 text-indigo-300 animate-pulse'
                            : d.status === 'SENT_MANUALLY'
                            ? 'bg-purple-500/20 text-purple-300'
                            : 'bg-rose-500/20 text-rose-300'
                        }`}
                      >
                        {d.status === 'CREATED_IN_GMAIL'
                          ? 'Live Gmail Draft'
                          : d.status === 'SIMULATED_DRAFT'
                          ? 'Simulated Draft'
                          : d.status === 'CREATING'
                          ? 'Creating in Background...'
                          : d.status === 'SENT_MANUALLY'
                          ? 'Sent Manually'
                          : d.status}
                      </span>
                      {d.gmail_draft_id && (
                        <span className="text-[10px] bg-slate-900 text-slate-400 px-2 py-0.5 rounded border border-slate-800">
                          ID: {d.gmail_draft_id.slice(0, 12)}...
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="bg-slate-900/80 p-3.5 rounded-lg border border-slate-800 space-y-1.5 text-xs">
                    <div className="font-semibold text-slate-200">Subject: {d.subject}</div>
                    <div className="text-slate-400 whitespace-pre-wrap max-h-36 overflow-y-auto font-mono text-[11px]">
                      {d.body_text}
                    </div>
                  </div>

                  <div className="flex items-center justify-between pt-1">
                    <div className="text-[11px] text-slate-500">
                      Idempotency Key: {d.idempotency_key}
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => openEditDraft(d)}
                        className="bg-slate-800 hover:bg-slate-700 text-slate-200 px-3 py-1.5 rounded text-xs font-semibold flex items-center gap-1.5"
                      >
                        <Edit3 size={13} />
                        Edit Draft
                      </button>
                      <button
                        onClick={() => api.updateDraftStatus(d.id, 'SENT_MANUALLY').then(loadDrafts)}
                        className="bg-emerald-950/40 hover:bg-emerald-900/60 border border-emerald-800 text-emerald-300 px-3 py-1.5 rounded text-xs font-semibold flex items-center gap-1.5"
                      >
                        <Check size={13} />
                        Mark Sent
                      </button>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Edit Draft Modal */}
          {editingDraft && (
            <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50">
              <div className="bg-slate-850 border border-slate-700 rounded-xl p-6 max-w-2xl w-full space-y-4">
                <h3 className="text-base font-bold text-white">Edit Outreach Draft</h3>
                <div className="space-y-3">
                  <div>
                    <label className="text-xs text-slate-400">Subject</label>
                    <input
                      type="text"
                      value={editSubject}
                      onChange={(e) => setEditSubject(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded p-2 text-sm text-white"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-slate-400">Email Body (Plain Text)</label>
                    <textarea
                      rows={10}
                      value={editBody}
                      onChange={(e) => setEditBody(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded p-2 text-xs text-slate-200 font-mono"
                    />
                  </div>
                </div>

                <div className="flex justify-end gap-2 pt-2">
                  <button
                    onClick={() => setEditingDraft(null)}
                    className="px-4 py-2 rounded text-xs text-slate-400 hover:text-white"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleSaveEditedDraft}
                    className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded text-xs font-semibold"
                  >
                    Save & Update Draft
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 7: IMPORT HISTORY */}
      {activeTab === 'history' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-1 bg-slate-850 border border-slate-700/80 rounded-xl p-5 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                  Batches ({importJobs.length})
                </h3>
                <button onClick={loadJobs} className="text-slate-400 hover:text-white p-1 rounded">
                  <RefreshCw size={14} />
                </button>
              </div>

              <div className="space-y-3 max-h-[500px] overflow-y-auto pr-1">
                {importJobs.map((job) => {
                  const isSelected = selectedJob?.job_id === job.job_id;
                  const percent =
                    job.total_files > 0 ? Math.round((job.processed_files / job.total_files) * 100) : 0;

                  return (
                    <div
                      key={job.job_id}
                      onClick={() => handleSelectJob(job)}
                      className={`p-3.5 rounded-lg border cursor-pointer transition-all ${
                        isSelected
                          ? 'bg-indigo-950/40 border-indigo-500/50'
                          : 'bg-slate-900/60 border-slate-800 hover:border-slate-700'
                      }`}
                    >
                      <div className="flex items-center justify-between text-xs mb-1.5">
                        <span className="font-semibold text-slate-200 truncate max-w-[140px]">
                          {job.source_path.split('\\').pop() || 'Batch Job'}
                        </span>
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                            job.status === 'COMPLETED'
                              ? 'bg-emerald-500/20 text-emerald-300'
                              : job.status === 'PARTIAL'
                              ? 'bg-amber-500/20 text-amber-300'
                              : job.status === 'PROCESSING'
                              ? 'bg-indigo-500/20 text-indigo-300 animate-pulse'
                              : 'bg-rose-500/20 text-rose-300'
                          }`}
                        >
                          {job.status}
                        </span>
                      </div>

                      <div className="w-full bg-slate-800 rounded-full h-1.5 mb-2 overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all duration-300 ${
                            job.status === 'COMPLETED' ? 'bg-emerald-500' : 'bg-indigo-500'
                          }`}
                          style={{ width: `${percent}%` }}
                        />
                      </div>

                      <div className="flex items-center justify-between text-[11px] text-slate-400">
                        <span>
                          {job.processed_files}/{job.total_files} files
                        </span>
                        <span className="text-emerald-400 font-medium">+{job.successful_files} indexed</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Selected Job File Inspector */}
            <div className="lg:col-span-2 bg-slate-850 border border-slate-700/80 rounded-xl p-5 space-y-4">
              {selectedJob ? (
                <>
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
                    <div>
                      <h3 className="text-sm font-bold text-white">Job: {selectedJob.job_id.slice(0, 8)}...</h3>
                      <p className="text-xs text-slate-400 truncate max-w-md">{selectedJob.source_path}</p>
                    </div>

                    <div className="flex items-center gap-2">
                      {selectedJob.status === 'PROCESSING' && (
                        <>
                          <button
                            onClick={() => handlePauseJob(selectedJob.job_id)}
                            className="bg-amber-950/40 hover:bg-amber-900/60 border border-amber-800 text-amber-300 px-3 py-1.5 rounded text-xs font-semibold flex items-center gap-1.5"
                          >
                            <Pause size={14} />
                            Pause
                          </button>
                          <button
                            onClick={() => handleCancelJob(selectedJob.job_id)}
                            className="bg-rose-950/40 hover:bg-rose-900/60 border border-rose-800 text-rose-300 px-3 py-1.5 rounded text-xs font-semibold flex items-center gap-1.5"
                          >
                            <StopCircle size={14} />
                            Cancel
                          </button>
                        </>
                      )}
                      {selectedJob.status === 'PAUSED' && (
                        <>
                          <button
                            onClick={() => handleResumeJob(selectedJob.job_id)}
                            className="bg-emerald-950/40 hover:bg-emerald-900/60 border border-emerald-800 text-emerald-300 px-3 py-1.5 rounded text-xs font-semibold flex items-center gap-1.5"
                          >
                            <Play size={14} />
                            Resume
                          </button>
                          <button
                            onClick={() => handleCancelJob(selectedJob.job_id)}
                            className="bg-rose-950/40 hover:bg-rose-900/60 border border-rose-800 text-rose-300 px-3 py-1.5 rounded text-xs font-semibold flex items-center gap-1.5"
                          >
                            <StopCircle size={14} />
                            Cancel
                          </button>
                        </>
                      )}
                      {(selectedJob.status === 'PARTIAL' || selectedJob.status === 'FAILED') && (
                        <button
                          onClick={() => handleRetryJob(selectedJob.job_id)}
                          className="bg-amber-950/40 hover:bg-amber-900/60 border border-amber-800 text-amber-300 px-3 py-1.5 rounded text-xs font-semibold flex items-center gap-1.5"
                        >
                          <RotateCcw size={14} />
                          Retry Failed
                        </button>
                      )}
                    </div>
                  </div>

                  <div className="border border-slate-800 rounded-lg overflow-hidden">
                    <div className="bg-slate-900/80 px-4 py-2 text-xs font-bold uppercase tracking-wider text-slate-300 flex justify-between">
                      <span>Indexed Files ({jobFiles.length})</span>
                      {loadingFiles && <RefreshCw size={12} className="animate-spin text-slate-400" />}
                    </div>

                    <div className="max-h-[350px] overflow-y-auto divide-y divide-slate-800">
                      {jobFiles.map((file) => (
                        <div key={file.id} className="p-3 text-xs flex items-center justify-between hover:bg-slate-800/40">
                          <div className="truncate max-w-sm">
                            <div className="text-slate-200 font-medium truncate">{file.file_name}</div>
                            {file.error_message && (
                              <div className="text-[11px] text-rose-400 truncate">{file.error_message}</div>
                            )}
                          </div>

                          <div className="flex items-center gap-2">
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                                file.status === 'SUCCESS'
                                  ? 'bg-emerald-500/20 text-emerald-300'
                                  : file.status === 'SKIPPED_DUPLICATE'
                                  ? 'bg-amber-500/20 text-amber-300'
                                  : file.status === 'OCR_REQUIRED'
                                  ? 'bg-indigo-500/20 text-indigo-300'
                                  : 'bg-rose-500/20 text-rose-300'
                              }`}
                            >
                              {file.status}
                            </span>
                            {file.candidate_id && (
                              <span className="text-[10px] bg-slate-800 text-slate-300 px-1.5 py-0.5 rounded">
                                #{file.candidate_id}
                              </span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              ) : (
                <div className="p-12 text-center text-slate-400 text-sm">
                  Select a job from the history to inspect files.
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
export default CvOutreachView;
