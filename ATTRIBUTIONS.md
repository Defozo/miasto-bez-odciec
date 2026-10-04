# Źródła, biblioteki i użycie AI

Projekt: **Miasto bez odcięć**. Zespół: **DEFOZO SOFTWARE HOUSE**. Jedyny członek: **Michał Kiełtyka**, zgodnie z `TEAM.json`. Zestawienie opisuje faktycznie użyte zasoby, nie przenosi licencji jednego składnika na całą aplikację.

## Materiały zadania i przygotowanie

Projekt odpowiada na zadanie SMART CITY w HackYeah 2026. [Szczegóły zadania](https://drive.google.com/file/d/19i1NhqZOV0PR7LOnsl5ErHbJ5DFPJEbP/view) i [regulamin](https://drive.google.com/file/d/19gg_vvg2SnV0lkyPP7k5BY7DDka3xC47/view) są materiałami organizatora.

Materiały zadania, propozycje A/B/C/D, plan i katalog usług stanowiły wcześniejszy wkład przygotowawczy. Kod realizuje wybrany wariant „Miasto bez odcięć” z elementami pozostałych propozycji. Opis autorstwa nie oznacza, że wszystkie prace powstały w jednym oknie konkursowym.

## Znaczące użycie AI

OpenAI Codex wspierał analizę materiałów, projekt architektury i interfejsu, programowanie, debugging, testowanie oraz przygotowanie dokumentacji i prezentacji. Za zrozumienie, działanie, prawa i decyzje odpowiada zespół.

Opcjonalna funkcja produktu wykorzystuje model **`openai/gpt-oss-120b` przez Groq** do kandydatur ekstrakcji publicznych komunikatów. Licencja wag modelu Apache-2.0 nie zastępuje warunków hostowanego API. Źródła: [karta modelu OpenAI](https://huggingface.co/openai/gpt-oss-120b), [dokumentacja Groq](https://console.groq.com/docs/model/openai/gpt-oss-120b), [warunki Groq](https://groq.com/terms-of-use/).

Ekstrakcja nie decyduje o drożności i nie publikuje danych. Test 30 komunikatów rozróżnia poprawność schematu i pól. Pozostaje błąd wpływu na pieszych, wymagający korekty moderatora; poprawny JSON nie jest gwarancją poprawnej interpretacji.

Firecrawl jest opcjonalnym adapterem pozyskania publicznej treści z dopuszczonych źródeł: [dokumentacja](https://docs.firecrawl.dev/), [warunki](https://www.firecrawl.dev/terms-of-service). Nie wymaga go działanie ręcznego procesu.

## Referencja startera

[Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template), revision **1762adac607a1b29cfc4da129557780beea71616**, licencja [MIT](https://github.com/fastapi/full-stack-fastapi-template/blob/1762adac607a1b29cfc4da129557780beea71616/LICENSE), copyright Sebastián Ramírez. Lokalna kopia: `third_party/FASTAPI-TEMPLATE-LICENSE`; audyt: `third_party/fastapi-template-audit.json`; materiał audytu: `third_party/fastapi-template-security.py`.

Zakres: referencja architektury i przegląd kodu bezpieczeństwa. Zachowano wybór Argon2. JWT startera zastąpiono odwoływalnymi, losowymi sesjami opaque w ciasteczku i kontrolą CSRF. Nie przedstawiamy projektu jako pełnego klonu template ani jego kompletnego audytu. Własny model grafu, dowodów, obiegu spraw i planowania nie pochodzi z template.

## Główne biblioteki

Bezpośrednie zależności określają `requirements.txt` i `requirements-ingest.txt`. Kompletny lock Python z hashami znajduje się w `requirements.lock`, a lock frontendu w `apps/web/package-lock.json`. Poniżej główne bezpośrednie zależności; zależności przechodnie zachowują własne notices w dystrybucjach pakietów. Przy dystrybucji obrazów zachowaj także ich notices.

| Zasób | Wersja | Licencja | Zastosowanie i źródło |
| --- | --- | --- | --- |
| React / React DOM | 18.3.1 | MIT | Interfejs, [repozytorium](https://github.com/facebook/react) |
| TypeScript | 5.7.3 | Apache-2.0 | Typy, [repozytorium](https://github.com/microsoft/TypeScript) |
| Vite | 6.4.3 | MIT | Budowanie, [repozytorium](https://github.com/vitejs/vite) |
| MapLibre GL JS | 6.11.2 | BSD-3-Clause i notices składników | Mapa, [licencja](https://github.com/maplibre/maplibre-gl-js/blob/v6.11.2/LICENSE.txt) |
| Lucide React | 0.468.0 | ISC | Ikony, [repozytorium](https://github.com/lucide-icons/lucide) |
| FastAPI | 0.142.2 | MIT | API, [repozytorium](https://github.com/fastapi/fastapi) |
| Starlette | 1.7.0 | BSD-3-Clause | Warstwa ASGI, [repozytorium](https://github.com/Kludex/starlette) |
| Uvicorn | 0.34.2 | BSD-3-Clause | ASGI, [repozytorium](https://github.com/encode/uvicorn) |
| SQLAlchemy / Alembic | 2.0.40 / 1.15.2 | MIT | Trwałość i migracje, [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy), [Alembic](https://github.com/sqlalchemy/alembic) |
| psycopg | 3.2.6 | LGPL-3.0 | Sterownik PostgreSQL, [repozytorium](https://github.com/psycopg/psycopg) |
| GeoAlchemy2 | 0.17.1 | MIT | Typy przestrzenne, [repozytorium](https://github.com/geoalchemy/geoalchemy2) |
| argon2-cffi | 23.1.0 | MIT | Haszowanie haseł, [repozytorium](https://github.com/hynek/argon2-cffi) |
| python-multipart | 0.0.32 | Apache-2.0 | Upload, [repozytorium](https://github.com/Kludex/python-multipart) |
| Pillow | 12.3.0 | MIT-CMU | Walidacja i ponowne kodowanie zdjęć, [repozytorium](https://github.com/python-pillow/Pillow) |
| HTTPX | 0.28.1 | BSD-3-Clause | Pobieranie i integracje, [repozytorium](https://github.com/encode/httpx) |
| NetworkX | 3.5 | BSD-3-Clause | Narzędzia grafowe, [repozytorium](https://github.com/networkx/networkx) |
| OSMnx | 2.0.6 | MIT | Stos importu OSM, [repozytorium](https://github.com/gboeing/osmnx) |
| Shapely | 2.1.2 | BSD-3-Clause | Geometria, [repozytorium](https://github.com/shapely/shapely) |
| pyproj | 3.7.2 | MIT | Pomiary w EPSG:2180, [repozytorium](https://github.com/pyproj4/pyproj) |
| OR-Tools | 9.14.6206 | Apache-2.0 | CP-SAT, [licencja](https://github.com/google/or-tools/blob/v9.14/LICENSE) |
| pytest | 9.1.1 | MIT | Testy domeny/API/importu, [repozytorium](https://github.com/pytest-dev/pytest) |
| Playwright | 1.63.0 | Apache-2.0 | Testy przeglądarkowe, [repozytorium](https://github.com/microsoft/playwright) |
| axe-core / adapter Playwright | 4.10.3 / 4.10.2 | MPL-2.0 | Automatyczny audyt dostępności UI, [repozytorium](https://github.com/dequelabs/axe-core) |
| ReportLab / pypdf | 5.0.1 / 6.19.0 | BSD | Tworzenie i kontrola PDF, [ReportLab](https://www.reportlab.com/), [pypdf](https://github.com/py-pdf/pypdf) |
| PostgreSQL | obraz PostGIS 16 | PostgreSQL License | Baza, [licencja](https://www.postgresql.org/about/licence/) |
| PostGIS | obraz 16-3.5-alpine | GPL-2.0-or-later | Rozszerzenie przestrzenne, [projekt](https://postgis.net/) |
| Caddy | 2.10.2-alpine | Apache-2.0 | Reverse proxy, [repozytorium](https://github.com/caddyserver/caddy) |

OSMnx/NetworkX stanowią zainstalowany stos importu; własny importer i własne reguły routingu nie są pełnym silnikiem OSMnx. Zainstalowana biblioteka nie jest sama dowodem wykorzystania każdego jej API.

## Dane i grafika

Własny generator `domain/graph/fixture.py`, `fixtures/smart-city.json` i syntetyczne przypadki ekstrakcji: **CC0-1.0**, [tekst licencji](https://creativecommons.org/publicdomain/zero/1.0/). Wszystkie wydarzenia, pomiary i liczby referencyjne z fixture są syntetyczne. Współrzędne mają charakter ilustracyjny. Nie są zgłoszeniami realnych mieszkańców.

Pobrany kandydat sieci: **© OpenStreetMap contributors**, **ODbL-1.0**. Źródło: [OpenStreetMap i zasady atrybucji](https://www.openstreetmap.org/copyright), [ODbL](https://opendatacommons.org/licenses/odbl/1-0/), zapytanie przez [Overpass](https://overpass-api.de/). Import pozostaje staged i nie zawiera potwierdzonego audytu terenowego. ODbL obowiązuje niezależnie od licencji własnych fixture. Licencja danych nie daje nieograniczonego prawa korzystania z publicznych serwerów kafli; lokalny demonstrator nie jest zależny od zewnętrznego podkładu.

Zrzuty w pakiecie przedstawiają własny interfejs działający na fixture. Nie są wygenerowanymi zdjęciami infrastruktury. Prezentacja używa lokalnego fontu Arial z instalacji systemowej; pakiet nie dystrybuuje plików fontu osobno. Materiały nie zawierają zdjęć realnych zgłaszających.

## Granice potwierdzeń

Dane demonstracyjne są syntetyczne. Import OSM wymaga kontroli terenowej przed publikacją potwierdzonych dojść. Warunki użycia i zakres przeprowadzonych testów opisuje [instrukcja testowania](docs/VERIFICATION.md).

## Audio filmu konkursowego, wersja v3

Polski lektor został wygenerowany na jawne zlecenie użytkownika w ElevenLabs z dostępnego głosu premade **Bella - Professional, Bright, Warm** i modelu `eleven_multilingual_v2`, na uwierzytelnionym koncie `payg`. Nie klonowano głosu użytkownika. [Zasady publikacji ElevenLabs](https://help.elevenlabs.io/hc/en-us/articles/13313564601361-Can-I-publish-the-content-I-generate-on-the-platform) pozwalają na komercyjne użycie treści utworzonych na płatnym planie, z zastrzeżeniem [warunków dostawcy](https://elevenlabs.io/terms-of-use) i [warunków usług](https://elevenlabs.io/service-specific-terms). Źródła sprawdzono 3 października 2026.

Podkład jest oryginalną kompozycją instrumentalną utworzoną lokalnie z oscylatorów i deterministycznego szumu, bez cudzych nagrań i sampli. Własny kod kompozycji i instrumental udostępniamy na [CC0-1.0](https://creativecommons.org/publicdomain/zero/1.0/) w zakresie praw przysługujących twórcom projektu. Ta deklaracja nie obejmuje lektora ElevenLabs.

Powyższe informacje o autorstwie, pochodzeniu i licencjach zachowaj przy przekazywaniu kodu oraz materiałów demonstracyjnych.
