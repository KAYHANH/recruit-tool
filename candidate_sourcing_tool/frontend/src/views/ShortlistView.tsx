import React, { useEffect, useState } from 'react';
import {
  CheckCircle2,
  Download,
  Mail,
  Phone,
  Building,
  MapPin,
  ExternalLink,
  RotateCcw,
  Edit3,
  Loader2,
  AlertCircle,
  Check,
} from 'lucide-react';
import { api } from '../api';
import type { Candidate, Job } from '../types';
import { CandidateDetailDrawer } from '../components/CandidateDetailDrawer';

interface ShortlistViewProps {
  jobs: Job[];
  activeJobId: number | null;
  onSelectJob: (id: number) => void;
  onShortlistChanged: () => void;
}

export const ShortlistView: React.FC<ShortlistViewProps> = ({
  jobs: _jobs,
  activeJobId,
  onSelectJob: _onSelectJob,
  onShortlistChanged,
}) => {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingNotesId, setEditingNotesId] = useState<number | null>(null);
  const [notesValue, setNotesValue] = useState<string>('');
  const [actionLoadingId, setActionLoadingId] = useState<number | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState<number | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  const loadShortlist = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getShortlist(activeJobId ?? undefined);
      setCandidates(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load shortlist.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadShortlist();
  }, [activeJobId]);

  // Non-destructive remove from shortlist
  const handleRemoveFromShortlist = async (candidateId: number) => {
    try {
      setActionLoadingId(candidateId);
      await api.removeFromShortlist(candidateId);
      setCandidates((prev) => prev.filter((c) => c.id !== candidateId));
      onShortlistChanged();
    } catch (err: any) {
      alert(`Failed to update candidate: ${err.message}`);
    } finally {
      setActionLoadingId(null);
    }
  };

  // Save notes
  const handleSaveNotes = async (candidateId: number) => {
    try {
      setActionLoadingId(candidateId);
      await api.updateCandidate(candidateId, { notes: notesValue });
      setCandidates((prev) =>
        prev.map((c) => (c.id === candidateId ? { ...c, notes: notesValue } : c))
      );
      setEditingNotesId(null);
    } catch (err: any) {
      alert(`Failed to save notes: ${err.message}`);
    } finally {
      setActionLoadingId(null);
    }
  };

  const exportUrl = api.getExportShortlistUrl(activeJobId ?? undefined);

  return (
    <div className="p-8 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight flex items-center gap-2.5">
            <CheckCircle2 className="text-emerald-400" size={26} />
            Shortlist Pipeline
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Decision-ready candidates selected for interview outreach. Formula-injection sanitized CSV exports.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <a
            href={exportUrl}
            download
            className={`px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-semibold flex items-center gap-2 shadow-lg shadow-emerald-600/20 transition-all ${
              candidates.length === 0 ? 'opacity-50 pointer-events-none' : ''
            }`}
          >
            <Download size={15} />
            Export to CSV
          </a>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm flex items-center gap-2">
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      {/* Table Container */}
      <div className="bg-slate-950 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
        {loading ? (
          <div className="py-20 text-center text-slate-400 text-xs flex items-center justify-center gap-2">
            <Loader2 size={16} className="animate-spin" /> Loading shortlisted candidates...
          </div>
        ) : candidates.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-slate-800 bg-slate-900/40 text-slate-400 uppercase tracking-wider text-[11px]">
                  <th className="py-3 px-4 font-semibold">Candidate</th>
                  <th className="py-3 px-4 font-semibold">Location / Company</th>
                  <th className="py-3 px-4 font-semibold">Verified Contact</th>
                  <th className="py-3 px-4 font-semibold">Recruiter Notes</th>
                  <th className="py-3 px-4 text-right font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {candidates.map((cand) => (
                  <tr key={cand.id} className="hover:bg-slate-900/60 transition-colors">
                    {/* Candidate Name & Link */}
                    <td className="py-3.5 px-4">
                      <div
                        onClick={() => {
                          setSelectedCandidateId(cand.id);
                          setIsDrawerOpen(true);
                        }}
                        className="font-semibold text-slate-200 hover:text-indigo-400 cursor-pointer transition-colors"
                      >
                        {cand.name}
                      </div>
                      <div className="text-[11px] text-slate-400 truncate max-w-xs mt-0.5">
                        {cand.headline || 'Shortlisted profile'}
                      </div>
                      {cand.profile_url && (
                        <a
                          href={cand.profile_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-[11px] text-indigo-400 hover:underline flex items-center gap-1 mt-1"
                        >
                          View Profile <ExternalLink size={10} />
                        </a>
                      )}
                    </td>

                    {/* Location & Company */}
                    <td className="py-3.5 px-4">
                      <div className="text-slate-200 flex items-center gap-1">
                        <Building size={12} className="text-slate-500" />
                        {cand.company || 'Not specified'}
                      </div>
                      <div className="text-slate-400 text-[11px] flex items-center gap-1 mt-0.5">
                        <MapPin size={11} className="text-slate-500" />
                        {cand.location || 'Remote'}
                      </div>
                    </td>

                    {/* Verified Contact & Provenance */}
                    <td className="py-3.5 px-4">
                      {cand.email ? (
                        <div className="text-emerald-400 font-mono flex items-center gap-1">
                          <Mail size={11} /> {cand.email}
                        </div>
                      ) : (
                        <div className="text-slate-500">Email: Not found</div>
                      )}
                      {cand.phone ? (
                        <div className="text-slate-300 font-mono flex items-center gap-1 mt-0.5">
                          <Phone size={11} /> {cand.phone}
                        </div>
                      ) : null}
                      <div className="text-[10px] text-slate-500 mt-1">
                        Provenance: {cand.contact_provenance || 'Profile bio'}
                      </div>
                    </td>

                    {/* Recruiter Notes */}
                    <td className="py-3.5 px-4 max-w-xs">
                      {editingNotesId === cand.id ? (
                        <div className="flex items-center gap-2">
                          <input
                            type="text"
                            value={notesValue}
                            onChange={(e) => setNotesValue(e.target.value)}
                            className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500 w-full"
                          />
                          <button
                            onClick={() => handleSaveNotes(cand.id)}
                            className="p-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded"
                            title="Save note"
                          >
                            <Check size={13} />
                          </button>
                        </div>
                      ) : (
                        <div
                          onClick={() => {
                            setEditingNotesId(cand.id);
                            setNotesValue(cand.notes || '');
                          }}
                          className="cursor-pointer group flex items-center justify-between text-slate-300 hover:text-white"
                          title="Click to edit notes"
                        >
                          <span className="truncate">{cand.notes || 'Click to add notes...'}</span>
                          <Edit3 size={11} className="opacity-0 group-hover:opacity-100 text-indigo-400 shrink-0 ml-1" />
                        </div>
                      )}
                    </td>

                    {/* Actions */}
                    <td className="py-3.5 px-4 text-right">
                      <button
                        onClick={() => handleRemoveFromShortlist(cand.id)}
                        disabled={actionLoadingId === cand.id}
                        className="px-2.5 py-1.5 bg-slate-800 hover:bg-amber-500/20 text-slate-400 hover:text-amber-400 border border-slate-700 hover:border-amber-500/30 rounded-lg text-xs font-medium inline-flex items-center gap-1 transition-colors cursor-pointer"
                        title="Moves candidate to 'Under Review' without deleting record"
                      >
                        <RotateCcw size={12} />
                        Move to Review
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-16 text-center text-slate-500 text-sm">
            No candidates shortlisted yet. Head over to{' '}
            <span className="text-indigo-400">Candidates</span> to evaluate and shortlist talent.
          </div>
        )}
      </div>

      {/* Slide-over Full Candidate Profile Drawer */}
      <CandidateDetailDrawer
        candidateId={selectedCandidateId}
        activeJobId={activeJobId}
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        onCandidateUpdated={() => {
          loadShortlist();
          onShortlistChanged();
        }}
      />
    </div>
  );
};
