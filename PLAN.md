# ksefcio Implementation Roadmap

## Phase 1: Login + Key Management
Tightly coupled — first login generates the AES key.

1. Parse .key (encrypted private key) + .pem (certificate) in the browser
2. Challenge-response auth against ksefcio backend (sign nonce with private key)
3. On first login: generate random AES key, wrap with cert public key, upload to server
4. On subsequent logins: download wrapped key, unwrap with private key
5. Store entity (cert+key+AES key) in localStorage via entities store
6. AES key export/import UI in Settings (for multi-device)

## Phase 2: KSeF Sync
Fetching invoices from KSeF through the proxy.

1. KSeF API authentication — XAdES-signed AuthTokenRequest XML (hardest piece — browser-side XAdES signing)
2. Fetch invoice list via KSeF query API
3. Fetch individual invoice XML
4. Encrypt invoice data with AES key, store as blobs on ksefcio server
5. Manual "Sync" button triggers the flow

## Phase 3: Invoice List
Decrypt and display.

1. Fetch encrypted blobs from ksefcio server
2. Decrypt client-side with AES key
3. Parse FA(2) XML, extract key fields (seller, amount, date, due date, bank account)
4. Render table with sorting/filtering
5. Paid/ignored toggle buttons, persisted via PATCH to server

## Phase 4: Invoice Detail
Single invoice view.

1. Parse full FA(2) XML
2. Render readable invoice (line items, tax breakdown, seller/buyer info)

## Phase 5: Payment Basket
Generate payment files.

1. Select unpaid invoices from the list
2. Review selected invoices in basket view
3. Generate mBank payment file for download

## Notes

- Phase 1 unblocks everything
- Phase 2 depends on Phase 1 (need private key for KSeF auth)
- Phases 3-4 depend on Phase 2 (need invoice data)
- Phase 5 is independent once Phase 3 works
- XAdES signing in the browser (Phase 2.1) is the biggest risk / hardest piece
