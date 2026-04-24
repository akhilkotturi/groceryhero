"""
NLP normalization pipeline.
Takes raw scraped deal text like "Lays Chips 8oz 2/$5" and extracts:
- normalized product name
- brand
- category
- unit price
- quantity string

Uses spaCy for NER + regex for price/quantity patterns.
"""
import re
import logging
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

def _word_match(text_lower: str, keywords: list[str]) -> bool:
    """Return True if any keyword matches as a whole word (not substring).
    Checks longer phrases first so 'fruit snacks' beats 'fruit'."""
    for kw in sorted(keywords, key=len, reverse=True):
        pattern = r'\b' + re.escape(kw) + r'\b'
        if re.search(pattern, text_lower):
            return True
    return False

# Lazy-load spaCy model
_nlp = None


def get_nlp():
    global _nlp
    if _nlp is None:
        import spacy
        try:
            _nlp = spacy.load("en_core_web_sm")
        except OSError:
            logger.warning("spaCy model not found, running: python -m spacy download en_core_web_sm")
            import subprocess
            subprocess.run(["python", "-m", "spacy", "download", "en_core_web_sm"])
            _nlp = spacy.load("en_core_web_sm")
    return _nlp


# ─── Non-grocery exclusion ────────────────────────────────────────────────────
# Checked FIRST. If any term matches, the item is not a grocery product.
# Keep this list conservative — only add terms that would NEVER appear in a
# food/household product name.
NON_GROCERY_KEYWORDS = [
    # Apparel
    "t-shirt", "tshirt", "polo shirt", "dress shirt", "tank top",
    "jeans", "denim", "leggings", "yoga pants", "sweatpants", "cargo pants",
    "dress", "skirt", "blouse", "cardigan", "sweater", "hoodie",
    "jacket", "blazer", "coat", "parka", "windbreaker",
    "underwear", "boxers", "briefs", "bra", "sports bra",
    "socks", "stockings", "tights", "swimsuit", "bikini",
    "pajamas", "nightgown", "robe", "onesie",
    "clothing", "apparel", "activewear", "outerwear",
    # Footwear
    "shoes", "sneakers", "boots", "sandals", "heels", "flats",
    "loafers", "slippers", "clogs", "footwear",
    # Jewelry / accessories
    "necklace", "bracelet", "anklet", "earrings", "nose ring",
    "pendant", "charm bracelet", "locket",
    "engagement ring", "wedding ring", "fashion ring",
    "jewelry", "jewellery", "gemstone", "diamond necklace",
    "gold chain", "silver chain", "pearl necklace",
    "watch strap", "sunglasses", "reading glasses", "eyeglasses",
    "handbag", "purse", "clutch", "tote bag", "backpack purse",
    "wallet", "belt buckle",
    # Electronics
    "laptop", "notebook computer", "desktop computer",
    "television", "smart tv", "oled tv", "qled",
    "smartphone", "cell phone", "iphone", "galaxy phone",
    "tablet", "ipad",
    "headphones", "earbuds", "airpods",
    "video game console", "playstation", "xbox", "nintendo",
    "digital camera", "security camera", "baby monitor",
    "printer", "scanner", "projector",
    # Automotive
    "motor oil", "wiper blades", "car battery", "antifreeze",
    "tire", "tires", "car seat cover", "steering wheel cover",
    # Garden / hardware
    "fertilizer", "pesticide", "herbicide", "weed killer",
    "lawn mower", "leaf blower", "hedge trimmer",
    "power drill", "circular saw", "socket wrench",
]

# ─── Category keyword mapping ──────────────────────────────────────────────────
# All matched as whole words to avoid substring false positives.
CATEGORY_KEYWORDS = {
    "pet": [
        # Pet food — must come BEFORE meat so "chicken cat food" → pet, not meat
        "cat food", "dog food", "kitten food", "puppy food",
        "cat treat", "cat treats", "dog treat", "dog treats",
        "cat litter", "kitty litter", "pet food", "pet treat", "pet treats",
        "cat chow", "dog chow", "kibble", "pedigree", "purina", "friskies",
        "fancy feast", "meow mix", "blue buffalo", "iams", "eukanuba",
        "hill's science", "royal canin", "nutro", "wellness pet",
        "bird seed", "birdseed", "fish food", "hamster food", "guinea pig food",
        "cat collar", "dog collar", "pet shampoo", "flea collar",
    ],
    "produce": [
        "apple", "apples", "banana", "bananas", "orange", "oranges",
        "grape", "grapes", "strawberry", "strawberries",
        "blueberry", "blueberries", "raspberry", "raspberries",
        "blackberry", "blackberries", "watermelon", "cantaloupe",
        "pineapple", "mango", "mangoes", "papaya",
        "peach", "peaches", "pear", "pears", "plum", "plums",
        "cherry", "cherries", "lemon", "lemons", "lime", "limes",
        "grapefruit", "kiwi", "clementine", "tangerine",
        "tomato", "tomatoes", "roma tomato", "cherry tomato",
        "lettuce", "romaine", "spinach", "arugula", "kale",
        "broccoli", "cauliflower", "brussels sprouts",
        "carrot", "carrots", "baby carrots",
        "onion", "onions", "red onion", "green onion", "shallot",
        "bell pepper", "jalapeño", "poblano", "serrano",
        "celery", "cucumber", "cucumbers", "zucchini",
        "squash", "butternut squash", "acorn squash",
        "asparagus", "corn on the cob", "sweet corn",
        "avocado", "avocados", "mushroom", "mushrooms",
        "garlic", "garlic bulb", "cabbage", "bok choy",
        "sweet potato", "sweet potatoes", "yam", "yams",
        "russet potato", "red potato", "gold potato",
        "fresh vegetable", "fresh vegetables",
        "fresh fruit", "mixed fruit", "fruit salad",
        "produce", "salad mix", "coleslaw mix",
        # NOTE: "organic" intentionally removed — too broad, hits clothing/other
    ],
    "meat": [
        # Whole-word terms that only refer to meat cuts/seafood, not pet food
        "chicken breast", "chicken thigh", "chicken thighs", "chicken wing",
        "chicken wings", "chicken drumstick", "chicken drumsticks",
        "whole chicken", "chicken leg", "chicken legs",
        "ground beef", "ground turkey", "ground pork", "ground chicken",
        "beef steak", "sirloin steak", "ribeye steak", "flank steak",
        "t-bone steak", "ny strip", "chuck roast", "beef roast",
        "beef brisket", "beef ribs", "short ribs",
        "pork chop", "pork chops", "pork loin", "pork ribs",
        "pork tenderloin", "pork shoulder", "pork belly",
        "turkey breast", "turkey tenderloin", "whole turkey",
        "lamb chop", "lamb chops", "rack of lamb",
        "salmon fillet", "salmon filet", "atlantic salmon",
        "tilapia fillet", "cod fillet", "halibut fillet",
        "tuna steak", "mahi mahi", "catfish fillet",
        "shrimp", "jumbo shrimp", "raw shrimp", "cooked shrimp",
        "lobster tail", "crab legs", "sea scallops",
        "fish fillet", "fish fillets", "seafood mix",
        "sausage link", "sausage links", "italian sausage",
        "breakfast sausage", "bratwurst", "kielbasa",
        "bacon", "turkey bacon", "canadian bacon",
        "ham steak", "spiral ham", "honey ham",
        "hot dog", "hot dogs", "beef frank", "beef franks",
        "pepperoni", "salami", "prosciutto", "chorizo",
        "deli meat", "lunch meat", "lunchmeat",
        "beef", "pork", "veal", "bison", "venison",
    ],
    "dairy": [
        "whole milk", "2% milk", "skim milk", "1% milk",
        "oat milk", "almond milk", "soy milk", "coconut milk beverage",
        "lactose free milk", "chocolate milk",
        "cheddar cheese", "mozzarella cheese", "parmesan cheese",
        "swiss cheese", "provolone cheese", "pepper jack",
        "colby jack", "brie", "gouda", "feta cheese",
        "american cheese", "string cheese", "cream cheese",
        "cottage cheese", "ricotta cheese",
        "greek yogurt", "plain yogurt", "flavored yogurt",
        "dairy butter", "unsalted butter", "salted butter",
        "sour cream", "half and half", "heavy cream",
        "whipping cream", "heavy whipping cream",
        "egg carton", "dozen eggs", "large eggs", "extra large eggs",
        "cage free eggs", "free range eggs",
        "milk", "butter", "yogurt", "cheese", "eggs",
    ],
    "bakery": [
        "sourdough bread", "whole wheat bread", "white bread",
        "multigrain bread", "rye bread", "sliced bread", "sandwich bread",
        "baguette", "french bread", "italian bread",
        "bagel", "bagels", "everything bagel",
        "english muffin", "english muffins",
        "hamburger bun", "hamburger buns", "hot dog bun", "hot dog buns",
        "dinner roll", "dinner rolls", "kaiser roll",
        "croissant", "croissants", "danish pastry",
        "muffin", "muffins", "blueberry muffin",
        "cake", "birthday cake", "bundt cake", "cheesecake",
        "cupcake", "cupcakes", "brownie", "brownies",
        "cookie", "cookies", "sugar cookie", "chocolate chip cookie",
        "donut", "donuts", "doughnut", "glazed donut",
        "pie crust", "puff pastry", "pastry",
        "tortilla", "flour tortilla", "corn tortilla",
        "pita bread", "flatbread", "naan",
        "biscuit", "biscuits", "buttermilk biscuit",
        "bread loaf", "loaf of bread",
    ],
    "beverages": [
        "orange juice", "apple juice", "grape juice", "cranberry juice",
        "fruit juice", "vegetable juice", "v8 juice",
        "bottled water", "spring water", "purified water", "distilled water",
        "sparkling water", "mineral water", "seltzer water", "club soda",
        "soda", "diet soda", "cola", "diet cola",
        "energy drink", "sports drink", "electrolyte drink",
        "coffee beans", "ground coffee", "instant coffee", "cold brew",
        "black tea", "green tea", "herbal tea", "iced tea",
        "beer", "lager", "ale", "ipa", "stout", "hard cider",
        "wine", "red wine", "white wine", "rosé", "champagne", "prosecco",
        "lemonade", "limeade", "fruit punch",
        "smoothie", "protein shake", "meal replacement shake",
        "kombucha", "coconut water", "aloe drink",
        "hot chocolate", "cocoa mix", "drink mix", "powdered drink",
        "juice", "water", "coffee", "tea", "beer", "wine",
    ],
    "snacks": [
        "potato chips", "tortilla chips", "corn chips", "veggie chips",
        "pita chips", "multigrain chips",
        "crackers", "graham crackers", "rice crackers", "cheese crackers",
        "microwave popcorn", "popped popcorn", "kettle corn",
        "pretzels", "pretzel sticks", "soft pretzel",
        "mixed nuts", "roasted nuts", "almonds", "cashews",
        "peanuts", "pistachios", "walnuts", "pecans",
        "trail mix", "dried fruit mix",
        "granola bar", "granola bars", "cereal bar",
        "protein bar", "protein bars", "energy bar", "kind bar", "clif bar",
        "candy bar", "chocolate bar", "milk chocolate", "dark chocolate",
        "gummy bears", "gummy worms", "gummies",
        "fruit snacks", "fruit rollup", "fruit leather",
        "beef jerky", "turkey jerky", "meat jerky",
        "pork rinds", "pork skins",
        "rice cake", "rice cakes",
        "sunflower seeds", "pumpkin seeds",
        "candy", "chips", "popcorn", "crackers", "jerky",
        "chocolate", "gummy", "pretzel", "nuts",
    ],
    "frozen": [
        "frozen pizza", "frozen burrito", "frozen quesadilla",
        "frozen waffle", "frozen waffles", "frozen pancakes",
        "frozen french fries", "frozen fries", "tater tots", "onion rings",
        "frozen meal", "frozen entree", "frozen dinner",
        "frozen vegetables", "frozen peas", "frozen corn", "frozen broccoli",
        "frozen fruit", "frozen berries", "frozen mango",
        "frozen chicken", "frozen chicken nuggets", "frozen fish sticks",
        "frozen shrimp", "frozen fish fillet",
        "ice cream", "ice cream pint", "ice cream gallon",
        "gelato", "sorbet", "sherbet",
        "popsicle", "popsicles", "ice pop", "fudge bar",
        "edamame", "frozen edamame",
        "frozen", "ice cream",
    ],
    "pantry": [
        "spaghetti", "penne pasta", "fettuccine", "linguine",
        "rotini", "rigatoni", "bowtie pasta", "pasta noodles",
        "ramen noodles", "rice noodles", "egg noodles",
        "white rice", "brown rice", "jasmine rice", "basmati rice",
        "wild rice", "quinoa", "couscous", "farro",
        "black beans", "pinto beans", "kidney beans", "navy beans",
        "chickpeas", "garbanzo beans", "cannellini beans",
        "red lentils", "green lentils", "split peas",
        "chicken soup", "tomato soup", "vegetable soup",
        "chicken broth", "beef broth", "vegetable broth", "bone broth",
        "pasta sauce", "marinara sauce", "alfredo sauce",
        "tomato sauce", "crushed tomatoes", "diced tomatoes",
        "salsa", "picante sauce", "enchilada sauce", "taco sauce",
        "olive oil", "extra virgin olive oil", "vegetable oil",
        "canola oil", "coconut oil", "avocado oil",
        "apple cider vinegar", "balsamic vinegar", "white vinegar",
        "all purpose flour", "bread flour", "cake flour",
        "granulated sugar", "powdered sugar", "brown sugar",
        "honey", "maple syrup", "agave",
        "baking soda", "baking powder", "yeast",
        "oatmeal", "rolled oats", "steel cut oats",
        "granola", "muesli",
        "ketchup", "mustard", "mayonnaise", "relish",
        "soy sauce", "teriyaki sauce", "hot sauce", "sriracha",
        "ranch dressing", "italian dressing", "balsamic dressing",
        "peanut butter", "almond butter", "sunflower butter",
        "strawberry jam", "grape jelly", "fruit preserves",
        "pancake syrup", "waffle syrup",
        "chicken noodle soup", "beef stew", "chili",
        "spices", "seasoning", "spice blend", "taco seasoning",
        "pasta", "rice", "beans", "soup", "sauce", "cereal",
        "oats", "flour", "sugar", "oil", "vinegar", "broth",
    ],
    "household": [
        "paper towels", "paper towel roll", "bounty paper towels",
        "toilet paper", "toilet tissue", "bathroom tissue",
        "facial tissue", "kleenex",
        "laundry detergent", "liquid detergent", "laundry pods",
        "fabric softener", "dryer sheets", "static guard",
        "dish soap", "dishwashing liquid", "dish detergent",
        "dishwasher pods", "dishwasher detergent",
        "hand soap", "liquid hand soap", "foam hand soap",
        "all purpose cleaner", "multi surface cleaner",
        "bathroom cleaner", "toilet bowl cleaner",
        "glass cleaner", "windex",
        "bleach", "disinfectant spray", "lysol spray",
        "shampoo", "conditioner", "2-in-1 shampoo",
        "body wash", "shower gel", "bar soap",
        "body lotion", "hand lotion", "moisturizer",
        "toothpaste", "whitening toothpaste",
        "toothbrush", "electric toothbrush",
        "mouthwash", "dental floss", "floss picks",
        "deodorant", "antiperspirant", "body spray",
        "razor", "disposable razor", "razor blades",
        "shaving cream", "shaving gel",
        "trash bags", "garbage bags", "kitchen trash bags",
        "aluminum foil", "plastic wrap", "wax paper",
        "zip lock bags", "storage bags", "freezer bags",
        "sandwich bags", "snack bags",
        "paper plates", "plastic cups", "disposable cups",
        "napkins", "paper napkins",
        "sponge", "scrubbing sponge", "steel wool pad",
        "mop", "broom", "dust mop",
        "air freshener", "febreze", "glade",
        "bug spray", "insect repellent", "ant trap",
        "sunscreen", "spf lotion", "sunblock",
        "bandages", "band aid", "first aid",
        "pain reliever", "ibuprofen", "acetaminophen", "tylenol", "advil",
        "cough syrup", "cold medicine", "allergy medicine",
        "vitamins", "multivitamin", "vitamin c", "vitamin d",
    ],
    "deli": [
        "rotisserie chicken", "whole rotisserie",
        "sliced turkey breast", "sliced ham",
        "prepared meal", "ready to eat meal",
        "deli sandwich", "sub sandwich",
        "potato salad", "coleslaw deli", "macaroni salad",
    ],
}

# Known brands (extend as needed)
KNOWN_BRANDS = [
    "Lays", "Doritos", "Frito-Lay", "Pepsi", "Coca-Cola", "Coke", "Sprite",
    "Gatorade", "Powerade", "Tropicana", "Minute Maid", "Dannon", "Chobani",
    "Yoplait", "Kraft", "Tillamook", "Daisy", "Land O Lakes", "Kerrygold",
    "Tyson", "Perdue", "Oscar Mayer", "Jimmy Dean", "Johnsonville",
    "Kellogg's", "General Mills", "Quaker", "Post", "Nature Valley",
    "Clif", "Kind", "RXBar", "Oreo", "Nabisco", "Pepperidge Farm",
    "Dave's", "Nature's Own", "Sara Lee", "Wonder", "Mission", "Old El Paso",
    "Barilla", "Ronzoni", "Hunt's", "Heinz", "Del Monte", "Progresso",
    "Campbell's", "Swanson", "Knorr", "Lipton", "Folgers", "Maxwell House",
    "Starbucks", "Dunkin", "Tide", "Downy", "Gain", "Bounce", "Charmin",
    "Bounty", "Quilted Northern", "Angel Soft", "Scott", "Clorox", "Lysol",
    "Dawn", "Palmolive", "Dove", "Pantene", "Head & Shoulders",
    "Colgate", "Crest", "Listerine", "Degree", "Secret", "Old Spice",
    "HEB", "Central Market",
]

# Price patterns
PRICE_PATTERNS = [
    r"(\d+)\s*(?:for|\/)\s*\$(\d+\.?\d*)",    # "2 for $5" or "2/$5"
    r"\$(\d+\.?\d*)\s*(?:each|ea\.?)?",         # "$2.99 each"
    r"(\d+\.?\d*)\s*(?:cents?|¢)",              # "99 cents"
]


@dataclass
class NormalizedDeal:
    normalized_name: str
    brand: Optional[str]
    category: Optional[str]
    sale_price: Optional[float]
    original_price: Optional[float]
    unit_price: Optional[float]
    quantity: Optional[str]
    discount_pct: Optional[float]


CATEGORY_CHECK_ORDER = [
    "pet", "snacks", "frozen", "deli", "meat", "pantry", "dairy", "bakery",
    "beverages", "household", "produce",
]

def detect_category(text: str) -> Optional[str]:
    """Detect category using whole-word matching. More-specific categories
    are checked first so 'fruit snacks' → snacks, not produce.
    Non-grocery items (clothing, electronics, etc.) return None immediately."""
    text_lower = (text or "").lower()
    # Exclude non-grocery items first
    if _word_match(text_lower, NON_GROCERY_KEYWORDS):
        return None
    for category in CATEGORY_CHECK_ORDER:
        if _word_match(text_lower, CATEGORY_KEYWORDS[category]):
            return category
    return None


def detect_brand(text: str) -> Optional[str]:
    text_lower = (text or "").lower()
    for brand in KNOWN_BRANDS:
        if brand.lower() in text_lower:
            return brand
    return None


def extract_prices(price_text: str, title: str) -> tuple[Optional[float], Optional[str]]:
    """Returns (unit_price, quantity_string)."""
    combined = f"{title} {price_text}".strip()

    # Multi-buy: "2/$5", "3 for $10"
    multi = re.search(r"(\d+)\s*(?:for|\/)\s*\$(\d+\.?\d*)", combined, re.IGNORECASE)
    if multi:
        count = int(multi.group(1))
        total = float(multi.group(2))
        unit_price = round(total / count, 2)
        return unit_price, f"{count}/${total:.2f}"

    # Simple price: "$2.99"
    simple = re.search(r"\$(\d+\.?\d*)", combined)
    if simple:
        return float(simple.group(1)), None

    # Cents: "99¢"
    cents = re.search(r"(\d+)\s*(?:cents?|¢)", combined, re.IGNORECASE)
    if cents:
        return round(int(cents.group(1)) / 100, 2), None

    return None, None


def normalize_name(raw_title: str, brand: Optional[str]) -> str:
    """Strip price info, size info, and clean up the product name."""
    name = raw_title or ""

    # Remove price patterns
    name = re.sub(r"\$\d+\.?\d*", "", name)
    name = re.sub(r"\d+\s*(?:for|\/)\s*\$\d+\.?\d*", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\d+\.?\d*\s*(?:cents?|¢)", "", name, flags=re.IGNORECASE)

    # Remove size info (8oz, 12 fl oz, 1.5 lb, etc.)
    name = re.sub(r"\d+\.?\d*\s*(?:oz|fl\.?\s*oz|lb|lbs|kg|g|ml|L|ct|pk|pack)\b", "", name, flags=re.IGNORECASE)

    # Clean up extra spaces
    name = re.sub(r"\s+", " ", name).strip()
    name = name.strip(",-.")

    return name if name else (raw_title or "")


def normalize_deal(
    raw_title: str,
    raw_price: Optional[str] = None,
    sale_price: Optional[float] = None,
    original_price: Optional[float] = None,
    discount_pct: Optional[float] = None,
) -> NormalizedDeal:
    """
    Main normalization function — takes raw deal text and returns structured data.
    """
    brand = detect_brand(raw_title)
    category = detect_category(raw_title)
    normalized_name = normalize_name(raw_title, brand)

    unit_price, quantity = extract_prices(raw_price or "", raw_title)

    # Use provided sale_price if we couldn't extract one
    if unit_price is None and sale_price is not None:
        unit_price = sale_price

    # Calculate discount if we have both prices
    if discount_pct is None and unit_price and original_price and original_price > 0:
        discount_pct = round((1 - unit_price / original_price) * 100, 1)

    return NormalizedDeal(
        normalized_name=normalized_name,
        brand=brand,
        category=category,
        sale_price=sale_price or unit_price,
        original_price=original_price,
        unit_price=unit_price,
        quantity=quantity,
        discount_pct=discount_pct,
    )


def batch_normalize(raw_deals: list[dict]) -> list[dict]:
    """Normalize a batch of raw deal dicts in place."""
    normalized = []
    for deal in raw_deals:
        result = normalize_deal(
            raw_title=deal.get("raw_title", ""),
            raw_price=deal.get("raw_price"),
            sale_price=deal.get("sale_price"),
            original_price=deal.get("original_price"),
            discount_pct=deal.get("discount_pct"),
        )
        normalized.append({
            **deal,
            "normalized_name": result.normalized_name,
            "brand": result.brand,
            "category": result.category,
            "unit_price": result.unit_price,
            "sale_price": result.sale_price,
            "original_price": result.original_price,
            "discount_pct": result.discount_pct,
            "quantity": result.quantity or deal.get("quantity"),
        })
    return normalized
