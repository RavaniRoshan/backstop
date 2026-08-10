"""A tiny module used by the Wedge example.

Contains a couple of standalone functions that operate on "Item" dicts.
The example task asks an agent to refactor these into a class-based approach.
"""


def create_item(name: str, price: float, qty: int = 1) -> dict:
    """Create an item dict with a computed total."""
    return {"name": name, "price": price, "qty": qty, "total": price * qty}


def apply_discount(item: dict, percent: float) -> dict:
    """Return a new item with ``percent`` discount applied to the total."""
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    factor = 1 - percent / 100
    result = dict(item)
    result["total"] = round(item["total"] * factor, 2)
    return result


def format_item(item: dict) -> str:
    """Return a human-readable summary of an item."""
    return f"{item['name']}: {item['qty']} x ${item['price']:.2f} = ${item['total']:.2f}"
