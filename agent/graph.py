from langgraph.graph import StateGraph, END

from agent.state import DailyState, DiscoveryState
from agent.nodes.scraper import load_sources, scrape_sources
from agent.nodes.deduplicator import deduplicate, persist_seen
from agent.nodes.keyword_filter import keyword_filter
from agent.nodes.llm_ranker import llm_ranker
from agent.nodes.digest_composer import compose_digest
from agent.nodes.site_discoverer import (
    load_config,
    generate_queries,
    run_serp,
    score_sites,
    update_sources,
)
from agent.tools.email_tool import send_email_node


def build_daily_graph():
    g = StateGraph(DailyState)

    g.add_node("load_sources", load_sources)
    g.add_node("scrape_sources", scrape_sources)
    g.add_node("deduplicate", deduplicate)
    g.add_node("keyword_filter", keyword_filter)
    g.add_node("llm_ranker", llm_ranker)
    g.add_node("compose_digest", compose_digest)
    g.add_node("send_email", send_email_node)
    g.add_node("persist_seen", persist_seen)

    g.set_entry_point("load_sources")
    g.add_edge("load_sources", "scrape_sources")
    g.add_edge("scrape_sources", "deduplicate")
    g.add_edge("deduplicate", "keyword_filter")
    g.add_edge("keyword_filter", "llm_ranker")
    g.add_edge("llm_ranker", "compose_digest")
    g.add_edge("compose_digest", "send_email")
    g.add_edge("send_email", "persist_seen")
    g.add_edge("persist_seen", END)

    return g.compile()


def build_discovery_graph():
    g = StateGraph(DiscoveryState)

    g.add_node("load_config", load_config)
    g.add_node("generate_queries", generate_queries)
    g.add_node("run_serp", run_serp)
    g.add_node("score_sites", score_sites)
    g.add_node("update_sources", update_sources)

    g.set_entry_point("load_config")
    g.add_edge("load_config", "generate_queries")
    g.add_edge("generate_queries", "run_serp")
    g.add_edge("run_serp", "score_sites")
    g.add_edge("score_sites", "update_sources")
    g.add_edge("update_sources", END)

    return g.compile()
