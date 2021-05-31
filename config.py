TESTNET = True

RPC_USERNAME = ""
RPC_PASSWORD = ""
RPC_HOST = "localhost"
RPC_POST = 18766 if TESTNET else 8766
SWAP_STORAGE_PATH = "orders.json"
LOCK_STORAGE_PATH = "locks.json"
RPC_UNLOCK_PHRASE = "" #if needed


#This controls if UTXO's are locked in your wallet. Locked UTXOs can't accidentally be spent (which would invalidate an order)
#NOTE: Locked UTXO's are NOT INCLUDED IN YOUR BALANCE or most rpc commands. they are effectively spent
#Locked UTXO's can be viewed with `listlockunspent` and unlocked with `lockunspent true` (will unlock all)
LOCK_UTXOS_IN_WALLET = True

RPC_URL = "http://{}:{}@{}:{}".format(RPC_USERNAME, RPC_PASSWORD, RPC_HOST, RPC_POST)
TX_QRY = "https://rvnt.cryptoscope.io/api/getrawtransaction/?txid={}&decode=1" if TESTNET\
    else "https://rvn.cryptoscope.io/api/getrawtransaction/?txid={}&decode=1"