from __future__ import annotations

import tkinter as tk
from tkinter import ttk

try:
    from content_models import ValidationIssue, ValidationReport
    from control_panel_forms import _style_text_widget
    from helpers_validation import ContentValidator, load_validation_report, summarize_validation_report, write_validation_report
except ImportError:  # pragma: no cover
    from scripts.content_models import ValidationIssue, ValidationReport  # type: ignore
    from scripts.control_panel_forms import _style_text_widget  # type: ignore
    from scripts.helpers_validation import ContentValidator, load_validation_report, summarize_validation_report, write_validation_report  # type: ignore


class ValidationTab(ttk.Frame):
    def __init__(self, master: tk.Misc, app: "ControlPanel") -> None:
        super().__init__(master)
        self.app = app
        self.validator = ContentValidator(getattr(app, 'ROOT', None) or __import__('pathlib').Path(__file__).resolve().parents[1])
        self.report = ValidationReport()
        self.build_ui()
        self.refresh(rerun=True)

    def build_ui(self) -> None:
        top = ttk.Frame(self)
        top.pack(fill='x', pady=(0, 8))
        self.summary_var = tk.StringVar(value='No validation report yet.')
        ttk.Label(top, textvariable=self.summary_var, style='Sub.TLabel').pack(side='left')
        ttk.Button(top, text='Validate all', command=self.run_full_validation, style='Accent.TButton').pack(side='right')
        ttk.Button(top, text='Validate current page', command=self.run_current_page_validation).pack(side='right', padx=(0, 8))

        split = ttk.Panedwindow(self, orient='horizontal')
        split.pack(fill='both', expand=True)
        left = ttk.Labelframe(split, text='Issues', padding=8)
        right = ttk.Labelframe(split, text='Issue detail', padding=8)
        split.add(left, weight=2)
        split.add(right, weight=1)

        tree_wrap = ttk.Frame(left)
        tree_wrap.pack(fill='both', expand=True)
        tree_wrap.columnconfigure(0, weight=1)
        tree_wrap.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(tree_wrap, columns=('severity', 'scope', 'target', 'message'), show='headings')
        for key, width in [('severity', 70), ('scope', 80), ('target', 120), ('message', 520)]:
            self.tree.heading(key, text=key.title())
            self.tree.column(key, width=width, anchor='w')
        self.tree.grid(row=0, column=0, sticky='nsew')
        tree_scroll = ttk.Scrollbar(tree_wrap, orient='vertical', command=self.tree.yview)
        tree_scroll.grid(row=0, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.bind('<<TreeviewSelect>>', self.on_issue_selected)

        self.detail = tk.Text(right, wrap='word')
        _style_text_widget(self.detail, rows=20)
        self.detail.pack(fill='both', expand=True)
        buttons = ttk.Frame(right)
        buttons.pack(fill='x', pady=(8, 0))
        ttk.Button(buttons, text='Open target', command=self.open_selected_issue_target).pack(side='left')
        ttk.Button(buttons, text='Copy report', command=self.copy_report).pack(side='left', padx=(8, 0))

    def refresh(self, *, rerun: bool = False) -> None:
        if rerun:
            self.report = self.validator.validate_all()
            write_validation_report(self.report)
        else:
            self.report = load_validation_report()
        self.load_report(self.report)

    def load_report(self, report: ValidationReport) -> None:
        self.report = report
        for row in self.tree.get_children():
            self.tree.delete(row)
        for idx, issue in enumerate(report.issues):
            self.tree.insert('', 'end', iid=str(idx), values=(issue.severity, issue.scope, issue.target_key, issue.message))
        counts = summarize_validation_report(report)
        self.summary_var.set(f"Errors: {counts['errors']}   Warnings: {counts['warnings']}   Total: {counts['total']}")
        self.detail.delete('1.0', 'end')
        if not report.issues:
            self.detail.insert('end', 'No issues found.')

    def filtered_issues(self) -> list[ValidationIssue]:
        return list(self.report.issues)

    def run_full_validation(self) -> None:
        self.refresh(rerun=True)
        self.app.log('Ran full validation scan.')

    def run_current_page_validation(self) -> None:
        builder = getattr(self.app, 'content_builder_widget', None)
        if builder and getattr(builder, 'current_page_key', ''):
            report = builder.validate_current_page()
            self.load_report(report)
        else:
            self.refresh(rerun=True)

    def on_issue_selected(self, event: object | None = None) -> None:
        sel = self.tree.selection()
        self.detail.delete('1.0', 'end')
        if not sel:
            return
        issue = self.report.issues[int(sel[0])]
        self.detail.insert('end', f"Severity: {issue.severity}\nScope: {issue.scope}\nTarget: {issue.target_key}\nField: {issue.field_path}\n\n{issue.message}\n\nSuggestion: {issue.suggestion or '—'}")

    def open_selected_issue_target(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        issue = self.report.issues[int(sel[0])]
        self.app.open_validation_target(issue.scope, issue.target_key)

    def copy_report(self) -> None:
        lines = [f"[{item.severity}] {item.scope}:{item.target_key} — {item.message}" for item in self.report.issues]
        text = '\n'.join(lines) if lines else 'No validation issues.'
        self.clipboard_clear()
        self.clipboard_append(text)
