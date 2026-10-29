import React, { useState, useEffect } from 'react';
import {
  Search,
  RefreshCw,
  Building2,
  Mail,
  Phone,
  UserSearch,
  Layers,
} from 'lucide-react';
import { api } from '../api';
import type { Job, PipelineData, PipelineCandidate } from '../types';
import { CandidateDetailDrawer, LinkedinIcon } from '../components/CandidateDetailDrawer';
import { GithubIcon } from '../components/GithubIcon';

interface PipelineViewProps {
  jobs: Job[];
  activeJobId: number | null;
  onSelectJob: (id: number | null) => void;
  onNavigate?: (view: any) => void;
  onCandidateChanged?: () => void;
}

export const PipelineView: React.FC<PipelineViewProps> = ({
  jobs,
  activeJobId,
  onSelectJob,
  onNavigate,
  onCandidateChanged,
}) => {
  const [pipelineData, setPipelineData] = useState<PipelineData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [minScore, setMinScore] = useState<number>(0);
  const [sortBy, setSortBy] = useState<'score' | 'exp' | 'name'>('score');

  // Candidate Drawer state
  const [selectedCandidateId, setSelectedCandidateId] = useState<number | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState<boolean>(false);

  // Selected job
  const currentJob = jobs.find((j) => j.id === activeJobId) || jobs[0];

  const loadPipeline = async () => {
    if (!currentJob) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await api.getJobPipeline(currentJob.id);
      setPipelineData(data);
    } catch (err: any) {
      console.error('Failed to load pipeline:', err);
      setError(err?.message || 'Could not load candidate pipeline.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPipeline();
  }, [activeJobId, jobs]);

  const handleOpenCandidate = (candidateId: number) => {
    setSelectedCandidateId(candidateId);
    setIsDrawerOpen(true);
  };

  const handleStageChange = async (_candidateId?: number, _newStage?: string) => {
    // Reload pipeline after stage change
    await loadPipeline();
    if (onCandidateChanged) onCandidateChanged();
  };

  // Filter and sort candidates within stages
  const getFilteredCandidates = (candidates: PipelineCandidate[]) => {
    return candidates
      .filter((c) => {
        if (minScore > 0 && (c.match_score || 0) < minScore) return false;
        if (!searchTerm.trim()) return true;
        const q = searchTerm.toLowerCase();
        const nameMatch = c.name.toLowerCase().includes(q);
        const headMatch = (c.headline || '').toLowerCase().includes(q);
        const compMatch = (c.company || '').toLowerCase().includes(q);
        const locMatch = (c.location || '').toLowerCase().includes(q);
        return nameMatch || headMatch || compMatch || locMatch;
      })
      .sort((a, b) => {
        if (sortBy === 'score') return (b.match_score || 0) - (a.match_score || 0);
        if (sortBy === 'exp') return (b.years_of_experience || 0) - (a.years_of_experience || 0);
        return a.name.localeCompare(b.name);
      });
  };

  const STAGE_DOT_COLORS: Record<string, string> = {
    Sourced: 'bg-blue-400',
    'Under Review': 'bg-amber-400',
    'My Shortlisted': 'bg-indigo-400',
    Contacted: 'bg-purple-400',
    Replied: 'bg-emerald-400',
    Interview: 'bg-teal-400',
    Rejected: 'bg-rose-400',
    Archived: 'bg-slate-400',
  };

  return (
    <div className="flex flex-col h-full bg-[#0b0f19] text-slate-100 overflow-hidden">
      {/* Top Header Bar matching reference screenshot */}
      <div className="px-6 py-4 border-b border-slate-800/80 bg-slate-950/60 flex flex-wrap items-center justify-between gap-4 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 to-cyan-600 flex items-center justify-center text-white shadow-md shadow-indigo-600/20">
            <Layers size={20} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold text-slate-100 tracking-tight">
                {currentJob ? currentJob.title : 'Select a Job'}
              </h1>
              {currentJob?.location && (
                <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-medium border border-slate-700/60">
                  {currentJob.location}
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Candidate Pipeline · {pipelineData?.total_candidates || 0} Total Discovered Profiles
            </p>
          </div>
        </div>

        {/* Quick Actions & Job Switcher */}
        <div className="flex items-center gap-3">
          {/* Active Job Selector */}
          <div className="relative">
            <select
              value={activeJobId ?? (currentJob?.id || '')}
              onChange={(e) => onSelectJob(Number(e.target.value))}
              className="text-xs font-medium bg-slate-900 border border-slate-700 hover:border-slate-600 text-slate-200 rounded-lg px-3 py-2 pr-8 appearance-none focus:outline-none focus:ring-2 focus:ring-indigo-500/40 cursor-pointer"
            >
              {jobs.map((j) => (
                <option key={j.id} value={j.id}>
                  #{j.id}: {j.title}
                </option>
              ))}
            </select>
          </div>

          <button
            onClick={loadPipeline}
            className="p-2 rounded-lg bg-slate-900 border border-slate-700 text-slate-300 hover:text-white hover:bg-slate-800 transition-colors"
            title="Refresh Pipeline"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>

          {onNavigate && (
            <button
              onClick={() => onNavigate('discovery')}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white transition-all shadow-sm shadow-indigo-600/20 cursor-pointer"
            >
              <UserSearch size={14} />
              Auto-Source More
            </button>
          )}
        </div>
      </div>

      {/* Filter and Control Sub-Bar */}
      <div className="px-6 py-2.5 border-b border-slate-800/60 bg-slate-900/30 flex flex-wrap items-center justify-between gap-3 text-xs shrink-0">
        <div className="flex items-center gap-3 flex-1 max-w-md">
          <div className="relative w-full">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Filter by name, headline, company, or location..."
              className="w-full bg-slate-950/80 border border-slate-800 rounded-lg pl-9 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/40"
            />
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Match Score Filter */}
          <div className="flex items-center gap-1.5 text-slate-400">
            <span>Min Score:</span>
            <select
              value={minScore}
              onChange={(e) => setMinScore(Number(e.target.value))}
              className="bg-slate-950 border border-slate-800 rounded-lg px-2 py-1 text-slate-200 focus:outline-none"
            >
              <option value={0}>All Scores</option>
              <option value={50}>50%+</option>
              <option value={70}>70%+</option>
              <option value={85}>85%+</option>
            </select>
          </div>

          {/* Sort By */}
          <div className="flex items-center gap-1.5 text-slate-400">
            <span>Sort:</span>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as any)}
              className="bg-slate-950 border border-slate-800 rounded-lg px-2 py-1 text-slate-200 focus:outline-none"
            >
              <option value="score">Highest Match</option>
              <option value="exp">Experience</option>
              <option value="name">Name (A-Z)</option>
            </select>
          </div>
        </div>
      </div>

      {/* Kanban Board Multi-Column Grid */}
      <div className="flex-1 overflow-x-auto overflow-y-hidden p-6 bg-slate-950/40">
        {loading && !pipelineData ? (
          <div className="flex items-center justify-center h-full">
            <div className="flex flex-col items-center gap-2">
              <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
              <span className="text-xs text-slate-400">Loading pipeline board...</span>
            </div>
          </div>
        ) : error ? (
          <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs">
            {error}
          </div>
        ) : (
          <div className="flex gap-4 h-full items-start min-w-max pb-4">
            {pipelineData?.stages.map((stage) => {
              const filtered = getFilteredCandidates(stage.candidates);
              const dotClass = STAGE_DOT_COLORS[stage.name] || 'bg-slate-400';

              return (
                <div
                  key={stage.id}
                  className="w-72 bg-slate-900/40 rounded-2xl border border-slate-800/80 flex flex-col max-h-full shrink-0 shadow-lg"
                >
                  {/* Column Header matching screenshot */}
                  <div className="p-3.5 border-b border-slate-800/80 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full ${dotClass}`} />
                      <h3 className="text-xs font-bold text-slate-200 tracking-wide uppercase">
                        {stage.name}
                      </h3>
                      <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700/60">
                        {stage.count}
                      </span>
                    </div>
                  </div>

                  {/* Candidates List inside Column */}
                  <div className="flex-1 overflow-y-auto p-2.5 space-y-2.5">
                    {filtered.length === 0 ? (
                      <div className="py-8 text-center text-slate-500 text-xs font-medium">
                        No candidates
                      </div>
                    ) : (
                      filtered.map((candidate) => {
                        const initLetter = candidate.name.trim().charAt(0).toUpperCase();

                        return (
                          <div
                            key={candidate.id}
                            onClick={() => handleOpenCandidate(candidate.id)}
                            className="p-3.5 rounded-xl bg-slate-900/90 border border-slate-800/90 hover:border-indigo-500/50 hover:bg-slate-850 hover:shadow-md hover:shadow-indigo-500/5 transition-all cursor-pointer group"
                          >
                            <div className="flex items-start gap-3">
                              {/* Avatar circle matching screenshot */}
                              <div className="w-8 h-8 rounded-full bg-blue-100 text-blue-700 font-bold flex items-center justify-center text-xs shrink-0 shadow-xs">
                                {initLetter}
                              </div>

                              <div className="flex-1 min-w-0">
                                <div className="flex items-center justify-between gap-1">
                                  <h4 className="text-xs font-bold text-slate-100 truncate group-hover:text-indigo-300 transition-colors">
                                    {candidate.name}
                                  </h4>
                                  {candidate.match_score !== undefined && candidate.match_score > 0 && (
                                    <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 shrink-0">
                                      {candidate.match_score}%
                                    </span>
                                  )}
                                </div>

                                <p className="text-[11px] font-medium text-slate-400 truncate mt-0.5">
                                  {candidate.headline || 'Software Specialist'}
                                </p>

                                {candidate.company && (
                                  <div className="flex items-center gap-1 text-[11px] text-slate-400 mt-1 truncate">
                                    <Building2 size={11} className="text-blue-400 shrink-0" />
                                    <span className="truncate">{candidate.company}</span>
                                  </div>
                                )}

                                {/* Bottom Metadata row: Exp · Location */}
                                <div className="flex items-center gap-1.5 text-[10px] text-slate-400 mt-2">
                                  <span className="font-semibold text-slate-300">
                                    {candidate.experience_badge}
                                  </span>
                                  {candidate.location && (
                                    <>
                                      <span>·</span>
                                      <span className="truncate">{candidate.location}</span>
                                    </>
                                  )}
                                </div>

                                {/* Quick Contact icons */}
                                <div className="flex items-center gap-2 mt-2.5 pt-2 border-t border-slate-800/60 text-slate-400">
                                  {candidate.email && (
                                    <Mail size={12} className="text-slate-400 hover:text-white" />
                                  )}
                                  {candidate.phone && (
                                    <Phone size={12} className="text-slate-400 hover:text-white" />
                                  )}
                                  {candidate.linkedin_url && (
                                    <LinkedinIcon size={12} className="text-blue-400" />
                                  )}
                                  {candidate.github_url && (
                                    <GithubIcon size={12} className="text-slate-300" />
                                  )}
                                </div>
                              </div>
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Slide-over Profile Detail Drawer */}
      <CandidateDetailDrawer
        candidateId={selectedCandidateId}
        activeJobId={currentJob ? currentJob.id : null}
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        onStageChange={handleStageChange}
        onCandidateUpdated={loadPipeline}
      />
    </div>
  );
};
