import React, { useState, useEffect } from 'react';
import {
  X,
  Mail,
  Phone,
  Globe,
  Briefcase,
  Clock,
  ChevronDown,
  Check,
  Sparkles,
  FileText,
  Activity as ActivityIcon,
  ExternalLink,
  ShieldCheck,
  AlertCircle,
  User,
  Send,
  Building2,
  Award,
} from 'lucide-react';
import { api } from '../api';
import { GithubIcon } from './GithubIcon';
import type { FullCandidateProfile } from '../types';

export const LinkedinIcon: React.FC<{ size?: number; className?: string }> = ({ size = 16, className = '' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z" />
    <rect width="4" height="12" x="2" y="9" />
    <circle cx="4" cy="4" r="2" />
  </svg>
);

interface CandidateDetailDrawerProps {
  candidateId: number | null;
  activeJobId: number | null;
  isOpen: boolean;
  onClose: () => void;
  onStageChange?: (candidateId: number, newStage: string) => void;
  onCandidateUpdated?: () => void;
}

export const CandidateDetailDrawer: React.FC<CandidateDetailDrawerProps> = ({
  candidateId,
  activeJobId,
  isOpen,
  onClose,
  onStageChange,
  onCandidateUpdated,
}) => {
  const [activeTab, setActiveTab] = useState<'overview' | 'analysis' | 'resume' | 'activity' | 'jobs'>('overview');
  const [profile, setProfile] = useState<FullCandidateProfile | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Stage dropdown state
  const [isStageOpen, setIsStageOpen] = useState<boolean>(false);
  const [updatingStage, setUpdatingStage] = useState<boolean>(false);

  // Note form state
  const [newNote, setNewNote] = useState<string>('');
  const [isSubmittingNote, setIsSubmittingNote] = useState<boolean>(false);

  // Expanded experience descriptions
  const [expandedExps, setExpandedExps] = useState<Record<number, boolean>>({});

  const toggleExpandExp = (id: number) => {
    setExpandedExps((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const STAGES = [
    { id: 'Sourced', name: 'Sourced', color: 'bg-blue-500/20 text-blue-400 border-blue-500/30 dot: bg-blue-400' },
    { id: 'Under Review', name: 'Under Review', color: 'bg-amber-500/20 text-amber-400 border-amber-500/30 dot: bg-amber-400' },
    { id: 'My Shortlisted', name: 'My Shortlisted', color: 'bg-indigo-500/20 text-indigo-400 border-indigo-500/30 dot: bg-indigo-400' },
    { id: 'Contacted', name: 'Contacted', color: 'bg-purple-500/20 text-purple-400 border-purple-500/30 dot: bg-purple-400' },
    { id: 'Replied', name: 'Replied', color: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30 dot: bg-emerald-400' },
    { id: 'Interview', name: 'Interview', color: 'bg-teal-500/20 text-teal-400 border-teal-500/30 dot: bg-teal-400' },
    { id: 'Rejected', name: 'Rejected', color: 'bg-rose-500/20 text-rose-400 border-rose-500/30 dot: bg-rose-400' },
    { id: 'Archived', name: 'Archived', color: 'bg-slate-700/40 text-slate-400 border-slate-600/30 dot: bg-slate-400' },
  ];

  // Load full profile whenever drawer opens or candidateId/jobId changes
  const loadProfile = async () => {
    if (!candidateId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.getCandidateFullProfile(candidateId, activeJobId || undefined);
      setProfile(data);
    } catch (err: any) {
      console.error('Failed to load candidate full profile:', err);
      setError(err?.message || 'Could not load candidate profile.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen && candidateId) {
      loadProfile();
      setActiveTab('overview');
      setIsStageOpen(false);
    }
  }, [isOpen, candidateId, activeJobId]);

  if (!isOpen) return null;

  const handleStageSelect = async (newStage: string) => {
    if (!profile || !candidateId) return;
    setIsStageOpen(false);
    setUpdatingStage(true);
    try {
      const targetJobId = activeJobId || (profile.associated_jobs[0]?.job_id ?? 1);
      await api.updateCandidateStage(targetJobId, candidateId, newStage, `Stage moved to ${newStage} via Profile Drawer.`);
      setProfile((prev) => (prev ? { ...prev, stage: newStage } : null));
      if (onStageChange) onStageChange(candidateId, newStage);
      if (onCandidateUpdated) onCandidateUpdated();
      // Reload profile to refresh activities timeline
      await loadProfile();
    } catch (err: any) {
      console.error('Failed to update stage:', err);
      alert(`Could not update stage: ${err?.message}`);
    } finally {
      setUpdatingStage(false);
    }
  };

  const handleAddNote = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newNote.trim() || !candidateId) return;
    setIsSubmittingNote(true);
    try {
      await api.addCandidateNote(candidateId, newNote.trim(), 'Recruiter', activeJobId || undefined);
      setNewNote('');
      await loadProfile();
      if (onCandidateUpdated) onCandidateUpdated();
    } catch (err: any) {
      alert(`Failed to save note: ${err?.message}`);
    } finally {
      setIsSubmittingNote(false);
    }
  };

  const currentStageMeta = STAGES.find((s) => s.id === profile?.stage) || STAGES[0];
  const initialLetter = profile?.name ? profile.name.trim().charAt(0).toUpperCase() : '?';

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      {/* Drawer Container */}
      <div className="relative w-full max-w-3xl bg-[#0f172a] text-slate-100 h-full shadow-2xl flex flex-col border-l border-slate-800 z-10 overflow-hidden animate-in slide-in-from-right duration-200">
        {/* Loading Overlay */}
        {loading && (
          <div className="absolute inset-0 bg-[#0f172a]/80 backdrop-blur-xs flex items-center justify-center z-30">
            <div className="flex flex-col items-center gap-2">
              <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
              <span className="text-xs text-slate-400">Loading candidate profile...</span>
            </div>
          </div>
        )}

        {/* Drawer Header matching screenshot */}
        <div className="p-6 border-b border-slate-800/80 bg-slate-900/50">
          <div className="flex items-start justify-between gap-4">
            {/* Left section: Avatar + Details */}
            <div className="flex items-start gap-4 flex-1 min-w-0">
              <button
                onClick={onClose}
                className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors mr-1 mt-1"
                title="Close drawer"
              >
                <X size={18} />
              </button>

              {/* Avatar Initial Circle */}
              <div className="w-12 h-12 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center font-bold text-xl shrink-0 shadow-sm">
                {initialLetter}
              </div>

              {/* Name & Title */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <h2 className="text-xl font-bold text-slate-100 tracking-tight truncate">
                    {profile?.name || 'Loading candidate...'}
                  </h2>
                  {profile?.analysis?.match_score !== undefined && profile.analysis.match_score > 0 && (
                    <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                      {profile.analysis.match_score}% Match
                    </span>
                  )}
                </div>

                <p className="text-sm font-medium text-slate-300 mt-0.5 truncate">
                  {profile?.headline || 'Professional Profile'}
                </p>

                {/* Meta details row: Company, Location, Experience, Added by, Time */}
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 mt-2 text-xs text-slate-400">
                  {profile?.company && (
                    <span className="flex items-center gap-1 text-slate-300 font-medium">
                      <Building2 size={13} className="text-blue-400" />
                      {profile.company}
                    </span>
                  )}

                  {profile?.location && (
                    <span className="flex items-center gap-1">
                      <Globe size={13} className="text-slate-400" />
                      {profile.location}
                    </span>
                  )}

                  <span className="flex items-center gap-1 bg-slate-800 px-2 py-0.5 rounded text-slate-300 font-medium">
                    <Briefcase size={12} className="text-amber-400" />
                    {profile?.years_of_experience ? `${profile.years_of_experience}y exp` : 'Emerging'}
                  </span>

                  <span className="flex items-center gap-1 text-purple-300 font-medium">
                    <User size={13} className="text-purple-400" />
                    Added by {profile?.added_by || 'System Auto-Sourcing'}
                  </span>

                  {profile?.created_at && (
                    <span className="flex items-center gap-1 text-slate-400">
                      <Clock size={12} />
                      {new Date(profile.created_at).toLocaleDateString()}
                    </span>
                  )}
                </div>

                {/* Contact links row */}
                <div className="flex items-center gap-3 mt-3">
                  {profile?.contacts.email ? (
                    <a
                      href={`mailto:${profile.contacts.email}`}
                      className="p-1.5 rounded-md text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                      title={profile.contacts.email}
                    >
                      <Mail size={16} />
                    </a>
                  ) : (
                    <span className="p-1.5 text-slate-400" title="Email not publicly published">
                      <Mail size={16} />
                    </span>
                  )}

                  {profile?.contacts.phone ? (
                    <a
                      href={`tel:${profile.contacts.phone}`}
                      className="p-1.5 rounded-md text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                      title={profile.contacts.phone}
                    >
                      <Phone size={16} />
                    </a>
                  ) : (
                    <span className="p-1.5 text-slate-400" title="Phone not publicly published">
                      <Phone size={16} />
                    </span>
                  )}

                  {profile?.contacts.linkedin_url && (
                    <a
                      href={profile.contacts.linkedin_url}
                      target="_blank"
                      rel="noreferrer"
                      className="p-1.5 rounded-md text-blue-400 hover:text-blue-300 hover:bg-blue-500/10 transition-colors"
                      title="LinkedIn Profile"
                    >
                      <LinkedinIcon size={16} />
                    </a>
                  )}

                  {profile?.contacts.github_url && (
                    <a
                      href={profile.contacts.github_url}
                      target="_blank"
                      rel="noreferrer"
                      className="p-1.5 rounded-md text-slate-300 hover:text-white hover:bg-slate-800 transition-colors"
                      title="GitHub Profile"
                    >
                      <GithubIcon size={16} />
                    </a>
                  )}

                  {profile?.contacts.portfolio_url && (
                    <a
                      href={profile.contacts.portfolio_url}
                      target="_blank"
                      rel="noreferrer"
                      className="p-1.5 rounded-md text-cyan-400 hover:text-cyan-300 hover:bg-cyan-500/10 transition-colors"
                      title="Portfolio / Showcase"
                    >
                      <Globe size={16} />
                    </a>
                  )}
                </div>
              </div>
            </div>

            {/* Right section: Stage Selector Dropdown */}
            <div className="relative shrink-0">
              <button
                type="button"
                onClick={() => setIsStageOpen(!isStageOpen)}
                disabled={updatingStage}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold border ${currentStageMeta.color} hover:opacity-90 transition-colors cursor-pointer`}
              >
                <span className="w-2 h-2 rounded-full bg-blue-400" />
                <span className="text-slate-200">{profile?.stage || 'Sourced'}</span>
                <ChevronDown size={14} className="text-slate-400" />
              </button>

              {isStageOpen && (
                <div className="absolute right-0 mt-2 w-48 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl py-1 z-30">
                  <div className="px-3 py-1.5 text-[11px] font-semibold text-slate-400 uppercase tracking-wider border-b border-slate-800">
                    Change Stage
                  </div>
                  {STAGES.map((s) => (
                    <button
                      key={s.id}
                      onClick={() => handleStageSelect(s.id)}
                      className={`w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-left hover:bg-slate-800 transition-colors ${
                        profile?.stage === s.id ? 'text-indigo-400 bg-slate-800/60' : 'text-slate-300'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-slate-400" />
                        <span>{s.name}</span>
                      </div>
                      {profile?.stage === s.id && <Check size={14} className="text-indigo-400" />}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* 5 Tabs Navigation matching screenshot */}
          <div className="flex items-center gap-1 mt-6 p-1 bg-slate-950/80 rounded-xl border border-slate-800/80 w-fit">
            {[
              { id: 'overview', label: 'Overview' },
              { id: 'analysis', label: 'Analysis' },
              { id: 'resume', label: 'Resume' },
              { id: 'activity', label: 'Activity' },
              { id: 'jobs', label: 'Associated Jobs' },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={`px-4 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  activeTab === tab.id
                    ? 'bg-slate-800 text-white shadow-sm font-semibold'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/60'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* Tab Contents Area */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {error && (
            <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-center gap-2">
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          )}

          {/* TAB 1: OVERVIEW */}
          {activeTab === 'overview' && profile && (
            <div className="space-y-6">
              {/* HIGHLIGHTS SECTION */}
              <div>
                <h3 className="text-xs font-bold text-slate-400 tracking-wider uppercase mb-3 flex items-center gap-2">
                  <Sparkles size={14} className="text-amber-400" />
                  Highlights
                </h3>
                <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80 text-sm">
                  {profile.highlights && profile.highlights.length > 0 ? (
                    <ul className="space-y-2">
                      {profile.highlights.map((h, i) => (
                        <li key={i} className="flex items-start gap-2 text-slate-300">
                          <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 mt-2 shrink-0" />
                          <span>{h}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-slate-400 text-xs">No highlights are available for this candidate.</p>
                  )}
                </div>
              </div>

              {/* WORK EXPERIENCE SECTION */}
              <div>
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-xs font-bold text-slate-400 tracking-wider uppercase flex items-center gap-2">
                    <Briefcase size={14} className="text-indigo-400" />
                    Work Experience ({profile.total_experience_str})
                  </h3>
                </div>

                {profile.work_experiences && profile.work_experiences.length > 0 ? (
                  <div className="space-y-3">
                    {profile.work_experiences.map((exp) => {
                      const isExpanded = expandedExps[exp.id];
                      return (
                        <div
                          key={exp.id}
                          className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80 hover:border-slate-700/80 transition-colors"
                        >
                          <div className="flex items-start gap-3">
                            {/* Briefcase Icon in rounded box */}
                            <div className="w-10 h-10 rounded-xl bg-slate-800 text-blue-400 flex items-center justify-center shrink-0 border border-slate-700/60">
                              <Briefcase size={18} />
                            </div>

                            <div className="flex-1 min-w-0">
                              <div className="flex items-baseline justify-between gap-2">
                                <h4 className="text-sm font-bold text-slate-100 truncate">{exp.company}</h4>
                                {exp.is_current === 1 && (
                                  <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                                    Current
                                  </span>
                                )}
                              </div>

                              <p className="text-xs font-medium text-slate-300 mt-0.5">{exp.title}</p>

                              <p className="text-xs text-slate-400 mt-0.5">
                                {exp.start_date} - {exp.end_date || 'Present'} {exp.duration ? `· ${exp.duration}` : ''}
                              </p>

                              {exp.description && (
                                <div className="mt-2 text-xs text-slate-300 leading-relaxed">
                                  <p className={!isExpanded && exp.description.length > 150 ? 'line-clamp-2' : ''}>
                                    {exp.description}
                                  </p>
                                  {exp.description.length > 150 && (
                                    <button
                                      type="button"
                                      onClick={() => toggleExpandExp(exp.id)}
                                      className="text-indigo-400 hover:text-indigo-300 font-medium text-xs mt-1"
                                    >
                                      {isExpanded ? 'Show less' : 'Show more'}
                                    </button>
                                  )}
                                </div>
                              )}

                              {exp.skills && exp.skills.length > 0 && (
                                <div className="flex flex-wrap gap-1.5 mt-3">
                                  {exp.skills.map((s, idx) => (
                                    <span
                                      key={idx}
                                      className="px-2 py-0.5 rounded text-[11px] font-mono bg-slate-800/80 text-slate-300 border border-slate-700/50"
                                    >
                                      {s}
                                    </span>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 text-xs text-slate-400">
                    No individual experience records parsed yet.
                  </div>
                )}
              </div>

              {/* TECHNICAL SKILLS BADGES */}
              {profile.skills && profile.skills.length > 0 && (
                <div>
                  <h3 className="text-xs font-bold text-slate-400 tracking-wider uppercase mb-3 flex items-center gap-2">
                    <Award size={14} className="text-cyan-400" />
                    Skills & Competencies
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {profile.skills.map((skill, idx) => (
                      <span
                        key={idx}
                        className="px-2.5 py-1 rounded-lg text-xs font-medium bg-slate-800 text-slate-200 border border-slate-700/60"
                      >
                        {skill}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* EVIDENCE TIER & PROVENANCE */}
              <div>
                <h3 className="text-xs font-bold text-slate-400 tracking-wider uppercase mb-3 flex items-center gap-2">
                  <ShieldCheck size={14} className="text-emerald-400" />
                  Verification & Provenance
                </h3>
                <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80 text-xs space-y-2">
                  <div className="flex justify-between items-center py-1 border-b border-slate-800">
                    <span className="text-slate-400">Evidence Ladder Tier:</span>
                    <span className="font-semibold text-emerald-400">{profile.evidence_ladder_tier}</span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-slate-800">
                    <span className="text-slate-400">Source:</span>
                    <span className="text-slate-200">{profile.source}</span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-slate-800">
                    <span className="text-slate-400">Contact Status:</span>
                    <span className="text-slate-200">{profile.contacts.contact_status}</span>
                  </div>
                  {profile.profile_url && (
                    <div className="flex justify-between items-center py-1">
                      <span className="text-slate-400">Profile URL:</span>
                      <a
                        href={profile.profile_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-indigo-400 hover:underline flex items-center gap-1 truncate max-w-xs"
                      >
                        {profile.profile_url}
                        <ExternalLink size={12} />
                      </a>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: ANALYSIS */}
          {activeTab === 'analysis' && profile && (
            <div className="space-y-6">
              {/* Job context & Match Header */}
              <div className="p-4 rounded-xl bg-gradient-to-r from-indigo-950/40 to-slate-900 border border-indigo-900/30 flex items-center justify-between">
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-indigo-400">
                    Evaluated Against Job
                  </div>
                  <div className="text-base font-bold text-slate-100 mt-0.5">
                    {profile.analysis.job_title}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="text-right">
                    <div className="text-2xl font-black text-indigo-400">
                      {profile.analysis.match_score}%
                    </div>
                    <div className="text-[10px] text-slate-400 font-semibold uppercase">Overall Match</div>
                  </div>
                </div>
              </div>

              {/* Matched Required Skills */}
              <div>
                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-2">
                  <Check size={14} className="text-emerald-400" />
                  Matched Required Criteria
                </h4>
                <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80">
                  {profile.analysis.matched_required_skills && profile.analysis.matched_required_skills.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {profile.analysis.matched_required_skills.map((skill, idx) => (
                        <span
                          key={idx}
                          className="px-2.5 py-1 rounded-lg text-xs font-medium bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 flex items-center gap-1.5"
                        >
                          <Check size={12} />
                          {skill}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-400">No direct required skills detected in evidence text.</p>
                  )}
                </div>
              </div>

              {/* Matched Preferred Skills */}
              {profile.analysis.matched_preferred_skills && profile.analysis.matched_preferred_skills.length > 0 && (
                <div>
                  <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-2">
                    <Sparkles size={14} className="text-indigo-400" />
                    Matched Preferred Criteria
                  </h4>
                  <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80">
                    <div className="flex flex-wrap gap-2">
                      {profile.analysis.matched_preferred_skills.map((skill, idx) => (
                        <span
                          key={idx}
                          className="px-2.5 py-1 rounded-lg text-xs font-medium bg-indigo-500/15 text-indigo-300 border border-indigo-500/30 flex items-center gap-1.5"
                        >
                          <Check size={12} />
                          {skill}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* Missing or Unverified Skills */}
              {profile.analysis.missing_skills && profile.analysis.missing_skills.length > 0 && (
                <div>
                  <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-2">
                    <AlertCircle size={14} className="text-amber-400" />
                    Missing or Unverified Criteria
                  </h4>
                  <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80">
                    <div className="flex flex-wrap gap-2">
                      {profile.analysis.missing_skills.map((skill, idx) => (
                        <span
                          key={idx}
                          className="px-2.5 py-1 rounded-lg text-xs font-medium bg-amber-500/10 text-amber-300 border border-amber-500/20"
                        >
                          {skill}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* Evidence Quotes with Source URLs */}
              <div>
                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-2">
                  <FileText size={14} className="text-cyan-400" />
                  Verifiable Evidence Snippets & Sources
                </h4>
                <div className="space-y-2">
                  {profile.analysis.evidence_quotes && profile.analysis.evidence_quotes.length > 0 ? (
                    profile.analysis.evidence_quotes.map((q, idx) => (
                      <div
                        key={idx}
                        className="p-3.5 rounded-xl bg-slate-900/80 border border-slate-800 text-xs space-y-1.5"
                      >
                        <p className="text-slate-300 italic font-sans leading-relaxed">"{q.quote}"</p>
                        <div className="flex items-center justify-between text-[11px] text-slate-400 pt-1 border-t border-slate-800/60">
                          <span className="font-medium text-slate-400">Source: {q.source}</span>
                          {q.url && (
                            <a
                              href={q.url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-indigo-400 hover:underline flex items-center gap-1"
                            >
                              Verify Evidence <ExternalLink size={11} />
                            </a>
                          )}
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 text-xs text-slate-400">
                      No quoted evidence text available.
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* TAB 3: RESUME */}
          {activeTab === 'resume' && profile && (
            <div className="space-y-4">
              {profile.resume.has_resume ? (
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <h4 className="text-sm font-bold text-slate-200">
                        {profile.resume.resume_filename || 'Candidate Resume Text'}
                      </h4>
                      <p className="text-xs text-slate-400">
                        Source: {profile.resume.resume_source} · Uploaded: {profile.resume.resume_uploaded_at || 'Recently'}
                      </p>
                    </div>
                    <button
                      onClick={() => navigator.clipboard.writeText(profile.resume.resume_text)}
                      className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 transition-colors"
                    >
                      Copy Resume Text
                    </button>
                  </div>

                  <div className="p-4 rounded-xl bg-slate-950 font-mono text-xs text-slate-300 leading-relaxed border border-slate-800 overflow-x-auto whitespace-pre-wrap max-h-[500px]">
                    {profile.resume.resume_text}
                  </div>
                </div>
              ) : (
                <div className="p-8 rounded-2xl bg-slate-900/40 border border-slate-800 flex flex-col items-center justify-center text-center space-y-3">
                  <div className="w-12 h-12 rounded-2xl bg-slate-800 text-slate-400 flex items-center justify-center">
                    <FileText size={24} />
                  </div>
                  <div>
                    <h4 className="text-sm font-bold text-slate-200">No Resume Document Uploaded</h4>
                    <p className="text-xs text-slate-400 max-w-sm mt-1 leading-relaxed">
                      This candidate was auto-sourced from verified public engineering platforms (GitHub, LinkedIn X-Ray, Portfolio Showcase). You can upload a CV or document to parse full resume contents.
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* TAB 4: ACTIVITY */}
          {activeTab === 'activity' && profile && (
            <div className="space-y-6">
              {/* Add Note Form */}
              <form onSubmit={handleAddNote} className="p-4 rounded-xl bg-slate-900/70 border border-slate-800 space-y-3">
                <label className="text-xs font-bold text-slate-300 uppercase tracking-wider block">
                  Add Recruiter Note / Activity
                </label>
                <textarea
                  value={newNote}
                  onChange={(e) => setNewNote(e.target.value)}
                  placeholder="Record interview notes, feedback, contact outcome, or recruiter observations..."
                  rows={3}
                  className="w-full text-xs bg-slate-950 border border-slate-800 rounded-lg p-3 text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/40 resize-none"
                />
                <div className="flex justify-end">
                  <button
                    type="submit"
                    disabled={isSubmittingNote || !newNote.trim()}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white transition-colors disabled:opacity-50 cursor-pointer"
                  >
                    <Send size={13} />
                    {isSubmittingNote ? 'Saving...' : 'Add Note'}
                  </button>
                </div>
              </form>

              {/* Chronological Activity Timeline */}
              <div>
                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-4 flex items-center gap-2">
                  <ActivityIcon size={14} className="text-indigo-400" />
                  Audit Trail & Activity Log
                </h4>

                {profile.activities && profile.activities.length > 0 ? (
                  <div className="relative pl-6 space-y-4 border-l border-slate-800">
                    {profile.activities.map((act) => (
                      <div key={act.id} className="relative">
                        {/* Timeline dot */}
                        <div className="absolute -left-[31px] top-1 w-3.5 h-3.5 rounded-full bg-slate-900 border-2 border-indigo-500" />

                        <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800/80 space-y-1">
                          <div className="flex items-center justify-between text-xs">
                            <span className="font-semibold text-slate-200">{act.title}</span>
                            <span className="text-[11px] text-slate-400">
                              {new Date(act.created_at).toLocaleString()}
                            </span>
                          </div>
                          {act.details && (
                            <p className="text-xs text-slate-300 leading-relaxed">{act.details}</p>
                          )}
                          <div className="text-[10px] text-slate-400 font-medium">Actor: {act.actor}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 text-xs text-slate-400">
                    No activity recorded yet for this candidate.
                  </div>
                )}
              </div>
            </div>
          )}

          {/* TAB 5: ASSOCIATED JOBS */}
          {activeTab === 'jobs' && profile && (
            <div className="space-y-4">
              <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-2">
                <Briefcase size={14} className="text-indigo-400" />
                Linked Jobs & Cross-Pipeline Status
              </h4>

              {profile.associated_jobs && profile.associated_jobs.length > 0 ? (
                <div className="space-y-3">
                  {profile.associated_jobs.map((job) => (
                    <div
                      key={job.job_id}
                      className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80 flex items-center justify-between gap-4"
                    >
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-bold text-indigo-400">#{job.job_id}</span>
                          <h5 className="text-sm font-bold text-slate-100">{job.job_title}</h5>
                        </div>
                        {job.job_location && (
                          <p className="text-xs text-slate-400 mt-0.5">{job.job_location}</p>
                        )}
                        <p className="text-[11px] text-slate-400 mt-1">
                          Updated: {job.updated_at ? new Date(job.updated_at).toLocaleDateString() : 'Initial'}
                        </p>
                      </div>

                      <div className="flex items-center gap-3">
                        <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-800 text-slate-300 border border-slate-700">
                          {job.stage}
                        </span>
                        {job.match_score !== undefined && (
                          <span className="text-sm font-bold text-indigo-400">
                            {job.match_score}%
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 text-xs text-slate-400">
                  Candidate is not linked to any jobs yet.
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
