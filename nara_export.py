#!/usr/bin/env python3
"""Export Nara Baby to local JSON and CSV. Python 3.9+, no dependencies."""
import argparse
import csv
import getpass
import json
import os
from pathlib import Path
import re
import sys
import warnings
from datetime import datetime, timezone
from urllib import request, error, parse

API_KEY = "AIzaSyApsJ5h5-JCjp9SJvWbHG4Fxq8NbxDW0EQ"  # Public Firebase app identifier, not a password.
DB = "https://amazing-ripple-221320.firebaseio.com"
FUNCTION = "https://us-central1-amazing-ripple-221320.cloudfunctions.net/app"


class ExportError(Exception):
    pass


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self):
        # Credentials go only to Firebase/Nara over verified HTTPS.
        self.opener = request.build_opener(request.ProxyHandler({}), NoRedirect())
        self.token = None
        self.uid = None

    def call(self, url, payload=None, bearer=False):
        headers = {"Content-Type": "application/json"}
        if bearer:
            headers["Authorization"] = "Bearer " + self.token
        req = request.Request(url, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
        try:
            with self.opener.open(req, timeout=60) as response:
                return json.load(response)
        except error.HTTPError as exc:
            try:
                exc.close()
            except Exception:
                # Cleanup must not mask the fixed, secret-free request error.
                pass
            if exc.code in (401, 403):
                raise ExportError("Login expired, incorrect login, or access denied (HTTP %s)." % exc.code) from None
            raise ExportError("Nara request failed (HTTP %s). Try again later." % exc.code) from None
        except (error.URLError, TimeoutError, OSError):
            raise ExportError("Could not connect. Check your internet connection and try again.") from None
        except (ValueError, UnicodeError):
            raise ExportError("Nara returned an unexpected response. The service may have changed.") from None

    def login(self, email, password):
        data = self.call("https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=" + API_KEY,
                         {"email": email, "password": password, "returnSecureToken": True})
        if not isinstance(data, dict) or not all(isinstance(data.get(k), str) and data[k] for k in ("idToken", "localId")):
            raise ExportError("Login did not return a valid session.")
        self.token, self.uid = data["idToken"], data["localId"]

    def get(self, path):
        return self.call(DB + path + ".json?" + parse.urlencode({"auth": self.token}))

    def sync(self, family):
        return self.call(FUNCTION, {"data": {"action": "/family/trackz/sync2", "familyKey": family, "prevSyncKey": None}}, bearer=True)


def key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ExportError("Nara returned an invalid identifier.")
    return value


def mapping(value, label, allow_null=False):
    if value is None and allow_null:
        return {}
    if not isinstance(value, dict) or "error" in value:
        raise ExportError("Unexpected %s response; this is not an empty export." % label)
    return value


def tracks_from(payload):
    result = mapping(mapping(payload, "sync").get("result"), "sync result")
    data = result if "trackz" in result else result.get("data")
    if not isinstance(data, dict) or "trackz" not in data:
        raise ExportError("Activity sync is missing history; this is not an empty export.")
    tracks = mapping(data["trackz"], "activities", allow_null=True)
    if any(not isinstance(v, dict) for v in tracks.values()):
        raise ExportError("Unexpected activity record format.")
    return tracks


def save_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    path.chmod(0o600)


def csv_value(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if value is None:
        return ""
    # Prevent notes/names from becoming formulas when opened in a spreadsheet.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def iso_ms(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return ""
    try:
        return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return ""


def save_csv(path, tracks, children):
    extra = ["export_record_id", "export_child_name", "export_begin_utc", "export_end_utc"]
    fields = extra + sorted({field for track in tracks.values() for field in track} - set(extra))
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for record_id, track in tracks.items():
            child = children.get(track.get("childKey"))
            row = dict(track)
            row.update(export_record_id=record_id,
                       export_child_name=child.get("name", "") if isinstance(child, dict) else "",
                       export_begin_utc=iso_ms(track.get("beginDt")), export_end_utc=iso_ms(track.get("endDt")))
            writer.writerow({k: csv_value(v) for k, v in row.items()})
    path.chmod(0o600)


def export(client, folder):
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = {"exported_at_utc": datetime.now(timezone.utc).isoformat(), "complete": False,
              "scope": "Accessible account/family database snapshots and full-reset activity sync; not a verified exhaustive server backup.",
              "families": [], "errors": []}
    try:
        memberships = mapping(client.get("/userz/%s/familyKeyz" % key(client.uid)), "family membership", allow_null=True)
        save_json(folder / "family-memberships.json", memberships)
        try:
            save_json(folder / "account.json", client.get("/userz/%s" % key(client.uid)))
        except ExportError as exc:
            report["errors"].append("Account snapshot: " + str(exc))
        for index, family in enumerate(memberships, 1):
            family_dir = folder / ("family-%02d" % index)
            family_dir.mkdir(mode=0o700)
            item = {"folder": family_dir.name, "family_key": family, "activities": None}
            report["families"].append(item)
            try:
                family = key(family)
                try:
                    save_json(family_dir / "family-snapshot.json", client.get("/familyz/" + family))
                except ExportError as exc:
                    report["errors"].append(family_dir.name + " database snapshot: " + str(exc))
                children = {}
                try:
                    children = mapping(client.get("/familyz/" + family + "/childz"), "children", allow_null=True)
                    if any(not isinstance(v, dict) for v in children.values()):
                        raise ExportError("Unexpected child profile format.")
                    save_json(family_dir / "children.json", children)
                except ExportError as exc:
                    report["errors"].append(family_dir.name + " child profiles: " + str(exc))
                    children = {}
                payload = client.sync(family)
                # Save original sync even when parsing fails, for future recovery.
                save_json(family_dir / "activity-sync.json", payload)
                tracks = tracks_from(payload)
                save_json(family_dir / "activities.json", tracks)
                save_csv(family_dir / "activities.csv", tracks, children)
                item["activities"] = len(tracks)
                print("Family %d: saved %d activities and %d child profiles." % (index, len(tracks), len(children)))
            except ExportError as exc:
                report["errors"].append(family_dir.name + ": " + str(exc))
        report["complete"] = not report["errors"]
    except ExportError as exc:
        report["errors"].append(str(exc))
    finally:
        save_json(folder / "export-report.json", report)
    return report


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New backup folder (must not exist)")
    args = parser.parse_args()
    folder = args.output or Path("nara-backup-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    print("Nara Baby backup — your login is never saved. Nothing in the app is changed.")
    client = Client()
    try:
        if not sys.stdin.isatty():
            raise ExportError("Run this in a terminal so you can enter your login privately.")
        email = input("Nara account email: ").strip()
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Nara password (hidden): ")
        try:
            client.login(email, password)
        finally:
            password = None
        report = export(client, folder)
        print("Backup saved to: " + str(folder.resolve()))
        if report["errors"]:
            print("PARTIAL BACKUP — some requests failed. See export-report.json and rerun into a new folder.")
            for message in report["errors"]:
                print("  " + message)
            return 1
        print("All requested exports succeeded. Compare the oldest dates and totals with your app; server coverage is unverified.")
        return 0
    except (ExportError, FileExistsError) as exc:
        print("Error: " + ("Output folder already exists. Choose a new folder." if isinstance(exc, FileExistsError) else str(exc)), file=sys.stderr)
        return 1
    except OSError:
        print("Could not write the backup. Check folder permissions and free space. Any saved files remain in the output folder.", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCanceled. Any files already downloaded remain in the output folder.", file=sys.stderr)
        return 1
    finally:
        client.token = None
        client.uid = None


if __name__ == "__main__":
    sys.exit(main())
