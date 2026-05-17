# Query Intelligence Endpoint

- Built a FastAPI app with `POST /queries` and `GET /queries/{id}`.
- `POST /queries` accepts a natural-language query, runs structured extraction through Anthropic when `ANTHROPIC_API_KEY` is set, stores the result in SQLite, and returns the saved record.
- `GET /queries/{id}` reads the stored record back from SQLite.
- Added a small local fallback extractor so the app still works in development if no API key is present or the model response is unavailable.

## Run

- Install dependencies: `pip install -r requirements.txt`
- Set `ANTHROPIC_API_KEY` in `.env`
- Start the API: `uvicorn main:app --reload`

## Example

- `POST /queries`
```json
{
  "query": "find battery technology startups in Southeast Asia"
}
```

## With More Time

- I would add automated tests around the extraction pipeline and tighten the LLM contract with schema-enforced parsing plus richer error observability.
