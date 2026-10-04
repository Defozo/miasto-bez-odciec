# Testowanie i interpretacja wyników

Testy automatyczne korzystają z danych syntetycznych. Obejmują routing i całe okno podróży, konflikty robót, wspólne awarie, ważność dowodów, role, CSRF, idempotencję, wersjonowanie, zgłoszenia, pomiary oraz obieg decyzji i efektu.

## Zapisane wyniki

| Sprawdzenie | Wynik | Warunki |
| --- | --- | --- |
| Python przy publikacji 4.10.2026 | 125 testów zakończonych powodzeniem | Izolowany eksport źródeł, środowisko Python 3.12 |
| Frontend przy publikacji 4.10.2026 | `npm ci` i build zakończone powodzeniem | Przypięty `package-lock.json` |
| Przeglądarka podczas walidacji implementacji | 9 scenariuszy zakończonych powodzeniem | Przepływy aplikacji, klawiatura, offline, mobilny viewport |
| HTTP na Compose/PostGIS | 41 kontroli zakończonych powodzeniem | Logowanie, moderacja, zdjęcia, worker, decyzja i efekt |
| Katalog CP-SAT | 26 kontroli; `OPTIMAL` dla badanego katalogu i puli ścieżek | Kandydat ponownie sprawdzony na pełnym grafie fixture |
| Restart | 9 kontroli zakończonych powodzeniem | Zachowanie danych, sesji, wersji i uruchomienie workera |
| Odtworzenie PostGIS | Odczyt 9 scenariuszy i 9 prywatnych zdjęć, zgodne hashe plików | Izolowana baza odtworzona z backupu |
| Publiczne demo, 4.10.2026 | 23 kontrole w czystej przeglądarce poza serwerem | Obliczenia 9/+9 h, zmiana harmonogramu, trasa i bariera, mapy, uprawnienia |

To wyniki wykonanych sprawdzeń z podanymi warunkami, a nie gwarancja dostępności usługi w dowolnym późniejszym czasie.

## Powtórzenie

Po instalacji opisanej w [README](../README.md):

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Przy działającym lokalnym API:

```powershell
.venv\Scripts\python.exe scripts/benchmark.py --scale
.venv\Scripts\python.exe scripts/verify-catalog.py
.venv\Scripts\python.exe scripts/evaluate-extraction.py --output artifacts/extraction-baseline.json
```

W katalogu `apps/web`, przy działającej aplikacji:

```powershell
npm ci
npm run build
npx playwright install chromium
npm run test:e2e
```

Testy przepływów zapisują dane kontrolne, więc używaj wydzielonego fixture. Skrypty tworzą raporty lokalnie w `artifacts/`. Instrukcja [utrzymania](OPERATIONS.md) opisuje sprawdzenie restartu, backup i próbę odtworzenia. Wywołanie ekstrakcji z `--live` wymaga osobnego klucza i zużywa limit dostawcy; domyślna ocena nie włącza tej usługi.

## Wydajność i ekstrakcja

W zapisanym benchmarku 100 zapytań o trasę osiągnęło p95 28,56 ms i medianę 15,09 ms. Użyto rozgrzanego procesu na Windows 11, Python 3.12.5, Intel Core i9-14900KF i grafu `graph-fixture-v1`, bez cache wyników tras. Host nie był dedykowany benchmarkowi.

Ocena 6000 relacji zakończyła się po 25,05 s statusem `UNKNOWN` i wynikiem częściowym przy limicie 25 s. Nieprzeliczone relacje pozostają osobno oznaczone. Ten pomiar nie opisuje wydajności pełnej sieci miejskiej.

Ekstrakcja 30 komunikatów przez `openai/gpt-oss-120b` uzyskała poprawny schemat w 30/30 przypadków, lokalizację w 30/30 i wpływ na pieszych w 29/30. Wynik wymaga moderacji także wtedy, gdy JSON jest poprawny. Model nie wyznacza tras i nie publikuje blokad.

## Warunki użycia

Wynik 9/+9 h dotyczy syntetycznego grafu i zadanych godzin. Prognoza odzysku wymaga potwierdzenia otwarcia przejścia. W kontrolnym obiegu decyzji prognoza wyniosła +9 h, a zmiana zaobserwowana 0 h: sam zapis wykonania nie dodaje dowodu poprawy.

Import OSM nie potwierdza cech przejścia w terenie. Brak danych jest odrębnym wynikiem. Profile i koszty należy dopasować do rzeczywistego zastosowania. Do badania terenowego służy [procedura pilotażu](PILOT.md).

Testy interfejsu obejmowały klawiaturę, semantykę, kontrast i emulowany widok telefonu. Nie przeprowadzono badania z mieszkańcami, testu fizycznego telefonu ani odsłuchu działającego czytnika ekranu. Nie deklarujemy pełnej zgodności z WCAG. Po zmianie czasu nowy wynik należy odczytać w tabeli; aktualizacja nie ma komunikatu `aria-live`. Widok mieszkańca zachowuje tytuł głównego ekranu w karcie przeglądarki, a bieżący ekran wskazuje widoczny nagłówek i nawigacja.
