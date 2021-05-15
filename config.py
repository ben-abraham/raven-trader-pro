TESTNET = True

RPC_USERNAME = ""
RPC_PASSWORD = ""
RPC_HOST = "localhost"
RPC_POST = 18766 if TESTNET else 8766
SWAP_STORAGE_PATH = "orders.json"
RPC_UNLOCK_PHRASE = "" #if needed

RPC_URL = "http://{}:{}@{}:{}".format(RPC_USERNAME, RPC_PASSWORD, RPC_HOST, RPC_POST)
TX_QRY = "https://rvnt.cryptoscope.io/api/getrawtransaction/?txid={}&decode=1" if TESTNET\
    else "https://rvn.cryptoscope.io/api/getrawtransaction/?txid={}&decode=1"