from jsonrpcclient.requests import Request
from requests import post, get
from decimal import *

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5 import uic

import sys, getopt, argparse, json, time, getpass, os.path

TESTNET = True

#NOTE: Nothing with rosetta is not needed, these are just my defaults
RPC_USERNAME = "rosetta"
RPC_PASSWORD = "rosetta"
RPC_HOST = "localhost"
RPC_POST = 118766 if TESTNET else 8766
SWAP_STORAGE_PATH = "orders.json"
RPC_UNLOCK_PHRASE = "" #if needed

rpc_url = "http://{}:{}@{}:{}".format(RPC_USERNAME, RPC_PASSWORD, RPC_HOST, RPC_POST)
tx_qry = "https://rvnt.cryptoscope.io/api/getrawtransaction/?txid={}&decode=1" if TESTNET\
    else "https://rvn.cryptoscope.io/api/getrawtransaction/?txid={}&decode=1"

def do_rpc(method, log_error=True, **kwargs):
  req = Request(method, **kwargs)
  try:
    resp = post(rpc_url, json=req)
    if resp.status_code != 200:
      print("==>", end="")
      print(req)
      print("<== ERR:", end="")
      print(resp.text)
    return json.loads(resp.text)["result"]
  except:
    print("RPC Error")
    return None

def decode_full(txid):
  resp = get(tx_qry.format(txid))
  if resp.status_code != 200:
    print("Error fetching raw transaction")
  result = json.loads(resp.text)
  return result

def check_unlock(timeout = 10):
  print("Unlocking Wallet for {}s".format(timeout))
  global prompted_phrase
  phrase_test = do_rpc("help", command="walletpassphrase")
  #returns None if no password set
  if(phrase_test.startswith("walletpassphrase")):
    #if(not prompted_phrase):
      #prompted_phrase = getpass.getpass("Enter Wallet Password: ")
    do_rpc("walletpassphrase", passphrase=RPC_UNLOCK_PHRASE, timeout=timeout)

def make_transfer(name, quantity):
  return {"transfer":{name:quantity}}

def show_error(title, message, message_extra="", parent=None):
  msg = QMessageBox(parent)
  msg.setIcon(QMessageBox.Critical)

  msg.setText(message)
  if(message_extra):
    msg.setInformativeText(message_extra)
  msg.setWindowTitle(title)
  msg.setStandardButtons(QMessageBox.Ok)
	
  return msg.exec_()

def show_dialog(title, message, message_extra="", parent=None):
  msg = QMessageBox(parent)
  msg.setIcon(QMessageBox.Information)

  msg.setText(message)
  if(message_extra):
    msg.setInformativeText(message_extra)
  msg.setWindowTitle(title)
  msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
	
  return msg.exec_()

def dup_transaction(tx):
  new_vin = []
  new_vout = {}
  for old_vin in tx["vin"]:
    new_vin.append({"txid": old_vin["txid"], "vout": old_vin["vout"], "sequence": old_vin["sequence"]})
  for old_vout in tx["vout"]:
    vout_script = old_vout["scriptPubKey"]
    vout_addr = vout_script["addresses"][0]
    if(vout_script["type"] == "transfer_asset"):
      new_vout[vout_addr] = make_transfer(vout_script["asset"]["name"], vout_script["asset"]["amount"])
    else:
      new_vout[vout_addr] = old_vout["value"]
  return new_vin, new_vout

def search_swap_tx(utxo):
  utxo_parts = utxo.split("|")
  height = do_rpc("getblockcount")
  check_height = height
  while check_height >= height - 10:
    hash = do_rpc("getblockhash", height=check_height)
    details = do_rpc("getblock", blockhash=hash, verbosity=2)
    for block_tx in details["tx"]:
      for tx_vin in block_tx["vin"]:
        if "vout" in tx_vin and block_tx["txid"] == utxo_parts[0] and tx_vin["vout"] == int(utxo_parts[1]):
          return block_tx["txid"]
    check_height -= 1
  print("Unable to find transaction for completed swap")
  return None #If we don't find it 10 blocks back, who KNOWS what happened to it

def decode_swap(raw_swap):
  parsed = do_rpc("decoderawtransaction", log_error=False, hexstring=raw_swap)
  if parsed:
    if len(parsed["vin"]) != 1 or len(parsed["vout"]) != 1:
      print("Invalid Transaction. Has more than one vin/vout")
      return None
    if "SINGLE|ANYONECANPAY" not in parsed["vin"][0]["scriptSig"]["asm"]:
      print("Transaction not signed with SINGLE|ANYONECANPAY")
      return None

    src_vin = parsed["vin"][0]
    src_vout = parsed["vout"][0]

    order_type = "buy" if src_vout["scriptPubKey"]["type"] == "transfer_asset" else "sell"
    vin_tx = decode_full(src_vin["txid"])
    
    #If nothing comes back this is likely a testnet tx on mainnet of vice-versa
    if not vin_tx:
      print("Unable to find transaction. Is this for the correct network?")
      return None

    vin_vout = vin_tx["vout"][src_vin["vout"]]
    
    #Pull asset data based on order type
    if order_type == "sell":
      vout_data = src_vout["value"]
      asset_data = vin_vout["scriptPubKey"]["asset"]
      total_price = vout_data
    else:
      asset_data = src_vout["scriptPubKey"]["asset"]
      vout_data = make_transfer(asset_data["name"], asset_data["amount"])
      total_price = vin_vout["value"]

    unit_price = float(total_price) / float(asset_data["amount"])

    return SwapTransaction({
      "asset": asset_data['name'], 
      "own": False,
      "quantity": float(asset_data['amount']),
      "unit_price": unit_price,
      "utxo": src_vin["txid"] + "|" + str(src_vin["vout"]),
      "destination": src_vout["scriptPubKey"]["addresses"][0],
      "state": "new",
      "type": order_type,
      "raw": raw_swap,
      "txid": ""
    },{
      "vin": src_vin,
      "vout": src_vout,
      "src_vout": vin_vout,
      "vout_data": vout_data,
      "from_tx": vin_tx
    })
    
  else:
    print("Invalid TX")
    return None

class SwapStorage:
  def __init__ (self):
    super()
    self.swaps = []
  
  def load_swaps(self):
    global SWAP_STORAGE_PATH
    if not os.path.isfile(SWAP_STORAGE_PATH):
      return []
    fSwap = open(SWAP_STORAGE_PATH, mode="r")
    swapJson = fSwap.read()
    fSwap.close()
    self.swaps = json.loads(swapJson, object_hook=SwapTransaction)
    print("Loaded {} swaps from disk".format(len(self.swaps)))
    return self.swaps

  def load_utxos(self):
    #Locked UTXO's are excluded from the list command
    self.utxos = do_rpc("listunspent")
      
    #Pull list of assets for selecting
    self.assets = do_rpc("listmyassets", asset="", verbose=True)
    self.my_asset_names = [*self.assets.keys()]

    total_balance = 0
    for utxo in self.utxos:
      total_balance += utxo["amount"]
    self.balance = total_balance

  def find_utxo(self, type, quantity, name=None, exact=True):
    if type == "rvn":
      for rvn_utxo in self.utxos:
        if(self.is_taken(rvn_utxo)):
          continue
        if(float(rvn_utxo["amount"]) == float(quantity) and exact) or (rvn_utxo["amount"] >= quantity and not exact):
          return rvn_utxo
    elif type == "asset":
      matching_asset = self.assets[name]
      if(matching_asset):
        if(matching_asset["balance"] < quantity):
          return None
        for asset_utxo in matching_asset["outpoints"]:
          if(self.is_taken(asset_utxo)):
            continue
          if(float(asset_utxo["amount"]) == float(quantity) and exact) or (asset_utxo["amount"] >= quantity and not exact):
            return asset_utxo
    return None

  #check if a swap's utxo is still unspent
  #if not then the swap has been executed!
  def swap_utxo_unspent(self, utxo):
    utxo_parts = utxo.split("|")
    for utxo in self.utxos:
      if utxo["txid"] == utxo_parts[0] and utxo["vout"] == int(utxo_parts[1]):
        return True
    for asset_name in self.my_asset_names:
      for a_utxo in self.assets[asset_name]["outpoints"]:
        if a_utxo["txid"] == utxo_parts[0] and a_utxo["vout"] == int(utxo_parts[1]):
          return True
    return False

  def wallet_lock_all_swaps(self):
    #first unlock everything
    self.wallet_unlock_all()
    #now build all orders and send it in one go
    locked_utxos = []
    for swap in self.swaps:
      if swap.state == "new":
        utxo_parts = swap.utxo.split("|")
        locked_utxos.append({"txid":utxo_parts[0],"vout":int(utxo_parts[1])})
    print("Locking {} UTXO's for buy orders".format(len(locked_utxos)))
    do_rpc("lockunspent", unlock=False, transactions=locked_utxos)
  
  def wallet_lock_single(self, swap):
    utxo_parts = swap.utxo.split("|")
    lock_utxo = [{"txid":utxo_parts[0],"vout":int(utxo_parts[1])}]
    do_rpc("lockunspent", unlock=False, transactions=lock_utxo)

  def wallet_unlock_all(self):
    do_rpc("lockunspent", unlock=True)

  def is_taken(self, utxo):
    for swap in self.swaps:
      expected = "{}|{}".format(utxo["txid"], utxo["vout"])
      if swap.utxo == expected:
        return True
    return False

  def locaked_rvn(self):
    total = 0
    for swap in self.swaps:
      if swap.type == "buy" and swap.state == "new":
        total += swap.totalPrice()
    return total

  def locaked_assets(self):
    total = 0
    for swap in self.swaps:
      if swap.type == "sell" and swap.state == "new":
        total += swap.quantity
    return total

  def add_swap(self, swap):
    self.swaps.append(swap)

  def save_swaps(self):
    global SWAP_STORAGE_PATH
    fSwap = open(SWAP_STORAGE_PATH, mode="w")
    fSwap.truncate()
    json.dump(self.swaps, fSwap, default=lambda o: o.__dict__, indent=2)
    fSwap.flush()
    fSwap.close()



class SwapTransaction():
  def __init__(self, dict, decoded=None):
    self.decoded = decoded
    vars(self).update(dict)

  def totalPrice(self):
    return self.quantity * self.unit_price

  #This is run by Alice when she wants to create an order
  def sign_partial(self):
    utxo_parts = self.utxo.split("|")
    vin = {"txid":utxo_parts[0], "vout":int(utxo_parts[1]), "sequence":0}
    vout = {self.destination: make_transfer(self.asset, self.quantity)} if self.type == "buy"\
      else {self.destination: self.totalPrice()}

    check_unlock()

    raw_tx = do_rpc("createrawtransaction", inputs=[vin], outputs=vout)

    #TODO: Better user interaction here
    print("Signing Partial Transaction")
    signed_raw = do_rpc("signrawtransaction", hexstring=raw_tx, prevtxs=None, privkeys=None, sighashtype="SINGLE|ANYONECANPAY")
    print("Done!")

    self.raw = signed_raw["hex"]
    return self.raw

  #This is run by Bob when he wants to complete an order
  def complete_order(self, swap_storage):
    final_vin = [{"txid":self.decoded["vin"]["txid"], "vout":self.decoded["vin"]["vout"], "sequence":self.decoded["vin"]["sequence"]}]
    final_vout = {self.decoded["vout"]["scriptPubKey"]["addresses"][0]:self.decoded["vout_data"]}

    tx_allowed = False
    tx_final = None

    #Check for unlock here and for extended duration because the fee checks are jenky and can take time
    check_unlock(240)

    if self.type == "sell":
      #Sale order means WE are purchasing
      print("Completing Sale of {} x [{}] for {} RVN".format(self.quantity, self.asset, self.totalPrice()))


      #Add our destination for assets
      final_vout[self.destination] = make_transfer(self.asset, self.quantity)

      #Build final combined raw transaction
      final_raw = do_rpc("createrawtransaction", inputs=final_vin, outputs=final_vout)

      #Fund the transaction, this will cover both the purchase debit and any fees
      funded_tx = do_rpc("fundrawtransaction", hexstring=final_raw, options={'changePosition':1})

      funded_dec = do_rpc("decoderawtransaction", hexstring=funded_tx["hex"])
      funded_vin, funded_vout = dup_transaction(funded_dec)
      vout_keys = [*funded_vout.keys()]

      estimated_fee = 0.01 * len(funded_tx["hex"]) / 2 / 1024 #2 hex chars = 1 byte

      calculated_change = funded_vout[vout_keys[1]] 
      fee_test = calculated_change - estimated_fee

      #Jenky AF, no great way to estimate raw fee from rpc, so lower and test in mempool until good
      while fee_test > 0:
        funded_vout[vout_keys[1]] = round(fee_test, 8)

        dup_funded = do_rpc("createrawtransaction", inputs=funded_vin, outputs=funded_vout)

        #Merge the signed tx from the original order
        combined_raw = do_rpc("combinerawtransaction", txs=[dup_funded, self.raw])

        #Sign the final transaction
        signed_final = do_rpc("signrawtransaction", hexstring=combined_raw)
        signed_hex = signed_final["hex"]
        
        mem_accept = do_rpc("testmempoolaccept", rawtxs=[signed_hex])

        if(mem_accept and mem_accept[0]["allowed"]):
          print("Accepted to mempool!")
          tx_allowed = True
          tx_final = signed_hex
          break
        elif(mem_accept and mem_accept[0]["reject-reason"]=="66: min relay fee not met"):
          fee_test -= 0.0001
        else:
          print(mem_accept)
          print("Raw")
          print(combined_raw)
          print("Signed")
          print(signed_final)
          print("!!Error!!")
          break
    elif self.type == "buy":
      #Buy order means WE are selling
      print("Completing Sale of {} x [{}] for {} RVN".format(self.quantity, self.asset, self.totalPrice()))
      
      #Search for valid UTXO, no need for exact match
      asset_utxo = swap_storage.find_utxo("asset", self.quantity, name=self.asset, exact=False)
      if(not asset_utxo):
        print("Unable to find a single UTXO for purchasing. Does not combine automatically yet")
        exit()

      #Add our asset input
      final_vin.append({"txid":asset_utxo["txid"], "vout":asset_utxo["vout"]})

      #NOTE: self.destination is where the assets are going, not our wallet
      #hence the call to getnewaddress
      target_addr = do_rpc("getnewaddress")
      print("Funds are being sent to {}".format(target_addr))

      #Add asset change if needed
      if(asset_utxo["amount"] > self.quantity):
        asset_change_addr = do_rpc("getnewaddress")
        print("Asset change being sent to {}".format(asset_change_addr))
        final_vout[asset_change_addr] = make_transfer(self.asset, asset_utxo["amount"] - self.quantity)
      
      final_vout[target_addr] = 0

      print("Final Vin: ", final_vin)
      print("Final Vout: ", final_vout)
        
      test_create = do_rpc("createrawtransaction", inputs=final_vin, outputs=final_vout)
      estimated_fee = 0.01 * len(test_create) / 2 / 1024 #2 hex chars = 1 byte

      fee_test = float(self.decoded["src_vout"]["value"]) - estimated_fee

      #Jenky AF, no great way to estimate raw fee from rpc, so lower and test in mempool until good
      while fee_test > 0:
        final_vout[target_addr] = round(fee_test, 8)

        #Build final combined raw transaction
        final_raw = do_rpc("createrawtransaction", inputs=final_vin, outputs=final_vout)
        
        #Merge the signed tx from the original order
        combined_raw = do_rpc("combinerawtransaction", txs=[final_raw, self.raw])
        
        #Sign our part with our keys
        signed_raw = do_rpc("signrawtransaction", hexstring=combined_raw)
        signed_hex = signed_raw["hex"]

        mem_accept = do_rpc("testmempoolaccept", rawtxs=[signed_hex])

        if(mem_accept and mem_accept[0]["allowed"]):
          print("Accepted to mempool!")
          tx_allowed = True
          tx_final = signed_hex
          break
        elif(mem_accept and mem_accept[0]["reject-reason"]=="66: min relay fee not met"):
          fee_test -= 0.0001
        else:
          print(mem_accept)
          print("Test Create")
          print(test_create)
          print("Final Raw")
          print(final_raw)
          print("!!Error!!")
          break

    #remove this so it doesn't get encoded to json later
    del(self.decoded)
    return tx_final





class QTwoLineRowWidget (QWidget):
  def __init__ (self, parent = None):
    super(QTwoLineRowWidget, self).__init__(parent)
    self.textQVBoxLayout = QVBoxLayout()
    self.textUpQLabel    = QLabel()
    self.textDownQLabel  = QLabel()
    self.textQVBoxLayout.addWidget(self.textUpQLabel)
    self.textQVBoxLayout.addWidget(self.textDownQLabel)
    self.allQHBoxLayout  = QHBoxLayout()
    self.iconQLabel      = QLabel()
    self.allQHBoxLayout.addWidget(self.iconQLabel, 0)
    self.allQHBoxLayout.addLayout(self.textQVBoxLayout, 1)
    self.setLayout(self.allQHBoxLayout)
    # setStyleSheet
    self.textUpQLabel.setStyleSheet('''
        color: rgb(0, 0, 255);
    ''')
    self.textDownQLabel.setStyleSheet('''
        color: rgb(255, 0, 0);
    ''')
   

  @staticmethod
  def from_swap(swap, **kwargs):
    row = QTwoLineRowWidget()
    row.swap = swap
    if swap.type == "buy":
      row.setTextUp("{} {:.8g}x [{}] for {:.8g} RVN ({:.8g} each)".format(
        "Buy" if swap.own else "Sold", swap.quantity, swap.asset, swap.totalPrice(), swap.unit_price))
    else:
      row.setTextUp("{} {:.8g}x [{}] for {:.8g} RVN ({:.8g} each)".format(
        "Sell" if swap.own else "Bought", swap.quantity, swap.asset, swap.totalPrice(), swap.unit_price))
    if swap.state != "new":
      if not swap.own:
        row.setTextDown("Completed: {}".format(swap.txid))
      else:
        row.setTextDown("Executed: {}".format(swap.txid))
    return row

  @staticmethod
  def from_vout(vout, ismine):
    row = QTwoLineRowWidget()
    row.vout = vout
    row.ismine = ismine
    
    spk = vout["scriptPubKey"]

    if(spk["type"] == "transfer_asset"):
      row.setTextUp("{}x [{}]".format(spk["asset"]["amount"],spk["asset"]["name"]))
    else:
      row.setTextUp("{} RVN".format(row.vout["value"]))
    
    if(ismine):
      row.setTextDown("** {}".format(spk["addresses"][0]))
    else:  
      row.setTextDown(spk["addresses"][0])

    return row

  def getSwap (self):
    return self.swap

  def setTextUp (self, text):
    self.textUpQLabel.setText(text)

  def setTextDown (self, text):
    self.textDownQLabel.setText(text)

  def setIcon (self, imagePath):
    self.iconQLabel.setPixmap(QPixmap(imagePath))


class PreviewTransactionDialog(QDialog):
  def __init__(self, partial_swap, final_swap, swap_storage, parent=None, **kwargs):
    super().__init__(parent, **kwargs)
    uic.loadUi("previeworder.ui", self)
    self.swap = partial_swap
    self.setWindowTitle("Confirm Transaction [2/2]")
    self.txtRawFinal.setText(final_swap)

    decoded = do_rpc("decoderawtransaction", hexstring=final_swap)
    
    for vin in decoded["vin"]:
      #Have to use explorer API here because there is no guarantee that these transactions are local
      #vin_tx = do_rpc("getrawtransaction", txid=vin["txid"], verbose=True)
      vin_tx = decode_full(vin["txid"])
      src_vout = vin_tx["vout"][vin["vout"]]
      src_addr = src_vout["scriptPubKey"]["addresses"][0]
      is_my_utxo = False
      
      for my_utxo in swap_storage.utxos:
        if my_utxo["txid"] == vin["txid"] and my_utxo["vout"] == vin["vout"]:
          is_my_utxo = True
          break
      for my_asset in swap_storage.my_asset_names:
        for my_a_utxo in swap_storage.assets[my_asset]["outpoints"]:
          if my_a_utxo["txid"] == vin["txid"] and my_a_utxo["vout"] == vin["vout"]:
            is_my_utxo = True
            break
      
      self.add_swap_item(self.lstInputs, src_vout, is_my_utxo)

    for vout in decoded["vout"]:
      vout_addr = vout["scriptPubKey"]["addresses"][0]
      addr_check = do_rpc("validateaddress", address=vout_addr)
      is_my_out = addr_check["ismine"]
      
      self.add_swap_item(self.lstOutputs, vout, is_my_out)

  def add_swap_item(self, list, vout, mine):
    voutListWidget = QTwoLineRowWidget.from_vout(vout, mine)
    voutListItem = QListWidgetItem(list)
    voutListItem.setSizeHint(voutListWidget.sizeHint())
    list.addItem(voutListItem)
    list.setItemWidget(voutListItem, voutListWidget)

    


class OrderDetailsDialog(QDialog):
  def __init__(self, swap, swap_storage, parent=None, complete_mode=None, **kwargs):
    super().__init__(parent, **kwargs)
    uic.loadUi("orderdetails.ui", self)
    self.swap = swap
    self.swap_storage = swap_storage
    self.complete_mode = complete_mode

    if not self.complete_mode:
      self.setWindowTitle("Order Details")
      self.update_for_swap(self.swap)
      self.txtSigned.setText(self.swap.raw)
    else:
      self.setWindowTitle("Preview Completion [1/2]")
      #Allow user to edit and register listener for changes
      self.txtSigned.setReadOnly(False)
      self.txtSigned.textChanged.connect(self.raw_tx_changed)
      self.buttonBox.removeButton(self.buttonBox.button(QDialogButtonBox.Ok))
      self.confirm_button = self.buttonBox.addButton("Confirm", QDialogButtonBox.AcceptRole)

  def update_for_swap(self, swap):
    self.lblAsset.setText(swap.asset)
    self.lblQuantity.setText(str(swap.quantity))
    self.lblUnitPrice.setText("{:.8g} RVN".format(swap.unit_price))
    self.lblType.setText(swap.type)
    self.lblUTXO.setText(swap.utxo)
    self.lblTotalPrice.setText("{:.8g} RVN".format(swap.totalPrice()))
    self.txtDestination.setText(swap.destination)

  def swap_error(self):
    #Sell order means we are buying
    if self.swap.type == "sell":
      if self.swap.totalPrice() > self.swap_storage.balance:
        return "You don't have enough RVN to purchase."
    else:
      if self.swap.asset not in self.swap_storage.my_asset_names:
        return "You don't own that asset."
      if self.swap.quantity > self.swap_storage.assets[self.swap.asset]["balance"]:
        return "You don't own enough of that asset."

  def raw_tx_changed(self):
    if not self.complete_mode:
      return

    parsed = decode_swap(self.txtSigned.toPlainText())
    if parsed:
      self.swap = parsed
      self.update_for_swap(self.swap)
      err = self.swap_error()
      if err:
        show_error("Error!", err, parent=self)
        self.confirm_button.setVisible(False)
      else:
        self.confirm_button.setVisible(True)

    self.confirm_button.setEnabled(self.swap is not None)

  def build_order(self):
    return self.swap



class NewOrderDialog(QDialog):
  def __init__(self, mode, swap_storage, parent=None, **kwargs):
    super().__init__(parent, **kwargs)
    uic.loadUi("neworder.ui", self)
    self.mode = mode
    self.swap_storage = swap_storage
    if(self.mode != "buy" and self.mode != "sell"):
      raise "Invalid Order Mode"
    
    self.swap_storage.load_utxos()
    self.waiting_txid = None
    self.asset_exists = True

    if self.mode == "buy":
      self.setWindowTitle("New Buy Order")
      self.cmbAssets.setEditable(True)
      self.spinQuantity.setEnabled(False)
      self.btnCheckAvailable.clicked.connect(self.check_available)
      self.cmbAssets.currentTextChanged.connect(self.asset_changed)
    else:
      self.setWindowTitle("New Sell Order")
      self.cmbAssets.setEditable(False)
      self.cmbAssets.addItems(["{} [{}]".format(v, self.swap_storage.assets[v]["balance"]) for v in swap_storage.my_asset_names])
      self.btnCheckAvailable.setVisible(False)

    self.cmbAssets.currentIndexChanged.connect(self.update)
    self.spinQuantity.valueChanged.connect(self.update)
    self.spinUnitPrice.valueChanged.connect(self.update)
    self.btnCreateUTXO.clicked.connect(self.create_utxo)
    self.lblWhatUTXO.mousePressEvent = self.show_utxo_help #apparently this even is jenky?
    self.update()

  def show_utxo_help(self, *args):
    show_dialog("UTXO Explanation", 
    "Blockchain balances are comprised of the sum of many individual unspent transaction outputs (UTXO's). "+
      "These can be of any quantity/denomination, but ALL of it must be spent in whole during a transaction. "+
      "Any leftovers are returned to another address as change",
    "To construct a one-sided market order, you must have a single UTXO of the exact amount you would like to advertise.",
    parent=self)

  def check_available(self):
    #TODO: Save this asset data for later
    details = do_rpc("getassetdata", asset_name=self.cmbAssets.currentText())
    self.asset_exists = True if details else False
    self.btnCheckAvailable.setEnabled(False)
    if self.asset_exists:
      self.spinQuantity.setEnabled(True)
      self.btnCheckAvailable.setText("Yes! - {} total".format(details["amount"]))
      self.spinQuantity.setMaximum(float(details["amount"]))
    else:
      self.spinQuantity.setEnabled(False)
      self.btnCheckAvailable.setText("No!")
    self.update()

  def asset_changed(self):
    self.asset_exists = False
    self.btnCheckAvailable.setText("Check Available")
    self.btnCheckAvailable.setEnabled(True)

  def create_utxo(self):
    summary = "Send yourself {} to costruct a {} order?"  

    if self.mode == "buy":
      summary = summary.format("{:.8g} RVN".format(self.total_price), self.mode)
    elif self.mode == "sell":
      summary = summary.format("{:.8g}x [{}]".format(self.quantity, self.asset_name), self.mode)

    if(show_dialog("Are you sure?", "This involves sending yourself an exact amount of RVN/Assets to produce the order. This wil encur a smal transaction fee", summary, self)):
      #This makes sure all known swaps UTXO's are locked and won't be used when a transfer is requested
      #Could also smart-lock even-valued UTXO's but that's a whole thing...
      self.swap_storage.wallet_lock_all_swaps()

      try:
        if self.mode == "buy":
          print("Creating self RVN transaction")
          check_unlock()

          new_change_addr = do_rpc("getnewaddress")
          self.waiting_txid = do_rpc("sendtoaddress", address=new_change_addr, amount=self.total_price)
        elif self.mode == "sell":
          print("Creating self asset transaction")
          check_unlock()

          new_change_addr = do_rpc("getnewaddress")
          rvn_change_addr = do_rpc("getnewaddress")
          asset_change_addr = do_rpc("getnewaddress")
          transfer_self_txid = do_rpc("transfer", asset_name=self.asset_name, 
                    to_address=new_change_addr, qty=self.quantity, message="",
                    change_address=rvn_change_addr, asset_change_address=asset_change_addr)

          self.waiting_txid = transfer_self_txid[0]
      finally:
        #Unlock everything when done, locking causes too many problems.
        self.swap_storage.wallet_unlock_all()

      if(self.waiting_txid):
        show_dialog("Success!", "Transaction {} submitted successfully.".format(self.waiting_txid), "Waiting for confirmation")
        self.start_waiting()
        self.wait_timer()
      else:
        show_dialog("Error", "Transaction not submitted. Check logs")

      self.update()

  def start_waiting(self):
    if hasattr(self, "udpateTimer") and self.updateTimer:
      self.updateTimer.stop()

    self.wait_count = 0
    self.updateTimer = QTimer(self)
    self.updateTimer.timeout.connect(self.wait_timer)
    self.updateTimer.start(5 * 1000)

  def wait_timer(self):
    tx_status = do_rpc("getrawtransaction", txid=self.waiting_txid, verbose=True)
    confirmed = tx_status["confirmations"] >= 1 if "confirmations" in tx_status else False
    if confirmed:
      print("UTXO Setup Confirmed!")
      self.waiting_txid = None
      self.btnCreateUTXO.setText("Create Order UTXO")
      self.updateTimer.stop()
      self.updateTimer = None
      self.swap_storage.load_utxos() #need to re-load UTXO's to find the new one
      self.update()
    else:
      self.wait_count = (self.wait_count + 1) % 5
      self.btnCreateUTXO.setText("Waiting on confirmation" + ("." * self.wait_count))
      
  def update(self):
    #Read GUI
    self.quantity = self.spinQuantity.value()
    self.price = self.spinUnitPrice.value()
    self.destination = self.txtDestination.text()
    self.total_price = self.quantity * self.price
    self.valid_order = True
    if self.mode == "buy":
      self.asset_name = self.cmbAssets.currentText()
      self.order_utxo = self.swap_storage.find_utxo("rvn", self.total_price)
      self.chkUTXOReady.setText("UTXO Ready ({:.8g} RVN)".format(self.total_price))
      #don't have enough rvn for the order
      if self.total_price > self.swap_storage.balance:
        self.valid_order = False
    else:
      self.asset_name = self.swap_storage.my_asset_names[self.cmbAssets.currentIndex()]
      self.order_utxo = self.swap_storage.find_utxo("asset", self.quantity, name=self.asset_name)
      self.chkUTXOReady.setText("UTXO Ready ({:.8g}x [{}])".format(self.quantity, self.asset_name))
      #Don't own the asset or enough of it
      if self.asset_name not in self.swap_storage.my_asset_names or self.quantity > self.swap_storage.assets[self.asset_name]["balance"]:
        self.valid_order = False

    #Not valid while waiting on a tx to confirm or if asset hasn't been confirmed yet
    if self.waiting_txid or not self.asset_exists:
      self.valid_order = False

    #valid_order check doesn't cover UTXO existing b/c valid_order determins if we enable the UTXO button or not
    #Update GUI
    self.lblTotalDisplay.setText("{:.8g} RVN".format(self.total_price))
    self.chkUTXOReady.setChecked(self.order_utxo is not None)
    if self.waiting_txid:
      self.btnCreateUTXO.setEnabled(False)
    else:
      self.btnCreateUTXO.setEnabled(self.order_utxo is None)
    #Hide the button if we don't have a valid order
    if self.order_utxo and self.valid_order:
      self.btnDialogButtons.setStandardButtons(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
    else:
      self.btnDialogButtons.setStandardButtons(QDialogButtonBox.Cancel)

  def build_order(self):
    return SwapTransaction({
      "asset": self.asset_name, 
      "own": True,
      "quantity": self.quantity,
      "unit_price": self.price,
      "utxo": self.order_utxo["txid"] + "|" + str(self.order_utxo["vout"]),
      "destination": self.destination,
      "state": "new",
      "type": self.mode,
      "raw": "--",
      "txid": ""
    })



class MainWindow(QMainWindow):
  def __init__(self, storage, *args, **kwargs):
    super().__init__(*args, **kwargs)
    uic.loadUi("mainwindow.ui", self)
    self.setWindowTitle("Raven Trader Pro")

    self.swap_storage = storage

    self.btnNewBuyOrder.clicked.connect(self.new_buy_order)
    self.btnNewSellOrder.clicked.connect(self.new_sell_order)
    self.btnCompleteOrder.clicked.connect(self.complete_order)

    self.lstBuyOrders.itemDoubleClicked.connect(self.view_order_details)
    self.lstSellOrders.itemDoubleClicked.connect(self.view_order_details)

    self.updateTimer = QTimer(self)
    self.updateTimer.timeout.connect(self.mainWindowUpdate)
    self.updateTimer.start(10 * 1000)
    self.mainWindowUpdate()

  def new_buy_order(self):
    buy_dialog = NewOrderDialog("buy", self.swap_storage, parent=self)
    if(buy_dialog.exec_()):
      buy_swap = buy_dialog.build_order()
      if not buy_swap.destination:
        buy_swap.destination = do_rpc("getnewaddress")

      buy_swap.sign_partial()
      print("New Buy: ", json.dumps(buy_swap.__dict__))
      self.swap_storage.add_swap(buy_swap)
      self.swap_storage.save_swaps()
      self.update_lists()
      details = OrderDetailsDialog(buy_swap, self.swap_storage, parent=self)
      details.exec_()

  def new_sell_order(self):
    sell_dialog = NewOrderDialog("sell", self.swap_storage, parent=self)
    if(sell_dialog.exec_()):
      sell_swap = sell_dialog.build_order()
      if not sell_swap.destination:
        sell_swap.destination = do_rpc("getnewaddress")

      sell_swap.sign_partial()
      print("New Sell: ", json.dumps(sell_swap.__dict__))
      self.swap_storage.add_swap(sell_swap)
      self.swap_storage.save_swaps()
      self.update_lists()
      details = OrderDetailsDialog(sell_swap, self.swap_storage, parent=self)
      details.exec_()

  def complete_order(self):
    order_dialog = OrderDetailsDialog(None, self.swap_storage, complete_mode=True, parent=self)
    if(order_dialog.exec_()):
      partial_swap = order_dialog.build_order()
      finished_swap = partial_swap.complete_order(self.swap_storage)
      #print("Swap: ", json.dumps(partial_swap.__dict__))
      #print(finished_swap)
      
      preview_dialog = PreviewTransactionDialog(partial_swap, finished_swap, self.swap_storage, parent=self)

      if(preview_dialog.exec_()):
        print("Transaction Approved. Sending!")
        submitted_txid = do_rpc("sendrawtransaction", hexstring=finished_swap)
        partial_swap.txid = submitted_txid
        partial_swap.state = "completed"
        #Add a completed swap to the list.
        #it's internally tracked from an external source
        self.swap_storage.add_swap(partial_swap)

      else:
        print("Transaction Rejected")


  def view_order_details(self, widget):
    list = widget.listWidget()
    swap_row = list.itemWidget(widget)
    details = OrderDetailsDialog(swap_row.getSwap(), self.swap_storage, parent=self)
    details.exec_()
    
  def clear_list(self, list):
    for row in range(0, list.count()):
      list.takeItem(0) #keep removing idx 0

  def mainWindowUpdate(self):
    self.swap_storage.load_utxos()

    asset_total = 0
    for asset_name in self.swap_storage.my_asset_names:
      asset_total += self.swap_storage.assets[asset_name]["balance"]

    avail_balance = self.swap_storage.balance - self.swap_storage.locaked_rvn()
    avail_assets = asset_total - self.swap_storage.locaked_assets()

    self.lblBalanceTotal.setText("Total Balance: {:.8g} RVN [{:.8g} Assets]".format(self.swap_storage.balance, asset_total))
    self.lblBalanceAvailable.setText("Total Available: {:.8g} RVN [{:.8g} Assets]".format(avail_balance, avail_assets))
    self.update_lists()

  def update_lists(self):
    #Check for state changes, by looking over UTXO's
    for swap in self.swap_storage.swaps:
      if swap.state == "new" and swap.own:
        #if its no longer unspent, the swap has been executed
        #and this should be moved to completed
        if not self.swap_storage.swap_utxo_unspent(swap.utxo):
          swap_txid = search_swap_tx(swap.utxo)
          print("Swap Completed! txid: ", swap_txid)
          swap.state = "completed"
          swap.txid = swap_txid
          self.swap_storage.save_swaps()

    self.clear_list(self.lstBuyOrders)
    self.clear_list(self.lstSellOrders)
    self.clear_list(self.lstPastOrders)

    for swap in self.swap_storage.swaps:
      if swap.state == "new":
        if swap.type == "buy":
          self.add_swap_item(self.lstBuyOrders, swap)
        else:
          self.add_swap_item(self.lstSellOrders, swap)
      else:
        self.add_swap_item(self.lstPastOrders, swap)

  def add_swap_item(self, list, swap_details):
    swapListWidget = QTwoLineRowWidget.from_swap(swap_details)
    swapListItem = QListWidgetItem(list)
    swapListItem.setSizeHint(swapListWidget.sizeHint())
    list.addItem(swapListItem)
    list.setItemWidget(swapListItem, swapListWidget)
    
chain_info = do_rpc("getblockchaininfo")
app = QApplication(sys.argv)

if chain_info:
  swap_storage = SwapStorage()
  swap_storage.load_swaps()
  swap_storage.load_utxos()

  window = MainWindow(swap_storage)
  window.show()
  app.exec_()

  swap_storage.save_swaps()
else:
  show_error("Error connecting", 
  "Error connecting to RPC server.\r\n{}".format(rpc_url), 
  "Make sure the following configuration variables are in your raven.conf file"+
  "\r\n\r\nserver=1\r\nrpcuser={}\r\nrpcpassword={}".format(RPC_USERNAME, RPC_PASSWORD))

  