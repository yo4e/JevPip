# Research data export

JevPip can export selected local research datasets without changing paper or live-trading state.

## Supported datasets

- `decision_traces`: live paper decision trace JSONL under `data/decision_traces/<instrument>/YYYY-MM-DD.jsonl`
- `fifty_outcomes`: Fifty+ directional outcome records under `data/fifty_outcomes/<instrument>/YYYY-MM-DD.jsonl`

## Formats

- **JSONL** preserves the stored records as-is and is the preferred lossless format.
- **CSV** flattens nested dictionaries using dotted column names. Lists are kept as compact JSON strings in a cell.

The export endpoint is read-only:

```text
GET /api/export/dates?dataset=decision_traces&instrument_id=USD_JPY
GET /api/export/research?dataset=decision_traces&instrument_id=USD_JPY&date=2026-09-28&format=csv
```

Downloaded filenames include dataset, instrument and date so runs are less likely to be mixed accidentally.

Exports are generated from local research files. They do not include API credentials and they do not add any order, cancel, replace or other live mutation path.

Generated exports are analysis artifacts and should not be committed to the public repository.
