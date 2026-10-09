from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

try:
    from content_models import ActionLink, BlockType, PageKey, PageModel, SectionModel, MetaModel, HeroModel
except ImportError:  # pragma: no cover
    from scripts.content_models import ActionLink, BlockType, PageKey, PageModel, SectionModel, MetaModel, HeroModel  # type: ignore

EditorKind = Literal[
    "entry",
    "textarea",
    "token_list",
    "action_list",
    "checkbox",
    "combobox",
    "work_picker",
    "series_picker",
    "document_picker",
    "reorder_list",
    "card_list",
    "metric_list",
]


@dataclass(frozen=True, slots=True)
class FieldSpec:
    key: str
    label: str
    editor: EditorKind
    required: bool = False
    help_text: str = ""
    placeholder: str = ""
    options: tuple[str, ...] = ()
    rows: int = 1


@dataclass(frozen=True, slots=True)
class BlockSpec:
    type: BlockType
    label: str
    description: str
    allowed_pages: tuple[PageKey, ...]
    locked: bool = False
    fields: tuple[FieldSpec, ...] = field(default_factory=tuple)


def block_registry() -> dict[BlockType, BlockSpec]:
    return {
        "rich_text": BlockSpec(
            type="rich_text",
            label="Rich text",
            description="Narrative block with optional actions.",
            allowed_pages=("home", "about", "contact", "portfolio", "series", "performance"),
            fields=(
                FieldSpec("eyebrow", "Eyebrow", "entry"),
                FieldSpec("title", "Title", "entry", required=True),
                FieldSpec("text", "Body", "textarea", required=True, rows=8),
                FieldSpec("actions", "Actions", "action_list"),
            ),
        ),
        "card_grid": BlockSpec(
            type="card_grid",
            label="Card grid",
            description="Ordered group of editorial cards.",
            allowed_pages=("about", "performance"),
            fields=(
                FieldSpec("eyebrow", "Eyebrow", "entry"),
                FieldSpec("title", "Title", "entry"),
                FieldSpec("intro", "Intro", "textarea", rows=4),
                FieldSpec("items", "Cards", "card_list", required=True),
            ),
        ),
        "cta_band": BlockSpec(
            type="cta_band",
            label="CTA band",
            description="Call-to-action band with text and actions.",
            allowed_pages=("about", "contact", "performance"),
            fields=(
                FieldSpec("eyebrow", "Eyebrow", "entry"),
                FieldSpec("title", "Title", "entry", required=True),
                FieldSpec("text", "Body", "textarea", rows=4),
                FieldSpec("actions", "Actions", "action_list"),
            ),
        ),
        "document_list": BlockSpec(
            type="document_list",
            label="Document list",
            description="Public document block with selected downloads.",
            allowed_pages=("about", "contact", "series", "performance"),
            fields=(
                FieldSpec("eyebrow", "Eyebrow", "entry"),
                FieldSpec("title", "Title", "entry"),
                FieldSpec("intro", "Intro", "textarea", rows=4),
                FieldSpec("document_ids", "Documents", "document_picker"),
            ),
        ),
        "featured_series": BlockSpec(
            type="featured_series",
            label="Featured series",
            description="Curated homepage series list.",
            allowed_pages=("home",),
            fields=(
                FieldSpec("eyebrow", "Eyebrow", "entry"),
                FieldSpec("title", "Title", "entry"),
                FieldSpec("intro", "Intro", "textarea", rows=4),
                FieldSpec("series_slugs", "Series", "series_picker"),
            ),
        ),
        "featured_works": BlockSpec(
            type="featured_works",
            label="Featured works",
            description="Curated homepage work list.",
            allowed_pages=("home",),
            fields=(
                FieldSpec("eyebrow", "Eyebrow", "entry"),
                FieldSpec("title", "Title", "entry"),
                FieldSpec("intro", "Intro", "textarea", rows=4),
                FieldSpec("work_ids", "Works", "work_picker"),
            ),
        ),
        "work_spotlight": BlockSpec(
            type="work_spotlight",
            label="Work spotlight",
            description="One highlighted work and supporting copy.",
            allowed_pages=("home",),
            fields=(
                FieldSpec("eyebrow", "Eyebrow", "entry"),
                FieldSpec("title", "Title", "entry"),
                FieldSpec("text", "Body", "textarea", rows=4),
                FieldSpec("work_id", "Work", "combobox"),
                FieldSpec("action", "Action", "action_list"),
            ),
        ),
        "series_index": BlockSpec(
            type="series_index",
            label="Series index",
            description="Homepage index module for public series.",
            allowed_pages=("home",),
            fields=(
                FieldSpec("eyebrow", "Eyebrow", "entry"),
                FieldSpec("title", "Title", "entry"),
                FieldSpec("text", "Body", "textarea", rows=4),
            ),
        ),
        "metrics": BlockSpec(
            type="metrics",
            label="Metrics",
            description="Homepage metrics row.",
            allowed_pages=("home",),
            fields=(FieldSpec("items", "Metrics", "metric_list", required=True),),
        ),
        "contact_form": BlockSpec(
            type="contact_form",
            label="Contact form",
            description="Contact form copy and inquiry options.",
            allowed_pages=("contact",),
            fields=(
                FieldSpec("details_title", "Details title", "entry"),
                FieldSpec("form_intro", "Intro", "textarea", rows=4),
                FieldSpec("form_note", "Note", "textarea", rows=4),
                FieldSpec("form_button_label", "Button label", "entry"),
                FieldSpec("inquiry_types", "Inquiry types", "reorder_list"),
                FieldSpec("form_endpoint", "Endpoint", "entry"),
            ),
        ),
        "direct_contact": BlockSpec(
            type="direct_contact",
            label="Direct contact",
            description="Direct contact instructions block.",
            allowed_pages=("contact",),
            fields=(
                FieldSpec("eyebrow", "Eyebrow", "entry"),
                FieldSpec("title", "Title", "entry"),
                FieldSpec("intro", "Intro", "textarea", rows=4),
            ),
        ),
        "related_series": BlockSpec(
            type="related_series",
            label="Related series",
            description="Heading block for related series.",
            allowed_pages=("series",),
            fields=(
                FieldSpec("eyebrow", "Eyebrow", "entry"),
                FieldSpec("title", "Title", "entry"),
                FieldSpec("intro", "Intro", "textarea", rows=4),
            ),
        ),
        "inquiry_block": BlockSpec(
            type="inquiry_block",
            label="Inquiry block",
            description="Series-page inquiry CTA.",
            allowed_pages=("series",),
            fields=(
                FieldSpec("title", "Title", "entry"),
                FieldSpec("text", "Body", "textarea", rows=4),
                FieldSpec("label", "Button label", "entry"),
                FieldSpec("href", "Button target", "entry"),
            ),
        ),
        "system_portfolio_grid": BlockSpec(
            type="system_portfolio_grid",
            label="Portfolio grid",
            description="Locked system portfolio grid block.",
            allowed_pages=("portfolio",),
            locked=True,
            fields=(),
        ),
        "system_series_runtime": BlockSpec(
            type="system_series_runtime",
            label="Series runtime",
            description="Locked system block that renders current public series.",
            allowed_pages=("series",),
            locked=True,
            fields=(),
        ),
        "bullet_list": BlockSpec(
            type="bullet_list",
            label="Bullet list",
            description="Reserved block type.",
            allowed_pages=("about", "contact", "series"),
            fields=(
                FieldSpec("eyebrow", "Eyebrow", "entry"),
                FieldSpec("title", "Title", "entry"),
                FieldSpec("intro", "Intro", "textarea", rows=4),
                FieldSpec("items", "Items", "reorder_list"),
            ),
        ),
    }



def _default_document_ids() -> list[str]:
    try:
        from helpers_content import load_resources_payload
    except ImportError:  # pragma: no cover
        from scripts.helpers_content import load_resources_payload  # type: ignore
    payload = load_resources_payload() or {}
    ids: list[str] = []
    for item in payload.get("downloads") or []:
        if not isinstance(item, dict):
            continue
        audience = str(item.get("audience") or "public").strip().lower()
        ident = str(item.get("id") or "").strip()
        if ident and audience in {"public", "press"}:
            ids.append(ident)
    return ids


def _document_block_data(block: dict[str, Any] | None, *, eyebrow: str, title: str, intro: str) -> tuple[bool, dict[str, Any]]:
    payload = dict(block or {})
    document_ids = [str(item).strip() for item in (payload.get("document_ids") or []) if str(item).strip()]
    if not document_ids:
        document_ids = _default_document_ids()
    return (payload.get("visible", True) is not False), {
        "eyebrow": str(payload.get("eyebrow") or eyebrow),
        "title": str(payload.get("title") or title),
        "intro": str(payload.get("intro") or intro),
        "document_ids": document_ids,
    }

def block_spec(block_type: BlockType) -> BlockSpec:
    return block_registry()[block_type]


def allowed_block_types(page_key: PageKey) -> tuple[BlockType, ...]:
    return tuple(block_type for block_type, spec in block_registry().items() if page_key in spec.allowed_pages and not spec.locked)


def friendly_block_name(block_type: BlockType) -> str:
    return block_registry()[block_type].label


def default_section(block_type: BlockType, *, seed: str = "") -> SectionModel:
    spec = block_registry()[block_type]
    data: dict[str, Any] = {}
    for field in spec.fields:
        if field.editor in {"entry", "textarea", "combobox"}:
            data[field.key] = ""
        elif field.editor in {"token_list", "reorder_list", "series_picker", "work_picker", "document_picker", "metric_list", "card_list"}:
            data[field.key] = []
        elif field.editor == "action_list":
            data[field.key] = []
        elif field.editor == "checkbox":
            data[field.key] = False
    ident = seed or block_type.replace("_", "-")
    return SectionModel(id=ident, type=block_type, label=spec.label, visible=True, locked=spec.locked, data=data)


def locked_system_sections(page_key: PageKey) -> list[SectionModel]:
    if page_key == "portfolio":
        return [SectionModel(id="portfolio-grid", type="system_portfolio_grid", label="Portfolio grid", visible=True, locked=True, data={})]
    if page_key == "series":
        return [SectionModel(id="series-runtime", type="system_series_runtime", label="Series runtime", visible=True, locked=True, data={})]
    return []


def next_section_id(existing_ids: set[str], seed: str) -> str:
    base = (seed or "section").strip().lower().replace(" ", "-")
    if base not in existing_ids:
        return base
    idx = 2
    while f"{base}-{idx}" in existing_ids:
        idx += 1
    return f"{base}-{idx}"


def _actions_from_legacy(hero: dict[str, Any]) -> list[ActionLink]:
    actions: list[ActionLink] = []
    if isinstance(hero.get("actions"), list):
        actions.extend(ActionLink.from_dict(item) for item in hero.get("actions") or [] if isinstance(item, dict))
    else:
        for key in ("primary_action", "secondary_action"):
            if isinstance(hero.get(key), dict):
                actions.append(ActionLink.from_dict(hero[key]))
    return actions


def normalize_legacy_page_payload(page_key: PageKey, payload: dict[str, Any]) -> PageModel:
    meta = MetaModel.from_dict(payload.get("meta") if isinstance(payload.get("meta"), dict) else {})
    hero_payload = payload.get("hero") if isinstance(payload.get("hero"), dict) else {}
    if page_key == "series":
        hero_payload = dict(hero_payload)
        hero_payload.setdefault("eyebrow", str(payload.get("hero_eyebrow") or "Series"))
        hero_payload.setdefault("title", str(payload.get("hero_title") or "Where Presence Meets Distance"))
        hero_payload.setdefault("lead", str(payload.get("hero_lead") or meta.description or ""))
    hero = HeroModel(
        eyebrow=str(hero_payload.get("eyebrow") or "").strip(),
        title=str(hero_payload.get("title") or "").strip(),
        lead=str(hero_payload.get("lead") or "").strip(),
        feature_work_id=str(hero_payload.get("feature_work_id") or "").strip(),
        actions=_actions_from_legacy(hero_payload),
        notes=[str(item).strip() for item in (hero_payload.get("notes") or []) if str(item).strip()],
    )
    sections: list[SectionModel] = []
    if page_key == "home":
        sections.append(SectionModel(id="metrics", type="metrics", label="Metrics", visible=True, data={"items": list(payload.get("metrics") or [])}))
        fs = dict(payload.get("featured_series") or {})
        sections.append(SectionModel(id="featured-series", type="featured_series", label="Featured series", visible=fs.get("visible", True) is not False, data={
            "eyebrow": str(fs.get("eyebrow") or ""), "title": str(fs.get("title") or ""), "intro": str(fs.get("intro") or ""), "series_slugs": list(fs.get("series_slugs") or [])
        }))
        sw = dict(payload.get("selected_works") or {})
        sections.append(SectionModel(id="featured-works", type="featured_works", label="Selected works", visible=sw.get("visible", True) is not False, data={
            "eyebrow": str(sw.get("eyebrow") or ""), "title": str(sw.get("title") or ""), "intro": str(sw.get("intro") or ""), "work_ids": list(sw.get("work_ids") or [])
        }))
        for index, module in enumerate(payload.get("modules") or [], start=1):
            if not isinstance(module, dict):
                continue
            mod_type = str(module.get("type") or "text")
            if mod_type == "text":
                sections.append(SectionModel(id=f"module-{index}", type="rich_text", label=str(module.get("title") or f"Text {index}"), visible=module.get("visible", True) is not False, data={
                    "eyebrow": str(module.get("eyebrow") or ""), "title": str(module.get("title") or ""), "text": str(module.get("text") or ""), "actions": list(module.get("actions") or [])
                }))
            elif mod_type == "series_index":
                sections.append(SectionModel(id=f"module-{index}", type="series_index", label=str(module.get("title") or f"Series index {index}"), visible=module.get("visible", True) is not False, data={
                    "eyebrow": str(module.get("eyebrow") or ""), "title": str(module.get("title") or ""), "text": str(module.get("text") or "")
                }))
            elif mod_type == "work_spotlight":
                sections.append(SectionModel(id=f"module-{index}", type="work_spotlight", label=str(module.get("title") or f"Spotlight {index}"), visible=module.get("visible", True) is not False, data={
                    "eyebrow": str(module.get("eyebrow") or ""), "title": str(module.get("title") or ""), "text": str(module.get("text") or ""), "work_id": str(module.get("work_id") or ""), "action": [dict(module.get("action") or {})] if isinstance(module.get("action"), dict) else []
                }))
    elif page_key == "about":
        statement = dict(payload.get("statement") or {})
        sections.append(SectionModel(id="statement", type="rich_text", label="Statement", visible=True, data={
            "eyebrow": str(statement.get("eyebrow") or ""), "title": str(statement.get("title") or ""), "text": str(statement.get("text") or ""), "actions": []
        }))
        cards = [dict(item) for item in (payload.get("practice_cards") or []) if isinstance(item, dict)]
        sections.append(SectionModel(id="practice-cards", type="card_grid", label="Practice cards", visible=True, data={"items": cards, "eyebrow": "", "title": "", "intro": ""}))
        docs_visible, docs_data = _document_block_data(
            dict(payload.get("document_block") or {}) if isinstance(payload.get("document_block"), dict) else None,
            eyebrow="Documents",
            title="Press, exhibition, and profile PDFs.",
            intro="These downloadable files are part of the public build so editors, curators, and collaborators can review the supporting material without leaving the site blind.",
        )
        sections.append(SectionModel(id="documents", type="document_list", label="Documents", visible=docs_visible, data=docs_data))
        cta = dict(payload.get("cta") or {})
        sections.append(SectionModel(id="cta", type="cta_band", label="CTA", visible=True, data={
            "eyebrow": str(cta.get("eyebrow") or ""), "title": str(cta.get("title") or ""), "text": str(cta.get("text") or ""), "actions": list(cta.get("actions") or [])
        }))
    elif page_key == "contact":
        form = {
            "details_title": str(payload.get("details_title") or "Contact"),
            "form_intro": str(payload.get("form_intro") or ""),
            "form_note": str(payload.get("form_note") or ""),
            "form_button_label": str(payload.get("form_button_label") or "Draft inquiry email"),
            "inquiry_types": list(payload.get("inquiry_types") or []),
            "form_endpoint": str(payload.get("form_endpoint") or ""),
        }
        sections.append(SectionModel(id="contact-form", type="contact_form", label="Contact form", visible=True, data=form))
        docs_visible, docs_data = _document_block_data(
            dict(payload.get("document_block") or {}) if isinstance(payload.get("document_block"), dict) else None,
            eyebrow="Documents",
            title="Useful PDFs before you write.",
            intro="Press materials, exhibition details, and a short practice overview are gathered here so the essentials are easy to open before writing.",
        )
        sections.append(SectionModel(id="documents", type="document_list", label="Documents", visible=docs_visible, data=docs_data))
        sections.append(SectionModel(id="direct-contact", type="direct_contact", label="Direct contact", visible=True, data={
            "eyebrow": "Direct email", "title": str(payload.get("details_title") or "Contact"), "intro": "Use the public email directly when the draft flow is not the right fit."
        }))
    elif page_key == "portfolio":
        sections.extend(locked_system_sections("portfolio"))
    elif page_key == "series":
        rel = dict(payload.get("related_series") or {})
        sections.append(SectionModel(id="related-series", type="related_series", label="Related series", visible=True, data={
            "eyebrow": str(rel.get("eyebrow") or "Related series"), "title": str(rel.get("title") or "Other sequences in the archive."), "intro": str(rel.get("intro") or "")
        }))
        inquiry = dict(payload.get("inquiry") or {})
        sections.append(SectionModel(id="inquiry", type="inquiry_block", label="Inquiry", visible=True, data={
            "title": str(inquiry.get("title") or "Inquire"), "text": str(inquiry.get("text") or ""), "label": str(inquiry.get("label") or "Inquire"), "href": str(inquiry.get("href") or "contact.html")
        }))
        docs_visible, docs_data = _document_block_data(
            dict(payload.get("document_block") or {}) if isinstance(payload.get("document_block"), dict) else None,
            eyebrow="Documents",
            title="Selected documents",
            intro="Choose which public PDFs should accompany the current series view.",
        )
        sections.append(SectionModel(id="documents", type="document_list", label="Documents", visible=docs_visible, data=docs_data))
        sections.extend(locked_system_sections("series"))
    elif page_key == "performance":
        projects = dict(payload.get("projects") or {})
        sections.append(SectionModel(id="performance-projects", type="rich_text", label="Performance projects intro", visible=projects.get("visible", True) is not False, data={
            "eyebrow": str(projects.get("eyebrow") or "Performance projects"),
            "title": str(projects.get("title") or "Each performance stays readable as a complete sequence."),
            "text": str(projects.get("intro") or ""),
            "actions": [],
        }))
        guide = dict(payload.get("content_builder_guide") or {})
        guide_items = [dict(item) for item in (guide.get("items") or []) if isinstance(item, dict)]
        sections.append(SectionModel(id="performance-guide", type="card_grid", label="Performance guide scaffolds", visible=guide.get("visible", False) is not False, data={
            "eyebrow": str(guide.get("eyebrow") or "Guide scaffolds"),
            "title": str(guide.get("title") or "Draft performance projects"),
            "intro": str(guide.get("intro") or "Private guide cards for shaping individual performance projects before they become public."),
            "items": guide_items,
        }))
        structure = dict(payload.get("structure") or {})
        structure_cards = [dict(item) for item in (structure.get("cards") or []) if isinstance(item, dict)]
        sections.append(SectionModel(id="performance-structure", type="card_grid", label="Performance structure", visible=structure.get("visible", True) is not False, data={
            "eyebrow": str(structure.get("eyebrow") or "Structure"),
            "title": str(structure.get("title") or "Performance is a collection, not one oversized series."),
            "intro": str(structure.get("intro") or ""),
            "items": structure_cards,
        }))
        cta = dict(payload.get("cta") or {})
        sections.append(SectionModel(id="performance-cta", type="cta_band", label="Performance CTA", visible=cta.get("visible", True) is not False, data={
            "eyebrow": str(cta.get("eyebrow") or "Inquiry"),
            "title": str(cta.get("title") or ""),
            "text": str(cta.get("text") or ""),
            "actions": list(cta.get("actions") or []),
        }))
    return PageModel(schema_version=2, page_key=page_key, page_kind=page_key, meta=meta, hero=hero, sections=sections, options={})


def page_model_to_payload(model: PageModel, original_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(original_payload or {})
    payload["meta"] = model.meta.to_dict()
    hero_dict = payload.get("hero") if isinstance(payload.get("hero"), dict) else {}
    hero_dict = dict(hero_dict)
    hero_dict["eyebrow"] = model.hero.eyebrow
    hero_dict["title"] = model.hero.title
    hero_dict["lead"] = model.hero.lead
    hero_dict["feature_work_id"] = model.hero.feature_work_id
    if model.hero.actions:
        hero_dict["actions"] = [item.to_dict() for item in model.hero.actions]
        if len(model.hero.actions) >= 1:
            hero_dict["primary_action"] = model.hero.actions[0].to_dict()
        if len(model.hero.actions) >= 2:
            hero_dict["secondary_action"] = model.hero.actions[1].to_dict()
    hero_dict["notes"] = list(model.hero.notes)
    payload["hero"] = hero_dict

    section_by_type: dict[str, list[SectionModel]] = {}
    for section in model.sections:
        section_by_type.setdefault(section.type, []).append(section)

    if model.page_key == "home":
        metrics = section_by_type.get("metrics", [])
        payload["metrics"] = list((metrics[0].data.get("items") if metrics else []) or [])
        fs = section_by_type.get("featured_series", [])
        payload["featured_series"] = {
            "eyebrow": "", "title": "", "intro": "", "series_slugs": []
        }
        if fs:
            payload["featured_series"].update(fs[0].data)
            payload["featured_series"]["visible"] = fs[0].visible
        fw = section_by_type.get("featured_works", [])
        payload["selected_works"] = {
            "eyebrow": "", "title": "", "intro": "", "work_ids": []
        }
        if fw:
            payload["selected_works"].update(fw[0].data)
            payload["selected_works"]["visible"] = fw[0].visible
        modules: list[dict[str, Any]] = []
        for section in model.sections:
            if section.type == "rich_text":
                modules.append({"type": "text", "visible": section.visible, **section.data})
            elif section.type == "series_index":
                modules.append({"type": "series_index", "visible": section.visible, **section.data})
            elif section.type == "work_spotlight":
                action_list = list(section.data.get("action") or [])
                modules.append({
                    "type": "work_spotlight",
                    "visible": section.visible,
                    "eyebrow": section.data.get("eyebrow", ""),
                    "title": section.data.get("title", ""),
                    "text": section.data.get("text", ""),
                    "work_id": section.data.get("work_id", ""),
                    "action": action_list[0] if action_list else {},
                })
        payload["modules"] = modules
    elif model.page_key == "about":
        rich = section_by_type.get("rich_text", [])
        if rich:
            payload["statement"] = {k: rich[0].data.get(k, "") for k in ("eyebrow", "title", "text")}
        cards = section_by_type.get("card_grid", [])
        if cards:
            payload["practice_cards"] = list(cards[0].data.get("items") or [])
        docs = section_by_type.get("document_list", [])
        if docs:
            payload["document_block"] = {**docs[0].data, "visible": docs[0].visible}
        else:
            payload.pop("document_block", None)
        cta = section_by_type.get("cta_band", [])
        if cta:
            payload["cta"] = {**cta[0].data}
    elif model.page_key == "contact":
        form = section_by_type.get("contact_form", [])
        if form:
            data = form[0].data
            payload["details_title"] = str(data.get("details_title") or "Contact")
            payload["form_intro"] = str(data.get("form_intro") or "")
            payload["form_note"] = str(data.get("form_note") or "")
            payload["form_button_label"] = str(data.get("form_button_label") or "Draft inquiry email")
            payload["inquiry_types"] = list(data.get("inquiry_types") or [])
            payload["form_endpoint"] = str(data.get("form_endpoint") or "")
        docs = section_by_type.get("document_list", [])
        if docs:
            payload["document_block"] = {**docs[0].data, "visible": docs[0].visible}
        else:
            payload.pop("document_block", None)
    elif model.page_key == "series":
        payload["hero_eyebrow"] = model.hero.eyebrow or "Series"
        payload["hero_title"] = model.hero.title
        payload["hero_lead"] = model.hero.lead
        related = section_by_type.get("related_series", [])
        if related:
            payload["related_series"] = {**related[0].data}
        inquiry = section_by_type.get("inquiry_block", [])
        if inquiry:
            payload["inquiry"] = {**inquiry[0].data}
        docs = section_by_type.get("document_list", [])
        if docs:
            payload["document_block"] = {**docs[0].data, "visible": docs[0].visible}
        else:
            payload.pop("document_block", None)
    elif model.page_key == "performance":
        project_sections = [section for section in model.sections if section.id == "performance-projects" or section.type == "rich_text"]
        if project_sections:
            section = project_sections[0]
            payload["projects"] = {
                "eyebrow": str(section.data.get("eyebrow") or "Performance projects"),
                "title": str(section.data.get("title") or ""),
                "intro": str(section.data.get("text") or section.data.get("intro") or ""),
                "visible": bool(section.visible),
            }
        guide_sections = [section for section in model.sections if section.id == "performance-guide"]
        if guide_sections:
            section = guide_sections[0]
            payload["content_builder_guide"] = {
                "visible": bool(section.visible),
                "eyebrow": str(section.data.get("eyebrow") or "Guide scaffolds"),
                "title": str(section.data.get("title") or ""),
                "intro": str(section.data.get("intro") or ""),
                "items": list(section.data.get("items") or []),
            }
        structure_sections = [section for section in model.sections if section.id == "performance-structure"]
        if structure_sections:
            section = structure_sections[0]
            payload["structure"] = {
                "visible": bool(section.visible),
                "eyebrow": str(section.data.get("eyebrow") or "Structure"),
                "title": str(section.data.get("title") or ""),
                "intro": str(section.data.get("intro") or ""),
                "cards": list(section.data.get("items") or []),
            }
        cta_sections = [section for section in model.sections if section.id == "performance-cta" or section.type == "cta_band"]
        if cta_sections:
            section = cta_sections[0]
            payload["cta"] = {
                "visible": bool(section.visible),
                "eyebrow": str(section.data.get("eyebrow") or "Inquiry"),
                "title": str(section.data.get("title") or ""),
                "text": str(section.data.get("text") or ""),
                "actions": list(section.data.get("actions") or []),
            }
    return payload


def ensure_required_system_sections(model: PageModel) -> PageModel:
    locked_ids = {item.id for item in model.sections}
    for section in locked_system_sections(model.page_key):
        if section.id not in locked_ids:
            model.sections.append(section)
    return model
