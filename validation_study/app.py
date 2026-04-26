"""Inter-rater κ validation study — standalone Streamlit app.

Companion app to the main ONC-CAR-T-Trials-Monitor dashboard. Two
clinical raters (PJ + collaborator) independently classify a locked
random sample of 200 trials on six axes; Cohen's κ between raters
is the primary outcome (with bootstrap 95% CI), agreement with
the pipeline is a secondary outcome.

Methodology (locked 2026-04-26, see methods.md § Inter-rater κ):
  - Sample: validation_study/sample_v1.json (sha256 in manifest;
    pre-registered in commit before raters enrolled)
  - 200 trials stratified 50% Heme-onc / 50% Solid-onc, ≥5 trials
    per major DiseaseCategory
  - Six axes: Branch, DiseaseCategory, DiseaseEntity, TargetCategory,
    ProductType, SponsorType
  - "Unsure" is a first-class option on every axis (don't force a
    guess — better to mark unscorable than fabricate)
  - Pipeline labels are HIDDEN during rating (no anchoring)
  - Raters cannot see each other's classifications

DATA SAFETY (this is a multi-hour clinical rater session — every
single rating must be durable from the moment it leaves the rater's
fingers):
  1. Server-side autosave on every submit  (/tmp/...{token}.json)
  2. Git-committed canonical store          (responses/{rater}.json)
  3. Crash recovery: /tmp newer than git → offer to resume
  4. Visible "Last saved" indicator with stale-threshold warning
  5. Always-visible manual download button
  6. Auto-prompt for backup every 10 trials
  7. "Email progress" mailto: template for non-git-savvy raters
  8. Schema-versioned JSON with sample sha256 + app version
  9. Atomic writes (write to .tmp, rename)
 10. Resume uploads MERGE not replace

Deploy as a separate Streamlit Cloud app pointed at this file:
  https://share.streamlit.io → New app → main file = validation_study/app.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

# Make the parent repo importable so we can read sample_v1.json with
# the same path conventions whether running locally or on Streamlit Cloud.
APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.0"
APP_VERSION = "0.5.1"  # bump when rater UX changes
SAMPLE_PATH = APP_DIR / "sample_v1.json"
RESPONSES_DIR = APP_DIR / "responses"
LOCAL_BACKUP_DIR = Path("/tmp/validation_responses")
LOCAL_BACKUP_DIR.mkdir(exist_ok=True, parents=True)

# Axis options — kept in sync with config.py / app.py's _FLAG_AXIS_OPTIONS.
# "Unsure" is appended to every axis as a first-class option.
AXIS_OPTIONS = {
    "Branch": ["Heme-onc", "Solid-onc", "Mixed", "Unknown", "Unsure"],
    "DiseaseCategory": "_dynamic",   # populated from sample at load time
    "DiseaseEntity": None,            # free text + autocomplete
    "TargetCategory": None,           # free text + autocomplete
    "ProductType": ["Autologous", "Allogeneic/Off-the-shelf", "In vivo",
                    "Unclear", "Unsure"],
    "SponsorType": ["Industry", "Academic", "Government", "Other", "Unsure"],
}

AXIS_HELP = {
    "Branch": "The trial's primary indication: hematologic, solid, mixed, "
              "or unknown.",
    "DiseaseCategory": "Mid-level disease grouping (e.g. B-NHL, GI, CNS). "
                       "Pick the dominant category if multiple apply.",
    "DiseaseEntity": "Most specific disease leaf (e.g. DLBCL, GBM, HCC). "
                     "Use the trial's terminology where possible.",
    "TargetCategory": "The CAR antigen or, for non-antigen platforms, the "
                      "construct family (e.g. CD19, BCMA, CAR-NK, CAAR-T).",
    "ProductType": "Autologous = patient-derived, Allogeneic = "
                   "off-the-shelf donor, In vivo = mRNA-LNP delivery to "
                   "endogenous T cells.",
    "SponsorType": "Industry = for-profit, Academic = university/hospital, "
                   "Government = NIH/NCI/etc., Other = NGO/foundation.",
}

# Garden gamification — random bloom assignment per completed trial
GARDEN_BLOOMS = ["🌷", "🌹", "🌺", "🌻", "🌸", "🪻", "🌼", "💐", "🍀"]
MILESTONE_EMOJIS = {25: "🌱", 50: "🌿", 75: "🌳", 100: "🎉",
                    125: "🌳", 150: "🌸", 175: "🌹", 200: "🏆"}


# ---------------------------------------------------------------------------
# Page config + styling
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Trial Classification Validation Study",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    /* Tighter, calmer typography for a long rater session */
    .block-container { max-width: 1100px; padding-top: 2rem; }
    .stRadio > div { gap: 0.4rem; }
    /* Garden cells */
    .garden-cell {
        display: inline-block; width: 22px; height: 22px;
        text-align: center; font-size: 16px; line-height: 22px;
    }
    /* Save indicator pulse */
    @keyframes pulse-stale {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.4; }
    }
    .save-stale { animation: pulse-stale 1.5s ease-in-out infinite;
                   color: #d93f0b; }
    .save-fresh { color: #0e8a16; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Token auth
# ---------------------------------------------------------------------------

def _get_rater_identity() -> tuple[str, str] | tuple[None, None]:
    """Return (rater_id, role) where role in {'rater', 'admin'} or (None, None).

    Server-side: VALIDATION_TOKENS env var (or st.secrets) is a JSON dict
    mapping {token_str: {rater_id, role}}. Example:
        {"abc123": {"rater_id": "peter", "role": "rater"},
         "def456": {"rater_id": "drsmith", "role": "rater"},
         "admin789": {"rater_id": "ptjeong", "role": "admin"}}
    """
    token = ""
    try:
        token = st.query_params.get("token", "")
    except Exception:
        pass
    if not token:
        return None, None

    raw = os.environ.get("VALIDATION_TOKENS")
    if not raw:
        try:
            raw = st.secrets.get("validation_tokens", None)
        except Exception:
            raw = None
    if not raw:
        return None, None
    try:
        # secrets can be either a JSON string or a TOML-parsed dict
        tokens = raw if isinstance(raw, dict) else json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None, None

    info = tokens.get(token)
    if not info or not isinstance(info, dict):
        return None, None
    return info.get("rater_id", "anon"), info.get("role", "rater")


# ---------------------------------------------------------------------------
# Sample loading
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _load_sample() -> dict:
    """Load the locked sample manifest. Cached for the session."""
    if not SAMPLE_PATH.exists():
        st.error(f"Sample file not found: {SAMPLE_PATH}. "
                 "Run scripts/generate_validation_sample.py first.")
        st.stop()
    return json.loads(SAMPLE_PATH.read_text())


# ---------------------------------------------------------------------------
# Atomic file ops + storage
# ---------------------------------------------------------------------------

def _atomic_write_json(path: Path, data: dict | list) -> None:
    """Write JSON atomically: write to .tmp, then rename. No half-written files."""
    path.parent.mkdir(exist_ok=True, parents=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2) + "\n")
    tmp_path.replace(path)


def _local_backup_path(rater_id: str) -> Path:
    return LOCAL_BACKUP_DIR / f"{rater_id}.json"


def _committed_responses_path(rater_id: str) -> Path:
    return RESPONSES_DIR / f"{rater_id}.json"


def _load_persisted_responses(rater_id: str) -> dict:
    """Return the most recent persisted state for this rater.

    Resolution: the file with the latest `last_updated` timestamp wins,
    falling back to the committed file if the local backup is missing
    or older. Schema-validated; bad files return empty state with a
    warning so the rater isn't blocked.
    """
    sources: list[tuple[Path, dict]] = []
    for p in (_local_backup_path(rater_id), _committed_responses_path(rater_id)):
        if not p.exists():
            continue
        try:
            doc = json.loads(p.read_text())
        except json.JSONDecodeError as e:
            st.warning(f"Could not parse {p.name}: {e}. Ignored.")
            continue
        if doc.get("schema_version") != SCHEMA_VERSION:
            st.warning(f"{p.name} has incompatible schema version "
                       f"{doc.get('schema_version')!r} (expected {SCHEMA_VERSION!r}). "
                       "Ignored.")
            continue
        sources.append((p, doc))

    if not sources:
        return _empty_state(rater_id)

    sources.sort(key=lambda t: t[1].get("last_updated", ""), reverse=True)
    return sources[0][1]


def _empty_state(rater_id: str) -> dict:
    sample = _load_sample()
    return {
        "schema_version": SCHEMA_VERSION,
        "app_version": APP_VERSION,
        "rater_id": rater_id,
        "sample_version": sample.get("version", "?"),
        "sample_sha256": sample.get("sha256", "?"),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "ratings": {},        # nct_id → {labels, durations, notes, timestamp}
        "session_log": [],    # list of {start, end, n_rated} per session
    }


def _persist(state: dict) -> None:
    """Write state to local /tmp backup. Called on every submit."""
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    state["app_version"] = APP_VERSION
    rater_id = state.get("rater_id", "anon")
    _atomic_write_json(_local_backup_path(rater_id), state)


# ---------------------------------------------------------------------------
# Garden gamification
# ---------------------------------------------------------------------------

def _garden_html(state: dict, sample: dict) -> str:
    """Render a 20×10 garden grid as inline HTML.

    Each completed trial is a deterministic-random bloom (seeded by NCT
    so re-renders are stable). Empty cells show 🪴.
    """
    n_total = len(sample["trials"])
    cells = []
    for i, trial in enumerate(sample["trials"]):
        nct = trial["NCTId"]
        if nct in state["ratings"]:
            # Deterministic bloom assignment seeded by NCT
            bloom_idx = int(hashlib.md5(nct.encode()).hexdigest(), 16) % len(GARDEN_BLOOMS)
            bloom = GARDEN_BLOOMS[bloom_idx]
            cells.append(f'<span class="garden-cell" title="{nct}">{bloom}</span>')
        else:
            cells.append('<span class="garden-cell" style="opacity:0.25">🪴</span>')

    # Layout 20 cells per row
    rows = []
    for r in range(0, n_total, 20):
        rows.append("".join(cells[r:r + 20]))
    return "<div style='line-height:24px;'>" + "<br>".join(rows) + "</div>"


def _milestone_message(n_done: int) -> str | None:
    """Return a celebration message at major milestones, else None."""
    pct = n_done / 200 * 100
    if n_done == 25:
        return "🌱 First quarter — your garden is sprouting!"
    if n_done == 50:
        return "🌿 Halfway through the first half!"
    if n_done == 75:
        return "🌳 Three-eighths complete. The forest is taking shape."
    if n_done == 100:
        return "🎉 **Halfway there!** Take a stretch break — you've earned it."
    if n_done == 125:
        return "🌳 Five-eighths complete. The hard part is behind you."
    if n_done == 150:
        return "🌸 Three-quarters bloomed. Nearly there!"
    if n_done == 175:
        return "🌹 Final stretch — 25 trials to go."
    if n_done == 200:
        return "🏆 **Complete!** All 200 trials rated. Thank you — your contribution is preserved in `responses/`."
    return None


# ---------------------------------------------------------------------------
# Rater workflow
# ---------------------------------------------------------------------------

def _next_unrated_trial(state: dict, sample: dict) -> dict | None:
    """First trial in sample order that hasn't been rated yet."""
    for trial in sample["trials"]:
        if trial["NCTId"] not in state["ratings"]:
            return trial
    return None


def _format_trial_for_rater(trial: dict) -> None:
    """Render the trial info — ONLY the raw evidence, no pipeline labels.

    Layout is optimized for one-glance scannability:
      - Title at the top
      - Metadata chip row (NCT, phase, status, sponsor, design)
      - Conditions + Interventions side-by-side (the two highest-signal
        fields for classification)
      - Brief summary in a scrollable area (NOT collapsed — collapsing
        added a click that ~5 sec of context-switching per trial)
    """
    nct = trial["NCTId"]
    title = trial.get("BriefTitle") or "(no title)"
    st.markdown(f"#### {title}")
    st.caption(
        f"[{nct}](https://clinicaltrials.gov/study/{nct}) · "
        f"**Phase:** {trial.get('Phase') or '—'} · "
        f"**Status:** {trial.get('OverallStatus') or '—'} · "
        f"**Sponsor:** {trial.get('LeadSponsor') or '—'} · "
        f"**Design:** {trial.get('TrialDesign') or '—'}"
    )

    # Conditions + Interventions side-by-side (highest-signal fields)
    _ec1, _ec2 = st.columns(2)
    with _ec1:
        if trial.get("Conditions"):
            st.markdown(f"**Conditions**")
            st.markdown(f"<small>{trial['Conditions']}</small>",
                        unsafe_allow_html=True)
    with _ec2:
        if trial.get("Interventions"):
            st.markdown(f"**Interventions**")
            st.markdown(f"<small>{trial['Interventions']}</small>",
                        unsafe_allow_html=True)

    # Brief summary always visible (no expander click)
    if trial.get("BriefSummary"):
        st.markdown(f"**Brief summary**")
        st.markdown(
            f"<div style='max-height:240px; overflow-y:auto; "
            f"padding:8px 12px; background:#f8fafc; "
            f"border-left:3px solid #cbd5e1; border-radius:4px; "
            f"font-size:0.92em;'>{trial['BriefSummary']}</div>",
            unsafe_allow_html=True,
        )


def _render_axis_input(axis: str, sample: dict, key: str) -> str:
    """Render a single axis input. Returns the chosen value (or "").

    Three input modes by axis type:
      - Enumerable (Branch / ProductType / SponsorType): radio buttons
      - Categorical with many levels (DiseaseCategory): dropdown +
        "Other (specify)" text fallback
      - Free-text-with-suggestions (DiseaseEntity / TargetCategory):
        selectbox of the canonical vocabulary + "Other (specify)" text
        fallback. Standardizes spelling so κ doesn't get artificially
        deflated by 'DLBCL' vs 'Diffuse large B-cell lymphoma'.
    """
    options = AXIS_OPTIONS.get(axis)

    if options == "_dynamic":
        # DiseaseCategory — populated from the sample's pipeline labels
        cats = sorted({
            t["_pipeline"].get("DiseaseCategory") or ""
            for t in sample["trials"]
        } - {""})
        options = cats + ["Other (specify)", "Unsure"]
        choice = st.selectbox(
            axis, options=[""] + options, key=key,
            help=AXIS_HELP[axis], index=0,
            format_func=lambda x: "(pick one)" if not x else x,
        )
        if choice == "Other (specify)":
            other = st.text_input(
                f"Specify {axis}", key=f"{key}_other",
                placeholder="Type the category you'd use",
            ).strip()
            return other or ""
        return choice or ""

    if options is None:
        # Free-text-with-suggestions axis (DiseaseEntity, TargetCategory)
        vocab = sample.get("autocomplete_vocab", {}).get(axis, [])
        choices = [""] + sorted(vocab) + ["Other (specify)", "Unsure"]
        choice = st.selectbox(
            axis, options=choices, key=key,
            help=AXIS_HELP[axis], index=0,
            format_func=lambda x: ("(pick from canonical list, "
                                    "or 'Other' to type)" if not x else x),
        )
        if choice == "Other (specify)":
            other = st.text_input(
                f"Specify {axis}", key=f"{key}_other",
                placeholder="Type the value you'd use",
            ).strip()
            return other or ""
        return choice or ""

    # Enumerable axis — horizontal radio for tightness
    return st.radio(
        axis, options=options, key=key, horizontal=True,
        help=AXIS_HELP[axis], index=None,
    ) or ""


def _render_rater(rater_id: str) -> None:
    """Main rater workflow: one trial at a time + garden + safety nets."""
    sample = _load_sample()
    if "state" not in st.session_state:
        st.session_state["state"] = _load_persisted_responses(rater_id)
    state = st.session_state["state"]

    n_done = len(state["ratings"])
    n_total = len(sample["trials"])

    # ---- Top header: progress + save status + always-on manual save ----
    _c1, _c2, _c3 = st.columns([0.55, 0.25, 0.20])
    with _c1:
        st.progress(n_done / n_total, text=f"**{n_done} / {n_total} trials rated**")
    with _c2:
        last_save = state.get("last_updated", "—")
        try:
            dt = datetime.fromisoformat(last_save.replace("Z", "+00:00"))
            secs_ago = (datetime.now(timezone.utc) - dt).total_seconds()
            stale = secs_ago > 120
            klass = "save-stale" if stale else "save-fresh"
            label = (f"⚠ {int(secs_ago)}s ago — save!" if stale
                     else f"✓ {int(secs_ago)}s ago")
            st.markdown(
                f"<small>Last saved: <span class='{klass}'>{label}</span></small>",
                unsafe_allow_html=True,
            )
        except Exception:
            st.caption("Last saved: —")
    with _c3:
        st.download_button(
            "💾 Download progress",
            data=json.dumps(state, indent=2),
            file_name=f"{rater_id}_progress_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
            help="Save a backup to your computer. Do this whenever you "
                 "leave for a break — it's your safety net if the server "
                 "restarts.",
            use_container_width=True,
        )

    # ---- Garden (live) ----
    with st.expander(f"🌱 Your garden — {n_done} blooms so far", expanded=False):
        st.markdown(_garden_html(state, sample), unsafe_allow_html=True)

    # ---- Milestone banner ----
    msg = _milestone_message(n_done)
    if msg and st.session_state.get("last_milestone_shown") != n_done:
        st.success(msg)
        st.session_state["last_milestone_shown"] = n_done

    # ---- Done? ----
    if n_done >= n_total:
        _render_done(state, rater_id)
        return

    # ---- Current trial ----
    trial = _next_unrated_trial(state, sample)
    if trial is None:
        _render_done(state, rater_id)
        return

    nct = trial["NCTId"]
    st.divider()
    _format_trial_for_rater(trial)
    st.divider()

    st.markdown(f"#### Classify this trial across the six axes")
    st.caption("Pipeline labels are deliberately hidden. If you can't make a "
               "confident call, mark **Unsure** — that's data, not failure.")

    # Track time-on-trial — start the clock when this trial is first shown
    timer_key = f"timer_{nct}"
    if timer_key not in st.session_state:
        st.session_state[timer_key] = time.time()

    # Two-column layout for the six axes (3 left, 3 right)
    axes = list(AXIS_OPTIONS.keys())
    col_l, col_r = st.columns(2)
    user_labels: dict[str, str] = {}
    with col_l:
        for axis in axes[:3]:
            user_labels[axis] = _render_axis_input(axis, sample, key=f"input_{nct}_{axis}")
    with col_r:
        for axis in axes[3:]:
            user_labels[axis] = _render_axis_input(axis, sample, key=f"input_{nct}_{axis}")

    notes = st.text_input(
        "Notes (optional)",
        key=f"notes_{nct}",
        placeholder="Any rationale, ambiguity, or note for adjudication.",
    )

    # ---- Submit ----
    _submit_c1, _submit_c2 = st.columns([0.7, 0.3])
    with _submit_c1:
        skip = st.button("Skip this trial (don't record)",
                          key=f"skip_{nct}",
                          help="Use sparingly — every skip reduces κ statistical power.")
    with _submit_c2:
        submit = st.button(
            f"Submit + next ({n_done + 1}/{n_total}) →",
            key=f"submit_{nct}",
            type="primary",
            use_container_width=True,
        )

    if skip:
        # Record the skip (still durable; lets us report skip rate)
        state["ratings"][nct] = {
            "labels": {ax: "Skipped" for ax in AXIS_OPTIONS},
            "notes": "[skipped by rater]",
            "duration_seconds": int(time.time() - st.session_state[timer_key]),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "skipped": True,
        }
        _persist(state)
        st.session_state.pop(timer_key, None)
        st.rerun()

    if submit:
        # Validate: every axis must be filled (Unsure counts)
        unfilled = [ax for ax, v in user_labels.items() if not v]
        if unfilled:
            st.error(f"Please answer every axis (or pick 'Unsure'). "
                     f"Missing: {', '.join(unfilled)}")
            return
        state["ratings"][nct] = {
            "labels": user_labels,
            "notes": notes.strip(),
            "duration_seconds": int(time.time() - st.session_state[timer_key]),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "skipped": False,
        }
        _persist(state)
        st.session_state.pop(timer_key, None)

        # Auto-prompt for backup every 10 ratings
        if (n_done + 1) % 10 == 0:
            st.toast(
                f"💾 {n_done + 1} done — please click 'Download progress' "
                f"as a backup. Takes 2 sec.",
                icon="🌱",
            )
        st.rerun()

    # ---- Footer: median time + email ----
    _render_footer(state, rater_id)


def _render_footer(state: dict, rater_id: str) -> None:
    """Bottom-of-page utilities: median time, email backup, resume upload."""
    durations = [r.get("duration_seconds", 0) for r in state["ratings"].values()
                 if not r.get("skipped")]
    if durations:
        med = sorted(durations)[len(durations) // 2]
        n_left = 200 - len(state["ratings"])
        eta_min = (med * n_left) / 60
        st.divider()
        st.caption(
            f"Median time per trial so far: **{med}s**. "
            f"Estimated time remaining: **~{eta_min:.0f} min** "
            f"({n_left} trials left). Take breaks — fatigue degrades κ."
        )

    # Email backup template (mailto: with body) — works in any mail client.
    # The JSON itself is too large to fit in a mailto: body for full
    # progress, so we send a stub message + ask the rater to attach the
    # downloaded JSON manually. Lower friction for non-technical raters.
    n_done = len(state["ratings"])
    subj = f"Validation study progress — {rater_id} ({n_done}/200)"
    body = (
        f"Hi Peter,\n\nI've rated {n_done}/200 trials so far. "
        f"Attaching my progress JSON (downloaded just now).\n\n"
        f"Sample: {state.get('sample_sha256', '?')[:12]}…\n\n"
        f"Thanks!\n"
    )
    import urllib.parse as _up
    mailto = (
        f"mailto:peter.jeong@uk-koeln.de?"
        f"subject={_up.quote(subj)}&body={_up.quote(body)}"
    )
    st.markdown(
        f"[📧 Email progress to Peter (open mail client + attach the JSON)]({mailto})",
        unsafe_allow_html=True,
    )

    # Resume from upload — MERGE not replace
    with st.expander("Resume from a previously-downloaded JSON file"):
        uploaded = st.file_uploader(
            "Upload JSON to merge with your current progress",
            type="json", key="resume_upload",
            help="Only NCTs missing from your current state will be filled "
                 "in. Existing ratings are never overwritten.",
        )
        if uploaded:
            try:
                doc = json.loads(uploaded.getvalue())
                if doc.get("schema_version") != SCHEMA_VERSION:
                    st.error(f"Schema mismatch: file has "
                             f"{doc.get('schema_version')!r}, expected "
                             f"{SCHEMA_VERSION!r}.")
                else:
                    n_added = 0
                    for nct, rec in doc.get("ratings", {}).items():
                        if nct not in state["ratings"]:
                            state["ratings"][nct] = rec
                            n_added += 1
                    if n_added:
                        _persist(state)
                        st.success(f"Merged {n_added} new ratings. Refresh to continue.")
                    else:
                        st.info("No new ratings to merge — your current state "
                                "already has all of them.")
            except json.JSONDecodeError as e:
                st.error(f"Couldn't parse the uploaded JSON: {e}")


def _render_done(state: dict, rater_id: str) -> None:
    """All 200 done — celebration + final-submission instructions."""
    st.balloons()
    st.success(
        f"### 🏆 Complete! {len(state['ratings'])} trials rated.\n\n"
        "Your contribution is preserved on the server. **One last step:**"
    )
    st.markdown(
        "1. Click **Download progress** at the top-right one final time. "
        "Save the JSON somewhere safe.\n"
        "2. Email it to **peter.jeong@uk-koeln.de** with subject "
        f"**[validation-final] {rater_id}**.\n"
        "3. Peter commits it to `validation_study/responses/` and the "
        "κ analysis runs.\n\n"
        "Thank you for the time and the careful judgment — you're "
        "the difference between a tool and a published methodology."
    )

    # Always-visible final download
    st.download_button(
        "📥 Download FINAL submission",
        data=json.dumps(state, indent=2),
        file_name=f"{rater_id}_FINAL.json",
        mime="application/json",
        type="primary",
    )


# ---------------------------------------------------------------------------
# Admin view (separate role)
# ---------------------------------------------------------------------------

_ADJUDICATED_PATH = APP_DIR / "adjudicated_v1.json"
NON_RATING_LABELS_ADMIN = {"Unsure", "Skipped", "", None}


def _load_adjudicated() -> dict:
    """Load committed adjudicated gold-standard labels.

    Schema: {nct_id: {axis: gold_label, ...}, "_meta": {...}}
    """
    if not _ADJUDICATED_PATH.exists():
        return {"_meta": {
            "schema_version": SCHEMA_VERSION,
            "app_version": APP_VERSION,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }}
    try:
        return json.loads(_ADJUDICATED_PATH.read_text())
    except json.JSONDecodeError:
        return {"_meta": {"corrupted": True}}


def _save_adjudicated(adj: dict) -> None:
    """Atomic write of the adjudicated truth file."""
    adj["_meta"] = {
        **(adj.get("_meta") or {}),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "app_version": APP_VERSION,
    }
    _atomic_write_json(_ADJUDICATED_PATH, adj)


def _disagreements(rater_docs: dict[str, dict]) -> list[dict]:
    """List every (nct_id, axis) where two raters disagree (excluding
    Unsure/Skipped, which aren't classifications).

    Returns flat list, sorted by NCT then axis, suitable for sequential
    moderator triage.
    """
    if len(rater_docs) < 2:
        return []
    rater_ids = sorted(rater_docs.keys())
    out = []
    a_id, b_id = rater_ids[0], rater_ids[1]  # only first pair for now
    a_doc, b_doc = rater_docs[a_id], rater_docs[b_id]
    common = sorted(set(a_doc.get("ratings", {})) & set(b_doc.get("ratings", {})))
    for nct in common:
        a_rec = a_doc["ratings"][nct]
        b_rec = b_doc["ratings"][nct]
        for axis in AXIS_OPTIONS:
            la = a_rec.get("labels", {}).get(axis)
            lb = b_rec.get("labels", {}).get(axis)
            if la in NON_RATING_LABELS_ADMIN or lb in NON_RATING_LABELS_ADMIN:
                continue
            if la != lb:
                out.append({
                    "nct_id": nct, "axis": axis,
                    "rater_a": a_id, "rater_b": b_id,
                    "label_a": la, "label_b": lb,
                    "notes_a": a_rec.get("notes", ""),
                    "notes_b": b_rec.get("notes", ""),
                })
    return out


def _render_admin(rater_id: str) -> None:
    sample = _load_sample()
    st.title(f"⚙ Admin — {rater_id}")
    st.caption(f"Sample: {sample['sha256'][:16]}… · N={sample['n']} · "
               f"Schema v{SCHEMA_VERSION} · App v{APP_VERSION}")

    tab_status, tab_adj = st.tabs(["📊 Rater status", "⚖ Adjudication queue"])

    # --- Tab 1: rater status ---
    with tab_status:
        rater_files = sorted(RESPONSES_DIR.glob("*.json"))
        if not rater_files:
            st.info(
                "No committed rater responses yet. Final submissions go in "
                f"`{RESPONSES_DIR.relative_to(REPO_ROOT)}/`. Each rater "
                "emails their final JSON, you commit it as `<rater_id>.json`."
            )
            return
        rows = []
        for rp in rater_files:
            try:
                doc = json.loads(rp.read_text())
            except Exception:
                continue
            n_done = len(doc.get("ratings", {}))
            n_skipped = sum(1 for r in doc.get("ratings", {}).values()
                            if r.get("skipped"))
            durations = [r.get("duration_seconds", 0)
                         for r in doc.get("ratings", {}).values()
                         if not r.get("skipped")]
            median_s = (sorted(durations)[len(durations) // 2]
                        if durations else 0)
            rows.append({
                "Rater": doc.get("rater_id", rp.stem),
                "N rated": n_done,
                "N skipped": n_skipped,
                "Median time/trial (s)": median_s,
                "Last updated": doc.get("last_updated", "—"),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        st.info(
            "When all raters have submitted: run "
            "`python3 scripts/build_final_report.py` locally — "
            "produces the publication-ready markdown with κ + bootstrap "
            "CI + pipeline F1 + confusion matrices in one shot."
        )

    # --- Tab 2: adjudication ---
    with tab_adj:
        st.markdown("### Adjudicate disagreements")
        st.caption(
            "Walk through every trial × axis where the two raters "
            "disagreed. The label you pick becomes the gold-standard "
            "ground truth for computing the pipeline's per-axis F1. "
            "All adjudications are saved to "
            f"`{_ADJUDICATED_PATH.relative_to(REPO_ROOT)}` after each pick "
            "so partial sessions are durable."
        )

        # Load the committed rater files
        rater_docs = {}
        for rp in sorted(RESPONSES_DIR.glob("*.json")):
            try:
                doc = json.loads(rp.read_text())
                rater_docs[doc.get("rater_id", rp.stem)] = doc
            except Exception:
                continue
        if len(rater_docs) < 2:
            st.warning(
                f"Need ≥2 committed rater files; have {len(rater_docs)}. "
                "Adjudication queue activates once both raters submit."
            )
            return

        disagreements = _disagreements(rater_docs)
        adj = _load_adjudicated()
        adjudicated_keys = {
            k for k in adj if k != "_meta"
            for _ in [None]  # noqa
        }
        # Outstanding queue = disagreements not yet adjudicated AND
        # not session-skipped (lets the moderator deprioritize a hard
        # one and come back later in the same session).
        def _adj_key(d):
            return f"{d['nct_id']}::{d['axis']}"
        skipped_keys = st.session_state.get("adj_skipped_keys", set())
        outstanding = [d for d in disagreements
                       if _adj_key(d) not in adj
                       and _adj_key(d) not in skipped_keys]

        _m1, _m2, _m3 = st.columns(3)
        _m1.metric("Disagreed pairs", len(disagreements))
        _m2.metric("Adjudicated", sum(1 for k in adj if k != "_meta"))
        _m3.metric("Outstanding (not skipped)", len(outstanding))

        if not outstanding:
            st.success(
                "🎉 All disagreements adjudicated. Run "
                "`python3 scripts/compute_pipeline_f1.py` "
                "to compute pipeline F1 against the gold standard."
            )
            with st.expander("Review/edit adjudicated truth"):
                rows = [{"NCT": k.split("::")[0], "Axis": k.split("::")[1],
                         "Gold label": v}
                        for k, v in adj.items() if k != "_meta"]
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            return

        # Show the next outstanding disagreement
        d = outstanding[0]
        nct, axis = d["nct_id"], d["axis"]
        st.markdown(f"#### Trial {nct} — axis: **{axis}**")

        # Look up the trial in the sample for context
        trial = next((t for t in sample["trials"] if t["NCTId"] == nct), None)
        if trial:
            with st.expander("Trial info", expanded=True):
                _format_trial_for_rater(trial)

        st.markdown(f"##### Rater calls (disagreement)")
        _ac1, _ac2 = st.columns(2)
        with _ac1:
            st.markdown(f"**{d['rater_a']}** said: `{d['label_a']}`")
            if d["notes_a"]:
                st.caption(f"Notes: _{d['notes_a']}_")
        with _ac2:
            st.markdown(f"**{d['rater_b']}** said: `{d['label_b']}`")
            if d["notes_b"]:
                st.caption(f"Notes: _{d['notes_b']}_")

        # Picker for the consensus / gold-standard label
        st.markdown(f"##### Your decision")

        # Pre-compose a sensible option list: rater_a label, rater_b label,
        # plus the canonical option set for this axis (or the autocomplete
        # vocab for free-text axes).
        seed_options = [d["label_a"], d["label_b"]]
        axis_options = AXIS_OPTIONS.get(axis)
        if axis_options is None:
            vocab = sample.get("autocomplete_vocab", {}).get(axis, [])
            extra = vocab
        elif axis_options == "_dynamic":
            extra = sorted({
                t["_pipeline"].get("DiseaseCategory") or ""
                for t in sample["trials"]
            } - {""})
        else:
            extra = [o for o in axis_options if o not in NON_RATING_LABELS_ADMIN]
        all_options = sorted(set(seed_options + list(extra)))

        gold = st.selectbox(
            "Gold-standard label",
            options=[""] + all_options + ["Other (specify)"],
            key=f"adj_gold_{nct}_{axis}",
            format_func=lambda x: "(pick the consensus label)" if not x else x,
        )
        if gold == "Other (specify)":
            other = st.text_input(
                "Specify gold label",
                key=f"adj_other_{nct}_{axis}",
            ).strip()
            gold = other or ""

        rationale = st.text_area(
            "Rationale (recorded, public, becomes part of methodology)",
            key=f"adj_rationale_{nct}_{axis}",
            placeholder="e.g. 'CT.gov primary condition is GBM, not generic CNS'",
        )

        _bc1, _bc2 = st.columns([0.7, 0.3])
        with _bc1:
            if st.button(
                "Skip this disagreement (revisit later)",
                key=f"adj_skip_{nct}_{axis}",
            ):
                # Move to next by NOT recording — the queue auto-advances
                # because outstanding[0] is recomputed each render.
                # But we need to actually skip this one in the current
                # render — use a session-level skip set.
                skipped = st.session_state.setdefault("adj_skipped_keys", set())
                skipped.add(_adj_key(d))
                st.rerun()
        with _bc2:
            if st.button(
                "Record + next →",
                key=f"adj_record_{nct}_{axis}",
                type="primary", use_container_width=True,
            ):
                if not gold:
                    st.error("Pick a gold-standard label first.")
                    return
                adj[_adj_key(d)] = {
                    "nct_id": nct, "axis": axis,
                    "gold_label": gold,
                    "rater_a": d["rater_a"], "label_a": d["label_a"],
                    "rater_b": d["rater_b"], "label_b": d["label_b"],
                    "rationale": rationale.strip(),
                    "adjudicated_by": rater_id,
                    "adjudicated_at": datetime.now(timezone.utc).isoformat(),
                }
                _save_adjudicated(adj)
                st.toast(f"Adjudicated {nct} / {axis} → {gold}",
                         icon="⚖")
                st.rerun()

        if skipped_keys:
            st.caption(f"Skipped in this session: {len(skipped_keys)} "
                       "(will resurface on next session)")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    rater_id, role = _get_rater_identity()
    if rater_id is None:
        st.title("🧪 Trial Classification Validation Study")
        st.caption("Inter-rater reliability study for the CAR-T Trials "
                   "Monitor classification pipeline.")
        st.error(
            "**Access requires an invitation link with a token.**\n\n"
            "If you've been invited as a rater and don't have your link, "
            "please contact peter.jeong@uk-koeln.de.\n\n"
            "If you ARE Peter and the link looks broken, check that "
            "`VALIDATION_TOKENS` is set in Streamlit Cloud secrets."
        )
        return

    st.title("🧪 Trial Classification Validation Study")
    st.caption(
        f"Rater: **{rater_id}** ({role}) · "
        f"Sample v1 · sha256: `{_load_sample()['sha256'][:16]}…`"
    )

    if role == "admin":
        _render_admin(rater_id)
    else:
        _render_rater(rater_id)


if __name__ == "__main__":
    main()
