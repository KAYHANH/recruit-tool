import React from 'react';
import {
  LayoutDashboard,
  FileSearch,
  UserSearch,
  Users,
  CheckCircle2,
  Database,
  Settings,
  ShieldCheck,
  Briefcase,
  ChevronDown,
  Layers,
} from 'lucide-react';
import type { Job } from '../types';

export type ViewType =
  | 'overview'
  | 'analyzer'
  | 'discovery'
  | 'pipeline'
  | 'candidates'
  | 'shortlist'
  | 'data'
  | 'settings';

interface SidebarProps {
  currentView: ViewType;
  onNavigate: (view: ViewType) => void;
  jobs: Job[];
  activeJobId: number | null;
  onSelectJob: (id: number | null) => void;
  metrics?: {
    shortlisted: number;
    needing_review: number;
    total_candidates: number;
  };
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentView,
  onNavigate,
  jobs,
  activeJobId,
  onSelectJob,
  metrics,
}) => {
  const navItems: { id: ViewType; label: string; icon: React.ReactNode; badge?: number }[] = [
    { id: 'overview', label: 'Overview', icon: <LayoutDashboard size={18} /> },
    { id: 'analyzer', label: 'JD Analyzer', icon: <FileSearch size={18} /> },
    { id: 'discovery', label: 'Find Candidates', icon: <UserSearch size={18} /> },
    { id: 'pipeline', label: 'Pipeline', icon: <Layers size={18} />, badge: metrics?.total_candidates },
    {
      id: 'candidates',
      label: 'Candidates',
      icon: <Users size={18} />,
    },
    {
      id: 'shortlist',
      label: 'Shortlist',
      icon: <CheckCircle2 size={18} />,
      badge: metrics?.shortlisted,
    },
    { id: 'data', label: 'Data & Backups', icon: <Database size={18} /> },
    { id: 'settings', label: 'Settings', icon: <Settings size={18} /> },
  ];

  return (
    <aside className="w-64 bg-slate-950 border-r border-slate-800 flex flex-col h-screen select-none">
      {/* Brand Header */}
      <div className="p-4 border-b border-slate-800/80">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-cyan-500 to-indigo-600 flex items-center justify-center text-white shadow-md shadow-indigo-500/20 font-bold">
            CF
          </div>
          <div>
            <h1 className="text-base font-semibold text-slate-100 leading-tight">Candidate Finder</h1>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
              <span className="text-xs font-medium text-emerald-400">Strict ₹0 Spend</span>
            </div>
          </div>
        </div>
      </div>

      {/* Active Job Selector */}
      <div className="p-3 border-b border-slate-800/60 bg-slate-900/40">
        <label className="text-[11px] font-semibold tracking-wider uppercase text-slate-400 mb-1.5 flex items-center gap-1">
          <Briefcase size={12} className="text-indigo-400" />
          Active Job Context
        </label>
        <div className="relative">
          <select
            value={activeJobId ?? ''}
            onChange={(e) => onSelectJob(e.target.value ? Number(e.target.value) : null)}
            className="w-full text-xs font-medium bg-slate-900 border border-slate-700 hover:border-slate-600 text-slate-200 rounded-lg px-2.5 py-2 pr-7 appearance-none focus:outline-none focus:ring-2 focus:ring-indigo-500/40 cursor-pointer transition-colors truncate"
          >
            <option value="">All Jobs (Global Context)</option>
            {jobs.map((j) => (
              <option key={j.id} value={j.id}>
                #{j.id}: {j.title} {j.location ? `(${j.location})` : ''}
              </option>
            ))}
          </select>
          <ChevronDown
            size={14}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none"
          />
        </div>
      </div>

      {/* Navigation List */}
      <nav className="flex-1 px-2.5 py-4 space-y-1 overflow-y-auto">
        {navItems.map((item) => {
          const isActive = currentView === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
                isActive
                  ? 'bg-indigo-600 text-white shadow-sm shadow-indigo-600/30'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/80'
              }`}
            >
              <div className="flex items-center gap-3">
                <span className={isActive ? 'text-white' : 'text-slate-400'}>{item.icon}</span>
                <span>{item.label}</span>
              </div>
              {item.badge !== undefined && item.badge > 0 && (
                <span
                  className={`text-xs px-2 py-0.5 rounded-full font-semibold ${
                    isActive ? 'bg-indigo-700/80 text-white' : 'bg-slate-800 text-slate-300'
                  }`}
                >
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* System Status Footer */}
      <div className="p-3 m-2.5 rounded-xl bg-slate-900/70 border border-slate-800 text-xs">
        <div className="flex items-center justify-between text-slate-400 mb-1">
          <span className="flex items-center gap-1.5 font-medium text-slate-300">
            <ShieldCheck size={14} className="text-emerald-400" /> Local SQLite
          </span>
          <span className="text-emerald-400 font-semibold">Online</span>
        </div>
        <div className="text-[11px] text-slate-400">
          Total Spent: <strong className="text-slate-200">₹0.00</strong>
        </div>
        <div className="text-[11px] text-slate-400 mt-0.5">
          Privacy: <span className="text-slate-300">100% Local Storage</span>
        </div>
      </div>
    </aside>
  );
};
