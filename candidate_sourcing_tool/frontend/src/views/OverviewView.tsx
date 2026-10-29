import React, { useEffect, useState } from 'react';
import {
  Briefcase,
  Users,
  AlertCircle,
  CheckCircle2,
  PlusCircle,
  ShieldCheck,
  ArrowRight,
  RefreshCw,
  Sparkles,
  Layers,
} from 'lucide-react';
import { api } from '../api';
import type { OverviewStats } from '../types';
import { Badge } from '../components/Badge';
import type { ViewType } from '../components/Sidebar';

interface OverviewViewProps {
  onNavigate: (view: ViewType) => void;
  onSelectJob: (id: number) => void;
  activeJobId: number | null;
}

export const OverviewView: React.FC<OverviewViewProps> = ({
  onNavigate,
  onSelectJob,
  activeJobId,
}) => {
  const [stats, setStats] = useState<OverviewStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getOverviewStats();
      setStats(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load dashboard metrics.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  return (
    <div className="p-8 space-y-8 max-w-7xl mx-auto">
      {/* Top Banner / Welcome */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-slate-100 tracking-tight">Recruiter Command Center</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
              Zero-Budget Verified (₹0.00)
            </span>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            End-to-end automated talent discovery across GitHub, GitLab, Stack Overflow, Hugging Face, and Local Talent.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={loadData}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium rounded-lg transition-colors border border-slate-700 cursor-pointer"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
          <button
            onClick={() => onNavigate('analyzer')}
            className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold rounded-lg shadow-sm shadow-blue-600/30 transition-all cursor-pointer"
          >
            <PlusCircle size={15} />
            Analyze New JD
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={loadData} className="underline text-xs hover:text-rose-300">
            Retry
          </button>
        </div>
      )}

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total Jobs */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 hover:border-slate-700 transition-colors">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider">Active Jobs</span>
            <div className="p-2 rounded-lg bg-indigo-500/10 text-indigo-400">
              <Briefcase size={18} />
            </div>
          </div>
          <div className="text-3xl font-bold text-slate-100">{stats?.total_jobs ?? 0}</div>
          <div className="text-xs text-slate-500 mt-1">Saved in local SQLite</div>
        </div>

        {/* Total Candidates */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 hover:border-slate-700 transition-colors">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider">Total Candidates</span>
            <div className="p-2 rounded-lg bg-cyan-500/10 text-cyan-400">
              <Users size={18} />
            </div>
          </div>
          <div className="text-3xl font-bold text-slate-100">{stats?.total_candidates ?? 0}</div>
          <div className="text-xs text-slate-500 mt-1">Deduplicated across sources</div>
        </div>

        {/* Needing Review */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 hover:border-slate-700 transition-colors">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider">Under Review</span>
            <div className="p-2 rounded-lg bg-amber-500/10 text-amber-400">
              <AlertCircle size={18} />
            </div>
          </div>
          <div className="text-3xl font-bold text-amber-400">{stats?.needing_review ?? 0}</div>
          <div className="text-xs text-slate-500 mt-1">New or awaiting evaluation</div>
        </div>

        {/* Shortlisted */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 hover:border-slate-700 transition-colors">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider">Shortlisted</span>
            <div className="p-2 rounded-lg bg-emerald-500/10 text-emerald-400">
              <CheckCircle2 size={18} />
            </div>
          </div>
          <div className="text-3xl font-bold text-emerald-400">{stats?.shortlisted ?? 0}</div>
          <div className="text-xs text-slate-500 mt-1">Export-ready talent</div>
        </div>
      </div>

      {/* Zero Budget & Privacy Highlight Card */}
      <div className="p-5 rounded-2xl bg-gradient-to-r from-slate-900/80 via-slate-900 to-indigo-950/40 border border-indigo-500/20 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-start gap-3.5">
          <div className="p-2.5 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 shrink-0">
            <ShieldCheck size={24} />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-200">Strict ₹0.00 Financial Spend Enforced</h3>
            <p className="text-xs text-slate-400 mt-1 max-w-2xl leading-relaxed">
              No paid search APIs, no commercial scrapers, no subscriptions. Sourcing utilizes official free public endpoints (GitHub, GitLab, Stack Overflow, Hugging Face) and local talent rediscovery. Candidate records and recruiter notes remain 100% on your local machine.
            </p>
          </div>
        </div>
        <button
          onClick={() => onNavigate('settings')}
          className="text-xs font-semibold text-indigo-400 hover:text-indigo-300 flex items-center gap-1 shrink-0 self-start md:self-center cursor-pointer"
        >
          Check Connector Status <ArrowRight size={14} />
        </button>
      </div>

      {/* Sourcing Channel Breakdown */}
      {stats?.source_breakdown && Object.keys(stats.source_breakdown).length > 0 && (
        <div className="bg-slate-950 border border-slate-800 rounded-2xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-slate-200 flex items-center gap-2">
              <Layers size={18} className="text-blue-400" />
              Candidate Source Yield Breakdown
            </h2>
            <span className="text-xs text-slate-400">Live SQLite Provenance</span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
            {Object.entries(stats.source_breakdown).map(([sourceName, count]) => (
              <div key={sourceName} className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800">
                <span className="text-xs font-medium text-slate-400 block truncate" title={sourceName}>
                  {sourceName}
                </span>
                <span className="text-2xl font-bold text-slate-100 mt-1 block">{count}</span>
                <span className="text-[10px] text-slate-500">candidates</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Two Column Layout: Recent Jobs & Recent Sourcing Runs */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Saved Jobs */}
        <div className="bg-slate-950 border border-slate-800 rounded-2xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-slate-200 flex items-center gap-2">
              <Briefcase size={18} className="text-indigo-400" />
              Saved Job Descriptions
            </h2>
            <button
              onClick={() => onNavigate('data')}
              className="text-xs text-slate-400 hover:text-indigo-400 transition-colors cursor-pointer"
            >
              Manage all →
            </button>
          </div>

          {stats?.recent_jobs && stats.recent_jobs.length > 0 ? (
            <div className="divide-y divide-slate-800/80">
              {stats.recent_jobs.map((job) => {
                const isActive = activeJobId === job.id;
                return (
                  <div
                    key={job.id}
                    className={`py-3.5 flex items-center justify-between gap-3 group transition-colors rounded-lg px-2 -mx-2 ${
                      isActive ? 'bg-indigo-950/30 border border-indigo-500/30' : 'hover:bg-slate-900/60'
                    }`}
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-slate-200 truncate group-hover:text-indigo-300">
                          {job.title}
                        </span>
                        {isActive && <Badge variant="indigo">Active Context</Badge>}
                      </div>
                      <div className="text-xs text-slate-400 mt-0.5 flex items-center gap-2">
                        <span>{job.location || 'Remote'}</span>
                        <span>•</span>
                        <span>Saved {job.created_at ? new Date(job.created_at).toLocaleDateString() : ''}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        onClick={() => {
                          onSelectJob(job.id);
                          onNavigate('discovery');
                        }}
                        className="px-2.5 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold rounded-lg transition-colors cursor-pointer"
                      >
                        Find Candidates
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="text-center py-10 text-slate-500 text-sm">
              No jobs saved yet.{' '}
              <button
                onClick={() => onNavigate('analyzer')}
                className="text-indigo-400 underline hover:text-indigo-300"
              >
                Analyze your first JD
              </button>
            </div>
          )}
        </div>

        {/* Recent Automated Runs */}
        <div className="bg-slate-950 border border-slate-800 rounded-2xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-slate-200 flex items-center gap-2">
              <Sparkles size={18} className="text-amber-400" />
              Recent Sourcing Runs
            </h2>
            <button
              onClick={() => onNavigate('discovery')}
              className="text-xs text-slate-400 hover:text-amber-400 transition-colors cursor-pointer"
            >
              New Discovery Run →
            </button>
          </div>

          {stats?.recent_runs && stats.recent_runs.length > 0 ? (
            <div className="divide-y divide-slate-800/80">
              {stats.recent_runs.map((run) => (
                <div
                  key={run.run_id}
                  className="py-3 flex items-center justify-between gap-3 hover:bg-slate-900/60 px-2 -mx-2 rounded-lg transition-colors"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono text-slate-300 font-semibold">{run.run_id}</span>
                      <span
                        className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                          run.status === 'COMPLETED'
                            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                            : run.status === 'CANCELLED'
                            ? 'bg-slate-800 text-slate-400'
                            : 'bg-blue-500/10 text-blue-400 animate-pulse'
                        }`}
                      >
                        {run.status}
                      </span>
                    </div>
                    <div className="text-xs text-slate-400 mt-1 flex items-center gap-3">
                      <span>Unique: <strong className="text-slate-200">{run.total_unique_found}</strong></span>
                      <span>Duplicates: <strong className="text-slate-200">{run.total_duplicates}</strong></span>
                      {run.duration_seconds ? <span>Duration: {run.duration_seconds}s</span> : null}
                    </div>
                  </div>
                  <button
                    onClick={() => {
                      onSelectJob(run.job_id);
                      onNavigate('discovery');
                    }}
                    className="text-xs text-indigo-400 hover:text-indigo-300 font-medium px-2 py-1 rounded bg-slate-900 border border-slate-800 cursor-pointer"
                  >
                    View →
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-10 text-slate-500 text-sm">
              No discovery runs executed yet.{' '}
              <button
                onClick={() => onNavigate('discovery')}
                className="text-indigo-400 underline hover:text-indigo-300 cursor-pointer"
              >
                Start automated sourcing
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
