"""Portable two-step Geoapify MCP demonstration, standard-library only.

Default mode is fully synthetic and never reads credentials or opens a socket.
Live mode requires an explicit approval flag and GEOAPIFY_API_KEY.
It verifies dispatch lineage, not independent geospatial correctness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ENDPOINT = "https://api.geoapify.com/v1/mcp"
PROTOCOL = "2025-06-18"
TOOLS = ("geocode_address", "reverse_geocode_coordinates")
MAX_CALLS = 2
MAX_RESERVED = 2.0
REDACTED_QUERY = "Unter den Linden 1, Berlin"


class DemoError(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise DemoError("REDIRECT_REFUSED")


class McpSession:
    def __init__(self, *, live=False, api_key=None):
        if live and not api_key:
            raise DemoError("GEOAPIFY_API_KEY_MISSING")
        self.live = bool(live)
        self.api_key = api_key if live else None
        self.session_id = None
        self.next_id = 1
        self.calls = 0
        self.reserved = 0.0
        self.sent = []
        self.last_call_at = None
        self.opener = urllib.request.build_opener(NoRedirect())

    def post(self, method, params=None):
        params = params or {}
        if method == "tools/call":
            name = params.get("name")
            if name not in TOOLS:
                raise DemoError("TOOL_NOT_WHITELISTED")
            if self.calls >= MAX_CALLS or self.reserved + 1.0 > MAX_RESERVED:
                raise DemoError("CALL_OR_CREDIT_CEILING")
            self.calls += 1
            self.reserved += 1.0
            if self.live and self.last_call_at is not None:
                delay = 1.2 - (time.monotonic() - self.last_call_at)
                if delay > 0:
                    time.sleep(delay)
            self.last_call_at = time.monotonic()

        payload = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params}
        self.next_id += 1
        request_bytes = canonical(payload)

        if self.live:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": PROTOCOL,
                "User-Agent": "GeoAgent-Public-Walkthrough/1.0",
                "x-api-key": self.api_key,
            }
            if self.session_id:
                headers["Mcp-Session-Id"] = self.session_id
            req = urllib.request.Request(ENDPOINT, data=request_bytes, headers=headers, method="POST")
            try:
                with self.opener.open(req, timeout=30) as response:
                    if response.status != 200:
                        raise DemoError("HTTP_" + str(response.status))
                    raw = response.read(4_000_001)
                    content_type = response.headers.get("Content-Type", "")
                    sid = response.headers.get("Mcp-Session-Id")
                    if sid:
                        self.session_id = sid
            except urllib.error.HTTPError as exc:
                raise DemoError("HTTP_" + str(exc.code)) from None
            except urllib.error.URLError:
                raise DemoError("NETWORK_ERROR") from None
            except TimeoutError:
                raise DemoError("TIMEOUT") from None
            if len(raw) > 4_000_000:
                raise DemoError("RESPONSE_TOO_LARGE")
            text = raw.decode("utf-8")
            if "text/event-stream" in content_type.lower():
                items = [s[5:].strip() for s in text.splitlines() if s.startswith("data:")]
                if not items:
                    raise DemoError("SSE_WITHOUT_DATA")
                text = items[-1]
            try:
                doc = json.loads(text)
            except ValueError:
                raise DemoError("RESPONSE_NOT_JSON") from None
        else:
            doc = synthetic_response(payload)
            raw = canonical(doc)

        if not isinstance(doc, dict) or doc.get("jsonrpc") != "2.0":
            raise DemoError("MALFORMED_JSONRPC")
        if doc.get("error"):
            raise DemoError("JSONRPC_ERROR")
        result = doc.get("result")
        error_flag = result.get("isError") if isinstance(result, dict) else None
        if not isinstance(result, dict) or error_flag is True or error_flag == 1 or (isinstance(error_flag, str) and error_flag.strip().lower() in {"true", "1", "yes"}):
            raise DemoError("PROVIDER_ERROR_OR_MISSING_RESULT")

        evidence = {
            "method": method,
            "tool": params.get("name") if method == "tools/call" else None,
            "request_sha256": sha(request_bytes),
            "response_sha256": sha(raw),
            "capture_layer": "MCP_CLIENT_OBSERVABLE" if self.live else "SYNTHETIC",
        }
        self.sent.append(evidence)
        return result, evidence


def synthetic_response(payload):
    method = payload["method"]
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL, "capabilities": {}, "serverInfo": {"name": "synthetic-stub"}}
    elif method == "tools/list":
        result = {"tools": [
            {"name": "geocode_address", "inputSchema": {"type": "object", "required": ["query"]}},
            {"name": "reverse_geocode_coordinates",
             "inputSchema": {"type": "object", "required": ["lat", "lon"]}},
        ]}
    elif method == "tools/call":
        if payload["params"]["name"] == "geocode_address":
            result = {"structuredContent": {"count": 1, "results": [
                {"lat": 52.5172707, "lon": 13.3978233, "formatted": "SYNTHETIC_TEST_LOCATION"}
            ]}}
        else:
            args = payload["params"]["arguments"]
            result = {"structuredContent": {"count": 1, "results": [
                {"lat": args["lat"], "lon": args["lon"], "formatted": "SYNTHETIC_REVERSE_RESULT"}
            ]}}
    else:
        raise DemoError("UNSUPPORTED_METHOD")
    return {"jsonrpc": "2.0", "id": payload["id"], "result": result}


def structured(result):
    data = result.get("structuredContent")
    if isinstance(data, dict):
        return data
    for item in result.get("content") or []:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            try:
                data = json.loads(item["text"])
            except ValueError:
                continue
            if isinstance(data, dict):
                return data
    raise DemoError("UNSUPPORTED_RESPONSE_SHAPE")


def first_coordinates(result):
    data = structured(result)
    items = data.get("results")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise DemoError("NO_GEOCODE_RESULT")
    point = items[0]
    lat, lon = point.get("lat"), point.get("lon")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (lat, lon)):
        raise DemoError("INVALID_COORDINATE_TYPE")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise DemoError("COORDINATE_OUT_OF_RANGE")
    return {"lat": lat, "lon": lon}


def run_chain(session):
    session.post("initialize", {
        "protocolVersion": PROTOCOL,
        "capabilities": {},
        "clientInfo": {"name": "geoagent-public-walkthrough", "version": "1.0.0"},
    })
    listed, _ = session.post("tools/list")
    by_name = {x.get("name"): x for x in listed.get("tools") or [] if isinstance(x, dict)}
    if any(name not in by_name for name in TOOLS):
        raise DemoError("TOOL_CATALOGUE_DRIFT")
    required = (("geocode_address", {"query"}), ("reverse_geocode_coordinates", {"lat", "lon"}))
    for name, fields in required:
        schema = by_name[name].get("inputSchema") or {}
        if not fields.issubset(set(schema.get("required") or [])):
            raise DemoError("TOOL_SCHEMA_DRIFT")

    first, evidence1 = session.post("tools/call", {
        "name": "geocode_address", "arguments": {"query": REDACTED_QUERY},
    })
    source = first_coordinates(first)
    reverse_args = dict(source)
    second, evidence2 = session.post("tools/call", {
        "name": "reverse_geocode_coordinates", "arguments": reverse_args,
    })
    reverse_data = structured(second)
    lineage = {
        "source_tool": "geocode_address",
        "target_tool": "reverse_geocode_coordinates",
        "source_response_sha256": evidence1["response_sha256"],
        "lat_value_sha256": sha(canonical(source["lat"])),
        "lon_value_sha256": sha(canonical(source["lon"])),
        "resolved_arguments": reverse_args,
        "arguments_equal_first_response": reverse_args == first_coordinates(first),
        "reference_strings_sent": False,
    }
    return {
        "schema": "geoagent.public-two-step/1",
        "at": datetime.now(timezone.utc).isoformat(),
        "source": "LIVE" if session.live else "SYNTHETIC",
        "network_tools_calls": session.calls if session.live else 0,
        "simulated_tools_calls": 0 if session.live else session.calls,
        "credits_reserved": session.reserved if session.live else 0,
        "credits_observed": None,
        "tools": list(TOOLS),
        "lineage": lineage,
        "request_response_hashes": [evidence1, evidence2],
        "reverse_result_count": reverse_data.get("count"),
        "dispatch_lineage": "PASS" if lineage["arguments_equal_first_response"] else "FAIL",
        "independent_geographic_oracle": "UNKNOWN",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Enable up to two real Geoapify tools/call requests")
    parser.add_argument("--authorize-two-calls", action="store_true",
                        help="Explicit confirmation that two real calls may use free-plan quota")
    parser.add_argument("--out", type=Path, help="Create a JSON report (fails if the file exists)")
    args = parser.parse_args(argv)

    if args.live and not args.authorize_two_calls:
        parser.error("--live requires --authorize-two-calls")
    if args.out and args.out.exists():
        parser.error("--out already exists; refusing to overwrite or spend quota")
    api_key = os.environ.get("GEOAPIFY_API_KEY") if args.live else None
    session = McpSession(live=args.live, api_key=api_key)
    try:
        report = run_chain(session)
    except DemoError as exc:
        report = {
            "schema": "geoagent.public-two-step/1",
            "source": "LIVE" if args.live else "SYNTHETIC",
            "verdict": "STOPPED",
            "reason": str(exc),
            "attempts_booked": session.calls,
            "credits_reserved": session.reserved if args.live else 0,
            "credits_observed": None,
            "observed_exchanges": session.sent,
        }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("dispatch_lineage") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
