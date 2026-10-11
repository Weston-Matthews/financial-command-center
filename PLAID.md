# Bank linking (Plaid-style) — design notes

This app is **cash-flow first** and already works fully offline with manual balances, the bill book, and CSV/Excel statement import. Live bank aggregation is optional and should never be on the critical path.

## Goals if we add it

1. Refresh **account balances** without typing them.
2. Pull **transactions** into the existing `transactions` table (same shape as CSV import).
3. Optionally **suggest** recurring obligations from repeated merchants — user confirms before anything is added to the bill book.
4. Fail soft: if a link breaks, Command Center still runs on last known balances + bill book.

## What we would not do

- Store bank usernames/passwords ourselves (use OAuth / Link only).
- Require Plaid to open the app or compute safe-to-spend.
- Auto-mutate the bill book without confirmation.
- Send full transaction history to the LLM Advanced Coach by default (snapshot stays aggregated unless the user opts in later).

## Suggested architecture

```
Browser
  └─ Plaid Link (client) → public_token
Server
  └─ POST /api/plaid/exchange → access_token (encrypted at rest)
  └─ POST /api/plaid/sync
        → accounts balances → UPDATE accounts
        → transactions → INSERT OR IGNORE transactions (same dedupe as CSV)
  └─ Cron or manual “Sync” button
```

### Data model additions

| Table | Purpose |
|---|---|
| `plaid_items` | item_id, access_token (encrypted), institution_name, cursor, status |
| `plaid_accounts` | map plaid account_id → local `accounts.id` |
| Existing `transactions` | already has account_id, date, description, amount, balance, source |

Set `source = 'plaid'` on synced rows so CSV and Plaid can coexist with dedupe rules.

### Sync product flow

1. User clicks **Link institution** on Accounts.
2. Plaid Link completes → server stores item.
3. User maps each remote account to a local account (or create new).
4. **Sync** pulls balances + transactions since cursor.
5. Banner: “Last synced … · N new transactions.”
6. Separate action: **Suggest bills from merchants** → review list → add to obligations.

### Credentials & cost

- Plaid needs `PLAID_CLIENT_ID`, `PLAID_SECRET`, env (`sandbox` / `development` / `production`).
- Sandbox first; production requires application review.
- Pricing is per Item / product (Transactions, Auth, etc.) — keep Balances + Transactions only unless we need Identity.

### Alternatives

| Path | When |
|---|---|
| **CSV / Excel import** (already shipped) | Privacy-first, works with any bank export |
| **SimpleFIN / GoCardless** | Some US / EU banks without full Plaid |
| **OFX/QFX upload** | Desktop banking exports |
| **Plaid** | Convenience when the user accepts a third-party aggregator |

### Security checklist before shipping Link

- [ ] Encrypt access tokens (key from env, not in sqlite plain text)
- [ ] Never return access_token to the browser
- [ ] Webhook signature verification for transaction updates
- [ ] Clear “Disconnect institution” that revokes item
- [ ] Rate-limit sync endpoints
- [ ] Document that Advanced Coach does not receive raw Plaid payloads unless explicitly designed

### Implementation phases

1. **Env + sandbox Link** — exchange token, list accounts, map to local accounts, refresh balances only.
2. **Transactions sync** — cursor-based, feed existing preview/commit mental model.
3. **Recurring suggestions** — from transactions, not auto-write.
4. **Production** — encrypted secrets, webhooks, disconnect, audit log of sync times.

Until then, prefer **statement import** for accuracy and keep the bill book as the source of truth for “what hits which account on which day.”
