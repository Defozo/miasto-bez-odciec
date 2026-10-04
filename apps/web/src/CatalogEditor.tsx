import ResultsDetails from './ResultsDetails';
import {useEffect, useRef, useState} from 'react';
import {Download, FileInput, Play, RotateCcw} from 'lucide-react';
import {api, type Bootstrap, type RecordData, downloadJson, formatNumber, rows} from './api';
import {Badge, Button, Field, Notice, Status} from './ui';

type Props = {data: Bootstrap; onRefresh: () => Promise<void>; onEvaluated?: (result: RecordData) => void};
const terminal = new Set(['completed', 'succeeded', 'failed', 'stale']);
const requestKeys = new Set(['catalog', 'solver', 'origins', 'profiles', 'destinations', 'horizon', 'resources', 'budget', 'time_limit_s', 'max_variants', 'max_paths_per_relation', 'max_local_assignments', 'critical_relation_ids', 'weights', 'baseline_kind']);

function exampleFor(data: Bootstrap): RecordData {
  const graph = data.graph;
  const schedule = rows(graph.restrictions).length ? rows(graph.restrictions) : rows(graph.works);
  const options: RecordData[] = [{id: 'unchanged', name: 'Obecna kolejność prac', cost: null, works: schedule}];
  const x = schedule.find(work => work.id === 'X');
  const y = schedule.find(work => work.id === 'Y');
  if (data.layer === 'fixture' && x && y) {
    const start = new Date(x.end).valueOf() + 30 * 60000;
    const duration = new Date(y.end).valueOf() - new Date(y.start).valueOf();
    options.push({id: 'with-overlap', name: '30 minut wspólnej drożności', cost: null,
      works: schedule.map(work => work.id === y.id ? {...work, start: new Date(start).toISOString(), end: new Date(start + duration).toISOString()} : work),
      assumptions: ['Otwarcie pierwszego dojścia wymaga nowej obserwacji przed zamknięciem drugiego.']});
  }
  const resources = Object.fromEntries(schedule.filter(work => work.resource).map(work => [work.resource, {capacity: 1}]));
  return {catalog: [{id: 'work-order', name: 'Kolejność robót', options}], solver: 'cp_sat',
    origins: rows(graph.origins).map(origin => origin.id), profiles: rows(graph.profiles).slice(0, 1).map(profile => profile.id),
    destinations: rows(graph.places).map(place => place.id), horizon: graph.horizon,
    resources, time_limit_s: 30, max_variants: 4096, max_paths_per_relation: 128, max_local_assignments: 4096};
}

function object(value: unknown): value is RecordData { return typeof value === 'object' && value !== null && !Array.isArray(value); }
function date(value: unknown, label: string) {
  if (typeof value !== 'string' || !/(?:Z|[+-]\d{2}:\d{2})$/i.test(value) || !Number.isFinite(Date.parse(value))) {
    throw new Error(`${label}: podaj pełną datę ISO ze strefą, np. 2026-10-03T08:00:00+02:00.`);
  }
  return Date.parse(value);
}

function validateCatalog(text: string): RecordData {
  if (text.length > 500000) throw new Error('Katalog przekracza limit 500 kB formularza.');
  let request: unknown;
  try { request = JSON.parse(text); } catch { throw new Error('Niepoprawny JSON katalogu. Sprawdź przecinki, nawiasy i cudzysłowy.'); }
  if (!object(request)) throw new Error('Katalog wymaga jednego obiektu JSON.');
  const unsupported = Object.keys(request).filter(key => !requestKeys.has(key));
  if (unsupported.length) throw new Error(`Nieobsługiwane pola analizy: ${unsupported.join(', ')}.`);
  const inspect = (value: unknown, depth = 0) => {
    if (depth > 20) throw new Error('Zbyt wiele poziomów zagnieżdżenia katalogu.');
    if (Array.isArray(value)) value.forEach(item => inspect(item, depth + 1));
    else if (object(value)) for (const [key, item] of Object.entries(value)) {
      if (key.startsWith('_') || ['constructor', 'prototype'].includes(key) || /password|secret|token|api.?key/i.test(key)) {
        throw new Error(`Pole „${key}” nie należy do danych planowania. Nie wprowadzaj kluczy ani sekretów.`);
      }
      inspect(item, depth + 1);
    }
  };
  inspect(request);
  if (!Array.isArray(request.catalog) || request.catalog.length < 1 || request.catalog.length > 32) throw new Error('Wymagany jest katalog zawierający od 1 do 32 grup wyboru.');
  const groupIds = new Set<string>();
  for (const [index, group] of request.catalog.entries()) {
    if (!object(group) || typeof group.id !== 'string' || !group.id.trim() || groupIds.has(group.id)) throw new Error(`Grupa ${index + 1} wymaga unikalnego id.`);
    groupIds.add(group.id);
    if (!Array.isArray(group.options) || !group.options.length || group.options.length > 128) throw new Error(`Grupa „${group.id}” wymaga od 1 do 128 wariantów w options.`);
    const optionIds = new Set<string>();
    for (const option of group.options) {
      if (!object(option) || typeof option.id !== 'string' || !option.id.trim() || optionIds.has(option.id)) throw new Error(`Warianty grupy „${group.id}” wymagają unikalnych id.`);
      optionIds.add(option.id);
      if (option.cost != null && (typeof option.cost !== 'number' || !Number.isFinite(option.cost) || option.cost < 0)) throw new Error('Koszt wariantu musi być nieujemną liczbą albo null.');
      for (const key of ['works', 'restrictions', 'actions']) {
        if (option[key] !== undefined && !Array.isArray(option[key])) throw new Error(`Pole ${key} musi być listą.`);
        for (const activity of option[key] || []) {
          if (!object(activity) || typeof activity.id !== 'string' || !activity.id) throw new Error('Każda robota i działanie wymagają id.');
          if (activity.start || activity.end) {
            if (date(activity.start, 'Początek działania') >= date(activity.end, 'Koniec działania')) throw new Error('Koniec działania musi być późniejszy niż początek.');
          }
          for (const field of ['requires', 'excludes']) if (activity[field] !== undefined && (!Array.isArray(activity[field]) || activity[field].some((id: unknown) => typeof id !== 'string'))) throw new Error(`${field} wymaga listy identyfikatorów działań.`);
        }
      }
    }
  }
  for (const key of ['origins', 'profiles', 'destinations']) if (!Array.isArray(request[key]) || !request[key].length) throw new Error(`Uzupełnij ${key}; zbiór oceny nie może być pusty.`);
  if (!object(request.horizon) || date(request.horizon.start, 'Początek horyzontu') >= date(request.horizon.end, 'Koniec horyzontu')) throw new Error('Podaj poprawny wspólny horyzont analizy.');
  if (!['cp_sat', 'enumeration'].includes(request.solver)) throw new Error('Wybierz solver cp_sat lub enumeration.');
  if (request.time_limit_s !== undefined && (typeof request.time_limit_s !== 'number' || request.time_limit_s <= 0 || request.time_limit_s > 300)) throw new Error('Limit analizy musi wynosić od ponad 0 do 300 sekund.');
  if (request.budget != null && (typeof request.budget !== 'number' || !Number.isFinite(request.budget) || request.budget < 0)) throw new Error('Budżet musi być nieujemną liczbą albo null.');
  if (request.resources !== undefined) {
    if (!object(request.resources)) throw new Error('resources wymaga obiektu z nazwami zasobów.');
    for (const [id, resource] of Object.entries(request.resources)) {
      const capacity = object(resource) ? resource.capacity : resource;
      if (typeof capacity !== 'number' || !Number.isInteger(capacity) || capacity < 1) throw new Error(`Zasób „${id}” wymaga dodatniej całkowitej capacity.`);
      if (object(resource) && resource.windows !== undefined) {
        if (!Array.isArray(resource.windows)) throw new Error(`Okna zasobu „${id}” muszą być listą.`);
        for (const window of resource.windows) if (!object(window) || date(window.start, 'Początek okna zasobu') >= date(window.end, 'Koniec okna zasobu')) throw new Error(`Niepoprawne okno zasobu „${id}”.`);
      }
    }
  }
  return request;
}

export default function CatalogEditor({data, onRefresh, onEvaluated}: Props) {
  const [text, setText] = useState(() => JSON.stringify(exampleFor(data), null, 2));
  const [draftLayer, setDraftLayer] = useState(data.layer);
  const [name, setName] = useState('Katalog dopuszczalnych wariantów');
  const [error, setError] = useState(''), [message, setMessage] = useState(''), [busy, setBusy] = useState(false);
  const [job, setJob] = useState<RecordData | null>(null), [result, setResult] = useState<RecordData | null>(null), [scenario, setScenario] = useState<RecordData | null>(null);
  const callbacks = useRef({onRefresh, onEvaluated}); callbacks.current = {onRefresh, onEvaluated};
  const operation = useRef<{signature: string; key: string; scenario?: RecordData} | null>(null);
  const canWrite = !!data.user && ['operator', 'admin'].includes(data.user.role);
  const running = busy || !!(job && !terminal.has(job.status));

  useEffect(() => {
    if (!job?.job_id || terminal.has(job.status)) return;
    let stopped = false, inFlight = false;
    const poll = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const current = await api(`/jobs/${encodeURIComponent(job.job_id)}`);
        if (stopped) return;
        setJob({...current, job_id: current.job_id || current.id});
        if (terminal.has(current.status)) {
          if (['completed', 'succeeded'].includes(current.status) && current.result) {
            setResult(current.result); setMessage(rows(current.result.variants).some(variant => variant.complete) ? 'Analiza katalogu zapisana. Ukończone warianty sprawdzono ponownie na pełnym grafie.' : 'Analiza katalogu zapisana. Sprawdź status i zakres obliczeń; nie uzyskano ukończonego wariantu.');
            callbacks.current.onEvaluated?.(current.result);
          } else setError(current.error || (current.status === 'stale' ? 'Ten wynik dotyczy starszej wersji scenariusza. Odczytaj aktualny zapis przed decyzją.' : 'Analiza zakończyła się błędem. Sprawdź zadanie w diagnostyce.'));
          await callbacks.current.onRefresh();
        }
      } catch (e) { if (!stopped) setError((e as Error).message); }
      finally { inFlight = false; }
    };
    const event=(value:Event)=>{const update=(value as CustomEvent).detail;if((update.id||update.job_id)===job.job_id)void poll();};const reconnect=()=>{void poll();};void poll(); const interval = window.setInterval(() => void poll(), 1200);window.addEventListener('mbod-job-progress',event);window.addEventListener('mbod-stream-connected',reconnect);
    return () => { stopped = true; window.clearInterval(interval);window.removeEventListener('mbod-job-progress',event);window.removeEventListener('mbod-stream-connected',reconnect); };
  }, [job?.job_id, job?.status]);

  const submit = async () => {
    setBusy(true); setError(''); setMessage('');
    try {
      const request = validateCatalog(text);
      if (draftLayer !== data.layer) throw new Error('Ten szkic pochodzi z innej warstwy. Wczytaj właściwy katalog albo przywróć przykład dla bieżących danych.');
      if (name.trim().length < 3) throw new Error('Nazwa scenariusza wymaga co najmniej 3 znaków.');
      const signature = JSON.stringify({name: name.trim(), layer: data.layer, version: data.data_version, request});
      if (!operation.current || operation.current.signature !== signature) operation.current = {signature, key: crypto.randomUUID()};
      const active = operation.current;
      const saved: RecordData = active.scenario ?? await api<RecordData>('/scenarios', {name: name.trim(), layer: data.layer, request}, {idempotencyKey: active.key});
      active.scenario = saved; setScenario(saved);
      const queued = await api(`/scenarios/${saved.id}/evaluate`, {expected_version: saved.version}, {idempotencyKey: `${active.key}:evaluate`});
      setResult(null); setJob({...queued, job_id: queued.job_id || queued.id});
      setMessage('Katalog zapisano na zamrożonych danych. Worker ocenia legalne ścieżki oraz zasoby.');
      await onRefresh();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const check = () => { try { const request = validateCatalog(text); setText(JSON.stringify(request, null, 2)); setError(''); setMessage('Struktura katalogu jest poprawna. Wykonalność i dostępność sprawdzi silnik po zapisaniu analizy.'); } catch (e) { setError((e as Error).message); } };

  return <details className="card analysis-controls">
    <summary><FileInput size={17}/>Katalog alternatyw, zasoby i zależności</summary>
    <p className="muted">Koordynator określa skończone warianty. Z każdej grupy silnik wybiera jedną opcję, zachowuje wspólny horyzont i ponownie sprawdza cały graf.</p>
    <Notice>To edytor zaawansowanego planowania. Katalog zawiera wyłącznie dane robót i jawne założenia. Nie wpisuj kluczy usług ani danych zgłaszających. Zapis symulacji nie zleca wykonania prac.</Notice>
    {draftLayer !== data.layer && <Notice tone="warning">Szkic katalogu pochodzi z innej warstwy. Możesz go pobrać, a następnie wczytać właściwy plik albo przywrócić przykład bieżącego grafu.</Notice>}
    <form onSubmit={event => {event.preventDefault(); void submit();}}>
      <Field label="Nazwa analizy katalogu"><input value={name} onChange={event => setName(event.target.value)} minLength={3} maxLength={300} disabled={running} required/></Field>
      <Field label="Wczytaj katalog z pliku JSON"><input type="file" accept=".json,application/json" disabled={running} onChange={event => {
        const file = event.target.files?.[0]; if (!file) return;
        if (file.size > 500000) {setError('Maksymalny rozmiar katalogu to 500 kB.'); return;}
        void file.text().then(content => {validateCatalog(content); setText(content); setDraftLayer(data.layer); setError(''); setMessage('Wczytano katalog. Sprawdź zakres i założenia przed oceną.');}).catch(e => setError((e as Error).message));
      }}/></Field>
      <Field label="Katalog i zakres analizy (JSON)" hint="Daty wymagają strefy. Identyfikatory obiektów i robót muszą pochodzić z wybranego grafu. Koszt null oznacza brak danych."><textarea className="code-input" rows={16} value={text} onChange={event => setText(event.target.value)} disabled={running} spellCheck={false}/></Field>
      <div className="row-actions">
        <Button kind="secondary" disabled={running} onClick={check}>Sprawdź strukturę</Button>
        <Button kind="secondary" disabled={running} onClick={() => {try {downloadJson(validateCatalog(text), 'katalog-wariantow.json'); setError('');} catch (e) {setError((e as Error).message);}}}><Download size={15}/>Pobierz katalog</Button>
        <Button kind="ghost" disabled={running} onClick={() => {setText(JSON.stringify(exampleFor(data), null, 2)); setDraftLayer(data.layer); setError(''); setMessage('Przywrócono przykład oparty na bieżącym grafie.'); operation.current = null;}}><RotateCcw size={15}/>Przywróć przykład</Button>
        <Button type="submit" busy={running} disabled={!canWrite || draftLayer !== data.layer}><Play size={15}/>Zapisz i oceń katalog</Button>
      </div>
      {!canWrite && <p className="small muted">Zapis analizy wymaga zalogowanego operatora lub administratora. Katalog możesz przygotować i pobrać przed logowaniem.</p>}
    </form>
    <details className="evidence-details"><summary>Jak opisać zasoby, zależności i koszty</summary>
      <p><code>catalog</code> zawiera grupy z listą <code>options</code>. Każda grupa ma jeden wybrany wariant. <code>works</code> opisuje harmonogram robót, a <code>actions</code> naprawy lub utrzymanie obejścia. Zachowaj wszystkie pierwotne roboty i pozostałe ograniczenia.</p>
      <p>Zasób w <code>resources</code> ma <code>capacity</code> i opcjonalne <code>windows</code> z czasami <code>start/end</code>. Działanie wskazuje <code>resource</code> i liczbę <code>resource_units</code>. Nakładanie prac nie może przekroczyć pojemności ani okna dostępności.</p>
      <p><code>requires</code> i <code>excludes</code> są listami identyfikatorów działań. Działania wymagające siebie nawzajem muszą znaleźć się w wybranym zestawie. Kolejność robót opisuje <code>depends_on</code> z ewentualnym <code>lag_s</code>. Warianty respektują pierwotne <code>earliest_start/latest_end</code>.</p>
      <p>Naprawa zawiera <code>kind: "repair"</code>, <code>asset_id</code>, <code>feature</code>, <code>value</code>, <code>effective_from</code> i <code>valid_until</code>. Możesz podać listę <code>features</code>. <code>approved_feasible: false</code> wyklucza niezaakceptowaną wykonalność. <code>resolves_restriction_ids</code> dotyczy wyłącznie wskazanych ograniczeń.</p>
      <p>Wpisz uzgodniony <code>budget</code> i rzeczywiste <code>cost</code>. Brak kosztu pozostaw jako <code>null</code>; silnik nie potwierdzi wtedy budżetu. Podstawę kosztów i otwarcia zapisz w <code>assumptions</code> opcji. <code>cp_sat</code> optymalizuje zadaną pulę ścieżek; <code>enumeration</code> przegląda mały katalog. Raport ujawnia limity i niepełny zakres.</p>
      <pre className="data-detail">{JSON.stringify({resources: {brygada: {capacity: 1, windows: [{start: '2026-10-03T08:00:00+02:00', end: '2026-10-03T20:30:00+02:00'}]}}, actions: [{id: 'naprawa-B', kind: 'repair', asset_id: 'wskazany-obiekt', feature: 'width_m', value: 1.2, unit: 'm', requires: ['naprawa-A'], excludes: ['zamkniecie-obejscia'], resource: 'brygada', resource_units: 1, approved_feasible: false, cost: null}]}, null, 2)}</pre>
      <p className="small muted">Powyższy fragment wyjaśnia pola. Zastąp przykładowe identyfikatory, dodaj terminy i uzgodnij wykonalność przed użyciem.</p>
    </details>
    {error && <Notice tone="error">{error}</Notice>}{message && <Notice tone="success">{message}</Notice>}
    {job && <div className="job-progress"><Status value={job.status}/><progress max={100} value={job.progress ?? 0} aria-label="Postęp analizy katalogu"/><span className="small">Zadanie zapisane trwale; zakończenie można odczytać także w liście scenariuszy.</span></div>}
    {result && <section aria-label="Wynik analizy katalogu"><ResultsDetails data={data} evaluation={result}/><h3>Wynik katalogu</h3><Status value={result.solver_status}/><Badge tone="purple">Symulacja</Badge><p>{result.scope || result.search?.optimality_scope || 'Zakres podanego skończonego katalogu.'}</p>
      <div className="table-scroll"><table><thead><tr><th>Wariant</th><th>Dostępność · h relacji</th><th>Odzysk · h relacji</th><th>Warunki krytyczne</th><th>Budżet</th></tr></thead><tbody>{rows(result.variants).map(variant => <tr key={variant.id}><th>{variant.name || variant.id}</th><td>{formatNumber(variant.available_relation_hours)}</td><td>{formatNumber(variant.recovered_relation_hours)}</td><td>{variant.critical_satisfied ? 'Spełnione w modelu' : 'Niespełnione lub nierozstrzygnięte'}</td><td>{variant.feasibility?.budget_status === 'unknown' ? 'Brak pełnych kosztów' : variant.cost == null ? 'Koszt nieznany' : `${formatNumber(variant.cost)} zł`}</td></tr>)}</tbody></table></div>
      {!rows(result.variants).length && <Notice tone="warning">Brak zweryfikowanego wariantu. Sprawdź status, limity i warunki katalogu; nie oznacza to dowodu odcięcia w terenie.</Notice>}
      <details className="evidence-details"><summary>Zakres przeszukania i dowód obliczenia</summary><pre className="data-detail">{JSON.stringify({complete: result.complete, search: result.search, snapshot: result.snapshot, ranking: result.ranking_criteria}, null, 2)}</pre></details>
      {scenario && <><p className="small">Scenariusz „{scenario.name}” jest dostępny w sekcji „Decyzja i odpowiedzialność”. Jego zapis nie publikuje zmian infrastruktury.</p><div className="export-links">{['json', 'csv', 'geojson'].map(format => <a key={format} href={`/api/v1/exports/${encodeURIComponent(scenario.id)}?format=${format}`} download>{format.toUpperCase()}</a>)}</div></>}
    </section>}
  </details>;
}
