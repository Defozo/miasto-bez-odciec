import { useId } from 'react';
import { ArrowDownRight, ArrowUpRight, GitCompareArrows, Route, Users2 } from 'lucide-react';
import { type Bootstrap, type RecordData, rows, formatNumber, dateTime, label } from './api';
import { Badge, CardTitle, Notice } from './ui';
import './ResultsDetails.css';

type Props = { data: Bootstrap; evaluation: RecordData; variant?: RecordData };
type Group = { id: string; before: RecordData; after: RecordData; changes: RecordData[] };

const value = (record: RecordData | undefined, key: string): number | undefined => {
  const candidate = record?.[key] ?? record?.metrics?.[key];
  return typeof candidate === 'number' && Number.isFinite(candidate) ? candidate : undefined;
};
const dictionary = (input: unknown): Record<string, RecordData> => input && typeof input === 'object' && !Array.isArray(input) ? input as Record<string, RecordData> : {};
const signed = (number: number | undefined, digits = 1) => number === undefined ? 'Nie obliczono' : `${number > 0 ? '+' : ''}${formatNumber(number, digits)}`;
const sum = (changes: RecordData[], key: string) => changes.reduce((total, change) => total + (value(change, key) ?? 0), 0);
const named = (record: RecordData | undefined, fallback: string) => record ? label(record) : fallback;

export default function ResultsDetails({ data, evaluation, variant }: Props) {
  const headingId = useId();
  const variants = rows(evaluation.variants);
  const selected = variant || variants.find(item => item.id === evaluation.recommended_id) || variants[0];
  const baseline = evaluation.baseline || {};
  const changes = rows(selected?.changes);
  const relations = new Map<string, RecordData>([...rows(baseline.relations), ...rows(selected?.relations)].map(item => [item.id, item]));
  const origins = new Map(rows(data.graph.origins).map(item => [item.id, item]));
  const profiles = new Map([...rows(data.graph.profiles), ...rows(evaluation.snapshot?.profiles)].map(item => [item.id, item]));
  const places = new Map([...rows(data.graph.places), ...rows(data.graph.entrances)].map(item => [item.id, item]));
  const names = new Map(variants.map(item => [item.id, item.name || item.id]));
  const recovered = Array.isArray(selected?.recovered_relations) ? selected.recovered_relations as string[] : [];
  const lost = Array.isArray(selected?.lost_relations) ? selected.lost_relations as string[] : [];
  const nondominated = Array.isArray(evaluation.nondominated_ids) ? evaluation.nondominated_ids as string[] : [];
  const rankings = Array.isArray(evaluation.ranking_criteria) ? evaluation.ranking_criteria as string[] : [];
  const incomplete = evaluation.complete === false || selected?.complete === false;

  const destinationName = (id: string) => id.startsWith('category:')
    ? `kategoria: ${id.slice(9) === 'healthcare' ? 'opieka zdrowotna' : id.slice(9)}`
    : named(places.get(id), id);
  const describeRelation = (id: string) => {
    const relation = relations.get(id);
    const [origin, profile, ...destination] = id.split('|');
    return `${named(origins.get(relation?.origin || origin), relation?.origin || origin)} · ${named(profiles.get(relation?.profile_id || profile), relation?.profile_id || profile)} · ${destinationName(relation?.destination_id || destination.join('|'))}`;
  };
  const groups = (key: 'by_profile' | 'by_origin'): Group[] => {
    const before = dictionary(baseline[key]);
    const after = dictionary(selected?.[key]);
    return [...new Set([...Object.keys(before), ...Object.keys(after)])].map(id => ({
      id, before: before[id] || {}, after: after[id] || {},
      changes: changes.filter(change => key === 'by_profile'
        ? change.profile_id === id
        : relations.get(change.relation_id)?.origin === id),
    }));
  };
  const groupTable = (key: 'by_profile' | 'by_origin', title: string) => {
    const items = groups(key);
    if (!items.length) return <p className="small muted">Brak rozbicia tej analizy: {title.toLocaleLowerCase('pl')}.</p>;
    return <div className="table-scroll" tabIndex={0} role="region" aria-label={title}><table className="results-detail-table">
      <caption>{title}. Godziny dopuszczalnego rozpoczęcia całych podróży.</caption>
      <thead><tr><th scope="col">{key === 'by_profile' ? 'Profil wymagań' : 'Punkt oceny'}</th><th scope="col">Liczba relacji</th><th scope="col">Dostępne w bazie · h</th><th scope="col">Dostępne w wariancie · h</th><th scope="col">Odzysk · h</th><th scope="col">Strata · h</th><th scope="col">Niewiadome w wariancie · h</th><th scope="col">Niedokończone · h</th></tr></thead>
      <tbody>{items.map(group => <tr key={group.id}>
        <th scope="row">{named((key === 'by_profile' ? profiles : origins).get(group.id), group.id)}</th>
        <td>{formatNumber(value(group.after, 'relation_count') ?? value(group.before, 'relation_count'), 0)}</td>
        <td>{formatNumber(value(group.before, 'available_relation_hours'))}</td><td>{formatNumber(value(group.after, 'available_relation_hours'))}</td>
        <td>{selected ? formatNumber(sum(group.changes, 'recovered_hours')) : 'Nie obliczono'}</td><td>{selected ? formatNumber(sum(group.changes, 'lost_hours')) : 'Nie obliczono'}</td>
        <td>{formatNumber(value(group.after, 'unknown_relation_hours'))}</td><td>{formatNumber(value(group.after, 'incomplete_relation_hours'))}</td>
      </tr>)}</tbody>
    </table></div>;
  };

  return <section className="card results-details" aria-labelledby={headingId}>
    <div className="card-title"><div><span className="eyebrow">JAWNE ZYSKI, STRATY I NIEWIADOME</span><h2 id={headingId}>Kto odzyskuje dojście, a kto je traci?</h2></div><Badge tone="purple"><GitCompareArrows size={14}/>Symulacja</Badge></div>
    <p>{selected ? `Wybrany wariant: ${selected.name || selected.id}. ` : ''}Stały zbiór obejmuje {formatNumber(value(baseline, 'relation_count'), 0)} relacje. Relacja oznacza punkt startowy, profil i cel, a nie osobę.</p>
    {evaluation.horizon && <p className="small muted">Wspólny horyzont wyjść: {dateTime(evaluation.horizon.start)} do {dateTime(evaluation.horizon.end)}.</p>}
    {incomplete && <Notice tone="warning">Obliczenie jest częściowe. Nierozstrzygnięte przedziały pozostają oddzielne; nie są dowodem utraty dojścia ani optimum.</Notice>}
    {selected && <>
      <div className="results-detail-stats">
        <div><span><ArrowUpRight size={18}/>Relacje odzyskujące dostęp</span><strong>{formatNumber(recovered.length, 0)}</strong><small>{formatNumber(value(selected, 'recovered_relation_hours'))} h relacji odzysku</small></div>
        <div><span><ArrowDownRight size={18}/>Relacje tracące dostęp</span><strong>{formatNumber(lost.length, 0)}</strong><small>{formatNumber(value(selected, 'lost_relation_hours'))} h relacji straty</small></div>
        <div><span><Route size={18}/>Zmiana długości dojścia</span><strong>{signed(value(selected, 'mean_distance_change_m'))}<small> m</small></strong><small>Średnia ważona czasem, wyłącznie gdy oba warianty zapewniają dojście. Wartość dodatnia oznacza wydłużenie.</small></div>
      </div>
      <p className="small">Ta sama relacja może zyskać w jednym przedziale i stracić w innym. Wzrost wiedzy: {formatNumber(value(selected, 'knowledge_gain_relation_hours'))} h relacji. Pozostały odzysk potwierdzonej dostępności: {formatNumber(value(selected, 'confirmed_access_recovery_relation_hours'))} h. Wynik symulacji nie potwierdza wykonania naprawy.</p>
      <details className="evidence-details"><summary>Lista zysków i strat dla konkretnych relacji</summary>
        <div className="results-detail-lists"><div><h3>Odzyskują dostęp</h3>{recovered.length ? <ul>{recovered.map(id => <li key={id}>{describeRelation(id)}<span>{formatNumber(value(changes.find(change => change.relation_id === id), 'recovered_hours'))} h</span></li>)}</ul> : <p>Żadna relacja nie odzyskuje dostępu w obliczonym zakresie.</p>}</div>
          <div><h3>Tracą dostęp</h3>{lost.length ? <ul>{lost.map(id => <li key={id}>{describeRelation(id)}<span>{formatNumber(value(changes.find(change => change.relation_id === id), 'lost_hours'))} h</span></li>)}</ul> : <p>Żadna relacja nie traci dostępu w obliczonym zakresie.</p>}</div></div>
      </details>
    </>}

    <div className="results-detail-section"><CardTitle title="Każde zamknięcie osobno i wszystkie razem"/>
      {rows(evaluation.work_impacts).length ? <div className="table-scroll" tabIndex={0} role="region" aria-label="Skutki zamknięć osobno i razem"><table className="results-detail-table"><caption>Ten sam zbiór relacji i horyzont. Ocena w całym oknie podróży.</caption><thead><tr><th scope="col">Zakres robót</th><th scope="col">Dostępne · h relacji</th><th scope="col">Niedostępne w modelu · h relacji</th><th scope="col">Niewiadome · h relacji</th><th scope="col">Niedokończone · h relacji</th><th scope="col">Warunki krytyczne</th></tr></thead><tbody>
        {[...rows(evaluation.work_impacts).map(item => ({...item, id: item.work_id, name: item.name || item.work_id})), {...baseline, id: 'all-works', name: 'Wszystkie roboty łącznie (baza)'}].map(item => <tr key={item.id}><th scope="row">{item.name}</th><td>{formatNumber(value(item, 'available_relation_hours'))}</td><td>{formatNumber(value(item, 'unavailable_relation_hours'))}</td><td>{formatNumber(value(item, 'unknown_relation_hours'))}</td><td>{formatNumber(value(item, 'incomplete_relation_hours'))}</td><td>{item.complete === false ? 'Obliczenie niepełne' : item.critical_satisfied ? 'Spełnione' : 'Niespełnione'}</td></tr>)}
      </tbody></table></div> : <p className="small muted">Ta ocena nie zawiera osobnych prób zamknięć. Ich wynik nie jest wyliczany z sumy korzyści działań.</p>}
    </div>

    <div className="results-detail-section"><CardTitle title="Zyski i straty według potrzeb" action={<Users2 size={18}/>}/>{groupTable('by_profile', 'Porównanie profili')}
      <div className="results-detail-weighted"><span>Ważona dostępność bazy: <strong>{formatNumber(value(baseline, 'weighted_available_relation_hours'))}</strong></span><span>Ważona dostępność wariantu: <strong>{formatNumber(value(selected, 'weighted_available_relation_hours'))}</strong></span></div>
      <details className="evidence-details"><summary>Jawne wagi relacji</summary><p className="small">Domyślna waga wynosi 1. Ważony wynik służy podanej kolejności kryteriów. Nieważone godziny i straty pozostają widoczne osobno.</p><ul className="results-detail-weights" tabIndex={0} aria-label="Wagi poszczególnych relacji">{rows(baseline.relations).map(relation => <li key={relation.id}>{describeRelation(relation.id)}: <strong>{formatNumber(value(relation, 'weight'))}</strong></li>)}</ul></details>
    </div>
    <div className="results-detail-section"><CardTitle title="Podział według punktów oceny"/><p className="small muted">Każdy punkt reprezentuje jawnie wybrane miejsce rozpoczęcia. Te dane nie wyznaczają dzielnic ani liczby mieszkańców obszaru.</p>{groupTable('by_origin', 'Porównanie punktów oceny')}</div>

    <div className="results-detail-section"><CardTitle title="Dlaczego ten porządek wariantów?"/>
      {evaluation.recommended_id ? <p><strong>{evaluation.recommendation_status === 'least_loss' ? 'Najmniejsza znaleziona strata: ' : 'Rekomendowany w badanym zakresie: '}{names.get(evaluation.recommended_id) || evaluation.recommended_id}</strong>. {evaluation.recommendation_status === 'least_loss' ? 'Wymagania krytyczne nie są zachowane. To nie jest wariant spełniający warunek ciągłości.' : 'Przed decyzją sprawdź wykonalność, założenia i kompletność obliczeń.'}</p> : <Notice tone="warning">Brak rekomendowanego, w pełni ocenionego wariantu. Wynik nie potwierdza istnienia wykonalnego rozwiązania.</Notice>}
      {rankings.length ? <ol className="results-detail-ranking">{rankings.map((criterion, index) => <li key={`${index}-${criterion}`}>{criterion}</li>)}</ol> : <p className="small muted">W tym wyniku nie zapisano kolejności kryteriów.</p>}
      <h3>Warianty niezdominowane</h3><p className="small">Inny oceniony wariant nie jest jednocześnie co najmniej tak dobry we wszystkich porównywanych kryteriach i lepszy w przynajmniej jednym. Nieznany koszt pozostaje odrębną niewiadomą.</p>
      {nondominated.length ? <ul className="results-detail-options">{nondominated.map(id => <li key={id}><Badge tone="purple">Niezdominowany</Badge><span>{names.get(id) || id}</span></li>)}</ul> : <p>Brak wskazanych wariantów niezdominowanych w zakończonym zakresie oceny.</p>}
      {!!rows(selected?.critical_violations).length && <details className="evidence-details"><summary>Niespełnione wymagania krytyczne wybranego wariantu</summary><ul>{rows(selected?.critical_violations).map((item, index) => <li key={item.relation_id || index}>{describeRelation(item.relation_id || '')}: {formatNumber(item.unavailable_hours)} h niedostępności w modelu, {formatNumber(item.unknown_hours)} h niewiadomych, {formatNumber(item.incomplete_hours)} h niedokończonych obliczeń.</li>)}</ul></details>}
    </div>
  </section>;
}
