"""Segment-name normalisation shared by the XBRL stage and the model-read merge (no per-ticker config)."""
import re
ALLOTHER = re.compile(r"^(all other( segments)?|other segments?|corporate( and other| non[- ]segment)?|material reconciling items|segment reconciling items|reconciling items|unallocated( corporate)?)$", re.I)
def NORM(s):
    x = re.sub(r"\s+", " ", str(s)).strip(); x = re.sub(r"\s*\(\d\)$", "", x)
    x = re.sub(r"^(reportable|reporting|operating|business) segments?[:,]? ", "", x, flags=re.I)
    x = re.sub(r" (reportable|reporting|operating|business)? ?segments?$", "", x, flags=re.I).strip(" ,:-")
    return "All Other" if ALLOTHER.match(x) else x
def KEY(s): return re.sub(r"[^a-z0-9]", "", NORM(s).lower().replace("&", "and"))
def match(label, seg):
    """the existing series name whose key equals this label's key, else the normalised label itself"""
    k = KEY(label)
    for nm in seg.name.dropna().unique():
        if KEY(nm) == k: return nm
    return NORM(label)
