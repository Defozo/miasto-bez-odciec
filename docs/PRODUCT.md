# Produkt i wartość

Miasto bez odcięć służy do oceny dostępu do usług podczas remontów i awarii. Jednostką analizy jest relacja: początek, profil potrzeb, cel i okno podróży. Pozwala to porównać harmonogramy na tym samym zbiorze dojść, z uwzględnieniem czasu, brakujących pomiarów i wspólnych zależności infrastruktury.

## Użytkownicy i decyzje

| Użytkownik | Działanie w aplikacji | Wynik |
| --- | --- | --- |
| Koordynator robót | Porównanie terminów, obejść, zasobów i kosztów | Wariant z uzasadnieniem, skutkami dla profili i warunkami realizacji |
| Mieszkaniec | Wybór celu, godziny i wymagań | Mapa, instrukcja dojścia albo powód bariery lub niepewności |
| Operator danych | Import, moderacja zgłoszeń i publikacja cech | Wersjonowany stan z pochodzeniem i datą ważności |
| Weryfikator terenowy | Wykonanie przypisanego pomiaru | Obserwacja konkretnej cechy wraz z metodą, jednostką i czasem |

Dwie roboty mogą osobno pozostawiać obejście, a łącznie odcinać usługę. Aplikacja pokazuje ten konflikt oraz wynik zmiany terminu przed zapisaniem decyzji. Nieznany koszt pozostaje nieznany; brak pomiaru nie staje się potwierdzeniem przejezdności.

## Co mierzyć

W demonstracyjnym grafie przesunięcie jednych robót zachowuje ich czas trwania i daje prognozę odzysku 9 godzin relacji. Warunkiem jest potwierdzone otwarcie drugiego przejścia o 14:00. To wynik modelu syntetycznego, a nie oszacowanie korzyści dla całego miasta.

Przy wdrożeniu porównuj czas potrzebny do poprawnej decyzji, wykryte kolizje, długość przerw w dojściu, liczbę relacji z pełnymi dowodami i czas aktualizacji danych. Po wykonaniu prac zapisuj nową obserwację. Raport oddziela prognozę od zmiany zaobserwowanej, zachowując także wynik zerowy lub pogorszenie.

## Wdrożenie i koszt utrzymania

Aplikacja działa jako frontend, API, worker, baza i prywatny magazyn dowodów. SQLite służy do lokalnego pokazu, a Compose uruchamia wariant PostgreSQL/PostGIS. Funkcje podstawowe nie wymagają płatnych usług AI.

Koszt wdrożenia obejmuje przygotowanie grafu i wejść, kontrolę danych, konfigurację środowiska oraz przeszkolenie operatora. Koszt bieżący obejmuje hosting, bazę, storage, kopię poza hostem, moderację, pomiary i reakcję na wygasające dowody. Opcjonalne API są osobną pozycją zależną od zużycia. Ceny i nakład pracy ustala się dla faktycznego obszaru oraz rytmu zmian; aplikacja nie zawiera cennika usług miejskich ani automatycznego rozliczania.

Właściciel danych wyznacza osoby uprawnione do publikacji i pomiarów, rytm kontroli oraz procedurę reagowania na rozbieżność. Przydział zadania w systemie jest rejestrem pracy i sam nie stanowi przyjęcia zlecenia przez zewnętrznego wykonawcę. [Utrzymanie](OPERATIONS.md) i [pilotaż](PILOT.md) opisują wykonanie tych kroków.
