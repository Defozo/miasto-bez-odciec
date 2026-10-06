# Miasto bez odcięć

**DEFOZO SOFTWARE HOUSE · Michał Kiełtyka**

Zaplanuj remonty tak, by zachować dojście do przychodni, sklepu i przystanku. Miasto bez odcięć pokazuje, kiedy nakładające się zamknięcia odcinają usługę, oraz pozwala porównać terminy i obejścia przed zatwierdzeniem planu. Łączy pracę koordynatora, operatora danych i weryfikatora z widokiem dojścia dla mieszkańca.

[Otwórz demo](https://miasto-bez-odciec.34.116.152.48.sslip.io) · [Prezentacja PDF](https://miasto-bez-odciec.34.116.152.48.sslip.io/materialy/miasto-bez-odciec.pdf) · [Film](https://miasto-bez-odciec.34.116.152.48.sslip.io/materialy/miasto-bez-odciec-demo.mp4) · [Kod ZIP](https://miasto-bez-odciec.34.116.152.48.sslip.io/materialy/source-snapshot.zip) · [HackTribe](https://hackyeah2026.hacktribe.co/miasto-bez-odciec/)

## Zobacz skutki połączenia robót

Dwa zamknięcia mogą osobno pozostawiać obejście, a razem odcinać dostęp. Analiza sprawdza je we wspólnym horyzoncie, dla tych samych początków, celów i profili potrzeb. Porównanie pokazuje, kto w modelu zyskuje lub traci dojście, przez jaki czas oraz pod jakimi warunkami.

- **Czas całej podróży.** Dostępność przejść i ważność dowodów są sprawdzane w całym zadanym oknie dojścia, także gdy roboty rozpoczynają się w jego trakcie.
- **Rzeczywiste zależności modelu.** Dwie trasy korzystające z tej samej windy mają wspólny punkt awarii. Analiza odporności uwzględnia obiekty i grupy wspólnej awarii.
- **Wykonalny harmonogram.** Porównanie wariantów obejmuje terminy, zasoby, ich pojemność i okna dostępności oraz koszty. Warunki krytyczne i niewiadome pozostają widoczne przy wyniku.
- **Decyzja z historią.** Wybrany wariant prowadzi do zapisu odpowiedzialności, wykonania i nowej obserwacji. Można zestawić prognozę z zaobserwowaną zmianą i wyeksportować wynik.

## Od zgłoszenia do sprawdzonej informacji

1. Operator dodaje źródła, roboty i dowody dotyczące przejść oraz wejść do usług.
2. Koordynator porównuje harmonogramy i wybiera wariant z uzasadnieniem oraz warunkami realizacji.
3. Mieszkaniec wybiera początek, cel, godzinę i wymagania. Otrzymuje mapę i instrukcję dojścia albo wskazanie bariery lub potrzebnej kontroli.
4. Zgłoszenie trafia do moderacji i kontroli terenowej. Pomiar aktualizuje konkretną cechę przejścia, z metodą, jednostką i czasem ważności.
5. Po wykonaniu prac nowa obserwacja pozwala ocenić efekt decyzji.

Potwierdzone dojście, znana bariera i brak danych mają odrębne znaczenie. Zatwierdzenie planu ani planowy koniec robót nie zastępują dowodu otwarcia. AI może pomóc odczytać komunikat do przeglądu operatora; podstawowy proces planowania i podejmowania decyzji działa także bez usług AI.

## Sprawdź scenariusz dwóch zamknięć

Domyślna warstwa `fixture` zawiera **dane syntetyczne** z datą 3 października 2026 i godzinami Europe/Warsaw. Współrzędne ilustrują Kraków, ale nie opisują aktualnego stanu chodników. Importy OSM trafiają do stagingu i wymagają sprawdzenia przed publikacją. [Plan pilotażu](docs/PILOT.md) opisuje przygotowanie realnego obszaru, kontrolę danych i badanie z mieszkańcami.

W przykładzie dwie roboty powodują utratę **9 godzin relacji** dla dwóch początków i jednej przychodni. Przesunięcie Y na 14:30-20:30 daje prognozę odzysku 9 h przy potwierdzonym otwarciu X o 14:00. Jednostka dotyczy zadanego zbioru dojść, nie liczby mieszkańców. [Pełny scenariusz](docs/DEMO.md) wyjaśnia także opóźnione otwarcie, wspólną windę, zgłoszenia i działanie offline.

## Uruchomienie

Wymagane: Python 3.12, Node.js 20+ z npm, PowerShell i `psst` dostępne w PATH. W katalogu projektu uruchom:

```powershell
.\scripts\start.ps1 -Install
```

Skrypt tworzy `.venv`, instaluje zależności Python z `requirements.lock` z kontrolą hashy, wykonuje `npm ci` i build, zakłada brakujące sekrety w psst, uruchamia migracje, seed fixture, API oraz worker. Otwórz **http://127.0.0.1:8000**. Kolejny start: `.\scripts\start.ps1`. `Ctrl+C` zatrzymuje procesy, zachowując bazę `.data/smart-city.db` i pliki `.data/storage`.

Kontrola startowa zapisuje oznaczone rekordy testowe w fixture. Worker może potrzebować do 600 s na zimne załadowanie solvera. To osobny limit od budżetu analizy katalogu, domyślnie 30 s. Lokalnie dostępne jest demonstracyjne logowanie rolą; publiczny i kontenerowy wariant wymaga hasła.

Wariant PostgreSQL/PostGIS wymaga Docker Desktop:

```powershell
.\scripts\start.ps1 -Install -Docker
```

Otwórz **http://localhost:8087**. Compose uruchamia bazę, migracje, API, worker i Caddy. Baza i pliki mają trwałe wolumeny. `docker compose down -v` usuwa dane, więc nie służy do zwykłego zatrzymania.

## Konfiguracja

Jawne ustawienia: `.env.example` i `config/settings.json`. Sekrety przechowuj w psst, bez wpisywania wartości do repozytorium.

| Nazwa | Zastosowanie |
| --- | --- |
| `SMART_CITY_DB_PASSWORD` | Hasło bazy kontenerowej; URL powstaje w procesie |
| `SMART_CITY_OPERATOR_PASSWORD` | Hasło przy pierwszym utworzeniu operatora |
| `SMART_CITY_VERIFIER_PASSWORD` | Hasło przy pierwszym utworzeniu weryfikatora |
| `SMART_CITY_ADMIN_PASSWORD` | Hasło przy pierwszym utworzeniu administratora |
| `SMART_CITY_APP_SECRET` | Wpis zgodności konfiguracji; sesje opaque go nie używają |
| `GROQ_API_KEY` | Opcjonalna ekstrakcja komunikatów |
| `FIRECRAWL_API_KEY` | Opcjonalne pobieranie publicznych źródeł |

`scripts/bootstrap-secrets.py` tworzy tylko brakujące wpisy. Zmiana hasła w psst nie zmienia automatycznie istniejącego konta aplikacji. Adaptery AI są domyślnie wyłączone; opcja `-WithAI` włącza je także z `-Docker`. Podstawowy proces działa bez nich. Ekstrakcja używa `openai/gpt-oss-120b` przez Groq i wymaga moderacji.

## Testy i utrzymanie

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Podczas publikacji 4 października 2026 przeszło 125 testów Python oraz build frontendu z `npm ci`. Wcześniejsza walidacja obejmowała 9 scenariuszy przeglądarki i 41 kontroli HTTP na PostGIS. [Instrukcja testowania](docs/VERIFICATION.md) podaje zakres, polecenia oraz warunki interpretacji wyników.

Gotowość usługi sprawdza `/health/ready`, a stan workera, kolejki i aktualność dowodów są dostępne w diagnostyce dla uprawnionego operatora. [Instrukcja utrzymania](docs/OPERATIONS.md) opisuje backup, próbę odtworzenia, aktualizację, HTTPS i role.

## Dokumentacja

| Dokument | Zawartość |
| --- | --- |
| [Produkt i wartość](docs/PRODUCT.md) | Użytkownicy, decyzje, model utrzymania i pomiar korzyści |
| [Architektura](docs/ARCHITECTURE.md) | Dane, routing, solver, wersje i API |
| [Dane i katalog](docs/DATA-AND-CATALOG.md) | Import, profile, wejścia, zasoby i warianty |
| [Pilotaż](docs/PILOT.md) | Przygotowanie danych i sprawdzenie rozwiązania w terenie |
| [Demo](docs/DEMO.md) | Przepływ z oczekiwanymi wynikami |
| [Atrybucje](ATTRIBUTIONS.md) | Biblioteki, dane, wcześniejszy wkład, AI i licencje |
