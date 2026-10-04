import { useEffect, useId, useMemo, useState } from 'react';
import { ArrowDownRight, ArrowRight, ArrowUpRight, CalendarDays, CheckCircle2, CircleHelp, Clock3, Download, GitCompareArrows, Layers3, Play, Plus, RefreshCw, ShieldCheck, Sparkles, Users2 } from 'lucide-react';
import { api, type Bootstrap, type RecordData, rows, formatNumber, dateTime, downloadJson, statusLabel, localDateTime, warsawUtc } from './api';
import { AuthGate, Badge, Button, CardTitle, Empty, Field, Loading, Notice, PageHeading, Status } from './ui';
import CityMap from './CityMap';
import AnalysisControls from './AnalysisControls';
import CatalogEditor from './CatalogEditor';
import ResultsDetails from './ResultsDetails';
import ComparisonMaps,{RelationSnapshot} from './ComparisonMaps';

export function metric(value: RecordData | undefined, key: string): number | undefined {
  const aliases: Record<string,string[]> = {
    available:['available_relation_hours','accessible_relation_hours','availability_hours','A'],
    lost:['unavailable_relation_hours','blocked_relation_hours','lost_relation_hours'],
    unknown:['unknown_relation_hours','uncertain_relation_hours'],
    recovered:['recovered_relation_hours','gain_relation_hours','gained_relation_hours'],
    longest:['longest_interruption_hours','longest_gap_hours','max_outage_hours'],
    count:['relation_count','total_relations','denominator'],
  };
  for (const name of aliases[key] || [key]) { const result = value?.[name] ?? value?.metrics?.[name] ?? value?.evaluation?.[name]; if (typeof result === 'number') return result; }
  return undefined;
}
export function variantsOf(evaluation: RecordData | null): RecordData[] { return rows(evaluation?.variants || evaluation?.results).map(v => ({...v,...(v.evaluation || {})})); }
export function Timeline({graph, variant, selected, onSelect,horizon:analysisHorizon}: {graph: RecordData; variant?: RecordData; selected?: string; onSelect?: (value: string) => void;horizon?:RecordData}) {
  const horizon = analysisHorizon || graph.horizon || {};
  const start = new Date(horizon.start).valueOf(), end = new Date(horizon.end).valueOf();
  const total = end-start;
  const works = rows(variant?.works || variant?.restrictions || variant?.schedule || graph.works);
  const [selectedWork,setSelectedWork] = useState('');
  const selectedTimeId=useId();
  const left = (value: string) => Math.max(0,Math.min(100,(new Date(value).valueOf()-start)/total*100));
  if (!Number.isFinite(total) || total <= 0) return <Empty title="Brak wspólnego horyzontu"/>;
  return <div className="timeline">
    <div className="timeline-ticks"><span className="timeline-row-label">{dateTime(horizon.start).split(',')[0]}</span><div>{[0,.16,.32,.48,.64,.8,1].map(n => <span key={n} style={{left:`${n*100}%`}}>{dateTime(new Date(start+total*n).toISOString(),false)}</span>)}</div></div>
    {works.map((work,i) => <div className="timeline-row" key={work.id || i}><div className="timeline-row-label"><span className={`work-letter ${i % 2 ? 'yellow' : 'purple'}`}>{work.id || String.fromCharCode(88+i)}</span><span>{work.name || 'Ograniczenie'}<small>{dateTime(work.start,false)} do {dateTime(work.end,false)}</small></span></div><div className="timeline-track"><button className={`timeline-bar ${i%2 ? 'yellow':'purple'} ${selectedWork === work.id ? 'selected':''}`} style={{left:`${left(work.start)}%`,width:`${Math.max(1,left(work.end)-left(work.start))}%`}} aria-label={`${work.name}: ${dateTime(work.start,false)} do ${dateTime(work.end,false)}`} onClick={() => {setSelectedWork(work.id);onSelect?.(work.start);}}>{Number(work.duration_s)/3600 || formatNumber((new Date(work.end).valueOf()-new Date(work.start).valueOf())/3600000)} h prac</button></div></div>)}
    {selected && <div className="timeline-scrub"><span id={selectedTimeId} className="small">Mapa o <strong>{dateTime(selected,false)}</strong></span><input aria-label="Godzina widoku mapy" aria-valuetext={dateTime(selected,false)} aria-describedby={selectedTimeId} type="range" min="0" max={total/60000} step="5" value={(new Date(selected).valueOf()-start)/60000} onChange={e => onSelect?.(new Date(start+Number(e.target.value)*60000).toISOString())}/></div>}
    <div className="timeline-note"><Clock3 size={15}/><span>Stałe okno rozpoczęcia: {dateTime(horizon.start,false)} do {dateTime(horizon.end,false)}. Dane muszą pokrywać także ostatnią rozpoczętą podróż.</span></div>
  </div>;
}

export function Overview({data,evaluation,busy,onEvaluate,onCompare,onResident,onAsset}: {data: Bootstrap;evaluation: RecordData | null;busy: boolean;onEvaluate:()=>void;onCompare:()=>void;onResident:()=>void;onAsset:(id:string)=>void}) {
  const [selectedTime,setSelectedTime] = useState(data.graph.clock);
  const baseline = evaluation?.baseline;
  const horizon=evaluation?.horizon||data.graph.horizon;
  const mapGraph=useMemo(()=>({...data.graph,restrictions:baseline?.restrictions||data.graph.restrictions}),[data.graph,baseline?.restrictions]);
  useEffect(()=>{if(new Date(selectedTime).valueOf()<new Date(horizon?.start).valueOf()||new Date(selectedTime).valueOf()>new Date(horizon?.end).valueOf())setSelectedTime(horizon.start);},[horizon?.start,horizon?.end,selectedTime]);

  const variants = variantsOf(evaluation);
  const recommended = variants.find(v => v.id === 'safe' || v.variant_id === 'safe') || variants.find(v => (metric(v,'recovered') || 0) > 0);
  const works = rows(data.graph.works);
  return <>
    <PageHeading eyebrow={data.layer==='fixture'?'KOORDYNACJA ROBÓT':'KOORDYNACJA ROBÓT · OPUBLIKOWANY OBSZAR'} title="Sprawdź, czy remont odetnie dojście." description="Wykryj konflikt zamknięć. Porównaj terminy prac i zachowaj mieszkańcom dojście do celu." action={<Button kind="secondary" onClick={onResident}><FootprintsIcon/>Moje dojście<ArrowRight size={16}/></Button>}/>
    <div className="metrics-grid">
      <div className="metric-card"><div className="metric-top"><span>Utrata dojścia w obecnym planie</span><Clock3 size={19}/></div><div className="metric-value">{baseline ? formatNumber(metric(baseline,'lost')) : '…'}<span>h relacji</span></div><div className="metric-bottom"><Badge tone="red">{baseline ? 'Całe okno podróży' : 'Oczekuje na obliczenie'}</Badge><span>start · potrzeby · cel</span></div></div>
      <div className="metric-card"><div className="metric-top"><span>Do odzyskania po zmianie planu</span><ArrowUpRight size={20}/></div><div className="metric-value green-text">{recommended ? `+${formatNumber(metric(recommended,'recovered'))}` : '…'}<span>h relacji</span></div><div className="metric-bottom"><Badge tone="purple">Prognoza warunkowa</Badge><span>ten sam horyzont</span></div></div>
      <div className="metric-card compact-metric"><div className="metric-top"><span>Dojścia objęte analizą</span><Users2 size={19}/></div><div className="metric-value">{rows(data.graph.origins).length}<span>punkty startowe</span></div><div className="metric-bottom"><span>{rows(data.graph.places).length} cel · profil edytowalny · 30 min w przykładzie</span></div></div>
    </div>
    <details className="evidence-details relation-hours-definition"><summary>Co oznacza „h relacji”?<ChevronDownIcon/></summary><p className="small">Relacja to start, profil i cel. Przykład utraty w DEMO: <strong>2 relacje po 4,5 godziny dają 9 godzin relacji.</strong> To suma dla obu relacji, nie długość jednej przerwy. Każde wyjście sprawdzamy w całym oknie podróży (30 minut w DEMO).</p></details>
    <div className="overview-grid">
      <section className="card map-card"><div className="map-card-head"><div><span className="eyebrow">WSPÓLNY OBSZAR OCENY</span><h2>{data.layer==='fixture'?'Dwa dojścia do jednego celu':'Sieć dojść i objęte nią usługi'}</h2></div><Badge tone={data.layer==='fixture'?'purple':'amber'}>{data.layer==='fixture'?'DEMO':'Obserwacje'}</Badge></div><CityMap graph={mapGraph} selectedTime={selectedTime} onSelectAsset={onAsset}/><div className="map-card-footer"><span className="dot green"/>Sprawdź oba dojścia i miejsca zamknięć<span className="map-footer-count">{rows(data.graph.edges).length} połączeń w sieci</span></div></section>
      <section className="card conflict-card"><CardTitle eyebrow="UWAGA NA NAKŁADANIE" title={data.layer==='fixture'?'Dwa zamknięcia. Oba dojścia odcięte.':'Sprawdź wspólny wpływ ograniczeń.'}/><p className="muted">Każda robota osobno zostawia obejście. Gdy trwają razem, znika także druga droga do celu.</p><div className="works-list">{works.map((work,i) => <div className="work-summary" key={work.id}><span className={`work-letter ${i%2?'yellow':'purple'}`}>{work.id}</span><div><strong>{work.name}</strong><p>{dateTime(work.start,false)} do {dateTime(work.end,false)} · {dateTime(work.start).split(',')[0]}</p></div></div>)}</div>
        {baseline ? <div className="conflict-insight"><span className="insight-label">WYNIK ANALIZY</span><strong>{formatNumber(metric(baseline,'lost'))} h relacji bez potwierdzonego dojścia</strong><p>Sprawdzamy także zamknięcia, które zaczną się po wyjściu mieszkańca.</p></div> : <Empty title="Sprawdź wspólny wpływ robót" action={<Button onClick={onEvaluate} busy={busy}><Play size={16}/>Oblicz konflikt</Button>}/>}
        <Button onClick={onCompare} className="full">Porównaj warianty<ArrowRight size={17}/></Button>
      </section>
    </div>
    <section className="card timeline-card"><CardTitle eyebrow="HARMONOGRAM ZAMKNIĘĆ" title="Kiedy dojście wymaga uwagi?" action={<Badge><CalendarDays size={13}/>{dateTime(horizon?.start).split(',')[0]} · Warszawa</Badge>}/><Timeline graph={data.graph} horizon={horizon} selected={selectedTime} onSelect={setSelectedTime}/></section><RelationSnapshot graph={data.graph} evaluation={baseline} time={selectedTime}/>
    <div className="bottom-grid"><section className="card compact-card"><span className="feature-icon green"><ShieldCheck size={23}/></span><div><h3>Potwierdź otwarcie obejścia</h3><p>Zapisz plan, a po wykonaniu prac sprawdź przejście w terenie.</p></div></section><section className="card compact-card"><span className="feature-icon purple"><Layers3 size={23}/></span><div><h3>Znajdź wspólny punkt awarii</h3><p>Sprawdź, czy różne trasy zależą od tej samej windy lub przejścia.</p></div></section><section className="card compact-card"><span className="feature-icon amber"><CircleHelp size={23}/></span><div><h3>Skieruj kontrolę tam, gdzie trzeba</h3><p>Wskaż brakujący pomiar, który rozstrzygnie, czy można przejść.</p></div></section></div>
  </>;
}
function FootprintsIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" width="17" height="17" aria-hidden="true"><path d="m8 3 3 2-1 7-4-1 1-6zM14 12l4 1 1 7-3 1-3-5zM6 14l4 1-1 4-4-1z"/></svg>; }

export function Comparison({data,evaluation,busy,onEvaluate,onRefresh,onLogin}: {data:Bootstrap;evaluation:RecordData|null;busy:boolean;onEvaluate:(request?:RecordData)=>void;onRefresh:()=>Promise<void>;onLogin:()=>void}) {
  const variants = variantsOf(evaluation);
  const [selected,setSelected] = useState('safe');
  const chosen = variants.find(v => (v.id || v.variant_id) === selected) || variants[0];
  const [name,setName] = useState('Przekazanie obejścia z 30 minutami wspólnej drożności');
  const [owner,setOwner] = useState('');
  const [executor,setExecutor] = useState('');const [due,setDue]=useState(localDateTime(data.graph.horizon?.end));
  const [conditions,setConditions] = useState('Potwierdzone otwarcie pierwszego dojścia oraz 30 minut wspólnej drożności przed zamknięciem drugiego.');
  const [saving,setSaving] = useState(false), [error,setError] = useState(''), [message,setMessage] = useState('');
  const [job,setJob] = useState<RecordData|null>(null), [effects,setEffects] = useState<RecordData|null>(null);
  const [activeScenario,setActiveScenario] = useState<RecordData|null>(null);const [decisionVariant,setDecisionVariant]=useState('');const decisionVariants=rows(activeScenario?.latest_result?.variants);const approvedVariantId=decisionVariants.find(v=>v.id===decisionVariant)?.id||activeScenario?.latest_result?.recommended_id||decisionVariants[0]?.id;
  const [evidenceIds,setEvidenceIds] = useState('');
  const baseline = evaluation?.baseline;
  useEffect(()=>{if(activeScenario){const fresh=data.scenarios.find(s=>s.id===activeScenario.id);if(fresh&&fresh.version!==activeScenario.version)setActiveScenario(fresh);}},[data.scenarios,activeScenario]);

  useEffect(() => {
    if (!job?.id && !job?.job_id) return;
    if (['completed','succeeded','failed','stale'].includes(job.status)) return;
    let stopped=false,inFlight=false;const poll=()=>{if(inFlight||stopped)return;inFlight=true;void api(`/jobs/${job.id || job.job_id}`).then(j => {if(stopped)return;setJob(j);if(['completed','succeeded'].includes(j.status)) {setMessage('Wariant oceniony. Możesz zapisać decyzję.');void onRefresh();}}).catch(e => {if(!stopped)setError(e.message);}).finally(()=>{inFlight=false;});};const event=(value:Event)=>{const update=(value as CustomEvent).detail;if((update.id||update.job_id)===(job.id||job.job_id))poll();};const handle=window.setInterval(poll,1000);window.addEventListener('mbod-job-progress',event);window.addEventListener('mbod-stream-connected',poll);
    return () => {stopped=true;clearInterval(handle);window.removeEventListener('mbod-job-progress',event);window.removeEventListener('mbod-stream-connected',poll);};
  },[job?.id,job?.job_id,job?.status,onRefresh]);

  const saveScenario = async () => {
    setSaving(true);setError('');setMessage('');
    try {
      const scenario = await api('/scenarios',{name,layer:data.layer,request:{variants:chosen?[chosen]:[],origins:evaluation?.snapshot?.origins||rows(data.graph.origins).map(o=>o.id),profiles:evaluation?.snapshot?.profiles||[rows(data.graph.profiles)[0]?.id],destinations:evaluation?.snapshot?.destinations||rows(data.graph.places).map(p=>p.id),horizon:evaluation?.horizon||data.graph.horizon}});
      setActiveScenario(scenario);
      const result = await api(`/scenarios/${scenario.id}/evaluate`,{expected_version:scenario.version});setJob(result);
      setMessage('Scenariusz zapisany. Trwa porównanie dojść.');await onRefresh();
    } catch(e) {setError((e as Error).message);} finally {setSaving(false);}
  };
  const decision = async (status:string, scenario:RecordData) => {
    setSaving(true);setError('');setMessage('');
    try {
      const updated = await api(`/scenarios/${scenario.id}/decision`,{expected_version:scenario.version,status,owner,executor,conditions,due_at:due?warsawUtc(due):undefined,variant_id:status==='approved_plan'?approvedVariantId:scenario.decision?.variant_id,evidence_ids:evidenceIds.split(',').map(s=>s.trim()).filter(Boolean)});
      setActiveScenario(updated);setMessage(`Zapisano: ${statusLabel(status)}. Otwarcie przejścia potwierdza osobna obserwacja.`);await onRefresh();
    } catch(e) {setError((e as Error).message);} finally {setSaving(false);}
  };

  return <>
    <PageHeading eyebrow="DECYZJA KOORDYNATORA" title="Wybierz harmonogram, który zachowa dojście." description="Przesuń zamknięcia i sprawdź zysk dla każdego dojścia. Porównuj te same prace w tym samym okresie." action={<Button kind="secondary" onClick={onEvaluate} busy={busy}><RefreshCw size={16}/>Przelicz warianty</Button>}/>
    <AnalysisControls data={data} busy={busy} onEvaluate={onEvaluate}/>
    <CatalogEditor data={data} onRefresh={onRefresh}/>
    {!evaluation ? <section className="card"><Empty title="Rozpocznij porównanie" action={<Button onClick={onEvaluate} busy={busy}><Play size={16}/>Oblicz warianty</Button>}>Sprawdź, kiedy dojście będzie dostępne i które terminy prac warto zmienić.</Empty></section> : <>
      <div className="comparison-selector" aria-label="Porównywany wariant">{variants.map(v => <button key={v.id || v.variant_id} className={(v.id || v.variant_id) === (chosen?.id || chosen?.variant_id) ? 'active' : ''} onClick={() => setSelected(v.id || v.variant_id)}><GitCompareArrows size={17}/>{v.name || v.label || v.id || v.variant_id}</button>)}</div>
      <div className="comparison-grid"><section className="card comparison-card"><Badge>BAZA · HARMONOGRAM BEZ ZMIANY</Badge><h2>Roboty nakładają się w czasie</h2><div className="comparison-number">{formatNumber(metric(baseline,'available'))}<span>h dostępności relacji</span></div><Timeline graph={data.graph} horizon={evaluation.horizon}/><div className="comparison-submetric"><ArrowDownRight size={18}/><strong>{formatNumber(metric(baseline,'lost'))} h</strong> bez potwierdzonego dojścia</div></section>
        <section className="card comparison-card recommended"><Badge tone="purple">SYMULACJA · WYNIK WARUNKOWY</Badge><h2>{chosen?.name || chosen?.label || 'Wybrany wariant'}</h2><div className="comparison-number green-text">{formatNumber(metric(chosen,'available'))}<span>h dostępności relacji</span></div><Timeline graph={data.graph} variant={chosen} horizon={evaluation.horizon}/><div className="comparison-submetric green-text"><ArrowUpRight size={18}/><strong>{formatNumber(metric(chosen,'recovered'))} h</strong> odzyskanych relacji</div></section></div>
      <ComparisonMaps graph={data.graph} baseline={baseline} variant={chosen} horizon={evaluation.horizon||data.graph.horizon}/><ResultsDetails data={data} evaluation={evaluation} variant={chosen}/><section className="card"><CardTitle title="Co zmienia wybrany wariant?" action={<Badge tone="purple"><Sparkles size={13}/>Wynik symulacji</Badge>}/><div className="table-scroll"><table><thead><tr><th>Miara i jednostka</th><th>Plan bazowy</th><th>Wybrany wariant</th></tr></thead><tbody>
        <tr><th>Dostępność całych podróży · h relacji</th><td>{formatNumber(metric(baseline,'available'))}</td><td>{formatNumber(metric(chosen,'available'))}</td></tr>
        <tr><th>Brak potwierdzonego dojścia · h relacji</th><td>{formatNumber(metric(baseline,'lost'))}</td><td>{formatNumber(metric(chosen,'lost'))}</td></tr>
        <tr><th>Niewiadome · h relacji</th><td>{formatNumber(metric(baseline,'unknown'))}</td><td>{formatNumber(metric(chosen,'unknown'))}</td></tr>
        <tr><th>Najdłuższa przerwa · h</th><td>{formatNumber(metric(baseline,'longest'))}</td><td>{formatNumber(metric(chosen,'longest'))}</td></tr>
        <tr><th>Koszt i zgodność z budżetem</th><td>Nie ustalono</td><td>{chosen?.cost == null ? 'Koszt do ustalenia' : `${formatNumber(chosen.cost)} zł`}</td></tr>
      </tbody></table></div>
      <div className="comparison-explanation"><CheckCircle2 size={21}/><div><strong>{chosen?.critical_satisfied === false || chosen?.feasible === false ? 'Wariant nie zachowuje wszystkich wymaganych dojść' : 'Sprawdź warunki przed decyzją'}</strong><p>{chosen?.explanation || chosen?.reason || 'Otwarcie pierwszego dojścia musi być potwierdzone przed zamknięciem drugiego. Pozytywny wynik obowiązuje przy wskazanych założeniach.'}</p></div></div>
      <details className="evidence-details"><summary>Założenia, grupy i zakres obliczeń<ChevronDownIcon/></summary><p>Stały mianownik: {metric(baseline,'count') ?? evaluation.relation_count ?? rows(data.graph.origins).length} relacje. Relacja to punkt startowy, profil i konkretny cel. Nie jest liczbą mieszkańców.</p><p>Miara chwilowa, diagnostycznie: {formatNumber(baseline?.instantaneous_lost_relation_hours ?? evaluation.instantaneous_lost_relation_hours)} h relacji bez połączenia. Nie zastępuje oceny całego okna podróży.</p>{(chosen?.assumptions || evaluation.assumptions || []).map((a: string | RecordData,i:number)=><p key={i}>• {typeof a === 'string' ? a : a.description || a.name}</p>)}<pre className="data-detail">{JSON.stringify({status:chosen?.solver_status || evaluation.solver_status,scope:evaluation.search_scope || chosen?.search_scope,groups:chosen?.per_profile || chosen?.by_profile || chosen?.relations,losses:chosen?.losses,unknowns:chosen?.unknowns},null,2)}</pre></details>
      <div className="row-actions"><Button kind="secondary" onClick={()=>downloadJson({notice:'SYMULACJA. Dane demonstracyjne, nie stan miasta.',...evaluation},'symulacja-porownanie.json')}><Download size={16}/>Eksport analizy JSON</Button></div></section>
    </>}
    <section className="card"><CardTitle eyebrow="OD PLANU DO POTWIERDZONEGO EFEKTU" title="Decyzja i odpowiedzialność"/>
      <AuthGate loggedIn={!!data.user} role={data.user?.role} onLogin={onLogin}>
        {error && <Notice tone="error">{error}</Notice>}{message && <Notice tone="success">{message}</Notice>}
        <div className="form-grid"><Field label="Nazwa scenariusza"><input value={name} onChange={e=>setName(e.target.value)} required/></Field><Field label="Osoba odpowiedzialna"><input placeholder="Imię, nazwisko lub rola w zespole" value={owner} onChange={e=>setOwner(e.target.value)}/></Field><Field label="Wykonawca"><input value={executor} onChange={e=>setExecutor(e.target.value)} placeholder="Osoba lub zespół wykonujący prace"/></Field><Field label="Termin wykonania · Warszawa"><input type="datetime-local" value={due} onChange={e=>setDue(e.target.value)}/></Field><Field label="Warunki realizacji"><textarea value={conditions} onChange={e=>setConditions(e.target.value)}/></Field></div>
        <Button onClick={()=>void saveScenario()} busy={saving} disabled={!evaluation || !name}><Plus size={16}/>Zapisz i oceń scenariusz</Button>
        {job && <div className="job-progress"><Status value={job.status || 'queued'}/><progress max="100" value={job.progress ?? (['completed','succeeded'].includes(job.status)?100:10)} aria-label="Postęp oceny scenariusza"/>{job.error && <Notice tone="error">{String(job.error)}</Notice>}</div>}
        {rows(data.scenarios).length > 0 && <div className="scenario-list">{rows(data.scenarios).map(s=><button className={`scenario-row ${activeScenario?.id === s.id?'active':''}`} key={s.id} onClick={()=>setActiveScenario(s)}><div><strong>{s.name}</strong><span>{dateTime(s.updated_at || s.created_at)}</span></div><Status value={s.status}/><ArrowRight size={17}/></button>)}</div>}
        {activeScenario && <div className="decision-panel"><h3>{activeScenario.name || 'Wybrany scenariusz'}</h3><div className="decision-stages">{['draft','evaluated','approved_plan','in_progress','performed','effect_reviewed'].map(s=><span key={s} className={activeScenario.status===s?'current':''}>{statusLabel(s)}</span>)}</div><Field label="Wariant zatwierdzany w tym scenariuszu"><select value={activeScenario.status==='evaluated'?approvedVariantId:activeScenario.decision?.variant_id||approvedVariantId} disabled={activeScenario.status!=='evaluated'} onChange={e=>setDecisionVariant(e.target.value)}>{decisionVariants.map(v=><option key={v.id} value={v.id}>{v.name||v.id} · {v.feasible&&v.critical_satisfied?'spełnia wymagania krytyczne':'sprawdź wykonalność'}</option>)}</select></Field><Field label="Dowody wykonania lub obserwacji" hint="Identyfikatory istniejących dowodów oddziel przecinkiem. Wykonanie nie wystarcza do potwierdzenia efektu."><input value={evidenceIds} onChange={e=>setEvidenceIds(e.target.value)} placeholder="np. identyfikator z kontroli terenowej"/></Field><div className="row-actions">
          <Button kind="secondary" disabled={!owner||activeScenario.status!=='evaluated'} busy={saving} onClick={()=>void decision('approved_plan',activeScenario)}>Zatwierdź plan</Button>
          <Button kind="secondary" disabled={!owner||activeScenario.status!=='approved_plan'} busy={saving} onClick={()=>void decision('in_progress',activeScenario)}>Rozpocznij realizację</Button>
          <Button kind="secondary" disabled={!owner || !executor || !evidenceIds.trim()||activeScenario.status!=='in_progress'} busy={saving} onClick={()=>void decision('performed',activeScenario)}>Zapisz wykonanie</Button>
          <Button kind="secondary" disabled={!['performed','effect_reviewed'].includes(activeScenario.status)} onClick={()=>{void api(`/scenarios/${activeScenario.id}/effects`).then(setEffects).catch(e=>setError(e.message));}}>Porównaj efekt</Button>
          <Button kind="secondary" disabled={!effects || !evidenceIds.trim()||activeScenario.status!=='performed'} busy={saving} onClick={()=>void decision('effect_reviewed',activeScenario)}>Zapisz ocenę efektu</Button>
        </div><div className="export-links">{['json','csv','geojson'].map(format=><a key={format} href={`/api/v1/exports/${activeScenario.id}?format=${format}`} download><Download size={14}/>{format.toUpperCase()}</a>)}</div></div>}
        {effects && <EffectReport effect={effects}/>}
      </AuthGate>
    </section>
  </>;
}
function ChevronDownIcon() { return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>; }
export function EffectReport({effect}:{effect:RecordData}) {
  const planned=effect.planned_variant||rows(effect.planned?.variants).find(v=>v.id===effect.selected_variant_id);
  const before=metric(effect.before,'available'),after=metric(effect.after,'available');
  return <section className="effect-report"><h3>Prognoza, obserwacja i pozostałe niewiadome</h3><div className="three-values"><div><span>Prognozowana poprawa</span><strong>{formatNumber(metric(planned,'recovered'))} h</strong></div><div><span>Zaobserwowana zmiana w modelu</span><strong>{before==null||after==null?'Niepotwierdzona':`${formatNumber(after-before)} h`}</strong></div><div><span>Sprzeczne lub wygasłe dowody</span><strong>{effect.unresolved?.length ?? 'Brak wyniku'}</strong></div></div><Notice tone="warning">{effect.attribution || 'Porównanie przed i po nie dowodzi przyczynowości. Wykonanie zadania nie zastępuje obserwacji.'}</Notice><p className="small">Niewiadome po wykonaniu: {formatNumber(metric(effect.after,'unknown'))} h relacji. {effect.simulated?'Obserwacja dotyczy demonstracji na grafie syntetycznym.':''}</p><pre className="data-detail">{JSON.stringify(effect,null,2)}</pre></section>;
}

export function Resilience({data}:{data:Bootstrap}) {
  const [impact,setImpact]=useState<RecordData|null>(null);
  const [result,setResult] = useState<RecordData|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const run = async () => {setBusy(true);setError('');try {const [failures,measurements]=await Promise.all([api('/analysis/failures',{profiles:[rows(data.graph.profiles)[0]?.id],layer:data.layer}),api('/analysis/verification-impact',{profiles:[rows(data.graph.profiles)[0]?.id],layer:data.layer})]);setResult(failures);setImpact(measurements);}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
  return <section className="card"><CardTitle title="Wspólna awaria i wpływ kontroli" action={<Button kind="secondary" onClick={()=>void run()} busy={busy}><ShieldCheck size={16}/>Sprawdź zależności</Button>}/><p className="muted">Wyłączenie obiektu obejmuje wszystkie zależne połączenia, także w obu kierunkach. Pomiar jest priorytetowy, jeśli może zmienić decyzję.</p>{error&&<Notice tone="error">{error}</Notice>}{busy&&<Loading>Przeliczanie awarii fizycznych obiektów…</Loading>}{result && <><div className="table-scroll"><table><thead><tr><th>Obiekt lub wspólna przyczyna</th><th>Utracone h relacji</th><th>Dotknięte relacje</th></tr></thead><tbody>{rows(result.failures || result.results || result).map((r,i)=><tr key={r.asset_id || r.failure_group_id || i}><th>{r.name || r.asset_id || r.failure_group_id}</th><td>{formatNumber(r.lost_relation_hours)}</td><td>{Array.isArray(r.affected_relations)?r.affected_relations.length:r.affected_relations ?? 'Nie podano'}</td></tr>)}</tbody></table></div>{impact&&<><h3>Kontrole, które mogą zmienić wynik</h3>{rows(impact.measurements).length?<div className="table-scroll"><table><thead><tr><th>Obiekt i cecha</th><th>Metoda i próg</th><th>Wynik dodatni / ujemny · h relacji</th></tr></thead><tbody>{rows(impact.measurements).map((m,i)=><tr key={i}><th>{m.asset_id} · {m.feature}</th><td>{m.measurement?.instruction}<br/>{m.measurement?.threshold} {m.measurement?.unit}</td><td>{formatNumber(m.positive_available_relation_hours)} / {formatNumber(m.negative_available_relation_hours)}</td></tr>)}</tbody></table></div>:<p className="small muted">W analizowanym horyzoncie nie znaleziono brakującej cechy wymagającej rozstrzygnięcia.</p>}<p className="small muted">{impact.notice}</p></>}<p className="small muted">Wynik dotyczy obiektów i zależności zapisanych w danych.</p></>}</section>;
}
