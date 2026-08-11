import json

from fastapi import Depends, FastAPI, Form, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse

from app.db import Base, engine, get_db
from app.models import ImportedItem
from app.services.whatnot_scraper import get_listing_links, parse_listing
from app.services.review_flags import build_review_note

# Create database tables if they do not exist yet
Base.metadata.create_all(bind=engine)

app = FastAPI()

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    template = templates.get_template("index.html")
    content = template.render(request=request)
    return HTMLResponse(content=content)

@app.post("/import", response_class=HTMLResponse)
def import_storefront(
    request: Request,
    shop_url: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    links = get_listing_links(shop_url)

    saved_items: list[ImportedItem] = []

    # Keep this small while testing so Selenium does not take forever
    for link in links:
        parsed = parse_listing(link)
        review_note = build_review_note(
            parsed.get("title", ""),
            parsed.get("description_notes", "")
        )

        existing = (
            db.query(ImportedItem)
            .filter(ImportedItem.source_url == parsed["source_url"])
            .first()
        )

        if existing:
            # Update existing row with latest scraped values
            existing.title = parsed.get("title", "")
            existing.price = parsed.get("price", "")
            existing.size = parsed.get("size", "")
            existing.condition = parsed.get("condition", "")
            existing.description_notes = parsed.get("description_notes", "")
            existing.image_urls = json.dumps(parsed.get("image_urls", []))
            existing.review_notes = review_note

            db.commit()
            db.refresh(existing)
            saved_items.append(existing)
            continue

        item = ImportedItem(
            source_url=parsed["source_url"],
            title=parsed.get("title", ""),
            price=parsed.get("price", ""),
            size=parsed.get("size", ""),
            condition=parsed.get("condition", ""),
            description_notes=parsed.get("description_notes", ""),
            image_urls=json.dumps(parsed.get("image_urls", [])),
            review_notes=review_note,
        )

        db.add(item)
        db.commit()
        db.refresh(item)
        saved_items.append(item)

    template = templates.get_template("items.html")
    content = template.render(request=request, items=saved_items)
    return HTMLResponse(content=content)

@app.get("/items", response_class=HTMLResponse)
def list_items(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    items = db.query(ImportedItem).order_by(ImportedItem.id.desc()).all()

    template = templates.get_template("items.html")
    content = template.render(request=request, items=items)
    return HTMLResponse(content=content)

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
