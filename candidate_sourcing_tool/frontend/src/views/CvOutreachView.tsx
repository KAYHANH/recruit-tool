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

  // Opportunities State
  const [opportunities, setOpportunities] = useState<ReferralOpportunity[]>([]);
  const [showAddOppModal, setShowAddOppModal] = useState<boolean>(false);
  const [newOppPlatform, setNewOppPlatform] = useState<string>('Turing');
  const [newOppTitle, setNewOppTitle] = useState<string>('');
  const [newOppUrl, setNewOppUrl] = useState<string>('');
  const [newOppReqs, setNewOppReqs] = useState<string>('python, react, fastapi');

  // Matches State
  const [matches, setMatches] = useState<CandidateOpportunityMatch[]>([]);
  const [matchFilterOpp, setMatchFilterOpp] = useState<number | undefined>(undefined);
  const [matchMinScore, setMatchMinScore] = useState<number>(40);
  const [isEvaluatingMatches, setIsEvaluatingMatches] = useState<boolean>(false);

  // Drafts State
  const [drafts, setDrafts] = useState<OutreachDraft[]>([]);
  const [gmailAuth, setGmailAuth] = useState<GmailAuthStatus | null>(null);
  const [editingDraft, setEditingDraft] = useState<OutreachDraft | null>(null);
  const [editSubject, setEditSubject] = useState<string>('');
  const [editBody, setEditBody] = useState<string>('');

  // File upload ref for ZIP
  const zipInputRef = useRef<HTMLInputElement>(null);

  // Initial loader
  const loadOverview = async () => {
    try {
      const data = await api.getCVOutreachOverview();
      setOverview(data);
    } catch (err) {
      console.error(err);
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
      console.error(err);
    }
  };

  const loadCandidates = async () => {
    setLoadingCandidates(true);
    try {
      const data = await api.getReferralCandidates(candidateSearch, optOutOnly);
      setCandidates(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingCandidates(false);
    }
  };

  const loadOpportunities = async () => {
    try {
      const data = await api.getReferralOpportunities();
      setOpportunities(data);
    } catch (err) {
      console.error(err);
    }
  };

  const loadMatches = async () => {
    try {
      const data = await api.getMatches(matchFilterOpp, matchMinScore);
      setMatches(data);
    } catch (err) {
      console.error(err);
    }
  };

  const loadDrafts = async () => {
    try {
      const [d, auth] = await Promise.all([api.getDrafts(), api.getGmailAuthStatus()]);
      setDrafts(d);
      setGmailAuth(auth);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    loadOverview();
    if (activeTab === 'overview') {
      loadOverview();
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

  // Folder Import Handler
  const handleStartFolderImport = async () => {
    if (!folderPath.trim()) {
      setImportMessage({ text: 'Please enter a valid Windows folder path.', type: 'error' });
      return;
    }

    setIsImporting(true);
    setImportMessage(null);
    try {
      const res = await api.startFolderImport(folderPath.trim(), batchSize, false);
      setImportMessage({ text: res.message, type: 'success' });
      await loadJobs();
      await loadOverview();
      const updatedJob = await api.getImportJob(res.job_id);
      setSelectedJob(updatedJob);
      loadJobFiles(res.job_id);
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
      const res = await api.startZipImport(file, batchSize, false);
      setImportMessage({ text: res.message, type: 'success' });
      await loadJobs();
      await loadOverview();
      const updatedJob = await api.getImportJob(res.job_id);
      setSelectedJob(updatedJob);
      loadJobFiles(res.job_id);
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
    } catch (err) {
      console.error(err);
    }
  };

  const handleRetryJob = async (jobId: string) => {
    try {
      await api.retryImportJob(jobId, batchSize);
      await loadJobs();
      loadJobFiles(jobId);
    } catch (err) {
      console.error(err);
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

  // Create Draft from Match
  const handleGenerateDraftFromMatch = async (match: CandidateOpportunityMatch) => {
    try {
      const res = await api.createDraft({
        candidate_id: match.candidate_id,
        opportunity_id: match.opportunity_id,
        save_to_gmail: true,
        mock_mode: true,
      });
      alert(res.message || 'Draft prepared!');
      await loadDrafts();
      await loadOverview();
      setActiveTab('drafts');
    } catch (err: any) {
      alert(`Draft creation error: ${err.message}`);
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
        url: newOppUrl.trim(),
        requirements: reqList,
        verification_status: 'VERIFIED',
      });
      setShowAddOppModal(false);
      setNewOppTitle('');
      setNewOppUrl('');
      await loadOpportunities();
      await loadOverview();
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
        mock_mode: true,
      });
      setEditingDraft(null);
      await loadDrafts();
    } catch (err: any) {
      alert(`Save error: ${err.message}`);
    }
  };

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
                Ready to match imported candidates with Turing, Mercor & micro1?
              </h3>
              <p className="text-xs text-slate-300">
                Execute transparent deterministic scoring (40% skills, 25% exp, 15% lang, 10% loc, 10% other) across all non-opted-out candidates.
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

          {/* Verified Partner Programs */}
          <div className="bg-slate-850 border border-slate-800 rounded-xl p-5 space-y-3">
            <h3 className="text-sm font-bold text-white uppercase tracking-wider">
              Verified Partner Opportunity Hub ({opportunities.length})
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {opportunities.map((opp) => (
                <div key={opp.id} className="bg-slate-900/70 border border-slate-800 p-4 rounded-lg space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-indigo-400 uppercase tracking-wider">
                      {opp.platform}
                    </span>
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-300 uppercase">
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
                  Recursively extracts text from PDF, DOCX, and TXT files using local offline parsers. No PII is sent to external services.
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
                  Safely unpacks resumes into a local folder and indexes records with SHA-256 deduplication.
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
              <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                Indexed Candidates ({candidates.length})
              </h3>
              {loadingCandidates && <RefreshCw size={14} className="animate-spin text-slate-400" />}
            </div>

            <div className="divide-y divide-slate-800 max-h-[600px] overflow-y-auto">
              {candidates.length === 0 ? (
                <div className="p-12 text-center text-slate-400 text-sm">
                  No candidates found matching query.
                </div>
              ) : (
                candidates.map((cand) => {
                  const isOptedOut = cand.opt_out_status === 1;
                  return (
                    <div
                      key={cand.id}
                      className="p-5 hover:bg-slate-800/30 transition-colors flex flex-col md:flex-row md:items-center justify-between gap-4"
                    >
                      <div className="space-y-1.5">
                        <div className="flex items-center gap-3">
                          <span className="text-base font-bold text-white">{cand.name}</span>
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                              isOptedOut ? 'bg-rose-500/20 text-rose-300' : 'bg-emerald-500/20 text-emerald-300'
                            }`}
                          >
                            {isOptedOut ? 'Suppressed (Opted Out)' : 'Eligible for Outreach'}
                          </span>
                          <span className="text-[10px] bg-slate-800 text-slate-300 px-2 py-0.5 rounded border border-slate-700">
                            Basis: {cand.contact_permission_basis || 'public_cv'}
                          </span>
                        </div>

                        <div className="text-xs text-slate-300 flex flex-wrap items-center gap-x-4 gap-y-1">
                          {cand.email && <span className="text-indigo-300 font-mono">{cand.email}</span>}
                          {cand.phone && <span>{cand.phone}</span>}
                          {cand.location && <span>{cand.location}</span>}
                          {cand.headline && <span className="text-slate-400 italic">{cand.headline}</span>}
                        </div>

                        <div className="flex flex-wrap items-center gap-1.5 pt-1">
                          {Array.isArray(cand.skills) &&
                            cand.skills.slice(0, 6).map((skill: string, i: number) => (
                              <span key={i} className="px-2 py-0.5 rounded bg-slate-800 text-[11px] text-slate-300">
                                {skill}
                              </span>
                            ))}
                          {cand.file_count && cand.file_count > 0 && (
                            <span className="text-[11px] text-indigo-400 bg-indigo-950/40 px-2 py-0.5 rounded border border-indigo-800/40">
                              {cand.file_count} CV file{cand.file_count > 1 ? 's' : ''} linked
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="flex items-center gap-2 shrink-0">
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
          </div>
        </div>
      )}

      {/* TAB 4: REFERRAL OPPORTUNITIES */}
      {activeTab === 'opportunities' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-white">Managed Partner Opportunities</h2>
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
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-300 uppercase">
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
                  {opp.links && opp.links.length > 0 && (
                    <div className="text-xs text-indigo-300 truncate">
                      <span className="text-slate-500">Verified Referral URL:</span>{' '}
                      <a href={opp.links[0].url} target="_blank" rel="noreferrer" className="underline hover:text-indigo-200">
                        {opp.links[0].url}
                      </a>
                    </div>
                  )}
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
              matches.map((m) => (
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
                      <div className="text-right">
                        <div className="text-xl font-extrabold text-white">{m.score}/100</div>
                        <div
                          className={`text-[10px] font-bold uppercase ${
                            m.recommendation === 'Eligible for Outreach'
                              ? 'text-emerald-400'
                              : m.recommendation === 'Review'
                              ? 'text-amber-400'
                              : 'text-rose-400'
                          }`}
                        >
                          {m.recommendation}
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

                  {/* Skills tags */}
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
              ))
            )}
          </div>
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
                            : 'bg-amber-500/20 text-amber-300'
                        }`}
                      >
                        {d.status}
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
                        <button
                          onClick={() => handleCancelJob(selectedJob.job_id)}
                          className="bg-rose-950/40 hover:bg-rose-900/60 border border-rose-800 text-rose-300 px-3 py-1.5 rounded text-xs font-semibold flex items-center gap-1.5"
                        >
                          <StopCircle size={14} />
                          Cancel
                        </button>
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
