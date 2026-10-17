"""
English verbs utility module: Irregular verbs reference, lemmatizer, and formatter.
Ensures base dictionary form is used and irregular verbs clearly display past & p.p.,
while regular (-ed) verbs remain clean without redundant suffix annotations.
"""
from typing import Optional, Tuple, Dict
import re

# Comprehensive dictionary of standard English irregular verbs (base -> (past, past_participle))
IRREGULAR_VERBS: Dict[str, Tuple[str, str]] = {
    "arise": ("arose", "arisen"),
    "awake": ("awoke", "awoken"),
    "be": ("was/were", "been"),
    "bear": ("bore", "born"),
    "beat": ("beat", "beaten"),
    "become": ("became", "become"),
    "begin": ("began", "begun"),
    "bend": ("bent", "bent"),
    "bet": ("bet", "bet"),
    "bind": ("bound", "bound"),
    "bite": ("bit", "bitten"),
    "bleed": ("bled", "bled"),
    "blow": ("blew", "blown"),
    "break": ("broke", "broken"),
    "breed": ("bred", "bred"),
    "bring": ("brought", "brought"),
    "build": ("built", "built"),
    "burn": ("burnt/burned", "burnt/burned"),
    "burst": ("burst", "burst"),
    "buy": ("bought", "bought"),
    "catch": ("caught", "caught"),
    "choose": ("chose", "chosen"),
    "cling": ("clung", "clung"),
    "come": ("came", "come"),
    "cost": ("cost", "cost"),
    "creep": ("crept", "crept"),
    "cut": ("cut", "cut"),
    "deal": ("dealt", "dealt"),
    "dig": ("dug", "dug"),
    "do": ("did", "done"),
    "draw": ("drew", "drawn"),
    "dream": ("dreamt/dreamed", "dreamt/dreamed"),
    "drink": ("drank", "drunk"),
    "drive": ("drove", "driven"),
    "eat": ("ate", "eaten"),
    "fall": ("fell", "fallen"),
    "feed": ("fed", "fed"),
    "feel": ("felt", "felt"),
    "fight": ("fought", "fought"),
    "find": ("found", "found"),
    "flee": ("fled", "fled"),
    "fly": ("flew", "flown"),
    "forbid": ("forbade", "forbidden"),
    "forget": ("forgot", "forgotten"),
    "forgive": ("forgave", "forgiven"),
    "freeze": ("froze", "frozen"),
    "get": ("got", "gotten"),
    "give": ("gave", "given"),
    "go": ("went", "gone"),
    "grind": ("ground", "ground"),
    "grow": ("grew", "grown"),
    "hang": ("hung", "hung"),
    "have": ("had", "had"),
    "hear": ("heard", "heard"),
    "hide": ("hid", "hidden"),
    "hit": ("hit", "hit"),
    "hold": ("held", "held"),
    "hurt": ("hurt", "hurt"),
    "keep": ("kept", "kept"),
    "kneel": ("knelt", "knelt"),
    "know": ("knew", "known"),
    "lay": ("laid", "laid"),
    "lead": ("led", "led"),
    "lean": ("leant/leaned", "leant/leaned"),
    "leap": ("leapt/leaped", "leapt/leaped"),
    "learn": ("learnt/learned", "learnt/learned"),
    "leave": ("left", "left"),
    "lend": ("lent", "lent"),
    "let": ("let", "let"),
    "lie": ("lay", "lain"),
    "light": ("lit/lighted", "lit/lighted"),
    "lose": ("lost", "lost"),
    "make": ("made", "made"),
    "mean": ("meant", "meant"),
    "meet": ("met", "met"),
    "overcome": ("overcame", "overcome"),
    "pay": ("paid", "paid"),
    "put": ("put", "put"),
    "quit": ("quit", "quit"),
    "read": ("read", "read"),
    "ride": ("rode", "ridden"),
    "ring": ("rang", "rung"),
    "rise": ("rose", "risen"),
    "run": ("ran", "run"),
    "say": ("said", "said"),
    "see": ("saw", "seen"),
    "seek": ("sought", "sought"),
    "sell": ("sold", "sold"),
    "send": ("sent", "sent"),
    "set": ("set", "set"),
    "sew": ("sewed", "sewn"),
    "shake": ("shook", "shaken"),
    "shine": ("shone", "shone"),
    "shoot": ("shot", "shot"),
    "show": ("showed", "shown"),
    "shrink": ("shrank", "shrunk"),
    "shut": ("shut", "shut"),
    "sing": ("sang", "sung"),
    "sink": ("sank", "sunk"),
    "sit": ("sat", "sat"),
    "sleep": ("slept", "slept"),
    "slide": ("slid", "slid"),
    "speak": ("spoke", "spoken"),
    "spend": ("spent", "spent"),
    "spin": ("spun", "spun"),
    "spit": ("spat", "spat"),
    "split": ("split", "split"),
    "spread": ("spread", "spread"),
    "spring": ("sprang", "sprung"),
    "stand": ("stood", "stood"),
    "steal": ("stole", "stolen"),
    "stick": ("stuck", "stuck"),
    "sting": ("stung", "stung"),
    "strike": ("struck", "struck"),
    "swear": ("swore", "sworn"),
    "sweep": ("swept", "swept"),
    "swim": ("swam", "swum"),
    "swing": ("swung", "swung"),
    "take": ("took", "taken"),
    "teach": ("taught", "taught"),
    "tear": ("tore", "torn"),
    "tell": ("told", "told"),
    "think": ("thought", "thought"),
    "throw": ("threw", "thrown"),
    "understand": ("understood", "understood"),
    "undertake": ("undertook", "undertaken"),
    "undo": ("undid", "undone"),
    "upset": ("upset", "upset"),
    "wake": ("woke", "woken"),
    "wear": ("wore", "worn"),
    "weave": ("wove", "woven"),
    "weep": ("wept", "wept"),
    "win": ("won", "won"),
    "wind": ("wound", "wound"),
    "withdraw": ("withdrew", "withdrawn"),
    "write": ("wrote", "written"),
}

# Reverse lookup for past / past participle forms back to base
REVERSE_IRREGULAR: Dict[str, str] = {}
for base, (p, pp) in IRREGULAR_VERBS.items():
    for form in p.split("/"):
        REVERSE_IRREGULAR[form.strip().lower()] = base
    for form in pp.split("/"):
        REVERSE_IRREGULAR[form.strip().lower()] = base


def get_irregular_verb_info(word: str) -> Optional[Tuple[str, str]]:
    """
    Returns (past, past_participle) tuple if the word is an irregular verb, else None.
    Handles both base form (e.g. 'go') and conjugated forms (e.g. 'went').
    """
    w = word.strip().lower()
    if w in IRREGULAR_VERBS:
        return IRREGULAR_VERBS[w]
    if w in REVERSE_IRREGULAR:
        base = REVERSE_IRREGULAR[w]
        return IRREGULAR_VERBS.get(base)
    return None


def lemmatize_word(surface: str, pos: str = "") -> str:
    """
    Determines the base dictionary form (lemma) for English words.
    E.g.
    'allows' -> 'allow'
    'requires' -> 'require'
    'consolidated' -> 'consolidate'
    'went' -> 'go'
    'written' -> 'write'
    'taking' -> 'take'
    """
    cleaned = surface.strip()
    if not cleaned or " " in cleaned:
        # Multi-word phrase or idiom: return as is
        return cleaned

    w = cleaned.lower()

    # 1. Check irregular verbs reverse map
    if w in REVERSE_IRREGULAR:
        base = REVERSE_IRREGULAR[w]
        # Preserve original capitalization style (Title or lower)
        return base.capitalize() if cleaned.istitle() else base

    # 2. Check standard inflection suffixes for verbs and nouns
    # -ies -> -y (e.g. studies -> study, carries -> carry)
    if w.endswith("ies") and len(w) > 4 and w[-4] not in "aeiou":
        base = w[:-3] + "y"
        return base.capitalize() if cleaned.istitle() else base

    # -es -> (e.g. fixes -> fix, watches -> watch, passes -> pass)
    if w.endswith("es") and len(w) > 3:
        for ending in ("shes", "ches", "sses", "xes", "zes"):
            if w.endswith(ending):
                base = w[:-2]
                return base.capitalize() if cleaned.istitle() else base

    # -s (e.g. allows -> allow, requires -> require, but NOT focus, status, virus, analysis, bus)
    NON_INFLECTED_S_ENDINGS = ("us", "is", "os", "as", "ss")
    if w.endswith("s") and not w.endswith(NON_INFLECTED_S_ENDINGS) and len(w) > 3:
        base = w[:-1]
        return base.capitalize() if cleaned.istitle() else base

    # -ing (e.g. taking -> take, allowing -> allow, running -> run)
    if w.endswith("ing") and len(w) > 4:
        stem = w[:-3]
        if stem.endswith("t") and len(stem) > 2 and stem[-2] in "aeiou" and stem[-3] not in "aeiou":
            # running -> run, putting -> put
            base = stem[:-1] if stem[-1] == stem[-2] else stem
            return base.capitalize() if cleaned.istitle() else base
        if stem.endswith(("v", "s", "z", "c", "t", "d", "g", "r", "l", "m", "n", "p")):
            # taking -> take, creating -> create
            # test if stem + e is common
            base = stem + "e"
            return base.capitalize() if cleaned.istitle() else base
        return stem.capitalize() if cleaned.istitle() else stem

    # -ed (e.g. allowed -> allow, consolidated -> consolidate)
    if w.endswith("ed") and len(w) > 3:
        stem = w[:-2]
        if stem.endswith("i"):
            # studied -> study
            base = stem[:-1] + "y"
            return base.capitalize() if cleaned.istitle() else base
        if stem.endswith("d") and len(stem) > 2 and stem[-1] == stem[-2]:
            # nodded -> nod
            base = stem[:-1]
            return base.capitalize() if cleaned.istitle() else base
        if stem.endswith(("at", "id", "is", "iz", "ov", "at", "ut")):
            base = stem + "e"
            return base.capitalize() if cleaned.istitle() else base
        return stem.capitalize() if cleaned.istitle() else stem

    return cleaned


def format_verb_meaning(meaning: str, base_word: str, pos: str) -> str:
    """
    Appends irregular forms '(Past: X, P.P: Y)' ONLY if verb is irregular.
    If the verb is regular (-ed) or not a verb, DOES NOT add any past/pp.
    Also strips any incorrect regular past/p.p. like '(Past: allowed, P.P: allowed)'.
    """
    clean_meaning = meaning.strip()
    is_verb = "verb" in (pos or "").lower()

    if not is_verb:
        return clean_meaning

    irreg_info = get_irregular_verb_info(base_word)
    if irreg_info:
        past, pp = irreg_info
        # Avoid duplicate suffix if already present
        if "Past:" not in clean_meaning and "P.P:" not in clean_meaning:
            suffix = f" (Past: {past}, P.P: {pp})"
            return f"{clean_meaning}{suffix}" if clean_meaning else suffix.strip()
    else:
        # Regular verb: Ensure no redundant past/p.p. was accidentally appended
        clean_meaning = re.sub(r"\s*\(Past:\s*[^,]+,\s*P\.P:\s*[^)]+\)", "", clean_meaning, flags=re.IGNORECASE)

    return clean_meaning
