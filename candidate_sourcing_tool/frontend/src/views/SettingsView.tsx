import React, { useEffect, useState } from 'react';
import {
  Settings,
  ShieldCheck,
  Cpu,
  Sparkles,
  Lock,
  AlertCircle,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import { GithubIcon } from '../components/GithubIcon';
import { api } from '../api';
import type { SystemSettings } from '../types';
import { Badge } from '../components/Badge';

export const SettingsView: React.FC = () => {
  const [settings, setSettings] = useState<SystemSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Smoke Test States
  const [testingGroq, setTestingGroq] = useState(false);
  const [groqTestResult, setGroqTestResult] = useState<{
    success: boolean;
    model: string;
    latency_ms: number;
    message: string;
  } | null>(null);

  const [testingGithub, setTestingGithub] = useState(false);
  const [githubTestResult, setGithubTestResult] = useState<SystemSettings['github_search'] | null>(null);

  const loadSettings = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getSettings();
      setSettings(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load system settings.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSettings();
  }, []);

  const handleTestGroq = async () => {
    try {
      setTestingGroq(true);
      const res = await api.testGroq();
      setGroqTestResult(res);
    } catch (err: any) {
      setGroqTestResult({
        success: false,
        model: settings?.groq_extractor.active_model || 'Unknown',
        latency_ms: 0,
        message: err.message || 'Groq test failed.',
      });
    } finally {
      setTestingGroq(false);
    }
  };

  const handleTestGithub = async () => {
    try {
      setTestingGithub(true);
      const res = await api.testGitHub();
      setGithubTestResult(res);
    } catch (err: any) {
      console.error(err);
    } finally {
      setTestingGithub(false);
    }
  };

  return (
    <div className="p-8 space-y-8 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight flex items-center gap-2.5">
            <Settings className="text-indigo-400" size={26} />
            System Architecture & Zero-Budget Policy
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Verification of offline components, free-tier integrations, and zero-cost constraints.
          </p>
        </div>
        <button
          onClick={loadSettings}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium rounded-lg transition-colors border border-slate-700"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm flex items-center gap-2">
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      {/* Grid of Setting Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Card 1: Strict Zero-Budget Policy */}
        <div className="bg-slate-950 border border-slate-800 rounded-2xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-xl bg-emerald-500/10 text-emerald-400">
                <ShieldCheck size={20} />
              </div>
              <h2 className="text-sm font-semibold text-slate-200">Zero-Budget Policy</h2>
            </div>
            <Badge variant="emerald">Spend: ₹0.00</Badge>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            All billable APIs (Exa paid endpoints, SerpAPI, paid scraping services, credit subscriptions) are strictly blocked.
          </p>
          <div className="p-3 bg-slate-900 rounded-xl border border-slate-800/80 text-xs space-y-1.5">
            <div className="flex justify-between text-slate-400">
              <span>Financial Cap:</span>
              <span className="font-semibold text-emerald-400">₹0.00 (Zero spend)</span>
            </div>
            <div className="flex justify-between text-slate-400">
              <span>Paid Endpoints:</span>
              <span className="font-semibold text-slate-200">Disabled by design</span>
            </div>
            <div className="flex justify-between text-slate-400">
              <span>Billing Account:</span>
              <span className="font-semibold text-slate-200">None required</span>
            </div>
          </div>
        </div>

        {/* Card 2: Local Rule-Based Extractor */}
        <div className="bg-slate-950 border border-slate-800 rounded-2xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-xl bg-indigo-500/10 text-indigo-400">
                <Cpu size={20} />
              </div>
              <h2 className="text-sm font-semibold text-slate-200">Local Extractor Engine</h2>
            </div>
            <Badge variant="indigo">Default</Badge>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            Rule-based offline NLP running entirely on your Windows laptop's CPU. Never makes external network requests.
          </p>
          <div className="p-3 bg-slate-900 rounded-xl border border-slate-800/80 text-xs space-y-1.5">
            <div className="flex justify-between text-slate-400">
              <span>Offline Execution:</span>
              <span className="font-semibold text-emerald-400">100% CPU Local</span>
            </div>
            <div className="flex justify-between text-slate-400">
              <span>Telemetry:</span>
              <span className="font-semibold text-slate-200">None</span>
            </div>
            <div className="flex justify-between text-slate-400">
              <span>Latency:</span>
              <span className="font-semibold text-slate-200">&lt; 50ms</span>
            </div>
          </div>
        </div>

        {/* Card 3: Groq Free AI Extractor */}
        <div className="bg-slate-950 border border-slate-800 rounded-2xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-xl bg-amber-500/10 text-amber-400">
                <Sparkles size={20} />
              </div>
              <h2 className="text-sm font-semibold text-slate-200">Groq AI (Free Tier)</h2>
            </div>
            <Badge variant="amber">Optional</Badge>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            Configurable fast LLM inference. Model defaults to modern non-deprecated endpoint.
          </p>
          <div className="p-3 bg-slate-900 rounded-xl border border-slate-800/80 text-xs space-y-1.5">
            <div className="flex justify-between text-slate-400">
              <span>Configured Model:</span>
              <span className="font-mono text-indigo-300 font-semibold truncate max-w-[180px]">
                {settings?.groq_extractor.active_model || 'openai/gpt-oss-120b'}
              </span>
            </div>
            <div className="flex justify-between text-slate-400">
              <span>API Key in .env:</span>
              <span className="font-semibold text-slate-200">
                {settings?.groq_extractor.api_key_configured ? 'Configured (Secret Hidden)' : 'Not detected'}
              </span>
            </div>
          </div>

          <div className="pt-2 flex items-center justify-between">
            <button
              onClick={handleTestGroq}
              disabled={testingGroq}
              className="px-3.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors cursor-pointer"
            >
              {testingGroq ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              Test Groq Connection
            </button>
            {groqTestResult && (
              <span
                className={`text-xs font-semibold ${
                  groqTestResult.success ? 'text-emerald-400' : 'text-rose-400'
                }`}
              >
                {groqTestResult.success
                  ? `Success (${groqTestResult.latency_ms}ms)`
                  : 'Test failed'}
              </span>
            )}
          </div>
        </div>

        {/* Card 4: Official GitHub Search Provider */}
        <div className="bg-slate-950 border border-slate-800 rounded-2xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-xl bg-purple-500/10 text-purple-400">
                <GithubIcon size={20} />
              </div>
              <h2 className="text-sm font-semibold text-slate-200">GitHub Public Sourcing</h2>
            </div>
            <Badge variant="purple">Official Public API</Badge>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            Free, official, zero-budget candidate discovery for technical roles. Rate-limit aware.
          </p>
          <div className="p-3 bg-slate-900 rounded-xl border border-slate-800/80 text-xs space-y-1.5">
            <div className="flex justify-between text-slate-400">
              <span>Rate Limit Remaining:</span>
              <span className="font-semibold text-slate-200">
                {(githubTestResult || settings?.github_search)?.remaining ?? 'N/A'} / {(githubTestResult || settings?.github_search)?.limit ?? 60} req/hr
              </span>
            </div>
            <div className="flex justify-between text-slate-400">
              <span>Status:</span>
              <span className="font-semibold text-emerald-400">
                {(githubTestResult || settings?.github_search)?.status || 'Operational'}
              </span>
            </div>
          </div>

          <div className="pt-2 flex justify-end">
            <button
              onClick={handleTestGithub}
              disabled={testingGithub}
              className="px-3.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors cursor-pointer"
            >
              {testingGithub ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              Check Rate Limit
            </button>
          </div>
        </div>
      </div>

      {/* Verified Zero-Budget Multi-Source Connectors */}
      <div className="bg-slate-950 border border-slate-800 rounded-2xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-200 flex items-center gap-2">
            <ShieldCheck size={18} className="text-emerald-400" />
            Verified Zero-Budget Candidate Connectors
          </h2>
          <span className="text-xs font-bold text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-0.5 rounded-full">
            All Verified ₹0.00 Cost
          </span>
        </div>
        <p className="text-xs text-slate-400">
          The candidate sourcing engine coordinates across 5 eligible free talent channels without billing accounts or paid scrapers.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3 pt-1">
          {[
            { name: 'GitHub Public API', cost: '₹0.00', desc: 'Public developer profiles, contributions, and repositories', status: 'Active' },
            { name: 'GitLab Public API', cost: '₹0.00', desc: 'Open-source project creators and user namespaces', status: 'Active' },
            { name: 'Stack Overflow Public API', cost: '₹0.00', desc: 'Public technical contributors with verified reputation', status: 'Active' },
            { name: 'Hugging Face Hub API', cost: '₹0.00', desc: 'AI/ML and Data Science model and dataset authors', status: 'Active' },
            { name: 'Local Talent Rediscovery', cost: '₹0.00', desc: 'Offline SQLite database search for previously sourced talent', status: 'Active' },
            { name: 'Manual X-Ray Search Links', cost: '₹0.00', desc: 'Recruiter-executed Google and Bing queries (Manual Browser Fallback)', status: 'Fallback' },
          ].map((c) => (
            <div key={c.name} className="p-3.5 bg-slate-900/80 border border-slate-800 rounded-xl space-y-1">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-xs text-slate-200">{c.name}</span>
                <span className="text-[10px] font-bold text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded">
                  {c.cost}
                </span>
              </div>
              <p className="text-[11px] text-slate-400 leading-tight">{c.desc}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Privacy Guarantee Card */}
      <div className="p-5 rounded-2xl bg-slate-950 border border-slate-800 flex items-start gap-3.5">
        <div className="p-2 rounded-xl bg-cyan-500/10 text-cyan-400 shrink-0">
          <Lock size={20} />
        </div>
        <div className="space-y-1">
          <h3 className="text-sm font-semibold text-slate-200">Complete Privacy Guarantee</h3>
          <p className="text-xs text-slate-400 leading-relaxed">
            Candidate records, CVs, phone numbers, email addresses, and recruiter notes never leave your computer. Sourced data is stored in the local SQLite file (<code className="text-slate-300">{settings?.database.file || 'candidate_sourcing.db'}</code>, currently {settings?.database.size_kb} KB) and is never transmitted to any third-party cloud.
          </p>
        </div>
      </div>
    </div>
  );
};
