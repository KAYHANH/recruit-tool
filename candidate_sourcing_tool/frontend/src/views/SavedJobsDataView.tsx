import React, { useEffect, useState } from 'react';
import {
  Database,
  Briefcase,
  Trash2,
  Edit2,
  Save,
  X,
  Upload,
  Loader2,
  AlertTriangle,
  CheckCircle2,
} from 'lucide-react';
import { api } from '../api';
import type { BackupItem, Job } from '../types';
import { Badge } from '../components/Badge';

interface SavedJobsDataViewProps {
  jobs: Job[];
  onRefreshJobs: () => void;
  onSelectJob: (id: number) => void;
}

export const SavedJobsDataView: React.FC<SavedJobsDataViewProps> = ({
  jobs,
  onRefreshJobs,
  onSelectJob: _onSelectJob,
}) => {
  const [activeTab, setActiveTab] = useState<'jobs' | 'backups'>('jobs');

  // Job Editing State
  const [editingJobId, setEditingJobId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editLocation, setEditLocation] = useState('');
  const [savingJob, setSavingJob] = useState(false);

  // Backup State
  const [backups, setBackups] = useState<BackupItem[]>([]);
  const [loadingBackups, setLoadingBackups] = useState(false);
  const [creatingBackup, setCreatingBackup] = useState(false);
  const [restoringBackup, setRestoringBackup] = useState(false);

  // Messages
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; msg: string } | null>(null);

  const loadBackups = async () => {
    try {
      setLoadingBackups(true);
      const data = await api.getBackups();
      setBackups(data);
    } catch (err: any) {
      console.error('Failed to load backups:', err);
    } finally {
      setLoadingBackups(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'backups') {
      loadBackups();
    }
  }, [activeTab]);

  // Edit job
  const handleStartEdit = (job: Job) => {
    setEditingJobId(job.id);
    setEditTitle(job.title);
    setEditLocation(job.location || '');
  };

  const handleSaveJob = async (jobId: number) => {
    try {
      setSavingJob(true);
      await api.updateJob(jobId, {
        title: editTitle,
        location: editLocation,
      });
      setFeedback({ type: 'success', msg: `Job #${jobId} updated successfully.` });
      setEditingJobId(null);
      onRefreshJobs();
    } catch (err: any) {
      setFeedback({ type: 'error', msg: err.message || 'Failed to update job.' });
    } finally {
      setSavingJob(false);
    }
  };

  // Delete job
  const handleDeleteJob = async (jobId: number, title: string) => {
    if (!window.confirm(`Are you sure you want to delete Job #${jobId} ("${title}")? This action cannot be undone.`)) {
      return;
    }
    try {
      await api.deleteJob(jobId);
      setFeedback({ type: 'success', msg: `Job #${jobId} deleted.` });
      onRefreshJobs();
    } catch (err: any) {
      setFeedback({ type: 'error', msg: err.message || 'Failed to delete job.' });
    }
  };

  // Create timestamped backup
  const handleCreateBackup = async () => {
    try {
      setCreatingBackup(true);
      const res = await api.createBackup();
      setFeedback({ type: 'success', msg: res.message });
      loadBackups();
    } catch (err: any) {
      setFeedback({ type: 'error', msg: err.message || 'Backup failed.' });
    } finally {
      setCreatingBackup(false);
    }
  };

  // Restore backup
  const handleRestoreBackup = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!window.confirm(`Restore database from "${file.name}"? A safety snapshot will be created before restoring.`)) {
      return;
    }

    try {
      setRestoringBackup(true);
      const res = await api.restoreBackup(file);
      setFeedback({
        type: 'success',
        msg: `${res.message} (Safety snapshot: ${res.safety_snapshot || 'Created'})`,
      });
      onRefreshJobs();
      loadBackups();
    } catch (err: any) {
      setFeedback({ type: 'error', msg: err.message || 'Restore failed.' });
    } finally {
      setRestoringBackup(false);
    }
  };

  return (
    <div className="p-8 space-y-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight flex items-center gap-2.5">
            <Database className="text-indigo-400" size={26} />
            Data Management & Backups
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Manage your SQLite database records, create transactional snapshots, and restore historical backups.
          </p>
        </div>
      </div>

      {feedback && (
        <div
          className={`p-4 rounded-xl border text-xs flex items-center justify-between ${
            feedback.type === 'success'
              ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
              : 'bg-rose-500/10 border-rose-500/20 text-rose-400'
          }`}
        >
          <div className="flex items-center gap-2">
            {feedback.type === 'success' ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
            <span>{feedback.msg}</span>
          </div>
          <button onClick={() => setFeedback(null)} className="hover:opacity-75">
            <X size={14} />
          </button>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 border-b border-slate-800 pb-2">
        <button
          onClick={() => setActiveTab('jobs')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
            activeTab === 'jobs'
              ? 'bg-indigo-600 text-white shadow-sm shadow-indigo-600/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
          }`}
        >
          <Briefcase size={15} />
          Saved Jobs ({jobs.length})
        </button>
        <button
          onClick={() => setActiveTab('backups')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
            activeTab === 'backups'
              ? 'bg-indigo-600 text-white shadow-sm shadow-indigo-600/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
          }`}
        >
          <Database size={15} />
          Database Backups & Restore
        </button>
      </div>

      {/* TAB 1: Jobs Management */}
      {activeTab === 'jobs' && (
        <div className="space-y-4">
          <div className="bg-slate-950 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-slate-800 bg-slate-900/40 text-slate-400 uppercase tracking-wider text-[11px]">
                  <th className="py-3 px-4 font-semibold">ID</th>
                  <th className="py-3 px-4 font-semibold">Job Title</th>
                  <th className="py-3 px-4 font-semibold">Target Location</th>
                  <th className="py-3 px-4 font-semibold">Linked Candidates</th>
                  <th className="py-3 px-4 font-semibold">Created</th>
                  <th className="py-3 px-4 text-right font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {jobs.map((job) => (
                  <tr key={job.id} className="hover:bg-slate-900/60 transition-colors">
                    <td className="py-3.5 px-4 font-mono text-slate-400">#{job.id}</td>

                    <td className="py-3.5 px-4">
                      {editingJobId === job.id ? (
                        <input
                          type="text"
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                          className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-100 font-medium w-full"
                        />
                      ) : (
                        <span className="font-semibold text-slate-200">{job.title}</span>
                      )}
                    </td>

                    <td className="py-3.5 px-4">
                      {editingJobId === job.id ? (
                        <input
                          type="text"
                          value={editLocation}
                          onChange={(e) => setEditLocation(e.target.value)}
                          className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-100 w-full"
                        />
                      ) : (
                        <span className="text-slate-400">{job.location || 'Remote / Unspecified'}</span>
                      )}
                    </td>

                    <td className="py-3.5 px-4">
                      <Badge variant="indigo">{job.candidate_count ?? 0} candidates</Badge>
                    </td>

                    <td className="py-3.5 px-4 text-slate-500">
                      {job.created_at ? new Date(job.created_at).toLocaleDateString() : 'N/A'}
                    </td>

                    <td className="py-3.5 px-4 text-right">
                      <div className="flex items-center justify-end gap-2">
                        {editingJobId === job.id ? (
                          <>
                            <button
                              onClick={() => handleSaveJob(job.id)}
                              disabled={savingJob}
                              className="p-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded"
                              title="Save changes"
                            >
                              <Save size={13} />
                            </button>
                            <button
                              onClick={() => setEditingJobId(null)}
                              className="p-1.5 bg-slate-800 text-slate-400 hover:text-white rounded"
                              title="Cancel"
                            >
                              <X size={13} />
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              onClick={() => handleStartEdit(job)}
                              className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded"
                              title="Edit job title & location"
                            >
                              <Edit2 size={13} />
                            </button>
                            <button
                              onClick={() => handleDeleteJob(job.id, job.title)}
                              className="p-1.5 text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 rounded"
                              title="Delete job"
                            >
                              <Trash2 size={13} />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 2: Backups & Restore */}
      {activeTab === 'backups' && (
        <div className="space-y-6">
          {/* Action Row */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-5 rounded-2xl bg-slate-950 border border-slate-800">
            <div>
              <h3 className="text-sm font-semibold text-slate-200">Transactional SQLite Backups</h3>
              <p className="text-xs text-slate-400 mt-0.5">
                Uses SQLite's online transactional backup API. Safe against concurrent writes with zero locking issues.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <label className="cursor-pointer inline-flex items-center gap-1.5 px-3.5 py-2 bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-300 rounded-xl text-xs font-medium transition-colors">
                <Upload size={14} />
                {restoringBackup ? 'Restoring snapshot...' : 'Restore from .db File'}
                <input
                  type="file"
                  accept=".db"
                  className="hidden"
                  onChange={handleRestoreBackup}
                  disabled={restoringBackup}
                />
              </label>

              <button
                onClick={handleCreateBackup}
                disabled={creatingBackup}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all shadow-sm shadow-indigo-600/30 cursor-pointer"
              >
                {creatingBackup ? (
                  <>
                    <Loader2 size={14} className="animate-spin" /> Creating Backup...
                  </>
                ) : (
                  <>
                    <Database size={14} /> Create Backup Now
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Backup List */}
          <div className="bg-slate-950 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
            {loadingBackups ? (
              <div className="py-16 text-center text-slate-400 text-xs flex items-center justify-center gap-2">
                <Loader2 size={16} className="animate-spin" /> Loading backup catalog...
              </div>
            ) : backups.length > 0 ? (
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-slate-800 bg-slate-900/40 text-slate-400 uppercase tracking-wider text-[11px]">
                    <th className="py-3 px-4 font-semibold">Backup Filename</th>
                    <th className="py-3 px-4 font-semibold">Size</th>
                    <th className="py-3 px-4 font-semibold">Created Timestamp</th>
                    <th className="py-3 px-4 font-semibold">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/80">
                  {backups.map((b) => (
                    <tr key={b.filename} className="hover:bg-slate-900/60 transition-colors">
                      <td className="py-3 px-4 font-mono text-slate-200">{b.filename}</td>
                      <td className="py-3 px-4 text-slate-400">{b.size_kb} KB</td>
                      <td className="py-3 px-4 text-slate-400">{b.created_at}</td>
                      <td className="py-3 px-4">
                        <Badge variant="emerald">Verified Snapshot</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="py-16 text-center text-slate-500 text-sm">
                No backup files found. Click "Create Backup Now" to capture an instant snapshot.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
