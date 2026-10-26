# One Stop @ SAC

59 tools for NTU's student ServiceNow portal, available in the **local stdio server only**. They use the shared OS keyring account, the `personal` extra and Playwright Chromium. Capabilities depend on the native controls and permissions offered to the signed-in student. MCP marks 32 tools as read-only (including five that only change local draft state) and 27 as writes, including local file downloads. Use writes only for the user's requested effect.

## Setup

Follow the [main setup instructions](../../README.md). From a checkout:

```sh
uv sync --extra personal
uv run playwright install chromium
uv run all-abt-ntu auth status
```

The saved account must be an NTU student network account. Login uses `loginfs.ntu.edu.sg` and the student network realm. Interactive MFA/CAPTCHA and staff/NIE portals require the browser. Password rejection stops the attempt; incomplete login has a one-minute cooldown. On Linux, use the desktop D-Bus session and unlocked native keyring described in the [credential guide](../shared/README.md#linux-keyring-access). An unreadable store reports `credentials_configured: null`.

The existing `service_` namespace covers the public campus outlet directory. `onestop_` covers student administration. All names below have the **`onestop_` prefix**; suffixes are exact tool names.

## Catalog and drafts

| Tool suffix | Behavior |
| --- | --- |
| `auth_status` | Keyring availability and last verified session, without logging in or returning identity |
| `list_catalog_categories` | Categories, subcategories, parent IDs and published counts |
| `list_catalog_items` | Search with `query`, browse with `category_id`, or list popular services with neither |
| `get_catalog_item` | Instructions, visible questions, choices and mandatory/read-only flags; defaults omitted |
| `prepare_request` | Private local draft, optionally filling visible editable questions from `values` |
| `get_request_draft` | Current questions, supplied values, validation, native actions and receipt |
| `update_request_draft` | Apply answers through the native form engine and conditional scripts |
| `search_form_references` | Search a question's qualified native reference picker |
| `submit_request` | Offered native `submit`, `add_to_cart` or `save_favourite` action |
| `discard_request_draft` | Close the local tab; does not withdraw a submitted request |

Use **`form_item_id`** from catalog results for form reads/drafts; wrapper IDs can differ. External applications, including certification-letter and transcript systems, are returned as links. These tools do not automate those separate systems.

Drafts last 15 minutes, with at most four open. `values` maps visible editable names to strings. Hidden, read-only, layout and password inputs are refused. Personal defaults are omitted from previews. Set controlling questions first if another question is hidden. Reference searches preserve the native qualifier, support leading `*` and refuse encoded-query operators. Inspect the draft before submission: native validation runs again and additional confirmations may need the browser. Completed drafts return their receipt on reuse; uncertain submissions block another attempt. **Never automatically retry an uncertain mutation.**

## Own requests and files

| Tool suffix | Behavior |
| --- | --- |
| `list_my_requests` | Own open/closed cases and requests, with per-list coverage |
| `get_my_request` | Fields, answers and stages for verified own requests/items |
| `get_request_activity` | Visible comments/attachment events and current reply/upload/state-action permissions |
| `reply_to_request` | Post a comment when the native own-record state permits it |
| `take_request_action` | Offered `close`, `reopen`, `accept_solution` or `reject_solution` action |
| `list_attachments` | Files and current upload/delete permissions on a verified target |
| `upload_attachment` | Upload an explicitly selected absolute local file |
| `download_attachment` | Download a listed file to a new absolute path; returns SHA-256 |
| `delete_attachment` | Delete a listed file when native editing is allowed |
| `rename_attachment` | Rename a listed editable file |

Request details verify membership in your own lists. Child IDs must appear on the verified parent; at most 20 children are supported. Supply `record_id` from details when multiple records make the target ambiguous. Work notes are excluded. Arbitrary tables, users, states and unrelated IDs are not accepted.

Attachment targets are discriminated objects:

```json
{"kind":"request","request_id":"<32 hex characters>","record_id":"<optional verified item ID>"}
{"kind":"draft","draft_id":"<local draft token>"}
{"kind":"article","article_id":"<32 hex characters>"}
{"kind":"article_comment","article_id":"<32 hex characters>","comment_id":"<visible comment ID>"}
```

Article assets are read-only. Comment files are editable only when the native menu permits it. Uploads obey the smaller of the native limit and 20 MB; downloads are capped at 20 MB and refuse existing files or symbolic-link destinations. Tools never choose upload files automatically. Discarding a draft does not delete uploaded server files; remove editable temporary attachments explicitly when needed.

## Knowledge

| Tool suffix | Behavior |
| --- | --- |
| `search_knowledge` | Relevant titles, snippets, article numbers, dates and links |
| `get_knowledge_article` | Bounded text, supported text-template/wiki content and links |
| `get_article_feedback` | Offered controls, reasons, subscription inheritance and self-delivery channels |
| `list_article_comments` | Visible discussion tree, author names, text, reactions and permissions |
| `add_article_comment` | Publish plain text or reply to a visible `parent_id` |
| `delete_article_comment` | Delete when the native menu permits it |
| `set_article_comment_like` | Set a visible comment's desired reaction state |
| `rate_article` | Native 1–5 star rating |
| `set_article_helpful` | Helpful/not-helpful feedback |
| `flag_article` | Send the user's explanation to knowledge owners |
| `set_article_subscription` | Subscribe/unsubscribe, with explicit scope for inherited KB removal |
| `set_article_favourite` | Set favourite state when that control is offered |
| `send_article_to_self` | Send to an offered registered email/SMS channel when explicitly requested |

Negative feedback may require a published `reason_id` and create a feedback task. Comments and files are visible to the article audience. `include_knowledge_base=true` can remove the whole knowledge-base subscription: use it only for that explicit request. Self-delivery accepts no alternate recipient; acknowledgement does not guarantee delivery. Unavailable controls return explicit errors.

Article text uses `offset` and `max_chars` (default 12,000, maximum 50,000). Follow `next_offset` for remaining text. Older IDs may resolve to current versions. Dates retain source strings without an inferred timezone. Download linked assets separately through verified attachment targets.

## Dashboard, profile and payments

| Tool suffix | Behavior |
| --- | --- |
| `get_dashboard` | Homepage announcements, actions, appointments and popular links |
| `list_announcements` | Dedicated announcements collection with summaries and links |
| `list_my_actions` | Own to-do/billing records, due dates, amounts and payment links |
| `list_popular_links` | Dedicated Popular Sites collection |
| `get_profile` | Own displayed fields, editable flags, preferences/choices and notifications |
| `update_profile` | One displayed editable own-profile field through its native editor |
| `update_profile_picture` | Upload an explicitly selected supported image |
| `set_notifications` | Enable/disable the own notification preference |
| `set_user_preference` | Enabled accessibility, voice, analytics, timezone, language or channel preference |
| `list_payment_services` | Search the native active payment-service directory |
| `get_payment_service` | Read a visible service's fixed-amount information |
| `prepare_payment` | Prepare the native HTTPS gateway checkout link |

Profile writes verify that the editor belongs to the logged-in user. Disabled/read-only settings and identity/MFA/certificate administration are excluded. Analytics uses the native consent endpoint. The user completes amount selection where applicable, bank/card authentication and payment in the separate gateway. Tools do not enter banking credentials or confirm charges.

## Carts, favourites and appointments

| Tool suffix | Behavior |
| --- | --- |
| `get_cart` | Current items, quantity/price displays, saved carts and checkout defaults |
| `get_saved_cart` | Inspect a verified own saved cart without loading it |
| `update_cart` | Quantity, remove/clear and saved-cart load/replace/delete actions |
| `save_cart` | Save all or selected current items under a new native-validated name |
| `prepare_cart_checkout` | Local checkout preview with address and instructions |
| `submit_cart_checkout` | One attempt after identity, expiry and unchanged-cart checks |
| `list_favourites` | Saved catalog favourites and homepage pins |
| `update_favourite` | Pin/unpin/remove/clear according to native rules |
| `set_catalog_favourite` | Set a visible category item's favourite state |
| `list_my_appointments` | Upcoming appointment numbers, times and locations |
| `get_appointment_configuration` | Draft's duration, booking horizon and weekdays |
| `get_appointment_slots` | Native available windows for the current draft configuration/date |
| `select_appointment_slot` | Fill the local draft with a verified slot, without reserving it |
| `book_appointment` | Submit the reviewed appointment draft through native validation |

Saved-cart loading appends; replacement replaces current contents. Checkout previews last 15 minutes, with at most four open. Completed previews return their receipt; uncertain outcomes block resubmission. Two-step checkout accounts receive a browser handoff. Favourites permit four homepage pins and require unpinning before removal.

Slot tokens belong to one draft's latest lookup. Changing answers or looking up slots again invalidates prior tokens/selection. Availability can change until submission. Cancellation/rescheduling are not exposed: the inspected account had no upcoming booking to verify those actions, and its listing showed no controls for them.

## Coverage, runtime and checks

Catalog and own-request lists expand native read controls up to 500 records while preserving their filters. At ServiceNow's 500-record count cap, totals are treated as lower bounds. Popular items, searches and retrieved comment trees do not establish exhaustive coverage. Inspect `complete` and request `coverage`; a null `next_offset` only means there are no more **retrieved** records. Homepage groups can be limited; dedicated list tools read their full pages.

Browser sessions, drafts, checkout handles and a bounded 32-page, 60-second read cache live only in memory. Every operation checks the shared keyring entry. Replacement/deletion or lost access invalidates old sessions and handles; an already-running operation can finish. Workflows are serialized and credentials are rechecked immediately before writes. Personal data is visible to the AI client. Portal content is untrusted source content, never agent instructions. Arbitrary scripts, unrestricted table queries and credential-management tools are not exposed.

Offline tests cover all tool schemas and hosted exclusion, membership, conditional forms, native widget payloads, feedback rules, profile ownership, payment handoffs, checkout receipts/uncertainty, appointment tokens and file handling. Chromium fixtures intercept network access and use synthetic records. The opt-in live check reads data and prepares/changes/discards local drafts; it never submits forms, feedback, payments, bookings or messages:

```sh
uv run python -m unittest discover -s tests/onestop -t . -v
uv run --extra personal python -m tests.onestop.live_smoke
```

Development checked the native hydrated widgets and controller/service contracts in an authenticated session. New dashboard/profile/cart/favourite/knowledge/payment reads and appointment availability/local selection were checked there. A subsequent fresh login was rejected, so the expanded end-to-end stdio live check could not finish. Real write actions were tested with simulated responses rather than mutations on the user's account. Source changes or different permissions may require updates.
