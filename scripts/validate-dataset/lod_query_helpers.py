"""Shared LOD query helpers for validation scripts.

This module intentionally contains endpoint/query mechanics that are not
specific to LS/RVA/GS: Wikidata ASK, explicit DBpedia owl:sameAs -> QID
resolution, and query logging. It keeps new validators from importing each
other just to reuse these helpers.
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

DBP_ENDPOINT = "https://dbpedia.org/sparql"
WD_ENDPOINT = "https://query.wikidata.org/sparql"
RES = "http://dbpedia.org/resource/"
DBO = "http://dbpedia.org/ontology/"
DBP = "http://dbpedia.org/property/"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
WD_ENTITY = "http://www.wikidata.org/entity/"
SPARQL_TIMEOUT_SECONDS = 120
SPARQL_RETRIES = 10
SPARQL_BACKOFF_SECONDS = 1.5
SLEEP_PROGRESS_SECONDS = 30.0
EMPTY_RESULT_CONFIRM_ATTEMPTS = 2
QID_QUERY_ERROR_CACHE_SECONDS = 300.0
IDENTITY_POLICY = "explicit owl:sameAs only; no wikiPageRedirects or Wikidata sitelink fallback"


def normalize_lod_uri(uri: str) -> str:
    """Normalize obvious LOD URI serialization noise without changing identity policy.

    DBpedia occasionally contains resource IRIs whose local part is itself a full
    DBpedia resource IRI, e.g.:
      http://dbpedia.org/resource/http://dbpedia.org/resource/Germany

    The validators are checking explicit facts about the intended DBpedia
    resource, not treating this malformed wrapper as a distinct benchmark entity.
    This narrow normalization only unwraps that exact nested DBpedia-resource
    shape; it does not follow redirects, sameAs, sitelinks, or hierarchy edges.
    """
    nested = RES + RES
    while uri.startswith(nested):
        uri = RES + uri[len(nested):]
    return uri

PARTIAL_RESULT_HEADER_NAMES = (
    "X-SPARQL-Anytime",
    "X-SQL-State",
    "X-SQL-Message",
    "X-SPARQL-MaxRows",
    "X-Exec-Milliseconds",
    "X-Exec-DB-Activity",
)


def _ssl_context() -> ssl.SSLContext:
    """Verified context via certifi if available; else unverified.

    Some Python installs lack a usable CA bundle. These validators only perform
    read-only public ASK/SELECT checks, so an unverified fallback is preferable
    to silently classifying everything as endpoint errors.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl._create_unverified_context()


SSL_CTX = _ssl_context()


def _log(message: str) -> None:
    print(message, flush=True)


def _sleep_with_progress(seconds: float, label: str) -> None:
    remaining = seconds
    while remaining > 0:
        chunk = min(SLEEP_PROGRESS_SECONDS, remaining)
        time.sleep(chunk)
        remaining -= chunk
        if remaining > 0:
            _log(f"[retry-sleep] {label}: {remaining:.1f}s remaining")


def _sparql_response_headers(resp) -> dict:
    """Return SPARQL/Virtuoso diagnostic headers relevant to auditability."""
    headers = {}
    for name in PARTIAL_RESULT_HEADER_NAMES:
        value = resp.headers.get(name)
        if value is not None:
            headers[name] = value
    return headers


def _partial_result_reason(headers: dict) -> str | None:
    """Detect Virtuoso/DBpedia partial-result responses.

    DBpedia can return partial answers under Anytime Query behavior. Such
    responses must not be accepted as evidence of absence.
    """
    if headers.get("X-SPARQL-MaxRows"):
        return "partial SPARQL result indicated by X-SPARQL-MaxRows"
    if headers.get("X-SPARQL-Anytime"):
        return f"partial SPARQL result indicated by X-SPARQL-Anytime: {headers['X-SPARQL-Anytime']}"
    if headers.get("X-SQL-State") or headers.get("X-SQL-Message"):
        message = headers.get("X-SQL-Message", "")
        state = headers.get("X-SQL-State", "")
        return f"partial SPARQL result indicated by Virtuoso headers: state={state} message={message[:160]}"
    return None


def _endpoint_name(endpoint: str) -> str:
    if "dbpedia" in endpoint:
        return "DBpedia"
    if "wikidata" in endpoint:
        return "Wikidata"
    return endpoint


def _retry_wait(attempt: int, backoff: float) -> float:
    return backoff * (2 ** (attempt - 1))


def _query_failure_log(
    *,
    endpoint: str,
    query: str,
    timeout: int,
    retries: int,
    attempts: list[dict],
    final_reason: str,
) -> dict:
    return {
        "endpoint": endpoint,
        "query": query,
        "timeout_seconds": timeout,
        "server_timeout_ms": timeout * 1000 if endpoint == DBP_ENDPOINT else None,
        "max_retries": retries,
        "attempts": attempts,
        "final_reason": final_reason,
    }


def _http_error_body(e: urllib.error.HTTPError, limit: int = 4096) -> str:
    try:
        return e.read(limit).decode("utf-8", "replace")
    except Exception:
        return ""


def ask_endpoint(
    endpoint: str,
    query: str,
    timeout: int = SPARQL_TIMEOUT_SECONDS,
    retries: int = SPARQL_RETRIES,
    backoff: float = SPARQL_BACKOFF_SECONDS,
    label: str = "ASK",
    confirm_false_attempts: int = 1,
):
    confirm_false_attempts = max(1, confirm_false_attempts)
    params = {"query": query, "format": "json"}
    server_timeout_ms = None
    if endpoint == DBP_ENDPOINT:
        server_timeout_ms = int(timeout * 1000)
        params["timeout"] = str(server_timeout_ms)
    url = endpoint + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "RDFS-LLM-Bench/1.0 (research)"})
    last = "unknown"
    attempts: list[dict] = []
    endpoint_label = _endpoint_name(endpoint)
    false_attempts = 0
    for attempt in range(1, retries + 1):
        try:
            _log(f"[query] {endpoint_label} {label}: attempt {attempt}/{retries}, timeout={timeout}s")
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
                response_headers = _sparql_response_headers(resp)
                payload = json.load(resp)
                partial_reason = _partial_result_reason(response_headers)
                if partial_reason:
                    last = partial_reason
                    entry = {
                        "attempt": attempt,
                        "status": "partial",
                        "boolean": bool(payload["boolean"]) if "boolean" in payload else None,
                        "reason": partial_reason,
                        "response_headers": response_headers,
                    }
                    _log(f"[query] {endpoint_label} {label}: attempt {attempt}/{retries} -> PARTIAL ({partial_reason})")
                elif "boolean" not in payload:
                    last = "malformed ASK response: missing boolean"
                    entry = {
                        "attempt": attempt,
                        "status": "malformed",
                        "reason": last,
                        "payload_keys": sorted(payload.keys()),
                        "response_headers": response_headers,
                    }
                    _log(f"[query] {endpoint_label} {label}: attempt {attempt}/{retries} -> malformed (missing boolean)")
                else:
                    value = bool(payload["boolean"])
                    if not value:
                        false_attempts += 1
                    if not value and false_attempts < confirm_false_attempts:
                        last = "ASK false (unconfirmed, retrying)"
                        entry = {
                            "attempt": attempt,
                            "status": "false_unconfirmed",
                            "boolean": False,
                            "reason": last,
                            "false_attempt": false_attempts,
                            "response_headers": response_headers,
                        }
                        _log(f"[query] {endpoint_label} {label}: attempt {attempt}/{retries} -> false unconfirmed")
                    else:
                        attempts.append({
                            "attempt": attempt,
                            "status": "ok",
                            "boolean": value,
                            "retry": False,
                            "response_headers": response_headers,
                        })
                        _log(f"[query] {endpoint_label} {label}: attempt {attempt}/{retries} -> ok boolean={value}")
                        log = {
                            "endpoint": endpoint,
                            "query": query,
                            "timeout_seconds": timeout,
                            "server_timeout_ms": server_timeout_ms,
                            "max_retries": retries,
                            "attempts": attempts,
                        }
                        if confirm_false_attempts > 1:
                            log["false_confirm_attempts"] = confirm_false_attempts
                        return value, None, log
        except urllib.error.HTTPError as e:
            body = _http_error_body(e)
            last = f"HTTP {e.code}"
            entry = {"attempt": attempt, "status": "error", "reason": last}
            if body:
                entry["response_body_excerpt"] = body[:500]
            _log(f"[query] {endpoint_label} {label}: attempt {attempt}/{retries} -> {last}")
            if endpoint == WD_ENDPOINT and e.code == 500 and "TimeoutException" in body:
                last = "HTTP 500 WDQS TimeoutException"
                entry["reason"] = last
                entry["retry"] = False
                attempts.append(entry)
                return None, last, _query_failure_log(
                    endpoint=endpoint,
                    query=query,
                    timeout=timeout,
                    retries=retries,
                    attempts=attempts,
                    final_reason=last,
                )
            if e.code == 400:
                entry["retry"] = False
                attempts.append(entry)
                return None, last, _query_failure_log(
                    endpoint=endpoint,
                    query=query,
                    timeout=timeout,
                    retries=retries,
                    attempts=attempts,
                    final_reason=last,
                )
        except Exception as e:
            last = f"{type(e).__name__}: {str(e)[:80]}"
            entry = {"attempt": attempt, "status": "error", "reason": last}
            _log(f"[query] {endpoint_label} {label}: attempt {attempt}/{retries} -> {last}")
        if attempt < retries:
            wait = _retry_wait(attempt, backoff)
            entry["retry"] = True
            entry["sleep_seconds"] = wait
            attempts.append(entry)
            _log(f"[retry-sleep] {endpoint_label} {label}: sleeping {wait:.1f}s before attempt {attempt + 1}/{retries}")
            _sleep_with_progress(wait, f"{endpoint_label} {label}")
        else:
            entry["retry"] = False
            attempts.append(entry)
    return None, last, _query_failure_log(
        endpoint=endpoint,
        query=query,
        timeout=timeout,
        retries=retries,
        attempts=attempts,
        final_reason=last,
    )


def wd_ask(
    query: str,
    timeout: int = SPARQL_TIMEOUT_SECONDS,
    retries: int = SPARQL_RETRIES,
    backoff: float = SPARQL_BACKOFF_SECONDS,
    label: str = "direct ASK",
):
    return ask_endpoint(WD_ENDPOINT, query, timeout=timeout, retries=retries, backoff=backoff, label=label)


_QID_CACHE: dict[str, tuple[list[str] | None, str | None, dict | None]] = {}
_QID_QUERY_ERROR_CACHE: dict[str, tuple[list[str] | None, str | None, dict | None, float]] = {}


def _is_intermediate_node(local_name: str) -> bool:
    return "__" in local_name


def _select_rows(endpoint: str, query: str, var: str, confirm_empty: bool = False, label: str = "SELECT"):
    server_timeout_ms = None
    params = {
        "query": query,
        "format": "application/sparql-results+json" if "dbpedia" in endpoint else "json",
    }
    if endpoint == DBP_ENDPOINT:
        server_timeout_ms = SPARQL_TIMEOUT_SECONDS * 1000
        params["timeout"] = str(server_timeout_ms)
    url = endpoint + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "RDFS-LLM-Bench/1.0 (research)"})
    last = "unknown"
    attempts: list[dict] = []
    empty_attempts = 0
    endpoint_label = _endpoint_name(endpoint)
    for attempt in range(1, SPARQL_RETRIES + 1):
        try:
            _log(f"[query] {endpoint_label} {label}: attempt {attempt}/{SPARQL_RETRIES}, timeout={SPARQL_TIMEOUT_SECONDS}s")
            with urllib.request.urlopen(req, timeout=SPARQL_TIMEOUT_SECONDS, context=SSL_CTX) as resp:
                response_headers = _sparql_response_headers(resp)
                rows = json.load(resp)["results"]["bindings"]
                values = [row[var]["value"] for row in rows]
                partial_reason = _partial_result_reason(response_headers)
                if partial_reason:
                    last = partial_reason
                    entry = {
                        "attempt": attempt,
                        "status": "partial",
                        "row_count": len(values),
                        "reason": partial_reason,
                        "response_headers": response_headers,
                    }
                elif values or not confirm_empty:
                    attempts.append({
                        "attempt": attempt,
                        "status": "ok",
                        "row_count": len(values),
                        "retry": False,
                        "response_headers": response_headers,
                    })
                    return values, None, {
                        "endpoint": endpoint,
                        "query": query,
                        "timeout_seconds": SPARQL_TIMEOUT_SECONDS,
                        "server_timeout_ms": server_timeout_ms,
                        "max_retries": SPARQL_RETRIES,
                        "attempts": attempts,
                    }
                else:
                    empty_attempts += 1
                    last = "empty result (unconfirmed, retrying)"
                    entry = {
                        "attempt": attempt,
                        "status": "empty",
                        "row_count": 0,
                        "reason": last,
                        "empty_attempt": empty_attempts,
                        "response_headers": response_headers,
                    }
                    if empty_attempts >= EMPTY_RESULT_CONFIRM_ATTEMPTS:
                        entry["retry"] = False
                        attempts.append(entry)
                        return [], None, {
                            "endpoint": endpoint,
                            "query": query,
                            "timeout_seconds": SPARQL_TIMEOUT_SECONDS,
                            "server_timeout_ms": server_timeout_ms,
                            "max_retries": SPARQL_RETRIES,
                            "empty_result_confirm_attempts": EMPTY_RESULT_CONFIRM_ATTEMPTS,
                            "attempts": attempts,
                            "final_reason": "empty result confirmed",
                        }
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code == 400:
                attempts.append({"attempt": attempt, "status": "error", "reason": last, "retry": False})
                return None, last, _query_failure_log(
                    endpoint=endpoint,
                    query=query,
                    timeout=SPARQL_TIMEOUT_SECONDS,
                    retries=SPARQL_RETRIES,
                    attempts=attempts,
                    final_reason=last,
                )
            entry = {"attempt": attempt, "status": "error", "reason": last}
        except Exception as e:
            last = f"{type(e).__name__}: {str(e)[:80]}"
            entry = {"attempt": attempt, "status": "error", "reason": last}
        if attempt < SPARQL_RETRIES:
            wait = _retry_wait(attempt, SPARQL_BACKOFF_SECONDS)
            entry["retry"] = True
            entry["sleep_seconds"] = wait
            attempts.append(entry)
            _sleep_with_progress(wait, f"{endpoint_label} {label}")
        else:
            entry["retry"] = False
            attempts.append(entry)
    log = {
        "endpoint": endpoint,
        "query": query,
        "timeout_seconds": SPARQL_TIMEOUT_SECONDS,
        "server_timeout_ms": server_timeout_ms,
        "max_retries": SPARQL_RETRIES,
        "attempts": attempts,
        "final_reason": last,
    }
    return ([], None, log) if last == "empty result (unconfirmed, retrying)" else (None, last, log)


def resolve_wikidata_qids(dbr_uri: str, local_name: str):
    dbr_uri = normalize_lod_uri(dbr_uri)
    if dbr_uri in _QID_CACHE:
        qids, reason, log = _QID_CACHE[dbr_uri]
        return qids, reason, log, True
    if dbr_uri in _QID_QUERY_ERROR_CACHE:
        qids, reason, log, expires_at = _QID_QUERY_ERROR_CACHE[dbr_uri]
        if time.time() < expires_at:
            return qids, reason, log, True
        del _QID_QUERY_ERROR_CACHE[dbr_uri]
    if _is_intermediate_node(local_name):
        result = (None, "intermediate_node", {"resolution": "skipped", "reason": "intermediate_node"})
        _QID_CACHE[dbr_uri] = result
        return (*result, False)
    query = (
        f"SELECT ?wd WHERE {{ <{dbr_uri}> <http://www.w3.org/2002/07/owl#sameAs> ?wd . "
        f'FILTER(STRSTARTS(STR(?wd), "{WD_ENTITY}")) }}'
    )
    qids, reason, log = _select_rows(DBP_ENDPOINT, query, "wd", confirm_empty=True, label=f"sameAs {local_name}")
    if qids:
        result = (qids, None, log)
        _QID_CACHE[dbr_uri] = result
        return (*result, False)
    if qids is None:
        attempts = len((log or {}).get("attempts", []))
        log = {
            **(log or {}),
            "query_error_cache_seconds": QID_QUERY_ERROR_CACHE_SECONDS,
            "query_error_cache_policy": (
                "transient sameAs query errors are cached briefly within a run "
                "to avoid repeated full retries for the same DBpedia resource"
            ),
        }
        result = (None, f"sameAs query error after {attempts} attempts: {reason}", log)
        _QID_QUERY_ERROR_CACHE[dbr_uri] = (*result, time.time() + QID_QUERY_ERROR_CACHE_SECONDS)
        return (*result, False)
    result = (None, "no explicit owl:sameAs", log)
    _QID_CACHE[dbr_uri] = result
    return (*result, False)


def sameas_query_error_reason(*reasons: str | None) -> str | None:
    errors = []
    seen = set()
    for reason in reasons:
        if reason and reason.startswith("sameAs query error") and reason not in seen:
            errors.append(reason)
            seen.add(reason)
    return "; ".join(errors) if errors else None


def identity_resolution_detail(
    *,
    local_name: str,
    dbpedia_uri: str,
    qids,
    reason: str | None,
    query_log: dict | None,
    cache_hit: bool,
) -> dict:
    return {
        "local_name": local_name,
        "dbpedia_uri": dbpedia_uri,
        "resolved": bool(qids),
        "qids": qids or [],
        "reason": reason,
        "cache_hit": cache_hit,
        "query_log": query_log,
    }


def qid_resolution_log(
    s_name: str,
    s_uri: str,
    s_qids,
    s_reason: str | None,
    s_log: dict | None,
    s_cache_hit: bool,
    o_name: str,
    o_uri: str,
    o_qids,
    o_reason: str | None,
    o_log: dict | None,
    o_cache_hit: bool,
) -> dict:
    return {
        "identity_policy": IDENTITY_POLICY,
        "subject": identity_resolution_detail(
            local_name=s_name,
            dbpedia_uri=s_uri,
            qids=s_qids,
            reason=s_reason,
            query_log=s_log,
            cache_hit=s_cache_hit,
        ),
        "object": identity_resolution_detail(
            local_name=o_name,
            dbpedia_uri=o_uri,
            qids=o_qids,
            reason=o_reason,
            query_log=o_log,
            cache_hit=o_cache_hit,
        ),
    }


def missing_qid_reason(s_qids, s_reason: str | None, o_qids, o_reason: str | None) -> str:
    parts = []
    if not s_qids:
        parts.append(f"s={s_reason or 'unresolved'}")
    if not o_qids:
        parts.append(f"o={o_reason or 'unresolved'}")
    return "; ".join(parts)


def wd_direct_ask(s_qids: list[str], o_qids: list[str], p_wd_uri: str, label: str = "direct ASK"):
    p_pid = p_wd_uri.rsplit("/", 1)[-1]
    s_values = " ".join(f"wd:{q.rsplit('/', 1)[-1]}" for q in s_qids)
    o_values = " ".join(f"wd:{q.rsplit('/', 1)[-1]}" for q in o_qids)
    query = f"""ASK {{
  VALUES ?s {{ {s_values} }}
  VALUES ?o {{ {o_values} }}
  ?s wdt:{p_pid} ?o .
}}"""
    return wd_ask(query, label=label)
