# hyperresearch/ — folder structure

├── .agents/
│   ├── agents  4.0KB -> /home/monster/agentspace/.claude/agents
│   ├── rules  4.0KB -> /home/monster/agentspace/.claude/rules
│   └── skills/
├── .claude/
│   ├── agents  4.0KB -> /home/monster/agentspace/.claude/agents
│   ├── rules  4.0KB -> /home/monster/agentspace/.claude/rules
│   ├── skills/
│   ├── settings.json  17.6KB -> /home/monster/agentspace/.claude/settings.json
│   └── settings.local.json  73B
├── .cursor/
│   └── rules_md  4.0KB -> /home/monster/agentspace/.claude/rules
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.yml  2.1KB
│   │   ├── config.yml  490B
│   │   └── feature_request.yml  1.4KB
│   ├── workflows/
│   │   ├── ci.yml  1.4KB
│   │   └── publish.yml  1.0KB
│   ├── dependabot.yml  758B
│   └── pull_request_template.md  1.1KB
├── .hyperresearch/
│   ├── exports/
│   ├── templates/
│   │   └── note.md  394B -> ../../../manage_environment/manage_templates/active/hyperresearch/note.template.md
│   ├── config.toml  2.3KB
│   └── hyperresearch.db  10.4MB
├── assets/
│   ├── _banner_src.png  12.0KB
│   ├── _generate_banner.py  2.6KB
│   ├── _generate_benchmark.py  4.9KB
│   ├── banner.png  18.5KB
│   ├── banner_social.png  16.4KB
│   └── benchmark.png  89.9KB
├── docs/
│   └── roadmap-2.0/
│       ├── phase-0-cleanup.md  11.5KB
│       ├── phase-1-config-profiles.md  11.1KB
│       ├── phase-2-source-ranking.md  11.8KB
│       ├── phase-3-dissertation-scale.md  12.9KB
│       ├── phase-4-chrome-lane.md  12.5KB
│       ├── phase-5-verification.md  11.2KB
│       └── README.md  5.6KB
├── example-reports/
│   └── rl-exploration-trajectory-planning.md  85.0KB
├── orchestrator/
│   ├── ASSESSMENT_2026-09-19.md  7.1KB
│   ├── ECOSYSTEM_RECOMMENDATIONS_2026-09-21.md  8.7KB
│   └── launch_lane.sh  3.8KB
├── output/
│   ├── _inbox/
│   ├── assets/
│   ├── index/
│   ├── notes/
│   │   ├── agent-os-layers-capabilities-fe30a0/
│   │   │   ├── addozhang-sandboxes.md  1.4KB
│   │   │   ├── aios-llm-agent-operating-system.md  1.9KB
│   │   │   ├── always-on-agents-survey.md  2.1KB
│   │   │   ├── api7-mcp-registry.md  1.5KB
│   │   │   ├── blaxel-code-execution-sandboxes.md  1.5KB
│   │   │   ├── claude-agent-skills-best-practices.md  2.5KB
│   │   │   ├── claude-agent-skills-overview.md  2.1KB
│   │   │   ├── claude-code-best-practices.md  3.2KB
│   │   │   ├── cognition-dont-build-multi-agents.md  1.7KB
│   │   │   ├── cortexprism-open-source-agent-os-landscape.md  1.2KB
│   │   │   ├── cursor-agents-md-config.md  2.0KB
│   │   │   ├── cyera-lethal-trifecta-boundaries.md  1.9KB
│   │   │   ├── devto-agentsmd-vs-claudemd.md  1.6KB
│   │   │   ├── devto-gate-lethal-trifecta.md  2.0KB
│   │   │   ├── foundra-production-reliability.md  1.9KB
│   │   │   ├── google-adk-sessions-memory.md  1.9KB
│   │   │   ├── ijcai-llm-multi-agent-survey.md  3.1KB
│   │   │   ├── inngest-harness-not-framework.md  1.9KB
│   │   │   ├── interim-framework-retrofit-cost.md  6.6KB
│   │   │   ├── interim-mcp-registry-boundary.md  3.9KB
│   │   │   ├── interim-memory-tier-taxonomy.md  6.4KB
│   │   │   ├── interim-multi-agent-orchestration.md  7.1KB
│   │   │   ├── interim-permission-enforcement.md  9.0KB
│   │   │   ├── interim-six-senses-collapse.md  5.0KB
│   │   │   ├── jxnl-cognition-no-multiagent.md  1.9KB
│   │   │   ├── klavisai-mcp-connections.md  1.8KB
│   │   │   ├── konghq-mcp-registry.md  1.6KB
│   │   │   ├── konvu-yagni-framework.md  1.4KB
│   │   │   ├── langchain-multiagent.md  1.9KB
│   │   │   ├── lethal-trifecta-guardrails.md  2.3KB
│   │   │   ├── litellm-github.md  1.7KB
│   │   │   ├── make-agentic-operating-system.md  2.1KB
│   │   │   ├── mcp-dpt-defense-taxonomy.md  2.9KB
│   │   │   ├── memo-d-foundation-e2b.md  1.7KB
│   │   │   ├── mindstudio-agentic-operating-system.md  2.5KB
│   │   │   ├── mindstudio-memory-vector-search.md  1.8KB
│   │   │   ├── mlmastery-agent-memory-design.md  1.7KB
│   │   │   ├── mnemoverse-what-is-an-agent-os.md  2.2KB
│   │   │   ├── northflank-daytona-vs-e2b.md  2.2KB
│   │   │   ├── openobserve-otel-for-llms.md  2.0KB
│   │   │   ├── opentelemetry-llm-observability.md  1.7KB
│   │   │   ├── orchestrai-agent-os-architecture.md  1.1KB
│   │   │   ├── osworld-benchmark.md  1.8KB
│   │   │   ├── ro14nd-agents-md.md  1.5KB
│   │   │   ├── securing-mcp-risks-controls-governance.md  3.3KB
│   │   │   ├── simorconsulting-mcp-production.md  2.3KB
│   │   │   ├── sophos-blast-radius-reduction.md  2.0KB
│   │   │   ├── subagent-verification-practices.md  2.0KB
│   │   │   ├── tianpan-event-driven-vs-scheduled.md  1.6KB
│   │   │   ├── truefoundry-mcp-registries-comparison.md  1.7KB
│   │   │   └── zup-codegen-case-study.md  2.0KB
│   │   ├── ai-productivity-tools-096ea7/
│   │   │   ├── 1password-developer-tools.md  5.0KB
│   │   │   ├── ai-code-generation-security-study.md  78.8KB
│   │   │   ├── ai-coding-agent-for-building-ambitious-software-cursor.md  10.8KB
│   │   │   ├── ai-workflow-automation-platform-n8n.md  14.9KB
│   │   │   ├── aider-ai-pair-programming.md  4.8KB
│   │   │   ├── amazon-q-developer.md  13.1KB
│   │   │   ├── arc-from-the-browser-company.md  1.7KB
│   │   │   ├── architecture-overview-model-context-protocol.md  30.9KB
│   │   │   ├── augment-code-ai-assistant.md  23.7KB
│   │   │   ├── build-an-mcp-server-model-context-protocol.md  78.7KB
│   │   │   ├── calcom-scheduling-platform.md  13.3KB
│   │   │   ├── claude-code-documentation.md  15.4KB
│   │   │   ├── clipboard-api-web-apis-mdn.md  12.2KB
│   │   │   ├── close-this-consent-banner-2.md  4.6KB
│   │   │   ├── close-this-consent-banner.md  4.6KB
│   │   │   ├── contents.md  1.7KB
│   │   │   ├── continuedev-ai-code-assistant.md  950B
│   │   │   ├── copyq.md  6.6KB
│   │   │   ├── cursor-ai-code-editor-features.md  11.2KB
│   │   │   ├── cursor-pricing.md  3.6KB
│   │   │   ├── developer-api-obsidian-help.md  950B
│   │   │   ├── devin-ai-autonomous-developer.md  3.5KB
│   │   │   ├── evernote-developers.md  689B
│   │   │   ├── extending-joplin-joplin.md  2.6KB
│   │   │   ├── extension-api-visual-studio-code-extension-api.md  7.6KB
│   │   │   ├── gemini-code-assist.md  19.5KB
│   │   │   ├── getting-started-mcpjam-inspector.md  5.6KB
│   │   │   ├── getting-started-with-self-hosting.md  5.0KB
│   │   │   ├── github-clipyclipy-clipboard-extension-app-for-macos-github.md  8.7KB
│   │   │   ├── github-copilot-features-and-pricing.md  69.0KB
│   │   │   ├── github-copilot-features-documentation.md  7.7KB
│   │   │   ├── github-copilot-github.md  1.5KB
│   │   │   ├── github-copilot-plans-pricing-github.md  76.0KB
│   │   │   ├── google-calendar-google-for-developers.md  3.3KB
│   │   │   ├── help-support-and-documentation-for-notion.md  2.3KB
│   │   │   ├── html.md  3.8KB
│   │   │   ├── interim-authentication-and-privacy-model.md  4.0KB
│   │   │   ├── interim-automation-platforms-as-bridges.md  6.8KB
│   │   │   ├── interim-browser-and-clipboard-tools.md  5.7KB
│   │   │   ├── interim-mcp-server-maturity-and-interoperability.md  3.7KB
│   │   │   ├── interim-pricing-and-licensing.md  9.3KB
│   │   │   ├── interim-task-board-integration.md  3.0KB
│   │   │   ├── jira-features-and-capabilities.md  7.5KB
│   │   │   ├── linear-developer-api.md  1.7KB
│   │   │   ├── linear-developers.md  1.7KB
│   │   │   ├── linear-project-management.md  10.8KB
│   │   │   ├── litellm-documentation-2.md  11.6KB
│   │   │   ├── logseq-knowledge-base.md  4.2KB
│   │   │   ├── maccy-macos-clipboard-manager.md  3.1KB
│   │   │   ├── make-automation-platform.md  8.3KB
│   │   │   ├── mcp-servers-reference-implementations.md  17.9KB
│   │   │   ├── model-context-protocol-introduction.md  3.4KB
│   │   │   ├── notion-api-documentation.md  9.2KB
│   │   │   ├── notion-platform-overview.md  1.7KB
│   │   │   ├── obsidian-note-taking.md  7.1KB
│   │   │   ├── onenote-resource-type-microsoft-graph-v10-microsoft-learn.md  6.2KB
│   │   │   ├── openrouter-documentation.md  9.8KB
│   │   │   ├── plane-developer-documentation-api-reference-self-hosting-guides-plane.md  2.7KB
│   │   │   ├── portkey-ai-gateway.md  11.7KB
│   │   │   ├── projects-github-docs.md  4.7KB
│   │   │   ├── raycast-launcher.md  14.5KB
│   │   │   ├── raycast-pricing-free-and-pro-plans-with-ai.md  11.8KB
│   │   │   ├── raycast-pro-pricing.md  12.6KB
│   │   │   ├── reference-obsidian-help.md  952B
│   │   │   ├── replit-ai-agent.md  3.6KB
│   │   │   ├── slack-developer-documentation.md  5.1KB
│   │   │   ├── sourcegraph-cody-ai-code-assistant.md  5.3KB
│   │   │   ├── tailscale-developer-networking.md  8.9KB
│   │   │   ├── the-trello-rest-api.md  28.6KB
│   │   │   ├── todoist-task-management.md  9.3KB
│   │   │   ├── what-is-the-model-context-protocol-mcp-model-context-protocol.md  3.4KB
│   │   │   ├── windsurf-ide.md  12.6KB
│   │   │   ├── zapier-automate-ai-workflows-agents-and-apps.md  20.8KB
│   │   │   └── zen-browser.md  1.6KB
│   │   ├── batches/
│   │   ├── github/
│   │   │   ├── about-code-owners-github-docs.md  10.5KB
│   │   │   ├── ai-models-for-github-copilot-github-docs.md  910B
│   │   │   ├── final_report_github-workflow-platform-map-193a00.md  19.7KB
│   │   │   ├── github-discussions-documentation-github-docs.md  3.1KB
│   │   │   ├── github-feature-atlas.md  8.6KB
│   │   │   ├── github-issues-documentation-github-docs.md  2.2KB
│   │   │   ├── managing-files-github-docs.md  1.5KB
│   │   │   ├── planning-and-tracking-with-projects-github-docs.md  3.0KB
│   │   │   ├── pull-requests-documentation-github-docs.md  2.6KB
│   │   │   ├── security-and-code-quality-documentation-github-docs.md  2.5KB
│   │   │   ├── webhooks-documentation-github-docs.md  2.4KB
│   │   │   └── writing-workflows-github-docs.md  1.1KB
│   │   ├── grilling/
│   │   │   └── the-grilling-skill.md  13.0KB
│   │   ├── litellm-cost-perf-ops-506ad8/
│   │   │   ├── alerting-webhooks-litellm.md  22.9KB
│   │   │   ├── auto-inject-prompt-caching-checkpoints-litellm.md  20.0KB
│   │   │   ├── benchmarks-litellm.md  21.3KB
│   │   │   ├── berriai-blog.md  200B
│   │   │   ├── beta-guardrail-policies-litellm.md  14.2KB
│   │   │   ├── budgets-rate-limits-litellm.md  53.3KB
│   │   │   ├── bug-after-sending-a-streaming-request-to-a-custom-endpoint-the-entire-litellm-pr.md  11.2KB
│   │   │   ├── bug-cascading-fallback-failure-both-primary-and-fallback-deployments-unhealthy-i.md  8.4KB
│   │   │   ├── bug-in-v3-rate-limiting-requests-fail-when-redis-is-down-issue-14820-berriailite.md  9.1KB
│   │   │   ├── bug-litellm-proxy-availability-concerns-cascading-failures-during-high-load-to-p.md  11.2KB
│   │   │   ├── bug-using-litellm-proxy-at-scale-with-db-and-dynamodb-callback-issue-12067-berri.md  8.7KB
│   │   │   ├── build-a-self-hosted-ai-gateway-with-litellm-proxy.md  7.9KB
│   │   │   ├── caching-in-memory-redis-s3-gcs-redis-semantic-cache-disk-litellm.md  23.0KB
│   │   │   ├── caching-litellm.md  8.1KB
│   │   │   ├── config_settings-litellm.md  204.9KB
│   │   │   ├── duckduckgo-search-for-obsidian-security-cve-2026-47101.md  5.0KB
│   │   │   ├── dynamic-tpmrpm-allocation-litellm.md  16.5KB
│   │   │   ├── failureatlas-a-taxonomy-of-failure-modes-in-multi-provider-llm-serving-infrastru.md  56.0KB
│   │   │   ├── fallbacks-provider-failover-litellm.md  31.6KB
│   │   │   ├── github-advisory-for-cve-2026-40217.md  2.4KB
│   │   │   ├── github-advisory-for-cve-2026-47101.md  2.3KB
│   │   │   ├── github-advisory-for-cve-2026-47102.md  2.2KB
│   │   │   ├── gptcache-an-open-source-semantic-cache-for-llm-applications-enabling-faster-answ.md  29.4KB
│   │   │   ├── grafana-cloud-litellm.md  6.0KB
│   │   │   ├── guardrail-providers-litellm.md  12.0KB
│   │   │   ├── health-check-driven-routing-litellm.md  13.6KB
│   │   │   ├── health-checks-litellm.md  10.3KB
│   │   │   ├── how-to-add-guardrails-to-litellm-and-secure-it-for-enterprise-neuraltrust.md  27.6KB
│   │   │   ├── interim-concurrency-and-timeout-tuning-under-thin-third-party-validation.md  4.9KB
│   │   │   ├── interim-grounding-best-practices-to-multi-harness-self-hosted-gateway-host.md  4.6KB
│   │   │   ├── interim-guardrailgovernance-sufficiency.md  4.7KB
│   │   │   ├── interim-production-reliability-under-load.md  4.5KB
│   │   │   ├── interim-redis-as-reliability-single-point-of-failure.md  4.2KB
│   │   │   ├── interim-semantic-caching-costcorrectness-tradeoff.md  4.1KB
│   │   │   ├── litellm-benchmarks-show-gateway-self-reported-health-vs-client-observed-metrics.md  708B
│   │   │   ├── litellm-cost-tracking-multi-model-expense-management.md  17.1KB
│   │   │   ├── litellm-documentation.md  199.3KB
│   │   │   ├── litellm-fixes-max_parallel_requests-enforcement-bug-and-validates-concurrency-li.md  1.0KB
│   │   │   ├── litellm-gets-you-routing-it-doesnt-get-you-a-security-story-dev-community.md  7.8KB
│   │   │   ├── litellm-github-repository.md  711.8KB
│   │   │   ├── litellm-proxy-1-api-for-100-llms-15-min-setup-techsy.md  26.5KB
│   │   │   ├── litellm-proxy-cli-litellm.md  17.6KB
│   │   │   ├── making-the-ai-gateway-resilient-to-redis-failures-litellm.md  10.4KB
│   │   │   ├── obsidian-security-blog-post-litellm-privilege-escalation-and-rce-cve-2026-47101.md  25.2KB
│   │   │   ├── production-best-practices-litellm.md  37.7KB
│   │   │   ├── prometheus-metrics-litellm.md  55.0KB
│   │   │   ├── prompt-caching-vs-semantic-caching-real-world-tradeoffs-in-production-llm-system.md  12.5KB
│   │   │   ├── prompt-caching-works-with-auto-router-litellm.md  7.5KB
│   │   │   ├── redis-and-valkey-cache-litellm.md  14.7KB
│   │   │   ├── reliability-retries-fallbacks-litellm.md  9.3KB
│   │   │   ├── risk-constrained-freshness-aware-semantic-caching-for-open-web-retrieval-augment.md  71.2KB
│   │   │   ├── role-based-access-controls-rbac-litellm.md  28.4KB
│   │   │   ├── router-load-balancing-litellm.md  69.9KB
│   │   │   ├── routing-load-balancing-litellm.md  4.1KB
│   │   │   ├── scale-your-llm-gateway.md  5.4KB
│   │   │   ├── semantic-adversarial-examples-2018.md  26.0KB
│   │   │   ├── semantic-caching-litellm.md  14.1KB
│   │   │   ├── semantic-caching-thresholds-and-why-they-matter.md  16.0KB
│   │   │   ├── setting-team-budgets-litellm.md  5.7KB
│   │   │   ├── smartcache-context-aware-semantic-cache-for-efficient-multi-turn-llm-inference-2.md  2.1KB
│   │   │   ├── tamarin-hsq-reversible-hierarchical-kv-cache-compression-for-llm-inference-2026.md  44.3KB
│   │   │   ├── timeouts-litellm.md  11.0KB
│   │   │   ├── virtual-keys-litellm.md  38.1KB
│   │   │   └── when-cache-poisoning-meets-llm-systems-semantic-cache-poisoning-and-its-counterm.md  101.6KB
│   │   └── test.txt  4B
│   ├── raw/
│   │   ├── ai-code-generation-security-study.pdf  3.1MB
│   │   ├── failureatlas-a-taxonomy-of-failure-modes-in-multi-provider-llm-serving-infrastru.pdf  378.8KB
│   │   ├── gptcache-an-open-source-semantic-cache-for-llm-applications-enabling-faster-answ.pdf  180.9KB
│   │   ├── semantic-adversarial-examples-2018.pdf  381.3KB
│   │   ├── tamarin-hsq-reversible-hierarchical-kv-cache-compression-for-llm-inference-2026.pdf  215.8KB
│   │   └── when-cache-poisoning-meets-llm-systems-semantic-cache-poisoning-and-its-counterm.pdf  1.8MB
│   ├── reports/
│   │   ├── agent-os-layers-capabilities-fe30a0/
│   │   │   └── final_report_agent-os-layers-capabilities-fe30a0.md  38.5KB
│   │   ├── ai-productivity-tools-096ea7/
│   │   │   └── final_report_ai-productivity-tools-096ea7.md  55.9KB
│   │   └── litellm-cost-perf-ops-506ad8/
│   │       └── final_report_litellm-cost-perf-ops-506ad8.md  44.6KB
│   └── runs/
│       ├── agent-os-layers-capabilities-fe30a0/
│       │   ├── shims/
│       │   ├── temp/
│       │   ├── audit_findings.json  211B
│       │   ├── cite-check-findings-a.json  2.9KB
│       │   ├── cite-check-findings-b.json  1.1KB
│       │   ├── cite-check-findings.json  781B
│       │   ├── cite-check-pairs.json  34.3KB
│       │   ├── cite-check-patch-log.json  731B
│       │   ├── comparisons.md  8.1KB
│       │   ├── corpus-critic-gaps.json  1.5KB
│       │   ├── critic-findings-depth.json  7.3KB
│       │   ├── critic-findings-dialectic.json  7.8KB
│       │   ├── critic-findings-instruction.json  2.5KB
│       │   ├── critic-findings-width.json  2.6KB
│       │   ├── events.jsonl  4.1KB
│       │   ├── loci-a.json  9.9KB
│       │   ├── loci-b.json  9.5KB
│       │   ├── loci.json  9.2KB
│       │   ├── patch-log.json  4.1KB
│       │   ├── polish-log.json  516B
│       │   ├── prompt-decomposition.json  10.5KB
│       │   ├── query.md  2.0KB
│       │   ├── readability-decisions.json  255B
│       │   ├── readability-recommendations.json  15.5KB
│       │   ├── run.json  4.2KB
│       │   └── scaffold.md  5.4KB
│       ├── ai-productivity-tools-096ea7/
│       │   ├── shims/
│       │   ├── temp/
│       │   ├── cite-check-findings.json  41.1KB
│       │   ├── cite-check-pairs.json  33.9KB
│       │   ├── cite-check-patch-log.json  196B
│       │   ├── comparisons.md  6.1KB
│       │   ├── corpus-critic-gaps.json  2.7KB
│       │   ├── critic-findings-depth.json  3.1KB
│       │   ├── critic-findings-dialectic.json  437B
│       │   ├── critic-findings-instruction.json  493B
│       │   ├── critic-findings-width.json  1.1KB
│       │   ├── events.jsonl  2.2KB
│       │   ├── loci-a.json  3.1KB
│       │   ├── loci-b.json  3.8KB
│       │   ├── loci-c.json  2.2KB
│       │   ├── loci.json  7.3KB
│       │   ├── patch-log.json  1.0KB
│       │   ├── polish-log.json  280B
│       │   ├── prompt-decomposition.json  3.3KB
│       │   ├── query.md  867B
│       │   ├── readability-decisions.json  120B
│       │   ├── readability-recommendations.json  3B
│       │   ├── run.json  2.6KB
│       │   └── scaffold.md  415B
│       └── litellm-cost-perf-ops-506ad8/
│           ├── shims/
│           ├── temp/
│           ├── audit_findings.json  232B
│           ├── cite-check-findings.json  3B
│           ├── cite-check-pairs.json  7.2KB
│           ├── cite-check-patch-log.json  360B
│           ├── comparisons.md  12.5KB
│           ├── corpus-critic-gaps.json  5.0KB
│           ├── critic-findings-depth-v2.json  3.7KB
│           ├── critic-findings-depth.json  3.7KB
│           ├── critic-findings-dialectic-v2.json  7.0KB
│           ├── critic-findings-dialectic.json  7.0KB
│           ├── critic-findings-instruction-v2.json  16B
│           ├── critic-findings-instruction.json  16B
│           ├── critic-findings-width-v2.json  6.3KB
│           ├── critic-findings-width.json  6.3KB
│           ├── events.jsonl  3.9KB
│           ├── loci.json  7.3KB
│           ├── patch-log.json  1.7KB
│           ├── polish-log.json  35B
│           ├── prompt-decomposition.json  5.9KB
│           ├── query.md  433B
│           ├── readability-decisions.json  964B
│           ├── readability-recommendations.json  8.5KB
│           ├── run.json  3.2KB
│           └── scaffold.md  2.5KB
├── scripts/
│   └── capture-model-usage.sh  3.4KB
├── src/
│   └── hyperresearch/
│       ├── cli/
│       │   ├── __init__.py  6.5KB
│       │   ├── _output.py  4.1KB
│       │   ├── archive.py  6.1KB
│       │   ├── assets.py  3.7KB
│       │   ├── batch.py  12.8KB
│       │   ├── citecheck_cmd.py  2.9KB
│       │   ├── claims_cmd.py  6.8KB
│       │   ├── config_cmd.py  4.4KB
│       │   ├── dedup.py  4.8KB
│       │   ├── embed_cmd.py  2.5KB
│       │   ├── escalation_cmd.py  10.9KB
│       │   ├── export.py  4.3KB
│       │   ├── fetch.py  35.8KB
│       │   ├── fetch_batch.py  14.1KB
│       │   ├── git_cmd.py  5.6KB
│       │   ├── graph.py  11.1KB
│       │   ├── import_cmd.py  3.1KB
│       │   ├── index.py  2.4KB
│       │   ├── install.py  10.6KB
│       │   ├── levers_cmd.py  3.7KB
│       │   ├── link.py  2.8KB
│       │   ├── lint.py  93.0KB
│       │   ├── main.py  5.9KB
│       │   ├── mcp_cmd.py  498B
│       │   ├── note.py  28.4KB
│       │   ├── profile_cmd.py  8.4KB
│       │   ├── repair.py  10.7KB
│       │   ├── research.py  11.8KB
│       │   ├── run_cmd.py  20.9KB
│       │   ├── scholar_cmd.py  8.3KB
│       │   ├── search.py  9.9KB
│       │   ├── serve.py  746B
│       │   ├── setup.py  12.5KB
│       │   ├── sources.py  9.3KB
│       │   ├── tag.py  4.6KB
│       │   ├── template.py  1.6KB
│       │   ├── topic.py  5.6KB
│       │   ├── vault_tag.py  5.4KB
│       │   └── watch.py  4.1KB
│       ├── core/
│       │   ├── __init__.py  29B
│       │   ├── agent_docs.py  4.4KB
│       │   ├── citecheck.py  8.2KB
│       │   ├── claims.py  15.3KB
│       │   ├── config.py  18.3KB
│       │   ├── contracts.py  3.5KB
│       │   ├── db.py  8.9KB
│       │   ├── embed.py  6.5KB
│       │   ├── enrich.py  3.6KB
│       │   ├── escalation.py  6.1KB
│       │   ├── fetcher.py  8.7KB
│       │   ├── frontmatter.py  1.6KB
│       │   ├── graphrank.py  3.6KB
│       │   ├── hooks.py  20.5KB
│       │   ├── independence.py  5.7KB
│       │   ├── levers.py  13.5KB
│       │   ├── linker.py  4.5KB
│       │   ├── migrations.py  14.1KB
│       │   ├── note.py  5.8KB
│       │   ├── oa.py  32.4KB
│       │   ├── patterns.py  5.4KB
│       │   ├── profiles.py  17.2KB
│       │   ├── quality.py  2.6KB
│       │   ├── render.py  3.4KB
│       │   ├── runs.py  29.6KB
│       │   ├── scholar.py  16.8KB
│       │   ├── similarity.py  2.4KB
│       │   ├── sync.py  16.1KB
│       │   ├── templates.py  3.0KB
│       │   ├── untrusted.py  2.7KB
│       │   └── vault.py  7.4KB
│       ├── export/
│       │   └── __init__.py  25B
│       ├── graph/
│       │   └── __init__.py  34B
│       ├── indexgen/
│       │   ├── __init__.py  41B
│       │   └── generator.py  11.1KB
│       ├── mcp/
│       │   ├── __init__.py  96B
│       │   └── server.py  18.5KB
│       ├── models/
│       │   ├── __init__.py  57B
│       │   ├── graph.py  388B
│       │   ├── note.py  5.7KB
│       │   ├── output.py  831B
│       │   └── search.py  401B
│       ├── scholar/
│       │   ├── providers/
│       │   ├── __init__.py  295B
│       │   ├── base.py  12.0KB
│       │   ├── dedup.py  7.1KB
│       │   └── registry.py  3.2KB
│       ├── search/
│       │   ├── __init__.py  40B
│       │   ├── filters.py  3.4KB
│       │   └── fts.py  6.9KB
│       ├── serve/
│       │   ├── __init__.py  60B
│       │   ├── renderer.py  5.7KB
│       │   └── server.py  27.1KB
│       ├── skills/
│       │   ├── roles/
│       │   ├── __init__.py  40B
│       │   ├── hyperresearch-1-5-chapter-partition.md  6.2KB
│       │   ├── hyperresearch-1-decompose.md  15.4KB
│       │   ├── hyperresearch-10-triple-draft.md  14.7KB
│       │   ├── hyperresearch-11-synthesize.md  12.9KB
│       │   ├── hyperresearch-12-critics.md  3.6KB
│       │   ├── hyperresearch-13-gap-fetch.md  4.3KB
│       │   ├── hyperresearch-14-5-cite-check.md  4.7KB
│       │   ├── hyperresearch-14-patcher.md  8.5KB
│       │   ├── hyperresearch-15-polish.md  7.5KB
│       │   ├── hyperresearch-16-readability-audit.md  7.6KB
│       │   ├── hyperresearch-2-width-sweep.md  20.3KB
│       │   ├── hyperresearch-3-contradiction-graph.md  3.5KB
│       │   ├── hyperresearch-4-loci-analysis.md  7.4KB
│       │   ├── hyperresearch-5-depth-investigation.md  4.5KB
│       │   ├── hyperresearch-6-cross-locus-reconcile.md  4.8KB
│       │   ├── hyperresearch-7-source-tensions.md  5.4KB
│       │   ├── hyperresearch-8-corpus-critic.md  7.8KB
│       │   ├── hyperresearch-9-evidence-digest.md  3.8KB
│       │   └── hyperresearch.md  24.8KB
│       ├── web/
│       │   ├── __init__.py  85B
│       │   ├── base.py  9.3KB
│       │   ├── builtin.py  5.3KB
│       │   ├── crawl4ai_provider.py  20.3KB
│       │   ├── exa_provider.py  4.4KB
│       │   ├── parallel_provider.py  7.9KB
│       │   ├── pdf.py  10.5KB
│       │   ├── safe_http.py  10.1KB
│       │   ├── serply_provider.py  3.8KB
│       │   └── tavily_provider.py  3.3KB
│       ├── __init__.py  86B
│       ├── __main__.py  132B
│       └── py.typed  0B
├── tests/
│   ├── fixtures/
│   │   └── golden_prompts/
│   │       ├── agents/
│   │       └── skills/
│   ├── test_cli/
│   │   ├── __init__.py  0B
│   │   ├── test_archive.py  6.4KB
│   │   ├── test_commands.py  9.1KB
│   │   ├── test_fetch_batch.py  1.9KB
│   │   ├── test_install_browser.py  2.5KB
│   │   ├── test_install_profile.py  6.3KB
│   │   ├── test_lint.py  58.3KB
│   │   ├── test_note_ops.py  5.9KB
│   │   ├── test_oa_fetch.py  11.1KB
│   │   ├── test_orphan_dedup_call_sites.py  6.9KB
│   │   └── test_vault_tag.py  4.3KB
│   ├── test_core/
│   │   ├── __init__.py  0B
│   │   ├── test_claims_and_embed.py  15.3KB
│   │   ├── test_config_sections.py  10.9KB
│   │   ├── test_contracts.py  3.9KB
│   │   ├── test_dissertation_profile.py  5.1KB
│   │   ├── test_escalation.py  10.8KB
│   │   ├── test_fetcher_orphan_dedup.py  2.0KB
│   │   ├── test_frontmatter.py  2.3KB
│   │   ├── test_hooks.py  8.9KB
│   │   ├── test_levers.py  8.8KB
│   │   ├── test_note.py  8.9KB
│   │   ├── test_oa_core_resolver.py  27.0KB
│   │   ├── test_oa_recovery.py  29.8KB
│   │   ├── test_packaging.py  1.0KB
│   │   ├── test_patterns.py  9.5KB
│   │   ├── test_profiles.py  16.4KB
│   │   ├── test_prompt_golden.py  17.8KB
│   │   ├── test_render.py  2.7KB
│   │   ├── test_run_tag_validation.py  3.4KB
│   │   ├── test_runs.py  20.2KB
│   │   ├── test_scholar_enrichment.py  21.4KB
│   │   ├── test_source_ranking.py  10.8KB
│   │   ├── test_sync.py  13.0KB
│   │   ├── test_untrusted.py  5.6KB
│   │   ├── test_vault.py  2.6KB
│   │   └── test_verification.py  46.1KB
│   ├── test_graph/
│   │   ├── __init__.py  0B
│   │   └── test_links.py  2.7KB
│   ├── test_mcp/
│   │   ├── __init__.py  0B
│   │   └── test_update_note.py  2.0KB
│   ├── test_scholar/
│   │   ├── __init__.py  0B
│   │   ├── test_cli.py  13.5KB
│   │   ├── test_clinicaltrials.py  8.1KB
│   │   ├── test_core_provider.py  12.3KB
│   │   ├── test_crossref.py  14.1KB
│   │   ├── test_dedup.py  8.8KB
│   │   ├── test_doab.py  17.1KB
│   │   ├── test_edgar.py  9.9KB
│   │   ├── test_fred.py  8.8KB
│   │   ├── test_openalex.py  13.3KB
│   │   └── test_repec.py  3.7KB
│   ├── test_search/
│   │   ├── __init__.py  0B
│   │   └── test_fts.py  3.7KB
│   ├── test_serve/
│   │   ├── __init__.py  0B
│   │   ├── test_server.py  6.2KB
│   │   └── test_xss.py  3.8KB
│   ├── test_web/
│   │   ├── __init__.py  0B
│   │   ├── test_builtin_pdf_lane.py  5.6KB
│   │   ├── test_crawl4ai_running_loop.py  3.5KB
│   │   ├── test_crawl4ai_stealth.py  2.2KB
│   │   ├── test_exa_provider.py  7.2KB
│   │   ├── test_fetch_many_fallback.py  3.7KB
│   │   ├── test_fetch_many_gate.py  2.6KB
│   │   ├── test_fetch_settings.py  4.8KB
│   │   ├── test_final_url_recheck.py  6.5KB
│   │   ├── test_junk_detection.py  5.0KB
│   │   ├── test_parallel_provider.py  10.8KB
│   │   ├── test_pdf_diagnostics.py  10.7KB
│   │   ├── test_safe_http.py  14.9KB
│   │   ├── test_serply_provider.py  4.1KB
│   │   └── test_tavily_provider.py  4.5KB
│   ├── __init__.py  0B
│   └── conftest.py  2.8KB
├── .gitignore  743B
├── .mcp.json  1.1KB -> /home/monster/agentspace/.mcp.json
├── CHANGELOG.md  94.8KB
├── CONTRIBUTING.md  2.3KB
├── LICENSE  1.0KB
├── pyproject.toml  3.2KB
├── README.md  11.5KB
└── uv.lock  557.6KB

Listed: 523 files, 22.8MB; depth limit: 3
