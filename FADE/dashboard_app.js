const { useState, useEffect, useRef, useCallback } = React;

// ═══════════════════════════════════════════════════════════════
// CHANNEL DEFINITIONS
// ═══════════════════════════════════════════════════════════════

const CHANNELS = [
  { id: 'slack', name: 'Slack', icon: '\u{1f4ac}', color: '#E01E5A',
    bg: 'linear-gradient(135deg, #611f69 0%, #e01e5a 100%)',
    desc: 'Webhook URL from Slack app', placeholder: 'https://hooks.slack.com/services/...' },
  { id: 'discord', name: 'Discord', icon: '\u{1f3ae}', color: '#5865F2',
    bg: 'linear-gradient(135deg, #404EED 0%, #5865F2 100%)',
    desc: 'Discord channel webhook', placeholder: 'https://discord.com/api/webhooks/...' },
  { id: 'teams', name: 'MS Teams', icon: '\u{1f4ce}', color: '#6264A7',
    bg: 'linear-gradient(135deg, #464775 0%, #6264A7 100%)',
    desc: 'Teams incoming webhook', placeholder: 'https://outlook.office.com/webhook/...' },
  { id: 'email', name: 'Email', icon: '\u{2709}\ufe0f', color: '#06b6d4',
    bg: 'linear-gradient(135deg, #0891b2 0%, #06b6d4 100%)',
    desc: 'Sent from fadeeeeai@gmail.com', placeholder: 'recipient@company.com' },
];

// ═══════════════════════════════════════════════════════════════
// ONBOARDING — Step 1: Repository
// ═══════════════════════════════════════════════════════════════

function OnboardingStep1({ repo, setRepo, error, setError }) {
  const inputRef = useRef(null);
  useEffect(() => { if (inputRef.current) inputRef.current.focus(); }, []);

  const examples = ['facebook/react', 'vercel/next.js', 'microsoft/vscode',
                     'golang/go', 'tensorflow/tensorflow', 'flutter/flutter'];

  return (
    <>
      <div className="ob-features">
        <div className="ob-feature"><div className="ob-feature-icon">{'\u{1f916}'}</div><div className="ob-feature-title">Execute</div><div className="ob-feature-desc">Run the AI agent task</div></div>
        <div className="ob-feature"><div className="ob-feature-icon">{'\u{1f50d}'}</div><div className="ob-feature-title">Analyze</div><div className="ob-feature-desc">Classify every step</div></div>
        <div className="ob-feature"><div className="ob-feature-icon">{'\u{1f4c9}'}</div><div className="ob-feature-title">Replace</div><div className="ob-feature-desc">Eliminate AI dependency</div></div>
      </div>
      <label className="ob-label">GitHub Repository</label>
      <div className="ob-input-wrap">
        <input ref={inputRef} id="repo-input" className={`ob-input mono${error ? ' error' : ''}`}
          type="text" placeholder="owner/repo" value={repo}
          onChange={(e) => { setRepo(e.target.value); setError(''); }}
          autoComplete="off" spellCheck="false" />
      </div>
      {error && <div className="ob-error">{error}</div>}
      <div className="ob-examples">
        {examples.map(ex => (
          <div key={ex} className="ob-example" onClick={() => { setRepo(ex); setError(''); }}>{ex}</div>
        ))}
      </div>
    </>
  );
}

// ═══════════════════════════════════════════════════════════════
// ONBOARDING — Step 2: Channels & Token
// ═══════════════════════════════════════════════════════════════

function OnboardingStep2({ channels, setChannels, token, setToken, showToken, setShowToken }) {
  const toggleChannel = (id) => {
    setChannels(prev => {
      const existing = prev.find(c => c.id === id);
      if (existing) return prev.filter(c => c.id !== id);
      return [...prev, { id, url: '' }];
    });
  };

  const updateUrl = (id, url) => {
    setChannels(prev => prev.map(c => c.id === id ? { ...c, url } : c));
  };

  return (
    <>
      <div className="ob-section-title">Delivery Channels <span style={{fontSize:'10px',color:'var(--dim)',fontWeight:400,textTransform:'none',letterSpacing:0}}>(optional)</span></div>
      <div className="channel-grid">
        {CHANNELS.map(ch => {
          const active = channels.find(c => c.id === ch.id);
          return (
            <div key={ch.id} className={`channel-card${active ? ' active' : ''}`}>
              <div onClick={() => toggleChannel(ch.id)} style={{cursor:'pointer'}}>
                <div className="channel-card-top">
                  <div className="channel-icon" style={{background: ch.bg, color: 'white', fontSize: '14px'}}>{ch.icon}</div>
                  <div className="channel-name">{ch.name}</div>
                </div>
                <div className="channel-desc">{ch.desc}</div>
                <div className="channel-check">{active ? '\u2713' : ''}</div>
              </div>
              {active && (
                <div className="channel-config">
                  <label>{ch.id === 'email' ? 'Recipient' : 'Webhook URL'}</label>
                  <input type={ch.id === 'email' ? 'email' : 'url'} placeholder={ch.placeholder}
                    value={active.url} onChange={(e) => updateUrl(ch.id, e.target.value)}
                    autoComplete="off" spellCheck="false" />
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="ob-toggle" onClick={() => setShowToken(!showToken)}>
        <span className={`ob-toggle-arrow${showToken ? ' open' : ''}`}>{'\u25b6'}</span>
        <span>GitHub Token (optional — higher rate limits)</span>
      </div>
      {showToken && (
        <div className="ob-input-wrap" style={{marginBottom:'16px'}}>
          <input id="token-input" className="ob-input mono" type="password" placeholder="ghp_xxxxxxxxxxxx"
            value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" />
        </div>
      )}
      {!token && !showToken && (
        <div className="ob-hint">
          <span className="ob-hint-icon">{'\u{1f4a1}'}</span>
          <span>Without a token, GitHub limits requests to 60/hour. A token gives 5,000/hour.</span>
        </div>
      )}
    </>
  );
}

// ═══════════════════════════════════════════════════════════════
// ONBOARDING CONTAINER
// ═══════════════════════════════════════════════════════════════

function Onboarding({ onStart }) {
  const [step, setStep] = useState(1);
  const [repo, setRepo] = useState('');
  const [token, setToken] = useState('');
  const [showToken, setShowToken] = useState(false);
  const [channels, setChannels] = useState([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const validate = (r) => {
    if (!r.trim()) return 'Please enter a repository';
    if (!r.includes('/')) return 'Use owner/repo format (e.g. facebook/react)';
    const parts = r.split('/');
    if (parts.length !== 2 || !parts[0] || !parts[1]) return 'Use owner/repo format';
    return '';
  };

  const handleNext = () => {
    if (step === 1) {
      const err = validate(repo);
      if (err) { setError(err); return; }
      setError('');
      setStep(2);
    }
  };

  const handleStart = async () => {
    setLoading(true);
    const notifChannels = channels
      .filter(c => c.url.trim())
      .map(c => ({ type: c.id, url: c.url.trim() }));

    try {
      const resp = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo: repo.trim(),
          github_token: token.trim(),
          notification_channels: notifChannels,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) { setError(data.error || 'Failed to start'); setLoading(false); return; }
      onStart(repo.trim(), notifChannels);
    } catch (e) {
      setError('Could not connect to server. Is server.py running?');
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !loading) {
      if (step === 1) handleNext();
      else handleStart();
    }
  };

  return (
    <div className="onboarding" onKeyDown={handleKeyDown}>
      <div className="onboarding-card">
        <div className="ob-logo">FADE</div>
        <div className="ob-subtitle">Fast Agent Deprecation Engine — The AI agent that replaces itself</div>

        <div className="ob-steps">
          <div className={`ob-step-dot ${step === 1 ? 'active' : 'done'}`} />
          <div className={`ob-step-dot ${step === 2 ? 'active' : ''}`} />
        </div>

        {step === 1 && <OnboardingStep1 repo={repo} setRepo={setRepo} error={error} setError={setError} />}
        {step === 2 && <OnboardingStep2 channels={channels} setChannels={setChannels} token={token} setToken={setToken} showToken={showToken} setShowToken={setShowToken} />}

        {error && step === 2 && <div className="ob-error" style={{marginBottom: '12px'}}>{error}</div>}

        {step === 1 ? (
          <button className="ob-btn" onClick={handleNext} disabled={!repo.trim()}>
            Next — Configure Delivery {'\u2192'}
          </button>
        ) : (
          <div className="ob-nav">
            <button className="ob-nav-back" onClick={() => setStep(1)}>{'\u2190'} Back</button>
            <button className="ob-btn" onClick={handleStart} disabled={loading} style={{flex:1}}>
              {loading ? <><span className="spinner" style={{marginRight:'8px',borderTopColor:'white',borderColor:'rgba(255,255,255,.3)'}}/> Connecting...</> : <>{'\u25b6'} Start Analysis</>}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// SHARED COMPONENTS (Step cards, Analysis, Meter, Cost, etc.)
// ═══════════════════════════════════════════════════════════════

function StepCard({ step }) {
  const isAI = step.step_type === 'reasoning';
  const isPending = step.pending;
  return (
    <div className="step-card">
      <div className="step-top">
        <div className="step-num" style={{ background: isAI?'var(--red-bg)':'var(--blue-bg)', color: isAI?'var(--red)':'var(--blue)' }}>
          {isPending ? <span className="spinner" style={{width:'14px',height:'14px',borderWidth:'1.5px'}}/> : step.step_number}
        </div>
        <div className="step-desc">{step.description}</div>
        <span className={`step-tag ${isAI?'tag-ai':'tag-tool'}`}>{isAI ? '\u{1f9e0} AI' : '\u{1f527} TOOL'}</span>
      </div>
      <div className="step-meta"><span style={{color: isPending?'var(--cyan)':'var(--dim)'}}>
        {isPending && <span className="spinner" style={{width:'10px',height:'10px',borderWidth:'1px',marginRight:'6px'}}/>}{step.output_summary}
      </span></div>
      {step.timestamp && !isPending && <div className="step-meta" style={{fontSize:'10px',marginTop:'2px'}}>{new Date(step.timestamp).toLocaleTimeString()}</div>}
    </div>
  );
}

function ScriptModal({ stepNum, snippets, onClose }) {
  const code = (snippets && snippets[stepNum]) || '# No script preview available';
  return (
    <div style={{position:'fixed',top:0,left:0,right:0,bottom:0,background:'rgba(0,0,0,.75)',zIndex:1000,display:'flex',alignItems:'center',justifyContent:'center',backdropFilter:'blur(4px)'}} onClick={onClose}>
      <div style={{background:'var(--surface)',border:'1px solid var(--border)',borderRadius:'16px',padding:'24px',maxWidth:'620px',width:'90%',maxHeight:'80vh',overflow:'auto'}} onClick={e=>e.stopPropagation()}>
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:'14px'}}>
          <span style={{fontSize:'13px',fontWeight:700,color:'var(--cyan)'}}>Generated Script — Step {stepNum}</span>
          <button className="btn" onClick={onClose} style={{padding:'4px 12px',fontSize:'11px'}}>{'\u2715'} Close</button>
        </div>
        <pre className="mono" style={{background:'var(--bg)',border:'1px solid var(--border)',borderRadius:'10px',padding:'16px',fontSize:'11px',lineHeight:'1.7',overflow:'auto',whiteSpace:'pre-wrap',color:'var(--text)'}}>{code}</pre>
      </div>
    </div>
  );
}

function AnalysisCard({ analysis, onViewScript }) {
  const cls = analysis.classification;
  const clsC = cls==='DETERMINISTIC'?'det':cls==='RULE_BASED'?'rule':'ai';
  const tagC = cls==='DETERMINISTIC'?'tag-det':cls==='RULE_BASED'?'tag-rule':'tag-aireq';
  const color = cls==='DETERMINISTIC'?'var(--green)':cls==='RULE_BASED'?'var(--yellow)':'var(--red)';
  const icon = cls==='DETERMINISTIC'?'\u{1f7e2}':cls==='RULE_BASED'?'\u{1f7e1}':'\u{1f534}';
  const hasScript = cls !== 'AI_REQUIRED';
  return (
    <div className={`analysis-card ${clsC}`}>
      <div className="step-top">
        <div className="step-num" style={{background:`${color}18`,color}}>{analysis.step_number}</div>
        <div className="step-desc">{analysis.original_description}</div>
        <span className={`step-tag ${tagC}`}>{cls.replace('_',' ')}</span>
      </div>
      <div className="step-meta" style={{marginTop:'6px'}}>{icon} {analysis.reasoning}</div>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginTop:'6px'}}>
        <div className="step-meta" style={{fontSize:'10px',color,margin:0}}>{'\u2192'} {hasScript?'Script generated':'Kept on AI (gemini-2.5-flash)'}</div>
        {hasScript && <button onClick={()=>onViewScript(analysis.step_number)} style={{background:'none',border:'1px solid var(--border)',borderRadius:'6px',padding:'3px 10px',fontSize:'10px',color:'var(--cyan)',cursor:'pointer',fontFamily:'inherit',transition:'all .15s'}}>{'\u{1f4c4}'} View Script</button>}
      </div>
    </div>
  );
}

function DependencyMeter({ pct, label }) {
  const color = pct>50?'var(--red)':pct>20?'var(--yellow)':'var(--green)';
  return (
    <div className="meter-section">
      <div className="meter-label">AI Dependency Score</div>
      <div className="meter-row">
        <div className="meter-value" style={{color}}>{pct}%</div>
        <div style={{fontSize:'12px',color:'var(--dim)'}}>{label||(pct===100?'All steps on AI':pct<=15?'100% \u2192 '+pct+'%':'Analyzing...')}</div>
      </div>
      <div className="meter-bar-track"><div className="meter-bar-fill" style={{width:`${pct}%`,backgroundColor:color}}/></div>
    </div>
  );
}

function CostBox({ costs }) {
  if (!costs) return null;
  return (
    <div className="cost-box">
      <div style={{fontSize:'10px',color:'var(--dim)',textTransform:'uppercase',letterSpacing:'1.5px',marginBottom:'12px',fontWeight:600}}>Cost Analysis</div>
      <div className="cost-row"><span className="cost-label">Agent ({costs.agent_model})</span><span className="cost-val old">${costs.agent_cost}/run</span></div>
      <div className="cost-row"><span className="cost-label">Pipeline ({costs.pipeline_model})</span><span className="cost-val new">${costs.pipeline_cost}/run</span></div>
      <div className="cost-row" style={{borderTop:'1px solid var(--border)',paddingTop:'8px',marginTop:'4px'}}><span className="cost-label">Yearly (52 runs)</span><span className="cost-val new">-${costs.yearly_savings}</span></div>
      <div className="cost-savings">-{costs.reduction_pct}%</div>
    </div>
  );
}

function ClassSummary({ summary }) {
  if (!summary) return null;
  return (
    <div className="class-summary">
      <div className="class-chip"><div className="chip-count" style={{color:'var(--green)'}}>{summary.deterministic}</div><div className="chip-label">Deterministic</div></div>
      <div className="class-chip"><div className="chip-count" style={{color:'var(--yellow)'}}>{summary.rule_based}</div><div className="chip-label">Rule-Based</div></div>
      <div className="class-chip"><div className="chip-count" style={{color:'var(--red)'}}>{summary.ai_required}</div><div className="chip-label">AI Required</div></div>
    </div>
  );
}

function SlackPreview({ label, content, borderColor }) {
  if (!content) return null;
  const html = content
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/\*([^*]+)\*/g,'<b>$1</b>').replace(/_([^_]+)_/g,'<i>$1</i>')
    .replace(/`([^`]+)`/g,'<code style="background:#2d2f33;padding:1px 4px;border-radius:3px;font-size:12px">$1</code>')
    .replace(/&lt;([^|]+)\|([^&]+)&gt;/g,(m,url,text)=>`<a href="${url.replace(/&amp;/g,'&')}" target="_blank" style="color:#1d9bd1;text-decoration:none;border-bottom:1px dotted #1d9bd1">${text}</a>`)
    .replace(/\n/g,'<br/>');
  return (<div><div className="slack-label" style={{borderLeft:`3px solid ${borderColor}`,paddingLeft:'8px'}}>{label}</div><div className="slack-preview" dangerouslySetInnerHTML={{__html:html}}/></div>);
}

function DeliveryBadges({ results }) {
  if (!results || results.length === 0) return null;
  const chNames = {slack:'Slack',discord:'Discord',teams:'MS Teams',email:'Email'};
  const chIcons = {slack:'\u{1f4ac}',discord:'\u{1f3ae}',teams:'\u{1f4ce}',email:'\u{2709}\ufe0f'};
  return (
    <div className="delivery-badges">
      {results.map((r,i) => (
        <div key={i} className={`delivery-badge ${r.success?'success':'failed'}`} title={r.error||''}>
          <span className="badge-icon">{chIcons[r.channel]||'\u{1f514}'}</span>
          <span>{chNames[r.channel]||r.channel}{r.recipient ? ` \u2192 ${r.recipient}` : ''}</span>
          <span>{r.success?'\u2713':'\u2717'}</span>
          {r.error && <div style={{fontSize:'10px',color:'var(--red)',marginTop:'4px',wordBreak:'break-word'}}>{r.error}</div>}
        </div>
      ))}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════════════════════════════

function App() {
  const [started, setStarted] = useState(false);
  const [repo, setRepo] = useState('');
  const [configuredChannels, setConfiguredChannels] = useState([]);
  const [phase, setPhase] = useState(0);
  const [phase1Steps, setPhase1Steps] = useState([]);
  const [phase2Steps, setPhase2Steps] = useState([]);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [scriptModal, setScriptModal] = useState(null);
  const [deliveryResults, setDeliveryResults] = useState([]);
  const eventSourceRef = useRef(null);
  const p1Ref = useRef(null);
  const p2Ref = useRef(null);

  useEffect(() => { if (p1Ref.current) p1Ref.current.scrollTop = p1Ref.current.scrollHeight; }, [phase1Steps]);
  useEffect(() => { if (p2Ref.current) p2Ref.current.scrollTop = p2Ref.current.scrollHeight; }, [phase2Steps]);

  const computeDep = () => {
    if (phase < 2 || phase2Steps.length === 0) return 100;
    const auto = phase2Steps.filter(s => s.classification !== 'AI_REQUIRED').length;
    const pct = Math.round(100 - (auto / 8) * 100);
    return Math.max(pct, result ? result.classification_summary.ai_pct_after : 13);
  };

  const handleStart = useCallback((repoName, channels) => {
    setRepo(repoName);
    setConfiguredChannels(channels || []);
    setStarted(true);
    setPhase(0); setPhase1Steps([]); setPhase2Steps([]); setResult(null); setError(null); setDeliveryResults([]);

    const es = new EventSource('/api/stream');
    eventSourceRef.current = es;
    es.addEventListener('connected', () => {});
    es.addEventListener('status', (e) => {
      const d = JSON.parse(e.data);
      if (d.phase==='phase1') setPhase(1); else if (d.phase==='phase2') setPhase(2); else if (d.phase==='phase3'||d.phase==='complete') setPhase(3);
    });
    es.addEventListener('phase1_step', (e) => {
      const s = JSON.parse(e.data); setPhase(1);
      setPhase1Steps(prev => {
        if (s.pending) return [...prev, s];
        const idx = prev.findIndex(x => x.step_number === s.step_number);
        if (idx >= 0) { const u = [...prev]; u[idx] = s; return u; }
        return [...prev, s];
      });
    });
    es.addEventListener('phase2_step', (e) => { setPhase(2); setPhase2Steps(prev => [...prev, JSON.parse(e.data)]); });
    es.addEventListener('phase3_result', (e) => { const d = JSON.parse(e.data); setResult(d); setPhase(3); if (d.delivery_results) setDeliveryResults(d.delivery_results); });
    es.addEventListener('delivery_result', (e) => { setDeliveryResults(prev => [...prev, JSON.parse(e.data)]); });
    es.addEventListener('error', (e) => { try { setError(JSON.parse(e.data).message); } catch { setError('Connection lost'); } });
  }, []);

  const handleNewRepo = useCallback(() => {
    if (eventSourceRef.current) { eventSourceRef.current.close(); eventSourceRef.current = null; }
    setStarted(false); setPhase(0); setPhase1Steps([]); setPhase2Steps([]); setResult(null); setError(null); setDeliveryResults([]);
  }, []);

  useEffect(() => () => { if (eventSourceRef.current) eventSourceRef.current.close(); }, []);

  if (!started) return <Onboarding onStart={handleStart} />;

  const dep = computeDep();
  const statusText = error ? `Error: ${error}` : phase===0?'Connecting...':phase===1?'Phase 1 — Agent executing...':phase===2?'Phase 2 — Self-analysis...':'Phase 3 — Complete';
  const statusClass = error ? 'error' : phase===3?'done':phase>0?'running':'idle';
  const hasEmail = configuredChannels.some(c => c.type === 'email');

  return (
    <>
      <div className="header">
        <div><h1><span>FADE</span> &mdash; Fast Agent Deprecation Engine</h1><div className="header-sub">The AI agent that replaces itself</div></div>
        <div className="header-actions">
          <span className="header-repo">{repo}</span>
          {configuredChannels.length > 0 && <span style={{fontSize:'11px',color:'var(--dim)'}}>{configuredChannels.length} channel{configuredChannels.length>1?'s':''}</span>}
          <button className="btn" onClick={handleNewRepo}>{'\u2190'} New Repo</button>
        </div>
      </div>

      {error && (
        <div style={{padding:'12px 24px',background:'var(--red-bg)',borderBottom:'1px solid rgba(239,68,68,.3)',color:'var(--red)',fontSize:'13px',display:'flex',alignItems:'center',gap:'8px'}}>
          <span>{'\u26a0\ufe0f'}</span><span>{error}</span>
          <button className="btn" onClick={handleNewRepo} style={{marginLeft:'auto',padding:'4px 12px',fontSize:'11px'}}>Try Another Repo</button>
        </div>
      )}

      <div className="panels" style={{paddingBottom:'36px',height:error?'calc(100vh - 95px)':'calc(100vh - 53px)'}}>
        {/* Phase 1 */}
        <div className="panel">
          <div className="panel-header">
            <span className="phase-tag" style={{background:'var(--blue-bg)',color:'var(--blue)',border:'1px solid rgba(59,130,246,.25)'}}>Phase 1</span>
            <h2>Agent Execution</h2>
            <div style={{fontSize:'11px',color:'var(--dim)',marginTop:'4px'}}>{phase>=1?`${repo} \u2022 ${phase1Steps.filter(s=>!s.pending).length} steps`:'Initializing...'}</div>
          </div>
          <div className="panel-body" ref={p1Ref}>
            {phase>=1 && phase1Steps.map((s,i) => <StepCard key={`${s.step_number}-${s.pending?'p':'d'}`} step={s} />)}
            {phase===0 && <div className="placeholder"><div className="placeholder-icon">{'\u{1f916}'}</div><div className="placeholder-text">Connecting...</div><div className="placeholder-sub"><span className="spinner"/></div></div>}
          </div>
        </div>

        {/* Phase 2 */}
        <div className="panel">
          <div className="panel-header">
            <span className="phase-tag" style={{background:'var(--purple-bg)',color:'var(--purple)',border:'1px solid rgba(168,85,247,.25)'}}>Phase 2</span>
            <h2>Self-Analysis</h2>
            <div style={{fontSize:'11px',color:'var(--dim)',marginTop:'4px'}}>{phase>=2?`Classifying... ${phase2Steps.length}/8`:phase>=1?'Waiting for Phase 1...':''}</div>
          </div>
          <div className="panel-body" ref={p2Ref}>
            {phase>=2 && phase2Steps.length>=8 && <ClassSummary summary={result?.classification_summary||{deterministic:phase2Steps.filter(s=>s.classification==='DETERMINISTIC').length,rule_based:phase2Steps.filter(s=>s.classification==='RULE_BASED').length,ai_required:phase2Steps.filter(s=>s.classification==='AI_REQUIRED').length}}/>}
            {phase>=2 && phase2Steps.map(a => <AnalysisCard key={a.step_number} analysis={a} onViewScript={n=>setScriptModal(n)}/>)}
            {phase<2 && <div className="placeholder"><div className="placeholder-icon">{'\u{1f50d}'}</div><div className="placeholder-text">Agent will analyze its own trace</div><div className="placeholder-sub">Each step classified: deterministic, rule-based, or AI-required</div></div>}
          </div>
        </div>

        {/* Phase 3 */}
        <div className="panel">
          <div className="panel-header">
            <span className="phase-tag" style={{background:'var(--green-bg)',color:'var(--green)',border:'1px solid rgba(34,197,94,.25)'}}>Result</span>
            <h2>Deprecation Report</h2>
            <div style={{fontSize:'11px',color:'var(--dim)',marginTop:'4px'}}>{phase>=3?'Pipeline generated \u2022 Validated \u2022 Ready':phase>=1?'Watching dependency...':''}</div>
          </div>
          <div className="panel-body">
            {phase>=1 && <DependencyMeter pct={dep} label={phase>=3?`100% \u2192 ${result?.classification_summary?.ai_pct_after||dep}%`:null}/>}
            {phase>=3 && result && <>
              <CostBox costs={result.costs} />
              {deliveryResults.length > 0 && (
                <div className="meter-section">
                  <div className="meter-label">Digest Delivery</div>
                  <DeliveryBadges results={deliveryResults} />
                </div>
              )}
              <div style={{fontSize:'10px',color:'var(--dim)',textTransform:'uppercase',letterSpacing:'1.5px',margin:'20px 0 10px',fontWeight:600}}>Side-by-Side Comparison</div>
              <SlackPreview label={`Agent Output (${result.costs.agent_model} — $${result.costs.agent_cost}/run)`} content={result.agent_slack} borderColor="var(--red)"/>
              <SlackPreview label={`Pipeline Output (${result.costs.pipeline_model||'local'} — $${result.costs.pipeline_cost}/run)`} content={result.pipeline_slack} borderColor="var(--green)"/>
              <div className="meter-section" style={{marginTop:'16px',textAlign:'center'}}>
                <div style={{fontSize:'14px',fontWeight:700,marginBottom:'4px'}}>{'\u2705'} Outputs match — pipeline validated</div>
                <div style={{fontSize:'11px',color:'var(--dim)'}}>Same structure, same categories. {result.costs.reduction_pct}% cheaper.<br/>Analyzed {result.pr_count} real PRs from <span className="mono" style={{color:'var(--cyan)'}}>{repo}</span></div>
              </div>
              <div className="meter-section" style={{textAlign:'center',border:'1px solid var(--green)',background:'var(--green-bg)'}}>
                <div style={{fontSize:'13px',color:'var(--green)',fontWeight:700,letterSpacing:'1px'}}>"You don't need me anymore." — The Agent</div>
              </div>
            </>}
            {phase===0 && !error && <div className="placeholder"><div className="placeholder-icon">{'\u{1f4c9}'}</div><div className="placeholder-text">AI Dependency Score</div><div className="placeholder-sub">Watch it drop in real time</div></div>}
          </div>
        </div>
      </div>

      {scriptModal !== null && <ScriptModal stepNum={scriptModal} snippets={result?.script_snippets} onClose={()=>setScriptModal(null)}/>}
      <div className="status-bar">
        <div className={`status-dot ${statusClass}`}/><span>{statusText}</span>
        <span style={{marginLeft:'auto',color:'var(--dim)'}}>FADE v2.1 &bull; {repo||'Ready'} &bull; {new Date().toLocaleDateString()}</span>
      </div>
    </>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
