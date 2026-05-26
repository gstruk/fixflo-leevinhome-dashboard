"""
Fixflo Dashboard Updater
------------------------
Drop a new "Issue Summary Export *.csv" in your Downloads folder,
then run this script. It will:
  1. Pick the latest export automatically
  2. Update changed records
  3. Close tickets that are no longer open
  4. Refresh timestamps
  5. Save fixflo-dashboard.html + index.html
  6. Deploy automatically to GitHub Pages
"""

import csv, json, re, shutil, glob, os, sys, base64, urllib.request, urllib.error, argparse
from datetime import datetime, date

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Only exact user-defined phrases — no extras to avoid false matches (e.g. dishwasher, hairdryer)
_APPLIANCE_KEYWORDS = [
    ("hot_water",       ["hot water"]),
    ("washing_machine", ["washing machine"]),
    ("dryer",           ["dryer"]),
    ("hob",             ["hob"]),
    ("hoover",          ["hoover", "vacuum cleaner"]),
    ("fridge",          ["fridge", "fridge freezer", "refrigerator"]),
    ("mattress",        ["mattress"]),
    ("oven",            ["oven", "cooker"]),
    ("cleaning",        ["cleaning"]),
    ("leak",            ["leak"]),
    ("cold_water",      ["cold water"]),
]

TRACKED_TYPES = {"washing_machine", "dryer", "hot_water", "hob", "hoover", "fridge", "mattress", "oven", "cleaning", "leak", "cold_water", "other"}

def detect_appliance_type(title):
    t = (title or "").lower()
    for atype, keywords in _APPLIANCE_KEYWORDS:
        if any(kw in t for kw in keywords):
            return atype
    return "other"

GITHUB_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "github_config.json")

TEAM_DEPT_MAP = {
    # CX Team
    'CX Team': 'CX Team', 'CX Admin': 'CX Team', 'Charge customer': 'CX Team',
    'CX Limerick': 'CX Team', 'Limerick - Waiting Customer FU': 'CX Team', 'Limerick Landlord': 'CX Team',
    'CX Waiting Customer': 'CX Team',
    'CX Limerick - Start Working': 'CX Team', 'CX Limerick - Technician': 'CX Team',
    'CX Limerick - Dashboard': 'CX Team', 'CX Limerick - Waiting Customer FU': 'CX Team',
    'CX Limerick - Landlord': 'CX Team',
    # Facilities Team
    'Maintenance - Dublin': 'Facilities Team', 'Maintenance - Cork': 'Facilities Team',
    'Technician - Dublin': 'Facilities Team', 'Technician - Cork': 'Facilities Team',
    'Waiting for Completion': 'Facilities Team', 'Facilities Admin': 'Facilities Team',
    'FIELD AGENT': 'Facilities Team', 'Inspection - Next step': 'Facilities Team',
    # Commercial Team
    'Commercial Team': 'Commercial Team',
    # Property Management
    '1 - LANDLORD': 'Property Management', '2 - LL - Waiting answer': 'Property Management',
    '3 - LL- Agreed': 'Property Management', '8 - LL - On hold': 'Property Management',
    'Furniture Analysis': 'Property Management',
    'Maint. - Inspec - Low score': 'Property Management', 'Maint. - Inspec - High score': 'Property Management',
    'Bills': 'Property Management', 'Inspecao/Manutencao Preventiva': 'Property Management',
    'Landlord - On hold': 'Property Management',
    '4 - LL - Follow up  customer': 'Property Management', '4-LL- Follow Up Customer': 'Property Management',
    '4 - LL - Follow Up Customer': 'Property Management',
    # Purchasing (Finance)
    'Purchasing': 'Purchasing (Finance)', 'Waiting for Purchasing': 'Purchasing (Finance)',
    'Waiting Delivery': 'Purchasing (Finance)',
}
DEPT_ORDER = ['CX Team', 'Facilities Team', 'Commercial Team', 'Property Management', 'Purchasing (Finance)', 'Others']

def get_dept(team):
    return TEAM_DEPT_MAP.get((team or '').strip(), 'Others')


def notify_google_chat(message):
    if datetime.today().weekday() >= 5:  # 5=Saturday, 6=Sunday
        print("  Google Chat notification skipped (weekend).")
        return
    if not os.path.exists(GITHUB_CONFIG):
        return
    with open(GITHUB_CONFIG) as f:
        cfg = json.load(f)
    webhooks = cfg.get("gchat_webhooks") or []
    if not webhooks:
        return
    payload = json.dumps({"text": message}).encode()
    for i, webhook in enumerate(webhooks, 1):
        req = urllib.request.Request(
            webhook,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=15)
            print(f"  Google Chat notified (webhook {i}/{len(webhooks)}).")
        except Exception as e:
            print(f"  Google Chat webhook {i} failed: {e}")


def deploy_to_github_pages(html_file):
    if not os.path.exists(GITHUB_CONFIG):
        print("  GitHub config not found — skipping deploy.")
        return

    with open(GITHUB_CONFIG) as f:
        cfg = json.load(f)

    token = cfg["token"]
    owner = cfg["owner"]
    repo = cfg["repo"]
    site_url = cfg.get("site_url", "")

    with open(html_file, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    # Get current SHA of the file (required for updates)
    sha_url = f"https://api.github.com/repos/{owner}/{repo}/contents/index.html"
    sha_req = urllib.request.Request(
        sha_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    sha = None
    for _attempt in range(2):
        try:
            sha_res = urllib.request.urlopen(sha_req, timeout=30)
            sha = json.loads(sha_res.read())["sha"]
            break
        except Exception:
            pass

    payload = {"message": "Update dashboard", "content": content_b64, "branch": "main"}
    if sha:
        payload["sha"] = sha

    req = urllib.request.Request(
        sha_url,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
        method="PUT",
    )
    try:
        urllib.request.urlopen(req, timeout=120)
        print(f"  Deployed! Live at: {site_url}")
        print("  (GitHub Pages may take ~1 minute to refresh)")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  Deploy failed ({e.code}): {body}")

DOWNLOADS = os.path.expanduser("~/Downloads")
DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(DASHBOARD_DIR, "fixflo-dashboard.html")
INDEX_FILE = os.path.join(DASHBOARD_DIR, "index.html")
TEAM_HISTORY_FILE = os.path.join(DASHBOARD_DIR, "team_history.json")


# ---------------------------------------------------------------------------
# Team history — tracks when each ticket was assigned to each team
# ---------------------------------------------------------------------------

def load_team_history():
    if os.path.exists(TEAM_HISTORY_FILE):
        with open(TEAM_HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_team_history(history):
    with open(TEAM_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def update_team_history(csv_records, today_str):
    """
    Compare current team assignment (from CSV) with last recorded team.
    Logs the change date whenever the assigned team changes.

    Rules:
    - First time a ticket is seen: initialize with rd (raised date) as team_since.
    - Team changed: close previous entry with today, open new entry from today.
    - Closed tickets: mark their last history entry as closed (to = cd).
    - Only the date we detect the change is accurate; intra-run changes are
      approximated to the script run date.
    """
    history = load_team_history()
    n_new = 0
    n_changed = 0

    for id_, rec in csv_records.items():
        team = (rec.get("team") or "").strip()
        rd   = rec.get("rd") or today_str
        cd   = rec.get("cd")
        is_open = rec.get("isOpen", True)
        was_unassigned = rec.get("_was_unassigned", False)

        if not team:
            continue

        if id_ not in history:
            # Unassigned tickets (→ CX Team): backdate to raised date — CX Team
            # owns them from creation. Explicitly assigned tickets: only backdate
            # if raised today (we can't know when they were assigned before tracking).
            since = rd if (was_unassigned or rd == today_str) else today_str
            history[id_] = {
                "team_since": since,
                "history": [{"team": team, "from": since, "to": None}],
            }
            n_new += 1
        else:
            entry = history[id_]
            last  = entry["history"][-1] if entry["history"] else None

            if last and last["team"] != team:
                # Team changed — close previous, open new entry.
                # Clamp: if today_str < last["from"] (stale CSV re-processed), avoid from > to.
                last["to"] = max(last["from"], today_str)
                entry["history"].append({"team": team, "from": today_str, "to": None})
                entry["team_since"] = today_str
                n_changed += 1

            # If ticket is now closed, mark the final history entry
            if not is_open and cd and last and last["to"] is None:
                last["to"] = cd

    save_team_history(history)
    return history, n_new, n_changed


# All known Fixflo export filename formats: (glob pattern, prefix to strip to reach the timestamp)
_CSV_FORMATS = [
    ("Issue Summary Export *.csv", "Issue Summary Export "),  # downloaded from Fixflo platform
    ("issue-export-*.csv",         "issue-export-"),          # downloaded from Fixflo email link
]

def _csv_export_dt(path):
    """Parse the Fixflo export timestamp from the filename, fall back to mtime."""
    name = os.path.splitext(os.path.basename(path))[0]
    for _, prefix in _CSV_FORMATS:
        if name.lower().startswith(prefix.lower()):
            ts_raw = name[len(prefix):].replace("_", ":")
            try:
                return datetime.strptime(ts_raw, "%Y-%m-%dT%H:%M:%S")
            except Exception:
                break
    return datetime.fromtimestamp(os.path.getmtime(path))

def find_latest_csv():
    files = []
    for pattern, _ in _CSV_FORMATS:
        files.extend(glob.glob(os.path.join(DOWNLOADS, pattern)))
    if not files:
        print()
        print("  ╔══════════════════════════════════════════════════════╗")
        print("  ║          ⚠  Downloads folder is empty               ║")
        print("  ║                                                      ║")
        print("  ║  No Fixflo export CSV was found in:                  ║")
        print(f"  ║  {DOWNLOADS[:50]:<50}  ║")
        print("  ║                                                      ║")
        print("  ║  Please download a fresh export from Fixflo first:   ║")
        print("  ║  • 'Issue Summary Export ...'  (Fixflo platform)     ║")
        print("  ║  • 'issue-export-...'          (Fixflo email link)   ║")
        print("  ╚══════════════════════════════════════════════════════╝")
        print()
        try:
            input("  Press Enter to close...")
        except EOFError:
            pass
        import sys; sys.exit(0)
    latest = max(files, key=_csv_export_dt)
    age_hours = (datetime.now() - _csv_export_dt(latest)).total_seconds() / 3600
    if age_hours > 48:
        print(f"  WARNING: newest export is {age_hours:.0f}h old — download a fresh Fixflo export first.")
    return latest


def parse_date(s):
    if not s or not s.strip():
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            pass
    return None


def _strip_id(s):
    """'First Last (ID123)' -> 'First Last'. Returns None for blank / 'Not set'."""
    s = (s or "").strip()
    if not s or s.lower() == "not set":
        return None
    m = re.match(r"^(.+?)\s*\([^)]+\)\s*$", s)
    return m.group(1).strip() if m else s


def csv_row_to_record(row):
    rd_dt = parse_date(row["Raised date"])
    cd_dt = parse_date(row["IssueStatusChanged"])
    jc_dt = parse_date(row.get("JobCompleted", ""))
    rd = rd_dt.strftime("%Y-%m-%d") if rd_dt else None
    cd = cd_dt.strftime("%Y-%m-%d") if cd_dt else rd

    is_open = row["IsOpen"].strip().lower() == "true"
    if rd_dt and cd_dt and not is_open:
        days = max(0.0, round((cd_dt - rd_dt).total_seconds() / 86400, 1))
    else:
        days = None

    prop = row["PropertyAddressLine2"].strip() or row["PropertyAddressLine1"].strip()

    addr_parts = [
        row["PropertyAddressLine1"].strip(),
        row["PropertyAddressLine2"].strip(),
        row["PropertyTown"].strip(),
    ]
    addr = ", ".join(p for p in addr_parts if p) or None

    try:
        priority = int(row["FaultPriority"])
    except (ValueError, KeyError):
        priority = 0

    fault_detail = row.get("Fault detail", "").strip() or None
    agent        = _strip_id(row.get("AssignedAgent", ""))
    tenant       = _strip_id(row.get("TenantNameCaption", ""))
    contractor   = _strip_id(row.get("JobContractorNameCaption", ""))
    tags         = row.get("Tags", "").strip() or None
    is_planned   = row.get("IsPlannedMaintenance", "").strip().lower() == "true"
    is_communal  = row.get("IsCommunal", "").strip().lower() == "true"
    job_done     = jc_dt.strftime("%Y-%m-%d") if jc_dt else None

    raw_team = row["AssignedTeam"].strip()
    # Unassigned tickets are CX Team's responsibility from the moment they're created
    team = raw_team or "CX Team"

    return {
        "id": row["Id"],
        "team": team,
        "status": row["IssueStatus"],
        "isOpen": is_open,
        "ry": rd_dt.year if rd_dt else None,
        "rm": rd_dt.month if rd_dt else None,
        "rd": rd,
        "cd": cd,
        "days": days,
        "priority": priority,
        "prop": prop,
        "postcode": row["PropertyPostcode"],
        "title": row["IssueTitle"],
        "appliance_type": detect_appliance_type(row["IssueTitle"]),
        # enriched fields
        "addr":        addr,
        "fault_detail": fault_detail,
        "agent":       agent,
        "tenant":      tenant,
        "contractor":  contractor,
        "tags":        tags,
        "is_planned":  is_planned,
        "is_communal": is_communal,
        "job_done":    job_done,
        # populated later
        "team_since":    None,
        "team_history":  None,
        "_was_unassigned": not bool(raw_team),
    }


def load_html_data(html):
    match = re.search(r"(var RAW =)(\[.*?\]);", html, re.DOTALL)
    if not match:
        raise ValueError("Could not find 'var RAW' in the dashboard HTML.")
    return match, json.loads(match.group(2))


def extract_export_name(csv_path):
    return os.path.splitext(os.path.basename(csv_path))[0]


def main():
    # --- Parse arguments ---
    parser = argparse.ArgumentParser(description="Fixflo Dashboard Updater")
    parser.add_argument("--csv-path", metavar="PATH",
                        help="Path to the CSV file (skips auto-discovery and archiving)")
    parser.add_argument("--ci", action="store_true",
                        help="CI mode: skip GitHub API deploy and interactive prompts")
    args = parser.parse_args()

    # --- Find CSV ---
    if args.csv_path:
        csv_path = args.csv_path
        if not os.path.exists(csv_path):
            print(f"ERROR: CSV file not found: {csv_path}")
            sys.exit(1)
        export_name = extract_export_name(csv_path)
        print(f"Using CSV (provided): {export_name}")
    else:
        csv_path = find_latest_csv()
        export_name = extract_export_name(csv_path)
        print(f"Using export: {export_name}")

    # --- Parse export datetime ---
    export_dt = _csv_export_dt(csv_path)

    # --- Load CSV — only tracked appliance types are imported ---
    with open(csv_path, encoding="utf-8-sig") as f:
        all_rows = [csv_row_to_record(row) for row in csv.DictReader(f)]
    csv_records = {r["id"]: r for r in all_rows if r["appliance_type"] in TRACKED_TYPES}
    skipped = len(all_rows) - len(csv_records)
    if skipped:
        print(f"  Skipped {skipped} rows with untracked appliance type (not imported)")

    csv_open_ids = {id_ for id_, r in csv_records.items() if r["isOpen"]}
    print(f"CSV records: {len(csv_records)}  |  Open in CSV: {len(csv_open_ids)}")

    # --- Load dashboard HTML ---
    with open(HTML_FILE, encoding="utf-8") as f:
        html = f.read()

    match, data = load_html_data(html)
    data_by_id = {r["id"]: r for r in data}

    dash_open_ids = {r["id"] for r in data if r["isOpen"]}
    print(f"Dashboard records: {len(data)}  |  Open in dashboard: {len(dash_open_ids)}")

    # Backfill appliance_type for existing records that predate this field
    for rec in data:
        if not rec.get("appliance_type"):
            rec["appliance_type"] = detect_appliance_type(rec.get("title", ""))

    # --- Update records present in the CSV ---
    updated = 0
    reopened_count = 0
    for rec in data:
        if rec["id"] in csv_records:
            new_data = dict(csv_records[rec["id"]])
            was_closed = not rec.get("isOpen", True)
            is_now_open = new_data["isOpen"]

            if was_closed and is_now_open:
                prev_cd = rec.get("cd")
                new_rd  = new_data.get("rd")
                gap = None
                if prev_cd and new_rd:
                    try:
                        gap = (date.fromisoformat(new_rd) - date.fromisoformat(prev_cd)).days
                    except (ValueError, TypeError):
                        pass
                # Reopened only if re-reported within 10 days; otherwise treat as fresh ticket
                if gap is None or gap <= 10:
                    new_data["reopened"] = True
                    new_data["prev_cd"] = prev_cd
                    new_data["days"] = None
                    reopened_count += 1
            elif not is_now_open and rec.get("reopened"):
                # Was previously flagged as reopened, now closed again — preserve flag
                new_data["reopened"] = True
                new_data["prev_cd"] = rec.get("prev_cd")

            old = dict(rec)
            rec.update(new_data)
            if old != rec:
                updated += 1

    # --- Close tickets that were open but are not in this export ---
    # Only auto-close a type if the CSV contains at least one OPEN ticket of that type.
    # If a type has zero open tickets in the CSV (e.g. closed-only backfill), we can't
    # tell the difference between "all resolved" and "not included" — so we skip closing.
    types_with_open_in_csv = {
        r["appliance_type"] for r in csv_records.values() if r["isOpen"]
    }
    print(f"  Appliance types with open tickets in CSV: {sorted(types_with_open_in_csv) or '(none)'}")
    newly_closed_ids = {
        id_ for id_ in (dash_open_ids - csv_open_ids)
        if data_by_id.get(id_, {}).get("appliance_type", "other") in types_with_open_in_csv
    }
    from datetime import timedelta
    close_dt = export_dt.date() - timedelta(days=1)
    close_date = close_dt.strftime("%Y-%m-%d")

    for rec in data:
        if rec["id"] in newly_closed_ids:
            rd_dt = datetime.strptime(rec["rd"], "%Y-%m-%d").date()
            rec["isOpen"] = False
            rec["status"] = "Closed"
            rec["cd"] = close_date
            rec["days"] = round((close_dt - rd_dt).days, 1)

    # --- Add brand-new records not yet in the dashboard ---
    added = 0
    newly_added_ids = set()
    for id_, rec in csv_records.items():
        if id_ not in data_by_id:
            data.append(rec)
            added += 1
            newly_added_ids.add(id_)

    # --- Drop records with no raised date (they break the JS timeline) ---
    data = [r for r in data if r.get("ry")]

    # --- Detect duplicate open tickets (same property + appliance type) ---
    from collections import defaultdict
    prop_app_map = defaultdict(list)
    for r in data:
        if r.get("isOpen") and r.get("prop") and r.get("appliance_type") and r["appliance_type"] != "other":
            prop_app_map[(r["prop"], r["appliance_type"])].append(r["id"])
    duplicate_ids = {id_ for ids in prop_app_map.values() if len(ids) >= 2 for id_ in ids}
    for r in data:
        r["duplicate"] = r["id"] in duplicate_ids

    # --- Team history: detect team changes, inject team_since + team_history ---
    today_str = export_dt.strftime("%Y-%m-%d")
    team_hist, h_new, h_changed = update_team_history(csv_records, today_str)

    for rec in data:
        h = team_hist.get(rec["id"])
        if h:
            rec["team_since"]   = h.get("team_since")
            rec["team_history"] = h.get("history", [])
        else:
            rec["team_since"]   = None
            rec["team_history"] = None

    # --- Update timestamps ---
    # Format timestamps for display
    try:
        ts_display = export_dt.strftime("%Y-%m-%d %H:%M:%S")
        ts_strong = f"{export_dt.day} {export_dt.strftime('%b %Y')} · {export_dt.strftime('%H:%M')}"
    except Exception:
        ts_display = close_date + " 00:00:00"
        ts_strong = close_date + " · updated"

    html = html[:match.start()] + "var RAW =" + json.dumps(data, separators=(",", ":"), ensure_ascii=False) + ";" + html[match.end():]
    html = re.sub(r"Generated: [\d\- :]+", "Generated: " + ts_display, html)
    html = re.sub(r"Last Updated:.*?(?=</strong>)", "Last Updated: " + ts_strong, html)
    html = re.sub(r"Source: [^<]+", "Source: " + export_name, html)
    html = re.sub(
        r"<footer>Leevin Home.*?</footer>",
        f"<footer>Leevin Home &middot; Fixflo Dashboard &middot; {ts_display}</footer>",
        html
    )

    # --- Save files ---
    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    shutil.copy2(HTML_FILE, INDEX_FILE)

    # --- Archive processed CSV (skip when path was explicitly provided or in CI) ---
    if not args.csv_path and not args.ci:
        archive_dir = os.path.join(DOWNLOADS, "fixflo-archive")
        os.makedirs(archive_dir, exist_ok=True)
        archive_name = export_name + ".csv"
        shutil.move(csv_path, os.path.join(archive_dir, archive_name))
        print(f"  Archived CSV -> fixflo-archive/{archive_name}")

    # --- Summary ---
    open_after = sum(1 for r in data if r["isOpen"])
    from collections import Counter
    appliance_counts = Counter(r.get("appliance_type", "other") for r in data if r["isOpen"])
    print()
    print("=" * 50)
    print(f"  Records updated  : {updated}")
    print(f"  Newly closed     : {len(newly_closed_ids)}")
    print(f"  Reopened tickets : {reopened_count}")
    print(f"  New records added: {added}")
    print(f"  Open tickets now : {open_after}")
    for atype, cnt in sorted(appliance_counts.items()):
        label = {"washing_machine": "Washing Machine", "dryer": "Dryer",
                 "hot_water": "Hot Water", "hob": "Hob", "other": "Other",
                 "hoover": "Hoover", "fridge": "Fridge", "mattress": "Mattress", "oven": "Oven",
                 "cleaning": "Cleaning", "leak": "Leak", "cold_water": "Cold Water"}.get(atype, atype)
        print(f"    {label:<18}: {cnt}")
    print(f"  Team history new : {h_new}  changed: {h_changed}")
    print(f"  Timestamp        : {ts_display}")
    print("=" * 50)
    print()
    if not args.ci:
        print("Deploying to GitHub Pages...")
        deploy_to_github_pages(INDEX_FILE)
    else:
        print("  CI mode: skipping GitHub API deploy (workflow handles git push)")

    # --- Google Chat notification ---
    # Only the original 4 appliances are shown in webhook messages.
    # Hoover / Fridge / Mattress / Oven are tracked in the dashboard only.
    _WEBHOOK_TYPES = {"washing_machine", "dryer", "hot_water", "hob"}
    label_map = {"washing_machine": "Washing Machine", "dryer": "Dryer", "hot_water": "Hot Water", "hob": "Hob",
                 "hoover": "Hoover", "fridge": "Fridge", "mattress": "Mattress", "oven": "Oven",
                 "cleaning": "Cleaning", "leak": "Leak", "cold_water": "Cold Water"}
    appliance_summary = "  |  ".join(
        f"{label_map.get(a, a)}: {c}"
        for a, c in sorted(appliance_counts.items())
        if a in _WEBHOOK_TYPES and c > 0
    )

    # New open tickets: always include tickets added this run.
    # On Monday: also include tickets raised since last Friday (covers Fri 18:00
    # Dublin → Mon update). Weekend tickets exist in the dashboard from Friday's
    # run so they won't be in newly_added_ids, but they are still "new" for the
    # team arriving Monday morning.
    new_open_ticket_ids = set(newly_added_ids)
    _is_monday = date.today().weekday() == 0
    if _is_monday:
        _last_friday = date.today() - timedelta(days=3)
        for r in data:
            if r.get("isOpen") and r.get("rd"):
                try:
                    if date.fromisoformat(r["rd"]) >= _last_friday:
                        new_open_ticket_ids.add(r["id"])
                except (ValueError, TypeError):
                    pass

    new_open_tickets = [r for r in data if r["id"] in new_open_ticket_ids and r.get("isOpen") and r.get("appliance_type") in _WEBHOOK_TYPES]
    if new_open_tickets:
        _new_label = (
            f"New tickets this weekend ({len(new_open_tickets)}) — Fri 18:00 → now:"
            if _is_monday
            else f"New tickets opened ({len(new_open_tickets)}):"
        )
        new_lines = "\n".join(
            f"  • #{r['id']} — {label_map.get(r.get('appliance_type',''), r.get('appliance_type','?'))} | {r.get('prop','?')}"
            for r in new_open_tickets[:15]
        )
        new_section = f"\n\n*{_new_label}*\n{new_lines}"
    else:
        new_section = ""

    # Top 5 oldest open tickets by days since raised
    today_d = date.today()
    def _days_open(r):
        try: return (today_d - date.fromisoformat(r["rd"])).days
        except: return 0
    open_tickets = [r for r in data if r.get("isOpen")]
    notif_open = [r for r in open_tickets if r.get("appliance_type") in _WEBHOOK_TYPES]
    top5_oldest = sorted(notif_open, key=_days_open, reverse=True)[:5]
    oldest_lines = "\n".join(
        f"  {i+1}. #{r['id']} — {_days_open(r)}d open | {label_map.get(r.get('appliance_type',''), '?')} | {r.get('prop','?')}"
        for i, r in enumerate(top5_oldest)
    )
    oldest_section = f"\n\n*Top 5 oldest open tickets:*\n{oldest_lines}" if oldest_lines else ""

    # Top 5 tickets longest with current team
    def _days_team(r):
        ts = r.get("team_since")
        if not ts: return 0
        try: return (today_d - date.fromisoformat(ts)).days
        except: return 0
    top5_team = sorted(notif_open, key=_days_team, reverse=True)[:5]
    team_lines = "\n".join(
        f"  {i+1}. #{r['id']} — {_days_team(r)}d with {r.get('team','?')} | {r.get('prop','?')}"
        for i, r in enumerate(top5_team)
    )
    team_section = f"\n\n*Top 5 longest with same team:*\n{team_lines}" if team_lines else ""

    def _dept_color(days):
        if days <= 7:  return "🟢"
        if days <= 14: return "🟡"
        return "🔴"

    def _days_with_dept(r, dept):
        """Days of the current continuous streak in dept (stops at first gap to another dept)."""
        history = r.get("team_history") or []
        earliest = None
        for entry in reversed(history):
            if get_dept(entry.get("team", "")) == dept:
                try:
                    earliest = date.fromisoformat(entry["from"])
                except (ValueError, TypeError):
                    pass
            else:
                break
        if earliest is None:
            return 0
        return max(0, (today_d - earliest).days)

    # 5 oldest open tickets per department
    dept_buckets = {}
    for r in notif_open:
        d = get_dept(r.get('team', ''))
        dept_buckets.setdefault(d, []).append(r)
    dept_oldest_parts = []
    for dept in DEPT_ORDER:
        bucket = dept_buckets.get(dept, [])
        if not bucket:
            continue
        top5 = sorted(bucket, key=_days_open, reverse=True)[:5]
        lines = "\n".join(
            f"    {i+1}. {_dept_color(_days_with_dept(r, dept))} #{r['id']} — {_days_open(r)}d open | {_days_with_dept(r, dept)}d w/dept | {r.get('prop', '?')} | {r.get('team', '?')}"
            for i, r in enumerate(top5)
        )
        dept_oldest_parts.append(f"  *{dept}*\n{lines}")
    dept_oldest_section = (
        "\n\n*5 oldest open tickets per department:*\n" + "\n".join(dept_oldest_parts)
        if dept_oldest_parts else ""
    )

    # Duplicate open tickets section
    dup_open = [r for r in data if r.get("duplicate") and r.get("isOpen") and r.get("appliance_type") in _WEBHOOK_TYPES]
    if dup_open:
        dup_groups = {}
        for r in dup_open:
            key = (r["prop"], r["appliance_type"])
            dup_groups.setdefault(key, []).append(r["id"])
        dup_lines = "\n".join(
            f"  * {label_map.get(app, app)} at {prop}: #{' #'.join(ids)}"
            for (prop, app), ids in sorted(dup_groups.items())
        )
        dup_section = f"\n\nDuplicate open tickets ({len(dup_groups)} {'property' if len(dup_groups)==1 else 'properties'}):\n{dup_lines}"
    else:
        dup_section = ""

    gchat_msg = (
        f"Fixflo Dashboard updated — {ts_display}\n"
        f"Open tickets: {open_after}  ({appliance_summary})\n"
        f"New: {added}  |  Updated: {updated}  |  Closed: {len(newly_closed_ids)}"
        f"{new_section}"
        f"{oldest_section}"
        f"{team_section}"
        f"{dept_oldest_section}"
        f"{dup_section}"
        f"\n\n🟢 0-7d  🟡 8-14d  🔴 15+d  (days with dept)"
        f"\nhttps://gstruk.github.io/fixflo-leevinhome-dashboard/"
    )
    notify_google_chat(gchat_msg)
    print()
    if newly_closed_ids:
        print()
        print("Closed tickets:")
        for r in data:
            if r["id"] in newly_closed_ids:
                print(f"  {r['id']}  {r['prop']}  ({r['days']} days)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERROR: {e}")
    try:
        input("\nPress Enter to close...")
    except EOFError:
        pass
