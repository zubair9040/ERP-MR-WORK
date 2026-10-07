"""Small line icons (24x24, stroke) used across the app."""
from markupsafe import Markup

PATHS = {
    "home": '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.6 3.2-5.5 6.5-5.5s5.9 1.9 6.5 5.5"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8"/><path d="M18 14.8c2 .7 3.2 2.4 3.5 5.2"/>',
    "invoice": '<path d="M6 2.5h9l4 4V21.5H6z"/><path d="M15 2.5v4h4"/><path d="M9 11h7M9 14.5h7M9 18h4"/>',
    "wallet": '<rect x="2.5" y="6" width="19" height="14" rx="2.5"/><path d="M2.5 10h19"/><path d="M6 6l9-3.5 1.5 3.5"/><circle cx="17" cy="15" r="1.2"/>',
    "box": '<path d="M3 7.5l9-4.5 9 4.5v9L12 21l-9-4.5z"/><path d="M3 7.5l9 4.5 9-4.5M12 12v9"/>',
    "calendar": '<rect x="3" y="4.5" width="18" height="16.5" rx="2.5"/><path d="M3 9.5h18M8 2.5v4M16 2.5v4"/><path d="M7.5 13.5h3v3h-3z"/>',
    "chart": '<path d="M3 21h18"/><rect x="5" y="11" width="3.2" height="7" rx=".8"/><rect x="10.4" y="6" width="3.2" height="12" rx=".8"/><rect x="15.8" y="13.5" width="3.2" height="4.5" rx=".8"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "chat": '<path d="M20.5 11.5a8.5 8 0 0 1-12.2 7.2L3.5 20l1.4-4.2A8.5 8 0 1 1 20.5 11.5z"/><path d="M8.5 11.5h.01M12 11.5h.01M15.5 11.5h.01"/>',
    "whatsapp": '<path d="M20.5 11.7a8.4 8.4 0 0 1-12.4 7.4L3.5 20.5l1.5-4.4a8.4 8.4 0 1 1 15.5-4.4z"/><path d="M9 8.3c.3-.6.7-.6 1-.6.4 0 .6.1.8.6l.5 1.3c.1.3 0 .6-.2.8l-.5.5c.5 1 1.3 1.8 2.3 2.3l.5-.5c.2-.2.5-.3.8-.2l1.3.5c.5.2.6.4.6.8 0 .3 0 .7-.6 1-.6.4-1.8.6-3.5-.4a9 9 0 0 1-3-3c-1-1.7-.8-2.9-.4-3.5z"/>',
    "rep": '<circle cx="12" cy="7.5" r="4"/><path d="M4 21c.8-4.2 4-6.5 8-6.5s7.2 2.3 8 6.5"/><path d="M12 14.5l-1.2 2.2L12 21l1.2-4.3z"/>',
    "shield": '<path d="M12 2.5l8 3v6c0 5-3.4 8.6-8 10-4.6-1.4-8-5-8-10v-6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
    "settings": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    "upload": '<path d="M12 16V4M7 8.5L12 4l5 4.5"/><path d="M4 15v4.5h16V15"/>',
    "download": '<path d="M12 4v12M7 11.5l5 4.5 5-4.5"/><path d="M4 15v4.5h16V15"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "save": '<path d="M5 3.5h11.5l3 3V20.5H5z"/><path d="M8 3.5v5h7v-5"/><rect x="8" y="13" width="8" height="7.5" rx="1"/>',
    "print": '<path d="M7 8V3.5h10V8"/><rect x="3.5" y="8" width="17" height="8.5" rx="2"/><rect x="7" y="13.5" width="10" height="7" rx="1"/>',
    "send": '<path d="M21 3L10 14"/><path d="M21 3l-6.5 18-4.5-7-7-4.5z"/>',
    "left": '<path d="M15 5l-7 7 7 7"/>',
    "right": '<path d="M9 5l7 7-7 7"/>',
    "more": '<circle cx="5.5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="18.5" cy="12" r="1.3"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>',
    "cash": '<rect x="2.5" y="6" width="19" height="12" rx="2"/><circle cx="12" cy="12" r="2.8"/><path d="M6 9.5v5M18 9.5v5"/>',
    "pdf": '<path d="M6 2.5h9l4 4V21.5H6z"/><path d="M15 2.5v4h4"/><path d="M8.5 16.5v-4h1.5a1.2 1.2 0 0 1 0 2.4H8.5M13 12.5v4h1.2a2 2 0 0 0 0-4zM17.5 12.5h-1.8v4M15.7 14.4h1.5"/>',
    "excel": '<path d="M6 2.5h9l4 4V21.5H6z"/><path d="M15 2.5v4h4"/><path d="M9 12l5 5.5M14 12l-5 5.5"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M20.5 20.5l-4.8-4.8"/>',
    "logout": '<path d="M14 4h5v16h-5"/><path d="M10 8l-4 4 4 4M6 12h10"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M16.5 6.5l2.5 2.5"/>',
    "trend": '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    "alert": '<path d="M12 3l9.5 17h-19z"/><path d="M12 10v4.5M12 17.5h.01"/>',
    "check": '<path d="M4.5 12.5l5 5 10-11"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "import": '<path d="M4 4.5h16v15H4z"/><path d="M4 9h16M9 9v10.5"/><path d="M12.5 14.5h5M15 12v5"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "truck": '<path d="M2.5 6h11v10h-11z"/><path d="M13.5 9.5h4l3 3.5V16h-7"/><circle cx="6.5" cy="17.5" r="1.8"/><circle cx="17" cy="17.5" r="1.8"/>',
    "return": '<path d="M9 14L4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "tag": '<path d="M3 12V3.5h8.5l9 9-8.5 8.5z"/><circle cx="7.5" cy="7.5" r="1.4"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    "layers": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
}


def icon(name, size=18, cls=""):
    d = PATHS.get(name, "")
    return Markup(f'<svg class="ic {cls}" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
                  f'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" '
                  f'aria-hidden="true">{d}</svg>')
