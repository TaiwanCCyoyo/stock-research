# Classification evidence supplement v1

This is a supplemental `opportunity-classification-evidence.v1` data packet for
eight existing real cases. The saved producer, its selections and original
classification snapshot remain unchanged. The website owns the consumer adapter.

## Independent layers

| Field                           | Meaning                                                                         | Historical use                                                                                             |
| ------------------------------- | ------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `official_industry_snapshot`    | Preserved official broad industry label                                         | Display as an explicitly dated reference; no invented historical exchange membership                       |
| `official_value_chain_snapshot` | Direct official chain/node memberships; all matching nodes preserved            | Reference labels, with independently unknown effective intervals                                           |
| `research_group_snapshot`       | Existing catalog mappings from nodes to business groups                         | Analyst grouping, not a replacement official industry code                                                 |
| `company_business_assertions`   | Direct company role/product evidence or an explicitly identified sector mapping | Use documented coverage for retrospective context; preserve first-availability and effective-boundary gaps |

The exchange broad label **其他業** is a known classification value, not missing
data. Node codes such as T100 and FB00 belong to the value-chain taxonomy and must
not become exchange industry codes. An issuer can have multiple nodes, products
and roles; none is automatically its principal business or a growth driver.

## Time and provenance

- `metadata_fetched_at`: original issuer metadata timestamp, independent of chain
  snapshot retrieval and this packet's build time.
- `snapshot_recorded_at`: recorded classification artifact timestamp. A catalog-wide
  timestamp does not prove a separate fetch time for every chain.
- `document_covered_period`: what the source actually describes, using `from` and
  `until_exclusive` with a precision. This is not a membership interval.
- `effective_interval`: verified classification/role onset and cessation. Null in
  this packet. A fiscal-year description does not establish continuity every day.
- `published_at` / `first_available_at`: null unless independently verified. PDF
  creation metadata, a search crawler's date or a retrieval date is not publication.
- `source_ref`: source registry identity plus a locator. Raw-file digests and
  canonical JSON digests state their exact basis. An observation digest identifies
  retained notes/excerpts, not the unseen original HTML/PDF bytes.

No missing timestamp is filled with this packet's creation date. Retrospective
evidence may have been published after the displayed observation date and cannot
be used as an input to a point-in-time trading signal without a separate check.

## Presentation behavior recommended to the website

1. Retain known broad labels even when fine role evidence or historical dates are
   missing. Each layer carries its own missing reason. Unknown dates must not
   replace a known label with an undifferentiated industry-unknown value.
2. Resolve official historical exchange membership only from a verified effective
   interval. Show snapshot reference labels with their original metadata date.
3. For retrospective business grouping, use company assertions whose **document
   coverage** contains the observation date. Label the basis as a retrospective
   document-period classification. This grouping is distinct from exchange
   membership and from a rule available on that date.
4. Within matching claims, preserve multiple labels. If sources conflict, expose
   both claims and the conflict; do not silently take the last row or pick a main
   business. Undated assertions are reference information only.
5. Yang Ming on 2021-07-23 can display **航運 / 貨櫃航運** with the 2021 annual-report
   basis. The broad business-sector mapping is explicitly derived from its direct
   container-line operator role; the exact exchange-classification interval stays
   unverified. The report also discusses 2022 plans: they are not 2021 operations.
6. This packet is evidence for eight fixed examples, not a full market inventory,
   a completed 200-issuer evidence queue, or an approved leader-selection model.

## Small recomputable record

`classification-v1.json` contains normalized layers and source locators;
`sources-v1.json` retains short observations and file identities;
`gaps-v1.json` records independent gaps; `verification-receipt.json` binds these
files after formatting. Raw company documents and probes stay in this worktree's
`.tmp/classification-sources/`. Their future backup/collection ownership is a
separate owner decision, not established by this small curated supplement.
