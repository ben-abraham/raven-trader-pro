# Raven Trader Pro (EXTREMELY ALPHA!) #

The first and (currently) only integrated application for creating asset buy, sell, and trade orders for the ravencoin network via raw transactions. These transactions are signed using `SIGHASH_SINGLE|SIGHASH_ANYONECANPAY` which allows for on-chain swaps to take place with only 2 steps of user interaction, one for each party, and **only a single transaction published to the chain**. The order is fully inspectable at all steps along the way, leading to maximum transparency, while ensuring fast efficient orders can take place.

**Disclaimer: This software is in still in early development, and potentially involves financial transactions, please heavily review all transactions to watch for any potential errors**

# Screenshots #
![image](https://user-images.githubusercontent.com/793454/121434638-9f766a00-c94b-11eb-9bec-dff2b562f53a.png)

Setup:
- Install Python 3.7 & PIP
- Windows: `pip install -r requirements.txt` 
- Linux: `python3.7 -m pip install -r requirements.txt`
- Make sure [raven core wallet](https://github.com/Ravenqt-RVN-SIG/Ravencoin/) is running with the following `raven.conf` variables
- Run the app once and then edit the config files in `~/.raventrader/settings.json` as needed to connect to RPC

Running:
- Windows: `python main.py`
- Linux: `python3.7 main.py`

## raven.conf Variables ##
```
server=1
rpcuser=<user>
rpcpassword=<password>
```

# Instructions #

## Creating a Buy/Sell/Trade Order ##

1. Click "New Buy/Sell/Trade Order"
2. For buying, type and verify an asset name. It will also show the total quantity available.
3. For selling, select an asset from the list of your assets.
4. For trades, select the asset you are providing, and confirm the one you want.
5. Enter the quantity and per-unit price for the order (NOTE: Executors must complete the order in full. Use Order Quantity to split up bulk orders)
6. Set Order Quantity to the number of copies of this trade you want to make
7. [**Optional**] Specify a destination for where the output RVN/Assets should be sent. If not supplied one will be automatically generated like normal.
8. [**TX-Fee**] Either setup all trades now in bulk, or set them up one-at-a-time. (One-at-a-time will have more fee overhead in the long run)
9. Wait for confirmation (Indicated in bottom-left)
10. [**Online**] If posting online, right-click the trade and "Post trade(s) to Server"
11. [**P2P**] If sending direct, double-click the trade and send the "Signed Partial" hex to the counterparty
12. Trades will stay in the list until removed, each execution is added to the history. When a trade reaches 0/0 remaining, you can refill the pool or delete it.

## Completing an Order ##

1. [**Online**] Find a trade in the "Trade Server" dialog
2. [**P2P**] Click "Verify/Complete Order", Paste the hex provided into the "Signed Partial" field.
3. Verify all the order details look as-advertised (make sure the asset name, quantity and unit-price all line up) and Cofirm
4. Verify the final preview order looks accurate.
5. [**TX-Fee**] Execute when ready

## Important Considerations ##

* After creation, orders are not published anywhere, they are simply a partially signed transaction stating one of the following
  * Buy: "I will provide {total price} RVN, send {quantity} of {asset} to this destination"
  * Sell: "I will provide {quantity} of {asset}, send {total price} RVN to this destination"
  * These partial transaction are invalid by themselves (missing assets/rvn from one side) so must be made valid by a second party to complete
  * The partial transaction cannot be modified as it has been signed with [SIGHASH_SINGLE|SIGHASH_ANYONECANPAY]
* Due to the nature of how these orders are constructed, __a Signed Partial is indefinietly valid as long as that UTXO is__, this is why a Hard-Remove of an order is needed.
* The party setting up the order will almost

# Features (Roughly in order) #

- [x] Adding "Pro" to the name
- [x] Create Single/Bulk Buy Orders.
- [x] Create Single/Bulk Sell Orders.
- [x] Create Single/Bulk Trade Orders (exchange XX of asset A for YY of asset B)
- [x] Asset List
- [x] Soft-locking UTXO's (UTXO's setup on the buy/sell screen are locked to prevent use when setting up future UTXO's.)
- [x] [Optional/Default] Hard-Locking of UTXO's (UTXOs will appear gone and will be unspendable to core wallet.) This prevents accidental order invalidation
- [x] Soft-Remove Trade Order (Hide, but remember so it can be displayed if executed.)
- [x] Hard-Remove Trade Order (Invalidate the previous UTXO by using it in a transaction to yourself.) [Code exists but was removed with the bulk order changes]
- [x] Multiple RPC Connections

## TODO ##

- [ ] System notification on completed trade
- [ ] Proxy asset signing/reissuing. (Party `A` owns admin asset, Party `B` requests a child asset be minted/reissued/etc under `A`'s admin asset.) From the creators side, this just looks like a buy order for an asset that doesn't exist yet. 
- [x] Proper asset decimal/metadata support. (close enough)
- [ ] Available UTXO dialog (with option to manually lock/unlock? UTXO's.)
- [x] Settings menu
- [x] -- RPC Connections
- [ ] -- Preferred rvn/asset destination address (uses address pooling currently)
- [ ] -- Previous order history age (remove records after x days)
- [ ] -- Adjustable fee rate for optionally faster confirmation
- [ ] IPFS content preview

## Side-Channel Support ##

There is a companion repository [raven-trader-server](https://github.com/ben-abraham/raven-trader-server), a C# Asp.Net Core cross-platform web-server for indexing the chain for exectued swaps and providing that data via an API. This site will hopefully serve as a baseline implementation for an open standard of an api trading interface.

### Client Features ###

- [x] Post orders to API
- [x] View orders from API
- [x] Search orders from API
- [x] Purchase from API
- [ ] Preview historical asset prices on buy/sell
- [ ] Local automated purchase/sale at specific price (you are executing and therefore paying fees, but get guaranteed execution if there is an available order at a given price)

### Server Features ###

- [x] **Indexer**: Blocks, transaction count, asset volume, and swap history.
- [ ] **Indexer**: Asset metadata, full tx history.
- [x] **Indexer**: Invalidate orders on execution
- [ ] **Indexer**: Re-org detection and handling
- [x] **API**: Validate & Store swaps
- [x] **API**: Get swap history
- [x] **API**: Get active listings
- [x] **API**: Get active listings grouped by asset
- [x] **Web**: 24hr volume, recent swaps, add new swap
- [x] **API**: Detailed asset page
- [ ] **Web**: Asset list & history, omnisearch, documentation/guide
- [x] **General**: Asset <-> Asset swap support

# Process #

This application follows the [RIP-15](https://github.com/RavenProject/rips/blob/master/rip-0015.mediawiki) procedure for creating and completing 2-step swap transactions.
At a high-level the process looks like this:

1. `A` creates a partial order (buy or sell)
2. `A` announces that order over a side-channel, such as Dicord, a trading website, direct messaging or any other means
3. `B` gets the order from `A`
4. `B` verifies the order is as-advertised, and executes at-will

# Technical #

## UTXO's (Unspent Transaction Outputs) ##

This is important related information to how these trades operate.
At a high-level, all blockchain balances are stored as a collection of UTXO's. For example, if `A` sends `B` 10 RVN, B will then have a 10 RVN UTXO in his wallet, in addition to all his previous. When he goes to spend it, he must use it in it's entirety, so he might pay someone 1 RVN for goods/services, and he would then send the remaining 9 RVN (minus fees) to himself, leaving himself with an 8.99## RVN UTXO.

tl;dr: Total wallet balances are made up of individual UTXO's, UTXO's must be spent in full during a transaction, so any change is created as a new UTXO.

* The party creating the order
* The selling party must sell using a single UTXO, which in almost-all cases will require explicity setting up a UTXO to prepare a buy order.
* The buying party mu
