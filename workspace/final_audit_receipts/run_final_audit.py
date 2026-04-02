import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO_ROOT = Path('/home/notsolikely/Synapse')
RUNTIME_ROOT = REPO_ROOT / 'runtime'
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.continuity_obligations import load_obligations, open_obligation
from synapse_runtime.lineage_store import load_lineage_edges
from synapse_runtime.promotion_engine import load_working_records, promotion_summary
from synapse_runtime.quest_plans import list_plan_artifacts, load_execution_plan
from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state
from synapse_runtime.subject_bridge import install_local_codex_integration
from synapse_runtime.subject_resolver import write_focus_lock

SYNAPSE = [sys.executable, str(REPO_ROOT / 'runtime' / 'synapse.py')]
SNAPSHOT_WRITER = [sys.executable, str(REPO_ROOT / 'runtime' / 'tools' / 'synapse_snapshot_writer.py')]
OUT_ROOT = REPO_ROOT / 'workspace' / 'final_audit_receipts'
SCENARIO_DIR = OUT_ROOT / 'scenarios'
SCENARIO_DIR.mkdir(parents=True, exist_ok=True)


def run_synapse(args, *, cwd, home):
    env = os.environ.copy()
    env['HOME'] = str(home)
    env['SYNAPSE_ROOT'] = str(REPO_ROOT)
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True)


def run_snapshot(args, *, cwd, home):
    env = os.environ.copy()
    env['HOME'] = str(home)
    env['SYNAPSE_ROOT'] = str(REPO_ROOT)
    return subprocess.run(SNAPSHOT_WRITER + args, cwd=cwd, env=env, capture_output=True, text=True)


def write_json(path: Path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + '\n', encoding='utf-8')


def day_from_iso(text: str) -> str:
    return str(text).split('T', 1)[0]


def make_subject(root: Path, home: Path, subject: str):
    engine_root = root / subject
    engine_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'init', '-q'], cwd=engine_root, check=True)
    subprocess.run(['git', 'config', 'user.email', 'audit@example.com'], cwd=engine_root, check=True)
    subprocess.run(['git', 'config', 'user.name', 'Final Audit'], cwd=engine_root, check=True)
    data_root = root / f'{subject}_Data'
    initialize_subject_state(subject, data_root, engine_root)
    ensure_live_scaffold(subject, data_root)
    write_focus_lock(subject=subject, data_root=data_root, engine_root=engine_root, cwt=engine_root, home=home, selection_method='final-audit', source_detail='final_audit')
    return engine_root, data_root


def write_codex_freeze(data_root: Path):
    freeze = data_root / 'Codex' / 'CODEX_FREEZE.md'
    freeze.parent.mkdir(parents=True, exist_ok=True)
    freeze.write_text('# CODEX FREEZE\n\nBrains Approval: YES\nDate: 2026-04-01\n', encoding='utf-8')
    return freeze


def write_draftshot(data_root: Path):
    draft_dir = data_root / 'Snapshots' / 'Draft Shots'
    draft_dir.mkdir(parents=True, exist_ok=True)
    path = draft_dir / 'DRAFTSHOT__runtime-bridge__REV1__2026-04-01.txt'
    path.write_text(
        'DRAFTSHOT\n\nStatus: ACTIVE\nRevision: REV1\n\nNotes: Preserve planning context.\n',
        encoding='utf-8',
    )
    return path


def scenario_receipt(name, *, setup, actions, artifacts, passed, reasons):
    return {
        'scenario': name,
        'setup': setup,
        'actions': actions,
        'artifacts': artifacts,
        'passed': bool(passed),
        'reasons': reasons,
    }


def repo_adoption(tmp: Path, home: Path):
    repo = tmp / 'FrontendPlayground'
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'init', '-q'], cwd=repo, check=True)
    subprocess.run(['git', 'config', 'user.email', 'audit@example.com'], cwd=repo, check=True)
    subprocess.run(['git', 'config', 'user.name', 'Final Audit'], cwd=repo, check=True)
    engage = run_synapse(['engage', '--adopt-current-repo', '--json'], cwd=repo, home=home)
    payload = json.loads(engage.stdout)
    data_root = Path(payload['data_root'])
    install = run_synapse(['install-local-integration', '--json'], cwd=repo, home=home)
    doctor = run_synapse(['doctor', '--governance-root', 'governance'], cwd=repo, home=home)
    passed = engage.returncode == 0 and install.returncode == 0 and (repo / 'AGENTS.md').exists() and (repo / 'CLAUDE.md').exists() and (repo / '.codex' / 'mcp.json').exists() and 'RAW_HEALTHY' in doctor.stdout and 'LOCAL_INTEGRATION:HOOKED:INSTALLED' in doctor.stdout and 'FAIL_ONBOARDING_CONFIRMATION_REQUIRED' in doctor.stdout
    reasons = [] if passed else ['engage/install/doctor posture did not match expected adoption truth']
    return scenario_receipt(
        'repo_adoption',
        setup={'repo': str(repo), 'home': str(home)},
        actions=['engage --adopt-current-repo --json', 'install-local-integration --json', 'doctor --governance-root governance'],
        artifacts={'data_root': str(data_root), 'agents_bridge': str(repo / 'AGENTS.md'), 'claude_bridge': str(repo / 'CLAUDE.md'), 'local_integration_manifest': str(repo / '.codex' / 'synapse_local_integration.json')},
        passed=passed,
        reasons=reasons,
    )


def ordinary_planning_chat(tmp: Path, home: Path):
    engine_root, data_root = make_subject(tmp, home, 'PlanningRepo')
    result = run_synapse(['record-raw-turn', '--role', 'user', '--text', "Okay, that's the plan: build an installable web app with separate user accounts and audio transcription support.", '--json'], cwd=engine_root, home=home)
    payload = json.loads(result.stdout)
    plans = list_plan_artifacts(data_root)
    day = day_from_iso(payload['recorded_at'])
    seg = data_root / '.synapse' / 'SEGMENTS' / 'CONVERSATION' / f'{day}.jsonl'
    sem = data_root / '.synapse' / 'SEMANTIC_EVENTS' / f'{day}.jsonl'
    passed = result.returncode == 0 and Path(payload['raw_turn_path']).exists() and seg.exists() and sem.exists() and len(plans) >= 1 and not payload['event']['payload']['truth_flags']['canon_mutated']
    reasons = [] if passed else ['planning turn did not persist raw/semantic/plan evidence cleanly']
    return scenario_receipt(
        'ordinary_planning_chat',
        setup={'engine_root': str(engine_root), 'data_root': str(data_root)},
        actions=['record-raw-turn user planning statement'],
        artifacts={'raw_turn_path': payload['raw_turn_path'], 'segment_path': str(seg), 'semantic_path': str(sem), 'plan_artifact_path': str(plans[-1]) if plans else None},
        passed=passed,
        reasons=reasons,
    )


def architecture_pivot(tmp: Path, home: Path):
    engine_root, data_root = make_subject(tmp, home, 'PivotRepo')
    texts = [
        "Okay, that's the plan: we will build this as a local-only desktop app with no user accounts.",
        'We are rejecting the desktop path. The plan is now an installable web app with an API and separate user accounts.',
    ]
    actions = []
    for text in texts:
        result = run_synapse(['record-raw-turn', '--role', 'user', '--text', text, '--json'], cwd=engine_root, home=home)
        actions.append({'command': 'record-raw-turn', 'returncode': result.returncode, 'text': text})
    records = [r for r in load_working_records(data_root) if r.get('family') == 'ARCHITECTURE_EVOLUTION']
    edges = load_lineage_edges(data_root)
    obligations = load_obligations(data_root)
    supersedes = [e for e in edges if e.get('relation') == 'supersedes']
    review = [o for o in obligations if str(o.get('state')) == 'open' and str(o.get('obligation_kind')) in {'promotion.review.required', 'architecture.review.required'}]
    passed = len(records) >= 2 and len(supersedes) >= 1 and len(review) >= 1
    reasons = []
    if len(records) < 2:
        reasons.append('architecture evolution records were not preserved across the pivot')
    if len(supersedes) < 1:
        reasons.append('no supersession lineage edge recorded for the architecture pivot')
    if len(review) < 1:
        reasons.append('no review-required artifact was opened when authoritative architecture meaning shifted')
    return scenario_receipt(
        'architecture_pivot',
        setup={'engine_root': str(engine_root), 'data_root': str(data_root)},
        actions=actions,
        artifacts={'architecture_records': [r['path'] for r in records], 'lineage_edges': [e['path'] for e in edges], 'open_obligations': [o['path'] for o in obligations if o.get('state') == 'open']},
        passed=passed,
        reasons=reasons,
    )


def executor_structured_plan(tmp: Path, home: Path):
    engine_root, data_root = make_subject(tmp, home, 'ExecutorPlanRepo')
    text = 'Plan:\n1. Build an installable web app shell.\n2. Add separate user accounts.\n3. Support audio transcription from uploads and links.\nWe need to support accounts, installable delivery, and transcription.'
    result = run_synapse(['record-raw-turn', '--role', 'executor', '--text', text, '--json'], cwd=engine_root, home=home)
    payload = json.loads(result.stdout)
    summary = payload['reducer']['sidecar']['governed_promotion']
    plans = list_plan_artifacts(data_root)
    scope_refs = []
    if plans:
        scope_refs = load_execution_plan(plans[-1]).get('scope_campaign_refs') or []
    passed = result.returncode == 0 and len(plans) >= 1 and len(scope_refs) >= 1 and summary['lineage_edge_count'] >= 1
    reasons = [] if passed else ['executor plan did not persist a plan artifact with scope linkage and lineage']
    return scenario_receipt(
        'executor_generated_structured_plan',
        setup={'engine_root': str(engine_root), 'data_root': str(data_root)},
        actions=['record-raw-turn executor structured plan'],
        artifacts={'raw_turn_path': payload['raw_turn_path'], 'plan_artifact_path': str(plans[-1]) if plans else None, 'scope_campaign_refs': scope_refs},
        passed=passed,
        reasons=reasons,
    )


def blocker_disclosure_case(tmp: Path, home: Path):
    engine_root, data_root = make_subject(tmp, home, 'BlockerRepo')
    text = 'We are blocked on provider credentials and it would be unsafe to claim the transcription feature works yet.'
    result = run_synapse(['record-raw-turn', '--role', 'user', '--text', text, '--json'], cwd=engine_root, home=home)
    payload = json.loads(result.stdout)
    records = [r for r in load_working_records(data_root) if r.get('family') == 'FAILURE_CHAINS']
    obligations = load_obligations(data_root)
    disclosures = list((data_root / '.synapse' / 'DISCLOSURES').glob('DISCLOSURE__*.md'))
    passed = len(records) >= 1 and (len(obligations) >= 1 or len(disclosures) >= 1) and not payload['event']['payload']['truth_flags']['canon_mutated']
    reasons = []
    if len(records) < 1:
        reasons.append('failure chain was not written for the blocker/disclosure case')
    if len(obligations) < 1 and len(disclosures) < 1:
        reasons.append('no obligation or disclosure artifact surfaced for unsafe blocker language')
    return scenario_receipt(
        'blocker_disclosure_case',
        setup={'engine_root': str(engine_root), 'data_root': str(data_root)},
        actions=['record-raw-turn blocker/unsafe claim'],
        artifacts={'failure_chain_paths': [r['path'] for r in records], 'open_obligation_paths': [o['path'] for o in obligations if o.get('state') == 'open'], 'disclosure_paths': [str(p) for p in disclosures]},
        passed=passed,
        reasons=reasons,
    )


def imported_transcript_recovery(tmp: Path, home: Path):
    engine_root, data_root = make_subject(tmp, home, 'ImportRepo')
    note = tmp / 'transcript.txt'
    note.write_text('We need a reusable website system. It must support accounts and installable web apps.\n', encoding='utf-8')
    result = run_synapse(['import-continuity', '--source-file', str(note), '--kind', 'transcript', '--json'], cwd=engine_root, home=home)
    payload = json.loads(result.stdout)
    day = day_from_iso(payload['recorded_at'])
    seg = data_root / '.synapse' / 'SEGMENTS' / 'CONVERSATION' / f'{day}.jsonl'
    sem = data_root / '.synapse' / 'SEMANTIC_EVENTS' / f'{day}.jsonl'
    obligations = load_obligations(data_root)
    imported_records = [r for r in load_working_records(data_root) if r.get('family') == 'IMPORTED_EVIDENCE']
    passed = result.returncode == 0 and payload['import_envelope']['confidence_band'] in {'medium','low'} and seg.exists() and sem.exists() and len(imported_records) >= 1 and any(o.get('obligation_kind') == 'import.review.required' for o in obligations)
    reasons = [] if passed else ['import continuity did not preserve limited-confidence provenance and review requirement correctly']
    return scenario_receipt(
        'imported_transcript_recovery',
        setup={'engine_root': str(engine_root), 'data_root': str(data_root), 'source_file': str(note)},
        actions=['import-continuity --source-file transcript.txt --kind transcript --json'],
        artifacts={'segment_path': str(seg), 'semantic_path': str(sem), 'imported_record_paths': [r['path'] for r in imported_records], 'open_obligation_paths': [o['path'] for o in obligations if o.get('state') == 'open']},
        passed=passed,
        reasons=reasons,
    )


def session_closeout_without_manual_ritual(tmp: Path, home: Path):
    engine_root, data_root = make_subject(tmp, home, 'CloseoutRepo')
    install_local_codex_integration(subject='CloseoutRepo', repo_root=engine_root, data_root=data_root, synapse_root=REPO_ROOT)
    run_synapse(['install-hooks', '--json'], cwd=engine_root, home=home)
    open_obligation(subject='CloseoutRepo', data_root=data_root, recorded_at='2026-04-01T12:20:00-04:00', obligation_kind='draftshot.recommended', severity='warning', summary='High-signal planning happened without a draftshot or equivalent session capture.', required_record_families=['governed_working_record'], source_segment_ids=['SEG-CLS-1'], source_semantic_event_ids=['SEM-CLS-1'], source_refs=[{'kind':'semantic_event','id':'SEM-CLS-1'}], metadata={'topic_key':'session.capture'})
    result = run_synapse(['close-turn', '--strict', '--json'], cwd=engine_root, home=home)
    payload = json.loads(result.stdout)
    rehydrate = data_root / '.synapse' / 'REHYDRATE.md'
    passed = result.returncode == 0 and payload['validation_status'] == 'caution' and payload['open_continuity_obligation_count'] >= 1 and rehydrate.exists()
    reasons = [] if passed else ['close-turn did not surface a lawful continuation warning while keeping rehydrate usable']
    return scenario_receipt(
        'session_closeout_without_manual_ritual',
        setup={'engine_root': str(engine_root), 'data_root': str(data_root)},
        actions=['install-local-integration', 'install-hooks', 'open warning obligation', 'close-turn --strict --json'],
        artifacts={'rehydrate_path': str(rehydrate), 'close_turn_payload': 'close-turn returned caution'},
        passed=passed,
        reasons=reasons,
    )


def bypass_missed_capture(tmp: Path, home: Path):
    engine_root, data_root = make_subject(tmp, home, 'BypassRepo')
    run_synapse(['install-hooks', '--json'], cwd=engine_root, home=home)
    open_obligation(subject='BypassRepo', data_root=data_root, recorded_at='2026-04-01T12:25:00-04:00', obligation_kind='plan.capture.required', severity='blocker', summary='Execution-grade planning is still missing a lawful persisted plan revision.', required_record_families=['plan_revision'], source_segment_ids=['SEG-BYP-1'], source_semantic_event_ids=['SEM-BYP-1'], source_refs=[{'kind':'semantic_event','id':'SEM-BYP-1'}], metadata={'topic_key':'build.plan'})
    pre_commit = subprocess.run([str(engine_root / '.git' / 'hooks' / 'pre-commit')], cwd=engine_root, env={**os.environ, 'HOME': str(home), 'SYNAPSE_ROOT': str(REPO_ROOT)}, capture_output=True, text=True)
    pre_push = subprocess.run([str(engine_root / '.git' / 'hooks' / 'pre-push')], cwd=engine_root, env={**os.environ, 'HOME': str(home), 'SYNAPSE_ROOT': str(REPO_ROOT)}, capture_output=True, text=True)
    passed = pre_commit.returncode == 2 and pre_push.returncode == 2 and 'blocker_continuity_obligation_count: 1' in pre_commit.stdout and 'provenance_status: blocked' in pre_push.stdout
    reasons = [] if passed else ['strict backstop did not fail closed on blocker-class missed capture at honest boundaries']
    return scenario_receipt(
        'bypass_missed_capture',
        setup={'engine_root': str(engine_root), 'data_root': str(data_root)},
        actions=['install-hooks --json', 'open blocker obligation', '.git/hooks/pre-commit', '.git/hooks/pre-push'],
        artifacts={'pre_commit_output': pre_commit.stdout, 'pre_push_output': pre_push.stdout},
        passed=passed,
        reasons=reasons,
    )


def false_positive_sludge_control(tmp: Path, home: Path):
    engine_root, data_root = make_subject(tmp, home, 'NoiseRepo')
    install_local_codex_integration(subject='NoiseRepo', repo_root=engine_root, data_root=data_root, synapse_root=REPO_ROOT)
    run_synapse(['install-hooks', '--json'], cwd=engine_root, home=home)
    turn = run_synapse(['record-raw-turn', '--role', 'user', '--text', 'ok', '--json'], cwd=engine_root, home=home)
    close = run_synapse(['close-turn', '--strict', '--json'], cwd=engine_root, home=home)
    payload = json.loads(close.stdout)
    plans = list_plan_artifacts(data_root)
    records = load_working_records(data_root)
    passed = close.returncode == 0 and payload['validation_status'] == 'clear' and len(plans) == 0 and len(records) == 0
    reasons = [] if passed else ['noise/filler produced bogus durable records or a hard boundary reaction']
    return scenario_receipt(
        'false_positive_sludge_control',
        setup={'engine_root': str(engine_root), 'data_root': str(data_root)},
        actions=['record-raw-turn filler', 'close-turn --strict --json'],
        artifacts={'raw_turn': json.loads(turn.stdout)['raw_turn_path'], 'plan_count': len(plans), 'working_record_count': len(records)},
        passed=passed,
        reasons=reasons,
    )


def degraded_enforcement_mode(tmp: Path, home: Path):
    engine_root, data_root = make_subject(tmp, home, 'DegradedRepo')
    result = run_synapse(['provenance-status', '--strict', '--json'], cwd=engine_root, home=home)
    payload = json.loads(result.stdout)
    passed = result.returncode == 0 and payload['integration_posture'] == 'degraded' and payload['degraded_mode'] and payload['provenance_status'] == 'caution'
    reasons = [] if passed else ['degraded posture was not surfaced honestly when local integration was absent']
    return scenario_receipt(
        'degraded_enforcement_mode',
        setup={'engine_root': str(engine_root), 'data_root': str(data_root)},
        actions=['provenance-status --strict --json'],
        artifacts={'payload_path': 'inline json', 'missing_assets': payload.get('local_integration_missing_assets')},
        passed=passed,
        reasons=reasons,
    )


def onboarding_readiness_regression(tmp: Path, home: Path):
    repo = tmp / 'ExistingRepo'
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'init', '-q'], cwd=repo, check=True)
    engage = run_synapse(['engage', '--adopt-current-repo', '--json'], cwd=repo, home=home)
    payload = json.loads(engage.stdout)
    doctor = run_synapse(['doctor', '--governance-root', 'governance'], cwd=repo, home=home)
    passed = engage.returncode == 0 and doctor.returncode != 0 and 'FAIL_ONBOARDING_CONFIRMATION_REQUIRED' in doctor.stdout
    reasons = [] if passed else ['adopted existing repo was allowed to present as ready without confirmed onboarding']
    return scenario_receipt(
        'onboarding_readiness_regression',
        setup={'repo': str(repo), 'data_root': payload['data_root']},
        actions=['engage --adopt-current-repo --json', 'doctor --governance-root governance'],
        artifacts={'doctor_output_contains': 'FAIL_ONBOARDING_CONFIRMATION_REQUIRED'},
        passed=passed,
        reasons=reasons,
    )


def quest_lifecycle_regression(tmp: Path, home: Path):
    subject='QuestAudit'
    engine_root, data_root = make_subject(tmp, home, subject)
    subject_args = ['--subject', subject, '--data-root', str(data_root), '--engine-root', str(engine_root), '--allow-switch']
    write_codex_freeze(data_root)
    open_sync = run_snapshot(['--subject', subject, '--data-root', str(data_root), '--allow-switch', 'control-open', '--participants', 'Brains, Hands'], cwd=REPO_ROOT, home=home)
    plan = run_synapse(
        [
            'plan-quests',
            '--json',
            '--title',
            'Quest lifecycle',
            '--goal',
            'Prove board to completed flow.',
            '--item',
            'Accept the quest.',
            '--item',
            'Complete the quest cleanly.',
            '--anchor',
            'Quest runtime legality',
            '--anchor',
            'Completion audit PASS',
            '--constraint',
            'Acceptance must stay on the governed quest path and completion must require a clean PASS audit.',
            *subject_args,
        ],
        cwd=REPO_ROOT,
        home=home,
    )
    if open_sync.returncode != 0 or plan.returncode != 0:
        return scenario_receipt(
            'quest_lifecycle_regression',
            setup={'engine_root': str(engine_root), 'data_root': str(data_root)},
            actions=['control-open', 'plan-quests --json'],
            artifacts={'control_open_stdout': open_sync.stdout, 'control_open_stderr': open_sync.stderr, 'plan_stdout': plan.stdout, 'plan_stderr': plan.stderr},
            passed=False,
            reasons=['control-open or plan-quests failed before the quest lifecycle could be exercised'],
        )
    plan_payload = json.loads(plan.stdout)
    board_path = plan_payload['quests'][0]['path']
    accepted = run_synapse(['accept-quest', board_path, '--json', *subject_args], cwd=REPO_ROOT, home=home)
    if accepted.returncode != 0:
        return scenario_receipt(
            'quest_lifecycle_regression',
            setup={'engine_root': str(engine_root), 'data_root': str(data_root)},
            actions=['control-open', 'plan-quests --json', 'accept-quest --json'],
            artifacts={'plan_artifact_path': plan_payload['plan_artifact_path'], 'accept_stdout': accepted.stdout, 'accept_stderr': accepted.stderr},
            passed=False,
            reasons=['accept-quest failed before the completed-quest leg could be exercised'],
        )
    accepted_payload = json.loads(accepted.stdout)
    accepted_path = accepted_payload['acceptance']['accepted_path']
    bundle_path = Path(accepted_payload['acceptance']['audit_bundle_path'])
    completed = run_synapse(['complete-quest', Path(accepted_path).name, '--json', '--milestone-status', 'MILESTONE-001:DONE:Accepted.', '--milestone-status', 'MILESTONE-002:DONE:Completed.', '--check', 'UNIT_TESTS:PASS:Quest audit scenario passed.', '--receipt-ref', str(bundle_path / '00_SUMMARY.md'), '--command-run', 'python3 -m unittest tests.test_quest_runtime_refactor -v', '--changed-file', 'runtime/synapse.py', *subject_args], cwd=REPO_ROOT, home=home)
    if completed.returncode != 0:
        return scenario_receipt(
            'quest_lifecycle_regression',
            setup={'engine_root': str(engine_root), 'data_root': str(data_root)},
            actions=['control-open', 'plan-quests --json', 'accept-quest --json', 'complete-quest --json'],
            artifacts={'plan_artifact_path': plan_payload['plan_artifact_path'], 'accepted_path': accepted_path, 'complete_stdout': completed.stdout, 'complete_stderr': completed.stderr},
            passed=False,
            reasons=['complete-quest failed before the completed-state assertions could be checked'],
        )
    comp_payload = json.loads(completed.stdout)
    passed = open_sync.returncode == 0 and plan.returncode == 0 and accepted.returncode == 0 and completed.returncode == 0 and comp_payload['completion']['overall_verdict'] == 'PASS' and '/Completed/' in comp_payload['completion']['active_path']
    reasons = [] if passed else ['quest flow did not survive board->accepted->completed under the engaged kernel changes']
    return scenario_receipt(
        'quest_lifecycle_regression',
        setup={'engine_root': str(engine_root), 'data_root': str(data_root)},
        actions=['control-open', 'plan-quests --json', 'accept-quest --json', 'complete-quest --json'],
        artifacts={'plan_artifact_path': plan_payload['plan_artifact_path'], 'completed_path': comp_payload['completion']['active_path'], 'completion_audit_path': comp_payload['completion']['latest_completion_audit_path']},
        passed=passed,
        reasons=reasons,
    )


def snapshot_draftshot_bridge_regression(tmp: Path, home: Path):
    subject='SnapshotAudit'
    data_root = tmp / f'{subject}_Data'
    engine_root = tmp / subject
    engine_root.mkdir(parents=True, exist_ok=True)
    initialize_subject_state(subject, data_root, engine_root)
    write_codex_freeze(data_root)
    draftshot = write_draftshot(data_root)
    open_sync = run_snapshot(['--subject', subject, '--data-root', str(data_root), '--allow-switch', 'control-open', '--participants', 'Brains, Hands'], cwd=REPO_ROOT, home=home)
    close_sync = run_snapshot(['--subject', subject, '--data-root', str(data_root), '--allow-switch', 'control-close', '--next-action', 'Resume governed execution.'], cwd=REPO_ROOT, home=home)
    snapshot_dir = data_root / 'Snapshots' / 'Control Sync'
    snaps = sorted(snapshot_dir.glob('*.txt'))
    draft_text = draftshot.read_text(encoding='utf-8')
    passed = open_sync.returncode == 0 and close_sync.returncode == 0 and len(snaps) == 1 and 'Source Draftshot:' in snaps[0].read_text(encoding='utf-8') and 'Status: CONSUMED' in draft_text
    reasons = [] if passed else ['snapshot writer, draftshot bridge, or control sync closeout regressed']
    return scenario_receipt(
        'snapshot_draftshot_control_sync_bridge_regression',
        setup={'engine_root': str(engine_root), 'data_root': str(data_root)},
        actions=['control-open', 'control-close --next-action ...'],
        artifacts={'draftshot_path': str(draftshot), 'control_snapshot_path': str(snaps[0]) if snaps else None},
        passed=passed,
        reasons=reasons,
    )


def truth_compile_regression(tmp: Path, home: Path):
    engine_root, data_root = make_subject(tmp, home, 'TruthRepo')
    run_synapse(['record-raw-turn', '--role', 'user', '--text', 'Okay, that\'s the plan: build an installable web app with accounts.', '--json'], cwd=engine_root, home=home)
    run_synapse(['record-raw-turn', '--role', 'user', '--text', 'We are blocked on provider credentials and cannot safely claim the feature works.', '--json'], cwd=engine_root, home=home)
    result = run_synapse(['compile-current-state', '--json'], cwd=engine_root, home=home)
    payload = json.loads(result.stdout)
    report = data_root / '.synapse' / 'TRUTH' / 'COMPILER_REPORT.yaml'
    statements = data_root / '.synapse' / 'TRUTH' / 'STATEMENTS.yaml'
    current_state = Path(payload['publication_paths']['current_state'])
    passed = (
        result.returncode == 0
        and report.exists()
        and statements.exists()
        and current_state.exists()
        and payload['runtime_status']['operation_status'] == 'ok'
    )
    reasons = [] if passed else ['truth compile regressed after new evidence families existed']
    return scenario_receipt(
        'truth_compile_regression',
        setup={'engine_root': str(engine_root), 'data_root': str(data_root)},
        actions=['record planning turn', 'record blocker turn', 'compile-current-state --json'],
        artifacts={'compiler_report': str(report), 'truth_statements': str(statements), 'current_state': str(current_state)},
        passed=passed,
        reasons=reasons,
    )


def run_all():
    scenario_funcs = [
        repo_adoption,
        ordinary_planning_chat,
        architecture_pivot,
        executor_structured_plan,
        blocker_disclosure_case,
        imported_transcript_recovery,
        session_closeout_without_manual_ritual,
        bypass_missed_capture,
        false_positive_sludge_control,
        degraded_enforcement_mode,
        onboarding_readiness_regression,
        quest_lifecycle_regression,
        snapshot_draftshot_bridge_regression,
        truth_compile_regression,
    ]
    summary = {'scenarios': [], 'pass_count': 0, 'fail_count': 0}
    for func in scenario_funcs:
        with tempfile.TemporaryDirectory(prefix=f'final_audit_{func.__name__}_') as tmpdir:
            tmp = Path(tmpdir)
            home = tmp / 'home'
            home.mkdir(parents=True, exist_ok=True)
            receipt = func(tmp, home)
        summary['scenarios'].append({'scenario': receipt['scenario'], 'passed': receipt['passed'], 'reasons': receipt['reasons']})
        if receipt['passed']:
            summary['pass_count'] += 1
        else:
            summary['fail_count'] += 1
        write_json(SCENARIO_DIR / f"{receipt['scenario']}.json", receipt)
    write_json(OUT_ROOT / 'validation_matrix_summary.json', summary)
    md = ['# Final validation matrix', '']
    for item in summary['scenarios']:
        md.append(f"- {'PASS' if item['passed'] else 'FAIL'} `{item['scenario']}`")
        for reason in item['reasons']:
            md.append(f"  - {reason}")
    (OUT_ROOT / 'validation_matrix_summary.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    run_all()
