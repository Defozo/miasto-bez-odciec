# Miasto bez odcięć

**DEFOZO SOFTWARE HOUSE · Michał Kiełtyka**

Miasto bez odcięć pomaga koordynować remonty tak, aby zachować dojście do przychodni, sklepu czy przystanku. Wykrywa sytuacje, w których dwa zamknięcia osobno pozostawiają obejście, ale razem odcinają usługę. Koordynator porównuje harmonogramy, mieszkaniec sprawdza dojście dla swoich potrzeb, a operator i weryfikator uzupełniają dane pomiarami.

[Otwórz demo](https://miasto-bez-odciec.34.116.152.48.sslip.io) · [Prezentacja PDF](https://miasto-bez-odciec.34.116.152.48.sslip.io/materialy/miasto-bez-odciec.pdf) · [Film](https://miasto-bez-odciec.34.116.152.48.sslip.io/materialy/miasto-bez-odciec-demo.mp4) · [Kod ZIP](https://miasto-bez-odciec.34.116.152.48.sslip.io/materialy/source-snapshot.zip) · [HackTribe](https://hackyeah2026.hacktribe.co/miasto-bez-odciec/)

## Jak działa

1. Operator dodaje źródła, roboty i dowody dotyczące przejść oraz wejść do usług.
2. Koordynator porównuje terminy robót, dostępność obejść, wymagane zasoby i koszty. Wynik pokazuje zyski, straty i warunki wybranego wariantu.
3. Mieszkaniec wybiera początek, cel, godzinę i wymagania. Otrzymuje mapę i instrukcję dojścia albo informację o barierze lub brakujących danych.
4. Zgłoszenie prowadzi do moderacji i kontroli terenowej. Nowy pomiar aktualizuje konkretną cechę przejścia.
5. Zapis decyzji, wykonania i nowej obserwacji pozwala porównać prognozę z zaobserwowanym efektem.

Obliczenia obejmują całe okno podróży oraz wspólne zależności tras, np. jedną windę. Brak danych jest osobnym stanem. AI może pomóc odczytać komunikat, ale wynik zatwierdza operator; trasy i harmonogramy liczy silnik reguł.

## Dane demonstracyjne

Domyślna warstwa `fixture` zawiera **dane syntetyczne** z datą 3 października 2026 i godzinami Europe/Warsaw. Współrzędne ilustrują Kraków, ale nie opisują aktualnego stanu chodników. Importy OSM trafiają do stagingu i wymagają sprawdzenia przed publikacją. Pilota terenowego i badania z mieszkańcami dotąd nie przeprowadzono.

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

Gotowość usługi sprawdza `/health/ready`, a stan workera, kolejki i aktualność dowodów są dostępne w diagnostyce dla uprawnionego operatora. [Instrukcja utrzymania](docs/OPERATIONS.md) opisuje backup, próbę odtworzenia, aktualizację, HTTPS i role. Publiczne demo zależy od utrzymania hostingu i DNS.

## Dokumentacja

| Dokument | Zawartość |
| --- | --- |
| [Produkt i wartość](docs/PRODUCT.md) | Użytkownicy, decyzje, model utrzymania i pomiar korzyści |
| [Architektura](docs/ARCHITECTURE.md) | Dane, routing, solver, wersje i API |
| [Dane i katalog](docs/DATA-AND-CATALOG.md) | Import, profile, wejścia, zasoby i warianty |
| [Pilotaż](docs/PILOT.md) | Przygotowanie danych i sprawdzenie rozwiązania w terenie |
| [Demo](docs/DEMO.md) | Przepływ z oczekiwanymi wynikami |
| [Atrybucje](ATTRIBUTIONS.md) | Biblioteki, dane, wcześniejszy wkład, AI i licencje |
