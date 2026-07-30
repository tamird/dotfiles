"""Continuously observe personal GitHub sources through one receipt writer."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import sqlite3
import sys
from typing import cast

from .config import RuntimeConfig, require_writer_leadership
from .model import compact_json
from .receipt_server import submit_receipts


JsonObject = dict[str, object]
MAXIMUM_PROVIDER_CONCURRENCY = 4
PROVIDER_TIMEOUT_SECONDS = 45
REPLAY_OVERLAP = timedelta(minutes=5)
OWNED_COMMENT_FIELDS = "id createdAt updatedAt author{__typename login}body"
OWNED_REVIEW_FIELDS = "id submittedAt author{__typename login}body state commit{oid}"
OWNED_INLINE_FIELDS = (
    "id createdAt updatedAt author{__typename login}body commit{oid}"
)
OWNED_THREAD_FIELDS = (
    "id isResolved isOutdated comments(last:15){"
    "pageInfo{hasPreviousPage startCursor}nodes{"
    + OWNED_INLINE_FIELDS
    + "}}"
)


def _object(value: object, *, context: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ValueError(f"GitHub returned an invalid {context}")
    return cast(JsonObject, value)


def _objects(value: object, *, context: str) -> list[JsonObject]:
    if not isinstance(value, list):
        raise ValueError(f"GitHub returned invalid {context}")
    return [_object(item, context=context) for item in cast(list[object], value)]


def _string(value: object, *, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"GitHub omitted {context}")
    return value


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _actor(value: object) -> tuple[str, str]:
    actor = _object(value, context="event actor")
    login = _string(actor.get("login"), context="event actor login")
    kind = _string(actor.get("__typename"), context="event actor type")
    if kind not in {"User", "Bot"}:
        raise ValueError("GitHub actor is neither a user nor an authenticated bot")
    return login, kind


def review_request_is_outstanding(
    request_time: str, reviews: Sequence[JsonObject], *, principal: str
) -> bool:
    """A newer human re-request, not a moved head, reopens an obligation."""
    requested = _timestamp(request_time)
    terminal = max(
        (
            _timestamp(_string(review.get("submittedAt"), context="review time"))
            for review in reviews
            if _object(review.get("author"), context="review author").get("login")
            == principal
        ),
        default=datetime.min.replace(tzinfo=UTC),
    )
    return terminal < requested


def has_actionable_feedback(item: JsonObject) -> bool:
    """Approval prose is status; independently authored comments remain events."""
    return item.get("state") != "APPROVED"


async def complete_previous_pages(
    connection: JsonObject,
    fetch: Callable[[str], Awaitable[JsonObject]],
    *,
    context: str,
) -> list[JsonObject]:
    """Retain every earlier provider page before declaring the source complete."""
    nodes = _objects(connection.get("nodes"), context=f"{context} nodes")
    page = _object(connection.get("pageInfo"), context=f"{context} pagination")
    while page.get("hasPreviousPage") is True:
        cursor = _string(page.get("startCursor"), context=f"{context} cursor")
        previous = await fetch(cursor)
        older = _objects(previous.get("nodes"), context=f"{context} nodes")
        nodes = older + nodes
        page = _object(previous.get("pageInfo"), context=f"{context} pagination")
    if page.get("hasPreviousPage") is not False:
        raise ValueError(f"{context} pagination is incomplete")
    return nodes


def is_actionable_feedback_actor(
    item: JsonObject, *, current_head: str, unresolved_current_thread: bool = False
) -> bool:
    """Accept people and exact-current, verified Codex inline findings only."""
    candidate = item.get("author")
    if not isinstance(candidate, dict):
        return False
    author = cast(JsonObject, candidate)
    if author.get("__typename") == "User":
        return True
    if (
        author.get("__typename") != "Bot"
        or author.get("login") != "chatgpt-codex-connector"
        or not unresolved_current_thread
    ):
        return False
    commit = item.get("commit")
    return isinstance(commit, dict) and cast(JsonObject, commit).get("oid") == current_head


def immutable_event_payload(raw: str, *, event_id: str) -> JsonObject:
    """Replay the original authenticated event, never mutable presentation."""
    evidence = _object(json.loads(raw), context="stored GitHub evidence")
    payload = _object(evidence.get("payload"), context="immutable event")
    if payload.get("event_id") != event_id or payload.get("verified") is not True:
        raise ValueError("stored GitHub event evidence is not authentic")
    return payload


def comment_event_identity(
    identifier: str,
    *,
    created_at: str,
    updated_at: str | None,
    body: str,
    previous_body: str | None,
    previous_event_id: str | None = None,
) -> tuple[str, str]:
    """Distinguish genuine comment edits from mutable provider metadata."""
    if previous_body == body and previous_event_id is not None:
        if previous_event_id.startswith(f"{identifier}@"):
            return previous_event_id, previous_event_id.removeprefix(f"{identifier}@")
        return previous_event_id, created_at
    if (
        updated_at is not None
        and _timestamp(updated_at) > _timestamp(created_at)
        and previous_body != body
    ):
        return f"{identifier}@{updated_at}", updated_at
    return identifier, created_at


@dataclass(frozen=True, slots=True)
class ReaderConfig:
    owner: str
    principal: str
    interval_seconds: float
    frozen_subjects: frozenset[str]


class GithubReader:
    """Run independently scheduled source scans against the existing writer."""

    def __init__(self, config: ReaderConfig) -> None:
        self.config = config
        self.runtime = RuntimeConfig.from_environment()
        require_writer_leadership(self.runtime.database)
        self.gate = asyncio.Semaphore(MAXIMUM_PROVIDER_CONCURRENCY)
        self.owned_lock = asyncio.Lock()
        self.owned_at: datetime | None = None
        self.owned_nodes: list[JsonObject] = []

    def _previous_comment(
        self, source: str, identifier: str
    ) -> tuple[str | None, str | None]:
        uri = f"file:{self.runtime.database}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5) as connection:
            row = connection.execute(
                "SELECT event_id, raw_json FROM notifications "
                "WHERE source_id = ? AND (event_id = ? OR event_id LIKE ?) "
                "ORDER BY occurred_at DESC LIMIT 1",
                (source, identifier, f"{identifier}@%"),
            ).fetchone()
        if row is None:
            return None, None
        event_id, raw = row
        if not isinstance(event_id, str) or not isinstance(raw, str):
            raise ValueError("stored GitHub comment evidence is malformed")
        body = immutable_event_payload(raw, event_id=event_id).get("body")
        return event_id, body if isinstance(body, str) else None

    async def _github(self, *arguments: str) -> object:
        async with self.gate:
            process = await asyncio.create_subprocess_exec(
                "gh",
                "api",
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                output, error = await asyncio.wait_for(
                    process.communicate(), timeout=PROVIDER_TIMEOUT_SECONDS
                )
            except TimeoutError:
                process.kill()
                await process.wait()
                raise
        if process.returncode != 0:
            raise ValueError(error.decode(errors="replace")[:500])
        return cast(object, json.loads(output))

    async def _search(self, query: str, fields: str) -> list[JsonObject]:
        document = (
            "query($search:String!,$cursor:String){"
            "search(query:$search,type:ISSUE,first:50,after:$cursor){"
            "pageInfo{hasNextPage endCursor}nodes{...on PullRequest{"
            + fields
            + "}}}}"
        )
        cursor: str | None = None
        result: list[JsonObject] = []
        while True:
            arguments = ["graphql", "-f", f"query={document}", "-f", f"search={query}"]
            if cursor is not None:
                arguments.extend(("-f", f"cursor={cursor}"))
            response = _object(await self._github(*arguments), context="GraphQL response")
            data = _object(response.get("data"), context="GraphQL data")
            search = _object(data.get("search"), context="search result")
            result.extend(_objects(search.get("nodes"), context="pull request nodes"))
            page = _object(search.get("pageInfo"), context="search pagination")
            if page.get("hasNextPage") is not True:
                return result
            cursor = _string(page.get("endCursor"), context="search cursor")

    def _cutoff(self, source: str) -> datetime:
        uri = f"file:{self.runtime.database}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5) as connection:
            row = connection.execute(
                "SELECT high_water_mark FROM sources WHERE source_id = ? AND owner = ?",
                (source, self.config.owner),
            ).fetchone()
        if row is None or not isinstance(row[0], str):
            raise ValueError(f"canonical source {source} is not registered")
        return _timestamp(row[0]) - REPLAY_OVERLAP

    @staticmethod
    def _subject(node: JsonObject) -> str:
        repository = _object(node.get("repository"), context="pull request repository")
        name = _string(repository.get("nameWithOwner"), context="repository name")
        number = node.get("number")
        if not isinstance(number, int) or isinstance(number, bool):
            raise ValueError("pull request number is invalid")
        return f"{name}#{number}"

    def _event(
        self,
        *,
        source: str,
        node: JsonObject,
        item: JsonObject,
        category: str,
        reviewer: bool = False,
    ) -> JsonObject | None:
        subject = self._subject(node)
        if subject in self.config.frozen_subjects:
            return None
        actor_login, actor_kind = _actor(item.get("actor", item.get("author")))
        if actor_login == self.config.principal:
            return None
        head = _string(node.get("headRefOid"), context="pull request head")
        identifier = _string(item.get("id"), context="GitHub event ID")
        occurred = _string(
            item.get("createdAt", item.get("submittedAt")), context="event time"
        )
        body = item.get("body")
        if isinstance(body, str):
            updated = item.get("updatedAt")
            previous_event_id, previous_body = self._previous_comment(source, identifier)
            identifier, occurred = comment_event_identity(
                identifier,
                created_at=occurred,
                updated_at=updated if isinstance(updated, str) else None,
                body=body,
                previous_body=previous_body,
                previous_event_id=previous_event_id,
            )
        event: JsonObject = {
            "event_id": identifier,
            "category": category,
            "subject_key": subject,
            "actor": actor_login,
            "actor_type": actor_kind,
            "occurred_at": occurred,
            "head": head,
            "verified": True,
            "provider": "github",
        }
        if isinstance(body, str):
            event["body"] = body
        if reviewer:
            author_login, author_kind = _actor(node.get("author"))
            if author_kind != "User":
                return None
            event.update(
                {
                    "reviewer": self.config.principal,
                    "reviewer_type": "User",
                    "author": author_login,
                    "author_type": author_kind,
                    "individual": True,
                }
            )
        return event

    async def _submit(self, source: str, events: Sequence[JsonObject]) -> None:
        observed = datetime.now(UTC)
        floor = min(self._cutoff(source), observed - timedelta(days=2))
        immutable: dict[str, JsonObject] = {}
        event_ids = [
            _string(event.get("event_id"), context="observed GitHub event ID")
            for event in events
        ]
        if event_ids:
            placeholders = ",".join("?" for _ in event_ids)
            uri = f"file:{self.runtime.database}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=5) as connection:
                rows = connection.execute(
                    "SELECT event_id, raw_json FROM notifications "
                    f"WHERE source_id = ? AND event_id IN ({placeholders})",
                    (source, *event_ids),
                ).fetchall()
            for identifier, raw in rows:
                if not isinstance(identifier, str) or not isinstance(raw, str):
                    raise ValueError("stored GitHub event evidence is malformed")
                immutable[identifier] = immutable_event_payload(raw, event_id=identifier)
        canonical_events: list[JsonObject] = []
        seen: set[str] = set()
        for event, identifier in zip(events, event_ids, strict=True):
            if identifier in seen:
                continue
            seen.add(identifier)
            canonical_events.append(immutable.get(identifier, event))
        observation: JsonObject = {
            "source_id": source,
            "owner": self.config.owner,
            "observed_at": observed.isoformat(),
            "high_water_mark": observed.isoformat(),
            "overlap_floor": floor.isoformat(),
            "overlap_seconds": int(REPLAY_OVERLAP.total_seconds()),
            "pagination_complete": True,
            "observed_candidate_event_ids": list(seen),
            "events": canonical_events,
            "verified": True,
        }
        result = await asyncio.to_thread(
            submit_receipts, self.runtime.database, [observation]
        )
        print(
            compact_json(
                {
                    "kind": "github_source_observation",
                    "source": source,
                    "at": observed.isoformat(),
                    "events": len(canonical_events),
                    "result": result,
                }
            ),
            flush=True,
        )

    async def scan_requested(self) -> None:
        source = "github_org_review_requested_search"
        cutoff = self._cutoff(source)
        fields = (
            "number isDraft headRefOid repository{nameWithOwner}author{__typename login}"
            "reviewRequests(first:100){pageInfo{hasNextPage}nodes{requestedReviewer{"
            "__typename ...on User{login}}}}"
            "reviews(last:25){nodes{author{login}submittedAt commit{oid}}}"
            "timelineItems(last:40,itemTypes:[REVIEW_REQUESTED_EVENT]){nodes{"
            "...on ReviewRequestedEvent{id createdAt actor{__typename login}"
            "requestedReviewer{__typename ...on User{login}}}}}"
        )
        nodes = await self._search(
            f"is:pr is:open user-review-requested:{self.config.principal}", fields
        )
        events: list[JsonObject] = []
        for node in nodes:
            if node.get("isDraft") is True:
                continue
            requests = _object(node.get("reviewRequests"), context="review requests")
            if _object(requests.get("pageInfo"), context="review request page").get(
                "hasNextPage"
            ) is True:
                raise ValueError("individual requested-reviewer connection is incomplete")
            actual = [
                _object(item.get("requestedReviewer"), context="requested reviewer")
                for item in _objects(requests.get("nodes"), context="reviewer nodes")
            ]
            if not any(
                reviewer.get("__typename") == "User"
                and reviewer.get("login") == self.config.principal
                for reviewer in actual
            ):
                continue
            reviews = _object(node.get("reviews"), context="pull request reviews")
            terminal_reviews = _objects(reviews.get("nodes"), context="review nodes")
            timeline = _object(node.get("timelineItems"), context="review timeline")
            for item in _objects(timeline.get("nodes"), context="review request events"):
                reviewer = _object(item.get("requestedReviewer"), context="request target")
                if reviewer.get("__typename") != "User" or reviewer.get("login") != self.config.principal:
                    continue
                when = _timestamp(_string(item.get("createdAt"), context="request time"))
                if when < cutoff or not review_request_is_outstanding(
                    _string(item.get("createdAt"), context="request time"),
                    terminal_reviews,
                    principal=self.config.principal,
                ):
                    continue
                event = self._event(
                    source=source, node=node, item=item, category="review_request", reviewer=True
                )
                if event is not None:
                    events.append(event)
        await self._submit(source, events)

    async def scan_assigned(self) -> None:
        source = "github_individually_assigned_pull_requests"
        cutoff = self._cutoff(source)
        fields = (
            "number isDraft updatedAt headRefOid repository{nameWithOwner}"
            "author{__typename login}assignees(first:100){pageInfo{hasNextPage}nodes{login}}"
            "reviews(last:20){nodes{author{login}submittedAt commit{oid}}}"
            "timelineItems(last:30,itemTypes:[ASSIGNED_EVENT]){nodes{"
            "...on AssignedEvent{id createdAt actor{__typename login}"
            "assignee{__typename ...on User{login}}}}}"
        )
        nodes = await self._search(
            f"is:pr is:open assignee:{self.config.principal}", fields
        )
        events: list[JsonObject] = []
        for node in nodes:
            if node.get("isDraft") is True:
                continue
            if _timestamp(_string(node.get("updatedAt"), context="PR update")) < cutoff:
                continue
            assignees = _object(node.get("assignees"), context="pull request assignees")
            if _object(assignees.get("pageInfo"), context="assignee page").get("hasNextPage") is True:
                raise ValueError("personal assignee connection is incomplete")
            if not any(
                assignee.get("login") == self.config.principal
                for assignee in _objects(assignees.get("nodes"), context="assignee nodes")
            ):
                continue
            reviews = _object(node.get("reviews"), context="assignment reviews")
            terminal_reviews = _objects(reviews.get("nodes"), context="review nodes")
            timeline = _object(node.get("timelineItems"), context="assignment timeline")
            for item in _objects(timeline.get("nodes"), context="assignment events"):
                assignee = _object(item.get("assignee"), context="assignment target")
                if assignee.get("__typename") != "User" or assignee.get("login") != self.config.principal:
                    continue
                when = _string(item.get("createdAt"), context="assignment time")
                if not review_request_is_outstanding(
                    when, terminal_reviews, principal=self.config.principal
                ):
                    continue
                event = self._event(
                    source=source, node=node, item=item, category="review_request", reviewer=True
                )
                if event is not None:
                    events.append(event)
        await self._submit(source, events)

    async def _owned_connection_page(
        self, node: JsonObject, *, connection: str, cursor: str
    ) -> JsonObject:
        """Fetch the page immediately preceding an owned pull-request cursor."""
        selections = {
            "comments": OWNED_COMMENT_FIELDS,
            "reviews": OWNED_REVIEW_FIELDS,
            "reviewThreads": OWNED_THREAD_FIELDS,
        }
        selection = selections.get(connection)
        if selection is None:
            raise ValueError("unknown owned pull-request connection")
        repository = _string(
            _object(node.get("repository"), context="pull request repository").get(
                "nameWithOwner"
            ),
            context="repository name",
        )
        owner, separator, name = repository.partition("/")
        number = node.get("number")
        if not separator or not name or not isinstance(number, int):
            raise ValueError("owned pull request identity is invalid")
        document = (
            "query($owner:String!,$name:String!,$number:Int!,$cursor:String!){"
            "repository(owner:$owner,name:$name){pullRequest(number:$number){"
            + connection
            + "(last:50,before:$cursor){pageInfo{hasPreviousPage startCursor}nodes{"
            + selection
            + "}}}}}"
        )
        response = _object(
            await self._github(
                "graphql",
                "-f",
                f"query={document}",
                "-f",
                f"owner={owner}",
                "-f",
                f"name={name}",
                "-F",
                f"number={number}",
                "-f",
                f"cursor={cursor}",
            ),
            context="owned connection response",
        )
        data = _object(response.get("data"), context="owned connection data")
        repo = _object(data.get("repository"), context="owned connection repository")
        pull = _object(repo.get("pullRequest"), context="owned connection pull request")
        return _object(pull.get(connection), context=f"owned {connection}")

    async def _owned_thread_page(self, thread_id: str, cursor: str) -> JsonObject:
        """Fetch earlier inline replies without dropping their immutable roots."""
        document = (
            "query($id:ID!,$cursor:String!){node(id:$id){"
            "...on PullRequestReviewThread{comments(last:50,before:$cursor){"
            "pageInfo{hasPreviousPage startCursor}nodes{"
            + OWNED_INLINE_FIELDS
            + "}}}}}"
        )
        response = _object(
            await self._github(
                "graphql",
                "-f",
                f"query={document}",
                "-f",
                f"id={thread_id}",
                "-f",
                f"cursor={cursor}",
            ),
            context="owned review-thread response",
        )
        data = _object(response.get("data"), context="owned review-thread data")
        thread = _object(data.get("node"), context="owned review thread")
        return _object(thread.get("comments"), context="owned review-thread comments")

    async def _complete_owned_thread(self, thread: JsonObject) -> None:
        thread_id = _string(thread.get("id"), context="owned review thread ID")
        connection = _object(thread.get("comments"), context="owned review-thread comments")
        comments = await complete_previous_pages(
            connection,
            lambda cursor: self._owned_thread_page(thread_id, cursor),
            context="owned review-thread comments",
        )
        connection["nodes"] = comments
        connection["pageInfo"] = {"hasPreviousPage": False}

    async def _complete_owned_node(self, node: JsonObject) -> None:
        async def complete(name: str) -> None:
            connection = _object(node.get(name), context=f"owned {name}")
            nodes = await complete_previous_pages(
                connection,
                lambda cursor: self._owned_connection_page(
                    node, connection=name, cursor=cursor
                ),
                context=f"owned {name}",
            )
            connection["nodes"] = nodes
            connection["pageInfo"] = {"hasPreviousPage": False}

        await asyncio.gather(*(complete(name) for name in ("comments", "reviews", "reviewThreads")))
        threads = _object(node.get("reviewThreads"), context="owned review threads")
        await asyncio.gather(
            *(
                self._complete_owned_thread(thread)
                for thread in _objects(threads.get("nodes"), context="owned review threads")
            )
        )

    async def _owned(self) -> list[JsonObject]:
        async with self.owned_lock:
            now = datetime.now(UTC)
            if self.owned_at is not None and (now - self.owned_at).total_seconds() < 25:
                return self.owned_nodes
            fields = (
                "number isDraft updatedAt headRefOid repository{nameWithOwner}"
                "author{__typename login}"
                "comments(last:20){pageInfo{hasPreviousPage startCursor}nodes{"
                + OWNED_COMMENT_FIELDS
                + "}}reviews(last:20){pageInfo{hasPreviousPage startCursor}nodes{"
                + OWNED_REVIEW_FIELDS
                + "}}reviewThreads(last:15){pageInfo{hasPreviousPage startCursor}nodes{"
                + OWNED_THREAD_FIELDS
                + "}}"
            )
            nodes = await self._search(
                f"is:pr is:open author:{self.config.principal}", fields
            )
            await asyncio.gather(*(self._complete_owned_node(node) for node in nodes))
            self.owned_nodes = nodes
            self.owned_at = now
            return self.owned_nodes

    async def scan_owned(self) -> None:
        source = "github_owned_pr_feedback_all_repos"
        cutoff = self._cutoff(source)
        events: list[JsonObject] = []
        for node in await self._owned():
            if node.get("isDraft") is True:
                continue
            if _timestamp(_string(node.get("updatedAt"), context="PR update")) < cutoff:
                continue
            groups: list[tuple[list[JsonObject], bool]] = [
                (_objects(
                    _object(node.get("comments"), context="issue comments").get("nodes"),
                    context="issue comment nodes",
                ), False),
                (_objects(
                    _object(node.get("reviews"), context="formal reviews").get("nodes"),
                    context="formal review nodes",
                ), False),
            ]
            threads = _object(node.get("reviewThreads"), context="review threads")
            for thread in _objects(threads.get("nodes"), context="review thread nodes"):
                comments = _object(thread.get("comments"), context="review thread comments")
                current = thread.get("isResolved") is False and thread.get("isOutdated") is False
                groups.append(
                    (_objects(comments.get("nodes"), context="thread comment nodes"), current)
                )
            head = _string(node.get("headRefOid"), context="pull request head")
            for items, current_thread in groups:
                for item in items:
                    if not has_actionable_feedback(item):
                        continue
                    if not is_actionable_feedback_actor(
                        item, current_head=head, unresolved_current_thread=current_thread
                    ):
                        continue
                    at = _string(
                        item.get(
                            "updatedAt", item.get("createdAt", item.get("submittedAt"))
                        ),
                        context="feedback time",
                    )
                    if _timestamp(at) < cutoff:
                        continue
                    event = self._event(
                        source=source, node=node, item=item, category="owned_feedback"
                    )
                    if event is not None:
                        events.append(event)
        await self._submit(source, events)

    async def scan_participating(self) -> None:
        source = "github_personal_participating_threads"
        cutoff = self._cutoff(source)
        route = "/notifications?participating=true&per_page=100&since=" + cutoff.isoformat()
        pages = await self._github("--paginate", "--slurp", route)
        if not isinstance(pages, list):
            raise ValueError("GitHub notification pagination did not complete")
        events: list[JsonObject] = []
        for page in cast(list[object], pages):
            for notice in _objects(page, context="participating notification page"):
                subject = _object(notice.get("subject"), context="notification subject")
                if subject.get("type") != "PullRequest":
                    continue
                comment_url = subject.get("latest_comment_url")
                pull_url = subject.get("url")
                if not isinstance(comment_url, str) or not isinstance(pull_url, str):
                    continue
                comment_value, pull_value = await asyncio.gather(
                    self._github(comment_url), self._github(pull_url)
                )
                comment = _object(comment_value, context="participating comment")
                pull = _object(pull_value, context="participating pull request")
                if pull.get("state") != "open":
                    continue
                author = _object(comment.get("user"), context="participating author")
                if author.get("type") != "User" or author.get("login") == self.config.principal:
                    continue
                repo = _object(notice.get("repository"), context="notification repository")
                number = pull.get("number")
                if not isinstance(number, int):
                    raise ValueError("participating pull request number is invalid")
                head = _object(pull.get("head"), context="participating pull head")
                occurred = _string(comment.get("created_at"), context="participating time")
                changed_at = comment.get("updated_at")
                latest = changed_at if isinstance(changed_at, str) else occurred
                if _timestamp(latest) < cutoff:
                    continue
                subject_key = (
                    _string(repo.get("full_name"), context="notification repository name")
                    + f"#{number}"
                )
                if subject_key in self.config.frozen_subjects:
                    continue
                identifier = str(comment.get("id"))
                body = comment.get("body")
                if isinstance(body, str):
                    updated = comment.get("updated_at")
                    previous_event_id, previous_body = self._previous_comment(
                        source, identifier
                    )
                    identifier, occurred = comment_event_identity(
                        identifier,
                        created_at=occurred,
                        updated_at=updated if isinstance(updated, str) else None,
                        body=body,
                        previous_body=previous_body,
                        previous_event_id=previous_event_id,
                    )
                event: JsonObject = {
                    "event_id": identifier,
                    "category": "owned_feedback",
                    "subject_key": subject_key,
                    "actor": _string(author.get("login"), context="participating actor"),
                    "actor_type": "User",
                    "occurred_at": occurred,
                    "head": _string(head.get("sha"), context="participating head"),
                    "verified": True,
                    "provider": "github",
                }
                if isinstance(body, str):
                    event["body"] = body
                events.append(event)
        await self._submit(source, events)

    async def scan_tempest(self) -> None:
        source = "github_tempest_current_head_findings_72h"
        cutoff = self._cutoff(source)
        events: list[JsonObject] = []
        for node in await self._owned():
            if node.get("isDraft") is True:
                continue
            if _timestamp(_string(node.get("updatedAt"), context="PR update")) < cutoff:
                continue
            reviews = _object(node.get("reviews"), context="tempest reviews")
            for review in _objects(reviews.get("nodes"), context="tempest review nodes"):
                author = _object(review.get("author"), context="tempest author")
                login = author.get("login")
                if not isinstance(login, str) or "tempest" not in login.lower():
                    continue
                commit = review.get("commit")
                if not isinstance(commit, dict) or cast(JsonObject, commit).get(
                    "oid"
                ) != node.get("headRefOid"):
                    continue
                occurred = _string(review.get("submittedAt"), context="tempest time")
                if _timestamp(occurred) < cutoff:
                    continue
                event = self._event(
                    source=source, node=node, item=review, category="ci_update"
                )
                if event is not None:
                    events.append(event)
        await self._submit(source, events)

    async def _lane(self, name: str, operation: object) -> None:
        if not callable(operation):
            raise TypeError("GitHub source operation is not callable")
        scan = cast(object, operation)
        while True:
            started = asyncio.get_running_loop().time()
            try:
                await cast(object, scan)()  # type: ignore[operator]
            except (OSError, TimeoutError, ValueError, sqlite3.Error) as error:
                print(
                    compact_json(
                        {"kind": "github_source_failure", "source": name, "error": str(error)}
                    ),
                    file=sys.stderr,
                    flush=True,
                )
            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(0.0, self.config.interval_seconds - elapsed))

    async def run(self) -> None:
        identity = _object(await self._github("user"), context="authenticated identity")
        if identity.get("login") != self.config.principal:
            raise ValueError("GitHub identity does not match the requested source owner")
        operations = {
            "github_org_review_requested_search": self.scan_requested,
            "github_individually_assigned_pull_requests": self.scan_assigned,
            "github_owned_pr_feedback_all_repos": self.scan_owned,
            "github_personal_participating_threads": self.scan_participating,
            "github_tempest_current_head_findings_72h": self.scan_tempest,
        }
        print(
            compact_json(
                {
                    "kind": "github_single_reader_started",
                    "principal": self.config.principal,
                    "source_count": len(operations),
                }
            ),
            flush=True,
        )
        async with asyncio.TaskGroup() as group:
            for name, operation in operations.items():
                _ = group.create_task(self._lane(name, operation))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--owner", required=True)
    _ = parser.add_argument("--principal", required=True)
    _ = parser.add_argument("--interval-seconds", type=float, default=50.0)
    _ = parser.add_argument("--exclude", action="append", default=[])
    arguments = parser.parse_args()
    interval = cast(float, arguments.interval_seconds)
    if interval <= 0 or interval > 100:
        parser.error("interval must be greater than zero and at most 100 seconds")
    config = ReaderConfig(
        owner=cast(str, arguments.owner),
        principal=cast(str, arguments.principal),
        interval_seconds=interval,
        frozen_subjects=frozenset(cast(list[str], arguments.exclude)),
    )
    asyncio.run(GithubReader(config).run())


if __name__ == "__main__":
    main()
