from django.core.exceptions import ValidationError


def normalize_topic_candidates(*, query_growth=None, feeds=()):
    if type(feeds) not in {list, tuple} or len(feeds) > 5:
        raise ValidationError("Select at most five project feeds.")
    candidates = []
    feed_items = {}
    failed_feeds = []
    partial_feeds = []
    for result in feeds:
        if not isinstance(result, dict) or result.get("state") not in {
            "failed", "partial", "complete_for_bounded_feed",
        } or not isinstance(result.get("source_feed"), str):
            raise ValidationError("Check the feed evidence.")
        if result["state"] == "failed":
            failed_feeds.append({"source_feed": result["source_feed"], "category": result.get("error", "unknown")})
            continue
        if result["state"] == "partial":
            partial_feeds.append(result["source_feed"])
        items = result.get("items", [])
        if not isinstance(items, list) or len(items) > 50:
            raise ValidationError("Check the bounded feed items.")
        for item in items:
            if not isinstance(item, dict) or not all(isinstance(item.get(field), str) for field in (
                "title", "url", "source_feed", "freshness", "observation",
            )) or item["source_feed"] != result["source_feed"]:
                raise ValidationError("Check the feed item evidence.")
            key = (item["url"], item["title"].casefold(), item.get("published_at"))
            existing = feed_items.get(key)
            if existing:
                if item["source_feed"] not in existing["source_feeds"]:
                    existing["source_feeds"].append(item["source_feed"])
                continue
            feed_items[key] = {
                "kind": "public_feed_item", "title": item["title"], "url": item["url"],
                "published_at": item.get("published_at"), "freshness": item["freshness"],
                "source_feeds": [item["source_feed"]], "trend_state": "not_measured",
                "evergreen_state": "unknown",
                "business_relevance": "not_evaluated",
            }
    if query_growth is not None:
        if not isinstance(query_growth, dict) or not isinstance(query_growth.get("candidates"), list):
            raise ValidationError("Check the query growth evidence.")
        for row in query_growth["candidates"][:100]:
            if not isinstance(row, dict) or not isinstance(row.get("query"), str):
                raise ValidationError("Check the query growth evidence.")
            candidates.append({
                "kind": "first_party_query_growth", "query": row["query"],
                "connection_id": query_growth["connection_id"], "provider": query_growth["provider"],
                "property": query_growth["property"], "search_type": row["search_type"],
                "previous_observation_id": row["previous_observation_id"],
                "current_observation_id": row["current_observation_id"],
                "click_change": row["click_change"], "impression_change": row["impression_change"],
                "source_windows": [query_growth["previous"], query_growth["current"]],
                "source_coverage": query_growth["coverage"],
                "trend_state": "first_party_comparable_growth", "evergreen_state": "unknown",
                "business_relevance": "not_evaluated",
            })
    candidates.extend(feed_items.values())
    return {
        "method": "topic-candidates-v1", "candidates": candidates[:150],
        "coverage": {"failed_feeds": failed_feeds, "partial_feeds": partial_feeds,
                     "truncated": len(candidates) > 150,
                     "source_labels": (["first_party_measured"] if query_growth is not None else [])
                     + (["public_feed_observation"] if feed_items else []),
                     "popularity_is_not_business_relevance": True},
    }
