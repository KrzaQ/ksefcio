# ksefcio

Przeglądarka faktur z KSeF z generatorem plików przelewów bankowych.

## Co to jest

Aplikacja webowa do przeglądania faktur pobranych z Krajowego Systemu e-Faktur (KSeF) oraz generowania plików przelewów w formacie mBank (Elixir). Skierowana do polskich firm — obsługuje wiele podmiotów (JDG + spółka) w ramach jednego certyfikatu.

### Główne funkcje

- **Synchronizacja z KSeF** — pobieranie faktur przychodowych z KSeF za ostatnie 12 miesięcy
- **Przeglądanie faktur** — sortowanie, filtrowanie, rozwijane szczegóły z pozycjami (FaWiersz)
- **Obsługa wielu NIP-ów** — przełączanie między podmiotami w ramach jednego certyfikatu
- **Generowanie przelewów** — zaznaczanie faktur i eksport do pliku CSV w formacie mBank (do 32 przelewów na plik)
- **Oznaczanie faktur** — oznaczanie jako opłacone lub ignorowane
- **Kwota do zapłaty** — automatyczne rozpoznawanie kwoty z sekcji Rozliczenie > DoZaplaty (np. faktury notarialne z PCC)

### Czego nie robi

- Nie jest programem księgowym — nie generuje faktur, nie prowadzi ksiąg
- Nie przechowuje danych w formie jawnej na serwerze

## Wymagania

- Certyfikat KSeF (.pem + .key) wydany przez Ministerstwo Finansów
- Docker (do uruchomienia produkcyjnego) lub Python + Node.js (do developmentu)

## Uruchomienie

### Development

```bash
make dev-backend    # serwer FastAPI
make dev-frontend   # serwer Vite (proxy API do backendu)
```

### Produkcja

```bash
make build          # buduje obraz Docker (multi-stage: Vue + FastAPI)
make deploy         # zdefiniowane w Makefile.local
```

Pojedynczy kontener Docker. Baza SQLite montowana jako volume.

## Stack technologiczny

- **Backend**: Python, FastAPI — minimalny serwer proxy + CRUD zaszyfrowanych blobów
- **Frontend**: Vue.js + Vite — cała kryptografia (Web Crypto API), parsowanie faktur, UI
- **Baza danych**: SQLite
- **Uwierzytelnianie**: certyfikaty KSeF — challenge-response z podpisem kluczem prywatnym

## Model bezpieczeństwa

### Serwer zero-knowledge

Treści faktur są **szyfrowane po stronie przeglądarki** przed wysłaniem na serwer. Serwer przechowuje wyłącznie zaszyfrowane bloby.

- Przeglądarka generuje losowy klucz AES do szyfrowania faktur
- Klucz AES jest opakowywany (szyfrowany) kluczem publicznym z certyfikatu użytkownika i przechowywany na serwerze w formie zaszyfrowanej
- Odpakowywanie klucza AES odbywa się w przeglądarce za pomocą klucza prywatnego

### Co zostaje w przeglądarce

- Operacje na kluczu prywatnym (podpisywanie zapytań, odpakowywanie klucza AES)
- Surowy materiał klucza prywatnego nie jest wysyłany na serwer

### Co opuszcza przeglądarkę

- **Certyfikat** jest wysyłany z podpisanymi zapytaniami API (nagłówek `X-Cert`), aby serwer mógł zweryfikować podpis
- Podczas uwierzytelniania z KSeF dane certyfikatu są częścią podpisanego żądania XAdES

Innymi słowy: **klucze prywatne pozostają po stronie klienta; certyfikaty są przesyłane w celach weryfikacji/uwierzytelniania.**

### Zakres szyfrowania

- Treści faktur są szyfrowane algorytmem AES-GCM w przeglądarce przed zapisem
- Backend/baza danych nie może odszyfrować treści faktur bez materiału klucza użytkownika

### W przypadku wycieku bazy danych

Atakujący **nie uzyska** jawnych treści faktur, ale pewne metadane są jawne z założenia:

- tożsamość użytkownika (NIP/PESEL), nazwa
- fingerprint certyfikatu
- zaszyfrowany blob klucza AES
- powiązanie faktura-użytkownik, NIP, numer KSeF, flagi opłacona/ignorowana
- znaczniki czasu rekordów

**Poufność treści faktur — tak. Pełna poufność metadanych — nie.**

### Przechowywanie lokalne

Dla wygody użytkowania przeglądarka przechowuje certyfikat i zaszyfrowany klucz prywatny PEM (chroniony hasłem, PKCS#8) w localStorage, a klucz AES w IndexedDB jako nieekstrahowalny `CryptoKey`.

Kompromitacja przeglądarki (np. XSS, malware) może ujawnić te lokalne artefakty.

## Licencja

[AGPL-3.0](LICENSE)
