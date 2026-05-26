"""
Download the latest Fixflo CSV export from a Google Drive folder.

Environment variables required:
  GDRIVE_CREDENTIALS_JSON  - Service account credentials JSON (full content as string)
  GDRIVE_FOLDER_ID         - Google Drive folder ID containing the CSV exports

On success: prints the local temp file path to stdout and exits 0.
On failure: prints an error to stderr and exits 1.
"""

import os, sys, json, tempfile, re
from datetime import datetime

CREDENTIALS_JSON = os.environ.get("GDRIVE_CREDENTIALS_JSON", "")
FOLDER_ID        = os.environ.get("GDRIVE_FOLDER_ID", "")

if not CREDENTIALS_JSON or not FOLDER_ID:
    print("ERROR: GDRIVE_CREDENTIALS_JSON and GDRIVE_FOLDER_ID must be set.", file=sys.stderr)
    sys.exit(1)

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
except ImportError:
    print("ERROR: Run: pip install google-api-python-client google-auth", file=sys.stderr)
    sys.exit(1)


def _csv_dt(name):
    """Parse export timestamp from filename; fall back to epoch so old names sort last."""
    stem = re.sub(r"\.csv$", "", name, flags=re.IGNORECASE)
    for prefix in ("Issue Summary Export ", "issue-export-"):
        if stem.lower().startswith(prefix.lower()):
            ts_raw = stem[len(prefix):].replace("_", ":")
            try:
                return datetime.strptime(ts_raw, "%Y-%m-%dT%H:%M:%S")
            except Exception:
                break
    return datetime(1970, 1, 1)


SHEETS_MIME = "application/vnd.google-apps.spreadsheet"
CSV_MIME    = "text/csv"


def main():
    creds = service_account.Credentials.from_service_account_info(
        json.loads(CREDENTIALS_JSON),
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    service = build("drive", "v3", credentials=creds, cache_discovery=False)

    # Search for both plain CSV files and Google Sheets (Drive auto-converts uploaded CSVs)
    q = (
        f"'{FOLDER_ID}' in parents and trashed=false and "
        f"(mimeType='{CSV_MIME}' or mimeType='{SHEETS_MIME}')"
    )
    result = service.files().list(q=q, fields="files(id,name,mimeType)", pageSize=50).execute()
    files = result.get("files", [])

    csv_files = [
        f for f in files
        if f["name"].lower().startswith("issue summary export")
        or f["name"].lower().startswith("issue-export-")
    ]

    if not csv_files:
        print("ERROR: No Fixflo CSV or Google Sheet found in Google Drive folder.", file=sys.stderr)
        sys.exit(1)

    latest = max(csv_files, key=lambda f: _csv_dt(f["name"]))
    print(f"Downloading: {latest['name']} (type: {latest['mimeType']})", file=sys.stderr)

    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, prefix="fixflo_")
    tmp.close()

    if latest["mimeType"] == SHEETS_MIME:
        # Google Sheets file -- export as CSV
        request = service.files().export_media(fileId=latest["id"], mimeType=CSV_MIME)
    else:
        # Plain CSV file -- download directly
        request = service.files().get_media(fileId=latest["id"])

    with open(tmp.name, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

    print(tmp.name)  # stdout -- captured by the caller


if __name__ == "__main__":
    main()
