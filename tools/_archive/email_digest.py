from __future__ import annotations

"""
email_digest.py

Sends a beautifully formatted HTML email digest of new apartment listings.
Part of the WAT framework apartment hunting automation.

Environment variables required:
    EMAIL_FROM          - Gmail address to send from
    EMAIL_TO            - Gmail address to send to
    GMAIL_APP_PASSWORD  - Gmail App Password (16-char, spaces optional)
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def format_score_bar(score: float, max_score: float = 100) -> str:
    """Return a 10-char ASCII progress bar, e.g. '████████░░ 82/100'."""
    filled = round((score / max_score) * 10)
    filled = max(0, min(10, filled))
    bar = "█" * filled + "░" * (10 - filled)
    return f"{bar} {int(score)}/{int(max_score)}"


def _badge(label: str, bg: str, fg: str = "#ffffff") -> str:
    """Return an inline-styled badge span."""
    style = (
        f"display:inline-block;"
        f"background:{bg};"
        f"color:{fg};"
        f"font-size:11px;"
        f"font-weight:600;"
        f"padding:2px 8px;"
        f"border-radius:12px;"
        f"margin:2px 3px 2px 0;"
        f"white-space:nowrap;"
    )
    return f'<span style="{style}">{label}</span>'


def format_listing_card(listing: dict) -> str:
    """
    Return an HTML string for one listing card.

    Expected keys in `listing` (all optional except noted):
        title           str   – display name / address headline *
        url             str   – listing URL
        price           int   – monthly rent in dollars
        total_score     float – 0-100 composite score
        floor           int|str
        caltrain_miles  float – distance to nearest Caltrain stop
        bedrooms        int|str
        in_unit_laundry bool
        gym             bool
        pet_friendly    bool
        rooftop         bool
        city_view       bool
        doorman         bool
        new_building    bool
        address         str
        neighborhood    str
        description     str
        urban_score     float – /35
        price_score     float – /25
        caltrain_score  float – /20
        amenity_score   float – /20
        auto_rejected   bool
        rejection_reason str
    """
    title = listing.get("title", "Untitled Listing")
    url = listing.get("url", "#")
    price = listing.get("price")
    score = listing.get("score_total", 0)
    floor_val = listing.get("floor_number", "—")
    caltrain = listing.get("nearest_caltrain_mi")
    bedrooms = listing.get("bedrooms", "—")
    address = listing.get("address_raw", "")
    neighborhood = listing.get("neighborhood", "")
    description = listing.get("description_snippet", "")
    auto_rejected = listing.get("auto_rejected", False)
    rejection_reason = listing.get("reject_reason", "")

    # Sub-scores
    urban_score = listing.get("score_urban")
    price_score = listing.get("score_price")
    caltrain_score = listing.get("score_caltrain")
    amenity_score = listing.get("score_amenities")

    # Card wrapper
    border_color = "#ef4444" if auto_rejected else "#e5e7eb"
    card_style = (
        f"background:#ffffff;"
        f"border:1px solid {border_color};"
        f"border-radius:10px;"
        f"padding:20px 22px;"
        f"margin-bottom:18px;"
        f"max-width:600px;"
        f"font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
    )

    html_parts = [f'<div style="{card_style}">']

    # --- Auto-rejected banner ---
    if auto_rejected:
        banner_style = (
            "background:#fee2e2;"
            "color:#b91c1c;"
            "font-size:12px;"
            "font-weight:700;"
            "padding:5px 10px;"
            "border-radius:5px;"
            "margin-bottom:12px;"
            "display:block;"
        )
        reason_text = f" — {rejection_reason}" if rejection_reason else ""
        html_parts.append(f'<span style="{banner_style}">AUTO-REJECTED{reason_text}</span>')

    # --- Title (clickable link) ---
    title_style = (
        "font-size:18px;"
        "font-weight:700;"
        "color:#111827;"
        "text-decoration:none;"
        "line-height:1.3;"
    )
    html_parts.append(
        f'<a href="{url}" style="{title_style}" target="_blank">{title}</a>'
    )

    # --- Price + Score row ---
    html_parts.append('<div style="margin-top:10px;display:flex;align-items:baseline;gap:16px;flex-wrap:wrap;">')

    if price is not None:
        price_style = "font-size:22px;font-weight:800;color:#16a34a;margin-right:4px;"
        html_parts.append(f'<span style="{price_style}">${price:,}/mo</span>')

    # Score — make it visually dominant
    score_container = (
        "background:#eff6ff;"
        "border:1px solid #bfdbfe;"
        "border-radius:8px;"
        "padding:6px 12px;"
        "display:inline-block;"
    )
    score_label_style = "font-size:11px;color:#6b7280;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;"
    score_value_style = "font-size:20px;font-weight:800;color:#2563eb;display:block;line-height:1.1;"
    bar_style = "font-size:13px;color:#2563eb;font-family:monospace;display:block;margin-top:2px;"
    score_bar = format_score_bar(score)
    html_parts.append(
        f'<div style="{score_container}">'
        f'<span style="{score_label_style}">Score</span>'
        f'<span style="{score_value_style}">{int(score)}<span style="font-size:13px;color:#6b7280;">/100</span></span>'
        f'<span style="{bar_style}">{score_bar}</span>'
        f'</div>'
    )

    html_parts.append('</div>')  # close price+score row

    # --- Key stats row ---
    stat_style = (
        "font-size:13px;"
        "color:#374151;"
        "background:#f9fafb;"
        "border:1px solid #e5e7eb;"
        "border-radius:6px;"
        "padding:4px 10px;"
        "margin-right:6px;"
        "white-space:nowrap;"
    )
    caltrain_str = f"{caltrain:.1f} mi" if caltrain is not None else "—"
    html_parts.append(
        f'<div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:6px;">'
        f'<span style="{stat_style}">Floor {floor_val}</span>'
        f'<span style="{stat_style}">🚂 {caltrain_str} to Caltrain</span>'
        f'<span style="{stat_style}">{bedrooms} bed</span>'
        f'</div>'
    )

    # --- Feature badges ---
    badge_map = [
        ("has_inunit_laundry", "In-unit laundry", "#16a34a"),
        ("has_gym", "Gym", "#2563eb"),
        ("is_pet_friendly", "Pet-friendly", "#7c3aed"),
        ("has_rooftop", "Rooftop", "#0d9488"),
        ("has_view", "City view", "#ea580c"),
        ("has_doorman", "Doorman", "#6b7280"),
        ("is_new_construction", "New building", "#ca8a04", "#1f2937"),
    ]
    badges = []
    for item in badge_map:
        key, label = item[0], item[1]
        bg = item[2]
        fg = item[3] if len(item) > 3 else "#ffffff"
        if listing.get(key):
            badges.append(_badge(label, bg, fg))

    if badges:
        html_parts.append(f'<div style="margin-top:10px;">{"".join(badges)}</div>')

    # --- Address / neighborhood ---
    if address or neighborhood:
        loc_parts = []
        if address:
            loc_parts.append(address)
        if neighborhood:
            loc_parts.append(f"<em>{neighborhood}</em>")
        addr_style = "font-size:13px;color:#6b7280;margin-top:8px;"
        html_parts.append(f'<div style="{addr_style}">📍 {", ".join(loc_parts)}</div>')

    # --- Description snippet ---
    if description:
        snippet = description[:200].rstrip()
        if len(description) > 200:
            snippet += "…"
        desc_style = (
            "font-size:13px;"
            "color:#4b5563;"
            "margin-top:10px;"
            "line-height:1.5;"
            "border-left:3px solid #e5e7eb;"
            "padding-left:10px;"
        )
        html_parts.append(f'<div style="{desc_style}">{snippet}</div>')

    # --- Sub-scores ---
    sub_score_pairs = [
        ("Urban", urban_score, 35),
        ("Price", price_score, 25),
        ("Caltrain", caltrain_score, 20),
        ("Amenities", amenity_score, 20),
    ]
    valid_pairs = [(label, val, mx) for label, val, mx in sub_score_pairs if val is not None]

    if valid_pairs:
        html_parts.append(
            '<div style="margin-top:12px;padding-top:10px;border-top:1px solid #f3f4f6;">'
            '<span style="font-size:11px;color:#9ca3af;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;">Sub-scores</span>'
            '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:6px;">'
        )
        for label, val, mx in valid_pairs:
            pct = int(round((val / mx) * 100))
            color = "#16a34a" if pct >= 75 else "#d97706" if pct >= 50 else "#dc2626"
            chip_style = (
                f"font-size:12px;color:{color};font-weight:600;"
                "background:#f9fafb;border:1px solid #e5e7eb;"
                "border-radius:5px;padding:2px 8px;"
            )
            html_parts.append(f'<span style="{chip_style}">{label} {int(val)}/{mx}</span>')
        html_parts.append('</div></div>')

    html_parts.append('</div>')  # close card
    return "\n".join(html_parts)


# ---------------------------------------------------------------------------
# Email builder
# ---------------------------------------------------------------------------

def build_html_email(new_listings: list[dict], run_metadata: dict) -> str:
    """
    Build and return the full HTML email body.

    run_metadata keys (all optional):
        sources_scraped   list[str] | int
        total_seen        int
        timestamp         str  (ISO or human-readable)
    """
    now = datetime.now()
    timestamp = run_metadata.get("timestamp") or now.strftime("%B %d, %Y at %I:%M %p")
    sources = run_metadata.get("sources_scraped", [])
    if isinstance(sources, list):
        sources_str = ", ".join(sources) if sources else "—"
        sources_count = len(sources)
    else:
        sources_str = str(sources)
        sources_count = int(sources)

    # Partition listings
    accepted = [l for l in new_listings if not l.get("auto_rejected")]
    rejected = [l for l in new_listings if l.get("auto_rejected")]
    top_listings = sorted(accepted, key=lambda l: l.get("score_total", 0), reverse=True)[:10]

    n_new = len(new_listings)
    n_rejected = len(rejected)

    # -----------------------------------------------------------------------
    # Boilerplate
    # -----------------------------------------------------------------------
    body_style = (
        "margin:0;padding:0;"
        "background:#f3f4f6;"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
    )
    wrapper_style = (
        "max-width:600px;"
        "margin:0 auto;"
        "padding:24px 16px;"
    )

    # -----------------------------------------------------------------------
    # Header
    # -----------------------------------------------------------------------
    header_style = (
        "background:#2563eb;"
        "border-radius:10px 10px 0 0;"
        "padding:28px 28px 22px;"
        "text-align:center;"
    )
    h1_style = "font-size:26px;font-weight:800;color:#ffffff;margin:0 0 6px;"
    sub_style = "font-size:13px;color:#bfdbfe;margin:0;"

    header_html = (
        f'<div style="{header_style}">'
        f'<h1 style="{h1_style}">🏙️ SF Apartment Hunt — {n_new} New Listing{"s" if n_new != 1 else ""}</h1>'
        f'<p style="{sub_style}">{timestamp}</p>'
        f'</div>'
    )

    # -----------------------------------------------------------------------
    # Summary stats bar
    # -----------------------------------------------------------------------
    stats_style = (
        "background:#1d4ed8;"
        "padding:14px 28px;"
        "border-radius:0;"
        "display:flex;"
    )
    stat_item_style = (
        "flex:1;"
        "text-align:center;"
    )
    stat_num_style = "font-size:22px;font-weight:800;color:#ffffff;display:block;"
    stat_lbl_style = "font-size:11px;color:#bfdbfe;text-transform:uppercase;letter-spacing:0.07em;"

    stats_html = (
        f'<div style="{stats_style}">'
        f'<div style="{stat_item_style}">'
        f'<span style="{stat_num_style}">{n_new}</span>'
        f'<span style="{stat_lbl_style}">New Listings</span>'
        f'</div>'
        f'<div style="{stat_item_style}">'
        f'<span style="{stat_num_style}">{n_rejected}</span>'
        f'<span style="{stat_lbl_style}">Auto-rejected</span>'
        f'</div>'
        f'<div style="{stat_item_style}">'
        f'<span style="{stat_num_style}">{sources_count if isinstance(sources_count, int) else "—"}</span>'
        f'<span style="{stat_lbl_style}">Sources</span>'
        f'</div>'
        f'</div>'
    )

    # -----------------------------------------------------------------------
    # Sources row
    # -----------------------------------------------------------------------
    if sources_str and sources_str != "—":
        sources_html = (
            f'<div style="background:#eff6ff;border-radius:0;padding:8px 28px;text-align:center;">'
            f'<span style="font-size:12px;color:#6b7280;">Sources: <strong style="color:#374151;">{sources_str}</strong></span>'
            f'</div>'
        )
    else:
        sources_html = ""

    # -----------------------------------------------------------------------
    # Listings section
    # -----------------------------------------------------------------------
    content_wrap_style = (
        "background:#f3f4f6;"
        "border-radius:0 0 10px 10px;"
        "padding:20px 16px 16px;"
    )

    section_heading_style = (
        "font-size:14px;"
        "font-weight:700;"
        "color:#6b7280;"
        "text-transform:uppercase;"
        "letter-spacing:0.07em;"
        "margin:0 0 14px;"
        "padding-bottom:8px;"
        "border-bottom:2px solid #e5e7eb;"
    )

    listings_html_parts = []

    if top_listings:
        listings_html_parts.append(
            f'<h2 style="{section_heading_style}">'
            f'Top Listings ({len(top_listings)})'
            f'</h2>'
        )
        for listing in top_listings:
            listings_html_parts.append(format_listing_card(listing))
    else:
        empty_style = (
            "text-align:center;padding:40px 20px;"
            "color:#9ca3af;font-size:14px;"
        )
        listings_html_parts.append(
            f'<div style="{empty_style}">No qualifying listings found this run.</div>'
        )

    # -----------------------------------------------------------------------
    # Auto-rejected section (collapsed via details/summary — no JS needed)
    # -----------------------------------------------------------------------
    rejected_html = ""
    if rejected:
        rej_heading_style = (
            "font-size:14px;"
            "font-weight:700;"
            "color:#9ca3af;"
            "text-transform:uppercase;"
            "letter-spacing:0.07em;"
            "margin:20px 0 10px;"
            "padding-bottom:8px;"
            "border-bottom:2px solid #fee2e2;"
        )
        rej_parts = [
            f'<h2 style="{rej_heading_style}">'
            f'{len(rejected)} Listing{"s" if len(rejected) != 1 else ""} Filtered Out'
            f'</h2>'
        ]
        for listing in rejected:
            rej_parts.append(format_listing_card(listing))
        rejected_html = "\n".join(rej_parts)

    # -----------------------------------------------------------------------
    # Footer
    # -----------------------------------------------------------------------
    footer_style = (
        "text-align:center;"
        "padding:20px;"
        "font-size:11px;"
        "color:#9ca3af;"
        "line-height:1.6;"
    )
    footer_html = (
        f'<div style="{footer_style}">'
        f'SF Apartment Hunt — automated digest<br>'
        f'Scores: Urban /35 · Price /25 · Caltrain /20 · Amenities /20'
        f'</div>'
    )

    # -----------------------------------------------------------------------
    # Assemble
    # -----------------------------------------------------------------------
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<title>SF Apartment Hunt Digest</title>
</head>
<body style="{body_style}">
<div style="{wrapper_style}">

{header_html}
{stats_html}
{sources_html}

<div style="{content_wrap_style}">
{"".join(listings_html_parts)}
{rejected_html}
</div>

{footer_html}

</div>
</body>
</html>"""

    return html


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------

def send_email(html_body: str, subject: str) -> bool:
    """
    Send an HTML email via Gmail SMTP (port 587, STARTTLS).
    Returns True on success, False on failure.
    """
    email_from = os.getenv("EMAIL_FROM", "").strip()
    email_to = os.getenv("EMAIL_TO", "").strip()
    app_password = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()

    if not email_from or not app_password:
        print(
            "[email_digest] ERROR: EMAIL_FROM or GMAIL_APP_PASSWORD not set.\n"
            "  Add to .env:\n"
            "    EMAIL_FROM=you@gmail.com\n"
            "    EMAIL_TO=you@gmail.com\n"
            "    GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx\n"
            "  Generate an App Password at: https://myaccount.google.com/apppasswords"
        )
        return False

    recipient = email_to or email_from  # default to sending to self

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = recipient

    # Plain-text fallback
    plain_text = (
        "Your email client does not support HTML.\n"
        "Please view this digest in a modern email client."
    )
    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.ehlo()
            server.starttls()
            server.login(email_from, app_password)
            server.sendmail(email_from, recipient, msg.as_string())
        print(f"[email_digest] Email sent → {recipient}")
        return True
    except smtplib.SMTPAuthenticationError:
        print(
            "[email_digest] Authentication failed. Check EMAIL_FROM and GMAIL_APP_PASSWORD.\n"
            "  Tip: Make sure 2FA is enabled on your Google account and you're using\n"
            "  an App Password (not your regular password)."
        )
        return False
    except smtplib.SMTPException as exc:
        print(f"[email_digest] SMTP error: {exc}")
        return False
    except OSError as exc:
        print(f"[email_digest] Network error: {exc}")
        return False


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

def send_digest(new_listings: list[dict], run_metadata: dict) -> bool:
    """
    Build and send the apartment digest email.

    Args:
        new_listings:  List of listing dicts (see format_listing_card for schema).
        run_metadata:  Dict with keys like sources_scraped, timestamp, etc.

    Returns:
        True if email was sent successfully, False otherwise.
    """
    email_from = os.getenv("EMAIL_FROM", "").strip()
    app_password = os.getenv("GMAIL_APP_PASSWORD", "").strip()

    if not email_from or not app_password:
        print(
            "[email_digest] Setup required — add the following to your .env file:\n"
            "    EMAIL_FROM=you@gmail.com\n"
            "    EMAIL_TO=you@gmail.com          # optional, defaults to EMAIL_FROM\n"
            "    GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx\n"
            "\n"
            "  To generate an App Password:\n"
            "    1. Enable 2-Step Verification on your Google Account\n"
            "    2. Go to https://myaccount.google.com/apppasswords\n"
            "    3. Create an app password for 'Mail'\n"
        )
        return False

    now = datetime.now()
    hour = now.hour
    if hour < 12:
        time_of_day = "Morning"
    elif hour < 17:
        time_of_day = "Afternoon"
    else:
        time_of_day = "Evening"

    n = len(new_listings)
    date_str = now.strftime("%b %d")
    subject = f"SF Apartments — {n} new listing{'s' if n != 1 else ''} [{time_of_day}] {date_str}"

    html_body = build_html_email(new_listings, run_metadata)
    return send_email(html_body, subject)


# ---------------------------------------------------------------------------
# Test / CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mock_listings = [
        {
            "title": "Bright 1BR in SoMa High-Rise",
            "url": "https://www.example.com/listing/1",
            "price": 3_200,
            "total_score": 87,
            "floor": 14,
            "caltrain_miles": 0.3,
            "bedrooms": 1,
            "in_unit_laundry": True,
            "gym": True,
            "pet_friendly": False,
            "rooftop": True,
            "city_view": True,
            "doorman": True,
            "new_building": True,
            "address": "425 Mission St",
            "neighborhood": "SoMa",
            "description": (
                "Stunning 14th-floor unit with panoramic Bay Bridge views. "
                "Floor-to-ceiling windows, chef's kitchen with quartz countertops, "
                "in-unit washer/dryer, and access to rooftop lounge. Building features "
                "24-hour concierge, state-of-the-art fitness center, and bike storage."
            ),
            "urban_score": 31,
            "price_score": 20,
            "caltrain_score": 18,
            "amenity_score": 18,
            "auto_rejected": False,
        },
        {
            "title": "Cozy Studio near Castro",
            "url": "https://www.example.com/listing/2",
            "price": 2_450,
            "total_score": 61,
            "floor": 2,
            "caltrain_miles": 1.8,
            "bedrooms": "Studio",
            "in_unit_laundry": False,
            "gym": False,
            "pet_friendly": True,
            "rooftop": False,
            "city_view": False,
            "doorman": False,
            "new_building": False,
            "address": "3901 18th St",
            "neighborhood": "Castro",
            "description": (
                "Charming studio in the heart of the Castro. Hardwood floors, "
                "updated kitchen, and tons of natural light. Shared laundry in building. "
                "Walking distance to Muni, grocery stores, and all the neighborhood has to offer."
            ),
            "urban_score": 24,
            "price_score": 18,
            "caltrain_score": 9,
            "amenity_score": 10,
            "auto_rejected": False,
        },
        {
            "title": "1BR Apartment — Tenderloin",
            "url": "https://www.example.com/listing/3",
            "price": 1_800,
            "total_score": 34,
            "floor": 1,
            "caltrain_miles": 0.9,
            "bedrooms": 1,
            "in_unit_laundry": False,
            "gym": False,
            "pet_friendly": False,
            "rooftop": False,
            "city_view": False,
            "doorman": False,
            "new_building": False,
            "address": "500 Eddy St",
            "neighborhood": "Tenderloin",
            "description": (
                "Affordable 1-bedroom in central SF. Basic amenities, close to public transit."
            ),
            "urban_score": 16,
            "price_score": 22,
            "caltrain_score": 12,
            "amenity_score": 4,
            "auto_rejected": True,
            "rejection_reason": "Below score threshold (34 < 50)",
        },
    ]

    mock_metadata = {
        "sources_scraped": ["Zillow", "Craigslist", "Apartments.com"],
        "timestamp": datetime.now().strftime("%B %d, %Y at %I:%M %p"),
    }

    html = build_html_email(mock_listings, mock_metadata)

    email_from = os.getenv("EMAIL_FROM", "").strip()
    app_password = os.getenv("GMAIL_APP_PASSWORD", "").strip()

    if email_from and app_password:
        success = send_digest(mock_listings, mock_metadata)
        if success:
            print("Test email sent successfully.")
        else:
            print("Test email failed to send.")
    else:
        print(f"Test email built successfully, {len(html):,} chars.")
        print("(Set EMAIL_FROM and GMAIL_APP_PASSWORD in .env to actually send it.)")
