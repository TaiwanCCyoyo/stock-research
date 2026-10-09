"""Pure expansion of a versioned value-chain snapshot into research groups."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


class SectorGroupError(ValueError):
    """The supplied taxonomy or group configuration is malformed."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SectorGroupError(f"{name} must be a nonempty string")
    return value


def _selector(value: Any) -> tuple[str, str | None]:
    if not isinstance(value, dict):
        raise SectorGroupError("selector must be an object")
    node = value.get("node_code")
    return _text(value.get("chain_code"), "selector.chain_code"), None if node is None else _text(node, "selector.node_code")


def _source_id(snapshot: dict[str, Any]) -> str:
    for key in ("snapshot_id", "id"):
        value = snapshot.get(key)
        if isinstance(value, str) and value:
            return value
    raise SectorGroupError("snapshot needs snapshot_id")


def build_groups(
    snapshot: dict[str, Any], config: dict[str, Any], securities: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build focused and official-chain groups from caller-supplied metadata only.

    Config selectors have the shape ``{"chain_code": "memory", "node_code": "dram"}``.
    A group may name ``parent_id`` to express presentation hierarchy; it never changes
    membership.  All return collections and member lists have stable lexical ordering.
    """
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
        raise SectorGroupError("snapshot must use schema_version 1")
    if not isinstance(config, dict) or config.get("schema_version") != "sector-groups.v1":
        raise SectorGroupError("config must use sector-groups.v1")
    if not isinstance(securities, list) or any(not isinstance(item, dict) for item in securities):
        raise SectorGroupError("securities must be a list of objects")
    source_snapshot_id = _source_id(snapshot)
    chains = snapshot.get("chains")
    if not isinstance(chains, list):
        raise SectorGroupError("snapshot.chains must be a list")
    if not isinstance(snapshot.get("symbols"), dict):
        raise SectorGroupError("snapshot.symbols must be an object")

    security_by_code: dict[str, dict[str, Any]] = {}
    for security in securities:
        security_id, code = _text(security.get("security_id"), "security_id"), _text(security.get("code"), "code")
        if security_id != f"TW:{code}" or code in security_by_code:
            raise SectorGroupError("securities need unique TW:code identities")
        security_by_code[code] = security

    node_data: dict[tuple[str, str], dict[str, Any]] = {}
    chain_data: dict[str, dict[str, Any]] = {}
    for chain in chains:
        if not isinstance(chain, dict):
            raise SectorGroupError("chain must be an object")
        chain_code = _text(chain.get("code"), "chain.code")
        if chain_code in chain_data:
            raise SectorGroupError("duplicate chain code")
        nodes = chain.get("nodes")
        if not isinstance(nodes, list):
            raise SectorGroupError("chain.nodes must be a list")
        chain_data[chain_code] = chain
        for node in nodes:
            if not isinstance(node, dict):
                raise SectorGroupError("node must be an object")
            node_code = _text(node.get("code"), "node.code")
            key = (chain_code, node_code)
            if key in node_data:
                raise SectorGroupError("duplicate node code within chain")
            members = node.get("members", [])
            if not isinstance(members, list):
                raise SectorGroupError("node.members must be a list")
            source_codes = []
            for member in members:
                if not isinstance(member, dict):
                    raise SectorGroupError("node member must be an object")
                source_codes.append(_text(member.get("code"), "member.code"))
            parent = node.get("parent_code")
            if parent is not None:
                parent = _text(parent, "node.parent_code")
            node_data[key] = {"raw": node, "parent": parent, "source_codes": tuple(sorted(set(source_codes)))}

    children: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for (chain_code, node_code), item in node_data.items():
        parent = item["parent"]
        if parent is not None:
            parent_key = (chain_code, parent)
            if parent_key not in node_data:
                raise SectorGroupError("node parent does not exist in chain")
            children[parent_key].append((chain_code, node_code))

    ancestry: dict[tuple[str, str], tuple[str, ...]] = {}
    expanded_source_codes: dict[tuple[str, str], tuple[str, ...]] = {}
    visiting: set[tuple[str, str]] = set()

    def visit(key: tuple[str, str]) -> None:
        if key in ancestry:
            return
        if key in visiting:
            raise SectorGroupError("node parent cycle")
        visiting.add(key)
        parent = node_data[key]["parent"]
        if parent is None:
            ancestors: tuple[str, ...] = ()
        else:
            parent_key = (key[0], parent)
            visit(parent_key)
            ancestors = (parent, *ancestry[parent_key])
        ancestry[key] = ancestors
        visiting.remove(key)

    for key in sorted(node_data):
        visit(key)

    def expand(key: tuple[str, str]) -> tuple[str, ...]:
        if key not in expanded_source_codes:
            codes = set(node_data[key]["source_codes"])
            for child in children[key]:
                codes.update(expand(child))
            expanded_source_codes[key] = tuple(sorted(codes))
        return expanded_source_codes[key]

    for key in sorted(node_data):
        expand(key)

    def selected_codes(selector: tuple[str, str | None]) -> set[str]:
        chain_code, node_code = selector
        if node_code is None:
            return {code for key, codes in expanded_source_codes.items() if key[0] == chain_code for code in codes}
        return set(expanded_source_codes[(chain_code, node_code)])

    direct_memberships: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    ancestor_memberships: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for (chain_code, node_code), item in node_data.items():
        for code in item["source_codes"]:
            if code in security_by_code:
                direct_memberships[code][chain_code].add(node_code)
                ancestor_memberships[code][chain_code].update(ancestry[(chain_code, node_code)])

    taxonomy_nodes = []
    for (chain_code, node_code), item in sorted(node_data.items()):
        raw = item["raw"]
        direct = sorted(code for code in item["source_codes"] if code in security_by_code)
        expanded = sorted(code for code in expanded_source_codes[(chain_code, node_code)] if code in security_by_code)
        parent = item["parent"]
        taxonomy_nodes.append({
            "node_id": f"official:{chain_code}:{node_code}",
            "chain_code": chain_code,
            "node_code": node_code,
            "name": _text(raw.get("name"), "node.name"),
            "parent_node_id": f"official:{chain_code}:{parent}" if parent else None,
            "ancestor_node_codes": list(ancestry[(chain_code, node_code)]),
            "direct_member_security_ids": [security_by_code[code]["security_id"] for code in direct],
            "expanded_member_security_ids": [security_by_code[code]["security_id"] for code in expanded],
            "source_member_codes": list(item["source_codes"]),
        })

    configured = config.get("groups")
    if not isinstance(configured, list):
        raise SectorGroupError("config.groups must be a list")
    seen_group_ids: set[str] = set()
    configs: list[dict[str, Any]] = []
    for group in configured:
        if not isinstance(group, dict):
            raise SectorGroupError("configured group must be an object")
        group_id = _text(group.get("group_id"), "group_id")
        if group_id in seen_group_ids or group_id.startswith("official:"):
            raise SectorGroupError("duplicate or reserved group_id")
        seen_group_ids.add(group_id)
        parent_id = group.get("parent_id")
        if parent_id is not None:
            parent_id = _text(parent_id, "parent_id")
        selectors = group.get("selectors", [])
        excludes = group.get("exclude_selectors", [])
        if not isinstance(selectors, list) or not selectors or not isinstance(excludes, list):
            raise SectorGroupError("group selectors must be a nonempty list and exclusions a list")
        selected = tuple(_selector(selector) for selector in selectors)
        excluded = tuple(_selector(selector) for selector in excludes)
        for selector in (*selected, *excluded):
            if selector[0] not in chain_data or (selector[1] is not None and selector not in node_data):
                raise SectorGroupError("selector does not exist")
        configs.append({"raw": group, "group_id": group_id, "parent_id": parent_id, "selectors": selected, "excludes": excluded})
    parents = {item["group_id"]: item["parent_id"] for item in configs}
    for group_id, parent_id in parents.items():
        if parent_id is not None and parent_id not in parents:
            raise SectorGroupError("configured group parent does not exist")
        walked: set[str] = set()
        current = group_id
        while parents[current] is not None:
            if current in walked:
                raise SectorGroupError("configured group parent cycle")
            walked.add(current)
            current = parents[current]

    groups: list[dict[str, Any]] = []
    focused_members: dict[str, set[str]] = defaultdict(set)
    for item in sorted(configs, key=lambda value: value["group_id"]):
        included_codes = set().union(*(selected_codes(selector) for selector in item["selectors"]))
        excluded_codes = set().union(*(selected_codes(selector) for selector in item["excludes"])) if item["excludes"] else set()
        codes = sorted((included_codes - excluded_codes) & security_by_code.keys())
        member_ids = [security_by_code[code]["security_id"] for code in codes]
        focused_members[item["group_id"]].update(codes)
        raw = item["raw"]
        selector_chains = {selector[0] for selector in (*item["selectors"], *item["excludes"])}
        groups.append({
            "group_id": item["group_id"],
            "label": _text(raw.get("label"), "label"),
            "kind": raw.get("kind", "focused"),
            "parent_id": item["parent_id"],
            "source_snapshot_id": source_snapshot_id,
            "source_selectors": [{"chain_code": chain_code, "node_code": node_code} for chain_code, node_code in item["selectors"]],
            "source_exclusion_selectors": [{"chain_code": chain_code, "node_code": node_code} for chain_code, node_code in item["excludes"]],
            "member_security_ids": member_ids,
            "source_urls": sorted({_text(chain_data[chain_code].get("source_url"), "chain.source_url") for chain_code in selector_chains}),
        })
    for chain_code, chain in sorted(chain_data.items()):
        codes = sorted({code for (chain, _), item in node_data.items() if chain == chain_code for code in item["source_codes"] if code in security_by_code})
        groups.append({
            "group_id": f"official:{chain_code}",
            "label": _text(chain.get("name"), "chain.name"),
            "kind": "official_chain",
            "parent_id": None,
            "source_snapshot_id": source_snapshot_id,
            "source_selectors": [
                {"chain_code": chain_code, "node_code": node_code} for source_chain, node_code in sorted(node_data) if source_chain == chain_code
            ],
            "member_security_ids": [security_by_code[code]["security_id"] for code in codes],
            "source_urls": [_text(chain.get("source_url"), "chain.source_url")],
        })

    enriched = []
    for security in securities:
        code = security["code"]
        memberships = [
            {"chain_code": chain_code, "direct_node_codes": sorted(nodes), "ancestor_node_codes": sorted(ancestor_memberships[code][chain_code])}
            for chain_code, nodes in sorted(direct_memberships[code].items())
        ]
        group_ids = sorted(group["group_id"] for group in groups if security["security_id"] in group["member_security_ids"])
        if not memberships:
            status, reason = "source_missing", "security_code_not_in_source_members"
        elif any(not group_id.startswith("official:") for group_id in group_ids):
            status, reason = "classified", None
        else:
            status, reason = "official_only", None
        row = dict(security)
        row.update({"group_ids": group_ids, "official_memberships": memberships, "coverage_status": status, "coverage_reason": reason})
        enriched.append(row)
    return groups, enriched, taxonomy_nodes
