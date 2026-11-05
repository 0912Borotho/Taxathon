#!/usr/bin/env python3
"""
Mohoebi Connect - Taxathon prototype engine (PRACTICE DATA ONLY)

Builds a made-up Maseru universe of small businesses with a known right answer, then
produces records the way the six real places would:

  1. RSL register            (who is already registered)
  2. Wholesalers             (monthly purchases by shop; example names)
  3. Mobile money            (M-Pesa, Vodacom Lesotho; EcoCash, Econet Telecom Lesotho)
  4. Licences                (Liquor and Guesthouse: Ministry of Tourism; Snack Bar, General Dealer
                              and Services: Ministry of Trade; Butchery and livestock: Ministry of
                              Agriculture; Health Certificate: Ministry of Health)
  5. Utility accounts        (LEC electricity, WASCO water)
  6. Field agents            (what an agent sees on the ground)

The engine links the records into businesses, removes those already registered, scores the rest with
plain-language reasons, and sorts them into three groups: Ordinary (ready to visit), Exception
(check first) and Human review (officer to decide). It then tests itself against the known answer.

Usage: python3 mohoebi_engine.py <output_dir>
"""
import random, json, re, sys, os, difflib
from collections import defaultdict, Counter

SEED = int(os.environ.get("MOHOEBI_SEED", "2026"))
# PLACEHOLDER: monthly sales (M) above which a trader is treated as needing registration.
# Replace with the real Simplified Business Tax threshold from RSL.
THRESH = 12500
N_BIZ = int(os.environ.get("MOHOEBI_N", "420"))
OUT = sys.argv[1] if len(sys.argv) > 1 else "."
CALIBRATED = os.environ.get("MOHOEBI_FIXED") != "1"  # set MOHOEBI_FIXED=1 to run the first, uncalibrated rule
os.makedirs(OUT, exist_ok=True)
random.seed(SEED)

FIRST = ("Mamello Thabo Lerato Palesa Mathabo Tumelo Teboho Limpho Nthabiseng Karabo Ntsoaki Pule Motlatsi Puseletso "
         "Katleho Lineo Tsepo Mpho Refiloe Thato Libuseng Sello Bokang Neo Khotso Masechaba Lebohang Rethabile Nkopane "
         "Mosa Boitumelo Moleboheng Mookho Mampho Malefu Lipholo Letsatsi Thabang Tebello Tankiso Thulo Relebohile "
         "Pontso Pheello Nthati Napo Moliehi Mokete Mojalefa Moeketsi Khauhelo Itumeleng Fumane Dineo Bonang Seabata "
         "Matseliso Nteboheleng Ts'episo Lehlohonolo Tlali Masello Mapaseka Hlompho Kopano Lintle Tsholo").split()
LAST = ("Mokoena Molapo Letsie Mohapi Thamae Lebusa Ramokoena Nkhasi Matsoso Mofokeng Sekhonyana Lephoto Tsepe Rapitsi "
        "Mphutlane Khanyane Moteane Makara Ntlhoki Mosala Ramatla Phafoli Seboka Mahao Monyake Tlali Mpiti Khoabane "
        "Rakotsoane Sehlabaka Maqutu Hlalele Putsoane Chabeli Tau Mabote Nyanyadu Lekhooa Ntaote Mosuoe Majara Mapetla "
        "Lerotholi Ramaili Mohale Khati Mokhele Lebakeng Matela Mpholo Pitso Rametse Tsiu Thoahlane Moleko Mokete "
        "Motsamai Mphaki Mochochoko Makhetha Makotoko Mathealira Ramabele Nthunya Sebatane Seitlheko Selebalo Setsabi "
        "Thakhisi Thulo Tseuoa Hlaoli Hoohlo Jobo Kao Khasu Khoase Khalane Lebitsa Leboela Lenka Lesenyeho Letete "
        "Liphapang Lithebe Maama Mafatle Mahlelebe Maieane Makhoalibe Makoae Malefane Manyeli Masilo Matete Mathaba "
        "Mathibeli Mochaba Mohlomi Mokuoa Monaheng Monare Morahanye Motaung Motloheloa Mpeta Mphuthi Ntsane Nthako "
        "Ramohapi Rantsane Ranyali Sebusi Sefali Sekoai Senatla Shale Sebotsa Tsoeu Tsolo Thaanyane").split()
FIRST = [f.replace("'", "") for f in FIRST]

# licence key -> (licence name, issuing ministry). Mapping follows Maxwell's list; confirm with RSL.
LIC = {
    "liquor":  ("Liquor Licence", "Ministry of Tourism"),
    "accom":   ("Guesthouse Licence", "Ministry of Tourism"),
    "snack":   ("Snack Bar Licence", "Ministry of Trade"),
    "general": ("General Dealer Licence", "Ministry of Trade"),
    "service": ("Services Trading Licence", "Ministry of Trade"),
    "agri":    ("Butchery and Livestock Permit", "Ministry of Agriculture"),
    "health":  ("Health Certificate", "Ministry of Health"),
}
# type, kind, licence key, wholesaler pool, needs health certificate, weight in the population
TYPES = [
    ("general dealer", "goods", "general", "food", False, 3),
    ("tuck shop", "goods", "general", "food", False, 3),
    ("mini market", "goods", "general", "food", False, 2),
    ("butchery", "goods", "agri", "meat", True, 1),
    ("hardware", "goods", "general", "hardware", False, 1),
    ("snack bar", "goods", "snack", "food", True, 2),
    ("tavern", "goods", "liquor", "drinks", False, 2),
    ("hair salon", "service", "service", None, False, 2),
    ("tailoring", "service", "service", None, False, 1),
    ("car wash", "service", "service", None, False, 1),
    ("guesthouse", "service", "accom", None, False, 1),
    ("phone repairs", "service", "service", None, False, 1),
]
# Lines of business ("sectors"). Each behaves differently: how much of sales is spent on stock,
# and how much of sales arrives as mobile money. These ranges are made up for the practice data.
SECTORS = ["retail", "snack bar", "tavern", "butchery", "hardware", "services"]
SECTOR = {"general dealer": "retail", "tuck shop": "retail", "mini market": "retail", "butchery": "butchery",
          "hardware": "hardware", "snack bar": "snack bar", "tavern": "tavern"}  # everything else: services
PURCH = {"retail": (0.65, 0.80), "snack bar": (0.35, 0.50), "tavern": (0.50, 0.65), "butchery": (0.70, 0.82),
         "hardware": (0.60, 0.75), "services": (0.30, 0.50)}   # stock bought as a share of sales
MOBILE = {"retail": (0.15, 0.45), "snack bar": (0.20, 0.50), "tavern": (0.10, 0.35), "butchery": (0.10, 0.30),
          "hardware": (0.30, 0.60), "services": (0.35, 0.80)}  # share of sales paid by mobile money
# Example wholesaler names. In a pilot these come from RSL's own VAT register.
POOLS = {"food": ["Maseru Cash & Carry", "Thetsane Wholesale"], "drinks": ["Maluti Beverage Distributors"],
         "meat": ["Berea Meat Wholesalers"], "hardware": ["Lesotho Builders Supply"]}
TYPE_WORDS = {w for t, *_ in TYPES for w in t.split()}
AREAS = ["Thetsane", "Qoaling", "Lithoteng", "Khubetsoana", "Ha Abia", "Ha Matala", "Motimposo", "Maseru West"]
NEIGH = {a: AREAS[(i + 1) % len(AREAS)] for i, a in enumerate(AREAS)}
STOP = {"shop", "store", "trading", "the", "and", "ltd", "pty", "s"}
SRC_ORDER = ["register", "wholesaler", "mpesa", "ecocash", "licence", "lec", "wasco", "canvass"]
CAT = {"register": "register", "wholesaler": "wholesalers", "mpesa": "mobile money", "ecocash": "mobile money",
       "licence": "licences", "lec": "utility accounts", "wasco": "utility accounts", "canvass": "field agents"}


def phone():
    return "+266 " + random.choice("56") + "".join(random.choice("0123456789") for _ in range(7))


def typo(s):
    if len(s) < 5:
        return s
    i = random.randint(1, len(s) - 2)
    if random.random() < 0.5:
        return s[:i] + s[i + 1:]
    return s[:i] + s[i + 1] + s[i] + s[i + 2:]


def name_variant(b, person_prob):
    f, l, t = b["first"], b["last"], b["type"]
    if random.random() < person_prob:
        n = random.choice([f"{f} {l}", f"{f} {l}", f"{f[0]}. {l}"])
    else:
        n = random.choice([f"{f} {l} {t}", f"{f} {l} {t}", f"{f} {l} {t}", f"{f[0]}. {l} {t}", f"{l}'s {t}"])
    return typo(n) if random.random() < 0.10 else n


# ---------------------------------------------------------------- the made-up universe (known truth)
biz = []
for i in range(N_BIZ):
    t = random.choices(TYPES, weights=[x[5] for x in TYPES])[0]
    biz.append(dict(id=i, first=random.choice(FIRST), last=random.choice(LAST), type=t[0], kind=t[1], lic=t[2],
                    pool=t[3], health=t[4], area=random.choice(AREAS), phone=phone()))
# a few owners run two businesses on one phone (a real-world linking trap)
for b in random.sample(biz[:300], 5):
    t = random.choices(TYPES, weights=[x[5] for x in TYPES])[0]
    biz.append(dict(id=len(biz), first=b["first"], last=b["last"], type=t[0], kind=t[1], lic=t[2], pool=t[3],
                    health=t[4], area=b["area"], phone=b["phone"]))

for b in biz:
    b["sector"] = SECTOR.get(b["type"], "services")
for b in biz:
    b["registered"] = random.random() < 0.36
    if b["registered"]:
        b["trading"] = random.random() < 0.92
        b["turnover"] = random.lognormvariate(10.3, 0.8) if b["trading"] else 0
        if b["trading"]:
            b["nil_months"] = random.randint(8, 12) if random.random() < 0.08 else 0
        else:
            b["nil_months"] = 12 if random.random() < 0.7 else 0
    else:
        b["trading"] = random.random() < 0.82
        b["turnover"] = random.lognormvariate(9.1, 0.9) if b["trading"] else 0
        b["nil_months"] = 0
    b["target"] = (not b["registered"]) and b["trading"] and b["turnover"] >= THRESH

# ---------------------------------------------------------------- records from the six places
records = []


def add(src, detail, b, name, ph=None, value=None, activity=None, tin=None, nil=None, issuer=None,
        declared=None, sector=None):
    area = NEIGH[b["area"]] if random.random() < 0.07 else b["area"]
    records.append(dict(rid=len(records), src=src, cat=CAT[src], detail=detail, issuer=issuer, name=name,
                        phone=ph, area=area, value=value, activity=activity, tin=tin, nil_months=nil, declared=declared, sector=sector,
                        true_id=b["id"]))


for b in biz:
    t = b["trading"]
    # 1. RSL register
    if b["registered"]:
        tin = "TIN" + "".join(random.choice("0123456789") for _ in range(7))
        b["tin"] = tin
        add("register", "RSL register", b, name_variant(b, 0.05), b["phone"] if random.random() < 0.9 else None,
            tin=tin, nil=b["nil_months"], sector=b["sector"],
            declared=(b["turnover"] * random.uniform(0.85, 1.0) if (t and b["nil_months"] < 6) else 0))
    # 2. Wholesalers: one or two named wholesalers per shop, not all of them report
    if t and b["kind"] == "goods" and b["pool"]:
        pool = POOLS[b["pool"]]
        k = 1 if len(pool) == 1 else random.choice([1, 1, 2])
        chosen = random.sample(pool, k)
        purchases = b["turnover"] * random.uniform(*PURCH[b["sector"]])
        split = [1.0] if k == 1 else (lambda s: [s, 1 - s])(random.uniform(0.3, 0.7))
        for wname, share in zip(chosen, split):
            if random.random() < 0.65:
                add("wholesaler", wname, b, name_variant(b, 0.0), b["phone"] if random.random() < 0.7 else None,
                    value=purchases * share)
    # 3. Mobile money merchant accounts: M-Pesa, EcoCash, both, or cash only
    if t:
        r = random.random()
        channels = ["mpesa", "ecocash"] if r < 0.25 else ["mpesa"] if r < 0.60 else ["ecocash"] if r < 0.75 else []
        inflow = b["turnover"] * random.uniform(*MOBILE[b["sector"]]) * (4 if random.random() < 0.05 else 1)
        for ch in channels:
            if random.random() < 0.88:
                add(ch, "M-Pesa" if ch == "mpesa" else "EcoCash", b, name_variant(b, 0.5),
                    b["phone"] if random.random() < 0.8 else phone(), value=inflow / len(channels))
    # 4. Licences from the ministries (closed businesses often still hold one)
    if random.random() < (0.50 if t else 0.55):
        lname, issuer = LIC[b["lic"]]
        add("licence", lname, b, name_variant(b, 0.3), b["phone"] if random.random() < 0.4 else None, issuer=issuer)
    if b["health"] and random.random() < 0.20:
        lname, issuer = LIC["health"]
        add("licence", lname, b, name_variant(b, 0.3), b["phone"] if random.random() < 0.4 else None, issuer=issuer)
    # 5. Utility accounts: LEC electricity and WASCO water
    if random.random() < (0.40 if t else 0.45):
        add("lec", "LEC", b, name_variant(b, 0.7), b["phone"] if random.random() < 0.3 else None)
    if random.random() < (0.30 if t else 0.35):
        add("wasco", "WASCO", b, name_variant(b, 0.7), b["phone"] if random.random() < 0.3 else None)
    # 6. Field agents walking the area
    if random.random() < 0.25:
        if t:
            act = "busy" if b["turnover"] >= 20000 else ("moderate" if b["turnover"] >= THRESH * 0.5 else "quiet")
        else:
            act = "closed" if random.random() < 0.75 else "quiet"
        add("canvass", "Field agents", b, name_variant(b, 0.1), b["phone"] if random.random() < 0.5 else None,
            activity=act)

# ---------------------------------------------------------------- source files (the interface between "data" and "engine")
# MOHOEBI_EXPORT=dir  writes the six made-up source extracts and, separately, an answer key.
# MOHOEBI_SOURCES=dir makes the engine read those files only, so no figure is built into the engine.
import csv
SOURCE_FILES = [
    ("1_rsl_register.csv", ["register"], ["record_id", "tin", "taxpayer_name", "phone", "area", "line_of_business", "declared_monthly_sales_M", "nil_return_months_of_12"]),
    ("2_wholesalers.csv", ["wholesaler"], ["record_id", "wholesaler", "customer_name", "customer_phone", "area", "monthly_purchases_M"]),
    ("3_mobile_money.csv", ["mpesa", "ecocash"], ["record_id", "provider", "merchant_name", "merchant_phone", "area", "monthly_inflow_M"]),
    ("4_council_licences.csv", ["licence"], ["record_id", "licence_type", "issued_by", "holder_name", "phone", "area"]),
    ("5_utility_accounts.csv", ["lec", "wasco"], ["record_id", "utility", "account_name", "phone", "area"]),
    ("6_field_agents.csv", ["canvass"], ["record_id", "observed_name", "phone", "area", "activity"]),
]


def _row(r):
    n = lambda v: "" if v is None else v
    m = lambda v: "" if v is None else f"{v:.2f}"
    s_ = r["src"]
    if s_ == "register":
        return [r["rid"], n(r["tin"]), r["name"], n(r["phone"]), r["area"], r["sector"], m(r["declared"]), n(r["nil_months"])]
    if s_ == "wholesaler":
        return [r["rid"], r["detail"], r["name"], n(r["phone"]), r["area"], m(r["value"])]
    if s_ in ("mpesa", "ecocash"):
        return [r["rid"], r["detail"], r["name"], n(r["phone"]), r["area"], m(r["value"])]
    if s_ == "licence":
        return [r["rid"], r["detail"], r["issuer"], r["name"], n(r["phone"]), r["area"]]
    if s_ in ("lec", "wasco"):
        return [r["rid"], r["detail"], r["name"], n(r["phone"]), r["area"]]
    return [r["rid"], r["name"], n(r["phone"]), r["area"], r["activity"]]


def export_sources(d):
    os.makedirs(os.path.join(d, "answer_key"), exist_ok=True)
    for fname, srcs, cols in SOURCE_FILES:
        with open(os.path.join(d, fname), "w", newline="") as f:
            w = csv.writer(f); w.writerow(cols)
            for r in records:
                if r["src"] in srcs:
                    w.writerow(_row(r))
    with open(os.path.join(d, "answer_key", "answer_key_businesses.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["business_id", "owner_first_name", "owner_surname", "business_type", "area", "line_of_business", "registered", "trading", "true_monthly_sales_M", "nil_return_months_of_12", "should_be_registered", "tin"])
        for b in biz:
            w.writerow([b["id"], b["first"], b["last"], b["type"], b["area"], b["sector"], int(b["registered"]), int(b["trading"]), f"{b['turnover']:.2f}", b["nil_months"], int(b["target"]), b.get("tin", "")])
    with open(os.path.join(d, "answer_key", "answer_key_record_links.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["record_id", "true_business_id"])
        for r in records:
            w.writerow([r["rid"], r["true_id"]])


def load_sources(d):
    global records, biz
    f_ = lambda v: float(v) if v not in ("", None) else None
    i_ = lambda v: int(float(v)) if v not in ("", None) else None
    s_ = lambda v: v if v not in ("", None) else None
    recs = []
    base = dict(issuer=None, phone=None, value=None, activity=None, tin=None, nil_months=None, declared=None, sector=None)
    for fname, srcs, cols in SOURCE_FILES:
        for x in csv.DictReader(open(os.path.join(d, fname))):
            r = dict(base)
            r["rid"] = int(x["record_id"])
            if fname.startswith("1_"):
                r.update(src="register", detail="RSL register", name=x["taxpayer_name"], phone=s_(x["phone"]), area=x["area"], tin=s_(x["tin"]), sector=x["line_of_business"], declared=f_(x["declared_monthly_sales_M"]), nil_months=i_(x["nil_return_months_of_12"]))
            elif fname.startswith("2_"):
                r.update(src="wholesaler", detail=x["wholesaler"], name=x["customer_name"], phone=s_(x["customer_phone"]), area=x["area"], value=f_(x["monthly_purchases_M"]))
            elif fname.startswith("3_"):
                r.update(src="mpesa" if x["provider"] == "M-Pesa" else "ecocash", detail=x["provider"], name=x["merchant_name"], phone=s_(x["merchant_phone"]), area=x["area"], value=f_(x["monthly_inflow_M"]))
            elif fname.startswith("4_"):
                r.update(src="licence", detail=x["licence_type"], issuer=x["issued_by"], name=x["holder_name"], phone=s_(x["phone"]), area=x["area"])
            elif fname.startswith("5_"):
                r.update(src="lec" if x["utility"] == "LEC" else "wasco", detail=x["utility"], name=x["account_name"], phone=s_(x["phone"]), area=x["area"])
            else:
                r.update(src="canvass", detail="Field agents", name=x["observed_name"], phone=s_(x["phone"]), area=x["area"], activity=x["activity"])
            r["cat"] = CAT[r["src"]]
            recs.append(r)
    recs.sort(key=lambda r: r["rid"])
    link = {int(x["record_id"]): int(x["true_business_id"]) for x in csv.DictReader(open(os.path.join(d, "answer_key", "answer_key_record_links.csv")))}
    for r in recs:
        r["true_id"] = link[r["rid"]]
    records = recs
    biz = []
    for x in csv.DictReader(open(os.path.join(d, "answer_key", "answer_key_businesses.csv"))):
        biz.append(dict(id=int(x["business_id"]), first=x["owner_first_name"], last=x["owner_surname"], type=x["business_type"], area=x["area"],
                        sector=x["line_of_business"], registered=bool(int(x["registered"])), trading=bool(int(x["trading"])), turnover=float(x["true_monthly_sales_M"]),
                        nil_months=int(x["nil_return_months_of_12"]), target=bool(int(x["should_be_registered"])), tin=x["tin"] or None))
    biz.sort(key=lambda b: b["id"])


if os.environ.get("MOHOEBI_EXPORT"):
    export_sources(os.environ["MOHOEBI_EXPORT"])
if os.environ.get("MOHOEBI_SOURCES"):
    load_sources(os.environ["MOHOEBI_SOURCES"])
random.seed(SEED + 1)  # the random-visit baseline starts from the same state whether the data was generated or loaded

# ---------------------------------------------------------------- linking records into businesses
def toks(name):
    n = name.lower().replace("'s", " ")
    return [t for t in re.findall(r"[a-z]+", n) if t not in STOP]


def tok_eq(a, b):
    if a == b:
        return True
    if len(a) == 1 and a not in TYPE_WORDS and b not in TYPE_WORDS and b.startswith(a):
        return True
    if len(b) == 1 and b not in TYPE_WORDS and a not in TYPE_WORDS and a.startswith(b):
        return True
    return len(a) > 3 and len(b) > 3 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.84


def name_sim(ta, tb):
    if not ta or not tb:
        return 0.0
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    m = sum(1 for x in small if any(tok_eq(x, y) for y in big))
    return m / len(small)


for r in records:
    r["t"] = toks(r["name"])

parent = list(range(len(records)))


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb:
        parent[ra] = rb


def parse(r):
    core = [x for x in r["t"] if x not in TYPE_WORDS]
    return dict(sur=core[-1] if core else None, first=core[0] if len(core) >= 2 else None,
                types={x for x in r["t"] if x in TYPE_WORDS})


for r in records:
    r["p"] = parse(r)


def compat(ra, rb):
    """Could these two records describe the same business? Surname, first name (or initial), kind of business and area must not clash."""
    pa, pb = ra["p"], rb["p"]
    if not pa["sur"] or not pb["sur"] or not tok_eq(pa["sur"], pb["sur"]):
        return False
    if pa["first"] and pb["first"] and not tok_eq(pa["first"], pb["first"]):
        return False
    if pa["types"] and pb["types"] and not (pa["types"] & pb["types"]):
        return False
    return ra["area"] == rb["area"] or NEIGH[ra["area"]] == rb["area"] or NEIGH[rb["area"]] == ra["area"]


def full_first(r):
    return bool(r["p"]["first"]) and len(r["p"]["first"]) > 1


by_phone, bucket = defaultdict(list), defaultdict(list)
for r in records:
    if r["phone"]:
        by_phone[r["phone"]].append(r)
    if r["p"]["sur"]:
        bucket[r["p"]["sur"][0]].append(r)

shared_phone_pairs = []  # same phone but different names
for lst in by_phone.values():  # a shared phone number is strong evidence
    for i in range(len(lst)):
        for j in range(i + 1, len(lst)):
            s_ = name_sim(lst[i]["t"], lst[j]["t"])
            if s_ >= 0.30:
                union(lst[i]["rid"], lst[j]["rid"])
            else:
                shared_phone_pairs.append((lst[i]["rid"], lst[j]["rid"]))
for lst in bucket.values():  # pass A: two records with full first names that agree
    for i in range(len(lst)):
        if not full_first(lst[i]):
            continue
        for j in range(i + 1, len(lst)):
            if full_first(lst[j]) and compat(lst[i], lst[j]):
                union(lst[i]["rid"], lst[j]["rid"])
for _ in range(3):  # pass B: a vaguer record joins a business only when every record that fits it fits the others too
    for lst in bucket.values():
        for r in lst:
            matches = [g for g in lst if g["rid"] != r["rid"] and compat(r, g)]
            roots = {find(g["rid"]) for g in matches} - {find(r["rid"])}
            if len(roots) == 1 or (1 < len(roots) and len(matches) <= 8 and all(
                    compat(x, y) for i, x in enumerate(matches) for y in matches[i + 1:]
                    if find(x["rid"]) != find(y["rid"]))):
                for c in roots:
                    union(r["rid"], c)

clusters = defaultdict(list)
for r in records:
    clusters[find(r["rid"])].append(r)
cluster_of = {r["rid"]: find(r["rid"]) for r in records}
reg_records = [r for r in records if r["src"] == "register"]


def near_miss(cl):
    """An unregistered-looking cluster that is close to a registered record (maybe the same business)."""
    ids = {r["rid"] for r in cl}
    for a, b in shared_phone_pairs:
        for x, y in ((a, b), (b, a)):
            if x in ids and records[y]["src"] == "register" and cluster_of[y] != cluster_of[x]:
                return "phone", records[y]
    for r in cl:
        for g in reg_records:
            if cluster_of[g["rid"]] == cluster_of[r["rid"]]:
                continue
            if g["area"] not in (r["area"], NEIGH[r["area"]]) and r["area"] != NEIGH[g["area"]]:
                continue
            pr = [x for x in r["t"] if x not in TYPE_WORDS]
            pg = [x for x in g["t"] if x not in TYPE_WORDS]
            if not pr or not pg or not tok_eq(pr[-1], pg[-1]):
                continue  # surname must match
            if len(pr) >= 2 and len(pg) >= 2 and not tok_eq(pr[0], pg[0]):
                continue  # clearly different first names
            tr = {x for x in r["t"] if x in TYPE_WORDS}
            tg = {x for x in g["t"] if x in TYPE_WORDS}
            if tr and tg and not (tr & tg):
                continue  # clearly different type of business
            return "name", g
    return None


# ---------------------------------------------------------------- scoring
TYPE_SECTOR = {"general": "retail", "tuck": "retail", "mini": "retail", "snack": "snack bar", "tavern": "tavern",
               "butchery": "butchery", "hardware": "hardware", "hair": "services", "tailoring": "services",
               "car": "services", "guesthouse": "services", "phone": "services"}
LIC_SECTOR = {"General Dealer Licence": "retail", "Snack Bar Licence": "snack bar", "Liquor Licence": "tavern",
              "Butchery and Livestock Permit": "butchery", "Services Trading Licence": "services",
              "Guesthouse Licence": "services"}
WS_SECTOR = {"Maluti Beverage Distributors": "tavern", "Berea Meat Wholesalers": "butchery",
             "Lesotho Builders Supply": "hardware"}  # the two food wholesalers serve shops and snack bars alike
FIXED_BAND = {"busy": 20000, "moderate": 9000, "quiet": 3000, "closed": 0}


def infer_sector(cl):
    """The register holds the line of business. For others it is read from the name, the licence or the wholesaler."""
    for r in cl:
        if r.get("sector"):
            return r["sector"]
    for r in cl:
        for x in r["t"]:
            if x in TYPE_SECTOR:
                return TYPE_SECTOR[x]
    for r in cl:
        if r["src"] == "licence" and r["detail"] in LIC_SECTOR:
            return LIC_SECTOR[r["detail"]]
    for r in cl:
        if r["src"] == "wholesaler":
            return WS_SECTOR.get(r["detail"], "retail")
    return None


def median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2]


def observed(cl):
    w = sum(r["value"] for r in cl if r["src"] == "wholesaler")
    m = sum(r["value"] for r in cl if r["src"] in ("mpesa", "ecocash"))
    return w, m


# Calibration: registered businesses that file normally have declared sales. Compare what RSL knows they
# declared with what the outside records show, per line of business, to learn the multipliers.
samples = defaultdict(lambda: {"w": [], "m": [], "a": defaultdict(list)})
for cl in clusters.values():
    g = next((r for r in cl if r["src"] == "register"), None)
    if not g or not g["declared"]:
        continue
    w, m = observed(cl)
    for sec in (g["sector"], "all"):
        if w > 0:
            samples[sec]["w"].append(g["declared"] / w)
        if m > 0:
            samples[sec]["m"].append(g["declared"] / m)
    for r in cl:
        if r["src"] == "canvass":
            samples["all"]["a"][r["activity"]].append(g["declared"])


def ratio(sec, key):
    own = samples[sec][key] if sec else []
    if len(own) >= 5:
        return median(own)
    pooled = samples["all"][key]
    return median(pooled) if len(pooled) >= 5 else {"w": 1.6, "m": 1.4}[key]


def band(label):
    a = samples["all"]["a"][label]
    return median(a) if len(a) >= 3 else FIXED_BAND[label]


def est_turnover(cl, calibrated=True):
    sec = infer_sector(cl)
    w, m = observed(cl)
    rw, rm = (ratio(sec, "w"), ratio(sec, "m")) if calibrated else (1.6, 1.4)
    c = 0
    for r in cl:
        if r["src"] == "canvass":  # agent bands stay as guesses: registered shops are bigger than unregistered ones
            c = max(c, FIXED_BAND[r["activity"]])
    return {"wholesaler": w * rw, "mobile": m * rm, "canvass": c}


def combined(e, calibrated=True):
    """Calibrated: average of the money clues, agent guess only when there is no money clue.
    First rule (fixed): the highest of the three clues."""
    if not calibrated:
        return max(e.values())
    money = [v for v in (e["wholesaler"], e["mobile"]) if v > 0]
    return sum(money) / len(money) if money else e["canvass"]


SECTOR_LABEL = {"retail": "shops", "snack bar": "snack bars", "tavern": "taverns", "butchery": "butcheries",
                "hardware": "hardware shops", "services": "service businesses", None: "all businesses"}


def estimate_line(e, est, sec, rw, rm):
    parts = []
    if e["wholesaler"] > 0:
        parts.append(f"stock bought x {rw:.1f}")
    if e["mobile"] > 0:
        parts.append(f"mobile money x {rm:.1f}")
    if not parts:
        return f"Estimated sales: about M{est:,.0f} a month, a rough guess from what the field agent saw"
    return (f"Estimated sales: about M{est:,.0f} a month ({' and '.join(parts)}, "
            f"worked out from registered {SECTOR_LABEL.get(sec, 'businesses')} and their declared sales)")


def mask(p):
    return f"+266 ••••• {p[-3:]}" if p else "—"


def display_name(cl):
    best = max((r["name"] for r in cl if r["src"] != "register"), key=len, default=cl[0]["name"])
    return " ".join(w.capitalize() if not w.endswith(".") else w for w in best.replace("'s", "’s").split())


def tags_for(cl):
    out = []
    for s in SRC_ORDER:
        for r in cl:
            if r["src"] == s and s != "register":
                label = {"wholesaler": "Wholesaler", "canvass": "Field agent"}.get(s, r["detail"])
                if label not in out:
                    out.append(label)
    return out


def evidence_line(r, registered=False, wmult=1.6):
    s = r["src"]
    if s == "wholesaler":
        return (f"Buys about M{r['value']:,.0f} of stock a month from {r['detail']}"
                + ("" if registered else f" (about M{r['value'] * wmult:,.0f} in sales)"))
    if s == "mpesa":
        return f"Receives about M{r['value']:,.0f} a month on an M-Pesa merchant account (Vodacom Lesotho)"
    if s == "ecocash":
        return f"Receives about M{r['value']:,.0f} a month on an EcoCash merchant account (Econet Telecom Lesotho)"
    if s == "licence":
        return (f"Holds a {r['detail']} from the {r['issuer']}" +
                ("" if registered else " but is not registered with RSL"))
    if s == "lec":
        return "Has a business electricity account with LEC at the premises"
    if s == "wasco":
        return "Has a business water account with WASCO at the premises"
    if s == "canvass":
        return ("Field agent found the premises closed" if r["activity"] == "closed"
                else f"Field agent saw the business trading ({r['activity']})")
    return ""


def dominant_true_id(cl):
    return Counter(r["true_id"] for r in cl).most_common(1)[0][0]


worklist, nil_items = [], []
for cid, cl in clusters.items():
    has_reg = [r for r in cl if r["src"] == "register"]
    cats = sorted({r["cat"] for r in cl if r["cat"] != "register"})
    if not cats and not has_reg:
        continue
    e = est_turnover(cl, CALIBRATED)
    sec = infer_sector(cl)
    rw, rm = ratio(sec, "w"), ratio(sec, "m")
    est = combined(e, CALIBRATED)
    activity_cats = [c for c, k in (("wholesalers", "wholesaler"), ("mobile money", "mobile"), ("field agents", "canvass")) if e[k] > 0]
    closed = any(r["src"] == "canvass" and r["activity"] == "closed" for r in cl)
    phones = [r["phone"] for r in cl if r["phone"]]
    area = Counter(r["area"] for r in cl).most_common(1)[0][0]
    tid = dominant_true_id(cl)
    ordered = sorted((r for r in cl if r["src"] != "register"), key=lambda r: SRC_ORDER.index(r["src"]))

    if has_reg:  # ---- registered business: zero-sales (nil) return check
        g = has_reg[0]
        if g["nil_months"] is not None and g["nil_months"] >= 6:
            reasons = [f"Filed nil returns in {g['nil_months']} of the last 12 months"]
            for r in ordered:
                reasons.append(evidence_line(r, registered=True, wmult=rw))
            if est > 0:
                reasons.append(estimate_line(e, est, sec, rw, rm))
            if est >= THRESH * 0.5:
                verdict, action = "Possible undeclared trading", "Officer review: compare declared sales with purchases"
            elif est > 0:
                verdict, action = "Unclear", "Send a friendly reminder and offer assisted filing"
            else:
                verdict, action = "Likely genuinely inactive", "No enforcement. Offer assisted filing or deregistration"
            if est == 0:
                reasons.append("No sign of buying, mobile money payments or trading in any record")
            nil_items.append(dict(id=f"N{cid:04d}", tin=g["tin"], name=display_name(cl + has_reg), area=area,
                                  nil_months=g["nil_months"], est_turnover=round(est), verdict=verdict,
                                  action=action, reasons=reasons, tags=tags_for(cl),
                                  truth="trading" if biz[g["true_id"]]["trading"] else "inactive"))
        continue

    # ---- unregistered candidate
    score = 0
    reasons = ["No match in the RSL register (checked name, phone and area)"]
    if est >= THRESH:
        score += 40
    elif est >= THRESH * 0.5:
        score += 22
    elif est > 0:
        score += 8
    score += min(32, 8 * len(cats))
    score += 12 if len(activity_cats) >= 2 else (6 if len(activity_cats) == 1 else 0)
    if closed:
        score -= 20
    score = max(0, min(100, score))

    for r in ordered:
        reasons.append(evidence_line(r, wmult=rw))
    if est > 0:
        reasons.append(estimate_line(e, est, sec, rw, rm))
    reasons.append(f"Shows up in {len(cats)} of the 5 outside places we check")

    nm = near_miss(cl)
    per_src = Counter(r["src"] for r in cl)
    dup_accounts = any(per_src[k] >= 2 for k in ("mpesa", "ecocash", "lec", "wasco"))
    conflict = e["wholesaler"] and e["mobile"] and max(e["wholesaler"], e["mobile"]) / min(e["wholesaler"], e["mobile"]) > 3
    if nm:
        route = "Exception"
        action = "Verify against the register before any visit"
        if nm[0] == "phone":
            reasons.append(f"Uses the same phone number as registered {nm[1]['tin']} but under a different name")
        else:
            reasons.append(f"A similar name in the same area is registered ({nm[1]['tin']}). Confirm this is a different business")
    elif dup_accounts:
        route, action = "Exception", "Check whether this is more than one business"
        reasons.append("Has more than one account with the same provider, so this may be two businesses mixed up")
    elif conflict:
        route, action = "Exception", "Check which source is right before visiting"
        reasons.append("Purchases and mobile money point to very different sales levels")
    elif score >= 54 and activity_cats and est >= THRESH:
        route, action = "Ordinary", "Field visit with assisted registration"
    elif score >= 30:
        route, action = "Human review", "Officer reviews the evidence before deciding on a visit"
        if not activity_cats:
            reasons.append("Only licence or utility evidence: the business may have closed")
        elif est < THRESH:
            reasons.append("Evidence suggests trading below the registration threshold")
    else:
        continue  # monitor only

    worklist.append(dict(id=f"C{cid:04d}", name=display_name(cl), area=area, phone=mask(phones[0] if phones else None),
                         score=score, route=route, action=action, est_turnover=round(est), tags=tags_for(cl),
                         reasons=reasons, truth_target=biz[tid]["target"],
                         truth_note=("Registered business (record split)" if biz[tid]["registered"] else
                                     "Dormant or closed" if not biz[tid]["trading"] else
                                     "Trading below threshold" if not biz[tid]["target"] else "Taxable, unregistered"),
                         merged=len({r["true_id"] for r in cl}) > 1, _tid=tid))

worklist.sort(key=lambda w: (["Ordinary", "Exception", "Human review"].index(w["route"]), -w["score"]))
seen_t = set()
for w in worklist:  # the same real business listed twice counts once
    if w["truth_target"]:
        if w["_tid"] in seen_t:
            w["truth_target"], w["truth_note"], w["duplicate"] = False, "Same business listed twice", True
        seen_t.add(w["_tid"])
    w.pop("_tid")

# ---------------------------------------------------------------- testing against the known answer
targets = {b["id"] for b in biz if b["target"]}
visible = {r["true_id"] for r in records if r["src"] != "register"}
untraceable = targets - visible


def found_ids(items):
    ids = set()
    for w in items:
        ids |= {r["true_id"] for r in clusters[int(w["id"][1:])]} & targets
    return ids


ordinary = [w for w in worklist if w["route"] == "Ordinary"]
n_ord, hits_ord = len(ordinary), sum(1 for w in ordinary if w["truth_target"])
found_ord, found_all = found_ids(ordinary), found_ids(worklist)
hits_all = sum(1 for w in worklist if w["truth_target"])
sims = []
for _ in range(2000):
    s = random.sample(range(len(biz)), min(n_ord, len(biz)))
    sims.append(sum(1 for i in s if biz[i]["target"]) / len(s))
rate_random_sim = sum(sims) / len(sims)

metrics = dict(
    universe=len(biz), registered=sum(b["registered"] for b in biz), true_targets=len(targets),
    untraceable_targets=len(untraceable), records=len(records), clusters=len(clusters),
    worklist_total=len(worklist), ordinary=n_ord,
    exception=sum(1 for w in worklist if w["route"] == "Exception"),
    human_review=sum(1 for w in worklist if w["route"] == "Human review"),
    ordinary_hit_rate=hits_ord / n_ord if n_ord else 0, random_hit_rate=rate_random_sim,
    lift=(hits_ord / n_ord) / rate_random_sim if n_ord else 0,
    recall_ordinary=len(found_ord) / len(targets), recall_all=len(found_all) / len(targets),
    overall_precision=hits_all / len(worklist) if worklist else 0,
    merge_errors=sum(1 for w in worklist if w["merged"]),
    ordinary_false_positives=n_ord - hits_ord, nil_total=len(nil_items),
)
nu = [n for n in nil_items if n["verdict"] == "Possible undeclared trading"]
true_under = [b for b in biz if b["registered"] and b["trading"] and b["nil_months"] >= 6]
true_inactive = [b for b in biz if b["registered"] and not b["trading"] and b["nil_months"] >= 6]
inactive_flagged = [n for n in nil_items if n["verdict"] == "Likely genuinely inactive"]
metrics.update(
    nil_flagged_undeclared=len(nu), nil_flagged_correct=sum(1 for n in nu if n["truth"] == "trading"),
    nil_true_undeclared=len(true_under), nil_inactive_total=len(true_inactive),
    nil_inactive_correct=sum(1 for n in inactive_flagged if n["truth"] == "inactive"),
    nil_inactive_wrong=sum(1 for n in inactive_flagged if n["truth"] == "trading"),
)

errors = []
for w in ordinary:
    if not w["truth_target"]:
        errors.append(dict(type="False positive in Ordinary tier", id=w["id"], name=w["name"], why=w["truth_note"]))
for w in worklist:
    if w.get("duplicate"):
        errors.append(dict(type="Same business listed twice", id=w["id"], name=w["name"],
                           why="Records with only an initial or no first name did not link to the full record"))
    if w["merged"]:
        errors.append(dict(type="Merge error (two businesses joined)", id=w["id"], name=w["name"],
                           why="Records from different businesses linked by name or shared phone"))
for t in sorted(untraceable):
    errors.append(dict(type="Missed: no trace in any source", id=f"B{t:04d}",
                       name=f"{biz[t]['first']} {biz[t]['last']} {biz[t]['type']}", why="Found only by canvassing or referral"))
for t in sorted(targets - untraceable - found_all):
    errors.append(dict(type="Missed: seen but not listed", id=f"B{t:04d}",
                       name=f"{biz[t]['first']} {biz[t]['last']} {biz[t]['type']}",
                       why="Evidence too weak or records not linked"))

# ---------------------------------------------------------------- what each of the six places gives
PLACES = [
    ("register", "RSL register", "Revenue Services Lesotho",
     "Who is already registered. Used to take registered businesses off the list.",
     "RSL already holds it.", ["register"]),
    ("wholesalers", "Wholesalers", "VAT-registered wholesalers (example names)",
     "Which shops buy stock in bulk, and roughly how much each month.",
     "RSL asks wholesalers for a monthly list of their business customers and what each bought.", ["wholesaler"]),
    ("mobile", "Mobile money", "Vodacom Lesotho (M-Pesa) and Econet Telecom Lesotho (EcoCash)",
     "Which businesses take customer payments on a merchant account, and how much comes in each month.",
     "A data-sharing agreement with each provider.", ["mpesa", "ecocash"]),
    ("licences", "Licences", "Ministry of Trade, Ministry of Tourism, Ministry of Agriculture and Ministry of Health",
     "Which businesses hold a licence to trade, and what kind of business it is.",
     "A regular list of licences issued from each ministry.", ["licence"]),
    ("utilities", "Utility accounts", "LEC (electricity) and WASCO (water)",
     "Which premises have a business electricity or water account, so someone is operating there.",
     "A data-sharing agreement with each utility.", ["lec", "wasco"]),
    ("agents", "Field agents", "Mohoebi field agents",
     "What an agent sees on the ground: open or closed, and how busy.",
     "Our own staff. No agreement needed.", ["canvass"]),
]
sources = []
for key, label, holder, tells, how, srcs in PLACES:
    recs = [r for r in records if r["src"] in srcs]
    biz_ids = {r["true_id"] for r in recs}
    mem = Counter((r["detail"], r["issuer"]) for r in recs)
    order = sorted(mem.items(), key=lambda kv: (-kv[1], kv[0][0]))
    sources.append(dict(key=key, label=label, holder=holder, tells=tells, how=how, records=len(recs),
                        businesses=len(biz_ids), targets_seen=len(biz_ids & targets),
                        unregistered_seen=sum(1 for i in biz_ids if not biz[i]["registered"]),
                        members=[dict(name=k[0], issuer=k[1], records=v) for k, v in order]))

def err_stats(use_cal):
    errs = []
    for cl in clusters.values():
        if any(r["src"] == "register" for r in cl):
            continue
        ids = {r["true_id"] for r in cl}
        if len(ids) != 1:
            continue
        b = biz[next(iter(ids))]
        if b["registered"] or not b["trading"]:
            continue
        est = combined(est_turnover(cl, use_cal), use_cal)
        if est > 0:
            errs.append((est - b["turnover"]) / b["turnover"])
    absolute = sorted(abs(x) for x in errs)
    return dict(n=len(errs), median_error=absolute[len(absolute) // 2], median_bias=median(errs),
                within30=sum(1 for x in absolute if x <= 0.30) / len(absolute))


sales_estimate = dict(
    fixed=err_stats(False), calibrated=err_stats(True),
    rows=[dict(sector=sec, label=SECTOR_LABEL[sec], n_w=len(samples[sec]["w"]), mult_w=ratio(sec, "w"), n_m=len(samples[sec]["m"]),
               mult_m=ratio(sec, "m")) for sec in SECTORS],
    bands=[dict(label=k, value=v) for k, v in FIXED_BAND.items()],
    fixed_mult=dict(w=1.6, m=1.4), fixed_bands=FIXED_BAND)

meta = dict(threshold=THRESH, seed=SEED,
            note="All data is practice data. Names, phones, tax numbers and wholesaler names are invented.")
json.dump(dict(meta=meta, metrics=metrics, sales_estimate=sales_estimate, sources=sources, worklist=worklist, nil_returns=nil_items, errors=errors),
          open(os.path.join(OUT, "results.json"), "w"), indent=1)
json.dump([{k: v for k, v in r.items() if k not in ("t", "p")} for r in records], open(os.path.join(OUT, "records.json"), "w"))
print(json.dumps(metrics, indent=1))
print("errors:", Counter(e["type"] for e in errors))
for s in sources:
    print(s["label"], s["records"], s["businesses"], s["targets_seen"], [(m["name"], m["records"]) for m in s["members"]])
