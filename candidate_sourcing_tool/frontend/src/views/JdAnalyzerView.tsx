import React, { useEffect, useState } from 'react';
import {
  Upload,
  Cpu,
  Sparkles,
  CheckCircle,
  AlertTriangle,
  X,
  Save,
  ArrowRight,
  Loader2,
  FileSearch,
  CheckCircle2,
  KeyRound,
} from 'lucide-react';
import { api } from '../api';
import type { JobRequirements } from '../types';
import { Badge } from '../components/Badge';
import type { ViewType } from '../components/Sidebar';

interface JdAnalyzerViewProps {
  onJobSaved: (jobId: number) => void;
  onNavigate: (view: ViewType) => void;
}

export const JdAnalyzerView: React.FC<JdAnalyzerViewProps> = ({
  onJobSaved,
  onNavigate,
}) => {
  // Form State
  const [jdText, setJdText] = useState('');
  const [engine, setEngine] = useState<'local' | 'groq'>('local');
  const [groqModel, setGroqModel] = useState('openai/gpt-oss-120b');
  const [sessionKey, setSessionKey] = useState('');
  const [showKeyInput, setShowKeyInput] = useState(false);
  const [envKeyConfigured, setEnvKeyConfigured] = useState<boolean | null>(null);

  // Status
  const [parsingFile, setParsingFile] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Extracted Requirements for Editing
  const [reqs, setReqs] = useState<JobRequirements | null>(null);
  const [extractionMeta, setExtractionMeta] = useState<{
    engine: string;
    model: string;
    message: string;
    confidenceLevel?: string;
  } | null>(null);

  // New tag inputs
  const [newCoreSkill, setNewCoreSkill] = useState('');
  const [newTool, setNewTool] = useState('');
  const [newAltTitle, setNewAltTitle] = useState('');

  // Check Groq status on mount
  useEffect(() => {
    const checkSettings = async () => {
      try {
        const s = await api.getSettings();
        setEnvKeyConfigured(s.groq_extractor.api_key_configured);
        if (s.groq_extractor.active_model) {
          setGroqModel(s.groq_extractor.active_model);
        }
      } catch (err) {
        console.error('Failed to load settings:', err);
      }
    };
    checkSettings();
  }, []);

  // Handle file upload
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      setParsingFile(true);
      setError(null);
      const res = await api.parseDocument(file);
      setJdText(res.text);
    } catch (err: any) {
      setError(err.message || 'Failed to parse file.');
    } finally {
      setParsingFile(false);
    }
  };

  // Run analysis
  const handleAnalyze = async () => {
    if (!jdText.trim()) {
      setError('Please paste or upload a Job Description before analyzing.');
      return;
    }

    try {
      setAnalyzing(true);
      setError(null);
      setSuccessMsg(null);

      const res = await api.analyzeJd({
        jd_text: jdText,
        engine,
        groq_model: engine === 'groq' ? groqModel : undefined,
        session_key: sessionKey || undefined,
      });

      setReqs(res.requirements);
      setExtractionMeta({
        engine: res.engine,
        model: res.model,
        message: res.message,
        confidenceLevel: res.title_extraction?.confidence_level,
      });
    } catch (err: any) {
      setError(err.message || 'Failed to analyze Job Description.');
    } finally {
      setAnalyzing(false);
    }
  };

  // Full end-to-end: Analyze -> Save -> Navigate to Sourcing Engine
  const handleAnalyzeAndFindCandidates = async () => {
    if (!jdText.trim()) {
      setError('Please paste or upload a Job Description before proceeding.');
      return;
    }

    try {
      setAnalyzing(true);
      setError(null);

      let activeReqs = reqs;
      if (!activeReqs) {
        const res = await api.analyzeJd({
          jd_text: jdText,
          engine,
          groq_model: engine === 'groq' ? groqModel : undefined,
          session_key: sessionKey ? sessionKey.trim() : undefined,
        });
        activeReqs = res.requirements;
        setReqs(res.requirements);
      }

      const saved = await api.createJob({
        title: activeReqs.job_title || 'Untitled Role',
        jd_text: jdText,
        location: activeReqs.location || '',
        extracted_data: JSON.stringify(activeReqs),
      });

      onJobSaved(saved.id);
      onNavigate('discovery');
    } catch (err: any) {
      setError(err.message || 'Analysis or save failed.');
    } finally {
      setAnalyzing(false);
    }
  };

  // Save to SQLite
  const handleSaveJob = async () => {
    if (!reqs) return;

    try {
      setSaving(true);
      setError(null);

      const saved = await api.createJob({
        title: reqs.job_title || 'Untitled Role',
        jd_text: jdText,
        location: reqs.location || '',
        extracted_data: JSON.stringify(reqs),
      });

      setSuccessMsg(`Job #${saved.id} ("${saved.title}") saved successfully to local SQLite.`);
      onJobSaved(saved.id);
    } catch (err: any) {
      setError(err.message || 'Failed to save job.');
    } finally {
      setSaving(false);
    }
  };


  // Tag manipulation helpers
  const removeTag = (field: keyof JobRequirements, item: string) => {
    if (!reqs) return;
    const currentList = (reqs[field] as string[]) || [];
    const updated = currentList.filter((x) => x !== item);
    const newReqs = { ...reqs, [field]: updated };
    if (field === 'core_skills') newReqs.required_skills = updated;
    if (field === 'tools_and_technologies') newReqs.tools_and_tech = updated;
    setReqs(newReqs);
  };

  const addTag = (field: keyof JobRequirements, value: string, clearFn: () => void) => {
    if (!reqs || !value.trim()) return;
    const currentList = (reqs[field] as string[]) || [];
    const val = value.trim();
    if (!currentList.includes(val)) {
      const updated = [...currentList, val];
      const newReqs = { ...reqs, [field]: updated };
      if (field === 'core_skills') newReqs.required_skills = updated;
      if (field === 'tools_and_technologies') newReqs.tools_and_tech = updated;
      setReqs(newReqs);
    }
    clearFn();
  };

  const coreSkills = reqs?.core_skills || reqs?.required_skills || [];
  const tools = reqs?.tools_and_technologies || reqs?.tools_and_tech || [];
  const altTitles = reqs?.alternative_titles || [];

  return (
    <div className="p-8 space-y-8 max-w-5xl mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-100 tracking-tight flex items-center gap-2.5">
          <FileSearch className="text-indigo-400" size={26} />
          Job Description Analyzer
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Extract core skills, tools, titles, and locations offline or via free-tier Groq AI. Review and customize before persisting.
        </p>
      </div>

      {/* Notifications */}
      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm flex items-start gap-3">
          <AlertTriangle size={18} className="shrink-0 mt-0.5" />
          <div className="flex-1">{error}</div>
          <button onClick={() => setError(null)} className="text-rose-400 hover:text-rose-300">
            <X size={16} />
          </button>
        </div>
      )}

      {successMsg && (
        <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-sm flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <CheckCircle size={18} />
            <span>{successMsg}</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => onNavigate('discovery')}
              className="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1 transition-colors"
            >
              Start Sourcing <ArrowRight size={13} />
            </button>
          </div>
        </div>
      )}

      {/* Step 1: Input & Configuration */}
      <div className="bg-slate-950 border border-slate-800 rounded-2xl p-6 space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-4">
          <h2 className="text-base font-semibold text-slate-200">1. Job Description & Engine</h2>
          <label className="cursor-pointer inline-flex items-center gap-2 px-3 py-1.5 bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-300 rounded-lg text-xs font-medium transition-colors">
            <Upload size={14} />
            {parsingFile ? 'Reading file...' : 'Upload PDF / DOCX / TXT'}
            <input
              type="file"
              accept=".pdf,.docx,.txt,.md"
              className="hidden"
              onChange={handleFileUpload}
              disabled={parsingFile}
            />
          </label>
        </div>

        {/* Engine Selection */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div
            onClick={() => setEngine('local')}
            className={`p-4 rounded-xl border cursor-pointer transition-all ${
              engine === 'local'
                ? 'bg-indigo-950/40 border-indigo-500/60 ring-1 ring-indigo-500/40'
                : 'bg-slate-900/40 border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="font-semibold text-sm text-slate-200 flex items-center gap-2">
                <Cpu size={16} className="text-indigo-400" /> Local Extractor (Default)
              </span>
              <Badge variant="emerald">100% Offline</Badge>
            </div>
            <p className="text-xs text-slate-400 leading-relaxed">
              Deterministic rule-based NLP running on local CPU. Zero network calls, zero data transfer, zero telemetry.
            </p>
          </div>

          <div
            onClick={() => setEngine('groq')}
            className={`p-4 rounded-xl border cursor-pointer transition-all ${
              engine === 'groq'
                ? 'bg-indigo-950/40 border-indigo-500/60 ring-1 ring-indigo-500/40'
                : 'bg-slate-900/40 border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="font-semibold text-sm text-slate-200 flex items-center gap-2">
                <Sparkles size={16} className="text-amber-400" /> Optional Groq AI
              </span>
              <Badge variant="amber">Free Tier Only</Badge>
            </div>
            <p className="text-xs text-slate-400 leading-relaxed">
              Fast LLM inference via Groq Free API. Model defaults to <code className="text-indigo-300">openai/gpt-oss-120b</code>.
            </p>
          </div>
        </div>

        {/* Groq Settings & Key Status Banner */}
        {engine === 'groq' && (
          <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-3 text-xs">
            {/* Status of .env Key */}
            {envKeyConfigured ? (
              <div className="flex items-center justify-between p-3 bg-emerald-500/10 border border-emerald-500/25 rounded-xl text-emerald-400">
                <div className="flex items-center gap-2.5">
                  <CheckCircle2 size={16} className="shrink-0" />
                  <div>
                    <span className="font-semibold">GROQ_API_KEY detected in .env file</span>
                    <span className="block text-[11px] text-slate-300 mt-0.5">
                      Ready to fetch automatically using <strong className="text-emerald-300">{groqModel}</strong>. No manual key entry needed.
                    </span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setShowKeyInput(!showKeyInput)}
                  className="text-[11px] text-slate-400 hover:text-slate-200 underline ml-2 shrink-0 cursor-pointer"
                >
                  {showKeyInput ? 'Hide override' : 'Custom key override'}
                </button>
              </div>
            ) : (
              <div className="flex items-center justify-between p-3 bg-amber-500/10 border border-amber-500/25 rounded-xl text-amber-400">
                <div className="flex items-center gap-2.5">
                  <AlertTriangle size={16} className="shrink-0" />
                  <div>
                    <span className="font-semibold">No GROQ_API_KEY detected in .env</span>
                    <span className="block text-[11px] text-slate-300 mt-0.5">
                      Add it to your project's .env file, or paste a temporary session key below.
                    </span>
                  </div>
                </div>
              </div>
            )}

            <div className="flex flex-col sm:flex-row gap-3 pt-1">
              <div className="flex-1">
                <label className="text-slate-400 block mb-1 font-medium">Groq Model</label>
                <input
                  type="text"
                  value={groqModel}
                  onChange={(e) => setGroqModel(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-1.5 text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>

              {/* Show Key input only if not configured or user explicitly clicked override */}
              {(showKeyInput || !envKeyConfigured) && (
                <div className="flex-1">
                  <label className="text-slate-400 block mb-1 font-medium flex items-center gap-1">
                    <KeyRound size={12} /> Session API Key Override
                  </label>
                  <input
                    type="password"
                    placeholder="Enter gsk_... (Temporary session key)"
                    value={sessionKey}
                    onChange={(e) => setSessionKey(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-1.5 text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </div>
              )}
            </div>
          </div>
        )}

        {/* JD Text Area */}
        <div>
          <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
            Job Description Text
          </label>
          <textarea
            rows={10}
            value={jdText}
            onChange={(e) => setJdText(e.target.value)}
            placeholder="Paste raw Job Description text here (responsibilities, required qualifications, tools, location)..."
            className="w-full bg-slate-900 border border-slate-800 rounded-xl p-4 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 leading-relaxed resize-y font-mono text-xs"
          ></textarea>
        </div>

        {/* Analyze Buttons */}
        <div className="flex flex-wrap items-center justify-end gap-3">
          <button
            onClick={handleAnalyze}
            disabled={analyzing || !jdText.trim()}
            className="px-5 py-2.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 disabled:opacity-50 text-slate-200 rounded-xl text-sm font-medium flex items-center gap-2 transition-all cursor-pointer"
          >
            {analyzing ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Cpu size={16} />
            )}
            {engine === 'groq' ? 'Extract with Groq AI' : 'Extract Offline'}
          </button>

          <button
            onClick={handleAnalyzeAndFindCandidates}
            disabled={analyzing || !jdText.trim()}
            className="px-6 py-2.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 disabled:opacity-50 text-white rounded-xl text-sm font-bold flex items-center gap-2 shadow-lg shadow-indigo-600/30 transition-all cursor-pointer"
          >
            {analyzing ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                <span>Running Pipeline...</span>
              </>
            ) : (
              <>
                <Sparkles size={16} className="text-amber-300" />
                <span>⚡ Analyze JD & Find Candidates</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Step 2: Extracted Requirements Review & Edit */}
      {reqs && (
        <div className="bg-slate-950 border border-slate-800 rounded-2xl p-6 space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-4">
            <div>
              <h2 className="text-base font-semibold text-slate-200">2. Review & Refine Requirements</h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Engine:{' '}
                <span className="text-indigo-400 font-medium">
                  {extractionMeta?.engine === 'groq' ? 'Groq AI (Free Tier)' : extractionMeta?.engine}
                </span>{' '}
                ({extractionMeta?.model})
              </p>
            </div>
            <div className="flex items-center gap-2">
              {extractionMeta?.engine === 'groq' && (
                <Badge variant="emerald">Groq AI Extraction</Badge>
              )}
              {extractionMeta?.engine === 'local_fallback' && (
                <Badge variant="amber">Local Fallback</Badge>
              )}
              <Badge variant="indigo">Confidence: {extractionMeta?.confidenceLevel || 'High'}</Badge>
            </div>
          </div>

          {/* Engine Feedback Message */}
          {extractionMeta?.message && (
            <div
              className={`p-3 rounded-xl border text-xs flex items-center gap-2 ${
                extractionMeta.engine === 'groq'
                  ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-300'
                  : 'bg-indigo-500/10 border-indigo-500/25 text-indigo-300'
              }`}
            >
              <Sparkles size={14} className="shrink-0" />
              <span>{extractionMeta.message}</span>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Job Title */}
            <div>
              <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">
                Primary Job Title
              </label>
              <input
                type="text"
                value={reqs.job_title}
                onChange={(e) => setReqs({ ...reqs, job_title: e.target.value })}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>

            {/* Target Location */}
            <div>
              <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">
                Target Location / Arrangement
              </label>
              <input
                type="text"
                value={reqs.location || ''}
                onChange={(e) => setReqs({ ...reqs, location: e.target.value })}
                placeholder="e.g. Bengaluru, India or Remote"
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          </div>

          {/* Alternative Titles */}
          <div>
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-2">
              Alternative Titles ({altTitles.length})
            </label>
            <div className="flex flex-wrap gap-2 mb-2.5">
              {altTitles.map((title) => (
                <span
                  key={title}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-slate-900 border border-slate-700 text-slate-200 text-xs rounded-lg"
                >
                  {title}
                  <button onClick={() => removeTag('alternative_titles', title)} className="text-slate-400 hover:text-rose-400">
                    <X size={12} />
                  </button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="Add alternative title..."
                value={newAltTitle}
                onChange={(e) => setNewAltTitle(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addTag('alternative_titles', newAltTitle, () => setNewAltTitle(''))}
                className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500 w-64"
              />
              <button
                onClick={() => addTag('alternative_titles', newAltTitle, () => setNewAltTitle(''))}
                className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium cursor-pointer"
              >
                Add Title
              </button>
            </div>
          </div>

          {/* Required Core Skills */}
          <div>
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-2">
              Required Core Skills ({coreSkills.length}) · 40% Match Weight
            </label>
            <div className="flex flex-wrap gap-2 mb-2.5">
              {coreSkills.map((skill) => (
                <span
                  key={skill}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-indigo-500/15 border border-indigo-500/30 text-indigo-300 text-xs rounded-lg font-medium"
                >
                  {skill}
                  <button onClick={() => removeTag('core_skills', skill)} className="text-indigo-400 hover:text-rose-400">
                    <X size={12} />
                  </button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="Add core skill (e.g. python, sql)..."
                value={newCoreSkill}
                onChange={(e) => setNewCoreSkill(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addTag('core_skills', newCoreSkill, () => setNewCoreSkill(''))}
                className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500 w-64"
              />
              <button
                onClick={() => addTag('core_skills', newCoreSkill, () => setNewCoreSkill(''))}
                className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium cursor-pointer"
              >
                Add Skill
              </button>
            </div>
          </div>

          {/* Tools & Technologies */}
          <div>
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-2">
              Tools & Technologies ({tools.length}) · 25% Match Weight
            </label>
            <div className="flex flex-wrap gap-2 mb-2.5">
              {tools.map((tool) => (
                <span
                  key={tool}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-cyan-500/15 border border-cyan-500/30 text-cyan-300 text-xs rounded-lg font-medium"
                >
                  {tool}
                  <button onClick={() => removeTag('tools_and_technologies', tool)} className="text-cyan-400 hover:text-rose-400">
                    <X size={12} />
                  </button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="Add tool (e.g. docker, tableau, git)..."
                value={newTool}
                onChange={(e) => setNewTool(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addTag('tools_and_technologies', newTool, () => setNewTool(''))}
                className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500 w-64"
              />
              <button
                onClick={() => addTag('tools_and_technologies', newTool, () => setNewTool(''))}
                className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium cursor-pointer"
              >
                Add Tool
              </button>
            </div>
          </div>

          {/* Save to SQLite Actions */}
          <div className="pt-4 border-t border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <span className="text-xs text-slate-400">
              Saving creates or updates the active role record in <code className="text-slate-300">candidate_sourcing.db</code>.
            </span>
            <div className="flex items-center gap-3">
              <button
                onClick={handleSaveJob}
                disabled={saving}
                className="px-5 py-2.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 disabled:opacity-50 text-slate-200 rounded-xl text-sm font-semibold flex items-center gap-2 transition-all cursor-pointer"
              >
                {saving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                Save Job Only
              </button>

              <button
                onClick={async () => {
                  await handleSaveJob();
                  onNavigate('discovery');
                }}
                disabled={saving}
                className="px-6 py-2.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 disabled:opacity-50 text-white rounded-xl text-sm font-bold flex items-center gap-2 shadow-lg shadow-indigo-600/30 transition-all cursor-pointer"
              >
                <span>Save & Find Candidates</span>
                <ArrowRight size={16} />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
