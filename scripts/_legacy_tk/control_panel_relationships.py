from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Any

try:
    from helpers_content import (
        available_download_ids,
        available_series_slugs,
        available_work_ids,
        load_home_relationships,
        load_page_payload,
        load_resources_payload,
        load_series_entries,
        load_series_payload,
        load_work_entries,
        load_work_payload,
                move_work_to_series,
        save_home_relationships,
        save_series_payload,
        save_work_payload,
        series_position_for_work,
        series_relationship_refs,
                set_series_cover_work,
        transaction,
        work_lookup_by_id,
        work_relationship_refs,
    )
except ImportError:  # pragma: no cover
    from scripts.helpers_content import (  # type: ignore
        available_download_ids,
        available_series_slugs,
        available_work_ids,
        load_home_relationships,
        load_page_payload,
        load_resources_payload,
        load_series_entries,
        load_series_payload,
        load_work_entries,
        load_work_payload,
                move_work_to_series,
        save_home_relationships,
        save_series_payload,
        save_work_payload,
        series_position_for_work,
        series_relationship_refs,
                set_series_cover_work,
        transaction,
        work_lookup_by_id,
        work_relationship_refs,
    )


class RelationshipManagerTab(ttk.Frame):
    def __init__(self, master: tk.Misc, app: "Any") -> None:
        super().__init__(master)
        self.app = app
        self.current_series_slug: str = ""
        self.current_work_id: str = ""
        self._series_slugs: list[str] = []
        self._work_ids: list[str] = []
        self._featured_series: list[str] = []
        self._featured_works: list[str] = []
        self._series_sequence_original: list[str] = []
        self.series_search_var = tk.StringVar()
        self.work_search_var = tk.StringVar()
        self.series_visibility_var = tk.StringVar(value="public")
        self.series_order_var = tk.StringVar(value="0")
        self.series_cover_var = tk.StringVar()
        self.series_add_work_var = tk.StringVar()
        self.series_move_target_var = tk.StringVar()
        self.series_related_pick_var = tk.StringVar()
        self.series_download_pick_var = tk.StringVar()
        self.feature_series_pick_var = tk.StringVar()
        self.feature_work_pick_var = tk.StringVar()
        self.work_target_series_var = tk.StringVar()
        self.work_position_var = tk.StringVar(value="End")
        self.build_ui()
        self.refresh()

    def build_ui(self) -> None:
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)
        self.home_tab = ttk.Frame(notebook, padding=10)
        self.series_tab = ttk.Frame(notebook, padding=10)
        self.work_tab = ttk.Frame(notebook, padding=10)
        notebook.add(self.home_tab, text="Homepage features")
        notebook.add(self.series_tab, text="Series relationships")
        notebook.add(self.work_tab, text="Work placement")
        notebook.bind("<<NotebookTabChanged>>", lambda _e: self.refresh_current_view())
        self.sub_notebook = notebook

        self._build_home_tab()
        self._build_series_tab()
        self._build_work_tab()

    def refresh(self) -> None:
        self._refresh_home_lists()
        self._refresh_series_list()
        self._refresh_work_list()
        self.refresh_current_view()

    def refresh_current_view(self) -> None:
        if self.sub_notebook.select() == str(self.home_tab):
            self._refresh_home_lists()
        elif self.sub_notebook.select() == str(self.series_tab):
            self._refresh_series_editor()
        elif self.sub_notebook.select() == str(self.work_tab):
            self._refresh_work_inspector()

    # ---------------- Home features ----------------
    def _build_home_tab(self) -> None:
        wrap = ttk.Panedwindow(self.home_tab, orient="horizontal")
        wrap.pack(fill="both", expand=True)

        left = ttk.Labelframe(wrap, text="Featured series order", padding=10)
        wrap.add(left, weight=1)
        right = ttk.Labelframe(wrap, text="Featured works order", padding=10)
        wrap.add(right, weight=1)

        self.home_feature_series_list = tk.Listbox(left, exportselection=False, height=16)
        self.home_feature_series_list.pack(fill="both", expand=True)
        controls = ttk.Frame(left)
        controls.pack(fill="x", pady=(8, 0))
        ttk.Combobox(controls, textvariable=self.feature_series_pick_var, state="readonly").pack(side="left", fill="x", expand=True)
        self.feature_series_combo = controls.winfo_children()[-1]
        ttk.Button(controls, text="Add", command=self.add_featured_series).pack(side="left", padx=(6, 0))
        move = ttk.Frame(left)
        move.pack(fill="x", pady=(8, 0))
        ttk.Button(move, text="Remove", command=self.remove_featured_series).pack(side="left")
        ttk.Button(move, text="▲", command=lambda: self.move_featured_series(-1), width=4).pack(side="left", padx=(8, 0))
        ttk.Button(move, text="▼", command=lambda: self.move_featured_series(1), width=4).pack(side="left", padx=(6, 0))

        self.home_feature_work_list = tk.Listbox(right, exportselection=False, height=16)
        self.home_feature_work_list.pack(fill="both", expand=True)
        controls = ttk.Frame(right)
        controls.pack(fill="x", pady=(8, 0))
        ttk.Combobox(controls, textvariable=self.feature_work_pick_var, state="readonly").pack(side="left", fill="x", expand=True)
        self.feature_work_combo = controls.winfo_children()[-1]
        ttk.Button(controls, text="Add", command=self.add_featured_work).pack(side="left", padx=(6, 0))
        move = ttk.Frame(right)
        move.pack(fill="x", pady=(8, 0))
        ttk.Button(move, text="Remove", command=self.remove_featured_work).pack(side="left")
        ttk.Button(move, text="▲", command=lambda: self.move_featured_work(-1), width=4).pack(side="left", padx=(8, 0))
        ttk.Button(move, text="▼", command=lambda: self.move_featured_work(1), width=4).pack(side="left", padx=(6, 0))

        foot = ttk.Frame(self.home_tab)
        foot.pack(fill="x", pady=(10, 0))
        ttk.Label(foot, text="This manager edits home featured series/work ordering without opening raw page content.", style="Sub.TLabel").pack(side="left")
        ttk.Button(foot, text="Save homepage relationships", style="Accent.TButton", command=self.save_home_featured).pack(side="right")

    def _refresh_home_lists(self) -> None:
        home = load_home_relationships()
        self._featured_series = list(home.get("featured_series") or [])
        self._featured_works = list(home.get("featured_works") or [])
        self.home_feature_series_list.delete(0, "end")
        for slug in self._featured_series:
            self.home_feature_series_list.insert("end", slug)
        self.home_feature_work_list.delete(0, "end")
        for work_id in self._featured_works:
            self.home_feature_work_list.insert("end", work_id)
        series_choices = [slug for slug in available_series_slugs() if slug not in self._featured_series]
        work_choices = [work_id for work_id in available_work_ids() if work_id not in self._featured_works]
        self.feature_series_combo.configure(values=series_choices)
        self.feature_work_combo.configure(values=work_choices)
        if series_choices and self.feature_series_pick_var.get() not in series_choices:
            self.feature_series_pick_var.set(series_choices[0])
        if work_choices and self.feature_work_pick_var.get() not in work_choices:
            self.feature_work_pick_var.set(work_choices[0])

    def add_featured_series(self) -> None:
        slug = self.feature_series_pick_var.get().strip()
        if slug and slug not in self._featured_series:
            self._featured_series.append(slug)
            self._refresh_home_lists()

    def remove_featured_series(self) -> None:
        sel = self.home_feature_series_list.curselection()
        if not sel:
            return
        self._featured_series.pop(sel[0])
        self._refresh_home_lists()

    def move_featured_series(self, direction: int) -> None:
        sel = self.home_feature_series_list.curselection()
        if not sel:
            return
        idx = sel[0]
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self._featured_series):
            return
        self._featured_series[idx], self._featured_series[new_idx] = self._featured_series[new_idx], self._featured_series[idx]
        self._refresh_home_lists()
        self.home_feature_series_list.selection_set(new_idx)

    def add_featured_work(self) -> None:
        work_id = self.feature_work_pick_var.get().strip()
        if work_id and work_id not in self._featured_works:
            self._featured_works.append(work_id)
            self._refresh_home_lists()

    def remove_featured_work(self) -> None:
        sel = self.home_feature_work_list.curselection()
        if not sel:
            return
        self._featured_works.pop(sel[0])
        self._refresh_home_lists()

    def move_featured_work(self, direction: int) -> None:
        sel = self.home_feature_work_list.curselection()
        if not sel:
            return
        idx = sel[0]
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self._featured_works):
            return
        self._featured_works[idx], self._featured_works[new_idx] = self._featured_works[new_idx], self._featured_works[idx]
        self._refresh_home_lists()
        self.home_feature_work_list.selection_set(new_idx)

    def save_home_featured(self) -> None:
        try:
            with transaction("gui-home-relationships"):
                save_home_relationships(featured_series=self._featured_series, featured_works=self._featured_works)
            self.app.log("Saved homepage featured relationships")
            self.app.refresh_publish_state()
            if hasattr(self.app, "content_builder_widget"):
                self.app.content_builder_widget.refresh()
            if hasattr(self.app, "validation_widget"):
                self.app.validation_widget.refresh(rerun=True)
            if messagebox.askyesno("Build now", "Homepage featured relationships were updated.\n\nBuild now so the public pages reflect the new order?"):
                self.app.build_site_and_refresh()
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc), parent=self)

    # ---------------- Series relationships ----------------
    def _build_series_tab(self) -> None:
        outer = ttk.Panedwindow(self.series_tab, orient="horizontal")
        outer.pack(fill="both", expand=True)

        left = ttk.Frame(outer)
        outer.add(left, weight=1)
        ttk.Label(left, text="Series search").pack(anchor="w")
        ttk.Entry(left, textvariable=self.series_search_var).pack(fill="x", pady=(2, 6))
        self.series_search_var.trace_add("write", lambda *_: self._refresh_series_list())
        self.relationship_series_list = tk.Listbox(left, exportselection=False, height=24)
        self.relationship_series_list.pack(fill="both", expand=True)
        self.relationship_series_list.bind("<<ListboxSelect>>", lambda _e: self.load_selected_series())
        ttk.Button(left, text="Refresh series", command=self._refresh_series_list).pack(fill="x", pady=(8, 0))

        center = ttk.Labelframe(outer, text="Series editor", padding=10)
        outer.add(center, weight=2)
        head = ttk.Frame(center)
        head.pack(fill="x")
        self.series_title_label = ttk.Label(head, text="Select a series", style="Title.TLabel")
        self.series_title_label.pack(side="left")
        self.series_meta_label = ttk.Label(head, text="", style="Sub.TLabel")
        self.series_meta_label.pack(side="left", padx=(12, 0))

        form = ttk.Frame(center)
        form.pack(fill="x", pady=(10, 0))
        for idx in range(4):
            form.columnconfigure(idx, weight=1 if idx % 2 else 0)
        ttk.Label(form, text="Visibility").grid(row=0, column=0, sticky="w")
        ttk.Combobox(form, textvariable=self.series_visibility_var, values=["public", "private"], state="readonly", width=12).grid(row=0, column=1, sticky="ew", padx=(0, 12))
        ttk.Label(form, text="Order").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(form, from_=0, to=999, textvariable=self.series_order_var, width=8).grid(row=0, column=3, sticky="w")
        ttk.Label(form, text="Cover work").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.series_cover_combo = ttk.Combobox(form, textvariable=self.series_cover_var, state="readonly")
        self.series_cover_combo.grid(row=1, column=1, columnspan=3, sticky="ew", pady=(8, 0))

        seq_wrap = ttk.Frame(center)
        seq_wrap.pack(fill="both", expand=True, pady=(12, 0))
        current = ttk.Labelframe(seq_wrap, text="Sequence order", padding=8)
        current.pack(side="left", fill="both", expand=True)
        self.series_sequence_list = tk.Listbox(current, exportselection=False, height=15)
        self.series_sequence_list.pack(fill="both", expand=True)
        seq_btns = ttk.Frame(current)
        seq_btns.pack(fill="x", pady=(8, 0))
        ttk.Button(seq_btns, text="▲", command=lambda: self.move_sequence_work(-1), width=4).pack(side="left")
        ttk.Button(seq_btns, text="▼", command=lambda: self.move_sequence_work(1), width=4).pack(side="left", padx=(6, 0))
        ttk.Button(seq_btns, text="Use as cover", command=self.use_sequence_selection_as_cover).pack(side="left", padx=(10, 0))

        tools = ttk.Labelframe(seq_wrap, text="Placement tools", padding=8)
        tools.pack(side="left", fill="both", expand=True, padx=(10, 0))
        ttk.Label(tools, text="Add or move work into this series").pack(anchor="w")
        self.series_add_work_combo = ttk.Combobox(tools, textvariable=self.series_add_work_var, state="readonly")
        self.series_add_work_combo.pack(fill="x", pady=(4, 0))
        ttk.Button(tools, text="Add / move into this series", command=self.add_work_to_current_series).pack(fill="x", pady=(6, 0))
        ttk.Separator(tools).pack(fill="x", pady=10)
        ttk.Label(tools, text="Send selected sequence work to").pack(anchor="w")
        self.series_move_target_combo = ttk.Combobox(tools, textvariable=self.series_move_target_var, state="readonly")
        self.series_move_target_combo.pack(fill="x", pady=(4, 0))
        ttk.Button(tools, text="Move selected work now", command=self.send_selected_sequence_work).pack(fill="x", pady=(6, 0))
        ttk.Label(tools, text="Moving a work here or away updates both series membership and the work file.", style="Sub.TLabel", wraplength=260, justify="left").pack(anchor="w", pady=(10, 0))

        right = ttk.Labelframe(outer, text="Related links and docs", padding=10)
        outer.add(right, weight=1)
        related_box = ttk.Labelframe(right, text="Related series", padding=8)
        related_box.pack(fill="both", expand=True)
        self.series_related_list = tk.Listbox(related_box, exportselection=False, height=7)
        self.series_related_list.pack(fill="both", expand=True)
        row = ttk.Frame(related_box)
        row.pack(fill="x", pady=(8, 0))
        self.series_related_combo = ttk.Combobox(row, textvariable=self.series_related_pick_var, state="readonly")
        self.series_related_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Add", command=self.add_related_series).pack(side="left", padx=(6, 0))
        row = ttk.Frame(related_box)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Remove", command=self.remove_related_series).pack(side="left")
        ttk.Button(row, text="▲", command=lambda: self.move_related_series(-1), width=4).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="▼", command=lambda: self.move_related_series(1), width=4).pack(side="left", padx=(6, 0))

        downloads_box = ttk.Labelframe(right, text="Series documents", padding=8)
        downloads_box.pack(fill="both", expand=True, pady=(10, 0))
        self.series_download_list = tk.Listbox(downloads_box, exportselection=False, height=7)
        self.series_download_list.pack(fill="both", expand=True)
        row = ttk.Frame(downloads_box)
        row.pack(fill="x", pady=(8, 0))
        self.series_download_combo = ttk.Combobox(row, textvariable=self.series_download_pick_var, state="readonly")
        self.series_download_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Add", command=self.add_series_download).pack(side="left", padx=(6, 0))
        row = ttk.Frame(downloads_box)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Remove", command=self.remove_series_download).pack(side="left")
        ttk.Button(row, text="▲", command=lambda: self.move_series_download(-1), width=4).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="▼", command=lambda: self.move_series_download(1), width=4).pack(side="left", padx=(6, 0))

        self.series_summary_box = tk.Text(right, height=10, wrap="word", bg="white")
        self.series_summary_box.pack(fill="both", expand=True, pady=(10, 0))
        foot = ttk.Frame(self.series_tab)
        foot.pack(fill="x", pady=(10, 0))
        ttk.Button(foot, text="Save series relationships", style="Accent.TButton", command=self.save_current_series_relationships).pack(side="right")

    def _refresh_series_list(self) -> None:
        entries = sorted(load_series_entries(), key=lambda item: (int(item.get("order", 9999) or 9999), str(item.get("slug") or "")))
        query = self.series_search_var.get().strip().lower()
        self._series_slugs = []
        self.relationship_series_list.delete(0, "end")
        for entry in entries:
            slug = str(entry.get("slug") or "").strip()
            title = str(entry.get("title") or "").strip()
            haystack = f"{slug} {title} {entry.get('mood') or ''}".lower()
            if query and query not in haystack:
                continue
            self._series_slugs.append(slug)
            self.relationship_series_list.insert("end", f"{slug} — {title}")
        if self.current_series_slug in self._series_slugs:
            idx = self._series_slugs.index(self.current_series_slug)
            self.relationship_series_list.selection_clear(0, "end")
            self.relationship_series_list.selection_set(idx)
            self.relationship_series_list.see(idx)

    def load_selected_series(self) -> None:
        sel = self.relationship_series_list.curselection()
        if not sel:
            return
        self.current_series_slug = self._series_slugs[sel[0]]
        self._refresh_series_editor()

    def _refresh_series_editor(self) -> None:
        if not self.current_series_slug:
            return
        payload = load_series_payload(self.current_series_slug)
        title = str(payload.get("title") or self.current_series_slug)
        self.series_title_label.configure(text=title)
        self.series_meta_label.configure(text=f"{self.current_series_slug} · {len(payload.get('work_ids') or [])} works")
        self.series_visibility_var.set(str(payload.get("visibility") or "public"))
        self.series_order_var.set(str(payload.get("order") or 0))
        work_ids = [str(item).strip() for item in (payload.get("work_ids") or []) if str(item).strip()]
        self._series_sequence_original = list(work_ids)
        self.series_sequence_list.delete(0, "end")
        for work_id in work_ids:
            self.series_sequence_list.insert("end", work_id)
        self.series_cover_combo.configure(values=work_ids)
        self.series_cover_var.set(str(payload.get("cover_work_id") or (work_ids[0] if work_ids else "")))

        related = [str(item).strip() for item in (payload.get("related_series_slugs") or []) if str(item).strip()]
        self.series_related_list.delete(0, "end")
        for slug in related:
            self.series_related_list.insert("end", slug)
        rel_choices = [slug for slug in available_series_slugs() if slug not in related and slug != self.current_series_slug]
        self.series_related_combo.configure(values=rel_choices)
        if rel_choices and self.series_related_pick_var.get() not in rel_choices:
            self.series_related_pick_var.set(rel_choices[0])

        download_ids = [str(item).strip() for item in (payload.get("download_ids") or []) if str(item).strip()]
        self.series_download_list.delete(0, "end")
        for doc_id in download_ids:
            self.series_download_list.insert("end", doc_id)
        doc_choices = [doc_id for doc_id in available_download_ids() if doc_id not in download_ids]
        self.series_download_combo.configure(values=doc_choices)
        if doc_choices and self.series_download_pick_var.get() not in doc_choices:
            self.series_download_pick_var.set(doc_choices[0])

        lookup = work_lookup_by_id()
        work_choices = []
        for work_id in available_work_ids():
            owner = str((lookup.get(work_id) or {}).get("series") or "").strip()
            work_choices.append(f"{work_id} — {owner or 'unassigned'}")
        self._series_add_work_map = {label.split(" — ", 1)[0]: label for label in work_choices}
        self.series_add_work_combo.configure(values=work_choices)
        if work_choices and self.series_add_work_var.get() not in work_choices:
            self.series_add_work_var.set(work_choices[0])
        move_choices = [slug for slug in available_series_slugs() if slug != self.current_series_slug]
        self.series_move_target_combo.configure(values=move_choices)
        if move_choices and self.series_move_target_var.get() not in move_choices:
            self.series_move_target_var.set(move_choices[0])
        self._refresh_series_summary()

    def _refresh_series_summary(self) -> None:
        if not self.current_series_slug:
            return
        refs = series_relationship_refs(self.current_series_slug)
        payload = load_series_payload(self.current_series_slug)
        work_ids = [str(item).strip() for item in self.series_sequence_list.get(0, "end")]
        lines = [
            f"Series: {self.current_series_slug}",
            f"Visibility: {self.series_visibility_var.get().strip() or 'public'}",
            f"Order: {self.series_order_var.get().strip() or '0'}",
            f"Cover work: {self.series_cover_var.get().strip() or '—'}",
            f"Works in sequence: {len(work_ids)}",
            f"Homepage featured: {'Yes' if refs.get('home_featured') else 'No'}",
            f"Related series: {', '.join(self.series_related_list.get(0, 'end')) or '—'}",
            f"Documents: {', '.join(self.series_download_list.get(0, 'end')) or '—'}",
            "",
        ]
        current_cover = self.series_cover_var.get().strip()
        for idx, work_id in enumerate(work_ids, start=1):
            marker = " ★cover" if work_id == current_cover else ""
            lines.append(f"{idx:02d}. {work_id}{marker}")
        self.series_summary_box.delete("1.0", "end")
        self.series_summary_box.insert("end", "\n".join(lines))

    def move_sequence_work(self, direction: int) -> None:
        sel = self.series_sequence_list.curselection()
        if not sel:
            return
        idx = sel[0]
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= self.series_sequence_list.size():
            return
        value = self.series_sequence_list.get(idx)
        self.series_sequence_list.delete(idx)
        self.series_sequence_list.insert(new_idx, value)
        self.series_sequence_list.selection_set(new_idx)
        self._refresh_series_summary()

    def use_sequence_selection_as_cover(self) -> None:
        sel = self.series_sequence_list.curselection()
        if not sel:
            return
        self.series_cover_var.set(self.series_sequence_list.get(sel[0]))
        self._refresh_series_summary()

    def add_work_to_current_series(self) -> None:
        if not self.current_series_slug:
            return
        label = self.series_add_work_var.get().strip()
        work_id = label.split(" — ", 1)[0].strip() if label else ""
        if not work_id:
            return
        existing = list(self.series_sequence_list.get(0, "end"))
        if work_id in existing:
            messagebox.showinfo("Already present", f"{work_id} is already in this series.", parent=self)
            return
        existing.append(work_id)
        self.series_sequence_list.delete(0, "end")
        for item in existing:
            self.series_sequence_list.insert("end", item)
        self.series_cover_combo.configure(values=existing)
        if not self.series_cover_var.get().strip():
            self.series_cover_var.set(work_id)
        self._refresh_series_summary()

    def send_selected_sequence_work(self) -> None:
        if not self.current_series_slug:
            return
        sel = self.series_sequence_list.curselection()
        if not sel:
            return
        work_id = self.series_sequence_list.get(sel[0])
        target = self.series_move_target_var.get().strip()
        if not target or target == self.current_series_slug:
            return
        if not messagebox.askyesno("Move work", f"Move '{work_id}' from '{self.current_series_slug}' to '{target}' now?", parent=self):
            return
        try:
            with transaction(f"gui-send-sequence-work:{work_id}:{target}"):
                move_work_to_series(work_id, target)
            self.app.log(f"Moved {work_id} to {target}")
            self.app.refresh_publish_state()
            self._refresh_series_editor()
            self._refresh_work_list()
            if hasattr(self.app, "validation_widget"):
                self.app.validation_widget.refresh(rerun=True)
        except Exception as exc:
            messagebox.showerror("Move failed", str(exc), parent=self)

    def add_related_series(self) -> None:
        slug = self.series_related_pick_var.get().strip()
        if not slug:
            return
        current = list(self.series_related_list.get(0, "end"))
        if slug not in current:
            self.series_related_list.insert("end", slug)
            self._update_related_choices()
            self._refresh_series_summary()

    def remove_related_series(self) -> None:
        sel = self.series_related_list.curselection()
        if not sel:
            return
        self.series_related_list.delete(sel[0])
        self._update_related_choices()
        self._refresh_series_summary()

    def move_related_series(self, direction: int) -> None:
        sel = self.series_related_list.curselection()
        if not sel:
            return
        items = list(self.series_related_list.get(0, "end"))
        idx = sel[0]
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(items):
            return
        items[idx], items[new_idx] = items[new_idx], items[idx]
        self.series_related_list.delete(0, "end")
        for item in items:
            self.series_related_list.insert("end", item)
        self.series_related_list.selection_set(new_idx)

    def add_series_download(self) -> None:
        doc_id = self.series_download_pick_var.get().strip()
        if not doc_id:
            return
        current = list(self.series_download_list.get(0, "end"))
        if doc_id not in current:
            self.series_download_list.insert("end", doc_id)
            self._update_download_choices()
            self._refresh_series_summary()

    def remove_series_download(self) -> None:
        sel = self.series_download_list.curselection()
        if not sel:
            return
        self.series_download_list.delete(sel[0])
        self._update_download_choices()
        self._refresh_series_summary()

    def move_series_download(self, direction: int) -> None:
        sel = self.series_download_list.curselection()
        if not sel:
            return
        items = list(self.series_download_list.get(0, "end"))
        idx = sel[0]
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(items):
            return
        items[idx], items[new_idx] = items[new_idx], items[idx]
        self.series_download_list.delete(0, "end")
        for item in items:
            self.series_download_list.insert("end", item)
        self.series_download_list.selection_set(new_idx)

    def _update_related_choices(self) -> None:
        current = list(self.series_related_list.get(0, "end")) if hasattr(self, "series_related_list") else []
        rel_choices = [slug for slug in available_series_slugs() if slug not in current and slug != self.current_series_slug]
        self.series_related_combo.configure(values=rel_choices)
        if rel_choices:
            if self.series_related_pick_var.get() not in rel_choices:
                self.series_related_pick_var.set(rel_choices[0])
        else:
            self.series_related_pick_var.set("")

    def _update_download_choices(self) -> None:
        current = list(self.series_download_list.get(0, "end")) if hasattr(self, "series_download_list") else []
        doc_choices = [doc_id for doc_id in available_download_ids() if doc_id not in current]
        self.series_download_combo.configure(values=doc_choices)
        if doc_choices:
            if self.series_download_pick_var.get() not in doc_choices:
                self.series_download_pick_var.set(doc_choices[0])
        else:
            self.series_download_pick_var.set("")

    def save_current_series_relationships(self) -> None:
        if not self.current_series_slug:
            return
        work_ids = [str(item).strip() for item in self.series_sequence_list.get(0, "end") if str(item).strip()]
        cover_id = self.series_cover_var.get().strip()
        if cover_id and cover_id not in work_ids:
            messagebox.showerror("Invalid cover", "Cover work must be present in the sequence list.", parent=self)
            return
        try:
            order = int(self.series_order_var.get().strip() or "0")
        except ValueError:
            messagebox.showerror("Invalid order", "Order must be a number.", parent=self)
            return
        payload = load_series_payload(self.current_series_slug)
        related_series = [str(item).strip() for item in self.series_related_list.get(0, "end") if str(item).strip()]
        download_ids = [str(item).strip() for item in self.series_download_list.get(0, "end") if str(item).strip()]
        try:
            with transaction(f"gui-series-relationships:{self.current_series_slug}"):
                for other in load_series_entries():
                    other_slug = str(other.get("slug") or "").strip()
                    if not other_slug or other_slug == self.current_series_slug:
                        continue
                    other_ids = [str(item).strip() for item in (other.get("work_ids") or []) if str(item).strip()]
                    filtered = [work_id for work_id in other_ids if work_id not in work_ids]
                    if filtered != other_ids:
                        other["work_ids"] = filtered
                        if str(other.get("cover_work_id") or "").strip() not in filtered:
                            other["cover_work_id"] = filtered[0] if filtered else None
                        save_series_payload(other_slug, other)
                payload["visibility"] = self.series_visibility_var.get().strip() or "public"
                payload["order"] = order
                payload["work_ids"] = work_ids
                payload["cover_work_id"] = cover_id or (work_ids[0] if work_ids else None)
                payload["related_series_slugs"] = related_series
                payload["download_ids"] = download_ids
                save_series_payload(self.current_series_slug, payload)
                for work_id in work_ids:
                    work_payload = load_work_payload(work_id)
                    work_payload["series"] = self.current_series_slug
                    save_work_payload(work_id, work_payload)
            self.app.log(f"Saved series relationships: {self.current_series_slug}")
            self.app.refresh_publish_state()
            self._refresh_series_list()
            self._refresh_series_editor()
            self._refresh_work_list()
            if hasattr(self.app, "validation_widget"):
                self.app.validation_widget.refresh(rerun=True)
            if hasattr(self.app, "refresh_work_list"):
                self.app.refresh_work_list()
            if hasattr(self.app, "refresh_series_list"):
                self.app.refresh_series_list()
            if messagebox.askyesno("Build now", f"Series relationships for '{self.current_series_slug}' were updated.\n\nBuild now?"):
                self.app.build_site_and_refresh()
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc), parent=self)

    # ---------------- Work placement ----------------
    def _build_work_tab(self) -> None:
        outer = ttk.Panedwindow(self.work_tab, orient="horizontal")
        outer.pack(fill="both", expand=True)
        left = ttk.Frame(outer)
        outer.add(left, weight=1)
        ttk.Label(left, text="Work search").pack(anchor="w")
        ttk.Entry(left, textvariable=self.work_search_var).pack(fill="x", pady=(2, 6))
        self.work_search_var.trace_add("write", lambda *_: self._refresh_work_list())
        self.relationship_work_list = tk.Listbox(left, exportselection=False, height=24)
        self.relationship_work_list.pack(fill="both", expand=True)
        self.relationship_work_list.bind("<<ListboxSelect>>", lambda _e: self.load_selected_work())
        ttk.Button(left, text="Refresh works", command=self._refresh_work_list).pack(fill="x", pady=(8, 0))

        right = ttk.Labelframe(outer, text="Work relationship inspector", padding=10)
        outer.add(right, weight=2)
        self.work_heading_label = ttk.Label(right, text="Select a work", style="Title.TLabel")
        self.work_heading_label.pack(anchor="w")
        self.work_relationship_label = ttk.Label(right, text="", style="Sub.TLabel", justify="left")
        self.work_relationship_label.pack(anchor="w", pady=(4, 10))
        controls = ttk.Frame(right)
        controls.pack(fill="x")
        ttk.Label(controls, text="Move to series").grid(row=0, column=0, sticky="w")
        self.work_target_series_combo = ttk.Combobox(controls, textvariable=self.work_target_series_var, state="readonly")
        self.work_target_series_combo.grid(row=0, column=1, sticky="ew", padx=(8, 12))
        ttk.Label(controls, text="Position").grid(row=0, column=2, sticky="w")
        ttk.Combobox(controls, textvariable=self.work_position_var, values=["Start", "End"], state="readonly", width=10).grid(row=0, column=3, sticky="w")
        controls.columnconfigure(1, weight=1)
        btns = ttk.Frame(right)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Move now", command=self.move_selected_work_now, style="Accent.TButton").pack(side="left")
        ttk.Button(btns, text="Use as series cover", command=self.set_selected_work_as_cover).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="Toggle homepage feature", command=self.toggle_selected_work_featured).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="Open in Works tab", command=self.open_selected_work_in_main_tab).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="Open series in Series tab", command=self.open_selected_work_series_in_main_tab).pack(side="left", padx=(8, 0))
        self.work_detail_box = tk.Text(right, height=18, wrap="word", bg="white")
        self.work_detail_box.pack(fill="both", expand=True, pady=(10, 0))

    def _refresh_work_list(self) -> None:
        entries = sorted(load_work_entries(), key=lambda item: str(item.get("id") or ""))
        query = self.work_search_var.get().strip().lower()
        self._work_ids = []
        self.relationship_work_list.delete(0, "end")
        for entry in entries:
            work_id = str(entry.get("id") or "").strip()
            title = str(entry.get("title") or "").strip()
            series_slug = str(entry.get("series") or "").strip()
            haystack = f"{work_id} {title} {series_slug} {entry.get('location') or ''}".lower()
            if query and query not in haystack:
                continue
            self._work_ids.append(work_id)
            self.relationship_work_list.insert("end", f"{work_id} — {title}")
        if self.current_work_id in self._work_ids:
            idx = self._work_ids.index(self.current_work_id)
            self.relationship_work_list.selection_clear(0, "end")
            self.relationship_work_list.selection_set(idx)
            self.relationship_work_list.see(idx)

    def load_selected_work(self) -> None:
        sel = self.relationship_work_list.curselection()
        if not sel:
            return
        self.current_work_id = self._work_ids[sel[0]]
        self._refresh_work_inspector()

    def _refresh_work_inspector(self) -> None:
        if not self.current_work_id:
            return
        payload = load_work_payload(self.current_work_id)
        refs = work_relationship_refs(self.current_work_id)
        title = str(payload.get("title") or self.current_work_id)
        self.work_heading_label.configure(text=title)
        self.work_relationship_label.configure(text=f"{self.current_work_id} · {refs.get('series') or 'unassigned'} · position {refs.get('position') or '—'}")
        series_choices = available_series_slugs()
        self.work_target_series_combo.configure(values=series_choices)
        current_series = str(refs.get("series") or "")
        if current_series:
            self.work_target_series_var.set(current_series)
        lines = [
            f"Work id: {self.current_work_id}",
            f"Current series: {refs.get('series') or '—'}",
            f"Position in series: {refs.get('position') or '—'}",
            f"Series cover: {'Yes' if refs.get('is_cover_for') else 'No'}",
            f"Cover for: {', '.join(refs.get('is_cover_for') or []) or '—'}",
            f"Homepage featured: {'Yes' if refs.get('homepage_featured') else 'No'}",
            f"Page hero references: {', '.join(refs.get('hero_pages') or []) or '—'}",
            f"Location: {str(payload.get('location') or '').strip() or '—'}",
            f"Published: {'Yes' if bool(payload.get('published', True)) else 'No'}",
        ]
        self.work_detail_box.delete("1.0", "end")
        self.work_detail_box.insert("end", "\n".join(lines))

    def move_selected_work_now(self) -> None:
        if not self.current_work_id:
            return
        target = self.work_target_series_var.get().strip()
        if not target:
            return
        position = 1 if self.work_position_var.get().strip() == "Start" else None
        try:
            with transaction(f"gui-move-work:{self.current_work_id}:{target}"):
                move_work_to_series(self.current_work_id, target, position=position)
            self.app.log(f"Moved {self.current_work_id} to {target}")
            self.app.refresh_publish_state()
            self._refresh_work_inspector()
            self._refresh_series_list()
            if self.current_series_slug:
                self._refresh_series_editor()
            if hasattr(self.app, "refresh_work_list"):
                self.app.refresh_work_list()
            if hasattr(self.app, "refresh_series_list"):
                self.app.refresh_series_list()
            if hasattr(self.app, "validation_widget"):
                self.app.validation_widget.refresh(rerun=True)
        except Exception as exc:
            messagebox.showerror("Move failed", str(exc), parent=self)

    def set_selected_work_as_cover(self) -> None:
        if not self.current_work_id:
            return
        refs = work_relationship_refs(self.current_work_id)
        current_series = str(refs.get("series") or "")
        if not current_series:
            messagebox.showerror("No series", "This work is not assigned to a series.", parent=self)
            return
        try:
            with transaction(f"gui-set-cover:{current_series}:{self.current_work_id}"):
                set_series_cover_work(current_series, self.current_work_id)
            self.app.log(f"Set {self.current_work_id} as cover for {current_series}")
            self.app.refresh_publish_state()
            self._refresh_work_inspector()
            if self.current_series_slug == current_series:
                self._refresh_series_editor()
            if hasattr(self.app, "refresh_series_list"):
                self.app.refresh_series_list()
        except Exception as exc:
            messagebox.showerror("Cover update failed", str(exc), parent=self)

    def toggle_selected_work_featured(self) -> None:
        if not self.current_work_id:
            return
        home = load_home_relationships()
        featured = list(home.get("featured_works") or [])
        if self.current_work_id in featured:
            featured = [work_id for work_id in featured if work_id != self.current_work_id]
            action = "removed from"
        else:
            featured.append(self.current_work_id)
            action = "added to"
        try:
            with transaction(f"gui-toggle-home-featured:{self.current_work_id}"):
                save_home_relationships(featured_works=featured)
            self.app.log(f"{self.current_work_id} {action} homepage featured works")
            self.app.refresh_publish_state()
            self._refresh_home_lists()
            self._refresh_work_inspector()
            if hasattr(self.app, "validation_widget"):
                self.app.validation_widget.refresh(rerun=True)
        except Exception as exc:
            messagebox.showerror("Homepage update failed", str(exc), parent=self)

    def open_selected_work_in_main_tab(self) -> None:
        if not self.current_work_id:
            return
        if hasattr(self.app, "works_tab"):
            self.app.notebook.select(self.app.works_tab)
        if hasattr(self.app, "select_work_by_id"):
            self.app.select_work_by_id(self.current_work_id)

    def open_selected_work_series_in_main_tab(self) -> None:
        if not self.current_work_id:
            return
        refs = work_relationship_refs(self.current_work_id)
        current_series = str(refs.get("series") or "")
        if not current_series:
            return
        if hasattr(self.app, "series_tab"):
            self.app.notebook.select(self.app.series_tab)
        if current_series in getattr(self.app, "_series_slugs", []):
            idx = self.app._series_slugs.index(current_series)
            self.app.series_list.selection_clear(0, "end")
            self.app.series_list.selection_set(idx)
            self.app.series_list.activate(idx)
            self.app.series_list.see(idx)
            self.app.load_selected_series()
