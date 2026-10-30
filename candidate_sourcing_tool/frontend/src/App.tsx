import React, { useEffect, useState } from 'react';
import { Sidebar } from './components/Sidebar';
import type { ViewType } from './components/Sidebar';
import { OverviewView } from './views/OverviewView';
import { JdAnalyzerView } from './views/JdAnalyzerView';
import { FindCandidatesView } from './views/FindCandidatesView';
import { CandidatesView } from './views/CandidatesView';
import { ShortlistView } from './views/ShortlistView';
import { SavedJobsDataView } from './views/SavedJobsDataView';
import { SettingsView } from './views/SettingsView';
import { PipelineView } from './views/PipelineView';
import { CvOutreachView } from './views/CvOutreachView';
import { api } from './api';
import type { DashboardMetrics, Job } from './types';

export const App: React.FC = () => {
  const [currentView, setCurrentView] = useState<ViewType>('overview');
  const [jobs, setJobs] = useState<Job[]>([]);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);

  // Load initial global data
  const loadGlobalData = async () => {
    try {
      const [jobsData, overviewData] = await Promise.all([
        api.getJobs(),
        api.getOverview(),
      ]);
      setJobs(jobsData);
      setMetrics(overviewData);

      // Default active job to first job if not set
      if (activeJobId === null && jobsData.length > 0) {
        setActiveJobId(jobsData[0].id);
      }
    } catch (err) {
      console.error('Failed to load global application data:', err);
    }
  };

  useEffect(() => {
    loadGlobalData();
  }, []);

  const handleJobSaved = async (newJobId: number) => {
    await loadGlobalData();
    setActiveJobId(newJobId);
  };

  const handleCandidateChanged = async () => {
    try {
      const overview = await api.getOverview();
      setMetrics(overview);
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="flex h-screen w-full bg-[#0b0f19] text-slate-100 overflow-hidden font-sans">
      {/* Navigation Sidebar */}
      <Sidebar
        currentView={currentView}
        onNavigate={(v) => setCurrentView(v)}
        jobs={jobs}
        activeJobId={activeJobId}
        onSelectJob={(id) => setActiveJobId(id)}
        metrics={
          metrics
            ? {
                shortlisted: metrics.shortlisted,
                needing_review: metrics.needing_review,
                total_candidates: metrics.total_candidates,
              }
            : undefined
        }
      />

      {/* Main View Area */}
      <main className="flex-1 overflow-y-auto bg-slate-900/30">
        {currentView === 'overview' && (
          <OverviewView
            onNavigate={(v) => setCurrentView(v)}
            onSelectJob={(id) => setActiveJobId(id)}
            activeJobId={activeJobId}
          />
        )}

        {currentView === 'analyzer' && (
          <JdAnalyzerView
            onJobSaved={handleJobSaved}
            onNavigate={(v) => setCurrentView(v)}
          />
        )}

        {currentView === 'discovery' && (
          <FindCandidatesView
            jobs={jobs}
            activeJobId={activeJobId}
            onSelectJob={(id) => setActiveJobId(id)}
            onCandidateAdded={handleCandidateChanged}
            onNavigate={(v) => setCurrentView(v as ViewType)}
          />
        )}

        {currentView === 'pipeline' && (
          <PipelineView
            jobs={jobs}
            activeJobId={activeJobId}
            onSelectJob={(id) => setActiveJobId(id)}
            onNavigate={(v) => setCurrentView(v)}
            onCandidateChanged={handleCandidateChanged}
          />
        )}

        {currentView === 'candidates' && (
          <CandidatesView
            jobs={jobs}
            activeJobId={activeJobId}
            onSelectJob={(id) => setActiveJobId(id)}
          />
        )}

        {currentView === 'shortlist' && (
          <ShortlistView
            jobs={jobs}
            activeJobId={activeJobId}
            onSelectJob={(id) => setActiveJobId(id)}
            onShortlistChanged={handleCandidateChanged}
          />
        )}

        {currentView === 'data' && (
          <SavedJobsDataView
            jobs={jobs}
            onRefreshJobs={loadGlobalData}
            onSelectJob={(id) => setActiveJobId(id)}
          />
        )}

        {currentView === 'referrals' && <CvOutreachView />}

        {currentView === 'settings' && <SettingsView />}
      </main>
    </div>
  );
};

export default App;
