from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

PageKey = Literal["home", "about", "contact", "portfolio", "series", "performance"]
BlockType = Literal[
    "rich_text",
    "bullet_list",
    "card_grid",
    "cta_band",
    "document_list",
    "featured_series",
    "featured_works",
    "work_spotlight",
    "series_index",
    "metrics",
    "contact_form",
    "direct_contact",
    "related_series",
    "inquiry_block",
    "system_portfolio_grid",
    "system_series_runtime",
]
ValidationSeverity = Literal["error", "warning", "info"]
ValidationScope = Literal["site", "artist", "navigation", "resource", "page", "series", "work", "asset", "publish"]


@dataclass(slots=True)
class ActionLink:
    label: str = ""
    href: str = ""
    style: str = "primary"

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"label": self.label, "href": self.href}
        if self.style:
            data["style"] = self.style
        return data

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ActionLink":
        return cls(
            label=str(payload.get("label") or "").strip(),
            href=str(payload.get("href") or "").strip(),
            style=str(payload.get("style") or "primary").strip() or "primary",
        )


@dataclass(slots=True)
class MetaModel:
    title: str = ""
    description: str = ""
    og_description: str = ""
    og_image: str = ""
    og_image_alt: str = ""
    canonical_path: str = ""
    twitter_image_alt: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "title": self.title,
            "description": self.description,
            "og_description": self.og_description,
        }
        optional_fields = {
            "og_image": self.og_image,
            "og_image_alt": self.og_image_alt,
            "canonical_path": self.canonical_path,
            "twitter_image_alt": self.twitter_image_alt,
        }
        for key, value in optional_fields.items():
            value = str(value or '').strip()
            if value:
                data[key] = value
        return data

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MetaModel":
        return cls(
            title=str(payload.get("title") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            og_description=str(payload.get("og_description") or "").strip(),
            og_image=str(payload.get("og_image") or "").strip(),
            og_image_alt=str(payload.get("og_image_alt") or "").strip(),
            canonical_path=str(payload.get("canonical_path") or "").strip(),
            twitter_image_alt=str(payload.get("twitter_image_alt") or "").strip(),
        )


@dataclass(slots=True)
class HeroModel:
    eyebrow: str = ""
    title: str = ""
    lead: str = ""
    feature_work_id: str = ""
    actions: list[ActionLink] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "eyebrow": self.eyebrow,
            "title": self.title,
            "lead": self.lead,
            "feature_work_id": self.feature_work_id,
            "actions": [item.to_dict() for item in self.actions],
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "HeroModel":
        actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
        return cls(
            eyebrow=str(payload.get("eyebrow") or "").strip(),
            title=str(payload.get("title") or "").strip(),
            lead=str(payload.get("lead") or "").strip(),
            feature_work_id=str(payload.get("feature_work_id") or "").strip(),
            actions=[ActionLink.from_dict(item) for item in actions if isinstance(item, dict)],
            notes=[str(item).strip() for item in (payload.get("notes") or []) if str(item).strip()],
        )


@dataclass(slots=True)
class SectionModel:
    id: str
    type: BlockType
    label: str
    visible: bool = True
    locked: bool = False
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "visible": self.visible,
            "locked": self.locked,
            **self.data,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SectionModel":
        data = dict(payload)
        ident = str(data.pop("id", "")).strip()
        block_type = str(data.pop("type", "rich_text")).strip() or "rich_text"
        label = str(data.pop("label", ident or block_type.replace("_", " ").title())).strip()
        visible = bool(data.pop("visible", True))
        locked = bool(data.pop("locked", False))
        return cls(id=ident, type=block_type, label=label, visible=visible, locked=locked, data=data)


@dataclass(slots=True)
class PageModel:
    schema_version: int
    page_key: PageKey
    page_kind: PageKey
    meta: MetaModel
    hero: HeroModel
    sections: list[SectionModel] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "page_key": self.page_key,
            "page_kind": self.page_kind,
            "meta": self.meta.to_dict(),
            "hero": self.hero.to_dict(),
            "sections": [item.to_dict() for item in self.sections],
            "options": dict(self.options),
        }

    @classmethod
    def from_dict(cls, page_key: PageKey, payload: dict[str, Any]) -> "PageModel":
        sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
        return cls(
            schema_version=int(payload.get("schema_version") or 2),
            page_key=page_key,
            page_kind=page_key,
            meta=MetaModel.from_dict(payload.get("meta") if isinstance(payload.get("meta"), dict) else {}),
            hero=HeroModel.from_dict(payload.get("hero") if isinstance(payload.get("hero"), dict) else {}),
            sections=[SectionModel.from_dict(item) for item in sections if isinstance(item, dict)],
            options=dict(payload.get("options") or {}),
        )


@dataclass(slots=True)
class NavigationItemModel:
    id: str
    label: str
    href: str
    page: str
    visible: bool = True
    order: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "href": self.href,
            "page": self.page,
            "visible": self.visible,
            "order": self.order,
        }


@dataclass(slots=True)
class ResourceDocumentModel:
    id: str
    title: str
    description: str
    file: str
    kind: str
    visible: bool = True
    featured: bool = False
    public: bool = True
    order: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "file": self.file,
            "kind": self.kind,
            "visible": self.visible,
            "featured": self.featured,
            "public": self.public,
            "order": self.order,
        }


@dataclass(slots=True)
class ValidationIssue:
    code: str
    severity: ValidationSeverity
    scope: ValidationScope
    target_key: str
    field_path: str
    message: str
    suggestion: str = ""


@dataclass(slots=True)
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)
    generated_at: str = ""

    def error_count(self) -> int:
        return sum(1 for item in self.issues if item.severity == "error")

    def warning_count(self) -> int:
        return sum(1 for item in self.issues if item.severity == "warning")

    def issues_for_scope(self, scope: ValidationScope) -> list[ValidationIssue]:
        return [item for item in self.issues if item.scope == scope]

    def can_publish(self) -> bool:
        return self.error_count() == 0


@dataclass(slots=True)
class PublishState:
    last_build_at: str = ""
    last_publish_at: str = ""
    content_hash: str = ""
    has_unpublished_changes: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_build_at": self.last_build_at,
            "last_publish_at": self.last_publish_at,
            "content_hash": self.content_hash,
            "has_unpublished_changes": self.has_unpublished_changes,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PublishState":
        return cls(
            last_build_at=str(payload.get("last_build_at") or ""),
            last_publish_at=str(payload.get("last_publish_at") or ""),
            content_hash=str(payload.get("content_hash") or ""),
            has_unpublished_changes=bool(payload.get("has_unpublished_changes", False)),
        )
