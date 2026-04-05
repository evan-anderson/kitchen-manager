"""
Seed the canonical_items tab in Google Sheets with ~80 common household items.
Run once: uv run python scripts/seed_canonical_items.py
"""

from __future__ import annotations

import json
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gspread
from config import settings

CANONICAL_ITEMS = [
    # Proteins
    ("chicken breast", "protein", "freezer", "lbs"),
    ("chicken thighs", "protein", "freezer", "lbs"),
    ("ground beef", "protein", "freezer", "lbs"),
    ("ground turkey", "protein", "freezer", "lbs"),
    ("salmon", "protein", "freezer", "lbs"),
    ("shrimp", "protein", "freezer", "lbs"),
    ("pork chops", "protein", "freezer", "lbs"),
    ("pork tenderloin", "protein", "freezer", "lbs"),
    ("steak", "protein", "freezer", "lbs"),
    ("bacon", "protein", "fridge", "packs"),
    ("sausage", "protein", "fridge", "packs"),
    ("hot dogs", "protein", "fridge", "packs"),
    ("deli turkey", "protein", "fridge", "packs"),
    ("deli ham", "protein", "fridge", "packs"),
    ("rotisserie chicken", "protein", "fridge", "each"),
    # Dairy
    ("milk", "dairy", "fridge", "gallons"),
    ("eggs", "dairy", "fridge", "dozen"),
    ("butter", "dairy", "fridge", "sticks"),
    ("cheddar cheese", "dairy", "fridge", "lbs"),
    ("mozzarella cheese", "dairy", "fridge", "lbs"),
    ("parmesan cheese", "dairy", "fridge", "oz"),
    ("cream cheese", "dairy", "fridge", "blocks"),
    ("sour cream", "dairy", "fridge", "containers"),
    ("yogurt", "dairy", "fridge", "containers"),
    ("heavy cream", "dairy", "fridge", "pints"),
    # Produce
    ("bananas", "produce", "counter", "bunches"),
    ("apples", "produce", "fridge", "each"),
    ("strawberries", "produce", "fridge", "containers"),
    ("blueberries", "produce", "fridge", "containers"),
    ("grapes", "produce", "fridge", "lbs"),
    ("lemons", "produce", "fridge", "each"),
    ("limes", "produce", "fridge", "each"),
    ("avocados", "produce", "counter", "each"),
    ("tomatoes", "produce", "counter", "each"),
    ("onions", "produce", "pantry", "each"),
    ("garlic", "produce", "pantry", "heads"),
    ("potatoes", "produce", "pantry", "lbs"),
    ("sweet potatoes", "produce", "pantry", "each"),
    ("carrots", "produce", "fridge", "lbs"),
    ("celery", "produce", "fridge", "stalks"),
    ("broccoli", "produce", "fridge", "heads"),
    ("spinach", "produce", "fridge", "bags"),
    ("lettuce", "produce", "fridge", "heads"),
    ("bell peppers", "produce", "fridge", "each"),
    ("cucumbers", "produce", "fridge", "each"),
    ("zucchini", "produce", "fridge", "each"),
    # Frozen
    ("frozen peas", "frozen", "freezer", "bags"),
    ("frozen corn", "frozen", "freezer", "bags"),
    ("frozen broccoli", "frozen", "freezer", "bags"),
    ("frozen berries", "frozen", "freezer", "bags"),
    ("ice cream", "frozen", "freezer", "containers"),
    ("frozen pizza", "frozen", "freezer", "each"),
    ("frozen waffles", "frozen", "freezer", "boxes"),
    # Pantry staples
    ("rice", "pantry", "pantry", "lbs"),
    ("pasta", "pantry", "pantry", "boxes"),
    ("bread", "pantry", "counter", "loaves"),
    ("tortillas", "pantry", "pantry", "packs"),
    ("olive oil", "pantry", "pantry", "bottles"),
    ("vegetable oil", "pantry", "pantry", "bottles"),
    ("flour", "pantry", "pantry", "lbs"),
    ("sugar", "pantry", "pantry", "lbs"),
    ("salt", "pantry", "pantry", "containers"),
    ("pepper", "pantry", "pantry", "containers"),
    ("canned tomatoes", "pantry", "pantry", "cans"),
    ("tomato sauce", "pantry", "pantry", "jars"),
    ("chicken broth", "pantry", "pantry", "cartons"),
    ("peanut butter", "pantry", "pantry", "jars"),
    ("jelly", "pantry", "pantry", "jars"),
    ("cereal", "pantry", "pantry", "boxes"),
    ("oatmeal", "pantry", "pantry", "containers"),
    ("coffee", "pantry", "pantry", "bags"),
    ("tea", "pantry", "pantry", "boxes"),
    # Toddler staples (the toddler)
    ("pouches", "toddler", "pantry", "each"),
    ("goldfish crackers", "toddler", "pantry", "boxes"),
    ("string cheese", "toddler", "fridge", "packs"),
    ("apple sauce", "toddler", "pantry", "packs"),
    ("animal crackers", "toddler", "pantry", "boxes"),
    ("whole milk", "toddler", "fridge", "gallons"),
    # Condiments / misc
    ("ketchup", "condiment", "fridge", "bottles"),
    ("mustard", "condiment", "fridge", "bottles"),
    ("mayo", "condiment", "fridge", "jars"),
    ("soy sauce", "condiment", "pantry", "bottles"),
    ("hot sauce", "condiment", "pantry", "bottles"),
]


def main():
    if not settings.google_service_account_json or not settings.spreadsheet_id:
        print("Error: GOOGLE_SERVICE_ACCOUNT_JSON and SPREADSHEET_ID must be set in .env")
        sys.exit(1)

    creds = json.loads(settings.google_service_account_json)
    gc = gspread.service_account_from_dict(creds)
    spreadsheet = gc.open_by_key(settings.spreadsheet_id)

    # Ensure canonical_items tab exists with headers
    try:
        ws = spreadsheet.worksheet("canonical_items")
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title="canonical_items", rows=200, cols=4)
        ws.update("A1:D1", [["item", "category", "default_location", "default_unit"]])
        print("Created canonical_items tab with headers")

    # Check for existing items
    existing = ws.get_all_records()
    existing_names = {r["item"].lower() for r in existing if r.get("item")}

    # Add new items
    new_rows = []
    for item, category, location, unit in CANONICAL_ITEMS:
        if item.lower() not in existing_names:
            new_rows.append([item, category, location, unit])

    if new_rows:
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")
        print(f"Added {len(new_rows)} canonical items ({len(existing_names)} already existed)")
    else:
        print(f"All {len(CANONICAL_ITEMS)} items already exist")

    # Also ensure inventory tabs exist with headers
    for tab_name in ("freezer", "fridge", "pantry"):
        try:
            spreadsheet.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            ws_tab = spreadsheet.add_worksheet(title=tab_name, rows=200, cols=5)
            ws_tab.update("A1:E1", [["item", "quantity", "unit", "added_date", "notes"]])
            print(f"Created {tab_name} tab with headers")

    # Ensure meal_plans_history tab exists
    try:
        spreadsheet.worksheet("meal_plans_history")
    except gspread.WorksheetNotFound:
        ws_mp = spreadsheet.add_worksheet(title="meal_plans_history", rows=100, cols=3)
        ws_mp.update("A1:C1", [["week_start", "plan_json", "created_at"]])
        print("Created meal_plans_history tab with headers")

    print("Done! Canonical items seeded.")


if __name__ == "__main__":
    main()
