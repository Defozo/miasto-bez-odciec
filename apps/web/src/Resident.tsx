import { useState } from 'react';
import { ArrowRight, Check, ChevronDown, Clock3, Footprints, List, MapPin, Navigation2, RotateCw, Ruler, Send, SlidersHorizontal } from 'lucide-react';
import { api, type Bootstrap, type RecordData, rows, label, formatNumber, dateTime, localDateTime, warsawUtc, statusLabel } from './api';
import { Badge, Button, CardTitle, Empty, Field, Notice, PageHeading, Status } from './ui';
import CityMap from './CityMap';

export default function Resident({data, onReport}: {data: Bootstrap; onReport: (asset?: string) => void}) {
  const profiles = rows(data.graph.profiles), origins = rows(data.graph.origins), places = rows(data.graph.places);
  const [origin,setOrigin] = useState(origins[0]?.id || '');
  const [destination,setDestination] = useState(places[0]?.id || '');
  const [entrance,setEntrance] = useState('');
  const [profile,setProfile] = useState<RecordData>(profiles[0] || {});
  const [departure,setDeparture] = useState(localDateTime(data.graph.clock || '2026-10-03T07:00:00Z'));
  const [result,setResult] = useState<RecordData | null>(null);const [resultQuery,setResultQuery]=useState('');const inputSignature=JSON.stringify({origin,destination,entrance,profile,departure});
  const [busy,setBusy] = useState(false), [error,setError] = useState('');
  const parsedDeparture=(()=>{try{return {value:warsawUtc(departure),error:''};}catch(e){return {value:undefined,error:(e as Error).message};}})();
  const entrances = rows(data.graph.entrances).filter(e => e.place_id === destination);
  const field = (key: string, value: unknown) => setProfile(p => ({...p,[key]:value}));
  const query = async () => {
    setBusy(true);setError('');const submittedSignature=inputSignature;
    try { setResult(await api('/routes',{layer:data.layer,origin,destination:destination.startsWith('category:')?{category:destination.slice(9)}:entrance || destination,profile,departure:warsawUtc(departure)}));setResultQuery(submittedSignature); }
    catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  };
  const stale = !!result && (result.data_version !== data.data_version||resultQuery!==inputSignature);
  const positive = !stale && result && ['confirmed','confirmed_route'].includes(result.status);
  const possible = stale || result && ['possible','possible_route','uncertain'].includes(result.status);
  const headings: Record<string,string> = {confirmed:'Masz dojście potwierdzone w danych',confirmed_route:'Masz dojście potwierdzone w danych',possible:'To dojście wymaga jeszcze kontroli',possible_route:'To dojście wymaga jeszcze kontroli',blocked:'Znana bariera na dojściu',known_barrier:'Znana bariera na dojściu',limit_exceeded:'Dojście przekracza Twoje limity',no_connection:'Brak połączenia w tym modelu',no_path:'Brak połączenia w tym modelu',out_of_coverage:'Cel poza zakresem danych',incomplete:'Obliczenie pozostało nierozstrzygnięte'};
  return <>
    <PageHeading eyebrow="DLA MIESZKAŃCA" title="Dokąd chcesz dotrzeć?" description="Wybierz cel, godzinę i swoje potrzeby. Sprawdź dojście aż do właściwego wejścia."/>
    <div className="resident-grid">
      <section className="card route-form">
        <CardTitle title="Twoje dojście" eyebrow="KROK 1 · CEL I POTRZEBY"/>
        <form onSubmit={e => {e.preventDefault();void query();}}>
          <Field label="Skąd wyruszasz"><select value={origin} onChange={e => setOrigin(e.target.value)} required>{origins.map(o => <option key={o.id} value={o.id}>{label(o)}</option>)}</select></Field>
          <div className="route-connector"><span/><Footprints size={16}/><span/></div>
          <Field label="Cel dojścia"><select value={destination} onChange={e => {setDestination(e.target.value);setEntrance('');}} required>{places.map(p => <option key={p.id} value={p.id}>{label(p)}</option>)}{[...new Set(places.map(p=>p.category).filter(Boolean))].map(category=><option key={category} value={`category:${category}`}>Najbliższy cel kategorii: {category==='healthcare'?'opieka zdrowotna':category}</option>)}</select></Field>
          <Field label="Właściwe wejście"><select value={entrance} onChange={e => setEntrance(e.target.value)}><option value="">Dowolne zgodne wejście do wybranego celu</option>{entrances.map(e => <option key={e.id} value={e.id}>{label(e)} · poziom {e.level ?? '?'}</option>)}</select></Field>
          <Field label="Wyjście · czas w Warszawie"><input type="datetime-local" value={departure} onChange={e => setDeparture(e.target.value)} required/></Field>
          <Field label="Ustawienia początkowe"><select value={profile.id || ''} onChange={e => setProfile({...profiles.find(p => p.id === e.target.value)})}>{profiles.map(p => <option key={p.id} value={p.id}>{label(p)}</option>)}</select></Field>
          <details className="preferences"><summary><SlidersHorizontal size={17}/>Dostosuj wymagania<ChevronDown size={15}/></summary><div className="preferences-content">
            <p className="muted small">Dostosuj szerokość przejścia, krawężniki i dystans do swoich potrzeb.</p>
            <label className="check-label"><input type="checkbox" checked={!!profile.allow_steps} onChange={e => field('allow_steps',e.target.checked)}/>Dopuszczam schody</label>
            <div className="form-grid">
              <Field label="Min. szerokość (m)"><input type="number" min="0.1" max="10" step="0.05" value={profile.min_width_m ?? ''} onChange={e => field('min_width_m',Number(e.target.value))}/></Field>
              <Field label="Max. krawężnik (cm)"><input type="number" min="0" max="100" step="0.5" value={profile.max_kerb_cm ?? ''} onChange={e => field('max_kerb_cm',Number(e.target.value))}/></Field>
              <Field label="Pod górę, max. (%)"><input type="number" min="0" max="100" value={profile.max_uphill_pct ?? ''} onChange={e => field('max_uphill_pct',Number(e.target.value))}/></Field>
              <Field label="W dół, max. (%)"><input type="number" min="0" max="100" value={profile.max_downhill_pct ?? ''} onChange={e => field('max_downhill_pct',Number(e.target.value))}/></Field>
              <Field label="Max. odległość (m)"><input type="number" min="10" max="50000" step="10" value={profile.max_distance_m ?? ''} onChange={e => field('max_distance_m',Number(e.target.value))}/></Field>
              <Field label="Okno dojścia (min)"><input type="number" min="1" max="240" value={(profile.max_duration_s || 1800)/60} onChange={e => field('max_duration_s',Number(e.target.value)*60)}/></Field>
            </div>
            <fieldset className="surface-fieldset"><legend>Dopuszczalne nawierzchnie</legend>{[['asphalt','Asfalt'],['paving','Kostka'],['concrete','Beton'],['compacted','Utwardzona'],['gravel','Żwir']].map(([id,name]) => <label className="check-label" key={id}><input type="checkbox" checked={(profile.allowed_surfaces || []).includes(id)} onChange={e => field('allowed_surfaces',e.target.checked ? [...(profile.allowed_surfaces || []),id] : profile.allowed_surfaces.filter((s: string) => s !== id))}/>{name}</label>)}</fieldset>
          </div></details>
          <Button type="submit" busy={busy} className="full"><Navigation2 size={17}/>Sprawdź dojście<ArrowRight size={17}/></Button>
          <p className="privacy-note">Dokładny start i wymagania służą tylko do obliczenia. Nie zapisujemy historii Twoich podróży.</p>
        </form>
      </section>
      <div className="stack">
        {(error||parsedDeparture.error) && <Notice tone="error">{error||parsedDeparture.error}</Notice>}
        {stale && <Notice tone="warning">{result?.data_version!==data.data_version?'Pojawiła się nowa wersja danych. Ten wynik jest z poprzedniej wersji.':'Zmieniono cel, czas lub wymagania. Poprzedni wynik nie odpowiada bieżącym ustawieniom.'} <button className="text-button" onClick={() => void query()}>Sprawdź ponownie</button></Notice>}
        {result ? <section className={`card route-result ${positive ? 'positive' : possible ? 'uncertain' : 'blocked'}`} aria-live="polite">
          <div className="result-head"><span className="result-icon">{positive ? <Check size={24}/> : <MapPin size={24}/>}</span><div><Status value={stale?'needs_recheck':result.status}/><h2>{stale?'Sprawdź dojście z aktualnymi ustawieniami':headings[result.status] || statusLabel(result.status)}</h2></div></div>
          {result.distance_m != null && <div className="route-metrics"><span><Ruler size={18}/><strong>{formatNumber(result.distance_m,0)} m</strong> długość</span><span><Clock3 size={18}/><strong>{formatNumber(result.duration_s / 60)} min</strong> szacowany czas</span></div>}
          {result.window && <p className="small">Sprawdzone całe okno: <strong>{dateTime(result.window.start,false)} do {dateTime(result.window.end,false)}</strong>. Wyjście {dateTime(result.window.start)}.</p>}
          {(result.reasons || []).map((r: RecordData | string,i: number) => <p key={i} className="result-reason">{typeof r === 'string' ? r : r.message || r.code}</p>)}
          <div className="result-actions"><Button kind="secondary" onClick={() => void query()} busy={busy}><RotateCw size={15}/>Sprawdź ponownie</Button><Button kind="ghost" onClick={() => onReport()}><Send size={15}/>Zgłoś rozbieżność</Button></div>
        </section> : <div className="route-intro"><span className="route-intro-icon"><Navigation2 size={26}/></span><div><h2>Sprawdź całą drogę do wejścia</h2><p>Zobacz trasę, barierę albo miejsce wymagające kontroli. Wynik uwzględnia cały czas na dojście.</p></div></div>}
        <section className="card map-card"><CityMap graph={data.graph} route={stale?null:result} selectedTime={parsedDeparture.value} onSelectAsset={onReport}/></section>
        {result && <section className="card">
          <CardTitle title="Dojście krok po kroku" action={<List size={19}/>}/>
          {rows(result.steps).length ? <ol className="route-steps">{rows(result.steps).map((step,i) => <li key={step.edge_id || i}><span className="step-number">{i+1}</span><div><strong>{step.name || step.instruction || step.edge_id}</strong><p>{step.instruction && step.name ? step.instruction : `${formatNumber(step.length_m ?? step.distance_m,0)} m${step.duration_s != null ? ` · około ${formatNumber(step.duration_s /60)} min` : ''}`}</p></div></li>)}</ol> : <Empty title="Nie wyznaczono instrukcji dojścia">Zobacz przyczynę wyniku powyżej. Brak ścieżki w niepełnym modelu nie dowodzi odcięcia w terenie.</Empty>}
          <details className="evidence-details"><summary>Źródła i warunki wyniku <ChevronDown size={16}/></summary><p className="small">Potwierdzenie dotyczy cech wykazanych dowodami. Dojście do placówki nie potwierdza godzin jej pracy ani dostępności usług wewnątrz.</p>
            {rows(result.evidence).map((e,i) => <div className="evidence-row" key={e.id || i}><div><strong>{e.feature || e.property || e.id}</strong><p>{String(e.value ?? '')} {e.unit || ''} · {e.author || e.method}</p></div><span>do {dateTime(e.valid_until)}</span></div>)}
            {!!rows(result.unknowns).length && <Notice tone="warning">Nierozstrzygnięte warunki: {rows(result.unknowns).map(u => u.message || u.feature || u.code).join(', ')}</Notice>}
            <p className="small muted">Wersja danych: {result.data_version}. Konserwatywny model nie zakłada oczekiwania na otwarcie odcinka. Nie przewiduje niezgłoszonych awarii.</p>
          </details>
        </section>}
        <div className="context-note"><Badge tone={data.layer==='fixture'?'purple':'amber'}>{data.layer==='fixture'?'DEMO':'Obserwacje'}</Badge><p>{data.layer==='fixture'?'Przykładowe dojście.':'Wynik dotyczy wskazanego zakresu i czasu. Sprawdź źródła i warunki powyżej.'}</p></div>
      </div>
    </div>
  </>;
}
