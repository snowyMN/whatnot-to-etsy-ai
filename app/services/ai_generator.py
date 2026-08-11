import os
from openai import OpenAI
from app.config import OPENAI_API_KEY
import json

client = OpenAI(api_key=OPENAI_API_KEY)

def generate_listing_description(item):
    # Placeholder: call OpenAI or other model
    return f"Generated description for {item.get('title', 'item')}"

def generate_etsy_copy(item: dict) -> dict:
    prompt = f"""
You are helping convert a Whatnot shirt listing into an Etsy listing.

Input:
{json.dumps(item, indent=2)}

Return valid JSON with:
- etsy_title
- etsy_description
- etsy_tags (13 short tags max)
- etsy_category
- materials
- style
- review_notes

Rules:
- Product is a physical shirt
- Keep title natural and SEO-friendly
- Do not invent facts not supported by the input
- If size or condition is unclear, mention it in review_notes
"""

    response = client.responses.create(
        model="gpt-5.4",
        input=prompt
    )

    text = response.output_text
    return json.loads(text)
