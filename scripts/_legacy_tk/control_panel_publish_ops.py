from __future__ import annotations

from datetime import datetime
import tkinter as tk
from tkinter import ttk
from typing import Any

try:
    from helpers_content import ROOT, load_publish_state, recent_transactions
    from helpers_validation import ContentValidator, load_validation_report, summarize_validation_report, write_validation_report
except ImportError:  # pragma: no cover
    from scripts.helpers_content import ROOT, load_publish_state, recent_transactions  # type: ignore
    from scripts.helpers_validation import ContentValidator, load_validation_report, summarize_validation_report, write_validation_report  # type: ignore


class PublishOperationsTab(ttk.Frame):
    def __init__(self, master: tk.Misc, app: "Any") -> None:
        super().__init__(master)
        self.app = app
        self.validator = ContentValidator(ROOT)
        self.issue_view_var = tk.StringVar(value='Blocking publish')
        self.issue_search_var = tk.StringVar()
        self.checklist_status_var = tk.StringVar(value='Refresh to evaluate publish readiness.')
        self.summary_vars: dict[str, tk.StringVar] = {
            'status': tk.StringVar(value='—'),
            'errors': tk.StringVar(value='0'),
            'warnings': tk.StringVar(value='0'),
            'unpublished': tk.StringVar(value='Unknown'),
            'last_build': tk.StringVar(value='unknown'),
            'jobs': tk.StringVar(value='0 jobs'),
        }
        self.last_refresh_var = tk.StringVar(value='Not refreshed yet')
        self.hero_detail_var = tk.StringVar(value='Validation, build health, recovery, and workbook import stay connected here.')
        self.ops_action_detail_var = tk.StringVar(value='Select an action to inspect why it is ranked.')
        self.ops_txn_detail_var = tk.StringVar(value='Select a recent operation to inspect the changed files.')
        self._overview_actions: list[dict[str, Any]] = []
        self._overview_transactions: list[dict[str, Any]] = []
        self.report = load_validation_report()
        self._visible_issues: list[Any] = []
        self.build_ui()
        self.refresh(rerun_validation=True)

    def build_ui(self) -> None:
        shell = ttk.Frame(self, style='App.TFrame', padding=0)
        shell.pack(fill='both', expand=True)

        hero = ttk.Frame(shell, style='HeroCard.TFrame', padding=16)
        hero.pack(fill='x', pady=(0, 10))
        hero.columnconfigure(0, weight=3)
        hero.columnconfigure(1, weight=2)
        left = ttk.Frame(hero, style='HeroCard.TFrame')
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 16))
        ttk.Label(left, text='PUBLISH OPERATIONS', style='Kicker.TLabel').pack(anchor='w')
        ttk.Label(left, text='Release control surface', style='HeroTitle.TLabel').pack(anchor='w', pady=(6, 0))
        ttk.Label(left, textvariable=self.hero_detail_var, style='HeroSub.TLabel', wraplength=760, justify='left').pack(anchor='w', pady=(6, 10))
        strip = ttk.Frame(left, style='Strip.TFrame', padding=(10, 8))
        strip.pack(fill='x')
        ttk.Label(strip, textvariable=self.summary_vars['status'], style='StatusInfo.TLabel').pack(side='left')
        ttk.Label(strip, textvariable=self.summary_vars['jobs'], style='MutedPill.TLabel').pack(side='left', padx=(8, 0))
        ttk.Label(strip, textvariable=self.last_refresh_var, style='MiniMeta.TLabel').pack(side='left', padx=(12, 0))

        right = ttk.Frame(hero, style='Inset.TFrame', padding=12)
        right.grid(row=0, column=1, sticky='nsew')
        ttk.Label(right, text='Fast lane', style='SurfaceTitle.TLabel').pack(anchor='w')
        ttk.Label(right, text='Use this side for the next irreversible action only after the summary stops showing blockers.', style='SurfaceSub.TLabel', wraplength=340, justify='left').pack(anchor='w', pady=(4, 10))
        bar = ttk.Frame(right, style='Inset.TFrame')
        bar.pack(fill='x')
        ttk.Button(bar, text='Refresh', command=lambda: self.refresh(rerun_validation=False), style='Accent.TButton').grid(row=0, column=0, sticky='ew')
        ttk.Button(bar, text='Validate all', command=lambda: self.refresh(rerun_validation=True), style='Toolbar.TButton').grid(row=0, column=1, sticky='ew', padx=(8, 0))
        ttk.Button(bar, text='Prepare publish', command=self.app.prepare_publish, style='Ghost.TButton').grid(row=1, column=0, sticky='ew', pady=(8, 0))
        ttk.Button(bar, text='Open preview', command=self.app.open_current_preview_page, style='Toolbar.TButton').grid(row=1, column=1, sticky='ew', padx=(8, 0), pady=(8, 0))
        bar.columnconfigure(0, weight=1)
        bar.columnconfigure(1, weight=1)

        cards = ttk.Frame(shell, style='App.TFrame')
        cards.pack(fill='x', pady=(0, 10))
        card_defs = [
            ('Status', 'status'),
            ('Errors', 'errors'),
            ('Warnings', 'warnings'),
            ('Unpublished', 'unpublished'),
            ('Last build', 'last_build'),
            ('Recent jobs', 'jobs'),
        ]
        for idx, (label, key) in enumerate(card_defs):
            card = ttk.Frame(cards, style='Card.TFrame', padding=12)
            card.grid(row=0, column=idx, sticky='nsew', padx=(0 if idx == 0 else 8, 0))
            cards.columnconfigure(idx, weight=1)
            ttk.Label(card, text=label, style='MetricLabel.TLabel').pack(anchor='w')
            ttk.Label(card, textvariable=self.summary_vars[key], style='MetricValue.TLabel', wraplength=160, justify='left').pack(anchor='w', pady=(6, 0))

        notebook = ttk.Notebook(shell)
        notebook.pack(fill='both', expand=True)
        self.overview_tab = ttk.Frame(notebook, padding=10)
        self.readiness_tab = ttk.Frame(notebook, padding=10)
        self.builds_tab = ttk.Frame(notebook, padding=10)
        self.recovery_tab = ttk.Frame(notebook, padding=10)
        self.workbook_tab = ttk.Frame(notebook, padding=10)
        notebook.add(self.overview_tab, text='Overview')
        notebook.add(self.readiness_tab, text='Readiness')
        notebook.add(self.builds_tab, text='Builds & Logs')
        notebook.add(self.recovery_tab, text='Recovery')
        notebook.add(self.workbook_tab, text='Workbook')
        self.inner_notebook = notebook

        self._build_overview_tab()
        self._build_readiness_tab()
        self._build_builds_tab()
        self._build_recovery_tab()
        self._build_workbook_tab()

    def _build_overview_tab(self) -> None:
        outer = ttk.Panedwindow(self.overview_tab, orient='horizontal')
        outer.pack(fill='both', expand=True)

        left = ttk.Frame(outer, style='App.TFrame')
        center = ttk.Frame(outer, style='App.TFrame')
        right = ttk.Frame(outer, style='App.TFrame')
        outer.add(left, weight=4)
        outer.add(center, weight=3)
        outer.add(right, weight=4)
        left.rowconfigure(0, weight=3)
        left.rowconfigure(1, weight=2)
        center.rowconfigure(0, weight=3)
        center.rowconfigure(1, weight=2)
        right.rowconfigure(0, weight=3)
        right.rowconfigure(1, weight=2)
        left.columnconfigure(0, weight=1)
        center.columnconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        checks = ttk.Frame(left, style='Card.TFrame', padding=14)
        checks.grid(row=0, column=0, sticky='nsew')
        head = ttk.Frame(checks, style='Card.TFrame')
        head.pack(fill='x')
        ttk.Label(head, text='Release checklist', style='CardTitle.TLabel').pack(side='left')
        ttk.Label(head, text='Structured checks should be easier to scan than a long memo.', style='PanelSub.TLabel').pack(side='right')
        self.checklist_tree = ttk.Treeview(checks, columns=('state', 'check', 'detail'), show='headings', height=8, selectmode='browse')
        for key, text, width, stretch in [('state', 'State', 90, False), ('check', 'Check', 150, False), ('detail', 'Detail', 400, True)]:
            self.checklist_tree.heading(key, text=text)
            self.checklist_tree.column(key, width=width, minwidth=width, stretch=stretch, anchor='w')
        self.checklist_tree.pack(fill='both', expand=True, pady=(10, 0))
        bar = ttk.Frame(checks, style='Card.TFrame')
        bar.pack(fill='x', pady=(10, 0))
        ttk.Button(bar, text='Run pre-publish check', command=self.app.run_prepublish_check, style='Accent.TButton').pack(side='left')
        ttk.Button(bar, text='Build site', command=self.app.build_site, style='Toolbar.TButton').pack(side='left', padx=(8, 0))
        ttk.Button(bar, text='Open preview', command=self.app.open_current_preview_page, style='Ghost.TButton').pack(side='left', padx=(8, 0))

        spotlight = ttk.Frame(left, style='Card.TFrame', padding=14)
        spotlight.grid(row=1, column=0, sticky='nsew', pady=(10, 0))
        ttk.Label(spotlight, text='Issue spotlight', style='CardTitle.TLabel').pack(anchor='w')
        ttk.Label(spotlight, textvariable=self.checklist_status_var, style='PanelSub.TLabel', wraplength=420, justify='left').pack(anchor='w', pady=(6, 8))
        self.checklist_box = tk.Text(spotlight, wrap='word', height=7)
        self.app._style_text_widget(self.checklist_box, height=7)
        self.checklist_box.pack(fill='both', expand=True)

        actions = ttk.Frame(center, style='Card.TFrame', padding=14)
        actions.grid(row=0, column=0, sticky='nsew')
        a_head = ttk.Frame(actions, style='Card.TFrame')
        a_head.pack(fill='x')
        ttk.Label(a_head, text='Action center', style='CardTitle.TLabel').pack(side='left')
        ttk.Label(a_head, textvariable=self.ops_action_detail_var, style='PanelSub.TLabel').pack(side='right')
        self.overview_action_tree = ttk.Treeview(actions, columns=('priority', 'action', 'detail'), show='headings', height=8, selectmode='browse')
        for key, text, width, stretch in [('priority', '#', 44, False), ('action', 'Action', 160, False), ('detail', 'Why now', 300, True)]:
            self.overview_action_tree.heading(key, text=text)
            self.overview_action_tree.column(key, width=width, minwidth=width, stretch=stretch, anchor='w')
        self.overview_action_tree.pack(fill='both', expand=True, pady=(10, 0))
        self.overview_action_tree.bind('<<TreeviewSelect>>', lambda _e: self._on_overview_action_selected())
        self.overview_action_tree.bind('<Double-1>', lambda _e: self._run_selected_overview_action())
        a_bar = ttk.Frame(actions, style='Card.TFrame')
        a_bar.pack(fill='x', pady=(10, 0))
        self.run_overview_action_button = ttk.Button(a_bar, text='Run selected action', command=self._run_selected_overview_action, style='Accent.TButton')
        self.run_overview_action_button.pack(side='left')
        ttk.Button(a_bar, text='Refresh', command=lambda: self.refresh(rerun_validation=False), style='Toolbar.TButton').pack(side='left', padx=(8, 0))

        next_box = ttk.Frame(center, style='Card.TFrame', padding=14)
        next_box.grid(row=1, column=0, sticky='nsew', pady=(10, 0))
        ttk.Label(next_box, text='Recommended flow', style='CardTitle.TLabel').pack(anchor='w')
        self.next_actions_box = tk.Text(next_box, wrap='word', height=7)
        self.app._style_text_widget(self.next_actions_box, height=7)
        self.next_actions_box.pack(fill='both', expand=True, pady=(8, 0))

        recent = ttk.Frame(right, style='Card.TFrame', padding=14)
        recent.grid(row=0, column=0, sticky='nsew')
        r_head = ttk.Frame(recent, style='Card.TFrame')
        r_head.pack(fill='x')
        ttk.Label(r_head, text='Recent operations', style='CardTitle.TLabel').pack(side='left')
        ttk.Label(r_head, text='Selection reveals the changed paths.', style='PanelSub.TLabel').pack(side='right')
        self.overview_txn_tree = ttk.Treeview(recent, columns=('time', 'label', 'status'), show='headings', height=8, selectmode='browse')
        for key, text, width, stretch in [('time', 'Time', 120, False), ('label', 'Operation', 220, True), ('status', 'State', 90, False)]:
            self.overview_txn_tree.heading(key, text=text)
            self.overview_txn_tree.column(key, width=width, minwidth=width, stretch=stretch, anchor='w')
        self.overview_txn_tree.pack(fill='both', expand=True, pady=(10, 0))
        self.overview_txn_tree.bind('<<TreeviewSelect>>', lambda _e: self._on_overview_txn_selected())
        self.overview_txn_box = tk.Text(recent, wrap='word', height=7)
        self.app._style_text_widget(self.overview_txn_box, height=7)
        self.overview_txn_box.pack(fill='both', expand=True, pady=(10, 0))

        jobs = ttk.Frame(right, style='Card.TFrame', padding=14)
        jobs.grid(row=1, column=0, sticky='nsew', pady=(10, 0))
        ttk.Label(jobs, text='Jobs pulse', style='CardTitle.TLabel').pack(anchor='w')
        ttk.Label(jobs, text='Use the Builds tab for the full log. This surface stays focused on the current pulse.', style='PanelSub.TLabel', wraplength=420, justify='left').pack(anchor='w', pady=(6, 8))
        self.build_txn_box = tk.Text(jobs, wrap='word', height=7)
        self.app._style_text_widget(self.build_txn_box, height=7)
        self.build_txn_box.pack(fill='both', expand=True)

    def _build_readiness_tab(self) -> None:
        top = ttk.Frame(self.readiness_tab)
        top.pack(fill='x', pady=(0, 8))
        ttk.Label(top, text='View').pack(side='left')
        view_combo = ttk.Combobox(top, textvariable=self.issue_view_var, state='readonly', values=['Blocking publish', 'All issues', 'Errors only', 'Warnings only', 'Assets only', 'Content refs'])
        view_combo.pack(side='left', padx=(6, 12))
        view_combo.bind('<<ComboboxSelected>>', lambda _e: self._populate_issue_tree())
        ttk.Label(top, text='Search').pack(side='left')
        ttk.Entry(top, textvariable=self.issue_search_var).pack(side='left', fill='x', expand=True, padx=(6, 12))
        self.issue_search_var.trace_add('write', lambda *_: self._populate_issue_tree())
        ttk.Button(top, text='Open target', command=self._open_selected_issue_target).pack(side='right')
        ttk.Button(top, text='Run validation', command=lambda: self.refresh(rerun_validation=True), style='Accent.TButton').pack(side='right', padx=(0, 8))

        split = ttk.Panedwindow(self.readiness_tab, orient='horizontal')
        split.pack(fill='both', expand=True)
        left = ttk.Labelframe(split, text='Issues', padding=8)
        right = ttk.Labelframe(split, text='Issue detail', padding=8)
        split.add(left, weight=2)
        split.add(right, weight=1)

        self.issue_tree = ttk.Treeview(left, columns=('severity', 'scope', 'target', 'field', 'message'), show='headings')
        columns = [('severity', 80), ('scope', 90), ('target', 140), ('field', 160), ('message', 480)]
        for key, width in columns:
            self.issue_tree.heading(key, text=key.title())
            self.issue_tree.column(key, width=width, anchor='w')
        self.issue_tree.pack(fill='both', expand=True)
        self.issue_tree.bind('<<TreeviewSelect>>', self._on_issue_selected)

        self.issue_detail_box = tk.Text(right, wrap='word', bg='white', height=20)
        self.issue_detail_box.pack(fill='both', expand=True)
        btns = ttk.Frame(right)
        btns.pack(fill='x', pady=(8, 0))
        ttk.Button(btns, text='Copy issue list', command=self._copy_issue_list).pack(side='left')
        ttk.Button(btns, text='Run pre-publish check', command=self.app.run_prepublish_check).pack(side='left', padx=(8, 0))

    def _build_builds_tab(self) -> None:
        outer = ttk.Panedwindow(self.builds_tab, orient='horizontal')
        outer.pack(fill='both', expand=True)
        left = ttk.Frame(outer)
        right = ttk.Frame(outer)
        outer.add(left, weight=1)
        outer.add(right, weight=2)

        actions = ttk.Labelframe(left, text='Build actions', padding=10)
        actions.pack(fill='x')
        for label, cmd in [
            ('Build site', self.app.build_site),
            ('Prepare publish', self.app.prepare_publish),
            ('Start preview', self.app.start_preview),
            ('Stop preview', self.app.stop_preview),
            ('Open current preview page', self.app.open_current_preview_page),
            ('Generate OG images', self.app.generate_og),
            ('Rebuild missing derivatives', self.app.rebuild_missing_derivatives),
        ]:
            ttk.Button(actions, text=label, command=cmd).pack(fill='x', pady=3)

        jobs = ttk.Labelframe(left, text='Jobs center', padding=10)
        jobs.pack(fill='both', expand=True, pady=(10, 0))
        self.jobs_list = tk.Listbox(jobs, height=10, exportselection=False)
        self.jobs_list.pack(fill='both', expand=True)
        self.jobs_list.bind('<<ListboxSelect>>', lambda _e: self.app.show_selected_job_detail())
        self.job_detail_box = tk.Text(jobs, wrap='word', bg='white', height=8)
        self.job_detail_box.pack(fill='both', expand=True, pady=(8, 0))
        self.app.jobs_list = self.jobs_list
        self.app.job_detail_box = self.job_detail_box

        build_log_frame = ttk.Labelframe(right, text='Build log', padding=10)
        build_log_frame.pack(fill='both', expand=True)
        self.build_log = tk.Text(build_log_frame, wrap='word', bg='white')
        self.build_log.pack(fill='both', expand=True)
        self.app.build_log = self.build_log

        txn_frame = ttk.Labelframe(right, text='Recent operations', padding=10)
        txn_frame.pack(fill='both', expand=True, pady=(10, 0))
        self.build_txn_box = tk.Text(txn_frame, wrap='word', bg='white', height=10)
        self.build_txn_box.pack(fill='both', expand=True)

    def _build_recovery_tab(self) -> None:
        outer = ttk.Panedwindow(self.recovery_tab, orient='horizontal')
        outer.pack(fill='both', expand=True)
        left = ttk.Labelframe(outer, text='Snapshots', padding=10)
        right = ttk.Labelframe(outer, text='Snapshot detail', padding=10)
        outer.add(left, weight=1)
        outer.add(right, weight=2)

        top = ttk.Frame(left)
        top.pack(fill='x', pady=(0, 6))
        ttk.Button(top, text='Refresh snapshots', command=self.app.refresh_snapshot_browser).pack(side='left')
        ttk.Button(top, text='Restore selected snapshot', command=self.app.restore_selected_snapshot, style='Accent.TButton').pack(side='left', padx=(8, 0))
        self.snapshot_list = tk.Listbox(left, height=12, exportselection=False)
        self.snapshot_list.pack(fill='both', expand=True)
        self.snapshot_list.bind('<<ListboxSelect>>', lambda _e: self.app.show_selected_snapshot_detail(from_build=True))
        self.snapshot_detail = tk.Text(right, wrap='word', bg='white')
        self.snapshot_detail.pack(fill='both', expand=True)
        self.app.build_snapshot_list = self.snapshot_list
        self.app.snapshot_detail = self.snapshot_detail

    def _build_workbook_tab(self) -> None:
        wrap = ttk.Frame(self.workbook_tab)
        wrap.pack(fill='both', expand=True)
        review = ttk.Labelframe(wrap, text='Workbook review & import', padding=10)
        review.pack(fill='both', expand=True)
        path_row = ttk.Frame(review)
        path_row.pack(fill='x')
        self.workbook_path_var = getattr(self.app, 'workbook_path_var', tk.StringVar())
        self.app.workbook_path_var = self.workbook_path_var
        ttk.Entry(path_row, textvariable=self.workbook_path_var).pack(side='left', fill='x', expand=True)
        ttk.Button(path_row, text='Browse…', command=self.app.choose_workbook).pack(side='left', padx=(6, 0))
        btn_row = ttk.Frame(review)
        btn_row.pack(fill='x', pady=(8, 8))
        ttk.Button(btn_row, text='Analyze workbook', command=self.app.analyze_selected_workbook).pack(side='left')
        ttk.Button(btn_row, text='Import workbook', command=self.app.import_selected_workbook, style='Accent.TButton').pack(side='left', padx=(8, 0))
        ttk.Button(btn_row, text='Export workbook', command=self.app.export_workbook).pack(side='left', padx=(8, 0))
        self.workbook_review_box = tk.Text(review, wrap='word', bg='white')
        self.workbook_review_box.pack(fill='both', expand=True)
        self.app.workbook_review_box = self.workbook_review_box

    def _on_overview_action_selected(self) -> None:
        sel = self.overview_action_tree.selection()
        enabled = bool(sel)
        try:
            if enabled:
                self.run_overview_action_button.state(['!disabled'])
            else:
                self.run_overview_action_button.state(['disabled'])
        except Exception:
            pass
        if not sel:
            self.ops_action_detail_var.set('Select an action to inspect why it is ranked.')
            return
        try:
            row = self._overview_actions[int(sel[0])]
            self.ops_action_detail_var.set(str(row.get('detail') or ''))
        except Exception:
            self.ops_action_detail_var.set('Select an action to inspect why it is ranked.')

    def _run_selected_overview_action(self) -> None:
        sel = self.overview_action_tree.selection()
        if not sel:
            return
        try:
            row = self._overview_actions[int(sel[0])]
            command = row.get('command')
        except Exception:
            command = None
        if callable(command):
            command()

    def _on_overview_txn_selected(self) -> None:
        self.overview_txn_box.delete('1.0', 'end')
        sel = self.overview_txn_tree.selection()
        if not sel:
            self.overview_txn_box.insert('end', 'Select a recent operation to inspect the changed paths.')
            return
        try:
            txn = self._overview_transactions[int(sel[0])]
        except Exception:
            self.overview_txn_box.insert('end', 'Select a recent operation to inspect the changed paths.')
            return
        changed = txn.get('changed_paths') or []
        lines = [
            str(txn.get('label') or '—'),
            f"status: {txn.get('status') or '—'}",
            f"time: {txn.get('timestamp') or 'unknown'}",
            '',
        ]
        if changed:
            lines.append('Changed paths:')
            lines.extend([f'- {item}' for item in changed[:12]])
            if len(changed) > 12:
                lines.append('- …')
        else:
            lines.append('No changed paths were recorded for this operation.')
        self.overview_txn_box.insert('end', '\n'.join(lines))

    def refresh(self, *, rerun_validation: bool = False) -> None:
        if rerun_validation:
            self.report = self.validator.validate_all()
            write_validation_report(self.report)
        else:
            self.report = load_validation_report()
            if not self.report.issues and not self.report.generated_at:
                self.report = self.validator.validate_all()
                write_validation_report(self.report)
        counts = summarize_validation_report(self.report)
        build_status = self.app._build_status() if hasattr(self.app, '_build_status') else {}
        if not build_status and hasattr(self.app, '__class__'):
            try:
                from control_panel import _build_status as shared_build_status  # type: ignore
            except Exception:
                from scripts.control_panel import _build_status as shared_build_status  # type: ignore
            build_status = shared_build_status()
        publish_state = load_publish_state()
        pre_status, criticals, warnings = self.app._prepublish_report()
        self.summary_vars['status'].set(pre_status)
        self.summary_vars['errors'].set(str(counts['errors']))
        self.summary_vars['warnings'].set(str(counts['warnings']))
        self.summary_vars['unpublished'].set('Yes' if getattr(publish_state, 'has_unpublished_changes', False) else 'No')
        self.summary_vars['last_build'].set(str(build_status.get('built_at') or build_status.get('generated_at') or getattr(publish_state, 'last_build_at', '') or 'unknown'))
        self.summary_vars['jobs'].set(f"{len(getattr(self.app, 'job_history', []))} jobs")
        self.last_refresh_var.set('Updated ' + datetime.now().strftime('%H:%M:%S'))
        if criticals:
            self.hero_detail_var.set(f'{len(criticals)} blocking release issue(s) are still active. Clear the loudest blockers before you trust the preview.')
        elif warnings:
            self.hero_detail_var.set(f'No hard blockers remain, but {len(warnings)} warning(s) still need judgement before release.')
        else:
            self.hero_detail_var.set('Validation, build health, recovery, and workbook import are aligned. This surface is stable.')
        self._populate_overview(pre_status, criticals, warnings)
        self._populate_issue_tree()
        self._populate_transactions()
        self.app.refresh_jobs_panel()
        self.app.refresh_snapshot_browser()
        if hasattr(self.app, 'show_selected_job_detail'):
            self.app.show_selected_job_detail()
        if hasattr(self.app, 'show_selected_snapshot_detail'):
            self.app.show_selected_snapshot_detail(from_build=True)

    def _populate_overview(self, pre_status: str, criticals: list[str], warnings: list[str]) -> None:
        publish_state = load_publish_state()
        asset_errors = any(item.code in {'work_source_missing', 'resource_file_missing'} and item.severity == 'error' for item in self.report.issues)
        checks = [
            ('Clear' if self.report.error_count() == 0 else 'Blocked', 'Validation', f"{self.report.error_count()} blocking issue(s)" if self.report.error_count() else 'No validation errors.'),
            ('Clear' if not asset_errors else 'Blocked', 'Asset baseline', 'Source images and resource files are intact.' if not asset_errors else 'Missing source images or document files detected.'),
            ('Clear' if not getattr(publish_state, 'has_unpublished_changes', False) else 'Queue', 'Unpublished changes', 'Build matches current content.' if not getattr(publish_state, 'has_unpublished_changes', False) else 'Draft content still differs from the last successful build.'),
            ('Clear' if not any('OG' in item for item in criticals) else 'Blocked', 'OG coverage', next((item for item in criticals if 'OG' in item), 'Social previews are complete.')),
            ('Ready', 'Preview path', 'Use Open preview to verify the exact public page before release.'),
        ]
        self.checklist_tree.delete(*self.checklist_tree.get_children(''))
        for idx, row in enumerate(checks):
            self.checklist_tree.insert('', 'end', iid=str(idx), values=row)
        if criticals:
            self.checklist_status_var.set('Critical blockers are still present. This is not a publish candidate yet.')
        elif warnings:
            self.checklist_status_var.set('No blockers remain, but warnings still need judgement before release.')
        else:
            self.checklist_status_var.set('Baseline looks clear. Use preview and snapshots for final release confidence.')
        spotlight_lines = [f'Pre-publish status: {pre_status}']
        if criticals:
            spotlight_lines.extend(['', 'Critical blockers:'])
            spotlight_lines.extend([f'- {item}' for item in criticals[:8]])
        if warnings:
            spotlight_lines.extend(['', 'Warnings:'])
            spotlight_lines.extend([f'- {item}' for item in warnings[:8]])
        if not criticals and not warnings:
            spotlight_lines.extend(['', 'No blocking issues found. This build looks publish-ready.'])
        self.checklist_box.delete('1.0', 'end')
        self.checklist_box.insert('end', '\n'.join(spotlight_lines))

        next_actions: list[dict[str, Any]] = []
        if self.report.error_count():
            next_actions.append({'label': 'Clear validation', 'detail': 'Open the Readiness tab and resolve blocking errors before any publish attempt.', 'command': lambda: self.inner_notebook.select(self.readiness_tab)})
        elif getattr(publish_state, 'has_unpublished_changes', False):
            next_actions.append({'label': 'Build site', 'detail': 'Current content is ahead of the last successful build.', 'command': self.app.build_site})
        else:
            next_actions.append({'label': 'Open preview', 'detail': 'Inspect the exact public surface visually before release.', 'command': self.app.open_current_preview_page})
        if warnings:
            next_actions.append({'label': 'Review warnings', 'detail': 'Focus on warnings that affect public credibility, especially unpublished hero or cover works.', 'command': lambda: self.inner_notebook.select(self.readiness_tab)})
        else:
            next_actions.append({'label': 'Prepare publish', 'detail': 'Warnings are quiet; package the export only after preview confidence is high.', 'command': self.app.prepare_publish})
        next_actions.append({'label': 'Snapshot check', 'detail': 'Use the Recovery tab if you need to confirm rollback safety.', 'command': lambda: self.inner_notebook.select(self.recovery_tab)})
        self._overview_actions = next_actions
        self.overview_action_tree.delete(*self.overview_action_tree.get_children(''))
        for idx, row in enumerate(next_actions):
            self.overview_action_tree.insert('', 'end', iid=str(idx), values=(idx + 1, row['label'], row['detail']))
        if next_actions:
            self.overview_action_tree.selection_set('0')
        self._on_overview_action_selected()

        flow_lines = []
        for idx, row in enumerate(next_actions, start=1):
            flow_lines.append(f'{idx}. {row["label"]}')
            flow_lines.append(f'   {row["detail"]}')
            flow_lines.append('')
        self.next_actions_box.delete('1.0', 'end')
        self.next_actions_box.insert('end', '\n'.join(flow_lines).strip())

    def _populate_transactions(self) -> None:
        txns = recent_transactions(12)
        self._overview_transactions = txns
        self.overview_txn_tree.delete(*self.overview_txn_tree.get_children(''))
        for idx, txn in enumerate(txns):
            self.overview_txn_tree.insert('', 'end', iid=str(idx), values=(str(txn.get('timestamp') or 'unknown')[-8:], txn.get('label') or '—', txn.get('status') or '—'))
        if txns:
            self.overview_txn_tree.selection_set('0')
        self._on_overview_txn_selected()
        lines = []
        for txn in txns[:8]:
            lines.append(f"{txn.get('timestamp') or 'unknown'}  [{txn.get('status') or '—'}]")
            lines.append(str(txn.get('label') or '—'))
            lines.append('')
        text = '\n'.join(lines).strip() if lines else 'No recent operations recorded.'
        self.build_txn_box.delete('1.0', 'end')
        self.build_txn_box.insert('end', text)
    def _populate_issue_tree(self) -> None:
        for row in self.issue_tree.get_children():
            self.issue_tree.delete(row)
        view = self.issue_view_var.get().strip()
        needle = self.issue_search_var.get().strip().lower()
        issues = list(self.report.issues)
        if view == 'Blocking publish':
            issues = [item for item in issues if item.severity == 'error' or item.scope in {'publish', 'asset'}]
        elif view == 'Errors only':
            issues = [item for item in issues if item.severity == 'error']
        elif view == 'Warnings only':
            issues = [item for item in issues if item.severity == 'warning']
        elif view == 'Assets only':
            issues = [item for item in issues if item.scope == 'asset']
        elif view == 'Content refs':
            issues = [item for item in issues if item.scope in {'page', 'series', 'work', 'resource'}]
        if needle:
            issues = [item for item in issues if needle in f"{item.code} {item.scope} {item.target_key} {item.field_path} {item.message}".lower()]
        self._visible_issues = issues
        for idx, issue in enumerate(issues):
            self.issue_tree.insert('', 'end', iid=str(idx), values=(issue.severity, issue.scope, issue.target_key, issue.field_path, issue.message))
        self.issue_detail_box.delete('1.0', 'end')
        if not issues:
            self.issue_detail_box.insert('end', 'No issues match this view.')

    def _on_issue_selected(self, _event: object | None = None) -> None:
        self.issue_detail_box.delete('1.0', 'end')
        sel = self.issue_tree.selection()
        if not sel:
            return
        issue = self._visible_issues[int(sel[0])]
        self.issue_detail_box.insert('end', f"Severity: {issue.severity}\nScope: {issue.scope}\nTarget: {issue.target_key}\nField: {issue.field_path}\nCode: {issue.code}\n\n{issue.message}\n\nSuggestion: {issue.suggestion or '—'}")

    def _open_selected_issue_target(self) -> None:
        sel = self.issue_tree.selection()
        if not sel:
            return
        issue = self._visible_issues[int(sel[0])]
        self.app.open_validation_target(issue.scope, issue.target_key)

    def _copy_issue_list(self) -> None:
        lines = [f"[{item.severity}] {item.scope}:{item.target_key} — {item.message}" for item in self._visible_issues]
        text = '\n'.join(lines) if lines else 'No matching issues.'
        self.clipboard_clear()
        self.clipboard_append(text)
