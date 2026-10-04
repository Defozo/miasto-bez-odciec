# Dane pilota i katalog dopuszczalnych działań

Autor: Michał Kiełtyka, DEFOZO SOFTWARE HOUSE. Import, publikacja grafu, publikacja dowodu i przyjęcie decyzji są osobnymi operacjami.

## Pierwszy graf obserwacji

1. Zaloguj operatora hasłem, korzystając z własnego dostępu do psst. Lokalna sesja demonstracyjna jest ograniczona do fixture. W „Źródłach i imporcie” wybierz import, przestrzeń „Obserwacje” oraz OSM/Overpass JSON lub GeoJSON. Zachowaj pochodzenie i licencję pliku. CSV tworzy kandydatury komunikatów, nie graf ulic.
2. Zaimportuj plik. Odczytaj identyfikator grafu i wynik stagingu. Nie interpretuj tagu OSM jako potwierdzonego pomiaru. Geometria przecięcia nie tworzy automatycznie węzła, równoległe krawędzie oraz rozłączone składowe pozostają odrębne.
3. Pozostaw przestrzeń importu „Obserwacje” i w „Wersjach grafu i powiązaniach obiektów” kliknij „Wczytaj wersje”. Ten panel korzysta z przestrzeni importu, dlatego pierwszy graf obserwacji można przygotować jeszcze podczas oglądania demonstracji. Odczytaj właściwy graf staged. Rozwiń „Uzupełnij topologię, wejścia, profile i punkty oceny”. Edytor przyjmuje pełny JSON; zapis poprawki unieważnia wcześniejszą walidację. Opublikowanego grafu nie można edytować w miejscu.
4. Uzupełnij `profiles`, `origins`, `places`, `entrances` i `horizon`. Przycisk ustawień początkowych dostarcza szkic do edycji. Wartości z demonstracji nie są uzgodnionymi profilami pilota. Początek musi wskazywać istniejący węzeł. Każde wejście wskazuje istniejący węzeł, obiekt i cel. Cel jest usługą z konkretnym wejściem, nie centroidem budynku.
5. Sprawdź końce krawędzi, kierunek, stronę ulicy, poziom, przejścia między poziomami i rzeczywiste wejścia. Nie łącz automatycznie chodnika z sąsiednim pasem drogowym. Dopisz potwierdzone ustalenia topologii z ich źródłem; atrybuty bez pomiaru pozostaw nieznane.
6. Przypisz stabilne obiekty aktywnych ograniczeń do nowych krawędzi w polu `bindings`, np. `{"obiekt-przejscia": ["nowy-odcinek-1", "nowy-odcinek-2"]}`. Sprawdź również windę i inne wspólne zależności. Nierozstrzygnięte przypisanie blokuje publikację.
7. Zapisz uzupełnienie, uruchom „Sprawdź graf i przypisania”, przeczytaj błędy i ostrzeżenia. Administrator publikuje graf wraz z powiązaniami w jednej operacji. Nieznane cechy nadal pozostają nieznane.
8. Wybierz „Dane obserwowane”, sprawdź wersję oraz listę początków, celów i profili. Przeprowadź próbę trasy, utwórz zadania pomiarów i po przeglądzie opublikuj dowody. Dopiero dowody ważne przez całe okno podróży pozwalają potwierdzić relację. Audyt i odbiór pilota prowadź według `PILOT.md`.

Techniczny kontrakt tego samego obiegu: `POST /api/v1/imports`, `GET /api/v1/graphs?layer=observed`, `POST /api/v1/graphs/{id}/edit`, `/validate`, `/publish`. Edycja wymaga `expected_version` i przyjmuje `graph` lub `graph_patch` oraz opcjonalne `bindings`. Każda mutacja wymaga sesji, CSRF i klucza idempotencji. Pole `layer` jest zachowywane przez serwer.

Pobrany przez `scripts/fetch-osm.py` plik `artifacts/osm-candidate.json` zawiera już graf wewnętrzny. Do formularza OSM należy przekazać jego `source.raw`, czyli oryginalny obiekt Overpass z `elements`. Pełny graf wewnętrzny można przygotować przez `POST /api/v1/graphs/staging` z `{"layer":"observed","graph":...}`. Wydany snapshot jest kandydatem audytu, nie opublikowaną siecią dostępnych tras.

## Minimalne powiązania ustawień

Przykład pokazuje strukturę do uzupełnienia w zaimportowanym grafie. Identyfikatory `wezel-A`, `wezel-wejscia` i `obiekt-wejscia` muszą wcześniej istnieć odpowiednio w `nodes` i `assets`. Daty oraz liczby są przykładem konfiguracji, nie pomiarem lub normą. Horyzont wyjść powinien kończyć się przed końcem pokrycia danych o maksymalne okno podróży.

```json
{
  "profiles": [{
    "id": "profil-pilota",
    "name": "Profil do uzgodnienia",
    "allow_steps": false,
    "min_width_m": 0.9,
    "max_kerb_cm": 2,
    "max_uphill_pct": 6,
    "max_downhill_pct": 8,
    "allowed_surfaces": ["asphalt", "paving", "concrete"],
    "max_distance_m": 1600,
    "max_duration_s": 1800
  }],
  "origins": [{"id": "wezel-A", "name": "Początek audytu"}],
  "places": [{"id": "usluga-A", "name": "Usługa do sprawdzenia", "category": "healthcare", "entrance_ids": ["wejscie-A"]}],
  "entrances": [{"id": "wejscie-A", "place_id": "usluga-A", "node_id": "wezel-wejscia", "asset_id": "obiekt-wejscia", "level": 0}],
  "horizon": {"start": "2026-10-03T08:00:00+02:00", "end": "2026-10-03T20:30:00+02:00"},
  "valid_from": "2026-10-03T07:00:00+02:00",
  "valid_until": "2026-10-03T21:00:00+02:00"
}
```

W każdej kolejnej publikacji zachowuj źródła i dowody jako rozdzielone zapisy. Zmiana topologii nie odnawia daty pomiaru. Funkcja cotygodniowego pobierania z `config/settings.json` tworzy kolejny staging i nie wykonuje automatycznego audytu lub publikacji.

## Ponowny pomiar po robotach

Ograniczenie opisuje także zakres cech zmienianych przez organizację robót. Pole `invalidated_features` może zawierać np. `width_m`, `slope_pct`, `surface`, `kerb_cm` lub `steps`. Brak rozstrzygnięcia (`null`) wymaga świeżych dowodów wszystkich cech dostępności; wcześniejszy pomiar nie staje się ponownie aktualny po samym potwierdzeniu otwarcia. Pustą listę wolno wybrać dopiero po sprawdzeniu, że roboty nie zmieniają tych parametrów. W warstwie obserwowanej ponowne potwierdzenie drożności nadal wymaga nowego dowodu `open`.

W karcie nachylenia znak wyniku odnosi się do wskazanego kierunku referencyjnego: dodatni oznacza wznoszenie, ujemny spadek. Na krawędzi przeciwnej kierunek zostaje odwrócony przez `slope_direction`. Zdjęcie można dodać jako prywatny załącznik zadania; metoda, jednostka, miejsce, czas i zakres dowodu pozostają obowiązkiem pomiaru.

## Skończony katalog wariantów

W „Porównaniu wariantów” rozwiń „Katalog alternatyw, zasoby i zależności”. Domyślny szkic korzysta z bieżącej warstwy, a w fixture zawiera również przesunięcie Y dające 30 minut wspólnej drożności. Można zaimportować, sformatować i pobrać JSON przed zalogowaniem. Zapis i ocena wymagają operatora lub administratora.

Każda grupa `catalog` ma listę `options`. Silnik wybiera jedną opcję z każdej grupy. Podział powinien odzwierciedlać rzeczywiste niezależne decyzje. Nie przypisuj tych samych robót równocześnie do kilku grup. Zachowaj pełen harmonogram i wszystkie ograniczenia, również te, których termin nie podlega zmianie.

| Pole | Znaczenie |
| --- | --- |
| `works` albo `restrictions` opcji | Harmonogram robót z oryginalnymi identyfikatorami, czasem trwania i dopuszczalnymi oknami |
| `actions` | Naprawa cechy, utrzymanie obejścia lub inne jawnie opisane działanie |
| `requires`, `excludes` działania | Identyfikatory działań wymaganych i wykluczających się |
| `depends_on`, `lag_s` | Kolejność i minimalny odstęp czasowy prac |
| `resources` | Nazwane zasoby z `capacity` i opcjonalnymi `windows` |
| `resource`, `resource_units` | Zasób zajmowany przez działanie oraz wymagana liczba jednostek |
| `budget`, `cost` | Budżet i koszt opcji; `null` zachowuje brak danych |
| `approved_feasible` | Wykonalność konkretnego działania; `false` wyklucza nieuzgodnioną propozycję |
| `assumptions` opcji | Jawne warunki, źródła kosztów i zależność od potwierdzenia otwarcia |
| `origins`, `destinations`, `profiles`, `horizon` | Stały zbiór relacji i wspólny horyzont oceny wszystkich opcji |

Naprawa zawiera `kind: "repair"`, `asset_id`, `feature`, `value`, `effective_from` i `valid_until`, ewentualnie kilka `features`. `resolves_restriction_ids` wskazuje konkretne ograniczenia objęte działaniem. Sama poprawa szerokości nie usuwa niezależnego zamknięcia przejścia. Wykonalność wymaga całego zestawu napraw, a wynik nie sumuje dwa razy tej samej odzyskanej relacji.

„Sprawdź strukturę” kontroluje format. „Zapisz i oceń katalog” tworzy zamrożony scenariusz i zadanie trwałego workera. Pełne reguły wykonalności, zasobów, krytycznych relacji i dojścia rozstrzyga silnik. `enumeration` przegląda skończone kombinacje, a `cp_sat` optymalizuje katalog i jawną pulę legalnych ścieżek. Wynik pokazuje status, zakres optimum, limity oraz ponowną weryfikację na pełnym grafie. Przerwanie nie dowodzi odcięcia nieprzeliczonych relacji.

Zapis scenariusza pozwala później przejść decyzję, wykonanie i kontrolę efektu. Zmiana warstwy w czasie edycji nie przenosi szkicu automatycznie. Pobierz go, przełącz dane i jawnie wczytaj właściwy katalog lub przywróć przykład nowego grafu.
