# Amparacán Wiki

An editable, cross-linked wiki for **Amparacán**, a fictional island city-state
with documented history from the 1650s to the 2060s (part of the worldbuilding
project *Haroun*).

## What's here

This repo currently holds the **self-contained artifact** version of the wiki
plus the data pipeline that builds it. A full Next.js + Supabase + Vercel build
is planned (see *Next steps*).

```
scripts/parse_streets.py   Parse the Streets sheet (markdown-table export) → data/streets.json
scripts/build_data.py      Combine streets + curated People/Places/Parties/Heads-of-state → data/wiki_data.json
data/streets.json          309 parsed streets
data/wiki_data.json        Full dataset: 519 entities + 436 relationships + 53 head-of-state terms
wiki_template.html         Artifact source with a __WIKI_DATA__ placeholder
wiki.html                  Built artifact (template + embedded dataset)
```

## Rebuild

```bash
python3 scripts/parse_streets.py      # needs the Streets sheet export (see build_data notes)
python3 scripts/build_data.py         # writes data/wiki_data.json
python3 - <<'PY'                       # inject the dataset into the template
import json
tpl=open('wiki_template.html').read()
obj=json.loads(open('data/wiki_data.json').read()); obj['revisions']=[]
data=json.dumps(obj,ensure_ascii=False,separators=(',',':'))
open('wiki.html','w').write(tpl.replace('__WIKI_DATA__', data.replace('<','\\u003c')))
PY
```

## The world's data

Five private Google Sheets (~1,400 named entities across Characters, Streets,
Buildings, Government, Geography). The sheets are working documents — merged
cells, planning grids, working notes — so Streets is parsed programmatically
and the other entity types are curated. The Buildings sheet is mostly
per-neighbourhood typology *standards* rather than named places and is not yet
imported.

## Architecture (the core constraint)

Every fact lives **exactly once** as a record; every page renders by querying
those records, so editing one entry propagates to every page that references
it. Cross-entity links (street → neighbourhood, street → namesake person, head
of state → party) live as relationships, never as copied text.

## Editing

The artifact is editable in place: open any article → **Edit** → structured
fields. Saves write a revision (viewable per article) and re-publish a new
shared version; read-only viewers fall back to local (per-device) edits.

## Next steps — full stack build

- Supabase project **Amparacan Wiki** already exists with the 9-table schema
  applied (entities, people, places, streets, street_neighborhoods,
  political_parties, heads_of_state, entity_relationships, revisions) plus
  slug_redirects, pg_trgm and indexes.
- Remaining: RLS + revision trigger, load `data/wiki_data.json` into Postgres,
  scaffold Next.js 15 (App Router, RSC, Tailwind), build pages/search/edit
  forms, deploy to Vercel.
