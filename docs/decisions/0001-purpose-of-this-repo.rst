0001 Purpose of This Repo
#########################

Status
******

**Draft** (=> Provisional)

Context
*******

Open edX has four search surfaces, three libraries, and no shared engine layer
between them.

* **Studio content search and the Libraries V2 UI** are served by
  ``openedx/core/djangoapps/content/search`` in ``openedx-platform``. It talks
  to Meilisearch directly and is gated on ``MEILISEARCH_ENABLED``. No other
  engine is supported.
* **LMS courseware search and course discovery** are served by ``edx-search``.
  Its README lists four engines: Meilisearch (preferred), Elasticsearch
  (deprecated), Typesense (beta, LMS only), and a mock used in tests.
* **Forum search** is served by ``openedx/forum``, which carries its own
  ``es.py``, ``meilisearch.py`` and ``typesense.py`` under ``forum/search/``.
* **Notes** are served by ``edx-notes-api``, still on Elasticsearch 7 through
  ``django-elasticsearch-dsl-drf``.

Every one of those is a separate engine integration. An operator configures
each independently, and adding an engine means implementing it up to four
times. ``edx-search`` was meant to be the shared layer and is not: two of the
four surfaces were built outside it on purpose.

How the platform arrived here
=============================

``edx-search`` used django-haystack as a cross-engine abstraction. As
``content/search``'s own ADR 0001 records, that "was ripped out after the
package was abandoned upstream and it became an obstacle to upgrades and
efficiently utilizing Elasticsearch (the abstraction layer imposed significant
limits)."

That experience shaped what came next. When Meilisearch was adopted for Studio
search, it was adopted deliberately without an abstraction — but with the
expectation that one might be needed later. That ADR is explicit about it:
Decision 1 adopted Meilisearch "as an experiment and to evaluate it more
thoroughly," and Decision 3 committed to keeping "the Meilisearch-specific code
isolated to the new ``content/search`` Django app, so it's relatively easy to
swap out later if this experiment doesn't pan out." Its status is still
**Draft**. It was never accepted.

The isolation it asked for was largely achieved. Counting engine references
across the app: ``api.py`` holds 115 and is where essentially all engine
coupling lives; ``handlers.py`` has 21, of which 16 are the settings gate and
the rest are prose; ``documents.py`` has 17, all prose or key-slugging helpers;
``tasks.py`` has 16, of which 14 are ``MeilisearchError`` in retry handling —
the one piece of genuine coupling outside ``api.py``. ``views.py``,
``urls.py``, ``models.py`` and ``plain_text_math.py`` have two between them,
both prose.

Meanwhile ``openedx/modular-learning#245`` asked for exactly the layer this
repo is for: "prototype a search abstraction layer for content libraries,"
"prototype a Typesense backend," "refactor Meilisearch support to be a
backend." FC-0091 delivered Typesense backends to ``edx-search``, to
``forum``, and to the docs — but never to ``content/search``, and never as an
abstraction. The result is the split described above: Typesense is a supported
engine for LMS courseware search and forum search, and an unsupported one for
Studio.

Some of that work shipped incomplete rather than merely absent. The forum
Typesense backend was non-functional on every search — ``per_page`` set above
Typesense's hard cap of 250, and a topic filter naming a field the collection
schema does not declare. The fix is ``openedx/forum#289``, with end-to-end
tests against a real Typesense, since the existing tests mocked the client and
so could not observe a rejected request. This is worth stating in an ADR
because it is an argument about *where* engine support should live: a backend
that only one deployment exercises, tested only against a mock, will be broken
and nobody will know.

High availability, and where its licence landed
===============================================

``content/search``'s ADR 0001 gave as its first stated concern that Meilisearch
"doesn't (yet) support High Availability via replication, although this is
planned and under development." That has since been resolved, but not in a way
that helps an operator running the open-source stack.

Meilisearch now splits into two editions. Community Edition is MIT-licensed and
free. Enterprise Edition is licensed under BUSL-1.1 and ships as separate
binaries and Docker images (``getmeili/meilisearch-enterprise``). Replicated
sharding — the feature that answers that concern — requires Enterprise Edition
v1.37 or later. Self-hosted Community Edition still has no replication, and
therefore no high availability.

It is not only new capabilities that landed there. S3-streaming snapshots were
available in Community Edition and were reclassified as an Enterprise feature,
with CE 1.25–1.30 grandfathered. A capability that was open was withdrawn.

This matters more here than it would elsewhere, because it is the same problem
the platform moved to escape. That ADR's first stated objection to
Elasticsearch is that "in 2021, the license of Elasticsearch changed from
Apache 2.0 to a more restrictive license that prohibits providing 'the products
to others as a managed service'," which is "problematic for many Open edX
operators that use AWS and prefer to avoid any third-party services." The
specifics differ — this is a licence on the software rather than on reselling
it — but the position an operator ends up in is the same one, and an operator
who cannot or will not take a commercial licence is left where they started.

Typesense's clustering is not gated this way. It is GPL-3.0, and its
Raft-backed replication is part of the ordinary self-hosted product — the same
``typesense/typesense`` image, configured with a shared nodes file.

Meilisearch remains a good engine, and for a deployment that never needs
replication it remains a reasonable choice. The argument is not that one engine
should replace the other. It is that the platform should not oblige an operator
to run two engines, and that the answer to the platform's high-availability
question should not have to be a commercial licence.

Both engines are Algolia-shaped
===============================

The django-haystack history is the strongest objection to anything proposed
here, and it should be answered rather than waved past.

Haystack failed trying to span engines with genuinely different models —
Elasticsearch, Solr, Whoosh. Meilisearch and Typesense are not that. Both are
Algolia-inspired document stores with closely parallel APIs, and Algolia itself
is a third member of the same family. Abstracting across them is a narrow
problem, not a general one. Elasticsearch and OpenSearch are the opposite case,
and ``modular-learning#245`` already drew that line: the scope "would not try
to stretch to cover more traditional search engines like Elasticsearch, since
doing so would be much more work and present performance concerns."

That line is what keeps this from being haystack again. It also has a practical
payoff: an abstraction designed against two engines from the start will take a
third far more easily than one designed against a single engine and generalised
afterwards. A future Algolia backend is a realistic prospect rather than a
hypothetical: a code search for Algolia across the ``openedx`` org returns
several hundred files, so parts of the estate already speak that dialect.

Feasibility, checked rather than assumed
========================================

A capability-by-capability review found no parity blocker between the two
engines. Each mapping below was executed against a running Typesense 30.2, not
inferred from documentation.

* ``distinctAttribute`` maps to ``group_by``; the ordered
  ``searchableAttributes`` list to ``query_by`` plus explicit
  ``query_by_weights``; ``sortableAttributes`` to per-field ``sort``; and the
  ``rankingRules`` entry that puts ``"sort"`` ahead of relevance needs no
  counterpart, because an explicit ``sort_by`` already outranks text matching.
* The ``create``/``swap_indexes``/``delete`` rebuild becomes a collection alias
  repoint, which is simpler and reclaims disk immediately.
* ``delete_documents(filter=...)`` maps to a ``filter_by`` delete.
* Browser-direct search survives. Typesense scoped search keys are the
  analogue of Meilisearch tenant tokens: an HMAC of a parent key over a rule
  carrying ``filter_by`` and ``expires_at``, derived locally with no API call.
  The embedded filter is enforced server-side — a key scoped to one
  organisation returns nothing for another's content rather than erroring.
* Task polling around every write disappears, because Typesense writes are
  synchronous.

**Multi-select hierarchical faceting works on Typesense.** This was the open
feasibility question, since the Studio tag tree is the one place the current
frontend uses Meilisearch's advanced APIs, and InstantSearch has never
supported multi-select hierarchical menus. ``fetchAvailableTagOptions()`` was
replicated against a real Typesense 30.2 using the document shape
``searchable_doc_tags()`` produces: 29 checks, all passing.
``searchForFacetValues`` maps to ``facet_by`` plus ``facet_query`` with
``per_page=0``; ``tags.taxonomy`` and ``tags.levelN`` map to nested ``string[]``
facet fields; multi-select maps to ``&&`` of ``tags.levelN:=`` terms.
Selections AND correctly across taxonomies and levels.

The part expected to be hard did not arise. Disjunctive faceting looked like
the obstacle and is not, because ``fetchAvailableTagOptions`` never passes the
tags filter into the tree query — only ``extraFilter``, the block-type filter
and the parent filter, so the tree is already computed without the current
selections applied.

Two respects where Typesense fits this UI better: the hard-coded
``meilisearchFacetLimit = 100`` that drives the "not all tags could be
displayed" warning has no equivalent ceiling (300 sibling tags returned in one
request), and because these are ordinary searches rather than a separate
endpoint, the level query and the ``hasChildren`` look-ahead batch into one
``multi_search`` instead of costing two round trips per node.

Two things that need care, neither blocking: shared-prefix siblings still need
the existing exact-parent post-processing, since ``Location > North America >
Canada`` also prefix-matches ``Canada Extra > Nowhere``; and filters must use
``:=`` rather than ``:``, which matches both.

This proves the query mechanics, not a working UI. Rendering and the client
seam are still real work. They are no longer unknown work.

Indexing performance
====================

Measured on one host, same documents, same index size, equivalent
configuration — only the ratios within a single run are meaningful, and the
absolute numbers are machine-specific:

.. list-table::
   :header-rows: 1

   * - index size
     - Meilisearch 1.53.1
     - Typesense 30.2
   * - 50,000
     - 727 ms
     - 4 ms
   * - 150,000
     - 778 ms
     - 3 ms
   * - 300,000
     - 1044 ms
     - 6 ms
   * - 500,000
     - 1142 ms
     - 6 ms

The shape matters more than the ratio: Meilisearch's per-document cost rises
with index size, Typesense's stays flat. The Meilisearch figure is the queued
task's duration, which is what the current code blocks on; the Typesense figure
is a synchronous write, verified searchable immediately after the call returns.

This is context for ``openedx/openedx-platform#38993``, which is about the
indexing bottleneck itself. It is not an argument that one engine is better.
It is an argument that the API this repo exposes must not assume the
Meilisearch task-queue shape, because for one of the two supported engines
there is nothing to poll.

Decision
********

We will build ``openedx-search`` as the single search library for the Open edX
platform, replacing ``edx-search`` and the private engine layer inside
``content/search``.

1. **Use cases are registered, not hard-coded.** Studio content search, library
   search, learner courseware search, course discovery and forum search each
   register a use case that declares its document schema, index settings and
   query shape. Adding a surface does not mean writing another engine
   integration.

2. **Meilisearch and Typesense are both first-class from day one.** Neither is
   a backend bolted on after the interface has been shaped around the other.
   Every use case must work on both, and CI must exercise both against real
   servers rather than mocks.

3. **We do not carry Elasticsearch or OpenSearch forward.** The scope is
   Algolia-shaped engines, per ``modular-learning#245``. This is the boundary
   that keeps the abstraction narrow enough to survive.

4. **Filters are structured, not engine syntax.** Callers build filter terms;
   backends render them. Today ``content/search`` leaks Meilisearch filter
   strings across app boundaries — ``modulestore_migrator``, for one, builds
   ``breadcrumbs.usage_key IN [...]`` by hand.

5. **Index lifecycle is managed, and managed the same way for every use
   case.** Creation, settings changes and rebuilds are versioned and applied
   like migrations, with one set of management commands across all use cases
   rather than per-surface commands that each know one engine.
   See ``openedx-platform#36868``.

6. **Django stays out of the query path.** The browser queries the engine
   directly with a scoped, expiring credential minted locally. Proxying
   searches through the LMS to rewrite them would tie up worker threads for no
   gain. Minting scoped credentials is therefore part of the backend
   interface, not an engine-specific extra.

7. **The frontend gets an engine-agnostic client seam, shipped with this
   library.** It must support multi-select hierarchical facets, which
   InstantSearch does not, and must not require per-engine branching through
   the Authoring MFE component tree.

8. **The public API does not assume asynchronous indexing.** Writes are not
   modelled as "enqueue then poll." Where an engine is genuinely asynchronous,
   that is the backend's concern; where it is synchronous, there is no queue
   to model.

Consequences
************

1. An operator runs one search engine for the whole platform and picks which
   one. Today an operator who wants Typesense for courseware and forum search
   must also run Meilisearch for Studio.

2. ``edx-search`` is superseded. It is not extended: its API mixes
   abstractions with direct engine usage, which is why ``content/search`` was
   built outside it. Migration is per-use-case, and both libraries will exist
   side by side while it happens.

3. ``content/search`` keeps its documents, its Celery tasks and its views, and
   loses its engine layer. Its ADR 0001's Decision 3 anticipated exactly this
   substitution.

4. Two engines must be run in CI. Testing engine integrations against mocks is
   how the forum Typesense backend shipped broken, so this is a requirement
   rather than a nicety. ``content/search``'s ADR 0001 deferred this
   deliberately — its Decision 5 was that "for the experiment, we won't use
   Meilisearch during tests, but we expect to add that in the future if we move
   forward with replacing Elasticsearch completely." This is that future.

5. The Authoring MFE's ``search-manager`` is written against the raw
   ``meilisearch`` JavaScript client. Reworking it behind a client seam is the
   single largest piece of work in this proposal — larger than the backend —
   and it needs its own plan.

6. Result shapes differ and the seam must normalise them. Typesense returns
   ``grouped_hits`` where Meilisearch's ``distinctAttribute`` returns flat
   ``hits``. Highlighting does not map exactly: Typesense decides per field
   whether to snippet and how much context to keep, where Meilisearch crops to
   a token count per attribute. Result cards need a visual pass, not a rename.

7. Some engine differences cannot be abstracted away and must be surfaced
   honestly rather than papered over. Three found while building a Typesense
   schema for the Studio documents, recorded so they are not rediscovered
   painfully:

   * A ``content\..*`` string wildcard field, the pattern ``edx-search`` uses,
     rejects the array sub-fields container documents carry. Explicit
     ``string[]`` overrides must precede the wildcard.
   * ``max_facet_values`` defaults to 10 and also caps the reported total, so a
     truncated facet list is not detectable from the response. Every faceted
     request must set it explicitly. Meilisearch's equivalent defaults to 100.
   * Maximum hits per request differ sharply — Meilisearch 1000, Typesense 250 —
     so anything that pages must take its page size from the backend rather
     than assume one.

Open Questions
**************

* **Which engine is the default?** Both are first-class either way, and the
  default determines what a new deployment gets rather than what is supported.
* **Is Algolia a target?** Nothing here forecloses it, and the two-engine
  design is what makes it cheap. Whether it is in scope for a first release is
  a separate question.
* **Does forum search move into this library, or keep its own backends and
  adopt only the shared index tooling?** Its documents and permissions model
  are unlike the others.
* **What is the deprecation timeline for** ``edx-search``\ **, and for
  Elasticsearch across the platform?** ``edx-notes-api`` is still on
  Elasticsearch 7 and is not addressed by this proposal.

Rejected Alternatives
*********************

Re-architect ``edx-search`` in place
====================================

The obvious option, and what ``edx-search#245`` originally proposed. Rejected
because the useful outcome is a clean surface rather than a compatible one, and
because the existing package carries an Elasticsearch integration, a deprecated
engine, and an API that ``content/search`` was deliberately built to avoid. A
new package can be adopted use case by use case; a rewrite in place cannot.
The name is worth preserving as a redirect, not the code.

Leave each surface with its own engine layer
=============================================

The status quo. It is genuinely cheaper per change and has no abstraction risk.
Rejected because it multiplies every engine decision by four, and because the
forum Typesense backend demonstrates what happens to an integration that only
one deployment exercises.

Consolidate on Meilisearch and drop Typesense
=============================================

The simplest possible answer, and the one that requires no abstraction at all.
Rejected because it makes the platform's high-availability story depend on a
BUSL-1.1 licence, and because that is the same failure mode the move off
Elasticsearch was meant to avoid.

Consolidate on Typesense and drop Meilisearch
=============================================

Equally simple, and rejected for the mirror-image reason: it would force a
change on every operator currently running Meilisearch to solve a problem only
some of them have. Supporting both is the price of not doing that to either
group.

Implement search logic on the backend and proxy from the LMS
============================================================

Clean, and it would remove the frontend problem entirely. Rejected on
performance: it ties up LMS worker threads to rewrite and forward requests.
Worth revisiting if the platform adopts asyncio Django.

References
**********

* ``content/search`` ADR 0001, "Meilisearch" —
  https://github.com/openedx/openedx-platform/blob/master/openedx/core/djangoapps/content/search/docs/decisions/0001-meilisearch.rst
* openedx/edx-search#245, "This repo (edx-search) needs re-architecture" —
  https://github.com/openedx/edx-search/issues/245
* openedx/modular-learning#245, "Prototype Typesense search support" —
  https://github.com/openedx/modular-learning/issues/245
* openedx/openedx-platform#36868, "Improve Meilisearch Index upgrade workflow" —
  https://github.com/openedx/openedx-platform/issues/36868
* openedx/openedx-platform#38993, indexing performance and asynchronous updates —
  https://github.com/openedx/openedx-platform/issues/38993
* openedx/openedx-platform#39049, the earlier and narrower version of this
  proposal, superseded by this ADR —
  https://github.com/openedx/openedx-platform/pull/39049
* openedx/forum#289, the forum Typesense search fixes —
  https://github.com/openedx/forum/pull/289
