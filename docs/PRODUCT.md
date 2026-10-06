# Planowanie robót z zachowaniem dojścia do usług

Miasto bez odcięć pomaga koordynatorowi ocenić remonty z perspektywy mieszkańca: czy z danego miejsca, przy określonych potrzebach i godzinie wyjścia, pozostanie dojście do wybranej usługi. Wspólny model łączy harmonogram prac, przejścia, wejścia do budynków, dowody terenowe i zasoby potrzebne do realizacji wariantu.

## Wykryj konflikt przed zatwierdzeniem harmonogramu

Gdy dwa zamknięcia osobno pozostawiają obejście, ich łączny skutek łatwo przeoczyć. System porównuje je na tym samym zbiorze dojść i pokazuje czas utraty dostępu, relacje zyskujące i tracące oraz warunki wybranego wariantu. Analiza obejmuje całe okno podróży i wspólne zależności, takie jak winda używana przez kilka tras.

Koordynator może zestawić przesunięcia terminów i działania z katalogu, uwzględniając zasoby, okna pracy, pojemność oraz koszty. Wynik rozróżnia fizyczne przywrócenie dojścia od uzupełnienia brakującej wiedzy. To pozwala zdecydować, czy potrzebna jest zmiana organizacji robót, czy najpierw kontrola konkretnego przejścia.

## Wspólna praca czterech ról

| Użytkownik | Działanie | Wynik |
| --- | --- | --- |
| Koordynator robót | Porównuje terminy, obejścia, zasoby i koszty | Wariant z uzasadnieniem, skutkami dla profili i warunkami realizacji |
| Mieszkaniec | Wybiera cel, godzinę i wymagania | Mapa, instrukcja dojścia albo powód bariery lub niepewności |
| Operator danych | Importuje źródła, moderuje zgłoszenia i publikuje cechy | Wersjonowany stan z pochodzeniem i datą ważności |
| Weryfikator terenowy | Wykonuje przypisany pomiar | Obserwacja konkretnej cechy wraz z metodą, jednostką i czasem |

Potwierdzenie szerokości dotyczy szerokości, a odnotowane otwarcie dotyczy otwarcia. System zachowuje znaczenie każdej obserwacji i wskazuje wygasłe lub sprzeczne informacje. Brak pomiaru pozostaje niewiadomą.

## Połącz plan z oceną efektu

Wybrany wariant ma uzasadnienie, odpowiedzialnego, wykonawcę, termin i warunki. Rejestr wykonania oraz odrębna nowa obserwacja pozwalają zestawić prognozę z zaobserwowaną zmianą. Raport zachowuje także wynik zerowy, pogorszenie i relacje z niewystarczającymi danymi. Wyniki można wyeksportować do JSON, CSV i GeoJSON.

W syntetycznym [scenariuszu demonstracyjnym](DEMO.md) przesunięcie jednych robót zachowuje ich czas trwania i daje prognozę odzysku 9 godzin relacji. Warunkiem jest potwierdzone otwarcie drugiego przejścia o 14:00. Jednostka odnosi się do zadanego zbioru dojść; nie jest oszacowaniem korzyści dla całego miasta. Pilotaż terenowy i badanie z mieszkańcami pozostają do przeprowadzenia.

Przy pilotażu warto mierzyć czas potrzebny do poprawnej decyzji, wykryte kolizje, długość przerw w dojściu, pokrycie aktualnymi dowodami i czas aktualizacji danych. [Plan pilotażu](PILOT.md) opisuje przygotowanie obszaru, pracę z uczestnikami i kontrolę danych.

## Przygotowanie własnego obszaru

Aplikacja działa jako frontend, API, worker, baza i prywatny magazyn dowodów. SQLite umożliwia lokalny pokaz, a Compose uruchamia wariant PostgreSQL/PostGIS. Podstawowe funkcje działają bez płatnych usług AI. Import OSM, GeoJSON i CSV prowadzi przez staging oraz kontrolę topologii, wejść i cech przejść przed publikacją.

Wdrożenie obejmuje przygotowanie grafu i wejść, kontrolę danych, konfigurację środowiska oraz przeszkolenie operatora. Bieżący koszt zależy od hostingu, bazy, storage, kopii poza hostem, moderacji, pomiarów i rytmu zmian na danym obszarze. Opcjonalne API są rozliczane osobno według zużycia.

Właściciel danych wyznacza osoby uprawnione do publikacji i pomiarów oraz procedurę reakcji na rozbieżności. Przydział zadania w systemie rejestruje pracę; przyjęcie zlecenia przez zewnętrznego wykonawcę wymaga osobnego uzgodnienia. [Instrukcja utrzymania](OPERATIONS.md) opisuje role, aktualizacje, backup i odtwarzanie.
