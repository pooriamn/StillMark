from __future__ import annotations

import copy
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

import yaml

try:
    from content_models import PageModel, SectionModel, ValidationReport
    from control_panel_forms import ActionListEditor, BoundEntryRow, BoundTextRow, CardListEditor, DiffPreview, OrderedPickerEditor, OrderedRecordListEditor, OrderedStringListEditor, ValidationSummaryBar, _style_text_widget
    from helpers_content import available_page_keys, available_series_slugs, available_work_ids, diff_page_payloads, load_page_model, load_page_payload, load_resources_payload, save_page_model, save_page_payload
    from helpers_validation import ContentValidator, summarize_validation_report, write_validation_report
    from page_blocks import allowed_block_types, block_spec, default_section, ensure_required_system_sections, friendly_block_name, next_section_id
except ImportError:  # pragma: no cover
    from scripts.content_models import PageModel, SectionModel, ValidationReport  # type: ignore
    from scripts.control_panel_forms import ActionListEditor, BoundEntryRow, BoundTextRow, CardListEditor, DiffPreview, OrderedPickerEditor, OrderedRecordListEditor, OrderedStringListEditor, ValidationSummaryBar, _style_text_widget  # type: ignore
    from scripts.helpers_content import available_page_keys, available_series_slugs, available_work_ids, diff_page_payloads, load_page_model, load_page_payload, load_resources_payload, save_page_model, save_page_payload  # type: ignore
    from scripts.helpers_validation import ContentValidator, summarize_validation_report, write_validation_report  # type: ignore
    from scripts.page_blocks import allowed_block_types, block_spec, default_section, ensure_required_system_sections, friendly_block_name, next_section_id  # type: ignore


class ContentBuilderTab(ttk.Frame):
    def __init__(self, master: tk.Misc, app: "ControlPanel") -> None:
        super().__init__(master)
        self.app = app
        self.validator = ContentValidator(getattr(app, 'ROOT', None) or __import__('pathlib').Path(__file__).resolve().parents[1])
        self.current_page_key: str = ''
        self.current_model: PageModel | None = None
        self.original_payload: dict[str, Any] = {}
        self.section_editor_widgets: dict[str, Any] = {}
        self.hero_widgets: dict[str, Any] = {}
        self.advanced_unlocked = tk.BooleanVar(value=False)
        self.summary_bar = None
        self._live_after_id: str | None = None
        self._quiet_validation_after_id: str | None = None
        self._live_suspended = False
        self.builder_context_var = tk.StringVar(value='No page selected')
        self.builder_dirty_var = tk.StringVar(value='Clean')
        self.builder_status_var = tk.StringVar(value='Live sync idle')
        self.builder_readiness_var = tk.StringVar(value='Ready')
        self.builder_sections_var = tk.StringVar(value='No sections loaded')
        self.builder_focus_var = tk.StringVar(value='No selection yet')
        self.builder_sync_meta_var = tk.StringVar(value='Awaiting first page load')
        self.section_snapshot_var = tk.StringVar(value='No section selected')
        self.section_meta_var = tk.StringVar(value='Select a page, then choose a section to edit its content.')
        self.last_validation_errors = 0
        self.last_validation_warnings = 0
        self.build_ui()
        self.refresh()

    def build_ui(self) -> None:
        shell = ttk.Frame(self, style='Card.TFrame', padding=0)
        shell.pack(fill='both', expand=True)

        header = ttk.Frame(shell, style='Card.TFrame', padding=10)
        header.pack(fill='x', pady=(0, 10))
        left_info = ttk.Frame(header, style='Card.TFrame')
        left_info.pack(side='left', fill='x', expand=True)
        ttk.Label(left_info, text='Content builder', style='CardTitle.TLabel').pack(anchor='w')
        ttk.Label(left_info, text='Edit the current page with live diff, clearer section state, and quieter validation feedback.', style='PanelSub.TLabel').pack(anchor='w', pady=(2, 0))
        right_info = ttk.Frame(header, style='Card.TFrame')
        right_info.pack(side='right')
        ttk.Label(right_info, textvariable=self.builder_context_var, style='StatusInfo.TLabel').pack(anchor='e')
        ttk.Label(right_info, textvariable=self.builder_dirty_var, style='Pill.TLabel').pack(anchor='e', pady=(6, 0))
        ttk.Label(right_info, textvariable=self.builder_status_var, style='PanelSub.TLabel').pack(anchor='e', pady=(6, 0))

        metrics = ttk.Frame(shell, style='Card.TFrame', padding=(10, 0, 10, 10))
        metrics.pack(fill='x')
        self.readiness_label = ttk.Label(metrics, textvariable=self.builder_readiness_var, style='StatusGood.TLabel')
        self.readiness_label.pack(side='left')
        ttk.Label(metrics, textvariable=self.builder_sections_var, style='Pill.TLabel').pack(side='left', padx=(8, 0))
        ttk.Label(metrics, textvariable=self.builder_focus_var, style='StatusInfo.TLabel').pack(side='left', padx=(8, 0))
        ttk.Label(metrics, textvariable=self.builder_sync_meta_var, style='PanelSub.TLabel').pack(side='right')

        split = ttk.Panedwindow(shell, orient='horizontal')
        split.pack(fill='both', expand=True)

        left = ttk.Labelframe(split, text='Pages', padding=8)
        middle = ttk.Labelframe(split, text='Sections', padding=8)
        right = ttk.Labelframe(split, text='Editor', padding=8)
        split.add(left, weight=1)
        split.add(middle, weight=2)
        split.add(right, weight=4)

        self.page_list = tk.Listbox(left, exportselection=False, height=12)
        self.page_list.pack(fill='both', expand=True)
        self.page_list.bind('<<ListboxSelect>>', self.on_page_selected)
        self.page_reload_button = ttk.Button(left, text='Reload pages', command=self.refresh)
        self.page_reload_button.pack(anchor='w', pady=(8, 0))

        self.section_hint_var = tk.StringVar(value='Select a page, then choose a section to edit its content.')
        ttk.Label(middle, textvariable=self.section_hint_var, style='Sub.TLabel').pack(anchor='w', pady=(0, 6))
        ttk.Label(middle, textvariable=self.section_snapshot_var, style='StatusInfo.TLabel').pack(anchor='w')
        ttk.Label(middle, textvariable=self.section_meta_var, style='PanelSub.TLabel', wraplength=360, justify='left').pack(anchor='w', fill='x', pady=(6, 8))
        self.section_tree = ttk.Treeview(middle, columns=('order', 'label', 'type', 'state'), show='headings', height=14)
        columns = [('order', '#', 42, 'center', False), ('label', 'Section', 190, 'w', True), ('type', 'Type', 132, 'w', False), ('state', 'State', 118, 'w', False)]
        for key, title, width, anchor, stretch in columns:
            self.section_tree.heading(key, text=title)
            self.section_tree.column(key, width=width, anchor=anchor, stretch=stretch)
        self.section_tree.pack(fill='both', expand=True)
        try:
            self.section_tree.tag_configure('hidden', foreground='#7a8794')
            self.section_tree.tag_configure('locked', foreground='#153e75')
        except Exception:
            pass
        self.section_tree.bind('<<TreeviewSelect>>', self.on_section_selected)
        toolbar = ttk.Frame(middle)
        toolbar.pack(fill='x', pady=(8, 0))
        self.section_add_button = ttk.Button(toolbar, text='Add', command=self.add_section)
        self.section_add_button.pack(side='left')
        self.section_duplicate_button = ttk.Button(toolbar, text='Duplicate', command=self.duplicate_selected_section)
        self.section_duplicate_button.pack(side='left', padx=(6, 0))
        self.section_remove_button = ttk.Button(toolbar, text='Remove', command=self.remove_selected_section)
        self.section_remove_button.pack(side='left', padx=(6, 0))
        self.section_toggle_button = ttk.Button(toolbar, text='Hide/Show', command=self.toggle_selected_section_visibility)
        self.section_toggle_button.pack(side='left', padx=(12, 0))
        self.section_up_button = ttk.Button(toolbar, text='▲', command=lambda: self.move_selected_section(-1), width=4)
        self.section_up_button.pack(side='left', padx=(12, 0))
        self.section_down_button = ttk.Button(toolbar, text='▼', command=lambda: self.move_selected_section(1), width=4)
        self.section_down_button.pack(side='left', padx=(6, 0))

        self.editor_book = ttk.Notebook(right)
        self.editor_book.pack(fill='both', expand=True)
        self.hero_tab = ttk.Frame(self.editor_book, padding=8)
        self.section_tab = ttk.Frame(self.editor_book, padding=8)
        self.diff_tab = ttk.Frame(self.editor_book, padding=8)
        self.advanced_tab = ttk.Frame(self.editor_book, padding=8)
        self.editor_book.add(self.hero_tab, text='Hero & SEO')
        self.editor_book.add(self.section_tab, text='Section Editor')
        self.editor_book.add(self.diff_tab, text='Diff & Save')
        self.editor_book.add(self.advanced_tab, text='Advanced YAML')

        self.render_hero_seo_editor()

        self.section_editor_frame = ttk.Frame(self.section_tab)
        self.section_editor_frame.pack(fill='both', expand=True)

        self.summary_bar = ValidationSummaryBar(self.diff_tab)
        self.summary_bar.pack(fill='x')
        self.diff_preview = DiffPreview(self.diff_tab)
        self.diff_preview.pack(fill='both', expand=True, pady=(8, 8))
        diff_actions = ttk.Frame(self.diff_tab)
        diff_actions.pack(fill='x')
        self.validate_button = ttk.Button(diff_actions, text='Validate page', command=self.validate_current_page)
        self.validate_button.pack(side='left')
        self.save_button = ttk.Button(diff_actions, text='Save draft', command=self.save_draft, style='Accent.TButton')
        self.save_button.pack(side='left', padx=(8, 0))
        self.build_button = ttk.Button(diff_actions, text='Save and rebuild', command=self.save_and_rebuild)
        self.build_button.pack(side='left', padx=(8, 0))
        self.revert_button = ttk.Button(diff_actions, text='Revert unsaved', command=self.revert_unsaved)
        self.revert_button.pack(side='left', padx=(8, 0))

        ttk.Checkbutton(self.advanced_tab, text='Unlock raw YAML editor', variable=self.advanced_unlocked, command=lambda: self.unlock_advanced_yaml(self.advanced_unlocked.get())).pack(anchor='w')
        self.advanced_yaml = tk.Text(self.advanced_tab, wrap='none', state='disabled')
        _style_text_widget(self.advanced_yaml, rows=24)
        self.advanced_yaml.pack(fill='both', expand=True, pady=(8, 8))
        adv_actions = ttk.Frame(self.advanced_tab)
        adv_actions.pack(fill='x')
        ttk.Button(adv_actions, text='Validate YAML', command=self.validate_advanced_yaml).pack(side='left')
        ttk.Button(adv_actions, text='Save raw YAML', command=self.save_advanced_yaml).pack(side='left', padx=(8, 0))
        self._update_section_toolbar_state()

    def _set_live_suspended(self, value: bool) -> None:
        self._live_suspended = bool(value)

    def _schedule_live_refresh(self, *_args: Any) -> None:
        if self._live_suspended:
            return
        self.builder_status_var.set('Live sync pending…')
        if self._live_after_id is not None:
            try:
                self.after_cancel(self._live_after_id)
            except Exception:
                pass
        self._live_after_id = self.after(180, self._run_live_refresh)

    def _schedule_quiet_validation(self) -> None:
        if self._live_suspended:
            return
        if self._quiet_validation_after_id is not None:
            try:
                self.after_cancel(self._quiet_validation_after_id)
            except Exception:
                pass
        self._quiet_validation_after_id = self.after(320, self._run_quiet_validation)

    def _run_live_refresh(self) -> None:
        self._live_after_id = None
        if self._live_suspended:
            return
        try:
            self.commit_header_changes(quiet=True, render=False)
            self._apply_selected_section_changes(show_feedback=False, render=False)
            self.render_diff_preview()
            self.builder_status_var.set(f'Live diff updated · {self._timestamp()}')
            self._schedule_quiet_validation()
        except Exception as exc:
            self.builder_status_var.set(f'Live sync paused: {exc}')

    def _run_quiet_validation(self) -> None:
        self._quiet_validation_after_id = None
        try:
            self.validate_current_page(quiet=True, render=False)
            if not self._pending_diff_lines():
                self.builder_status_var.set(f'All changes reflected and clean · {self._timestamp()}')
        except Exception:
            pass

    def _timestamp(self) -> str:
        return time.strftime('%H:%M:%S')

    def _section_state_label(self, section: SectionModel | None) -> str:
        if not section:
            return 'No section selected'
        parts = ['Visible' if section.visible else 'Hidden']
        if section.locked:
            parts.append('System')
        return ' • '.join(parts)

    def _update_builder_metrics(self) -> None:
        if not self.current_model:
            self.builder_readiness_var.set('Ready')
            self.builder_sections_var.set('No sections loaded')
            self.builder_focus_var.set('No selection yet')
            self.builder_sync_meta_var.set('Awaiting first page load')
            self.section_snapshot_var.set('No section selected')
            self.section_meta_var.set('Select a page, then choose a section to edit its content.')
            return
        total = len(self.current_model.sections)
        visible = sum(1 for item in self.current_model.sections if item.visible)
        hidden = total - visible
        locked = sum(1 for item in self.current_model.sections if item.locked)
        diff_count = len(self._pending_diff_lines())
        if self.last_validation_errors:
            self.builder_readiness_var.set(f'Blocked · {self.last_validation_errors} error' + ('s' if self.last_validation_errors != 1 else ''))
            style_name = 'StatusBad.TLabel'
        elif self.last_validation_warnings:
            self.builder_readiness_var.set(f'Warnings · {self.last_validation_warnings}')
            style_name = 'StatusWarn.TLabel'
        elif diff_count:
            self.builder_readiness_var.set(f'Unsaved · {diff_count}')
            style_name = 'StatusInfo.TLabel'
        else:
            self.builder_readiness_var.set('Ready')
            style_name = 'StatusGood.TLabel'
        try:
            self.readiness_label.configure(style=style_name)
        except Exception:
            pass
        self.builder_sections_var.set(f'{total} sections • {visible} visible • {hidden} hidden • {locked} system')
        section = self._selected_section()
        if section is None:
            self.builder_focus_var.set('No section selected')
            self.section_snapshot_var.set('No section selected')
            self.section_meta_var.set('Choose a section to inspect its state, position, and content density.')
        else:
            idx = (self._selected_section_index() or 0) + 1
            filled = sum(1 for value in section.data.values() if str(value or '').strip())
            total_fields = len(block_spec(section.type).fields)
            self.builder_focus_var.set(f'Focus · {section.label} · {idx}/{max(total,1)}')
            self.section_snapshot_var.set(f'{section.label} · {self._section_state_label(section)}')
            self.section_meta_var.set(f'{friendly_block_name(section.type)} • {filled}/{total_fields} populated fields • id: {section.id}')
        self.builder_sync_meta_var.set(f'Live refresh {self._timestamp()}')

    def _update_builder_context(self) -> None:
        section = self._selected_section()
        section_label = section.label if section else 'No section selected'
        total_sections = len(self.current_model.sections) if self.current_model else 0
        page_label = self.current_page_key or 'No page'
        self.builder_context_var.set(f'{page_label} • {total_sections} sections • {section_label}')
        self._update_builder_metrics()

    def _update_section_toolbar_state(self) -> None:
        idx = self._selected_section_index()
        section = self._selected_section()
        has_selection = section is not None and idx is not None
        locked = bool(section.locked) if section else False
        total = len(self.current_model.sections) if self.current_model else 0
        for button, enabled in (
            (getattr(self, 'section_duplicate_button', None), has_selection),
            (getattr(self, 'section_toggle_button', None), has_selection),
            (getattr(self, 'section_remove_button', None), has_selection and not locked),
            (getattr(self, 'section_up_button', None), has_selection and idx not in (None, 0)),
            (getattr(self, 'section_down_button', None), has_selection and idx is not None and idx < max(0, total - 1)),
        ):
            try:
                if enabled:
                    button.state(['!disabled'])
                else:
                    button.state(['disabled'])
            except Exception:
                pass
        self._update_builder_context()

    def refresh(self) -> None:
        self.load_page_list()
        if self.page_list.size() and not self.page_list.curselection():
            self.page_list.selection_set(0)
            self.on_page_selected()

    def load_page_list(self) -> None:
        self.page_list.delete(0, 'end')
        for key in available_page_keys():
            self.page_list.insert('end', key)

    def select_page(self, page_key: str) -> None:
        keys = list(available_page_keys())
        if page_key in keys:
            idx = keys.index(page_key)
            self.page_list.selection_clear(0, 'end')
            self.page_list.selection_set(idx)
            self.on_page_selected()

    def on_page_selected(self, event: object | None = None) -> None:
        sel = self.page_list.curselection()
        if not sel:
            return
        self.current_page_key = str(self.page_list.get(sel[0]))
        self.load_current_page()

    def load_current_page(self) -> None:
        if not self.current_page_key:
            return
        self._set_live_suspended(True)
        self.current_model = ensure_required_system_sections(load_page_model(self.current_page_key))
        self.original_payload = load_page_payload(self.current_page_key)
        self.last_validation_errors = 0
        self.last_validation_warnings = 0
        self.load_hero_into_form()
        page_hints = {
            'about': 'To edit cards like Language, Series rhythm, or Archive, select the Practice cards section in the middle column.',
            'contact': 'Select a section such as Direct contact, Contact form, or Documents to edit that block.',
            'series': 'Select Related series, Inquiry block, or Documents to edit that page content.',
            'home': 'Select Featured series, Featured works, or spotlight modules to edit homepage content.',
        }
        self.section_hint_var.set(page_hints.get(self.current_page_key, 'Select a section to edit its content.'))
        self.render_section_list(preserve_index=0)
        self.load_advanced_yaml()
        self.render_diff_preview()
        self._set_live_suspended(False)
        self.validate_current_page(quiet=True, render=False)
        self.builder_status_var.set(f'Live sync ready · {self._timestamp()}')
        self._update_builder_context()
        self.app.status_var.set(f'Loaded page builder for {self.current_page_key}.')

    def load_hero_into_form(self) -> None:
        if not self.current_model:
            return
        for key, widget in self.hero_widgets.items():
            if isinstance(widget, tk.StringVar):
                if key.startswith('meta.'):
                    widget.set(str(getattr(self.current_model.meta, key.split('.', 1)[1]) or ''))
                else:
                    widget.set(str(getattr(self.current_model.hero, key) or ''))
            elif isinstance(widget, BoundTextRow):
                if key.startswith('meta.'):
                    widget.set_value(str(getattr(self.current_model.meta, key.split('.', 1)[1]) or ''))
                else:
                    widget.set_value(str(getattr(self.current_model.hero, key) or ''))
            elif isinstance(widget, OrderedStringListEditor):
                widget.set_items(list(self.current_model.hero.notes))
            elif isinstance(widget, ActionListEditor):
                widget.set_items([item.to_dict() for item in self.current_model.hero.actions])

    def render_page_header(self) -> None:
        self.load_hero_into_form()

    def render_section_list(self, preserve_index: int | None = None) -> None:
        for item in self.section_tree.get_children():
            self.section_tree.delete(item)
        if not self.current_model:
            self._update_section_toolbar_state()
            return
        current_idx = self._selected_section_index() if preserve_index is None else preserve_index
        for idx, section in enumerate(self.current_model.sections):
            tags: tuple[str, ...] = tuple(tag for tag, enabled in (('hidden', not section.visible), ('locked', section.locked)) if enabled)
            self.section_tree.insert('', 'end', iid=str(idx), values=(idx + 1, section.label, friendly_block_name(section.type), self._section_state_label(section)), tags=tags)
        if self.current_model.sections:
            if current_idx is None or current_idx >= len(self.current_model.sections):
                current_idx = 0
            self.section_tree.selection_set(str(current_idx))
            self.section_tree.focus(str(current_idx))
            self.section_tree.see(str(current_idx))
            self.on_section_selected()
        else:
            self._update_section_toolbar_state()

    def render_selected_section_editor(self) -> None:
        for child in self.section_editor_frame.winfo_children():
            child.destroy()
        self.section_editor_widgets = {}
        section = self._selected_section()
        if not section:
            ttk.Label(self.section_editor_frame, text='Select a section to edit.', style='Sub.TLabel').pack(anchor='w')
            self._update_section_toolbar_state()
            return
        spec = block_spec(section.type)
        idx = (self._selected_section_index() or 0) + 1
        total = len(self.current_model.sections) if self.current_model else 0
        ttk.Label(self.section_editor_frame, text=f'{spec.label} — {spec.description}', style='Sub.TLabel').pack(anchor='w', pady=(0, 6))
        ttk.Label(self.section_editor_frame, text=f'{self._section_state_label(section)} • Position {idx} of {total} • Changes update the diff preview automatically.', style='PanelSub.TLabel').pack(anchor='w', pady=(0, 10))
        label_var = tk.StringVar(value=section.label)
        label_var.trace_add('write', self._schedule_live_refresh)
        base_row = BoundEntryRow(self.section_editor_frame, label='Section label', textvariable=label_var, help_text='This label is only used in the control panel.')
        base_row.pack(fill='x', pady=(0, 8))
        self.section_editor_widgets['__label__'] = base_row
        self.section_editor_widgets['__label_var__'] = label_var
        for field in spec.fields:
            widget: Any
            value = section.data.get(field.key)
            if field.editor == 'entry':
                var = tk.StringVar(value=str(value or ''))
                var.trace_add('write', self._schedule_live_refresh)
                widget = BoundEntryRow(self.section_editor_frame, label=field.label, textvariable=var, help_text=field.help_text)
                widget.var = var  # type: ignore[attr-defined]
            elif field.editor == 'textarea':
                widget = BoundTextRow(self.section_editor_frame, label=field.label, help_text=field.help_text, rows=field.rows or 5, placeholder=field.placeholder, on_change=self._schedule_live_refresh)
                widget.set_value(str(value or ''))
            elif field.editor == 'action_list':
                widget = ActionListEditor(self.section_editor_frame, label=field.label, on_change=self._schedule_live_refresh)
                widget.set_items(list(value or []))
            elif field.editor == 'reorder_list':
                widget = OrderedStringListEditor(self.section_editor_frame, label=field.label, item_label='Item', on_change=self._schedule_live_refresh)
                widget.set_items(list(value or []))
            elif field.editor == 'card_list':
                widget = CardListEditor(self.section_editor_frame, label=field.label, on_change=self._schedule_live_refresh)
                widget.set_items(list(value or []))
            elif field.editor == 'metric_list':
                widget = OrderedRecordListEditor(self.section_editor_frame, label=field.label, columns=('value', 'label'), on_change=self._schedule_live_refresh)
                widget.set_items(list(value or []))
            elif field.editor == 'series_picker':
                widget = OrderedPickerEditor(self.section_editor_frame, label=field.label, source_label='series', on_change=self._schedule_live_refresh)
                choices = [(slug, slug) for slug in available_series_slugs()]
                widget.set_choices(choices)
                widget.set_selected_ids(list(value or []))
            elif field.editor == 'work_picker':
                widget = OrderedPickerEditor(self.section_editor_frame, label=field.label, source_label='works', on_change=self._schedule_live_refresh)
                choices = [(work_id, work_id) for work_id in available_work_ids()]
                widget.set_choices(choices)
                widget.set_selected_ids(list(value or []))
            elif field.editor == 'document_picker':
                widget = OrderedPickerEditor(self.section_editor_frame, label=field.label, source_label='documents', on_change=self._schedule_live_refresh)
                docs = load_resources_payload().get('downloads') if isinstance(load_resources_payload().get('downloads'), list) else []
                choices = [(str(item.get('id') or ''), str(item.get('title') or item.get('id') or '')) for item in docs if isinstance(item, dict) and str(item.get('id') or '').strip()]
                widget.set_choices(choices)
                widget.set_selected_ids(list(value or []))
            elif field.editor == 'combobox':
                frame = ttk.Frame(self.section_editor_frame)
                ttk.Label(frame, text=field.label).pack(anchor='w')
                var = tk.StringVar(value=str(value or ''))
                var.trace_add('write', self._schedule_live_refresh)
                combo = ttk.Combobox(frame, textvariable=var, values=available_work_ids(), state='readonly')
                combo.pack(fill='x', pady=(2, 0))
                frame.var = var  # type: ignore[attr-defined]
                widget = frame
            else:
                var = tk.StringVar(value=str(value or ''))
                var.trace_add('write', self._schedule_live_refresh)
                widget = BoundEntryRow(self.section_editor_frame, label=field.label, textvariable=var)
                widget.var = var  # type: ignore[attr-defined]
            widget.pack(fill='both', expand=False, pady=(0, 8))
            self.section_editor_widgets[field.key] = widget
        actions = ttk.Frame(self.section_editor_frame)
        actions.pack(fill='x', pady=(8, 0))
        self.apply_section_button = ttk.Button(actions, text='Apply section changes', command=self.commit_selected_section_changes, style='Accent.TButton')
        self.apply_section_button.pack(side='left')
        ttk.Label(actions, text='Live preview is already updating as you type.', style='PanelSub.TLabel').pack(side='left', padx=(10, 0))
        self._update_section_toolbar_state()

    def render_hero_seo_editor(self) -> None:
        for child in self.hero_tab.winfo_children():
            child.destroy()
        self.hero_widgets = {}
        ttk.Label(self.hero_tab, text='Hero fields also update the diff and readiness state automatically.', style='PanelSub.TLabel').pack(anchor='w', pady=(0, 10))
        fields = [
            ('meta.title', 'Meta title', 'entry'),
            ('meta.description', 'Meta description', 'textarea'),
            ('meta.og_description', 'OG description', 'textarea'),
            ('meta.og_image_alt', 'OG image alt', 'entry'),
            ('meta.canonical_path', 'Canonical path', 'entry'),
            ('meta.twitter_image_alt', 'Twitter image alt', 'entry'),
            ('eyebrow', 'Hero eyebrow', 'entry'),
            ('title', 'Hero title', 'entry'),
            ('lead', 'Hero lead', 'textarea'),
            ('feature_work_id', 'Hero feature work', 'entry'),
        ]
        for key, label, kind in fields:
            if kind == 'entry':
                var = tk.StringVar()
                var.trace_add('write', self._schedule_live_refresh)
                row = BoundEntryRow(self.hero_tab, label=label, textvariable=var)
                row.var = var  # type: ignore[attr-defined]
                row.pack(fill='x', pady=(0, 8))
                self.hero_widgets[key] = var
            else:
                row = BoundTextRow(self.hero_tab, label=label, rows=5, on_change=self._schedule_live_refresh)
                row.pack(fill='x', pady=(0, 8))
                self.hero_widgets[key] = row
        notes = OrderedStringListEditor(self.hero_tab, label='Hero notes', item_label='Note', on_change=self._schedule_live_refresh)
        notes.pack(fill='x', pady=(0, 8))
        actions = ActionListEditor(self.hero_tab, label='Hero actions', on_change=self._schedule_live_refresh)
        actions.pack(fill='both', expand=True, pady=(0, 8))
        self.hero_widgets['notes'] = notes
        self.hero_widgets['actions'] = actions
        self.apply_hero_button = ttk.Button(self.hero_tab, text='Apply hero and SEO changes', command=self.commit_header_changes, style='Accent.TButton')
        self.apply_hero_button.pack(anchor='w')

    def _selected_section_index(self) -> int | None:
        sel = self.section_tree.selection()
        return int(sel[0]) if sel else None

    def _selected_section(self) -> SectionModel | None:
        if not self.current_model:
            return None
        idx = self._selected_section_index()
        if idx is None or idx >= len(self.current_model.sections):
            return None
        return self.current_model.sections[idx]

    def on_section_selected(self, event: object | None = None) -> None:
        self.render_selected_section_editor()
        self._update_section_toolbar_state()
        self._update_builder_context()

    def _choose_block_type(self) -> str | None:
        if not self.current_model:
            return None
        choices = tuple(allowed_block_types(self.current_model.page_key))
        if not choices:
            return None
        dialog = tk.Toplevel(self)
        dialog.title('Add section')
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        dialog.resizable(False, False)

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Choose a section type for this page.').pack(anchor='w')

        pretty_choices = [f"{friendly_block_name(item)} ({item})" for item in choices]
        selected = tk.StringVar(value=pretty_choices[0])
        combo = ttk.Combobox(frame, textvariable=selected, values=pretty_choices, state='readonly', width=44)
        combo.pack(fill='x', pady=(8, 12))
        combo.focus_set()

        result = {'value': None}

        def confirm() -> None:
            current = selected.get().strip()
            for raw, pretty in zip(choices, pretty_choices):
                if current == pretty:
                    result['value'] = raw
                    break
            dialog.destroy()

        def cancel() -> None:
            dialog.destroy()

        buttons = ttk.Frame(frame)
        buttons.pack(fill='x')
        ttk.Button(buttons, text='Cancel', command=cancel).pack(side='right')
        ttk.Button(buttons, text='Add section', command=confirm, style='Accent.TButton').pack(side='right', padx=(0, 8))
        dialog.bind('<Return>', lambda e: confirm())
        dialog.bind('<Escape>', lambda e: cancel())
        dialog.wait_window()
        return result['value']

    def add_section(self, block_type: str | None = None) -> None:
        if not self.current_model:
            return
        if block_type is None:
            block_type = self._choose_block_type()
            if not block_type:
                return
        if block_type not in allowed_block_types(self.current_model.page_key):
            messagebox.showerror('Unsupported block', f"'{block_type}' is not supported for {self.current_model.page_key}.")
            return
        section = default_section(block_type)
        section.id = next_section_id({item.id for item in self.current_model.sections}, section.id)
        self.current_model.sections.append(section)
        self.render_section_list(preserve_index=len(self.current_model.sections) - 1)
        try:
            new_idx = len(self.current_model.sections) - 1
            self.section_tree.selection_set(str(new_idx))
            self.section_tree.focus(str(new_idx))
        except Exception:
            pass
        self.on_section_selected()
        self.render_diff_preview()

    def duplicate_selected_section(self) -> None:
        section = self._selected_section()
        if not section or not self.current_model:
            return
        copied = copy.deepcopy(section)
        copied.id = next_section_id({item.id for item in self.current_model.sections}, f'{section.id}-copy')
        copied.label = f'{section.label} copy'
        idx = self._selected_section_index() or 0
        self.current_model.sections.insert(idx + 1, copied)
        self.render_section_list(preserve_index=idx + 1)
        self.section_tree.selection_set(str(idx + 1))
        self.on_section_selected()
        self.render_diff_preview()

    def remove_selected_section(self) -> None:
        idx = self._selected_section_index()
        section = self._selected_section()
        if idx is None or not section or not self.current_model:
            return
        if section.locked:
            messagebox.showerror('Locked section', 'This system section cannot be removed.')
            return
        self.current_model.sections.pop(idx)
        next_idx = min(idx, len(self.current_model.sections) - 1) if self.current_model.sections else None
        self.render_section_list(preserve_index=next_idx)
        self.on_section_selected()
        self.render_diff_preview()

    def move_selected_section(self, direction: int) -> None:
        idx = self._selected_section_index()
        if idx is None or not self.current_model:
            return
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self.current_model.sections):
            return
        self.current_model.sections.insert(new_idx, self.current_model.sections.pop(idx))
        self.render_section_list(preserve_index=new_idx)
        self.section_tree.selection_set(str(new_idx))
        self.on_section_selected()
        self.render_diff_preview()

    def toggle_selected_section_visibility(self) -> None:
        section = self._selected_section()
        if not section:
            return
        section.visible = not section.visible
        self.render_section_list(preserve_index=self._selected_section_index())
        self.render_diff_preview()

    def commit_header_changes(self, quiet: bool = False, render: bool = True) -> None:
        if not self.current_model:
            return
        self.current_model.meta.title = str(self.hero_widgets['meta.title'].get()).strip()
        self.current_model.meta.description = self.hero_widgets['meta.description'].get_value()
        self.current_model.meta.og_description = self.hero_widgets['meta.og_description'].get_value()
        self.current_model.meta.og_image_alt = str(self.hero_widgets['meta.og_image_alt'].get()).strip()
        self.current_model.meta.canonical_path = str(self.hero_widgets['meta.canonical_path'].get()).strip()
        self.current_model.meta.twitter_image_alt = str(self.hero_widgets['meta.twitter_image_alt'].get()).strip()
        self.current_model.hero.eyebrow = str(self.hero_widgets['eyebrow'].get()).strip()
        self.current_model.hero.title = str(self.hero_widgets['title'].get()).strip()
        self.current_model.hero.lead = self.hero_widgets['lead'].get_value()
        self.current_model.hero.feature_work_id = str(self.hero_widgets['feature_work_id'].get()).strip()
        self.current_model.hero.notes = self.hero_widgets['notes'].get_items()
        from_item = self.hero_widgets['actions'].get_items()
        self.current_model.hero.actions = []
        for item in from_item:
            if isinstance(item, dict):
                from content_models import ActionLink  # local import for direct-run safety
                self.current_model.hero.actions.append(ActionLink.from_dict(item))
        if render:
            self.render_diff_preview()
        if not quiet:
            self.builder_status_var.set(f'Hero and SEO fields applied · {self._timestamp()}')

    def _apply_selected_section_changes(self, *, show_feedback: bool = False, render: bool = True, refresh_list: bool = False) -> None:
        section = self._selected_section()
        if not section:
            return
        label_var = self.section_editor_widgets.get('__label_var__')
        if isinstance(label_var, tk.StringVar):
            section.label = label_var.get().strip() or section.label
        spec = block_spec(section.type)
        for field in spec.fields:
            widget = self.section_editor_widgets.get(field.key)
            if widget is None:
                continue
            if field.editor == 'entry':
                section.data[field.key] = str(widget.var.get()).strip()  # type: ignore[attr-defined]
            elif field.editor == 'textarea':
                section.data[field.key] = widget.get_value()
            elif field.editor == 'action_list':
                items = widget.get_items()
                section.data[field.key] = items[0:1] if section.type == 'work_spotlight' and field.key == 'action' else items
            elif field.editor == 'reorder_list':
                section.data[field.key] = widget.get_items()
            elif field.editor == 'card_list':
                section.data[field.key] = widget.get_items()
            elif field.editor == 'metric_list':
                section.data[field.key] = widget.get_items()
            elif field.editor in {'series_picker', 'work_picker', 'document_picker'}:
                section.data[field.key] = widget.get_selected_ids()
            elif field.editor == 'combobox':
                section.data[field.key] = str(widget.var.get()).strip()  # type: ignore[attr-defined]
        if refresh_list:
            current_idx = self._selected_section_index()
            self.render_section_list(preserve_index=current_idx)
            try:
                if current_idx is not None:
                    self.section_tree.selection_set(str(current_idx))
                    self.on_section_selected()
            except Exception:
                pass
        if render:
            self.render_diff_preview()
        if show_feedback:
            self.builder_status_var.set(f'Section changes applied · {self._timestamp()}')
            messagebox.showinfo('Section updated', 'Section changes applied in the editor. Save draft to write them into content/.')

    def commit_selected_section_changes(self) -> None:
        self._apply_selected_section_changes(show_feedback=True, render=True, refresh_list=True)

    def validate_current_page(self, quiet: bool = False, render: bool = True) -> ValidationReport:
        if not self.current_model:
            return ValidationReport()
        self.commit_header_changes(quiet=True, render=False)
        self._apply_selected_section_changes(show_feedback=False, render=False)
        report = ValidationReport(issues=self.validator.validate_page_model(self.current_page_key, self.current_model))
        counts = summarize_validation_report(report)
        self.last_validation_errors = counts['errors']
        self.last_validation_warnings = counts['warnings']
        self.summary_bar.set_counts(errors=counts['errors'], warnings=counts['warnings'])
        if counts['errors']:
            self.builder_status_var.set(f'Blocking validation issues need attention · {self._timestamp()}')
        elif counts['warnings']:
            self.builder_status_var.set(f'Validation warnings available inline · {self._timestamp()}')
        else:
            self.builder_status_var.set(f'Validation clean · {self._timestamp()}')
        if render:
            self.render_diff_preview()
        else:
            self._update_builder_metrics()
        if not quiet:
            if report.issues:
                preview_lines = []
                for issue in report.issues[:8]:
                    path = str(issue.path or 'page').strip()
                    preview_lines.append(f"- {path}: {issue.message}")
                if len(report.issues) > 8:
                    preview_lines.append(f"- …and {len(report.issues) - 8} more")
                messagebox.showwarning('Page validation', 'Review these issues before saving\n\n' + '\n'.join(preview_lines))
            else:
                messagebox.showinfo('Page validation', 'No blocking issues found for this page.')
        return report

    def _pending_diff_lines(self) -> list[str]:
        if not self.current_model:
            return []
        return diff_page_payloads(self.original_payload, self.current_model_to_payload())

    def render_diff_preview(self) -> None:
        lines = self._pending_diff_lines()
        self.diff_preview.set_lines(lines)
        self.builder_dirty_var.set('Clean' if not lines else f'Unsaved · {len(lines)} line' + ('s' if len(lines) != 1 else ''))
        self._update_builder_context()

    def current_model_to_payload(self) -> dict[str, Any]:
        if not self.current_model:
            return {}
        from page_blocks import page_model_to_payload
        return page_model_to_payload(self.current_model, self.original_payload)

    def save_draft(self) -> None:
        if not self.current_model:
            return
        report = self.validate_current_page(quiet=True, render=True)
        if report.error_count() > 0:
            messagebox.showerror('Cannot save', 'Fix the blocking errors first.')
            return
        try:
            save_issues = save_page_model(self.current_page_key, self.current_model, validate=True)
            if any(item.severity == 'error' for item in save_issues):
                messagebox.showerror('Cannot save', 'The page still has blocking validation or schema errors.')
                return
            self.original_payload = load_page_payload(self.current_page_key)
            self.load_advanced_yaml()
            self.render_diff_preview()
            self.summary_bar.set_counts(errors=0, warnings=0)
            self.builder_status_var.set('Draft saved and synced')
            if hasattr(self.app, 'refresh_publish_state'):
                self.app.refresh_publish_state()
            if getattr(self.app, 'publish_ops_widget', None) is not None:
                try:
                    self.app.publish_ops_widget.refresh(rerun_validation=False)
                except Exception:
                    pass
            self.app.log(f'Saved page builder draft: {self.current_page_key}')
        except Exception as exc:
            messagebox.showerror('Save failed', str(exc))

    def save_and_rebuild(self) -> None:
        if not self.current_model:
            return
        report = self.validate_current_page(quiet=True, render=True)
        if report.error_count() > 0:
            messagebox.showerror('Cannot build', 'Fix the blocking page errors before rebuilding.')
            return
        try:
            save_issues = save_page_model(self.current_page_key, self.current_model, validate=True)
        except Exception as exc:
            messagebox.showerror('Cannot build', str(exc))
            return
        if any(item.severity == 'error' for item in save_issues):
            messagebox.showerror('Cannot build', 'The page still has blocking validation or schema errors.')
            return
        self.original_payload = load_page_payload(self.current_page_key)
        self.load_advanced_yaml()
        self.render_diff_preview()
        self.builder_status_var.set('Saved and handing off to rebuild')
        if hasattr(self.app, 'refresh_publish_state'):
            self.app.refresh_publish_state()
        if getattr(self.app, 'publish_ops_widget', None) is not None:
            try:
                self.app.publish_ops_widget.refresh(rerun_validation=False)
            except Exception:
                pass
        self.app.log(f'Saved page builder draft: {self.current_page_key}')
        self.app.build_site()

    def revert_unsaved(self) -> None:
        if not self.current_page_key:
            return
        self.load_current_page()

    def unlock_advanced_yaml(self, enabled: bool) -> None:
        self.advanced_yaml.configure(state='normal' if enabled else 'disabled')

    def load_advanced_yaml(self) -> None:
        self.advanced_yaml.configure(state='normal')
        self.advanced_yaml.delete('1.0', 'end')
        self.advanced_yaml.insert('1.0', yaml.safe_dump(self.original_payload, sort_keys=False, allow_unicode=True))
        if not self.advanced_unlocked.get():
            self.advanced_yaml.configure(state='disabled')

    def validate_advanced_yaml(self) -> None:
        try:
            payload = yaml.safe_load(self.advanced_yaml.get('1.0', 'end')) or {}
            if not isinstance(payload, dict):
                raise ValueError('The YAML root must be an object.')
            messagebox.showinfo('YAML validation', 'YAML parses successfully.')
        except Exception as exc:
            messagebox.showerror('YAML validation failed', str(exc))

    def save_advanced_yaml(self) -> None:
        if not self.advanced_unlocked.get():
            messagebox.showerror('Locked', 'Unlock the advanced YAML editor first.')
            return
        try:
            payload = yaml.safe_load(self.advanced_yaml.get('1.0', 'end')) or {}
            if not isinstance(payload, dict):
                raise ValueError('The YAML root must be an object.')
            save_page_payload(self.current_page_key, payload)
            self.load_current_page()
            self.app.log(f'Saved raw page payload: {self.current_page_key}')
        except Exception as exc:
            messagebox.showerror('Save raw YAML failed', str(exc))
