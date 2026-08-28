"""Mutations for the narrowing contract over the frozen SFIR8 bytes.

Each entry is one specific weakening, written by hand: what it changes,
and the text it replaces. Lifted verbatim from the driver that first ran
them, so the committed table is the table that produced the recorded
result.
"""

from __future__ import annotations

TARGET = 'tools/sfir9_transport.py'

TESTS = ['tests/test_sfir9_transport.py']

MUTATIONS = [
    # -- upstream binding
    ("X1 the content hash is not compared",
     "        if observed_sha != pinned.sha256:", "        if False:"),
    ("X2 the git blob id is not compared",
     "        if observed_blob != pinned.git_blob_id:", "        if False:"),
    ("X3 committed bytes are not compared with working bytes",
     "        if committed != working:", "        if False:"),
    ("X4 committed and working are compared by length instead of bytes",
     "        if committed != working:", "        if len(committed) != len(working):"),
    ("X5 a missing import origin is treated as passing",
     "        if origin is None:", "        if False:"),
    ("X6 the import origin directory is not checked",
     "        if resolved.parent != expected_directory or resolved.name != path.name:",
     "        if False:"),
    ("X7 the origin check accepts any directory named tools",
     "        if resolved.parent != expected_directory or resolved.name != path.name:",
     '        if resolved.parent.name != "tools":'),
    ("X8 the manifest is narrowed by one module",
     '        module="sfir8_checkpoint",', '        module="sfir8_checkpoint_REMOVED",'),
    ("X9 the git blob id omits the object header",
     "    header = f\"blob {len(raw)}\\0\".encode()\n    return hashlib.sha1(header + raw).hexdigest()",
     "    return hashlib.sha1(raw).hexdigest()"),
    ("X10 the git blob id omits the length",
     "    header = f\"blob {len(raw)}\\0\".encode()", "    header = b\"blob \\0\""),

    # -- target gating
    ("X11 the scheme is not checked",
     "    if parts.scheme != ALLOWED_SCHEME:", "    if False:"),
    ("X12 the host is not checked",
     "    if parts.hostname != ALLOWED_HOST:", "    if False:"),
    ("X13 the host is matched by suffix, so a lookalike domain passes",
     "    if parts.hostname != ALLOWED_HOST:",
     "    if not (parts.hostname or '').endswith(ALLOWED_HOST):"),
    ("X14 the target is not checked before the request is issued",
     "        require_permitted_target(url)\n        require_no_scientific_input(context",
     "        require_no_scientific_input(context"),
    ("X15 redirect hops are not re-checked against the surface",
     "            require_permitted_target(atom.requested_url)", "            pass"),

    # -- redirects and hops
    ("X16 hops are not recorded individually",
     "        for atom in record.atoms:", "        for atom in record.atoms[:1]:"),
    ("X19 the surface claims automatic following is permitted",
     '            "automatic_following": False,', '            "automatic_following": True,'),

    # -- identity
    ("X20 the numeric id is not compared",
     "        if observed is None or str(observed) != str(host_uuid):", "        if False:"),
    ("X21 the numeric id is compared loosely so any id passes",
     "        if observed is None or str(observed) != str(host_uuid):",
     "        if observed is None:"),
    ("X22 a non-200 metadata response is accepted",
     '        if entry["status"] != 200 or not isinstance(body, dict):', "        if False:"),
    ("X23 the canonical address is adopted before the identity is proved",
     "        if identity is None or not identity.verified:", "        if identity is None:"),
    ("X24 an unverified identity still yields the canonical address",
     "        if self.verified and self.canonical_address:", "        if self.canonical_address:"),

    # -- counters
    ("X25 hops are counted as logical requests",
     "            logical_requests=len(self.logical_requests),",
     "            logical_requests=len(self.hops),"),
    ("X26 logical requests are counted as hops",
     "            network_hops=len(self.hops),",
     "            network_hops=len(self.logical_requests),"),
    ("X27 provider charges are inferred from hop count",
     "            provider_charged_requests=sum(self._charges),",
     "            provider_charged_requests=len(self.hops),"),
    ("X28 a charge is dropped when it is recorded",
     "        if charge is not None:\n            self._charges.append(charge)",
     "        if False:\n            self._charges.append(charge)"),

    # -- provider accounting
    ("X29 the provider delta is not computed",
     "            None if window_used_delta is None else window_used_delta - charge_sum",
     "            0"),
    ("X30 a non-zero delta is reported as complete",
     '            "accounting_is_complete": unattributed == 0,',
     '            "accounting_is_complete": True,'),

    # -- rate window
    ("X31 the per-retry fail-safe is not enforced",
     "    if needed > protocol.RETRY_WAIT_SECONDS:", "    if False:"),
    ("X32 the cumulative fail-safe is not enforced",
     "    if cumulative_waited_seconds + needed > protocol.TOTAL_WAIT_SECONDS:",
     "    if False:"),
    ("X33 the per-retry fail-safe is widened by a local literal",
     "    if needed > protocol.RETRY_WAIT_SECONDS:", "    if needed > 3600:"),
    ("X34 an unbounded window is waited on instead of closing the segment",
     "    elif reset_epoch is None:\n        return WaitDecision(\n            SEGMENT_CLOSE_RATE_WINDOW,",
     "    elif reset_epoch is None:\n        return WaitDecision(\n            WAIT,"),
    ("X35 Retry-After is ignored when the counter looks healthy",
     "    if retry_after is None and (remaining is None or remaining > 0):",
     "    if remaining is None or remaining > 0:"),
    ("X36 a closed segment keeps issuing requests",
     "        if self.segment_closed is not None:", "        if False:"),
    ("X37 the closed-segment gate is not reached from get",
     "        self._require_open()\n        require_permitted_target(url)",
     "        require_permitted_target(url)"),
    ("X39 the segment is not marked closed",
     "            self.segment_closed = SEGMENT_CLOSE_RATE_WINDOW", "            pass"),
    ("X40 the wait is announced but never taken",
     "            self._sleep(decision.seconds)", "            pass"),
    ("X41 cumulative waiting is not accumulated",
     "            self.cumulative_waited_seconds += decision.seconds", "            pass"),
    ("X42 observing the rate window sends a probe",
     "        self._provider_remaining = remaining\n        self._provider_reset = reset_epoch",
     '        self.get(f"https://{ALLOWED_HOST}/rate_limit")\n        self._provider_remaining = remaining\n        self._provider_reset = reset_epoch'),

    # -- result awareness
    ("X43 a scientific quantity is filtered instead of refusing",
     "    if present:", "    if False:"),
    ("X44 the forbidden set is narrowed",
     '        "candidate_count",\n        "candidate_identities",', '        "candidate_identities",'),
    ("X45 the get path stops checking its context",
     '        require_no_scientific_input(context, "Sfir9Transport.get context")', "        pass"),
    ("X46 the handoff path stops checking its extras",
     '        require_no_scientific_input(extra, "Sfir9Transport.handoff")', "        pass"),

    # -- handoff
    ("X47 the handoff reports a roster it did not traverse",
     "            roster_digest=self.roster_digest,", '            roster_digest="sha256:whatever",'),
    ("X48 the handoff drops the selection digest",
     "            selection_digest=self.selection_digest,", '            selection_digest="",'),
    ("X49 the handoff reports counters it did not observe",
     "            logical_request_count=counters.logical_requests,",
     "            logical_request_count=0,"),
    ("X50 a closed segment is reported as open",
     '            disposition=disposition or self.segment_closed or "SEGMENT_OPEN",',
     '            disposition=disposition or "SEGMENT_OPEN",'),

    # -- credential hygiene
    ("X51 response bodies reach the receipt",
     '                {k: v for k, v in entry.items() if k != "body"}',
     "                dict(entry)"),

    # -- surface
    ("X52 the surface stops binding the protocol digest",
     '        "forbidden_transport_inputs": sorted(FORBIDDEN_TRANSPORT_INPUTS),\n'
     '        "protocol_digest": protocol.Protocol().digest(),',
     '        "forbidden_transport_inputs": sorted(FORBIDDEN_TRANSPORT_INPUTS),\n'
     '        "protocol_digest": "sha256:unbound",'),
    ("X53 the surface stops declaring the rate window",
     '        "rate_window": {', '        "_rate_window": {'),
    ("X54 the surface stops declaring the redirect policy",
     '        "redirect_policy": {', '        "_redirect_policy": {'),
    ("X55 the fail-safes are copied into the surface as literals",
     '            "retry_wait_fail_safe_seconds": protocol.RETRY_WAIT_SECONDS,',
     '            "retry_wait_fail_safe_seconds": 60,'),
]
