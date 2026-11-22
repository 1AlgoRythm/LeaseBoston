"""Snugd's MCP server: what Claude or ChatGPT sees.

Two layers, the same split Within uses:
  * Snugd's own tools (the shelves): search_apartments, get_apartment.
  * The landlord layer (the counter): ask_landlord returns the landlord's saved
    answer, or, if there is none, lets the renter send the question to the
    landlord's queue (send_question_to_landlord) and check back later
    (check_landlord_reply).
"""

from functools import wraps
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field

from mcp.server import MCPServer
from mcp.server.apps import Apps
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import service
from .seed_data import LANDMARKS, NEIGHBORHOODS

INSTRUCTIONS = """\
Snugd helps renters find apartments (Boston area, synthetic demo data).

Finding a place: call search_apartments with what the renter told you. Show the
results with their why_it_fits reasons and the listing ids. If there are
near_misses, say which one filter to loosen. Use get_apartment for details.

Questions for the landlord: when the renter asks about a specific listing and
get_apartment does not answer it (utilities, parking, deposits, fees, sublets,
tours, guarantors, pet rules beyond the listing's pets field), call ask_landlord
with ONE question per call. Never guess a landlord's policy.
- status "answered": give the answer word for word and say it is the
  landlord's own saved answer.
- status "not_answered": say the landlord hasn't answered this yet. Ask whether
  to send it to the landlord, the renter's name, and how they want the reply
  (email, sms, snugd_app, or chat_only). Call send_question_to_landlord only
  after the renter says yes. Never send without a clear yes.
- Later, check_landlord_reply with the reference code shows the landlord's reply.
- Landlords add answers over time. Call ask_landlord again every time a question is
  asked, even if the same question got "not_answered" earlier in this chat.

In-chat cards: hosts that support MCP Apps show search results and landlord
answers as Snugd cards. The renter can send a question to the landlord from the
card themselves; you will then see a message saying so. Do not send it again.
Keep your own text short when a card is shown: the card already lists the details.
"""

# The in-chat card (MCP App). search_apartments and ask_landlord render it; other
# hosts ignore it and get the same data as text. The SDK reads these tools when
# MCPServer is created, so they are defined before `mcp` below.
apps = Apps()
CARD = "ui://snugd/card.html"
apps.add_html_resource(CARD, (Path(__file__).parent / "ui" / "app.html").read_text(),
                       title="Snugd card", prefers_border=False)

Amenity = Literal["in_unit_laundry", "laundry_in_building", "dishwasher", "central_ac", "parking",
                  "gym", "elevator", "outdoor_space", "doorman"]
Place = Literal[tuple(LANDMARKS)]  # type: ignore[valid-type]
Neighborhood = Literal[tuple(NEIGHBORHOODS)]  # type: ignore[valid-type]
READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)


def user_errors(fn):
    """Turn a fixable problem into a message the model can read and act on."""
    @wraps(fn)
    def inner(*a, **kw):
        try:
            return fn(*a, **kw)
        except service.UserError as e:
            raise ToolError(str(e)) from e
    return inner


@apps.tool(resource_uri=CARD, title="Search apartments", annotations=READ)
@user_errors
def search_apartments(
    max_rent: Annotated[int | None, Field(description="Highest monthly rent in USD")] = None,
    min_beds: Annotated[int, Field(ge=0, le=6, description="Minimum bedrooms. 0 means studios are fine")] = 0,
    pets: Annotated[Literal["none", "cat", "dog"], Field(description="Pet the renter has")] = "none",
    move_in_by: Annotated[str | None, Field(pattern=r"^\d{4}-\d{2}-\d{2}$",
                                            description="Latest move-in date, YYYY-MM-DD")] = None,
    near: Annotated[Place | None, Field(description="Place the renter commutes to")] = None,
    neighborhoods: Annotated[list[Neighborhood] | None, Field(description="Only these areas")] = None,
    must_have: Annotated[list[Amenity] | None, Field(description="Amenities that are required")] = None,
    nice_to_have: Annotated[list[Amenity] | None, Field(description="Amenities that are a plus")] = None,
    limit: Annotated[int, Field(ge=1, le=10)] = 5,
) -> dict[str, Any]:
    """Find and rank apartments that fit the renter. Returns the best matches with a
    fit score and plain reasons, plus near-misses when few listings fit."""
    filters = {k: v for k, v in locals().items() if k != "limit" and v not in (None, [])}
    return service.search(filters, limit)


@apps.tool(resource_uri=CARD, title="Ask the landlord", annotations=READ)  # read-only for the renter; it logs the question for the landlord
@user_errors
def ask_landlord(
    listing_id: Annotated[str, Field(description="Listing id, e.g. A101")],
    question: Annotated[str, Field(min_length=3, max_length=500,
                                   description="ONE question, in the renter's words")],
) -> dict[str, Any]:
    """Get the landlord's own answer to a question about a listing. Returns the
    landlord's saved answer when one fits; otherwise status not_answered and a
    reference code to send the question to the landlord."""
    return service.ask_landlord(listing_id, question)


mcp = MCPServer("snugd", title="Snugd apartment search", version="0.1.0", instructions=INSTRUCTIONS,
                extensions=[apps])


@mcp.tool(title="Apartment details", annotations=READ)
@user_errors
def get_apartment(listing_id: Annotated[str, Field(description="Listing id, e.g. A101")]) -> dict[str, Any]:
    """Full details of one listing, including the landlord's company name."""
    return service.get_listing(listing_id)


@mcp.tool(title="Send question to landlord",
          annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                      idempotent_hint=True, open_world_hint=True))
@user_errors
def send_question_to_landlord(
    reference_code: Annotated[str, Field(description="From ask_landlord")],
    renter_name: Annotated[str, Field(min_length=1, max_length=100)],
    channel: Annotated[Literal["email", "sms", "snugd_app", "chat_only"],
                       Field(description="How the renter wants the reply")],
    contact: Annotated[str | None, Field(description="Email, phone or Snugd username. Not needed for chat_only")] = None,
) -> dict[str, Any]:
    """Put the renter's question in the landlord's queue and notify the landlord.
    ONLY call this after the renter has clearly said yes to sending it."""
    return service.send_to_landlord(reference_code, renter_name, channel, contact)


@mcp.tool(title="Check landlord reply", annotations=READ)
@user_errors
def check_landlord_reply(reference_code: Annotated[str, Field(description="From ask_landlord")]) -> dict[str, Any]:
    """See whether the landlord has replied to a question that was sent to them."""
    return service.check_reply(reference_code)
