"""Turn inspection records into the weekly Telegram digest."""

from collections import Counter
from datetime import date

from .models import Inspection
from .telegram import escape

# How many inspections to show in full detail before collapsing to a list.
DETAIL_LIMIT = 12
# How many violation lines to show per inspection.
VIOLATION_LIMIT = 4


def _fmt_range(start: date, end: date) -> str:
    if start.year == end.year:
        return f"{start:%b %-d} – {end:%b %-d, %Y}"
    return f"{start:%b %-d, %Y} – {end:%b %-d, %Y}"


def _headline(inspection: Inspection) -> str:
    """A short severity tag for the top of an entry."""
    n_priority = len(inspection.priority_violations)
    if n_priority >= 5:
        return "🔴"
    if n_priority >= 1:
        return "🟠"
    if inspection.violations:
        return "🟡"
    return "🟢"


def _render_inspection(inspection: Inspection, detailed: bool) -> str:
    name = escape(inspection.establishment)
    tag = _headline(inspection)

    if inspection.url:
        title = f'{tag} <a href="{escape(inspection.url)}"><b>{name}</b></a>'
    else:
        title = f"{tag} <b>{name}</b>"

    meta = [f"{inspection.inspection_date:%a %b %-d}"]
    if inspection.inspection_type:
        meta.append(escape(inspection.inspection_type))
    if inspection.address:
        meta.append(escape(inspection.address))
    lines = [title, f"<i>{' · '.join(meta)}</i>"]

    if inspection.is_clean:
        lines.append("No violations cited.")
        return "\n".join(lines)

    n_priority = len(inspection.priority_violations)
    n_repeat = len(inspection.repeat_violations)
    summary = f"{len(inspection.violations)} violation{'s' if len(inspection.violations) != 1 else ''}"
    if n_priority:
        summary += f", {n_priority} priority"
    if n_repeat:
        summary += f", {n_repeat} repeat"
    lines.append(summary)

    if detailed:
        # Worst first, so the truncation drops the least important lines.
        shown = sorted(inspection.violations, key=lambda v: (v.rank, not v.repeat))[:VIOLATION_LIMIT]
        for v in shown:
            marks = []
            if v.repeat:
                marks.append("repeat")
            if v.corrected_on_site:
                marks.append("corrected on site")
            suffix = f" <i>({', '.join(marks)})</i>" if marks else ""
            text = escape(v.text.strip())
            if len(text) > 180:
                text = text[:177] + "…"
            bullet = "•" if not v.is_priority else "‼️"
            lines.append(f"  {bullet} {text}{suffix}")
        remaining = len(inspection.violations) - len(shown)
        if remaining > 0:
            lines.append(f"  <i>+ {remaining} more</i>")

    return "\n".join(lines)


def build_digest(
    inspections: list[Inspection],
    start: date,
    end: date,
    source_links: dict[str, str] | None = None,
) -> str:
    """Render the full digest as Telegram-flavored HTML."""
    header = f"<b>🍽 Restaurant inspections</b>\n<i>{_fmt_range(start, end)}</i>"

    if not inspections:
        return (
            f"{header}\n\nNo inspections were published for Henrico County or "
            f"Richmond City this week."
        )

    total = len(inspections)
    with_priority = [i for i in inspections if i.priority_violations]
    clean = [i for i in inspections if i.is_clean]
    by_place = Counter(i.jurisdiction for i in inspections)

    place_summary = ", ".join(f"{n} in {escape(p)}" for p, n in sorted(by_place.items()))
    overview = (
        f"{total} inspection{'s' if total != 1 else ''} ({place_summary})\n"
        f"{len(with_priority)} with priority violations · {len(clean)} with none"
    )

    sections = [header, overview]

    for jurisdiction in sorted(by_place):
        rows = sorted(
            (i for i in inspections if i.jurisdiction == jurisdiction),
            key=lambda i: i.severity_key(),
        )
        sections.append(f"\n<b>━━ {escape(jurisdiction)} ━━</b>")

        detailed = [r for r in rows if r.violations][:DETAIL_LIMIT]
        for row in detailed:
            sections.append(_render_inspection(row, detailed=True))

        rest = [r for r in rows if r not in detailed]
        if rest:
            listed = [r for r in rest if r.violations]
            spotless = [r for r in rest if r.is_clean]
            if listed:
                sections.append("<b>Also cited</b>")
                for row in listed:
                    sections.append(_render_inspection(row, detailed=False))
            if spotless:
                names = ", ".join(escape(r.establishment) for r in spotless)
                sections.append(f"<b>🟢 No violations</b>\n{names}")

    if source_links:
        links = " · ".join(
            f'<a href="{escape(url)}">{escape(name)}</a>' for name, url in source_links.items()
        )
        sections.append(f"\n<i>Source: Virginia Dept. of Health — {links}</i>")

    return "\n\n".join(sections)
