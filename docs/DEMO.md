# Scenariusz demonstracji

Prowadzący: Michał Kiełtyka, DEFOZO SOFTWARE HOUSE. Wszystkie poniższe zdarzenia są syntetyczne. Data modelu: 3.10.2026, Europe/Warsaw. Demo nie opisuje aktualnych remontów w Krakowie.

Przygotowanie: uruchom aplikację instrukcją README, otwórz drugi widok mieszkańca w oddzielnej sesji, zachowaj czyste fixture do obliczenia referencji. Zmiany demo zapisuj w warstwie fixture. Nie resetuj bazy z realnymi zgłoszeniami. Kontrolę algorytmu można powtórzyć na świeżym `build_fixture()` bez zmiany serwera.

## 1. Konflikt robót i stały zbiór oceny

„Dwa dojścia prowadzą do tej samej przychodni. Każde zamknięcie osobno zostawia alternatywę. Sprawdzamy je razem i uwzględniamy także zmianę warunków po wyjściu.”

Otwórz „Ciągłość dostępu” i oblicz konflikt. Pokaż X 08:00-14:00, Y 10:00-16:00, dwa początki, jeden cel oraz 30 minut na podróż. Wynik: **9 godzin relacji** bez potwierdzonego dojścia. W diagnostyce/eksporcie chwilowa utrata wynosi **8 godzin**. Godziny relacji dotyczą zbioru oceny, a nie liczby mieszkańców. Wyjścia od 09:30 do 14:00 nie mają jednej ścieżki ważnej przez całe okno.

## 2. Trzy warianty

| Wariant | Oczekiwany wynik i wyjaśnienie |
| --- | --- |
| Y 14:30-20:30, X otwarte o 14:00 | 30 min wspólnej drożności, odzysk 9 h relacji; założenie otwarcia X wymaga nowego dowodu |
| Y 14:00-20:00 | Ciągłość chwilowa, ale 1 h relacji nadal bez potwierdzenia całych podróży; krytyczny warunek niespełniony |
| Y 14:30-20:30, otwarcie X opóźnione | Nowa utrata 0,5 h relacji, wynik netto +8,5 h; dodatnia średnia nie spełnia krytycznego warunku |

Pokaż wspólną skalę map i horyzont, straty oraz niewiadome. W pełnym raporcie porównaj każde zamknięcie osobno (0 h utraty) i oba razem (9 h), profile, punkty oceny, listy relacji zyskujących i tracących oraz zmianę dystansu tam, gdzie oba warianty zapewniają dojście. Odczytaj jawne wagi, kolejność kryteriów i warianty niezdominowane. Koszt nieznany pozostaje nieznany. Zapis wariantu nie oznacza wykonania robót ani zmiany stanu rzeczywistego.

## 3. Mieszkaniec na telefonie

Otwórz „Moje dojście”. Ustaw początek, konkretną przychodnię, profil oraz godzinę. O godzinie 07:00 dane fixture pozwalają potwierdzić dojście. Porównaj godzinę konfliktu. Rozwiń wymagania, źródła i listę kroków. Zmień limit dystansu i pokaż, że przekroczony limit różni się od znanej blokady. Nieznana szerokość daje kontrolę, a nie zapewnienie dostępności. Profil opisuje wymagania, nie stan zdrowia. Dane demo nie kierują uczestnika na prawdziwą barierę.

## 4. Wspólna winda

W widoku odporności uruchom test awarii obiektu/grupy. Dwie geometrycznie różne trasy wykorzystujące jeden obiekt nie tworzą niezależnych alternatyw. Awaria windy usuwa wszystkie jej zależne krawędzie. Jeżeli bieżący graf ekranu nie zawiera przykładu windy, użyj dedykowanego testu `tests/domain/test_routing.py` oraz jego grafu kontrolnego; nie przypisuj windy do rzeczywistego adresu bez dowodu.

## 5. Zgłoszenie, moderacja, pomiar

W widoku mieszkańca zgłoś „Do sprawdzenia: szerokość obejścia”, wskaż obiekt i opcjonalne zdjęcie. Zachowaj prywatny link/status. W drugiej sesji przed moderacją nie pojawia się potwierdzona blokada. Operator w „Dowodach i sprawach” lokalizuje zgłoszenie, określa zakres i publikuje ostrzeżenie do weryfikacji. Drugie okno powinno zasygnalizować nową wersję i umożliwić ponowne obliczenie.

Utwórz zadanie kontroli szerokości. Podaj metodę, jednostkę, miejsce i znaczenie wyniku dodatniego oraz ujemnego. Weryfikator zapisuje syntetyczny pomiar wraz z czasem ważności, nakładem pracy i opcjonalnym prywatnym zdjęciem. Zdjęcie pozostaje załącznikiem, nie dowodem szerokości bez pomiaru. Operator przegląda załącznik i publikuje dowód. Publikacja dotyczy tylko szerokości. Pokaż historię sprawy i dowodu; inne aktywne ograniczenia nadal obowiązują.

## 6. Decyzja, wykonanie i efekt

Koordynator zapisuje scenariusz, uruchamia trwałą analizę i obserwuje postęp. Wybiera wariant, wskazuje odpowiedzialnego, wykonawcę, termin, warunki i uzasadnienie. Zapis `approved_plan` nie zmienia tras obserwowanych.

Przejdź do `in_progress`, następnie `performed` z dowodem wykonania. Dodaj odrębną nową obserwację właściwej cechy i opublikuj ją. Dopiero wtedy wykonaj przegląd efektu. Raport pokazuje prognozę wariantu, zaobserwowaną zmianę i relacje z niewystarczającymi danymi. Ujawnia inne zmiany, które mogły wpłynąć na wynik. Zachowaj także zero lub pogorszenie. Eksportuj JSON, CSV i GeoJSON.

## 7. Wygaśnięcie, konflikt i restart

Przykład domenowy z dowodem kończącym się podczas podróży powinien stracić potwierdzenie. Pokaż zadanie ponownej kontroli. Planowy koniec robót oraz anonimowe zgłoszenie otwarcia nie przywracają drożności. Przy równoczesnej edycji pokaż komunikat konfliktu i odśwież właściwą wersję. Ponów identyczne żądanie z tym samym kluczem: nie powstaje duplikat. Po restarcie otwórz tę samą sprawę i zapisany scenariusz.

## 8. Offline i wyłączone AI

Po pierwszym załadowaniu włącz tryb offline w narzędziach przeglądarki. Pokaż datę ostatniego zapisanego widoku i brak obietnicy bieżącej trasy. Zapisz lokalny szkic zgłoszenia lub kontroli. Stan „niewysłane” jest odrębny od potwierdzenia serwera. Szkic kontroli zachowuje pola pomiaru i nakład pracy; niewysłany plik zdjęcia trzeba ponownie wybrać po przywróceniu sieci. Wyślij szkic, obsłuż ewentualny konflikt i sprawdź pojedynczy zapis.

Uruchom aplikację bez `-WithAI`. Dodaj ręcznie treść źródła, obiekt, czas i wpływ na pieszych. Przejdź moderację, analizę i decyzję. Podstawowa funkcjonalność pozostaje dostępna. Przy włączonej ekstrakcji pokaż nieznane pola i obowiązkowy przegląd; zgodny JSON nie gwarantuje poprawnego wpływu na pieszych.

## Zakończenie

„Miasto bez odcięć łączy wykrycie kolizji robót z wyborem harmonogramu, kontrolą przejścia i oceną efektu decyzji. Na tym przykładzie widać, jak przesunięcie prac zmienia dostęp do przychodni i od czego zależy wynik. Następnym krokiem jest pilotaż na zinwentaryzowanym obszarze, z udziałem mieszkańców i pomiarem kosztu aktualizacji danych.”

Zakres wykonanych testów i przypisanie wyników do wersji opisuje [raport weryfikacji](VERIFICATION.md). Przygotowanie badania na realnym obszarze: [plan pilotażu](PILOT.md).
