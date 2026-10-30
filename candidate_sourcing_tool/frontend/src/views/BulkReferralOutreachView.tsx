import React, { useEffect, useMemo, useState } from 'react';
import { Upload, Mail, RefreshCw, Plus, ExternalLink, ShieldCheck, FileText, AlertCircle } from 'lucide-react';

type Candidate = { id:number; name:string; email:string; skills:string[]; contact_basis_confirmed:boolean; opted_out:boolean };
type Opportunity = { id:number; platform:string; role_title:string; requirements:string; referral_url:string; link_verified_by_user:boolean };
type Match = { candidate_id:number; name:string; email:string; opportunity_id:number; platform:string; role_title:string; referral_url:string; match_score:number; matched_skills:string[]; missing_skills:string[]; draft_exists:boolean; eligible_for_draft:boolean };
type Draft = { id:number; name:string; email:string; platform:string; role_title:string; subject:string; status:string; gmail_draft_id:string };

const request = async <T,>(url:string, init?:RequestInit):Promise<T> => {
  const res = await fetch(url, init);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Request failed');
  return data as T;
};

export const BulkReferralOutreachView: React.FC = () => {
  const [files,setFiles] = useState<File[]>([]);
  const [basis,setBasis] = useState(false);
  const [busy,setBusy] = useState(false);
  const [message,setMessage] = useState('');
  const [error,setError] = useState('');
  const [candidates,setCandidates] = useState<Candidate[]>([]);
  const [opportunities,setOpportunities] = useState<Opportunity[]>([]);
  const [matches,setMatches] = useState<Match[]>([]);
  const [drafts,setDrafts] = useState<Draft[]>([]);
  const [gmailConnected,setGmailConnected] = useState(false);
  const [platform,setPlatform] = useState('Mercor');
  const [role,setRole] = useState('');
  const [requirements,setRequirements] = useState('');
  const [referralUrl,setReferralUrl] = useState('');
  const [verified,setVerified] = useState(false);

  const load = async () => {
    try {
      const [status,cs,ops,ms,ds] = await Promise.all([
        request<any>('/api/bulk-outreach/status'),
        request<Candidate[]>('/api/bulk-outreach/candidates'),
        request<Opportunity[]>('/api/bulk-outreach/opportunities'),
        request<Match[]>('/api/bulk-outreach/matches'),
        request<Draft[]>('/api/bulk-outreach/drafts')
      ]);
      setGmailConnected(status.gmail_connected);
      setCandidates(cs); setOpportunities(ops); setMatches(ms); setDrafts(ds);
    } catch(e) { setError(e instanceof Error ? e.message : 'Could not load outreach data'); }
  };
  useEffect(() => { void load(); }, []);

  const eligible = useMemo(() => matches.filter(m => m.eligible_for_draft && !m.draft_exists),[matches]);

  const importFiles = async () => {
    if (!files.length) { setError('Select PDF/DOCX files first.'); return; }
    if (!basis) { setError('Confirm an appropriate basis for contacting these candidates before importing.'); return; }
    setBusy(true); setError(''); setMessage('');
    try {
      const fd = new FormData();
      files.forEach(f => fd.append('files',f));
      fd.append('contact_basis_confirmed','true');
      const result = await request<any>('/api/bulk-outreach/import',{method:'POST',body:fd});
      setMessage(\`Processed \${result.uploaded_count} files: \${result.new_unique_candidates} new candidates, \${result.duplicates_merged} duplicates merged, \${result.error_count} errors.\`);
      setFiles([]); await load();
    } catch(e) { setError(e instanceof Error ? e.message : 'Import failed'); }
    finally { setBusy(false); }
  };

  const addOpportunity = async () => {
    setBusy(true); setError(''); setMessage('');
    try {
      await request('/api/bulk-outreach/opportunities',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({platform,role_title:role,requirements,referral_url:referralUrl,link_verified_by_user:verified})});
      setRole(''); setRequirements(''); setReferralUrl(''); setVerified(false);
      setMessage('Verified opportunity saved.'); await load();
    } catch(e) { setError(e instanceof Error ? e.message : 'Could not save opportunity'); }
    finally { setBusy(false); }
  };

  const connectGmail = async () => {
    setError('');
    try {
      const result = await request<{authorization_url:string}>('/api/bulk-outreach/gmail/connect');
      window.open(result.authorization_url,'_blank','noopener,noreferrer');
      setMessage('Complete Google authorization in the new tab, then refresh this screen.');
    } catch(e) { setError(e instanceof Error ? e.message : 'Could not connect Gmail'); }
  };

  const createDraft = async (m:Match) => {
    setBusy(true); setError(''); setMessage('');
    try {
      const result = await request<any>('/api/bulk-outreach/drafts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({candidate_id:m.candidate_id,opportunity_id:m.opportunity_id})});
      setMessage(result.message || 'Draft created. It has not been sent.'); await load();
    } catch(e) { setError(e instanceof Error ? e.message : 'Draft creation failed'); }
    finally { setBusy(false); }
  };

  return <div className="p-6 lg:p-8 max-w-7xl mx-auto space-y-6 text-slate-100">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div><p className="text-xs uppercase tracking-[0.2em] text-cyan-400 font-semibold">Recruitment workflow</p><h1 className="text-2xl font-bold mt-1">Bulk CV Referral Outreach</h1><p className="text-sm text-slate-400 mt-2">Import up to 1,000 PDF/DOCX resumes, match verified referrals and create Gmail drafts for manual review.</p></div>
      <button onClick={() => void load()} className="px-3 py-2 rounded-lg border border-slate-700 hover:bg-slate-800 flex items-center gap-2 text-sm"><RefreshCw size={15}/> Refresh</button>
    </div>

    {error && <div className="rounded-lg border border-rose-800 bg-rose-950/40 p-3 text-sm text-rose-200 flex gap-2"><AlertCircle size={17}/>{error}</div>}
    {message && <div className="rounded-lg border border-emerald-800 bg-emerald-950/30 p-3 text-sm text-emerald-200">{message}</div>}

    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {[['Unique candidates',candidates.length],['Opportunities',opportunities.length],['Potential matches',matches.length],['Gmail drafts',drafts.length]].map(([label,value])=><div key={String(label)} className="rounded-xl border border-slate-800 bg-slate-900/70 p-4"><p className="text-xs text-slate-400">{label}</p><p className="text-2xl font-semibold mt-1">{value}</p></div>)}
    </div>

    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 space-y-4">
      <div className="flex items-center gap-2"><Upload size={19} className="text-cyan-400"/><h2 className="font-semibold">1. Bulk CV import</h2></div>
      <p className="text-xs text-slate-400">PDF and DOCX only · Up to 1,000 files per batch · 15 MB maximum per file · text extraction runs locally.</p>
      <input type="file" multiple accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={e=>setFiles(Array.from(e.target.files || []))} className="block w-full text-sm text-slate-300 file:mr-4 file:rounded-lg file:border-0 file:bg-slate-700 file:px-4 file:py-2 file:text-slate-100"/>
      <p className="text-xs text-slate-400">{files.length} file(s) selected</p>
      <label className="flex items-start gap-2 text-sm text-slate-300"><input type="checkbox" checked={basis} onChange={e=>setBasis(e.target.checked)} className="mt-1"/><span>I confirm I have an appropriate legal/consent basis to contact these candidates about relevant opportunities, and will honor opt-outs.</span></label>
      <button disabled={busy || !files.length || !basis} onClick={()=>void importFiles()} className="px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 disabled:opacity-40 text-sm font-semibold">Process CV batch</button>
    </section>

    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 space-y-4">
      <div className="flex items-center gap-2"><Plus size={19} className="text-cyan-400"/><h2 className="font-semibold">2. Add verified referral opportunity</h2></div>
      <p className="text-xs text-slate-400">Enter your own referral link and role requirements. This app does not invent jobs or referral URLs.</p>
      <div className="grid md:grid-cols-2 gap-3">
        <select value={platform} onChange={e=>setPlatform(e.target.value)} className="rounded-lg bg-slate-950 border border-slate-700 p-2.5 text-sm"><option>Turing</option><option>Mercor</option><option>micro1</option></select>
        <input value={role} onChange={e=>setRole(e.target.value)} placeholder="Role title (e.g. AI Evaluator)" className="rounded-lg bg-slate-950 border border-slate-700 p-2.5 text-sm"/>
        <input value={referralUrl} onChange={e=>setReferralUrl(e.target.value)} placeholder="Your HTTPS referral URL" className="md:col-span-2 rounded-lg bg-slate-950 border border-slate-700 p-2.5 text-sm"/>
        <textarea value={requirements} onChange={e=>setRequirements(e.target.value)} placeholder="Required skills / experience (e.g. Python, SQL, ML, 3+ years)" rows={3} className="md:col-span-2 rounded-lg bg-slate-950 border border-slate-700 p-2.5 text-sm"/>
      </div>
      <label className="flex gap-2 text-xs text-slate-300"><input type="checkbox" checked={verified} onChange={e=>setVerified(e.target.checked)}/> I have personally verified this referral URL, role and applicable platform terms.</label>
      <button disabled={busy || !role.trim() || !requirements.trim() || !referralUrl.trim() || !verified} onClick={()=>void addOpportunity()} className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-sm font-semibold">Save opportunity</button>
      {opportunities.length>0 && <div className="space-y-2">{opportunities.map(o=><div key={o.id} className="rounded-lg border border-slate-800 p-3 text-sm flex flex-wrap justify-between gap-2"><span className="font-medium">{o.platform} · {o.role_title}</span><a href={o.referral_url} target="_blank" rel="noreferrer" className="text-cyan-400 flex items-center gap-1">Verify link <ExternalLink size={13}/></a></div>)}</div>}
    </section>

    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 space-y-4">
      <div className="flex flex-wrap justify-between gap-3 items-center"><div className="flex items-center gap-2"><Mail size={19} className="text-cyan-400"/><h2 className="font-semibold">3. Gmail connection & draft review</h2></div><span className={gmailConnected?'text-emerald-400':'text-amber-400'}>{gmailConnected?'Connected':'Not connected'}</span></div>
      <p className="text-xs text-slate-400">OAuth requests Gmail compose access only. Drafts are created in Gmail; this application has no send-email action.</p>
      <button onClick={()=>void connectGmail()} className="px-4 py-2 rounded-lg border border-slate-700 hover:bg-slate-800 text-sm">Connect Gmail</button>
      <div className="flex items-center gap-2 pt-2"><ShieldCheck size={17} className="text-emerald-400"/><h3 className="font-medium text-sm">Eligible candidate matches ({eligible.length})</h3></div>
      <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead className="text-slate-400 border-b border-slate-800"><tr><th className="py-2 pr-3">Candidate</th><th className="py-2 pr-3">Opportunity</th><th className="py-2 pr-3">Fit</th><th className="py-2 pr-3">Evidence</th><th className="py-2">Action</th></tr></thead><tbody>{matches.map((m,i)=><tr key={m.candidate_id+'-'+m.opportunity_id} className="border-b border-slate-800/70"><td className="py-3 pr-3"><div>{m.name}</div><div className="text-slate-500">{m.email}</div></td><td className="py-3 pr-3">{m.platform}<div className="text-slate-500">{m.role_title}</div></td><td className="py-3 pr-3">{m.match_score}%</td><td className="py-3 pr-3 text-slate-400">{m.matched_skills.join(', ') || 'No matched skills'}</td><td className="py-3">{m.draft_exists?<span className="text-emerald-400">Draft exists</span>:m.eligible_for_draft?<button disabled={busy || !gmailConnected} onClick={()=>void createDraft(m)} className="px-2.5 py-1.5 rounded bg-cyan-700 hover:bg-cyan-600 disabled:opacity-40">Create draft</button>:<span className="text-amber-400">Review contact basis</span>}</td></tr>)}</tbody></table></div>
      {matches.length===0 && <p className="text-sm text-slate-500">Import CVs and add verified opportunities to calculate matches.</p>}
    </section>

    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 space-y-3">
      <div className="flex items-center gap-2"><FileText size={18} className="text-cyan-400"/><h2 className="font-semibold">4. Created Gmail drafts</h2></div>
      {drafts.length===0?<p className="text-sm text-slate-500">No drafts created yet.</p>:drafts.map(d=><div key={d.id} className="rounded-lg border border-slate-800 p-3 text-sm flex flex-wrap justify-between gap-2"><div><div className="font-medium">{d.name} · {d.email}</div><div className="text-slate-400">{d.platform} — {d.role_title}</div><div className="text-slate-500">{d.subject}</div></div><span className="text-emerald-400">Saved in Gmail · Not sent</span></div>)}
    </section>
    <p className="text-xs text-slate-500 flex items-start gap-2"><AlertCircle size={15}/>Email extraction is heuristic; review candidate identity and match evidence. Scanned PDFs require OCR. A CV email alone is not proof of consent. Never describe an opportunity referral as an official shortlist.</p>
  </div>;
};
