from __future__ import annotations

import tkinter as tk
from tkinter import simpledialog, ttk
from typing import Any, Callable
import time


DEFAULT_FORM_PALETTE = {
    'bg': '#edf2f7',
    'panel': '#ffffff',
    'panel_alt': '#f7fafc',
    'text': '#132433',
    'muted': '#5a6b7c',
    'accent': '#153e75',
    'accent_soft': '#dce8f7',
    'accent_deep': '#0f2e57',
    'line': '#d7e0ea',
    'success': '#146c43',
    'warn': '#9a6700',
    'danger': '#b42318',
}


def _palette(widget: tk.Misc) -> dict[str, str]:
    top = widget.winfo_toplevel()
    pal = getattr(top, '_palette', None)
    if isinstance(pal, dict):
        merged = dict(DEFAULT_FORM_PALETTE)
        merged.update({k: str(v) for k, v in pal.items()})
        return merged
    return dict(DEFAULT_FORM_PALETTE)


def _style_text_widget(widget: tk.Text, *, readonly: bool = False, rows: int | None = None) -> None:
    pal = _palette(widget)
    widget.configure(
        bg=pal['panel_alt'],
        fg=pal['text'],
        insertbackground=pal['text'],
        relief='flat',
        bd=0,
        highlightthickness=1,
        highlightbackground=pal['line'],
        highlightcolor=pal['accent'],
        selectbackground=pal['accent'],
        selectforeground='#08101d',
        font=('Segoe UI', 10),
        padx=10,
        pady=9,
        spacing1=1,
        spacing3=2,
    )
    if rows is not None:
        widget.configure(height=rows)
    if readonly:
        widget.configure(state='disabled', cursor='arrow')


def _style_listbox_widget(widget: tk.Listbox, *, height: int | None = None) -> None:
    pal = _palette(widget)
    widget.configure(
        bg=pal['panel_alt'],
        fg=pal['text'],
        relief='flat',
        bd=0,
        highlightthickness=1,
        highlightbackground=pal['line'],
        highlightcolor=pal['accent'],
        selectbackground=pal['accent'],
        selectforeground='#08101d',
        font=('Segoe UI', 10),
        activestyle='none',
        selectborderwidth=0,
    )
    if height is not None:
        widget.configure(height=height)


def _style_tree_widget(widget: ttk.Treeview) -> None:
    try:
        widget.tag_configure('hidden', foreground='#7a8794')
        widget.tag_configure('active', foreground='#132433')
        widget.tag_configure('odd', background='#fbfdff')
        widget.tag_configure('even', background='#f4f7fb')
        widget.tag_configure('locked', foreground='#153e75')
    except Exception:
        pass


def _emit_change(callback: Callable[[], None] | None) -> None:
    if callback is None:
        return
    try:
        callback()
    except TypeError:
        try:
            callback(None)  # type: ignore[misc]
        except Exception:
            pass
    except Exception:
        pass


def _set_button_state(button: ttk.Widget | None, enabled: bool) -> None:
    if button is None:
        return
    try:
        button.state(['!disabled'] if enabled else ['disabled'])
    except Exception:
        pass


def _word_count(value: str) -> int:
    return len([part for part in str(value or '').split() if part.strip()])


class CardListEditor(ttk.Frame):
    def __init__(self, master: tk.Misc, *, label: str, on_change: Callable[[], None] | None = None) -> None:
        super().__init__(master, style='Card.TFrame', padding=0)
        self.items: list[dict[str, Any]] = []
        self.label = label
        self.on_change = on_change
        self.summary_var = tk.StringVar(value='No cards yet')
        self.selection_var = tk.StringVar(value='Nothing selected')
        self.preview_title_var = tk.StringVar(value='Select a card')
        self.preview_meta_var = tk.StringVar(value='Use the list to inspect, edit, reorder, or hide content blocks.')
        self.status_var = tk.StringVar(value='Ready')
        self.preview_text = None
        self.tree = None
        self.add_button = None
        self.edit_button = None
        self.remove_button = None
        self.duplicate_button = None
        self.move_up_button = None
        self.move_down_button = None
        self.toggle_button = None
        self.inspect_edit_button = None
        self.inspect_duplicate_button = None

        shell = ttk.Frame(self, style='Card.TFrame', padding=12)
        shell.pack(fill='both', expand=True)

        header = ttk.Frame(shell, style='Card.TFrame')
        header.pack(fill='x')
        title_wrap = ttk.Frame(header, style='Card.TFrame')
        title_wrap.pack(side='left', fill='x', expand=True)
        ttk.Label(title_wrap, text=label, style='CardTitle.TLabel').pack(anchor='w')
        ttk.Label(title_wrap, text='Scan on the left. Inspect and edit on the right.', style='PanelSub.TLabel').pack(anchor='w', pady=(2, 0))
        badges = ttk.Frame(header, style='Card.TFrame')
        badges.pack(side='right', anchor='ne')
        ttk.Label(badges, textvariable=self.summary_var, style='StatusInfo.TLabel').pack(anchor='e')
        ttk.Label(badges, textvariable=self.selection_var, style='Pill.TLabel').pack(anchor='e', pady=(6, 0))
        ttk.Label(badges, textvariable=self.status_var, style='PanelSub.TLabel').pack(anchor='e', pady=(6, 0))

        split = ttk.Panedwindow(shell, orient='horizontal')
        split.pack(fill='both', expand=True, pady=(12, 0))

        left = ttk.Labelframe(split, text='Cards overview', padding=10)
        split.add(left, weight=3)
        ttk.Label(left, text='Use the table for scanning; use the inspector for full copy and actions.', style='PanelSub.TLabel', justify='left', wraplength=620).pack(anchor='w', pady=(0, 8))
        tree_wrap = ttk.Frame(left, style='Card.TFrame')
        tree_wrap.pack(fill='both', expand=True)
        cols = ('order', 'visible', 'eyebrow', 'title', 'text')
        self.tree = ttk.Treeview(tree_wrap, columns=cols, show='headings', height=8, selectmode='browse')
        self.tree.heading('order', text='#')
        self.tree.heading('visible', text='State')
        self.tree.heading('eyebrow', text='Eyebrow')
        self.tree.heading('title', text='Title')
        self.tree.heading('text', text='Text excerpt')
        self.tree.column('order', width=52, minwidth=46, anchor='center', stretch=False)
        self.tree.column('visible', width=92, minwidth=86, anchor='center', stretch=False)
        self.tree.column('eyebrow', width=160, minwidth=130, anchor='w', stretch=False)
        self.tree.column('title', width=250, minwidth=180, anchor='w', stretch=False)
        self.tree.column('text', width=560, minwidth=360, anchor='w', stretch=True)
        self.tree.grid(row=0, column=0, sticky='nsew')
        tree_y = ttk.Scrollbar(tree_wrap, orient='vertical', command=self.tree.yview)
        tree_y.grid(row=0, column=1, sticky='ns')
        tree_x = ttk.Scrollbar(tree_wrap, orient='horizontal', command=self.tree.xview)
        tree_x.grid(row=1, column=0, sticky='ew', pady=(6, 0))
        tree_wrap.rowconfigure(0, weight=1)
        tree_wrap.columnconfigure(0, weight=1)
        self.tree.configure(yscrollcommand=tree_y.set, xscrollcommand=tree_x.set)
        _style_tree_widget(self.tree)
        self.tree.bind('<<TreeviewSelect>>', lambda _e: self._on_select())
        self.tree.bind('<Double-1>', lambda _e: self._edit())
        self.tree.bind('<Delete>', lambda _e: self._remove())
        self.tree.bind('<Return>', lambda _e: self._edit())

        right = ttk.Labelframe(split, text='Selected card inspector', padding=10)
        split.add(right, weight=2)
        ttk.Label(right, textvariable=self.preview_title_var, style='SectionTitle.TLabel').pack(anchor='w')
        ttk.Label(right, textvariable=self.preview_meta_var, style='PanelSub.TLabel', justify='left', wraplength=360).pack(anchor='w', fill='x', pady=(6, 8))
        self.preview_text = tk.Text(right, wrap='word', height=12)
        _style_text_widget(self.preview_text, rows=12)
        self.preview_text.pack(fill='both', expand=True)
        self.preview_text.configure(state='disabled', cursor='arrow')
        inspector_actions = ttk.Frame(right, style='Card.TFrame')
        inspector_actions.pack(fill='x', pady=(10, 0))
        self.inspect_edit_button = ttk.Button(inspector_actions, text='Edit selected', command=self._edit, style='Accent.TButton')
        self.inspect_edit_button.pack(side='left')
        self.toggle_button = ttk.Button(inspector_actions, text='Toggle visibility', command=self._toggle_visible)
        self.toggle_button.pack(side='left', padx=(8, 0))
        self.inspect_duplicate_button = ttk.Button(inspector_actions, text='Duplicate', command=self._duplicate)
        self.inspect_duplicate_button.pack(side='left', padx=(8, 0))

        controls = ttk.Frame(shell, style='Card.TFrame')
        controls.pack(fill='x', pady=(12, 0))
        primary = ttk.Frame(controls, style='Card.TFrame')
        primary.pack(side='left')
        self.add_button = ttk.Button(primary, text='Add card', command=self._add, style='Accent.TButton')
        self.add_button.pack(side='left')
        self.edit_button = ttk.Button(primary, text='Edit', command=self._edit)
        self.edit_button.pack(side='left', padx=(8, 0))
        self.duplicate_button = ttk.Button(primary, text='Duplicate', command=self._duplicate)
        self.duplicate_button.pack(side='left', padx=(8, 0))
        self.remove_button = ttk.Button(primary, text='Remove', command=self._remove)
        self.remove_button.pack(side='left', padx=(8, 0))
        secondary = ttk.Frame(controls, style='Card.TFrame')
        secondary.pack(side='right')
        self.move_up_button = ttk.Button(secondary, text='Move up', command=lambda: self._move(-1))
        self.move_up_button.pack(side='left')
        self.move_down_button = ttk.Button(secondary, text='Move down', command=lambda: self._move(1))
        self.move_down_button.pack(side='left', padx=(8, 0))

        self._update_dashboard()

    def _notify_change(self) -> None:
        _emit_change(self.on_change)

    def _selected_index(self) -> int | None:
        if not self.tree:
            return None
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _summary(self, idx: int, item: dict[str, Any]) -> tuple[str, str, str, str, str]:
        text = ' '.join(str(item.get('text') or '').strip().split())
        if len(text) > 110:
            text = text[:107] + '...'
        return (
            str(idx + 1),
            'Visible' if bool(item.get('visible', True)) else 'Hidden',
            str(item.get('eyebrow') or '').strip() or '—',
            str(item.get('title') or '').strip() or 'Untitled',
            text or '—',
        )

    def _set_preview_text(self, value: str) -> None:
        if not self.preview_text:
            return
        self.preview_text.configure(state='normal')
        self.preview_text.delete('1.0', 'end')
        self.preview_text.insert('1.0', value)
        self.preview_text.configure(state='disabled')

    def _update_action_state(self) -> None:
        idx = self._selected_index()
        has_selection = idx is not None and 0 <= idx < len(self.items)
        _set_button_state(self.edit_button, has_selection)
        _set_button_state(self.remove_button, has_selection)
        _set_button_state(self.duplicate_button, has_selection)
        _set_button_state(self.toggle_button, has_selection)
        _set_button_state(self.inspect_edit_button, has_selection)
        _set_button_state(self.inspect_duplicate_button, has_selection)
        _set_button_state(self.move_up_button, has_selection and idx not in (None, 0))
        _set_button_state(self.move_down_button, has_selection and idx is not None and idx < len(self.items) - 1)

    def _update_dashboard(self) -> None:
        total = len(self.items)
        visible = sum(1 for item in self.items if bool(item.get('visible', True)))
        hidden = total - visible
        if total:
            self.summary_var.set(f'{total} cards  •  {visible} visible  •  {hidden} hidden')
        else:
            self.summary_var.set('No cards yet')
        idx = self._selected_index()
        if idx is None or idx >= len(self.items):
            self.selection_var.set('Nothing selected')
            self.preview_title_var.set('Select a card')
            self.preview_meta_var.set('Use the list to inspect, edit, reorder, or hide content blocks.')
            self.status_var.set('Ready for a new card')
            self._set_preview_text('Choose a card from the table to read the full copy and check its visibility state before editing.')
            self._update_action_state()
            return
        item = self.items[idx]
        state = 'Visible' if bool(item.get('visible', True)) else 'Hidden'
        title = str(item.get('title') or '').strip() or 'Untitled'
        eyebrow = str(item.get('eyebrow') or '').strip() or 'No eyebrow'
        body = str(item.get('text') or '').strip()
        body_lines = max(1, body.count('\n') + 1) if body else 0
        body_words = _word_count(body)
        self.selection_var.set(f'Card {idx + 1} of {len(self.items)}')
        self.preview_title_var.set(title)
        self.preview_meta_var.set(f'{state} • {eyebrow} • {body_words} words across {body_lines} line(s).')
        self.status_var.set('Ready to edit, reorder, duplicate, or hide')
        self._set_preview_text(body or 'No body text.')
        self._update_action_state()

    def _refresh(self, *, preserve_selection: int | None = None) -> None:
        if not self.tree:
            return
        current_idx = self._selected_index() if preserve_selection is None else preserve_selection
        for row in self.tree.get_children():
            self.tree.delete(row)
        for idx, item in enumerate(self.items):
            tone_tags = ['active' if bool(item.get('visible', True)) else 'hidden', 'even' if idx % 2 == 0 else 'odd']
            self.tree.insert('', 'end', iid=str(idx), values=self._summary(idx, item), tags=tuple(tone_tags))
        if current_idx is not None and 0 <= current_idx < len(self.items):
            self.tree.selection_set(str(current_idx))
            self.tree.focus(str(current_idx))
            self.tree.see(str(current_idx))
        self._update_dashboard()

    def _prompt(self, initial: dict[str, Any] | None = None) -> dict[str, Any] | None:
        payload = dict(initial or {})
        dialog = tk.Toplevel(self)
        dialog.title('Card editor')
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        dialog.resizable(True, True)
        dialog.geometry('760x560')
        dialog.minsize(640, 500)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        pal = _palette(self)
        dialog.configure(bg=pal['bg'])

        shell = ttk.Frame(dialog, padding=14, style='Card.TFrame')
        shell.grid(row=0, column=0, sticky='nsew')
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)

        header = ttk.Frame(shell, style='Card.TFrame')
        header.grid(row=0, column=0, sticky='ew')
        ttk.Label(header, text='Card editor', style='HeroTitle.TLabel').pack(anchor='w')
        ttk.Label(header, text='Keep the table compact and move the detail into the card body. Use the title and eyebrow for fast scanning.', style='PanelSub.TLabel', justify='left', wraplength=680).pack(anchor='w', pady=(4, 0))

        body = ttk.Frame(shell, style='Card.TFrame')
        body.grid(row=1, column=0, sticky='nsew', pady=(12, 0))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)

        eyebrow_var = tk.StringVar(value=str(payload.get('eyebrow') or ''))
        title_var = tk.StringVar(value=str(payload.get('title') or ''))
        visible_var = tk.BooleanVar(value=bool(payload.get('visible', True)))
        count_var = tk.StringVar(value='0 words')

        top_grid = ttk.Frame(body, style='Card.TFrame')
        top_grid.grid(row=0, column=0, sticky='ew')
        top_grid.columnconfigure(0, weight=1)
        top_grid.columnconfigure(1, weight=1)

        eyebrow_box = ttk.Frame(top_grid, style='Card.TFrame')
        eyebrow_box.grid(row=0, column=0, sticky='ew', padx=(0, 8))
        ttk.Label(eyebrow_box, text='Eyebrow', style='SectionTitle.TLabel').pack(anchor='w')
        ttk.Entry(eyebrow_box, textvariable=eyebrow_var).pack(fill='x', pady=(4, 0))
        ttk.Label(eyebrow_box, text='Small context label for quick scanning in the control panel and on the public page.', style='PanelSub.TLabel', wraplength=320, justify='left').pack(anchor='w', pady=(4, 0))

        title_box = ttk.Frame(top_grid, style='Card.TFrame')
        title_box.grid(row=0, column=1, sticky='ew', padx=(8, 0))
        ttk.Label(title_box, text='Title', style='SectionTitle.TLabel').pack(anchor='w')
        ttk.Entry(title_box, textvariable=title_var).pack(fill='x', pady=(4, 0))
        ttk.Label(title_box, text='This is the primary scan target. Keep it clear and specific.', style='PanelSub.TLabel', wraplength=320, justify='left').pack(anchor='w', pady=(4, 0))

        visible_row = ttk.Frame(body, style='Card.TFrame')
        visible_row.grid(row=1, column=0, sticky='ew', pady=(12, 0))
        ttk.Checkbutton(visible_row, text='Visible on the public page', variable=visible_var).pack(side='left')
        ttk.Label(visible_row, text='Hidden cards stay editable here but are excluded from the public page.', style='PanelSub.TLabel').pack(side='left', padx=(12, 0))
        ttk.Label(visible_row, textvariable=count_var, style='Pill.TLabel').pack(side='right')

        body_box = ttk.Frame(body, style='Card.TFrame')
        body_box.grid(row=2, column=0, sticky='nsew', pady=(12, 0))
        body_box.columnconfigure(0, weight=1)
        body_box.rowconfigure(1, weight=1)
        ttk.Label(body_box, text='Body copy', style='SectionTitle.TLabel').grid(row=0, column=0, sticky='w')
        text_widget = tk.Text(body_box, wrap='word', undo=True)
        _style_text_widget(text_widget, rows=14)
        text_widget.grid(row=1, column=0, sticky='nsew', pady=(4, 0))
        text_widget.insert('1.0', str(payload.get('text') or ''))
        ttk.Label(body_box, text='Write for clarity first. The table shows only an excerpt, so use this area to verify rhythm, line breaks, and the full sense of the card.', style='PanelSub.TLabel', justify='left', wraplength=680).grid(row=2, column=0, sticky='w', pady=(6, 0))

        error_var = tk.StringVar(value='')
        error_label = ttk.Label(shell, textvariable=error_var, foreground=pal['danger'], background=pal['panel'])
        error_label.grid(row=2, column=0, sticky='w', pady=(12, 0))

        result: dict[str, Any] | None = None

        def update_count(_event: object | None = None) -> None:
            text_value = text_widget.get('1.0', 'end').strip()
            words = _word_count(text_value)
            lines = max(1, text_value.count('\n') + 1) if text_value else 0
            count_var.set(f'{words} words • {lines} lines')

        def submit() -> None:
            nonlocal result
            title = title_var.get().strip()
            text_value = text_widget.get('1.0', 'end').strip()
            if not title:
                error_var.set('Title is required.')
                return
            if not text_value:
                error_var.set('Body text is required.')
                return
            result = {
                'eyebrow': eyebrow_var.get().strip(),
                'title': title,
                'text': text_value,
                'visible': bool(visible_var.get()),
            }
            dialog.destroy()

        text_widget.bind('<KeyRelease>', update_count, add='+')
        update_count()

        actions = ttk.Frame(shell, style='Card.TFrame')
        actions.grid(row=3, column=0, sticky='e', pady=(12, 0))
        ttk.Button(actions, text='Cancel', command=dialog.destroy).pack(side='left')
        ttk.Button(actions, text='Save card', command=submit, style='Accent.TButton').pack(side='left', padx=(8, 0))
        dialog.wait_window()
        return result

    def _on_select(self) -> None:
        self._update_dashboard()

    def _add(self) -> None:
        payload = self._prompt()
        if payload:
            self.items.append(payload)
            self._refresh(preserve_selection=len(self.items) - 1)
            self._notify_change()

    def _edit(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        payload = self._prompt(self.items[idx])
        if payload:
            self.items[idx] = payload
            self._refresh(preserve_selection=idx)
            self._notify_change()

    def _duplicate(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        clone = dict(self.items[idx])
        clone['title'] = f"{str(clone.get('title') or '').strip()} copy".strip()
        self.items.insert(idx + 1, clone)
        self._refresh(preserve_selection=idx + 1)
        self._notify_change()

    def _remove(self) -> None:
        idx = self._selected_index()
        if idx is not None:
            self.items.pop(idx)
            next_idx = min(idx, len(self.items) - 1) if self.items else None
            self._refresh(preserve_selection=next_idx)
            self._notify_change()

    def _toggle_visible(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        self.items[idx]['visible'] = not bool(self.items[idx].get('visible', True))
        self._refresh(preserve_selection=idx)
        self._notify_change()

    def _move(self, direction: int) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self.items):
            return
        self.items.insert(new_idx, self.items.pop(idx))
        self._refresh(preserve_selection=new_idx)
        self._notify_change()

    def get_items(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.items]

    def set_items(self, items: list[dict[str, Any]]) -> None:
        self.items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            self.items.append({
                'eyebrow': str(item.get('eyebrow') or '').strip(),
                'title': str(item.get('title') or '').strip(),
                'text': str(item.get('text') or '').strip(),
                'visible': item.get('visible', True) is not False,
            })
        self._refresh(preserve_selection=0 if self.items else None)

class BoundEntryRow(ttk.Frame):
    def __init__(self, master: tk.Misc, *, label: str, textvariable: tk.StringVar, help_text: str = '', width: int = 48) -> None:
        super().__init__(master, style='Card.TFrame', padding=0)
        self.error_var = tk.StringVar(value='')
        top = ttk.Frame(self, style='Card.TFrame')
        top.pack(fill='x')
        ttk.Label(top, text=label, style='SectionTitle.TLabel').pack(side='left', anchor='w')
        ttk.Label(top, textvariable=self.error_var, foreground='#b42318', background=_palette(self)['panel']).pack(side='right', anchor='e')
        ttk.Entry(self, textvariable=textvariable, width=width).pack(fill='x', pady=(4, 0))
        if help_text:
            ttk.Label(self, text=help_text, style='PanelSub.TLabel', justify='left', wraplength=720).pack(anchor='w', pady=(4, 0))

    def set_error(self, message: str = '') -> None:
        self.error_var.set(message)

class BoundTextRow(ttk.Frame):
    def __init__(self, master: tk.Misc, *, label: str, help_text: str = '', rows: int = 6, placeholder: str = '', on_change: Callable[[], None] | None = None) -> None:
        super().__init__(master, style='Card.TFrame', padding=0)
        self.placeholder = placeholder
        self.on_change = on_change
        self.error_var = tk.StringVar(value='')
        self.meta_var = tk.StringVar(value='0 words')
        top = ttk.Frame(self, style='Card.TFrame')
        top.pack(fill='x')
        ttk.Label(top, text=label, style='SectionTitle.TLabel').pack(side='left', anchor='w')
        ttk.Label(top, textvariable=self.meta_var, style='Pill.TLabel').pack(side='right')
        self.text = tk.Text(self, wrap='word')
        _style_text_widget(self.text, rows=rows)
        self.text.pack(fill='both', expand=True, pady=(4, 0))
        if help_text:
            ttk.Label(self, text=help_text, style='PanelSub.TLabel', justify='left', wraplength=720).pack(anchor='w', pady=(4, 0))
        ttk.Label(self, textvariable=self.error_var, foreground='#b42318', background=_palette(self)['panel']).pack(anchor='w')
        if placeholder:
            self.text.insert('1.0', placeholder)
            self.text.bind('<FocusIn>', self._clear_placeholder, add='+')
        self.text.bind('<KeyRelease>', self._on_text_changed, add='+')
        self.text.bind('<FocusOut>', self._on_text_changed, add='+')
        self._update_meta()

    def _on_text_changed(self, _event: object | None = None) -> None:
        self._update_meta()
        _emit_change(self.on_change)

    def _update_meta(self, _event: object | None = None) -> None:
        value = self.get_value()
        words = _word_count(value)
        self.meta_var.set(f'{words} words')

    def _clear_placeholder(self, _event: object | None = None) -> None:
        if self.placeholder and self.get_value().strip() == self.placeholder:
            self.text.delete('1.0', 'end')
            self._update_meta()

    def get_value(self) -> str:
        return self.text.get('1.0', 'end').strip()

    def set_value(self, value: str) -> None:
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', value or '')
        self._update_meta()

    def set_error(self, message: str = '') -> None:
        self.error_var.set(message)

class TokenEditor(ttk.Frame):
    def __init__(self, master: tk.Misc, *, label: str, help_text: str = '') -> None:
        super().__init__(master, style='Card.TFrame', padding=0)
        ttk.Label(self, text=label, style='SectionTitle.TLabel').pack(anchor='w')
        wrap = ttk.Frame(self, style='Card.TFrame')
        wrap.pack(fill='both', expand=True, pady=(4, 0))
        self.listbox = tk.Listbox(wrap, exportselection=False)
        _style_listbox_widget(self.listbox, height=5)
        self.listbox.grid(row=0, column=0, sticky='nsew')
        ybar = ttk.Scrollbar(wrap, orient='vertical', command=self.listbox.yview)
        ybar.grid(row=0, column=1, sticky='ns')
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.listbox.configure(yscrollcommand=ybar.set)
        controls = ttk.Frame(self, style='Card.TFrame')
        controls.pack(fill='x', pady=(6, 0))
        ttk.Button(controls, text='Add', command=self._add).pack(side='left')
        ttk.Button(controls, text='Remove', command=self._remove).pack(side='left', padx=(8, 0))
        if help_text:
            ttk.Label(self, text=help_text, style='PanelSub.TLabel', justify='left', wraplength=720).pack(anchor='w', pady=(4, 0))

    def _add(self) -> None:
        value = simpledialog.askstring('Add item', 'Value:')
        if value and value.strip():
            self.listbox.insert('end', value.strip())

    def _remove(self) -> None:
        sel = self.listbox.curselection()
        if sel:
            self.listbox.delete(sel[0])

    def get_items(self) -> list[str]:
        return [str(self.listbox.get(i)).strip() for i in range(self.listbox.size()) if str(self.listbox.get(i)).strip()]

    def set_items(self, items: list[str]) -> None:
        self.listbox.delete(0, 'end')
        for item in items:
            if str(item).strip():
                self.listbox.insert('end', str(item).strip())


class ActionListEditor(ttk.Frame):
    def __init__(self, master: tk.Misc, *, label: str, on_change: Callable[[], None] | None = None) -> None:
        super().__init__(master, style='Card.TFrame', padding=0)
        self.on_change = on_change
        ttk.Label(self, text=label, style='SectionTitle.TLabel').pack(anchor='w')
        self.listbox = tk.Listbox(self, exportselection=False)
        _style_listbox_widget(self.listbox, height=5)
        self.listbox.pack(fill='both', expand=True, pady=(4, 0))
        self.items: list[dict[str, str]] = []
        self.listbox.bind('<<ListboxSelect>>', lambda _e: self._update_action_state())
        self.listbox.bind('<Double-Button-1>', lambda _e: self._edit())
        controls = ttk.Frame(self, style='Card.TFrame')
        controls.pack(fill='x', pady=(6, 0))
        self.add_button = ttk.Button(controls, text='Add', command=self._add)
        self.add_button.pack(side='left')
        self.edit_button = ttk.Button(controls, text='Edit', command=self._edit)
        self.edit_button.pack(side='left', padx=(8, 0))
        self.remove_button = ttk.Button(controls, text='Remove', command=self._remove)
        self.remove_button.pack(side='left', padx=(8, 0))
        self._update_action_state()

    def _notify_change(self) -> None:
        _emit_change(self.on_change)

    def _update_action_state(self) -> None:
        has_selection = bool(self.listbox.curselection())
        _set_button_state(self.edit_button, has_selection)
        _set_button_state(self.remove_button, has_selection)

    def _refresh(self) -> None:
        self.listbox.delete(0, 'end')
        for item in self.items:
            self.listbox.insert('end', f"{item.get('label', '')} → {item.get('href', '')} [{item.get('style', 'primary')}]")
        self._update_action_state()

    def _prompt(self, existing: dict[str, str] | None = None) -> dict[str, str] | None:
        base = dict(existing or {})
        label = simpledialog.askstring('Action label', 'Label:', initialvalue=base.get('label', ''))
        if label is None:
            return None
        href = simpledialog.askstring('Action href', 'Target href:', initialvalue=base.get('href', ''))
        if href is None:
            return None
        style = simpledialog.askstring('Action style', 'Style:', initialvalue=base.get('style', 'primary'))
        if style is None:
            return None
        return {'label': label.strip(), 'href': href.strip(), 'style': style.strip() or 'primary'}

    def _add(self) -> None:
        item = self._prompt()
        if item:
            self.items.append(item)
            self._refresh()
            self.listbox.selection_clear(0, 'end')
            self.listbox.selection_set(len(self.items) - 1)
            self._notify_change()

    def _edit(self) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        item = self._prompt(self.items[sel[0]])
        if item:
            self.items[sel[0]] = item
            self._refresh()
            self.listbox.selection_set(sel[0])
            self._notify_change()

    def _remove(self) -> None:
        sel = self.listbox.curselection()
        if sel:
            self.items.pop(sel[0])
            next_idx = min(sel[0], len(self.items) - 1) if self.items else None
            self._refresh()
            if next_idx is not None:
                self.listbox.selection_set(next_idx)
            self._notify_change()

    def get_items(self) -> list[dict[str, str]]:
        return [dict(item) for item in self.items if item.get('label') and item.get('href')]

    def set_items(self, items: list[dict[str, str]]) -> None:
        self.items = [dict(item) for item in items if isinstance(item, dict)]
        self._refresh()

class OrderedStringListEditor(ttk.Frame):
    def __init__(self, master: tk.Misc, *, label: str, item_label: str, on_change: Callable[[], None] | None = None) -> None:
        super().__init__(master, style='Card.TFrame', padding=0)
        self.item_label = item_label
        self.on_change = on_change
        self.summary_var = tk.StringVar(value='No items yet')
        self.selection_var = tk.StringVar(value='Nothing selected')
        self.helper_var = tk.StringVar(value='Use order to control narrative rhythm and save scanning effort later.')
        header = ttk.Frame(self, style='Card.TFrame')
        header.pack(fill='x')
        title_box = ttk.Frame(header, style='Card.TFrame')
        title_box.pack(side='left', fill='x', expand=True)
        ttk.Label(title_box, text=label, style='SectionTitle.TLabel').pack(anchor='w')
        ttk.Label(title_box, textvariable=self.helper_var, style='PanelSub.TLabel', justify='left', wraplength=620).pack(anchor='w', pady=(2, 0))
        meta_box = ttk.Frame(header, style='Card.TFrame')
        meta_box.pack(side='right', anchor='ne')
        ttk.Label(meta_box, textvariable=self.summary_var, style='StatusInfo.TLabel').pack(anchor='e')
        ttk.Label(meta_box, textvariable=self.selection_var, style='Pill.TLabel').pack(anchor='e', pady=(6, 0))

        self.listbox = tk.Listbox(self, exportselection=False)
        _style_listbox_widget(self.listbox, height=7)
        self.listbox.pack(fill='both', expand=True, pady=(8, 0))
        self.listbox.bind('<<ListboxSelect>>', lambda _e: self._update_action_state())
        self.listbox.bind('<Double-Button-1>', lambda _e: self._edit())
        self.listbox.bind('<Delete>', lambda _e: self._remove())

        self.preview = tk.Text(self, wrap='word', height=3)
        _style_text_widget(self.preview, readonly=False, rows=3)
        self.preview.pack(fill='x', pady=(8, 0))
        self.preview.configure(state='disabled', cursor='arrow')

        controls = ttk.Frame(self, style='Card.TFrame')
        controls.pack(fill='x', pady=(8, 0))
        primary = ttk.Frame(controls, style='Card.TFrame')
        primary.pack(side='left')
        self.add_button = ttk.Button(primary, text='Add', command=self._add)
        self.add_button.pack(side='left')
        self.edit_button = ttk.Button(primary, text='Edit', command=self._edit)
        self.edit_button.pack(side='left', padx=(8, 0))
        self.remove_button = ttk.Button(primary, text='Remove', command=self._remove)
        self.remove_button.pack(side='left', padx=(8, 0))
        secondary = ttk.Frame(controls, style='Card.TFrame')
        secondary.pack(side='right')
        self.move_up_button = ttk.Button(secondary, text='Move up', command=lambda: self._move(-1))
        self.move_up_button.pack(side='left')
        self.move_down_button = ttk.Button(secondary, text='Move down', command=lambda: self._move(1))
        self.move_down_button.pack(side='left', padx=(8, 0))
        self._update_action_state()

    def _notify_change(self) -> None:
        _emit_change(self.on_change)

    def _selected_index(self) -> int | None:
        sel = self.listbox.curselection()
        return sel[0] if sel else None

    def _set_preview(self, value: str) -> None:
        self.preview.configure(state='normal')
        self.preview.delete('1.0', 'end')
        self.preview.insert('1.0', value)
        self.preview.configure(state='disabled')

    def _update_action_state(self) -> None:
        idx = self._selected_index()
        count = self.listbox.size()
        has_selection = idx is not None
        _set_button_state(self.edit_button, has_selection)
        _set_button_state(self.remove_button, has_selection)
        _set_button_state(self.move_up_button, has_selection and idx not in (None, 0))
        _set_button_state(self.move_down_button, has_selection and idx is not None and idx < count - 1)
        self.summary_var.set(f'{count} {self.item_label.lower()}' + ('s' if count != 1 else '') + (' in order' if count else ''))
        if not count:
            self.summary_var.set('No items yet')
            self.selection_var.set('Nothing selected')
            self.helper_var.set('Use order to control narrative rhythm and save scanning effort later.')
            self._set_preview(f'Add {self.item_label.lower()}s to build sequence and rhythm.')
            return
        if idx is None:
            self.selection_var.set('Select an item')
            self.helper_var.set('Double-click to edit, Delete to remove, or use move controls to pace the sequence.')
            self._set_preview('Choose an item to inspect the full text instead of guessing from the list.')
            return
        value = str(self.listbox.get(idx)).strip()
        words = _word_count(value)
        self.selection_var.set(f'{self.item_label} {idx + 1} of {count}')
        self.helper_var.set(f'{words} words. Keep stronger lines earlier if they set the page tone.')
        self._set_preview(value or f'Empty {self.item_label.lower()}.')

    def _add(self) -> None:
        value = simpledialog.askstring(f'Add {self.item_label}', f'{self.item_label}:')
        if value and value.strip():
            self.listbox.insert('end', value.strip())
            self.listbox.selection_clear(0, 'end')
            self.listbox.selection_set(self.listbox.size() - 1)
            self._update_action_state()
            self._notify_change()

    def _edit(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        current = str(self.listbox.get(idx))
        value = simpledialog.askstring(f'Edit {self.item_label}', f'{self.item_label}:', initialvalue=current)
        if value and value.strip():
            self.listbox.delete(idx)
            self.listbox.insert(idx, value.strip())
            self.listbox.selection_set(idx)
            self._update_action_state()
            self._notify_change()

    def _remove(self) -> None:
        idx = self._selected_index()
        if idx is not None:
            self.listbox.delete(idx)
            next_idx = min(idx, self.listbox.size() - 1) if self.listbox.size() else None
            if next_idx is not None:
                self.listbox.selection_set(next_idx)
            self._update_action_state()
            self._notify_change()

    def _move(self, direction: int) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= self.listbox.size():
            return
        value = self.listbox.get(idx)
        self.listbox.delete(idx)
        self.listbox.insert(new_idx, value)
        self.listbox.selection_set(new_idx)
        self._update_action_state()
        self._notify_change()

    def get_items(self) -> list[str]:
        return [str(self.listbox.get(i)).strip() for i in range(self.listbox.size()) if str(self.listbox.get(i)).strip()]

    def set_items(self, items: list[str]) -> None:
        self.listbox.delete(0, 'end')
        for item in items:
            self.listbox.insert('end', item)
        if self.listbox.size():
            self.listbox.selection_set(0)
        self._update_action_state()

class OrderedRecordListEditor(ttk.Frame):
    def __init__(self, master: tk.Misc, *, label: str, columns: tuple[str, ...], on_change: Callable[[], None] | None = None) -> None:
        super().__init__(master, style='Card.TFrame', padding=0)
        self.columns = columns
        self.items: list[dict[str, Any]] = []
        self.on_change = on_change
        self.summary_var = tk.StringVar(value='No rows')
        self.selection_var = tk.StringVar(value='Nothing selected')
        self.preview_var = tk.StringVar(value='Select a row to inspect details.')

        header = ttk.Frame(self, style='Card.TFrame')
        header.pack(fill='x')
        left = ttk.Frame(header, style='Card.TFrame')
        left.pack(side='left', fill='x', expand=True)
        ttk.Label(left, text=label, style='SectionTitle.TLabel').pack(anchor='w')
        ttk.Label(left, textvariable=self.preview_var, style='PanelSub.TLabel', justify='left', wraplength=620).pack(anchor='w', pady=(2, 0))
        meta = ttk.Frame(header, style='Card.TFrame')
        meta.pack(side='right', anchor='ne')
        ttk.Label(meta, textvariable=self.summary_var, style='StatusInfo.TLabel').pack(anchor='e')
        ttk.Label(meta, textvariable=self.selection_var, style='Pill.TLabel').pack(anchor='e', pady=(6, 0))

        wrap = ttk.Frame(self, style='Card.TFrame')
        wrap.pack(fill='both', expand=True, pady=(8, 0))
        self.tree = ttk.Treeview(wrap, columns=columns, show='headings', height=7)
        for column in columns:
            self.tree.heading(column, text=column.title())
            self.tree.column(column, width=180, anchor='w')
        self.tree.grid(row=0, column=0, sticky='nsew')
        ybar = ttk.Scrollbar(wrap, orient='vertical', command=self.tree.yview)
        ybar.grid(row=0, column=1, sticky='ns')
        xbar = ttk.Scrollbar(wrap, orient='horizontal', command=self.tree.xview)
        xbar.grid(row=1, column=0, sticky='ew', pady=(6, 0))
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        _style_tree_widget(self.tree)
        self.tree.bind('<<TreeviewSelect>>', lambda _e: self._update_action_state())
        self.tree.bind('<Double-1>', lambda _e: self._edit())

        controls = ttk.Frame(self, style='Card.TFrame')
        controls.pack(fill='x', pady=(8, 0))
        self.add_button = ttk.Button(controls, text='Add', command=self._add)
        self.add_button.pack(side='left')
        self.edit_button = ttk.Button(controls, text='Edit', command=self._edit)
        self.edit_button.pack(side='left', padx=(8, 0))
        self.remove_button = ttk.Button(controls, text='Remove', command=self._remove)
        self.remove_button.pack(side='left', padx=(8, 0))
        self.move_up_button = ttk.Button(controls, text='Move up', command=lambda: self._move(-1))
        self.move_up_button.pack(side='right')
        self.move_down_button = ttk.Button(controls, text='Move down', command=lambda: self._move(1))
        self.move_down_button.pack(side='right', padx=(8, 0))
        self._update_action_state()

    def _notify_change(self) -> None:
        _emit_change(self.on_change)

    def _selected_index(self) -> int | None:
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _update_summary(self) -> None:
        count = len(self.items)
        self.summary_var.set(f'{count} row' + ('s' if count != 1 else '') + (' in order' if count else ''))
        if not count:
            self.summary_var.set('No rows')

    def _update_action_state(self) -> None:
        idx = self._selected_index()
        has_selection = idx is not None and idx < len(self.items)
        _set_button_state(self.edit_button, has_selection)
        _set_button_state(self.remove_button, has_selection)
        _set_button_state(self.move_up_button, has_selection and idx not in (None, 0))
        _set_button_state(self.move_down_button, has_selection and idx is not None and idx < len(self.items) - 1)
        self._update_summary()
        if not has_selection:
            self.selection_var.set('Nothing selected' if not self.items else 'Select a row')
            self.preview_var.set('Use the table to compare entries, then inspect the selected row before editing it.')
            return
        item = self.items[idx]
        self.selection_var.set(f'Row {idx + 1} of {len(self.items)}')
        non_empty = [f"{column}: {str(item.get(column) or '').strip() or '—'}" for column in self.columns]
        self.preview_var.set('  •  '.join(non_empty))

    def _refresh(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)
        for idx, item in enumerate(self.items):
            tags = ('odd',) if idx % 2 else ('even',)
            self.tree.insert('', 'end', iid=str(idx), values=[item.get(col, '') for col in self.columns], tags=tags)
        self._update_action_state()

    def _prompt(self, initial: dict[str, Any] | None = None) -> dict[str, Any] | None:
        payload = dict(initial or {})
        for column in self.columns:
            value = simpledialog.askstring(f'{column.title()}', f'{column.title()}:', initialvalue=str(payload.get(column, '')))
            if value is None:
                return None
            payload[column] = value.strip()
        return payload

    def _add(self) -> None:
        payload = self._prompt()
        if payload:
            self.items.append(payload)
            self._refresh()
            self.tree.selection_set(str(len(self.items) - 1))
            self._update_action_state()
            self._notify_change()

    def _edit(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        payload = self._prompt(self.items[idx])
        if payload:
            self.items[idx] = payload
            self._refresh()
            self.tree.selection_set(str(idx))
            self._update_action_state()
            self._notify_change()

    def _remove(self) -> None:
        idx = self._selected_index()
        if idx is not None:
            self.items.pop(idx)
            self._refresh()
            next_idx = min(idx, len(self.items) - 1) if self.items else None
            if next_idx is not None:
                self.tree.selection_set(str(next_idx))
            self._update_action_state()
            self._notify_change()

    def _move(self, direction: int) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self.items):
            return
        self.items.insert(new_idx, self.items.pop(idx))
        self._refresh()
        self.tree.selection_set(str(new_idx))
        self._update_action_state()
        self._notify_change()

    def get_items(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.items]

    def set_items(self, items: list[dict[str, Any]]) -> None:
        self.items = [dict(item) for item in items]
        self._refresh()
        if self.items:
            self.tree.selection_set('0')
            self._update_action_state()

class OrderedPickerEditor(ttk.Frame):
    def __init__(self, master: tk.Misc, *, label: str, source_label: str, on_change: Callable[[], None] | None = None) -> None:
        super().__init__(master, style='Card.TFrame', padding=0)
        self.choice_map: dict[str, str] = {}
        self.on_change = on_change
        self.summary_var = tk.StringVar(value='Nothing selected yet')
        self.selection_var = tk.StringVar(value='No focused item')
        self.detail_var = tk.StringVar(value='Move items from left to right to define the public output order.')

        header = ttk.Frame(self, style='Card.TFrame')
        header.pack(fill='x')
        left_head = ttk.Frame(header, style='Card.TFrame')
        left_head.pack(side='left', fill='x', expand=True)
        ttk.Label(left_head, text=label, style='SectionTitle.TLabel').pack(anchor='w')
        ttk.Label(left_head, textvariable=self.detail_var, style='PanelSub.TLabel', justify='left', wraplength=640).pack(anchor='w', pady=(2, 0))
        right_head = ttk.Frame(header, style='Card.TFrame')
        right_head.pack(side='right', anchor='ne')
        ttk.Label(right_head, textvariable=self.summary_var, style='StatusInfo.TLabel').pack(anchor='e')
        ttk.Label(right_head, textvariable=self.selection_var, style='Pill.TLabel').pack(anchor='e', pady=(6, 0))

        wrap = ttk.Frame(self, style='Card.TFrame')
        wrap.pack(fill='both', expand=True, pady=(8, 0))
        self.available = tk.Listbox(wrap, exportselection=False)
        self.selected = tk.Listbox(wrap, exportselection=False)
        _style_listbox_widget(self.available, height=7)
        _style_listbox_widget(self.selected, height=7)
        left = ttk.Frame(wrap, style='Card.TFrame')
        left.pack(side='left', fill='both', expand=True)
        ttk.Label(left, text=f'Available {source_label}', style='PanelSub.TLabel').pack(anchor='w')
        self.available.pack(in_=left, fill='both', expand=True, pady=(4, 0))
        mid = ttk.Frame(wrap, style='Card.TFrame')
        mid.pack(side='left', fill='y', padx=10)
        self.add_button = ttk.Button(mid, text='Add →', command=self._add)
        self.add_button.pack(pady=(18, 8), fill='x')
        self.remove_button = ttk.Button(mid, text='← Remove', command=self._remove)
        self.remove_button.pack(fill='x')
        ttk.Separator(mid).pack(fill='x', pady=10)
        self.move_up_button = ttk.Button(mid, text='Move up', command=lambda: self._move(-1))
        self.move_up_button.pack(fill='x')
        self.move_down_button = ttk.Button(mid, text='Move down', command=lambda: self._move(1))
        self.move_down_button.pack(fill='x', pady=(8, 0))
        right = ttk.Frame(wrap, style='Card.TFrame')
        right.pack(side='left', fill='both', expand=True)
        ttk.Label(right, text='Selected order', style='PanelSub.TLabel').pack(anchor='w')
        self.selected.pack(in_=right, fill='both', expand=True, pady=(4, 0))
        self.available.bind('<<ListboxSelect>>', lambda _e: self._update_action_state())
        self.selected.bind('<<ListboxSelect>>', lambda _e: self._update_action_state())
        self.available.bind('<Double-Button-1>', lambda _e: self._add())
        self.selected.bind('<Double-Button-1>', lambda _e: self._remove())
        self._update_action_state()

    def _notify_change(self) -> None:
        _emit_change(self.on_change)

    def _parse_value(self, text: str) -> str:
        if text.endswith(']') and '[' in text:
            return text.rsplit('[', 1)[-1].rstrip(']').strip()
        return text.strip()

    def _update_action_state(self) -> None:
        available_sel = self.available.curselection()
        selected_sel = self.selected.curselection()
        idx = selected_sel[0] if selected_sel else None
        _set_button_state(self.add_button, bool(available_sel))
        _set_button_state(self.remove_button, bool(selected_sel))
        _set_button_state(self.move_up_button, bool(selected_sel) and idx not in (None, 0))
        _set_button_state(self.move_down_button, bool(selected_sel) and idx is not None and idx < self.selected.size() - 1)
        total_selected = self.selected.size()
        self.summary_var.set(f'{total_selected} selected item' + ('s' if total_selected != 1 else '') + (' in output order' if total_selected else ''))
        if total_selected == 0:
            self.summary_var.set('Nothing selected yet')
        if selected_sel:
            value = str(self.selected.get(selected_sel[0])).strip()
            self.selection_var.set(f'Selected {selected_sel[0] + 1} of {total_selected}')
            self.detail_var.set(f'Current output target: {value}')
        elif available_sel:
            value = str(self.available.get(available_sel[0])).strip()
            self.selection_var.set('Available source')
            self.detail_var.set(f'Ready to add: {value}')
        else:
            self.selection_var.set('No focused item')
            self.detail_var.set('Move items from left to right to define the public output order.')

    def set_choices(self, choices: list[tuple[str, str]]) -> None:
        self.choice_map = {label: value for value, label in choices}
        self.available.delete(0, 'end')
        for value, label in choices:
            self.available.insert('end', f'{label} [{value}]')
        self._update_action_state()

    def _add(self) -> None:
        sel = self.available.curselection()
        if not sel:
            return
        value = self.available.get(sel[0])
        current = [self._parse_value(self.selected.get(i)) for i in range(self.selected.size())]
        if self._parse_value(value) not in current:
            self.selected.insert('end', value)
            self.selected.selection_clear(0, 'end')
            self.selected.selection_set(self.selected.size() - 1)
            self._update_action_state()
            self._notify_change()

    def _remove(self) -> None:
        sel = self.selected.curselection()
        if sel:
            idx = sel[0]
            self.selected.delete(idx)
            next_idx = min(idx, self.selected.size() - 1) if self.selected.size() else None
            if next_idx is not None:
                self.selected.selection_set(next_idx)
            self._update_action_state()
            self._notify_change()

    def _move(self, direction: int) -> None:
        sel = self.selected.curselection()
        if not sel:
            return
        idx = sel[0]
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= self.selected.size():
            return
        value = self.selected.get(idx)
        self.selected.delete(idx)
        self.selected.insert(new_idx, value)
        self.selected.selection_set(new_idx)
        self._update_action_state()
        self._notify_change()

    def get_selected_ids(self) -> list[str]:
        return [self._parse_value(self.selected.get(i)) for i in range(self.selected.size())]

    def set_selected_ids(self, ids: list[str]) -> None:
        self.selected.delete(0, 'end')
        reverse = {value: label for label, value in self.choice_map.items()}
        for value in ids:
            if value in reverse:
                self.selected.insert('end', f'{reverse[value]} [{value}]')
            elif str(value).strip():
                self.selected.insert('end', str(value).strip())
        if self.selected.size():
            self.selected.selection_set(0)
        self._update_action_state()

class DiffPreview(ttk.Frame):
    def __init__(self, master: tk.Misc, *, label: str = 'Pending changes') -> None:
        super().__init__(master, style='Card.TFrame', padding=0)
        head = ttk.Frame(self, style='Card.TFrame')
        head.pack(fill='x')
        ttk.Label(head, text=label, style='SectionTitle.TLabel').pack(side='left', anchor='w')
        self.state_var = tk.StringVar(value='Clean')
        self.count_var = tk.StringVar(value='0 lines')
        self.group_var = tk.StringVar(value='No unsaved changes detected.')
        self.updated_var = tk.StringVar(value='Not refreshed yet')
        self.state_label = ttk.Label(head, textvariable=self.state_var, style='StatusGood.TLabel')
        self.state_label.pack(side='right')
        ttk.Label(head, textvariable=self.count_var, style='Pill.TLabel').pack(side='right', padx=(0, 8))
        ttk.Label(self, textvariable=self.group_var, style='PanelSub.TLabel').pack(anchor='w', pady=(4, 0))
        ttk.Label(self, textvariable=self.updated_var, style='PanelSub.TLabel').pack(anchor='w', pady=(2, 0))
        self.text = tk.Text(self, wrap='word')
        _style_text_widget(self.text, rows=11)
        self.text.pack(fill='both', expand=True, pady=(6, 0))
        try:
            pal = _palette(self)
            self.text.tag_configure('group', foreground=pal['accent_deep'], font=('Segoe UI', 9, 'bold'))
            self.text.tag_configure('path', foreground=pal['accent'], font=('Consolas', 9, 'bold'))
            self.text.tag_configure('arrow', foreground=pal['muted'])
            self.text.tag_configure('before', foreground=pal['muted'])
            self.text.tag_configure('after', foreground=pal['text'])
        except Exception:
            pass

    def _group_name(self, path: str) -> str:
        raw = str(path or '').strip()
        if not raw:
            return 'Page'
        if raw.startswith('sections['):
            return 'Sections'
        first = raw.split('.', 1)[0].split('[', 1)[0].replace('_', ' ').strip()
        return first.title() or 'Page'

    def _set_state(self, detail: str, line_count: int, groups: dict[str, int]) -> None:
        self.state_var.set('Unsaved' if line_count else 'Clean')
        self.count_var.set(f'{line_count} line' + ('s' if line_count != 1 else ''))
        group_bits = [f'{name} {count}' for name, count in groups.items()]
        self.group_var.set(' • '.join(group_bits) if group_bits else detail)
        self.updated_var.set(f'Last live refresh: {time.strftime("%H:%M:%S")}')
        try:
            self.state_label.configure(style='StatusWarn.TLabel' if line_count else 'StatusGood.TLabel')
        except Exception:
            pass

    def set_text(self, value: str) -> None:
        lines = [line for line in str(value or '').splitlines() if line.strip()]
        self.set_lines(lines)

    def set_lines(self, lines: list[str]) -> None:
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        if not lines:
            self._set_state('No unsaved changes detected.', 0, {})
            self.text.insert('1.0', 'Saved payload matches the current editor state.')
            self.text.configure(state='disabled')
            return
        grouped: dict[str, list[str]] = {}
        for line in lines:
            path = line.partition(': ')[0]
            group = self._group_name(path)
            grouped.setdefault(group, []).append(line)
        self._set_state('Live diff of current editor state against the saved payload.', len(lines), {name: len(items) for name, items in grouped.items()})
        group_names = list(grouped.keys())
        for g_idx, group in enumerate(group_names):
            self.text.insert('end', group, ('group',))
            self.text.insert('end', '\n')
            for idx, line in enumerate(grouped[group]):
                path, sep, payload = line.partition(': ')
                if sep:
                    before, arrow, after = payload.partition(' → ')
                    self.text.insert('end', '  ')
                    self.text.insert('end', path, ('path',))
                    self.text.insert('end', ': ')
                    self.text.insert('end', before, ('before',))
                    if arrow:
                        self.text.insert('end', ' → ', ('arrow',))
                        self.text.insert('end', after, ('after',))
                else:
                    self.text.insert('end', '  ' + line)
                if idx < len(grouped[group]) - 1:
                    self.text.insert('end', '\n')
            if g_idx < len(group_names) - 1:
                self.text.insert('end', '\n\n')
        self.text.configure(state='disabled')

class ValidationSummaryBar(ttk.Frame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, style='Card.TFrame', padding=0)
        row = ttk.Frame(self, style='Card.TFrame')
        row.pack(fill='x')
        self.status_var = tk.StringVar(value='Validation idle')
        self.detail_var = tk.StringVar(value='No validation run yet.')
        self.updated_var = tk.StringVar(value='')
        self.status_label = ttk.Label(row, textvariable=self.status_var, style='StatusInfo.TLabel')
        self.status_label.pack(side='left')
        ttk.Label(row, textvariable=self.detail_var, style='PanelSub.TLabel').pack(side='left', padx=(8, 0))
        ttk.Label(row, textvariable=self.updated_var, style='PanelSub.TLabel').pack(side='right')

    def set_message(self, message: str) -> None:
        self.status_var.set('Validation status')
        self.detail_var.set(message)
        self.updated_var.set(f'Updated {time.strftime("%H:%M:%S")}')
        try:
            self.status_label.configure(style='StatusInfo.TLabel')
        except Exception:
            pass

    def set_counts(self, *, errors: int = 0, warnings: int = 0) -> None:
        if errors:
            self.status_var.set('Blocking issues')
            self.detail_var.set(f'{errors} error' + ('s' if errors != 1 else '') + f', {warnings} warning' + ('s' if warnings != 1 else ''))
            style_name = 'StatusBad.TLabel'
        elif warnings:
            self.status_var.set('Warnings only')
            self.detail_var.set(f'{warnings} warning' + ('s' if warnings != 1 else '') + ' to review before saving')
            style_name = 'StatusWarn.TLabel'
        else:
            self.status_var.set('Ready')
            self.detail_var.set('No blocking validation issues.')
            style_name = 'StatusGood.TLabel'
        self.updated_var.set(f'Updated {time.strftime("%H:%M:%S")}')
        try:
            self.status_label.configure(style=style_name)
        except Exception:
            pass
