export type RecordData = Record<string, any>;
export type Bootstrap = {
  layer: string; data_version: number; graph_version: string; graph: RecordData;
  user: {username: string; role: string} | null; local_demo_auth?: boolean;
  reports: RecordData[]; tasks: RecordData[]; scenarios: RecordData[];
  sources: RecordData[]; restrictions: RecordData[]; decisions: RecordData[];
  pilot_status: string; cached_at?: string; staff_evidence?: RecordData[];
};

let csrfToken = '';
export function setCsrf(value: string) { csrfToken = value; }
export async function uploadPhoto(reportId:string,token:string,file:File) {
  const form=new FormData();form.append('file',file);
  const response=await fetch(`/api/v1/reports/${encodeURIComponent(reportId)}/photos`,{method:'POST',credentials:'same-origin',headers:{'Idempotency-Key':crypto.randomUUID(),'X-Report-Token':token,...(csrfToken?{'X-CSRF-Token':csrfToken}:{})},body:form});
  const result=await response.json();if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'Nie udało się zapisać zdjęcia. Zgłoszenie tekstowe jest zapisane.');return result;
}
export async function uploadTaskPhoto(taskId:string,file:File,idempotencyKey:string):Promise<RecordData> {
  const form=new FormData();form.append('file',file);
  let response:Response;
  try {response=await fetch(`/api/v1/tasks/${encodeURIComponent(taskId)}/photos`,{method:'POST',credentials:'same-origin',headers:{'Idempotency-Key':idempotencyKey,...(csrfToken?{'X-CSRF-Token':csrfToken}:{})},body:form});}
  catch {throw new Error('Nie można wysłać zdjęcia. Pomiar pozostaje niewysłany; zachowaj szkic i spróbuj ponownie po odzyskaniu połączenia.');}
  const result=await response.json();if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'Nie udało się zapisać zdjęcia pomiaru.');return result;
}
export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function api<T = RecordData>(path: string, body?: unknown, options: {method?: string; idempotencyKey?: string; signal?: AbortSignal; headers?:Record<string,string>} = {}): Promise<T> {
  const method = options.method ?? (body === undefined ? 'GET' : 'POST');
  const headers: Record<string, string> = {Accept: 'application/json',...options.headers};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET') {
    headers['Idempotency-Key'] = options.idempotencyKey || crypto.randomUUID();
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
  }
  let response: Response;
  try { response = await fetch(`/api/v1${path}`, {method, headers, credentials: 'same-origin', body: body === undefined ? undefined : JSON.stringify(body), signal: options.signal}); }
  catch (error) { if (error instanceof Error && error.name === 'AbortError') throw error; throw new ApiError('Nie można połączyć się z serwerem. Szkic możesz zapisać na tym urządzeniu.', 0); }
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = result.detail;
    const message = response.status === 409 ? 'Dane zmieniły się od otwarcia formularza. Odśwież widok i sprawdź zmianę przed ponownym zapisem.'
      : response.status === 401 ? 'Zaloguj się, aby wykonać tę czynność.'
      : response.status === 403 ? 'Ta czynność wymaga odpowiedniej roli lub odświeżenia sesji.'
      : typeof detail === 'string' ? detail
      : Array.isArray(detail) ? detail.map((item: RecordData) => `${item.loc?.slice(1).join('.')}: ${item.msg}`).join('; ')
      : result.message || 'Nie udało się wykonać operacji. Spróbuj ponownie.';
    throw new ApiError(message, response.status);
  }
  return result as T;
}

export function rows(value: unknown): RecordData[] {
  if (Array.isArray(value)) return value;
  if (value && typeof value === 'object') return Object.entries(value).map(([id, item]) => typeof item === 'object' && item ? {id, ...item} : {id, value: item});
  return [];
}
export function label(item?: RecordData | string | null): string {
  if (typeof item === 'string') return item;
  return item?.name || item?.label || item?.title || item?.id || 'Bez nazwy';
}
export function formatNumber(value: unknown, digits = 1): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('pl-PL', {maximumFractionDigits: digits}) : 'brak wyniku';
}
export function dateTime(value: unknown, withDate = true): string {
  if (!value) return 'Nie podano';
  const date = new Date(String(value));
  if (Number.isNaN(date.valueOf())) return String(value);
  return new Intl.DateTimeFormat('pl-PL', {timeZone: 'Europe/Warsaw', ...(withDate ? {day:'2-digit',month:'2-digit',year:'numeric'} as const : {}), hour:'2-digit', minute:'2-digit'}).format(date);
}
export function localDateTime(iso: string): string {
  const d = new Date(iso); if (Number.isNaN(d.valueOf())) return '';
  const parts = new Intl.DateTimeFormat('sv-SE', {timeZone:'Europe/Warsaw',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(d);
  return parts.replace(' ', 'T');
}
export function warsawUtc(value: string): string {
  if (!value) return new Date().toISOString();
  if (/([+-]\d{2}:\d{2}|Z)$/.test(value)) {
    const explicit = new Date(value);
    if (Number.isNaN(explicit.valueOf())) throw new Error('Niepoprawna data lub strefa czasu.');
    return explicit.toISOString();
  }
  const guess = new Date(`${value}Z`);
  if (Number.isNaN(guess.valueOf())) throw new Error('Niepoprawna data.');
  const offsets = new Set<number>();
  const formatter = new Intl.DateTimeFormat('en-US', {timeZone:'Europe/Warsaw', timeZoneName:'shortOffset'});
  for (const delta of [-36,0,36]) {
    const parts=formatter.formatToParts(new Date(guess.valueOf()+delta*3600000));
    const offset=parts.find(p=>p.type==='timeZoneName')?.value.match(/GMT([+-]\d+)(?::(\d+))?/);
    offsets.add(offset ? Number(offset[1])*60+Math.sign(Number(offset[1]))*Number(offset[2]||0) : 0);
  }
  const candidates=[...offsets].map(offset=>new Date(guess.valueOf()-offset*60000).toISOString()).filter(candidate=>localDateTime(candidate)===value.slice(0,16));
  if (!candidates.length) throw new Error('Ta godzina nie istnieje w Warszawie z powodu zmiany czasu. Wybierz poprawną godzinę.');
  if (candidates.length!==1) throw new Error('Ta godzina występuje dwa razy przy zmianie czasu. Wybierz jednoznaczną godzinę lub podaj datę ISO z jawnym przesunięciem strefy.');
  return candidates[0];
}
export function downloadJson(value: unknown, name: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type:'application/json'}));
  const a = document.createElement('a'); a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url);
}
export function cacheGet<T>(key: string): T | null { try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch { return null; } }
export function cacheSet(key: string, value: unknown) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* The server result remains valid if private mode prevents caching. */ } }

export const statusLabels: Record<string, string> = {
  confirmed:'Potwierdzone w danych', confirmed_route:'Potwierdzone w danych', possible:'Wymaga kontroli', possible_route:'Wymaga kontroli', uncertain:'Niepewne',
  blocked:'Znana bariera', barrier:'Znana bariera', limit:'Przekroczony limit', known_barrier:'Znana bariera', limit_exceeded:'Przekroczony limit', out_of_coverage:'Poza pokryciem', no_connection:'Brak połączenia w modelu', no_path:'Brak połączenia w modelu', incomplete:'Obliczenie niepełne',
  submitted:'Przyjęte do przeglądu', pending_review:'Pomiar czeka na przegląd', assigned:'Przydzielone', observed:'Pomiar zapisany', conflicted:'Sprzeczne dowody', superseded:'Zastąpiony nowszym dowodem', staged:'W obszarze roboczym', validated:'Sprawdzono jakość', outside_coverage:'Poza pokryciem', needs_review:'Czeka na przegląd', located_unverified:'Ostrzeżenie do weryfikacji', needs_recheck:'Do ponownej kontroli', resolved:'Zamknięte', rejected:'Odrzucone',
  draft:'Szkic', evaluated:'Oceniony wariant', approved_plan:'Plan zatwierdzony', in_progress:'W realizacji', performed:'Wykonanie zapisane', effect_reviewed:'Efekt oceniony',
  pending:'Oczekuje', queued:'W kolejce', running:'W trakcie obliczeń', completed:'Zakończone', succeeded:'Zakończone', failed:'Błąd', published:'Opublikowano', expired:'Wygasło',
  OPTIMAL:'Optymalny w zadanym katalogu', FEASIBLE:'Wykonalny', INFEASIBLE:'Brak wykonalnego wariantu', UNKNOWN:'Nierozstrzygnięte',
  operator:'Operator', verifier:'Weryfikator', admin:'Administrator', fixture:'Dane demonstracyjne', planned:'Plan robót', scenario:'Symulacja',
};
export function statusLabel(status: string | undefined): string { return status ? statusLabels[status] || status : 'Brak statusu'; }
