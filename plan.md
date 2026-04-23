前提を置きます。この Skill は、`SKILL.md` の薄い入口、4本の reference、project state、session state、taxonomy、JSON Lines（JSONL）監査ログ、公開 Command-Line Interface（CLI）から成る「状態付き意思決定エンジン」として実装します。以下では、中核価値を保持しつつ、正本の状態と責務分割を整理した v2 の実装計画を示します。

## 方針選択

今回は **フルスクラッチ実装** を採用します。

理由は3点です。
第一に、重視する価値は **並行セッション、active proposal、taxonomy-aware search、close summary→plan 変換** にあります。
第二に、project-visible state と event log と `session/*.json` の責務が近接しすぎると、運用規約が強くない限り分裂しやすい構造になります。
第三に、破壊的変更が許容されるなら、**正本を一つにし、他は派生状態に落とす** 方が保守性と再構成性が高いです。

## v2 で採用するもの／採用しないもの

| 項目                                        | v2での扱い          | 判断                           |
| ----------------------------------------- | --------------- | ---------------------------- |
| 単一 public skill entrypoint                | 維持              | 利用者の入口は一つのままにします。            |
| 並行セッション、Resume/Close/Generate plan        | 維持              | 利用体験の中核です。                  |
| active proposal と plain `OK` 規則           | 維持しつつ改良         | `proposal_id` を追加して曖昧性を下げます。 |
| taxonomy と compatibility tags             | 維持              | 過去セッション再検索のため必須です。           |
| JSONL 監査ログ                                | 維持しつつ正本化        | v2 では event log を正本にします。     |
| project-visible decision state を projection に置く設計 | 採用              | 正本は event log に限定します。          |
| public CLI surface                       | 統合              | 1本の subcommand 型 CLI に統合します。 |
| human-readable export を runtime 正本にしない設計 | 採用              | 人間向け成果物は export に落とします。      |
| Architecture Decision Record（ADR）         | 任意 export として追加 | 技術判断だけに限定して出力します。            |

## v2 の設計目標

1. **低疲労の聞き取り**
   一度に一問、ただし質問前に codebase / docs / tests / 既存 state を優先的に探索します。

2. **状態付き継続性**
   会話が分かれても、複数の session を並行で持ち、明示的に resume / close / inspect できます。

3. **厳密な提案受理**
   plain `OK` は便利さを残しつつ、`proposal_id` と version を用いて stale acceptance を防ぎます。

4. **検索可能な履歴**
   taxonomy と session index により、過去の判断を後から再利用できます。

5. **計画への接続**
   closed session を plan-ready close summary に変換し、複数 session から action plan を生成できます。

6. **監査可能性**
   「なぜそうなったか」は event log を見れば再構成できるようにします。

## 採用アーキテクチャ

v2 は **event-sourced runtime** を採用します。つまり、正本は append-only の event log で、`project-state.json`、`session/*.json`、`taxonomy-state.json` はそこから再構成できる派生状態です。

### ランタイム構成

```text
.ai/decide-me/
├── event-log.jsonl              # 正本
├── project-state.json           # 派生状態
├── taxonomy-state.json          # 派生状態
├── sessions/
│   └── S-*.json                 # 派生状態
├── exports/
│   ├── plans/
│   └── adr/
└── write.lock                   # 排他制御
```

### この構成にする理由

* project-visible state と session file の二重正本問題を避けられます。
* 並行 session で「無関係な decision を上書きする」事故を減らせます。
* `rebuild-projections` で state を event log から再生成できます。
* JSONL 監査ログがそのまま provenance になります。

## リポジトリ構成

```text
decide-me/
├── SKILL.md
├── references/
│   ├── protocol-overview.md
│   ├── interview-engine.md
│   ├── session-lifecycle.md
│   ├── search-and-taxonomy.md
│   ├── event-and-projection-model.md
│   ├── plan-generation.md
│   ├── output-contract.md
│   └── examples.md
├── schemas/
│   ├── event-envelope.schema.json
│   ├── project-state.schema.json
│   ├── session-state.schema.json
│   ├── taxonomy-state.schema.json
│   ├── close-summary.schema.json
│   └── plan.schema.json
├── templates/
│   ├── adr-template.md
│   └── plan-template.md
├── scripts/
│   └── decide_me.py
├── decide_me/
│   ├── __init__.py
│   ├── store.py
│   ├── events.py
│   ├── projections.py
│   ├── selector.py
│   ├── protocol.py
│   ├── lifecycle.py
│   ├── taxonomy.py
│   ├── search.py
│   ├── planner.py
│   ├── exports.py
│   └── validate.py
└── tests/
    ├── unit/
    ├── integration/
    └── fixtures/
```

## 正本イベントモデル

v2 の正本は、flat な ad hoc JSONL ではなく、**共通 envelope を持つ typed event** にします。

### event envelope

```json
{
  "event_id": "E-20260423-000123",
  "ts": "2026-04-23T10:15:00Z",
  "session_id": "S-20260423-101500-a1",
  "event_type": "proposal_issued",
  "project_version_after": 12,
  "payload": {}
}
```

### 主要 event_type

* `project_initialized`
* `session_created`
* `session_resumed`
* `decision_discovered`
* `question_asked`
* `proposal_issued`
* `proposal_accepted`
* `proposal_rejected`
* `decision_deferred`
* `decision_resolved_by_evidence`
* `session_classified`
* `close_summary_generated`
* `session_closed`
* `plan_generated`
* `taxonomy_extended`
* `compatibility_backfilled`

### 改良点

log entry は平坦にせず、envelope を固定し、payload を event_type ごとに schema で検証します。

## project-state の設計

`project-state.json` は event log から再構成される materialized projection です。人間向け台帳ではなく、**現在の project-visible decision state** を表します。

### 主なフィールド

* `project`: name, objective, current_milestone, stop_rule
* `state`: project_version, updated_at, last_event_id
* `protocol`: plain_ok_scope, proposal_expiry_rules, close_policy
* `counts`: p0_now_open, blocked, deferred など
* `default_bundles`: 低リスクな P2 群をまとめる bundle
* `decisions`: decision graph

### decision record

各 decision には最低限、次を持たせます。

* `id`, `title`, `kind`
* `domain`
* `priority` (`P0`, `P1`, `P2`)
* `frontier` (`now`, `later`, `discovered-later`, `deferred`)
* `status`
* `resolvable_by` (`human`, `codebase`, `docs`, `tests`, `external`)
* `reversibility`
* `depends_on`, `blocked_by`
* `question`
* `context`
* `options`
* `recommendation`
* `accepted_answer`
* `evidence_refs`
* `revisit_triggers`
* `notes`
* `bundle_id`（該当時）

### 新規追加する観点

decision record には、次の観点も明示的に追加します。

* `kind`: constraint / choice / risk / dependency など
* `reversibility`: reversible / hard-to-reverse / irreversible
* `proposal_id`: recommendation version とは別に user-facing な安定識別子
* `resolved_by_evidence`: 証拠による自動解決の痕跡

これにより、比較・記録の観点を runtime に自然に統合できます。

## session-state の設計

`session/*.json` は会話ごとの局所状態です。正本ではありませんが、現在の対話継続に必要な working memory を持ちます。

### 主なフィールド

* `session`: id, started_at, last_seen_at, bound_context_hint
* `lifecycle`: active / idle / stale / closed
* `summary.latest_summary`
* `summary.current_question_preview`
* `summary.active_decision_id`
* `classification`: domain, abstraction_level, assigned_tags, compatibility_tags, search_terms, source_refs
* `close_summary`
* `working_state.current_question_id`
* `working_state.current_question`
* `working_state.active_proposal`
* `working_state.last_seen_project_version`

### active_proposal の改良

active_proposal は `decision_id + recommendation_version` だけに寄せず、次の shape にします。

```json
{
  "proposal_id": "P-0007",
  "target_type": "decision",
  "target_id": "D-012",
  "recommendation_version": 3,
  "based_on_project_version": 12,
  "is_active": true,
  "activated_at": "...",
  "inactive_reason": null
}
```

bundle 提案も扱えるように、`target_type` を `decision | bundle` にします。

## taxonomy-state の設計

taxonomy は additive evolution を維持しつつ運用します。

### 維持する仕様

* `domain` と `abstraction_level` は required axis
* taxonomy node は `id`, `label`, `aliases`, `parent_id`, `replaced_by`, `status`, `created_at`, `updated_at`
* additive evolution のみ
* closed session は assigned tag を凍結
* taxonomy 進化後は compatibility tag を lazy backfill
* 検索は label / alias / descendant / replaced_by chain を展開

### 改良点

* classification source を event payload に残す
* `search_terms` の追加理由を compact に event log に記録
* `session-classified` を `classification_updated` に統一して payload schema を厳密化

## 対話プロトコル

## 1. 起動と再調停

`SKILL.md` は起動時に次を行います。

1. `.ai/decide-me/` を確認
2. `project-state.json`, `taxonomy-state.json`, `sessions/*.json` を読む
3. `event-log.jsonl` と projection の整合性を検証
4. current session がなければ新規作成
5. active proposal を project version と照合し、stale 判定
6. 質問前に evidence scan を実施

## 2. evidence-first 質問抑制

質問前に、次の順で解けないかを見ます。

1. codebase
2. docs
3. tests
4. existing decisions / close summaries
5. それでも足りなければ user

解けた場合は質問せず、`Resolved by evidence:` 形式で decision を更新します。

## 3. 一問一答プロトコル

質問ターンは必ず次の構造にします。

```text
Decision: D-012
Proposal: P-0007
Question: Should the MVP use email magic links or passwords?
Recommendation: Use email magic links for the MVP.
Why: Lower coordination and implementation burden for the current milestone.
If not: Password reset, password policy, and credential recovery flows become in-scope now.
```

`Decision:` `Recommendation:` `Why:` `If not:` の contract を維持し、`Proposal:` を追加します。

## 4. plain `OK` と explicit accept

* plain `OK` は、**同一 session の直後の user turn** で、かつ active proposal が still-valid の場合のみ有効
* stale なら受理しない
* stale または曖昧な場合は `Accept P-0007` を要求
* `Accept P-0007` は常に最優先
* `Accept bundle B-003` も許可

これにより、受理対象の曖昧性を下げられます。

## 5. stop rule

* すべての relevant `P0` かつ `frontier=now` が resolved / accepted / explicitly deferred になったら停止
* `P1` / `P2` は、milestone readiness を阻害しない限り聞き切らない
* `P2` は default bundle にまとめてよい

## 6. close summary と plan generation

session close 時には必ず `close_summary` を生成し、初版から schema 化します。

### close_summary 必須項目

* work_item_title
* work_item_statement
* goal
* readiness (`ready`, `conditional`, `blocked`)
* accepted_decisions
* deferred_decisions
* unresolved_blockers
* unresolved_risks
* candidate_workstreams
* candidate_action_slices
* evidence_refs
* generated_at

### plan generation 規則

* source session は closed のみ
* conflict があれば `Conflicts:` のみ返す
* conflict がなければ `Action Plan:` を返す
* unresolved `P0` + `frontier=now` が残る場合は conditional plan を返す

### conflict check

最低限、次を検出します。

* 同一 decision ID に対する accepted answer の不一致
* mutually exclusive な workstream scope
* 同一 action slice 名に対する責務の不一致

## public Command-Line Interface (CLI)

公開 CLI は 1 本の subcommand 型に統合します。

```bash
python3 scripts/decide_me.py bootstrap --ai-dir .ai/decide-me --project-name ... --objective ...
python3 scripts/decide_me.py list-sessions --ai-dir .ai/decide-me
python3 scripts/decide_me.py show-session --ai-dir .ai/decide-me --session-id S-...
python3 scripts/decide_me.py resume-session --ai-dir .ai/decide-me --session-id S-...
python3 scripts/decide_me.py close-session --ai-dir .ai/decide-me --session-id S-...
python3 scripts/decide_me.py generate-plan --ai-dir .ai/decide-me --session-id S-... --session-id S-...
python3 scripts/decide_me.py rebuild-projections --ai-dir .ai/decide-me
python3 scripts/decide_me.py validate-state --ai-dir .ai/decide-me
python3 scripts/decide_me.py export-adr --ai-dir .ai/decide-me --decision-id D-...
```

session classification は internal command に統合します。

## 実装フェーズ

| Phase | 内容                                      | 成果物                                                              | 完了条件                                             |
| ----- | --------------------------------------- | ---------------------------------------------------------------- | ------------------------------------------------ |
| 0     | 仕様凍結                                    | `SKILL.md` 骨子、references 目次、schema list                          | runtime 正本と output contract が固定される               |
| 1     | repository skeleton                     | `references/`, `schemas/`, `scripts/`, `decide_me/`, `tests/`    | 空の v2 repo が起動可能                                 |
| 2     | event store と projection engine         | `store.py`, `events.py`, `projections.py`, `rebuild-projections` | event append → projection rebuild → validate が通る |
| 3     | project-state / session-state schema 実装 | 各 schema, validator                                              | 不整合 state を検出できる                                 |
| 4     | interview engine 実装                     | `protocol.py`, `selector.py`                                     | 一問一答、evidence-first、plain `OK` 規則が動く             |
| 5     | session lifecycle 実装                    | `lifecycle.py`, list/show/resume/close                           | active/idle/stale/closed が正しく遷移する                |
| 6     | taxonomy/search 実装                      | `taxonomy.py`, `search.py`                                       | query + status/domain/level/tag の検索が通る           |
| 7     | plan generation 実装                      | `planner.py`, `plan.schema.json`                                 | closed sessions から conflict / plan を生成できる        |
| 8     | export layer 実装                         | `exports.py`, ADR / plan template                                | accepted technical decision から ADR を出せる          |
| 9     | test / hardening                        | unit / integration / golden tests                                | multi-session と rebuild が安定する                    |

## テスト計画

## unit test

* taxonomy alias / descendant / replaced_by 展開
* active proposal stale 判定
* priority/frontier selector
* close summary assembly
* conflict detector
* projection rebuild idempotence

## integration test

1. 空の runtime から bootstrap
2. session 作成 → question → plain `OK` 受理
3. parallel session による stale proposal 発生
4. evidence-based resolution
5. close session → list/show
6. multiple closed sessions → conflict
7. multiple closed sessions → conditional plan
8. taxonomy 進化後の old session 検索

## golden prompt test

* 質問ターンの出力 contract
* 受理ターンの出力 contract
* close summary の形
* `Conflicts:` と `Action Plan:` の形

## 受け入れ基準

v2 の完成判定は次です。

1. plain `OK` が stale proposal を誤受理しない
2. 並行 session が同じ project-state を安全に共有できる
3. codebase で解ける decision を user に再質問しない
4. `List/Show/Resume/Close/Generate plan` が state と整合する
5. closed session が taxonomy 進化後も検索できる
6. `rebuild-projections` で event log から state を完全再構成できる
7. conditional plan と conflict blocking が正しく動く
8. human-readable artifact は export であり、runtime 正本ではない
9. validator が schema 違反と projection 不整合を検出できる

## 初版で意図的に捨てるもの

* 複数の公開 CLI
* hidden state
* runtime 正本としての human-readable 台帳
* closed session の reopen flow
* 自動 background compaction

## リスクと対処

最大のリスクは、event-sourcing によって実装がやや重くなることです。対処として、event_type を最小限に保ち、projection は `project-state`, `taxonomy-state`, `session` の3種類に限定します。

次のリスクは taxonomy drift です。対処として、taxonomy は additive evolution のみ許可し、closed session には lazy compatibility backfill を適用します。

もう一つは、Skill が projection と event を不整合に書く危険です。対処として、書き込みは常に `append event → rebuild affected projection → validate → atomic rename` の順に固定し、`validate-state` を必須にします。

## 実装順序の推奨

最初に固定すべきは、**event schema と output contract** です。ここが曖昧だと、session lifecycle と planner が後で崩れます。したがって、着手順は `Phase 0 → Phase 2 → Phase 4 → Phase 5 → Phase 7` の順が安全です。

この v2 は、正本・派生状態・公開操作・人間向け出力を明確に分離した設計になっています。最も重要な点は、**「決定台帳中心」ではなく「event log 中心」の状態付き意思決定エンジンにすること**です。これにより、session continuity, taxonomy search, JSONL audit, plan-ready close summary を整合的に維持できます。
