#!/usr/bin/env python3
"""Build the embedded wiki dataset for the Amparacán artifact.

Combines the programmatically parsed Streets sheet (data/streets.json) with
curated People / Places / Political parties / Heads of state records
transcribed from the five worldbuilding sheets. Emits data/wiki_data.json:
a single object of entities + typed relationships that the artifact renders.
"""
import os, json, re, unicodedata
from collections import OrderedDict

STREETS = json.load(open("/home/user/worldbuilder/data/streets.json"))

def slugify(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "x"

entities = OrderedDict()      # slug -> entity dict
rels = []                     # {a, b, type, description}
ident = {}                    # (type, lower name) -> slug  (type-aware identity)

def add(name, etype, description="", **fields):
    key = (etype, name.lower())
    if key in ident:          # merge new facts onto an existing entity
        e = entities[ident[key]]
        if description and not e.get("description"):
            e["description"] = description
        for k, v in fields.items():
            if v not in (None, "", [], {}) and not e.get(k):
                e[k] = v
        return ident[key]
    slug = slugify(name)      # a street and a person may share a name -> suffix
    base = slug; i = 2
    while slug in entities:
        slug = f"{base}-{i}"; i += 1
    entities[slug] = {"slug": slug, "name": name, "type": etype,
                      "description": description, **fields}
    ident[key] = slug
    return slug

def find(name, etype):        # resolve a name to an entity of a given type
    return ident.get((etype, name.lower()))

def rel(a_slug, b_slug, rtype, desc=""):
    if a_slug and b_slug and a_slug != b_slug:
        rels.append({"a": a_slug, "b": b_slug, "type": rtype, "description": desc})

# ── PROVINCES ─────────────────────────────────────────────────────────────
PROVINCES = [
    ("Isla Capital","Autonóma",300660,83.44,30),("Palmares","Autonóma",5658,1.57,2),
    ("Monte Negro","Ecológica",12480,3.46,5),("Cordillera","Autonóma",848,0.24,1),
    ("Comarca","Ecológica",1165,0.32,2),("Santiago de las Sierras","Autonóma",13634,3.78,8),
    ("La Selva","Ecológica",565,0.16,1),("Valdemoro","Autonóma",8508,2.36,1),
    ("La Yara","Ecológica",328,0.09,1),("Oniria","Autonóma",10812,3.00,5),
    ("Costa Mística","Autonóma",3660,1.02,8),("Cascadas","Ecológica",642,0.18,1),
    ("Isla Santa Clara","Autonóma",1362,0.38,1),
]
prov_slug = {}
for i,(nm,cat,pop,share,ndist) in enumerate(PROVINCES,1):
    roman = ["I","II","III","IV","V","VI","VII","VIII","IX","X","XI","XII","XIII"][i-1]
    s = add(nm,"place",
            f"Province {roman} of Amparacán, an {cat.lower()} province with a population of {pop:,} across {ndist} electoral district{'s' if ndist!=1 else ''}.",
            place_type="province", province_of=cat, population=pop, pop_share=share,
            districts=ndist)
    prov_slug[nm] = s

# ── CITY NEIGHBOURHOODS (all in Isla Capital) ─────────────────────────────
# name, founded_decade, peak_decade, population(optional)
NEIGH = [
    ("Pueblo Viejo","1550s","1570s",None),("Aracay","1780s","1850s",None),
    ("Las Alamedas","1780s","1880s",None),("El Borde","1690s","1710s",None),
    ("Centro","1710s","1710s",None),("Plaza Canaro","1710s","1710s",None),
    ("Los Arcos","1780s","1830s",None),("Media Luna","1830s","1930s",None),
    ("Aldea de Soria","1790s","1840s",None),("Mesa Verde","1890s","1950s",None),
    ("La Serenidad","1720s","1880s",None),("Puerto Ángel","1870s","1890s",None),
    ("Colonia Rosas","1680s","1880s",None),("Islas de la Madrugada","1690s","1830s",1634),
    ("Playa Pálida","1870s","1880s",None),("Las Cruces","1760s","1790s",None),
    ("Artesanias","1880s","1890s",None),("Academia","1880s","1900s",None),
    ("Sacromonte","1910s","1920s",None),("Ensenada de Bermeo","1790s","1850s",None),
    ("Distrito del Sol","1890s","1920s",None),("Lacoba","1740s","1890s",None),
    ("El Amparo","1750s","1810s",None),("Roviria","1890s","1930s",640),
    ("Tanayac","1830s","1950s",3564),("El Ocaso","1720s","1940s",2052),
    ("Avanzada Neblinosa","1940s","1970s",998),("Villa Cascadas","1920s","1950s",1886),
    ("Paraíso",None,None,612),("Isla Calo","1840s","1840s",560),
]
for nm,f,p,pop in NEIGH:
    desc = f"A neighbourhood of the capital city of Amparacán, in the province of Isla Capital."
    if f: desc = f"A neighbourhood of the capital city of Amparacán, established in the {f} and growing fastest in the {p}."
    s = add(nm,"place",desc,place_type="neighbourhood",founded_decade=f,peak_decade=p,
            population=pop,parent=prov_slug["Isla Capital"])
    rel(s, prov_slug["Isla Capital"], "located in", "Neighbourhood of the capital")

# ── SETTLEMENTS (outer island towns/villages) ─────────────────────────────
SETTLE = [
    ("Santiago de las Sierras","Santiago de las Sierras",13380,"Town"),
    ("Monte Negro","Monte Negro",12424,"Town"),
    ("Ciudad Oniria","Oniria",8508,"Town"),
    ("Valdemoro","Valdemoro",6613,"Town"),
    ("Camargo","Cascadas",5814,"Town"),
    ("Puerto Remedios","Palmares",3860,"Port"),
    ("Santa Clara","Isla Santa Clara",1412,"Village"),
    ("Siete Robles","Cordillera",1156,"Village"),
]
for nm,prov,pop,typ in SETTLE:
    s = add(nm,"place",
            f"A {typ.lower()} in the province of {prov}, with a population of about {pop:,}.",
            place_type="settlement",population=pop,typology=typ,parent=prov_slug.get(prov))
    if prov in prov_slug: rel(s, prov_slug[prov], "located in", f"{typ} of {prov}")

# ── POLITICAL PARTIES ─────────────────────────────────────────────────────
# name, abbr, alignment, votes, pct, seats, year_est, ideology, status
PARTIES = [
    ("Partido Laboral Progresista","PLP","Left wing",68685,31.38,10,1939,"Socialism","governing"),
    ("Acción Solidaria Amparacana","ASA","Left wing",28192,12.88,4,2007,"Syndicalism","governing coalition"),
    ("Movilización Verde","MV","Left wing",28958,13.23,4,1994,"Environmentalism","governing coalition"),
    ("Movimiento Democrático Ciudadano","MDC","Centre left",11732,5.36,1,1988,"","independent"),
    ("Alianza Anarcosindicalista","AA","Far left",6085,2.78,1,1970,"Anarcho-syndicalism","independent"),
    ("Partido por la Renovación Cívica","PRC","Centre right",11404,5.21,1,2010,"","independent"),
    ("Alianza Republicana","AR","Centre right",56515,25.82,8,1848,"","opposition"),
    ("Fuerza Popular","FP","Right wing",2802,1.28,1,2012,"","opposition"),
    ("Vanguardia Popular","VP","Far left",1051,0.48,0,2004,"","active, no seats"),
    ("Partido Paz y Unión","PAZ","Third way",1773,0.81,0,2008,"","active, no seats"),
    ("Partido del Sol","SOL","Third way",1685,0.77,0,1999,"","active, no seats"),
]
DEFUNCT = [
    ("Independence Party","Independence Party"),("Movimiento Socialista de los Trabajadores","MST"),
    ("Frente Comunista Insular","FC"),("Camino Nuevo","CN"),("Refugio Internacional","RI"),
    ("Liberación","Liberación"),("Acción Liberal para el Municipio Amparacano","ALMA"),
    ("Progreso y Futuro","PF"),("Grupo Independiente Liberal","GIL"),
    ("Plan Conservador","PC"),("Partido Nueva República","PNR"),
]
party_by_abbr = {}
for nm,ab,al,votes,pct,seats,yr,ideo,status in PARTIES:
    s = add(nm,"political_party",
            f"A {al.lower()} political party of Amparacán ({ab}), founded in {yr}. In the 2020 election it took {pct}% of the vote and {seats} seat{'s' if seats!=1 else ''}.",
            abbreviation=ab,alignment=al,constituency=votes,vote_pct=pct,seats=seats,
            year_est=yr,ideology=ideo,status=status)
    party_by_abbr[ab]=s
for nm,ab in DEFUNCT:
    s = add(nm,"political_party",
            f"A defunct political party of Amparacán ({ab}).",
            abbreviation=ab,status="defunct")
    party_by_abbr[ab]=s

# ── PEOPLE: season rosters (season -> [ (name, note?) ]) ───────────────────
SEASONS = {
1:[("Doña Clara",""),("Alejandro Vázquez Merayo","Renegade and smuggler; founding figure of the settlement"),
   ("Ayedemir Raïs",""),("Marco Antonio Negredo",""),("Joaquín Valdivia",""),("Carmen Santa María","")],
2:[("Ignacio Talavera","Pirate captain of the Talavera Crew"),("Ibrahim Raïs",""),
   ("Alejandro Navarro","Pirate captain of the Navarro Crew"),("Héctor Cardoso",""),
   ("Valantino de Izarduy",""),("King Bakombo",""),("Ross Hamilton",""),("Lewis Kaine",""),
   ("Logan Emeere",""),("Ernesto Montero",""),("Deniel Moreau",""),("Néstor Azireño","Spanish naval officer and colonial governor")],
3:[("Martín Corrientes",""),("Marius Abaco","Slave King"),("Fausto Oliviera Renato","")],
4:[("Don Blas",""),("Francisco Crescencio","Opened the first library; shifted the town from a smuggler's haven toward a centre of knowledge"),
   ("Inocencio Cabral","Colonial Spanish leader"),("Próspero Valdés","Colonial Spanish leader"),
   ("Iván Vargas Rosario","Colonial Spanish leader")],
5:[("Don Rafael de Osuna","Mexican hacendado who moved to the island after the war of independence"),
   ("Benicio de Palos","Postmaster")],
6:[("Rubén Castañeda","Radical pamphleteer, executed"),("Ricardo Alameda",""),("Miguel Moreno",""),
   ("Ana María Rosas","Abbess of the Abadía de la Rosa"),("Antonio Lafayette",""),
   ("Hernán Avellaneda",""),("Rafael Montoya","")],
7:[("Alonso Avellaneda",""),("Verónica Castañeda",""),("Yuri Béringer",""),
   ("Osvaldo Rosero Valencia","Architect; longest-serving head of state"),("Natalia Sarmiento",""),
   ("Manuel Saravia","Poet"),("Lionel Amador Ay",""),("Iván Márquez","Rural revolutionary leader")],
8:[("Francisco Montalbán","Barber and community leader in Barrio Andaluz"),("Enrico Cardinelli",""),
   ("Gianluca Cardinelli",""),("Michael Cardinelli",""),("Vincent Cardinelli",""),
   ("Serena Cardinelli",""),("Enzo Cardinelli",""),("Gervasio Cardinelli",""),("Álvaro Coronado",""),
   ("Victoria Solís",""),("Antonio Freeman",""),("Ezequiel Morata","Police officer"),("Ángelo Garrido",""),
   ("Gervasio Avellaneda",""),("Tiago Emerson Ramires",""),
   ("Enrique Ricardo Wolff","Intellectual and journalist"),("Leon Kasparov",""),("Nahia Zanetti",""),
   ("Giovani Orozco Martínez","Professor"),("Diana Valdéz",""),("Marat Rousseau",""),("Marc Lemaire","")],
9:[("Sofía Hidalgo",""),("Lucas Álvarez",""),("Ernesto Calderón",""),("Juan Castillo",""),
   ("Antonio Ramón Domínguez",""),("Antonio Bashara Riquelme","Non-aligned socialist; first head of state of Lebanese descent"),
   ("Rafael Serrat",""),("Javier Carranza","Installed by US occupation"),("Patricia Moriera",""),
   ("Guillermo Memonte Paz","Populist caudillo from Santiago de las Sierras with an aggressive international policy"),
   ("Raymond Lewis",""),("Samuel Carver",""),("Juan Jiménez Aguilar","Exporter"),("Diego Lorenti",""),
   ("Ángela Agramonte",""),("Adrien Morand",""),("Yana Kovalchenko",""),
   ("Víctor Yanik Vázquez","Playboy art dealer from a wealthy but disgraced family"),
   ("Zenaida Cruz","Pioneer pilot; completed the first air journeys to and from the island")],
10:[("Carlos Durán","Doctor")],
11:[("Santiago Macías","Teacher"),("Estefanía Luna","President Mayor; led the PLP–ASA–MV governing coalition"),
    ("Danica Ortega",""),("Manuela Díaz Leal","Physicist; led the team that discovered VALKO-1")],
}
def year_from_decade_span(span):  # "1650s-1690s" -> approx birth
    return None
for season,people in SEASONS.items():
    for nm,note in people:
        add(nm,"person",note,seasons=[season])

# ── HEADS OF STATE ────────────────────────────────────────────────────────
# (term_no, start, end, name, party_abbr, occupation, notes, era)
HOS = [
 (None,1658,1688,"Alejandro Vázquez Merayo",None,"Renegade, smuggler","Founding leader of the settlement","pirate"),
 (None,1688,1708,"Joaquín Valdivia",None,"",None,"pirate"),
 (None,1709,1713,"Ignacio Talavera",None,"Pirate","Captain of the Talavera Crew","pirate"),
 (None,1713,1716,"Alejandro Navarro",None,"Pirate","Captain of the Navarro Crew","pirate"),
 (None,1724,1738,"Néstor Azireño",None,"Spanish naval officer","Governor for the Spanish Empire","colonial"),
 (None,1744,1756,"Inocencio Cabral",None,"",None,"colonial"),
 (None,1756,1764,"Próspero Valdés",None,"",None,"colonial"),
 (None,1780,1785,"Víctor Hidalgo Acatzli de Salazar y Zamora",None,"",None,"colonial"),
 (None,1785,1791,"Iván Vargas Rosario",None,"",None,"colonial"),
 (None,1791,1798,"Próspero Valdés",None,"",None,"colonial"),
 (None,1806,1818,"Alonso Zamora",None,"","Spanish-appointed head; preferred the status quo, his wife did not","colonial"),
 (None,1818,1821,"Junta of Amparacán",None,"","Revolutionary junta (Teseo Domínguez de Mora, Héctor Ordóñez, Alejandro Vázquez Merayo)","independence"),
 (None,1821,1823,"José Venegas Morán",None,"","Cousin of the VI Count of Monclova; ruled under the First Mexican Empire","independence"),
 (1,1823,1828,"Eliseo de Moncada","Independence Party","",None,"independence"),
 (2,1828,1829,"Rúben Castañeda","Independence Party","","Radical pamphleteer","independence"),
 (3,1829,1838,"Eliseo de Moncada","Independence Party","","Second, non-consecutive term","independence"),
 (4,1838,1848,"Teseo Domínguez de Mora","Independence Party","Savant",None,"independence"),
 (5,1848,1850,"José María Pedraza","PF","Army veteran and lawyer",None,"independence"),
 (6,1850,1852,"Celestino Hernández Lara","PC","",None,"independence"),
 (7,1852,1856,"Teseo Domínguez de Mora","Independence Party","Savant","Non-consecutive term","independence"),
 (8,1856,1860,"Antonio Ramón Domínguez","PC","",None,"independence"),
 (9,1860,1862,"Sergio Méndez","PF","",None,"independence"),
 (10,1862,1866,"Jesús Marín Mendoza","PC","",None,"independence"),
 (11,1866,1896,"Osvaldo Rosero Valencia","PF","Architect","Longest-serving head of state; effective oligarchy in this period","independence"),
 (12,1896,1900,"Zacarías Gálvez Gallado","PC","",None,"independence"),
 (13,1900,1905,"Lautaro Santana","PF","","Switch to a presidency; first head of state of Maya descent","modern"),
 (14,1905,1910,"Aiser Carrasco","PF","",None,"modern"),
 (15,1910,1916,"Rafael Soler y Cárdenas","PC","",None,"modern"),
 (16,1916,1922,"Manuel Saravia","ALMA","Poet",None,"modern"),
 (17,1922,1924,"Hernán Vicario de Rayón","ALMA","Doctor","Distantly related to Andrés Quintana Roo","modern"),
 (18,1924,1929,"Ernesto Montero","PC","",None,"modern"),
 (19,1929,1932,"Antonio Saravia","ALMA","Lawyer",None,"modern"),
 (20,1932,1936,"Ezequiel Morata","CN","Police officer",None,"modern"),
 (21,1936,1938,"Giovani Orozco Martínez","GIL","Professor",None,"modern"),
 (22,1938,1940,"Anibal Báez Fuentes","PC","","Illegitimate son of T. O. B. Báez Machado; raised in a Santo Domingo orphanage","modern"),
 (23,1940,1949,"Enrique Ricardo Wolff","ALMA","Journalist","Intellectual and journalist","modern"),
 (24,1949,1954,"Benicio Carmona","ALMA","Printer","First head of state of African descent","modern"),
 (25,1954,1957,"Juan Castillo","PC","",None,"modern"),
 (26,1957,1962,"Benicio Carmona","ALMA","Printer","Non-consecutive term","modern"),
 (27,1962,1962,"Javier Carranza",None,"","Installed by US occupation","modern"),
 (28,1962,1964,"Enrique Ricardo Wolff","ALMA","Journalist","Non-consecutive term","modern"),
 (29,1964,1972,"Antonio Bashara Riquelme","MST","Doctor","Non-aligned socialist; first head of state of Lebanese descent","modern"),
 (30,1972,1974,"Juan Jiménez Aguilar","PC","Exporter",None,"modern"),
 (31,1974,1980,"Ximena de Arteaga","ALMA","Lawyer","First female head of state","modern"),
 (32,1980,1988,"Guillermo Memonte Paz","MST","Union organiser","Imprisoned in Mexico 1974–76; release secured by A. Bashara Riquelme","modern"),
 (33,1988,1995,"Ulises Salas Bravo","PC","Lawyer",None,"modern"),
 (34,1995,2003,"Carlos Durán","PLP","Doctor",None,"modern"),
 (35,2003,2008,"Mariano Lescay","ASA","Professor","First head of state of Haitian descent","modern"),
 (36,2008,2011,"Francisco Beltrán","PRC","Lawyer",None,"modern"),
 (37,2011,2015,"Santiago Macías","PLP","Teacher",None,"modern"),
 (38,2015,2028,"Estefanía Luna","PLP","","President Mayor; led the PLP–ASA–MV coalition","modern"),
 (39,2028,2030,"Juan Carlos Huerta","MV","",None,"modern"),
 (40,2030,2040,"Carla Ibáñez","MV","Environmental activist",None,"modern"),
]
heads=[]
for term,start,end,name,pab,occ,notes,era in HOS:
    psl = add(name,"person",notes or "",occupation=occ or None)
    # attach headline description if the person has none yet
    e=entities[psl]
    if not e.get("description"):
        role = "head of state of Amparacán"
        e["description"]=f"{name} served as {role} ({start}–{end}){', '+notes if notes else ''}."
    if occ and not e.get("occupation"): e["occupation"]=occ
    party_slug = party_by_abbr.get(pab) if pab else None
    heads.append({"term":term,"start":start,"end":end,"person":psl,
                  "party":party_slug,"occupation":occ,"notes":notes,"era":era})
    if party_slug: rel(psl,party_slug,"member of party",f"Head of state {start}–{end}")

# ── STREETS + cross references ────────────────────────────────────────────
# ensure a neighbourhood entity exists for every one referenced by a street
def ensure_neigh(nm):
    ex = find(nm,"place")
    if ex: return ex
    return add(nm,"place",
               "A neighbourhood of Amparacán referenced by the street register.",
               place_type="neighbourhood")

def ensure_person(nm, foreign=False):
    ex = find(nm,"person")
    if ex: return ex
    if foreign:
        desc = f"A figure from beyond Amparacán, honoured with a street in the city."
        return add(nm,"person",desc,origin="foreign")
    desc = "A local figure of Amparacán, honoured with a street in the city."
    return add(nm,"person",desc)

for st in STREETS:
    meaning = st["meaning"]
    slug = add(st["name"],"street",
               f"{st['type_full']} in Amparacán."+ (f" Named for: {meaning}." if meaning else ""),
               street_type=st["type_full"], category=st["category"],
               meaning=meaning, note=st["note"])
    for nm in st["neighbourhoods"]:
        nsl = ensure_neigh(nm)
        rel(slug,nsl,"runs through",f"{st['type_full']} in {nm}")
    # street named after a person? Create a stub for street-honoured people.
    cat = st["category"]
    if cat.startswith("Local people"):
        psl = ensure_person(meaning or st["name"])
        rel(slug, psl, "named after", f"Street honouring {entities[psl]['name']}")
    elif cat.startswith("Foreign people"):
        psl = ensure_person(meaning or st["name"], foreign=True)
        rel(slug, psl, "named after", f"Street honouring {entities[psl]['name']}")
    elif find(st["name"],"person"):
        rel(slug, find(st["name"],"person"), "named after", f"Street honouring {st['name']}")

# ── PORTRAITS (from exported Characters xlsx tabs) ─────────────────────────
def _norm(s):
    return unicodedata.normalize("NFKD", s).encode("ascii","ignore").decode().lower().strip()
def _lev1(a, b):  # True if edit distance between a and b is <= 1
    if a == b: return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1: return False
    if la == lb:  # single substitution
        return sum(x != y for x, y in zip(a, b)) == 1
    if la > lb: a, b, la, lb = b, a, lb, la   # ensure a shorter
    i = j = 0; diff = 0
    while i < la and j < lb:
        if a[i] == b[j]: i += 1; j += 1
        else:
            diff += 1; j += 1
            if diff > 1: return False
    return True

# era context for people who only appear here as portraits
ERA = {
 "Pirates era":      ("A pirate-era figure of Amparacán (17th–early 18th century).", [2]),
 "Legitimation era": ("A figure of Amparacán's colonial legitimation era (18th century).", [4]),
 "Independence era": ("A figure of Amparacán's independence era (early–mid 19th century).", [6]),
 "Early republic":   ("A figure of Amparacán's early republic.", [7]),
 "Sheet9":           ("A figure of Amparacán's history.", []),
}
PORT_PATH = "/home/user/worldbuilder/data/portraits.json"
if os.path.exists(PORT_PATH):
    portraits = json.load(open(PORT_PATH))
    people_norms = {_norm(e["name"]): e["slug"] for e in entities.values() if e["type"] == "person"}
    matched = new = 0
    for rec in portraits.values():
        nm, uri, sheet = rec["name"], rec["uri"], rec.get("sheet", "")
        k = _norm(nm)
        slug = people_norms.get(k)
        if not slug:  # fuzzy fallback: catch spelling variants (Abarco/Abaco)
            for kk, sl in people_norms.items():
                if _lev1(k, kk): slug = sl; break
        if slug:
            entities[slug]["photo"] = uri; matched += 1
        else:
            desc, seasons = ERA.get(sheet, ("A figure of Amparacán's history.", []))
            s = add(nm, "person", desc, seasons=seasons, photo=uri)
            people_norms[k] = s; new += 1
    print(f"portraits: matched {matched}, added {new} new people")

# ── finalise ──────────────────────────────────────────────────────────────
data = {
    "meta": {"title":"Amparacán","subtitle":"A wiki of the island city-state, 1650s–2060s"},
    "entities": list(entities.values()),
    "relationships": rels,
    "heads_of_state": heads,
}
json.dump(data, open("/home/user/worldbuilder/data/wiki_data.json","w"),
          ensure_ascii=False, separators=(",",":"))

from collections import Counter
tc = Counter(e["type"] for e in data["entities"])
print("entities:",len(data["entities"]), dict(tc))
print("relationships:",len(rels), dict(Counter(r["type"] for r in rels)))
print("heads of state:",len(heads))
print("bytes:", len(json.dumps(data,ensure_ascii=False)))
