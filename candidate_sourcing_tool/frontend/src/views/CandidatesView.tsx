import React, { useEffect, useState } from 'react';
import {
  Users,
  Search,
  Filter,
  Sparkles,
  Mail,
  MapPin,
  Loader2,
  AlertCircle,
} from 'lucide-react';
import { api } from '../api';
import type { Candidate, CandidateEvaluation, Job } from '../types';
import { ScoreBadge } from '../components/Badge';
import { CandidateDetailDrawer } from '../components/CandidateDetailDrawer';

interface CandidatesViewProps {
  jobs: Job[];
  activeJobId: number | null;
  onSelectJob: (id: number) => void;
}

export const CandidatesView: React.FC<CandidatesViewProps> = ({
  jobs,
  activeJobId,
  onSelectJob: _onSelectJob,
}) => {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [ranking, setRanking] = useState(false);
  const [rankedResults, setRankedResults] = useState<Record<number, CandidateEvaluation>>({});
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Selected candidate for drawer
  const [selectedCandidateId, setSelectedCandidateId] = useState<number | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  const activeJob = jobs.find((j) => j.id === activeJobId) || jobs[0];

  const loadCandidates = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getCandidates({
        job_id: activeJobId ?? undefined,
        status: statusFilter || undefined,
        search: searchQuery || undefined,
      });
      setCandidates(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load candidates.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCandidates();
  }, [activeJobId, statusFilter]);

  // Handle Search Input Debounce / Submit
  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loadCandidates();
  };

  // Perform deterministic heuristic ranking for active job
  const handleRankCandidates = async () => {
    if (!activeJob) {
      alert('Please select an active job to evaluate candidates against.');
      return;
    }

    try {
      setRanking(true);
      const res = await api.rankCandidates(activeJob.id, {
        include_all_candidates: activeJobId === null,
        status_filter: statusFilter || undefined,
      });

      const map: Record<number, CandidateEvaluation> = {};
      res.results.forEach((r) => {
        map[r.candidate.id] = r.evaluation;
      });
      setRankedResults(map);
    } catch (err: any) {
      alert(`Ranking failed: ${err.message}`);
    } finally {
      setRanking(false);
    }
  };

  // Quick Status change from table
  const handleQuickStatusChange = async (candidateId: number, newStatus: string) => {
    try {
      await api.updateCandidate(candidateId, { status: newStatus });
      setCandidates((prev) =>
        prev.map((c) => (c.id === candidateId ? { ...c, status: newStatus } : c))
      );
    } catch (err: any) {
      alert(`Status update failed: ${err.message}`);
    }
  };

  // Open drawer
  const handleOpenDrawer = (candidate: Candidate) => {
    setSelectedCandidateId(candidate.id);
    setIsDrawerOpen(true);
  };

  return (
    <div className="p-8 space-y-6 max-w-7xl mx-auto relative">
      {/* View Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight flex items-center gap-2.5">
            <Users className="text-indigo-400" size={26} />
            Candidate Directory & Matcher
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Deterministic, evidence-based candidate scoring. Evaluated locally on your machine with 0 external API calls.
          </p>
        </div>

        {activeJob && (
          <button
            onClick={handleRankCandidates}
            disabled={ranking || candidates.length === 0}
            className="px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-xl text-xs font-semibold flex items-center gap-2 shadow-lg shadow-indigo-600/30 transition-all cursor-pointer self-start md:self-center"
          >
            {ranking ? (
              <>
                <Loader2 size={15} className="animate-spin" /> Evaluating Evidence...
              </>
            ) : (
              <>
                <Sparkles size={15} /> Evaluate & Rank Candidates
              </>
            )}
          </button>
        )}
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs flex items-center gap-2">
          <AlertCircle size={15} />
          <span>{error}</span>
        </div>
      )}

      {/* Filter Toolbar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4 bg-slate-950 border border-slate-800 p-4 rounded-xl">
        <form onSubmit={handleSearchSubmit} className="relative flex-1 w-full sm:max-w-md">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            placeholder="Search candidates by name, company, or headline..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </form>

        <div className="flex items-center gap-3 w-full sm:w-auto">
          {/* Status Filter */}
          <div className="flex items-center gap-2">
            <Filter size={14} className="text-slate-400" />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            >
              <option value="">All Statuses</option>
              <option value="New">New</option>
              <option value="Under Review">Under Review</option>
              <option value="Shortlisted">Shortlisted</option>
              <option value="Contacted">Contacted</option>
              <option value="Rejected">Rejected</option>
            </select>
          </div>
        </div>
      </div>

      {/* Candidate Table */}
      <div className="bg-slate-950 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
        {loading ? (
          <div className="py-20 text-center text-slate-400 text-xs flex items-center justify-center gap-2">
            <Loader2 size={16} className="animate-spin" /> Loading candidates...
          </div>
        ) : candidates.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-slate-800 bg-slate-900/40 text-slate-400 uppercase tracking-wider text-[11px]">
                  <th className="py-3 px-4 font-semibold">Candidate</th>
                  <th className="py-3 px-4 font-semibold">Match Score</th>
                  <th className="py-3 px-4 font-semibold">Status</th>
                  <th className="py-3 px-4 font-semibold">Public Contact</th>
                  <th className="py-3 px-4 font-semibold">Source</th>
                  <th className="py-3 px-4 text-right font-semibold">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {candidates.map((cand) => {
                  const ev = rankedResults[cand.id];
                  return (
                    <tr
                      key={cand.id}
                      className="hover:bg-slate-900/60 transition-colors group cursor-pointer"
                      onClick={() => handleOpenDrawer(cand)}
                    >
                      {/* Name & Headline */}
                      <td className="py-3.5 px-4">
                        <div className="font-semibold text-slate-200 group-hover:text-indigo-400 transition-colors">
                          {cand.name}
                        </div>
                        <div className="text-[11px] text-slate-400 truncate max-w-xs mt-0.5">
                          {cand.headline || cand.company || 'No headline specified'}
                        </div>
                        {cand.location && (
                          <div className="text-[10px] text-slate-500 flex items-center gap-1 mt-0.5">
                            <MapPin size={10} /> {cand.location}
                          </div>
                        )}
                      </td>

                      {/* Score */}
                      <td className="py-3.5 px-4" onClick={(e) => e.stopPropagation()}>
                        {ev ? (
                          <ScoreBadge score={ev.total_score} percentage={ev.percentage} />
                        ) : (
                          <span className="text-slate-500 italic">Not evaluated</span>
                        )}
                      </td>

                      {/* Status Dropdown */}
                      <td className="py-3.5 px-4" onClick={(e) => e.stopPropagation()}>
                        <select
                          value={cand.status}
                          onChange={(e) => handleQuickStatusChange(cand.id, e.target.value)}
                          className={`text-xs font-medium rounded-lg px-2.5 py-1 border transition-colors cursor-pointer ${
                            cand.status === 'Shortlisted'
                              ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                              : cand.status === 'Rejected'
                              ? 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                              : cand.status === 'Under Review'
                              ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                              : 'bg-slate-800 text-slate-300 border-slate-700'
                          }`}
                        >
                          <option value="New" className="bg-slate-900 text-slate-200">New</option>
                          <option value="Under Review" className="bg-slate-900 text-slate-200">Under Review</option>
                          <option value="Shortlisted" className="bg-slate-900 text-slate-200">Shortlisted</option>
                          <option value="Contacted" className="bg-slate-900 text-slate-200">Contacted</option>
                          <option value="Rejected" className="bg-slate-900 text-slate-200">Rejected</option>
                        </select>
                      </td>

                      {/* Contact */}
                      <td className="py-3.5 px-4">
                        {cand.email ? (
                          <span className="text-emerald-400 font-mono flex items-center gap-1">
                            <Mail size={11} /> {cand.email}
                          </span>
                        ) : (
                          <span className="text-slate-500">Not found</span>
                        )}
                      </td>

                      {/* Source */}
                      <td className="py-3.5 px-4 text-slate-400">
                        <div>{cand.source || 'Manual'}</div>
                        {cand.evidence_ladder_tier && (
                          <div className="text-[10px] text-indigo-400 font-semibold mt-0.5">
                            {cand.evidence_ladder_tier}
                          </div>
                        )}
                      </td>

                      {/* Actions */}
                      <td className="py-3.5 px-4 text-right" onClick={(e) => e.stopPropagation()}>
                        <button
                          onClick={() => handleOpenDrawer(cand)}
                          className="px-2.5 py-1 bg-slate-800 hover:bg-indigo-600 text-slate-300 hover:text-white rounded text-xs transition-colors"
                        >
                          Details →
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-16 text-center text-slate-500 text-sm">
            No candidates found matching the current criteria.
          </div>
        )}
      </div>

      {/* Slide-over Full Candidate Profile Drawer */}
      <CandidateDetailDrawer
        candidateId={selectedCandidateId}
        activeJobId={activeJobId}
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        onCandidateUpdated={loadCandidates}
      />
    </div>
  );
};
