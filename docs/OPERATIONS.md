# Uruchomienie i utrzymanie

Odpowiedzialny za kod i pakiet: DEFOZO SOFTWARE HOUSE, Michał Kiełtyka. Właściciel rzeczywistych danych miejskich i operator pilota wymagają osobnego uzgodnienia.

## Kontrola gotowości

`GET /health/live` potwierdza działanie procesu. `GET /health/ready` sprawdza dostęp do bazy, stan schematu, zapisywalny storage i aktywny graf. Osobno zwraca heartbeat workera i flagi adapterów. Po zakończeniu rozruchu zdrowe API z nieaktualnym heartbeat workera wymaga sprawdzenia kolejki; nie traktuj gotowości HTTP jako ukończenia analizy.

Worker zaczyna od stanu `initializing` i ładuje OR-Tools przed podjęciem zadań. Heartbeat zawiera stan solvera i `setup_s`. Lokalny skrypt startowy czeka maksymalnie 600 s na aktywność nowego workera rozpoznanego po identyfikatorze właściciela. Stary heartbeat sprzed restartu nie spełnia tego warunku. Czas inicjalizacji jest oddzielony od domyślnego 30-sekundowego budżetu obliczania katalogu; wynik analizy ujawnia `solver_setup_s`. Niedostępny adapter pozostawia proces ręcznej oceny dostępny, a żądanie CP-SAT otrzymuje jawny stan nierozstrzygnięty.

Zalogowany operator lub administrator sprawdza „Diagnostykę”, `/api/v1/diagnostics` i `/api/v1/audit`. Kontroluje zadania `queued/running/failed/stale`, liczbę prób, zaległe kontrole, daty źródeł i aktywne wersje. Wynik `stale` pozostaje w historii i nie powinien zastąpić nowszej decyzji. Logi Compose: `docker compose logs --tail 100 api worker migrate` uruchomione w procesie ze wstrzykniętymi sekretami wymaganymi do rozpatrzenia pliku Compose. Logów zawierających dane zgłoszeń nie dołączaj automatycznie do publicznych materiałów.

## Harmonogram utrzymania danych

Worker domyślnie co minutę kontroluje terminy ważności. Dla fixture używa kontrolowanego zegara, dla obserwacji aktualnego UTC. Wygaśnięcie tworzy ponowną kontrolę i wersję danych. Źródła z włączonym odświeżaniem otrzymują trwałe zadania; domyślny odstęp wynosi co najmniej 30 minut i wynika z jawnej konfiguracji. Niedostępność źródła zachowuje poprzedni zapis i jego prawdziwą datę.

Ustawienia pilota w `config/settings.json` są jawnymi założeniami: bazowy import co 7 dni, kontrola dynamicznych obejść maksymalnie co 4 godziny, geometria co 30 dni. Worker potrafi zaplanować pobranie kolejnego grafu i zapisać go wyłącznie w stagingu. Domyślne `graph_source: null` wyłącza pobieranie, dopóki operator nie wskaże źródła. Konfiguracja `graph_source` przyjmuje `url`, `format` (`osm` albo `geojson`), opcjonalne `method`, `body`, `layer` i `enabled`; adres można też przekazać przez `SMART_CITY_GRAPH_SOURCE_URL`. Adres musi przejść kontrolę publicznego hosta. Nowy graf wymaga ponownego przypisania ograniczeń i publikacji administratora.

Harmonogram programu nie wykonuje fizycznego pomiaru: właściciel wyznacza osoby i okna kontroli. Nowa organizacja ruchu unieważnia dotknięte dowody niezależnie od terminu rutynowej kontroli. Ponowne pobranie dokumentu nie zmienia daty obserwacji w terenie. Planowy koniec utrudnienia tworzy zadanie sprawdzenia otwarcia, nie otwiera przejścia.

## Sesje i role

Hasła są haszowane Argon2. Sesja używa losowego tokenu w HttpOnly, SameSite=Strict cookie, a baza przechowuje hash tokenu. W trybie publicznym cookie ma `Secure`; każda mutacja sesji wymaga CSRF i właściwego originu. Sesje wygasają po 8 godzinach. Konto wyłączone w bazie nie zachowuje uprawnień tylko dlatego, że ma cookie. Mechanizm lokalnych ról demonstracyjnych wymaga loopback i wyłączonego trybu publicznego.

Mieszkaniec korzysta z trasy bez rejestracji, a status zgłoszenia chroni prywatny losowy token. Nowe prywatne linki przechowują go we fragmencie po `#`, który nie trafia do żądania strony i jej logu dostępowego. Po odczycie interfejs zapisuje klucz na urządzeniu i czyści fragment. Link pozostaje prywatnym kluczem dostępu. Weryfikator zapisuje obserwację. Operator publikuje cechę oraz moderuje. Administrator odpowiada za operacje uprzywilejowane, m.in. kontrolę grafu. API egzekwuje role niezależnie od widoczności przycisków.

## Sekrety i adaptery

Nie zapisuj `.env` z wartościami kluczy. `psst` przekazuje wymagane sekrety wyłącznie do procesu i jego potomków. Dostęp do `GROQ_API_KEY` i `FIRECRAWL_API_KEY` jest potrzebny dopiero po włączeniu danego adaptera. Wybór modelu ma kolejność: jawny parametr wywołania, `SMART_CITY_GROQ_MODEL`, `groq_model` w konfiguracji, a następnie wbudowane ustawienie domyślne. Wydane ustawienie i udokumentowana ewaluacja korzystają z `openai/gpt-oss-120b`; schemat ekstrakcji ma wersję `notice-v2`.

Wynik ekstrakcji zachowuje hash tekstu, model, schemat, zużycie i oryginalną kandydaturę przy wykrytej sprzeczności. Cache zależy od treści, modelu oraz schematu. Wspólny limit wywołań to `SMART_CITY_ADAPTER_DAILY_CALL_LIMIT` (domyślnie 100), oddzielny od ceny faktury. Ograniczony czas, próby i budżet chronią ciągłość procesu ręcznego. Zmiana dostępności modelu lub warunków konta wymaga nowej próby i pomiaru, nie podmiany wyników historycznych.

Domyślny budżet analizy wyznacza `analysis_timeout_seconds` w konfiguracji, a jawne `time_limit_s` żądania ma pierwszeństwo. Publiczna analiza ma górny limit 10 s, analiza workera i przegląd efektu 300 s. Domyślna konfiguracja workera wynosi 30 s. Przekroczenie budżetu daje oznaczony wynik niepełny. Czas uruchamiania usługi i ładowania solvera jest raportowany osobno.

Fetcher dopuszcza wskazane publiczne hosty, weryfikuje adresy i przekierowania, ogranicza rozmiar i czas. Treść dokumentu nie jest instrukcją wykonania narzędzi. Własny host dopuszczaj po świadomej aktualizacji `SMART_CITY_SOURCE_HOSTS`. W razie awarii dostawcy zachowaj dokument i wypełnij formularz komunikatu ręcznie.

## Backup lokalny i kontrola odtworzenia

Na czas spójnej kopii bazy oraz plików dowodów zatrzymaj zapisy aplikacji. SQLite backup API daje spójny plik bazy, lecz kopiowanie dowodów jest odrębną operacją, dlatego cisza zapisu obejmuje oba kroki.

```powershell
.venv\Scripts\python.exe scripts/backup.py --verify
```

Kopia powstaje w `artifacts/private/backups/<czas UTC>/`. Zawiera `database.sqlite`, kopię dowodów i manifest SHA-256. `--verify` otwiera kopię, wykonuje `PRAGMA integrity_check` i zlicza tabele. To kontrola kopii; pełny odbiór wymaga również uruchomienia aplikacji na odtworzonych danych.

Odtwórz kopię do nowego katalogu roboczego. Zweryfikuj hashe manifestu, ustaw `DATABASE_URL` na nowy plik SQLite i `STORAGE_PATH` na nowy katalog dowodów. Uruchom migracje oraz aplikację z odrębnym portem lub po zatrzymaniu dotychczasowej. Sprawdź prywatne pliki, historię, status znanego zgłoszenia i scenariusz. Dopiero po odbiorze przełącz konfigurację. Zachowaj starą bazę. Nigdy nie odtwarzaj próbnie nad bieżącymi danymi.

## Backup PostgreSQL/PostGIS

Wymagane wpisy psst podczas poleceń Compose:

```powershell
psst --global SMART_CITY_DB_PASSWORD SMART_CITY_OPERATOR_PASSWORD SMART_CITY_VERIFIER_PASSWORD SMART_CITY_ADMIN_PASSWORD -- powershell -NoProfile -File scripts/backup-compose.ps1
psst --global SMART_CITY_DB_PASSWORD SMART_CITY_OPERATOR_PASSWORD SMART_CITY_VERIFIER_PASSWORD SMART_CITY_ADMIN_PASSWORD -- .venv/Scripts/python.exe scripts/verify-postgres-restore.py
```

Pierwszy skrypt zachowuje dump w formacie custom i archiwum prywatnego wolumenu dowodów. Na czas kopii wstrzymaj zapisy dla zgodności tych dwóch zasobów. Drugi korzysta z istniejącej zapisanej kopii: domyślnie z najnowszego kompletnego katalogu, a po podaniu `--backup <katalog>` z wybranego snapshotu. Zapisuje nazwę kopii i SHA-256 obu archiwów. Odtwarza dump do nowej izolowanej bazy o prefiksie `smartcity_restore_`, odczytuje liczniki oraz wersję PostGIS, rozpakowuje archiwum zdjęć i porównuje hashe plików.

Następnie uruchamia API na odtworzonej bazie i sprawdza gotowość, logowanie, trasę, audyt, odczyt scenariuszy oraz prywatnych zdjęć przez HTTP testowego klienta aplikacji. Usuwa bazę próbną i katalog aplikacji odtworzonej do testu. Wynik zapisuje w `artifacts/postgres-restore.json`. Nie modyfikuje bazy źródłowej ani zapisanej kopii. Odbiór kopii produkcyjnej wymaga dodatkowo kontroli kompletności oczekiwanych danych, zwłaszcza gdy liczba zdjęć w raporcie wynosi zero.

Produkcyjne odtworzenie wykorzystuje `pg_restore` do nowej bazy i archiwum do nowego wolumenu. Operator sprawdza migrację, odczyt dowodów i cały przepływ przed przełączeniem API oraz workera. Harmonogram, szyfrowanie, retencję i kopię poza hostem musi uzgodnić właściciel wdrożenia.

## Wydanie i powrót

Przed migracją zachowaj wersję kodu, lockfile frontendu, wersje Python, obrazy, manifest źródeł oraz kopię. Python jest instalowany z pełnego `requirements.lock` z hashami. Obrazy Node, Python, PostGIS i Caddy w Dockerfile oraz Compose są przypięte do digestów faktycznie pobranych obrazów. Manifest lokalnego pakietu zachowuje hashe plików i źródłowe archiwum również wtedy, gdy katalog nie jest repozytorium Git.

Zmianę schematu sprawdź na odtworzonej bazie. Nie wykonuj automatycznego downgrade po zapisaniu nowych danych. Powrót oznacza kompatybilne stare wydanie albo kontrolowane odtworzenie poprzedniej kopii po ocenie utraty nowych zapisów. Aktualizacja zależności wymaga ponowienia odpowiednich testów i audytu; sam niezmienny digest nie dowodzi braku podatności w przyszłości.

## Publiczne HTTPS

Compose domyślnie publikuje proxy tylko na `127.0.0.1:8087`. Repozytorium zawiera `config/Caddyfile.public` i `compose.public.yaml`, które przygotowują Caddy dla domeny oraz portów 80/443. Właściciel podaje domenę, DNS, serwer, TLS i odpowiedzialność za dane. Publiczny wariant zachowuje wolumen certyfikatów.

Po uzgodnieniu domeny i przygotowaniu serwera uruchom oba pliki Compose z ustawionym `SMART_CITY_DOMAIN`. Poniższy przykład opisuje wykonanie na docelowym serwerze; domenę zastąp rzeczywiście skonfigurowaną nazwą:

```powershell
$env:SMART_CITY_DOMAIN = 'uzgodniona-domena.example'
psst --global SMART_CITY_DB_PASSWORD SMART_CITY_OPERATOR_PASSWORD SMART_CITY_VERIFIER_PASSWORD SMART_CITY_ADMIN_PASSWORD -- docker compose -f compose.yaml -f compose.public.yaml up --build -d --wait
```

Override używa `!override` dla portów, dlatego wymagany jest Docker Compose obsługujący ten znacznik. Utrzymuj serwer oraz DNS i zweryfikuj faktyczne uzyskanie certyfikatu przed odbiorem.

API i worker wymagają `SMART_CITY_PUBLIC_MODE=true`, `SMART_CITY_LOCAL_DEMO_AUTH=false` oraz `SMART_CITY_ORIGIN=https://<domena>`. Baza i storage pozostają prywatne. Przed przyjęciem realnych zgłoszeń ustal retencję, zakres informacji i procedurę usunięcia. Retencja opisuje faktycznie wykonywany proces operatora; aplikacja nie deklaruje automatycznego kompletnego usuwania danych według nieuzgodnionego harmonogramu.

Przy odbiorze wdrożenia sprawdź HTTPS z sieci poza serwerem, trasę, prywatne zgłoszenie, moderację w drugiej sesji, zmianę wersji i odczyt statusu. Gotowość HTTP i heartbeat workera kontroluj niezależnie od testu tych przepływów.

Publiczne demo: [https://miasto-bez-odciec.34.116.152.48.sslip.io](https://miasto-bez-odciec.34.116.152.48.sslip.io). Korzysta z trwałych danych testowych i HTTPS w Google Cloud. VM oraz proxy obsługują także drugi projekt; zatrzymanie całego hosta lub proxy wpływa na obie usługi. Przy własnym wdrożeniu użyj osobnego projektu Compose i jego wolumenów. Konto operatora oraz diagnostyka wymagają uprawnień.

## Granice odpowiedzialności

Wdrożenie miejskie wymaga właściciela danych, operatora publikacji, zastępstwa, rytmu kontroli, uzgodnionych profili, kosztów i dopuszczalnych wariantów robót. Wewnętrzne przypisanie zadania nie dowodzi przyjęcia zlecenia przez urząd lub wykonawcę. Stan demonstratora, potwierdzonego pilota i utrzymywanej usługi muszą pozostać osobno raportowane.

## Bieżąca obsługa

Na początku pracy sprawdź API, worker, nieudane zadania i terminy ważności źródeł. Wyznacz obsadę moderacji i pomiarów oraz zastępstwo. Kopie bazy i dowodów przechowuj poza hostem, sprawdzaj ich odtworzenie oraz kontroluj pojemność dysku i ważność certyfikatu. Po zmianie harmonogramu lub organizacji przejść sprawdź dotknięte relacje i zleć pomiary brakujących cech.

Nakład eksploatacyjny obejmuje hosting API/workera/bazy, storage, transfer, backup, moderację, pomiary i obsługę incydentów. Wariant podstawowy działa bez usług AI. Dla adapterów uwzględnij oddzielny limit i koszt wywołań. Konkretne stawki i częstotliwość kontroli wynikają z umowy i danych obszaru, nie z ustawień demonstracyjnych.
