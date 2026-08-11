from typing import Optional

GARMENT_KEYWORDS = {
    "t-shirt": ["t-shirt", "tee", "graphic tee", "shirt"],
    "tank": ["tank", "tank top"],
    "sweatshirt": ["sweatshirt", "crewneck", "crew"],
    "sweater": ["sweater", "ribbed sweater", "knit"],
    "bodysuit": ["bodysuit", "body suit"],
    "crop_top": ["crop top", "cropped top"],
    "long_sleeve": ["long sleeve", "long-sleeve"],
}

def normalize_text(value: Optional[str]) -> str:
    return (value or "").strip().lower()

def detect_garment_type(text: str) -> Optional[str]:
    text = normalize_text(text)

    for garment_type, keywords in GARMENT_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                return garment_type

    return None

def build_review_note(title: str, description: str) -> str:
    title_type = detect_garment_type(title)
    desc_type = detect_garment_type(description)

    if title_type and desc_type and title_type != desc_type:
        return (
            f"Manual review needed: title suggests '{title_type}' "
            f"but description suggests '{desc_type}'."
        )

    if not title_type and desc_type:
        return f"Manual review suggested: garment type unclear in title, description suggests '{desc_type}'."

    if title_type and not desc_type:
        return f"Manual review suggested: garment type unclear in description, title suggests '{title_type}'."

    return ""
